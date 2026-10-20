"""Concise public mTLS identity probe for the re-registered Leader.

The valid request intentionally stops at awaiting-input and is cancelled, so
this probe does not create an order or reservation.  The other cases verify
that missing certificates, a mismatched senderId and a serverAuth certificate
are rejected by the public Leader endpoint.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REMOTE = r'''
import json, ssl, socket, http.client, time, uuid
from datetime import datetime, timezone
from acps_sdk.aip import TaskCommand, TaskCommandType, TextDataItem
from acps_sdk.aip.aip_rpc_model import RpcRequest, RpcRequestParams

leader_aic = "1.2.156.3088.1.BUPT.JSQB3Y.GD6IGY.AWF688.0WV9"
resource_aic = "1.2.156.3088.1.BUPT.JSQB3Y.E164E8.FWIZ4R.03IA"
base = "/opt/gongwei/secrets/generations/20261010/leader"
partner = "/opt/gongwei/secrets/generations/20261007/resource"
report = {
    "checked_at": datetime.now(timezone.utc).isoformat(),
    "endpoint": "https://leader.yanyi.online/rpc",
    "leader_aic": leader_aic,
    "scope": "public mTLS identity binding; not DingDang",
    "platform_verified": False,
}

def context(cert=None, key=None, ca="trust-bundle.pem"):
    c = ssl.create_default_context(cafile=f"{base}/certs/{ca}")
    if cert:
        c.load_cert_chain(cert, key)
    return c

def command(kind, session, task, sender, message):
    return TaskCommand(
        id=f"identity-{uuid.uuid4().hex[:12]}",
        sentAt=datetime.now(timezone.utc).isoformat(),
        senderRole="leader", senderId=sender,
        sessionId=session, taskId=task,
        command=TaskCommandType(kind),
        dataItems=[TextDataItem(text=message)] if message else [],
    )

def request(cmd, ctx):
    body = RpcRequest(id=cmd.id, params=RpcRequestParams(command=cmd)).model_dump_json().encode()
    with socket.create_connection(("leader.yanyi.online", 443), timeout=12) as raw:
        with ctx.wrap_socket(raw, server_hostname="leader.yanyi.online") as sock:
            sock.sendall(
                b"POST /rpc HTTP/1.1\r\nHost: leader.yanyi.online\r\n"
                b"Content-Type: application/json\r\nConnection: close\r\nContent-Length: "
                + str(len(body)).encode() + b"\r\n\r\n" + body
            )
            response = http.client.HTTPResponse(sock)
            response.begin()
            raw_body = response.read()
            return {"http_status": response.status, "body": json.loads(raw_body)}

session = f"identity-{uuid.uuid4().hex[:12]}-session"
task = f"identity-{uuid.uuid4().hex[:12]}-task"
valid_ctx = context(
    f"{base}/certs/leader.crt",
    f"{base}/certs/private/leader.key",
)
valid_start = request(
    command("start", session, task, leader_aic,
            "水泵001运行异常，帮我安排明天下午检查。"),
    valid_ctx,
)
report["valid_start"] = valid_start
state = valid_start.get("body", {}).get("result", {}).get("status", {}).get("state")
for _ in range(20):
    if state not in {"accepted", "working"}:
        break
    time.sleep(0.2)
    got = request(command("get", session, task, leader_aic, ""), valid_ctx)
    report["valid_get"] = got
    state = got.get("body", {}).get("result", {}).get("status", {}).get("state")

try:
    report["valid_cancel"] = request(command("cancel", session, task, leader_aic, "取消本次测试"), valid_ctx)
except Exception as exc:
    report["valid_cancel_error"] = {"type": type(exc).__name__, "message": str(exc)}

wrong_sender_ctx = context(
    f"{partner}/certs/resource_partner.crt",
    f"{partner}/certs/private/resource_partner.key",
)
wrong_sender_session = f"identity-wrong-{uuid.uuid4().hex[:12]}-session"
wrong_sender_task = f"identity-wrong-{uuid.uuid4().hex[:12]}-task"
try:
    report["wrong_sender"] = request(
        command("start", wrong_sender_session, wrong_sender_task, leader_aic,
                "水泵001运行异常，帮我安排明天下午检查。"),
        wrong_sender_ctx,
    )
except Exception as exc:
    report["wrong_sender_error"] = {"type": type(exc).__name__, "message": str(exc)}

for name, ctx in [
    ("no_certificate", context()),
    ("server_auth_as_client", context(
        f"{base}/certs/leader-server.crt",
        f"{base}/certs/private/leader-server.key",
    )),
]:
    try:
        report[name] = request(
            command("start", f"identity-{name}-session", f"identity-{name}-task", leader_aic, "测试"),
            ctx,
        )
    except Exception as exc:
        report[name] = {"rejected": True, "error_type": type(exc).__name__, "error": str(exc)}

report["pass_result"] = (
    state == "awaiting-input"
    and report.get("valid_cancel", {}).get("body", {}).get("result", {}).get("status", {}).get("state") in {"canceled", "cancelled"}
    and report.get("wrong_sender", {}).get("body", {}).get("error") is not None
    and report.get("no_certificate", {}).get("rejected") is True
    and report.get("server_auth_as_client", {}).get("rejected") is True
)
print(json.dumps(report, ensure_ascii=False, indent=2))
'''


def main() -> int:
    ssh = [
        "ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
        "-o", "IdentitiesOnly=yes", "-i", str(ROOT.parent / "gongwei.pem"),
        "ubuntu@43.156.60.222", "sudo /opt/gongwei/.venv/bin/python -",
    ]
    completed = subprocess.run(ssh, input=REMOTE.encode(), capture_output=True, timeout=90)
    if completed.returncode:
        raise RuntimeError(completed.stderr.decode(errors="replace"))
    report = json.loads(completed.stdout)
    out = ROOT / "reports/full-reregister-20261010-identity-mtls.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "pass_result": report.get("pass_result"),
        "valid_state": report.get("valid_get", {}).get("body", {}).get("result", {}).get("status", {}).get("state"),
        "wrong_sender_rejected": report.get("wrong_sender", {}).get("body", {}).get("error") is not None,
        "no_certificate_rejected": report.get("no_certificate", {}).get("rejected"),
        "server_auth_rejected": report.get("server_auth_as_client", {}).get("rejected"),
    }, ensure_ascii=False))
    return 0 if report.get("pass_result") else 2


if __name__ == "__main__":
    raise SystemExit(main())
