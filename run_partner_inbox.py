"""Long-running official MQ Inbox entrypoint for Resource/Work-order Partners."""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
from pathlib import Path
from typing import Any

from mq_group_transport import OfficialMqPartnerHandler, OfficialMqPartnerRuntime, _runtime_rabbitmq_config
from platform_runtime_config import configure_platform_environment
from transport_mode import get_transport_mode
from amp_runtime import AmpHeartbeat, inbox_is_ready, runtime_log_dir, shutdown_signals

ROOT = Path(__file__).resolve().parent
_ROLES = {"resource": "资源协调 Partner", "workorder": "工单处理 Partner"}


def _ensure_platform_mode() -> None:
    if get_transport_mode() != "platform_mq_inbox":
        raise RuntimeError("Partner Inbox 只允许 GONGWEI_TRANSPORT_MODE=platform_mq_inbox，拒绝回退到 local_rpc。")


def build_runtime(role: str) -> OfficialMqPartnerRuntime:
    if role not in _ROLES:
        raise ValueError("role 必须是 resource 或 workorder")
    _ensure_platform_mode()
    identity = configure_platform_environment(role)
    runtime = OfficialMqPartnerRuntime(partner_aic=identity["aic"], rabbitmq_config=_runtime_rabbitmq_config())
    handler = OfficialMqPartnerHandler(role, runtime.client)
    runtime.set_command_handler(handler.handle)
    return runtime


async def _run(role: str) -> None:
    runtime = build_runtime(role)
    inbox_channel = None
    heartbeat = AmpHeartbeat(role=role, aic=runtime.partner_aic,
                             is_ready=lambda: inbox_is_ready(runtime.client, inbox_channel))
    stop = asyncio.Event()
    logging.getLogger(__name__).info("event=partner_inbox_start role=%s aic=%s", role, runtime.partner_aic)
    with shutdown_signals(stop):
        try:
            await runtime.start_inbox(lambda invitation: _record_invitation(role, invitation))
            inbox_channel = (await runtime.client.ensure_inbox_queue()).channel
            await heartbeat.start()
            logging.getLogger(__name__).info("event=partner_inbox_listening role=%s aic=%s", role, runtime.partner_aic)
            await stop.wait()
        finally:
            try:
                await heartbeat.stop()
            finally:
                await runtime.close()
            logging.getLogger(__name__).info("event=partner_inbox_closed role=%s aic=%s", role, runtime.partner_aic)


async def _record_invitation(role: str, invitation: Any) -> None:
    logging.getLogger(__name__).info(
        "event=partner_inbox_invitation_received role=%s group_id=%s leader_aic=%s",
        role,
        getattr(invitation.group, "groupId", ""),
        getattr(invitation.group.leader, "aic", ""),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run an official ACPs GroupPartner Inbox")
    parser.add_argument("--role", choices=sorted(_ROLES), required=True)
    args = parser.parse_args(argv)
    log_dir = runtime_log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=os.environ.get("GONGWEI_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(log_dir / f"{args.role}_partner_inbox.log", encoding="utf-8")],
    )
    try:
        asyncio.run(_run(args.role))
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
