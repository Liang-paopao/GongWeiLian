"""Long-running official Wutong Leader Inbox process.

Run with the project virtual environment.  The process refuses every
transport except ``platform_mq_inbox`` and never starts the local HTTP/RPC
server as a fallback.
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from leader_external_flow import handle_external_command
from leader_inbox_runtime import LeaderInboxRuntime
from mq_group_transport import _runtime_rabbitmq_config
from platform_runtime_config import configure_platform_environment
from transport_mode import get_transport_mode
from amp_runtime import AmpHeartbeat, inbox_is_ready, runtime_log_dir, shutdown_signals

ROOT = Path(__file__).resolve().parent


def _load_env_file() -> None:
    path = Path(os.environ.get("GONGWEI_LEADER_ENV_FILE", str(ROOT / "secrets" / "leader.env")))
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"'))


async def _run() -> None:
    _load_env_file()
    if get_transport_mode() != "platform_mq_inbox":
        raise RuntimeError("Leader Inbox 只允许 GONGWEI_TRANSPORT_MODE=platform_mq_inbox，拒绝回退到 local_rpc。")
    identity = configure_platform_environment("leader")
    runtime = LeaderInboxRuntime(
        leader_aic=identity["aic"],
        rabbitmq_config=_runtime_rabbitmq_config(),
        command_handler=handle_external_command,
    )
    inbox_channel = None
    heartbeat = AmpHeartbeat(role="leader_inbox", aic=identity["aic"],
                             is_ready=lambda: inbox_is_ready(runtime.runtime.client, inbox_channel))
    stop = asyncio.Event()
    logging.getLogger(__name__).info("event=leader_inbox_start aic=%s cert_file=%s", identity["aic"], identity["cert_file"])
    with shutdown_signals(stop):
        try:
            await runtime.start()
            inbox_channel = (await runtime.runtime.client.ensure_inbox_queue()).channel
            await heartbeat.start()
            await stop.wait()
        finally:
            try:
                await heartbeat.stop()
            finally:
                await runtime.close()
            logging.getLogger(__name__).info("event=leader_inbox_closed aic=%s", identity["aic"])


def main() -> int:
    _load_env_file()
    log_dir = runtime_log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=os.environ.get("GONGWEI_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(log_dir / "leader_inbox_runtime.log", encoding="utf-8")],
    )
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
