"""Manage only this checkout's recorded local uvicorn processes on Windows."""
from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
PYTHON = Path(sys.executable).absolute()
LOG_DIR = Path(os.environ.get("GONGWEI_LOG_DIR") or ROOT / "logs").absolute()
STATE_PATH = LOG_DIR / "stage2-services.json"
SERVICE_DEFINITIONS = (
    ("RESOURCE", 18012, "resource_partner_v1:app", "partner", "stage2-gongwei-resource"),
    ("WORKORDER", 18013, "work_order_partner_v1:app", "partner", "stage2-gongwei-work-order"),
    ("AUDIO", 18014, "audio_partner_v1:app", "partner", "stage2-gongwei-audio"),
    ("LEADER", 18010, "web_app:app", "service", "stage2-leader"),
)


def configured_services() -> list[dict]:
    result = []
    for role, default, module, key, value in SERVICE_DEFINITIONS:
        name = f"GONGWEI_STAGE2_{role}_PORT"
        try:
            port = int(os.environ.get(name, str(default)))
        except ValueError as exc:
            raise ValueError(f"{name} 必须是有效端口。") from exc
        if not 1 <= port <= 65535:
            raise ValueError(f"{name} 必须在 1 至 65535 之间。")
        if any(row["port"] == port for row in result):
            raise ValueError(f"服务端口重复：{port}")
        result.append({"role": role.lower(), "port": port, "module": module,
                       "health_key": key, "health_value": value})
    return result


def command_for(spec: dict) -> list[str]:
    return [str(PYTHON), "-u", "-m", "uvicorn", spec["module"], "--app-dir", str(ROOT),
            "--host", "127.0.0.1", "--port", str(spec["port"])]


def process_info(pid: int) -> dict | None:
    script = (
        "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new(); "
        f"$p=Get-CimInstance Win32_Process -Filter 'ProcessId = {int(pid)}' -ErrorAction Stop; "
        "if($p){[pscustomobject]@{pid=[int]$p.ProcessId; executable=$p.ExecutablePath; "
        "command=$p.CommandLine; created=$p.CreationDate.ToUniversalTime().ToString('o')} | ConvertTo-Json -Compress}"
    )
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                            capture_output=True, encoding="utf-8", check=True, timeout=15,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    return json.loads(result.stdout.lstrip("\ufeff")) if result.stdout.strip() else None


def same_process(record: dict, actual: dict | None) -> bool:
    return bool(actual and all(record.get(key) == actual.get(key) and record.get(key)
                               for key in ("pid", "executable", "command", "created")))


def healthy(spec: dict, payload: dict) -> bool:
    return payload.get("status") == "ok" and payload.get(spec["health_key"]) == spec["health_value"]


def check_health(spec: dict) -> bool:
    try:
        with build_opener(ProxyHandler({})).open(f"http://127.0.0.1:{spec['port']}/health", timeout=2) as response:
            return healthy(spec, json.load(response))
    except (OSError, ValueError):
        return False


def port_is_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            return True
    except OSError:
        return False


def read_state() -> list[dict]:
    if not STATE_PATH.exists():
        return []
    saved = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    if saved.get("root") != str(ROOT) or not isinstance(saved.get("processes"), list):
        raise ValueError("进程记录不属于当前项目，拒绝操作。")
    return saved["processes"]


