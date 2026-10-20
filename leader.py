"""Send real local AIP calls through the official SDK. No LLM or cloud access."""
from __future__ import annotations
import asyncio
import json
import os
import sys
import uuid
from urllib.error import URLError
from urllib.request import urlopen
from acps_sdk.aip import AipRpcClient, TaskState, TextDataItem
from local_log import record

LOCAL_LEADER_ID = "local-demo-gongwei-leader"
LOCAL_PARTNER_ID = "local-demo-gongwei-resource"


def configured_resource_port() -> int:
    raw_port = os.environ.get("GONGWEI_RESOURCE_PORT", "18011")
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise RuntimeError("GONGWEI_RESOURCE_PORT 必须是 1 至 65535 的端口号。") from exc
    if not 1 <= port <= 65535:
        raise RuntimeError("GONGWEI_RESOURCE_PORT 必须是 1 至 65535 的端口号。")
    return port


RESOURCE_PORT = configured_resource_port()
PARTNER_BASE_URL = f"http://127.0.0.1:{RESOURCE_PORT}"
PARTNER_URL = f"{PARTNER_BASE_URL}/rpc"


def safe_error_message(exc: Exception) -> str:
    """Return a diagnostic that never copies an untrusted peer response."""
    raw = str(exc)
    lowered = raw.lower()
    suspicious_markers = ("ticket_key", "ecdh_req", "psk_req", "handshake_base_req")
    has_control = any(ord(char) < 32 and char not in "\r\n\t" for char in raw)
    if len(raw) > 256 or has_control or any(marker in lowered for marker in suspicious_markers):
        return "本机互联失败：对端返回了非本练习协议响应，未记录原始内容。"
    if isinstance(exc, RuntimeError):
        return raw
    return f"{type(exc).__name__}: 本机互联失败，未记录对端原始内容。"


def assert_running() -> None:
    try:
        with urlopen(f"{PARTNER_BASE_URL}/health", timeout=3) as response:
            info = json.load(response)
    except (URLError, OSError, ValueError) as exc:
        raise RuntimeError(
            f"没有找到资源助手。请先双击 02_start_resource.cmd，并保持 {RESOURCE_PORT} 端口窗口打开。"
        ) from exc
    if info.get("mode") != "local_simulation_only":
        raise RuntimeError(f"{RESOURCE_PORT}端口不是本练习的资源助手，请先处理端口冲突。")


async def run_case(client: AipRpcClient, slot: str, expect_available: bool) -> None:
    task_id = "task-" + str(uuid.uuid4())
    session_id = "session-" + str(uuid.uuid4())
    query = {"action": "lookup_staff", "device_id": "pump-001", "slot": slot}
    print(f"\n查询：水泵001，{slot}")
    record("leader", "request", {"task_id": task_id, "query": query})
    task = await asyncio.wait_for(client.start_task(
        session_id=session_id, task_id=task_id,
        user_input=json.dumps(query, ensure_ascii=False)), timeout=15)
    record("leader", "response", {"task_id": task_id, "task": task.model_dump(mode="json")})
    if task.senderId != LOCAL_PARTNER_ID:
        raise RuntimeError("返回的本机演示标识不匹配。")
    if task.status.state != TaskState.AwaitingCompletion:
        raise RuntimeError(f"没有取得待确认的查询结果，实际状态：{task.status.state}")
    payloads = [json.loads(item.text) for product in task.products or []
                for item in product.dataItems or [] if isinstance(item, TextDataItem)]
    if len(payloads) != 1:
        raise RuntimeError("助手没有返回唯一的查询结果。")
    result = payloads[0]
    if result.get("simulated") is not True or result.get("device_id") != "pump-001" or result.get("slot") != slot:
        raise RuntimeError("查询结果与请求不对应。")
    available = result.get("available_staff")
    if not isinstance(available, list) or bool(available) != expect_available:
        raise RuntimeError("结果不符合随包演示数据的预期，请检查数据是否被修改。")
    if result.get("staff_reserved") is not False or result.get("work_order_created") is not False:
        raise RuntimeError("只读查询不应该修改排班或创建工单。")
    print("资源助手回答：" + result["message"])
    if available:
        print("可用人员：" + "、".join(person["name"] for person in available))
    print("协调助手确认收到的是查询结果，不是批准维修。")
    final = await asyncio.wait_for(client.complete_task(task_id=task_id, session_id=session_id), timeout=15)
    if final.status.state != TaskState.Completed:
        raise RuntimeError(f"任务未进入完成状态：{final.status.state}")
    record("leader", "completed", {"task_id": task_id, "task": final.model_dump(mode="json")})
    print("LOCAL CASE PASSED: " + slot)


async def main() -> None:
    assert_running()
    print("本机AIP互联练习。模拟业务；未接入梧桐；没有调用大模型。")
    # Loopback exercise only. Do NOT reuse this setting for platform deployment.
    client = AipRpcClient(partner_url=PARTNER_URL, leader_id=LOCAL_LEADER_ID,
                          expected_partner_aic=LOCAL_PARTNER_ID,
                          identity_binding_enabled=False)
    try:
        await run_case(client, "slot-a", True)
        await run_case(client, "slot-b", False)
    finally:
        await client.close()
    print("\nLOCAL CHECK PASSED (2/2)")
    print("只表示这两项本机查询检查通过，不表示平台验证或整个作品完成。")
    print("运行记录保存在 logs 文件夹。")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("已取消。")
        sys.exit(130)
    except Exception as exc:
        safe_message = safe_error_message(exc)
        record("leader", "error", {"type": type(exc).__name__, "message": safe_message})
        print(f"\nLOCAL CHECK FAILED: {safe_message}", file=sys.stderr)
        sys.exit(1)
