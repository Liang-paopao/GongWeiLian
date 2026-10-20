"""Formal Leader RPC over end-to-end mutual TLS, with MQ Partner transport.

The external proxy must pass the TLS stream through to this process. HTTP
client-certificate headers are never accepted as an identity source.
"""
from __future__ import annotations

import asyncio
import logging
import os
import ssl
from pathlib import Path

import uvicorn
from acps_sdk.aip.aip_peer_cert import AipPeerCertH11Protocol

import stage2_aip
from leader_rpc_runtime import LeaderRpcRuntime, create_app
from platform_runtime_config import configure_platform_environment
from transport_mode import get_transport_mode, require_mq_configuration
from amp_runtime import AmpHeartbeat

ROOT = Path(__file__).resolve().parent


def _load_env_file() -> None:
    secrets_dir = Path(os.environ.get("GONGWEI_SECRETS_DIR", str(ROOT / "secrets")))
    path = Path(os.environ.get("GONGWEI_LEADER_ENV_FILE", str(secrets_dir / "leader.env")))
    if path.is_file():
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"'))


def _validate_server_tls(identity: dict[str, str]) -> dict[str, str]:
    secrets_dir = Path(os.environ.get("GONGWEI_SECRETS_DIR", str(ROOT / "secrets")))
    paths = {
        "certfile": Path(os.environ.get("GONGWEI_LEADER_SERVER_CERT", str(secrets_dir / "certs" / "leader-server.crt"))),
        "keyfile": Path(os.environ.get("GONGWEI_LEADER_SERVER_KEY", str(secrets_dir / "certs" / "private" / "leader-server.key"))),
        "ca_certs": Path(os.environ.get("GONGWEI_LEADER_CLIENT_CA", str(secrets_dir / "certs" / "trust-bundle.pem"))),
    }
    if paths["certfile"].resolve() == Path(identity["cert_file"]).resolve() or paths["keyfile"].resolve() == Path(identity["key_file"]).resolve():
        raise RuntimeError("Leader serverAuth 与 MQ clientAuth 必须使用独立证书和私钥。")
    for name, path in paths.items():
        if not path.is_file():
            raise RuntimeError(f"Leader RPC 缺少 TLS 文件：{name}")
    from platform_runtime_config import validate_identity_certificate
    validate_identity_certificate(
        paths["certfile"], paths["keyfile"], identity["aic"], usage="serverAuth",
        hostname=os.environ.get("GONGWEI_LEADER_PUBLIC_HOSTNAME", "leader.yanyi.online"),
    )
    return {key: str(path) for key, path in paths.items()}


async def _startup_mq() -> None:
    # Configuration and adapter creation fail closed. Actual group connections
    # are opened by the official coordinator for the first task of each session.
    stage2_aip._mq_coordinator()


async def _shutdown_mq() -> None:
    coordinator = stage2_aip._MQ_COORDINATOR
    try:
        if coordinator is not None:
            await coordinator.close()
    finally:
        stage2_aip._MQ_COORDINATOR = None


def build_server_config() -> uvicorn.Config:
    _load_env_file()
    if get_transport_mode() != "platform_mq_inbox":
        raise RuntimeError("Leader RPC 只允许 GONGWEI_TRANSPORT_MODE=platform_mq_inbox。")
    identity = configure_platform_environment("leader")
    require_mq_configuration()
    tls = _validate_server_tls(identity)
    state_path = Path(os.environ.get("GONGWEI_LEADER_RPC_STATE_DB", str(ROOT / "state" / "leader_rpc.sqlite3")))
    runtime = LeaderRpcRuntime(leader_aic=identity["aic"], state_path=state_path)
    app = create_app(runtime, startup=_startup_mq, shutdown=_shutdown_mq)
    app.state.amp_aic = identity["aic"]
    return uvicorn.Config(
        app, host=os.environ.get("GONGWEI_LEADER_RPC_HOST", "127.0.0.1"),
        port=int(os.environ.get("GONGWEI_LEADER_RPC_PORT", "18443")),
        http=AipPeerCertH11Protocol, proxy_headers=False, workers=1,
        ssl_certfile=tls["certfile"], ssl_keyfile=tls["keyfile"], ssl_ca_certs=tls["ca_certs"],
        ssl_cert_reqs=ssl.CERT_REQUIRED, ssl_version=ssl.PROTOCOL_TLS_SERVER,
        log_level=os.environ.get("GONGWEI_LOG_LEVEL", "info").lower(),
        timeout_graceful_shutdown=30,
    )


class LeaderRpcServer(uvicorn.Server):
    """Emit liveness only after Uvicorn has successfully bound its listener."""

    def __init__(self, config: uvicorn.Config):
        super().__init__(config)
        self._heartbeat = AmpHeartbeat(role="leader_rpc", aic=config.app.state.amp_aic,
                                       is_ready=self._listener_ready)

    def _listener_ready(self) -> bool:
        listeners = getattr(self, "servers", ())
        return self.started and bool(listeners) and all(listener.is_serving() for listener in listeners)

    async def startup(self, sockets=None) -> None:
        await super().startup(sockets=sockets)
        if self._listener_ready():
            await self._heartbeat.start()

    async def shutdown(self, sockets=None) -> None:
        await self._heartbeat.stop()
        await super().shutdown(sockets=sockets)

    async def serve(self, sockets=None) -> None:
        try:
            await super().serve(sockets=sockets)
        finally:
            await self._heartbeat.stop()


async def _run() -> None:
    config = build_server_config()
    config.load()
    config.ssl.minimum_version = ssl.TLSVersion.TLSv1_2
    await LeaderRpcServer(config).serve()


def main() -> int:
    logging.basicConfig(level=os.environ.get("GONGWEI_LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