def save_state(rows: list[dict]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps({"root": str(ROOT), "processes": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(STATE_PATH)


def owned_record(row: dict) -> bool:
    return (row.get("module") in {item[2] for item in SERVICE_DEFINITIONS}
            and row.get("executable") == str(PYTHON)
            and row.get("command") == subprocess.list2cmdline(command_for(row)))


def terminate_process(row: dict) -> None:
    # Hold the process handle while verifying identity so PID reuse cannot kill
    # a different process between the check and TerminateProcess.
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    handle = kernel.OpenProcess(0x0001 | 0x1000 | 0x00100000, False, int(row["pid"]))
    if not handle:
        raise OSError(ctypes.get_last_error(), "无法打开记录的进程")
    try:
        if not owned_record(row) or not same_process(row, process_info(row["pid"])):
            raise RuntimeError(f"PID {row['pid']} 身份变化，拒绝停止。")
        if not kernel.TerminateProcess(handle, 0):
            raise OSError(ctypes.get_last_error(), "停止进程失败")
        if kernel.WaitForSingleObject(handle, 5000) != 0:
            raise RuntimeError(f"PID {row['pid']} 未在时限内退出。")
    finally:
        kernel.CloseHandle(handle)


def stop_services() -> int:
    rows = read_state()
    remaining = []
    for row in reversed(rows):
        try:
            actual = process_info(row["pid"])
            if actual is None:
                continue
            if not owned_record(row) or not same_process(row, actual):
                raise RuntimeError(f"PID {row['pid']} 不再匹配本项目记录，未停止。")
            terminate_process(row)
            print(f"Stopped {row['module']} on {row['port']}.")
        except Exception as exc:
            print(str(exc), file=sys.stderr)
            remaining.append(row)
    if rows:
        save_state(list(reversed(remaining)))
    if not rows:
        print("No recorded local services. Existing listeners were left untouched.")
    return 1 if remaining else 0


def start_services() -> int:
    specs = configured_services()
    existing = read_state()
    if existing:
        if len(existing) == len(specs) and all(
            row.get("module") == spec["module"] and row.get("port") == spec["port"]
            and owned_record(row) and same_process(row, process_info(row["pid"])) and check_health(spec)
            for row, spec in zip(existing, specs)
        ):
            print("All recorded local services are healthy.")
            return 0
        print("已有进程记录需要核查。请先运行 stop_stage2.cmd；未启动其他进程。", file=sys.stderr)
        return 1
    for spec in specs:
        if port_is_open(spec["port"]):
            print(f"端口 {spec['port']} 已被未受此启动器管理的进程占用，未启动或停止任何进程。", file=sys.stderr)
            return 1
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    current = None
    try:
        for spec in specs:
            command = command_for(spec)
            with (LOG_DIR / f"stage2_runtime_{spec['role']}.log").open("ab") as log:
                current = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL,
                                           stdout=log, stderr=subprocess.STDOUT,
                                           creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)
            actual = process_info(current.pid)
            row = {**spec, **(actual or {})}
            if not actual or not owned_record(row):
                raise RuntimeError(f"{spec['module']} 启动后无法核实项目进程身份。")
            rows.append(row)
            save_state(rows)
            deadline = time.monotonic() + 30
            while current.poll() is None and time.monotonic() < deadline:
                if check_health(spec):
                    print(f"Healthy {spec['module']} on {spec['port']}.")
                    break
                time.sleep(0.25)
            else:
                raise RuntimeError(f"{spec['module']} 健康检查失败，请查看 {LOG_DIR} 中的启动日志。")
            current = None
    except (Exception, KeyboardInterrupt) as exc:
        print(str(exc) or "启动已取消。", file=sys.stderr)
        if current is not None and current.poll() is None:
            # Popen owns the exact child handle, not an arbitrary port/PID.
            current.terminate()
            current.wait(timeout=5)
        stop_services()
        return 1
    print(f"Local services are healthy. Open http://127.0.0.1:{specs[-1]['port']}/")
    return 0


def main() -> int:
    if os.name != "nt" or len(sys.argv) != 2 or sys.argv[1] not in {"start", "stop"}:
        print("Windows usage: local_services.py start|stop", file=sys.stderr)
        return 2
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    lock = STATE_PATH.with_suffix(".lock")
    try:
        with lock.open("x", encoding="utf-8") as stream:
            stream.write(str(os.getpid()))
    except FileExistsError:
        print(f"已有启动/停止操作，或上次操作中断遗留锁：{lock}", file=sys.stderr)
        return 1
    try:
        return start_services() if sys.argv[1] == "start" else stop_services()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        lock.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
