"""Guardrails for switching from local smoke services to a real HTTPS runtime."""
from __future__ import annotations

import os
import ipaddress
from urllib.parse import urlsplit, urlunsplit

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
EXTERNAL_RPC_ENV = {
    "resource": "GONGWEI_EXTERNAL_RESOURCE_RPC_URL",
    "workorder": "GONGWEI_EXTERNAL_WORKORDER_RPC_URL",
    "audio": "GONGWEI_EXTERNAL_AUDIO_RPC_URL",
}


def validate_external_base_url(value: str | None) -> str:
    """Validate a real external base URL without inventing a deployment."""
    candidate = str(value or "").strip()
    if not candidate:
        raise ValueError("缺少 GONGWEI_PUBLIC_BASE_URL，不能生成正式端点。")
    parsed = urlsplit(candidate)
    if parsed.scheme.lower() != "https":
        raise ValueError("正式外部端点必须使用 HTTPS URL。")
    if not parsed.netloc or not parsed.hostname:
        raise ValueError("GONGWEI_PUBLIC_BASE_URL 必须是完整 HTTPS URL。")
    hostname = parsed.hostname.lower().strip("[]")
    if hostname in LOCAL_HOSTS or hostname.endswith(".localhost") or hostname.endswith(".localdomain"):
        raise ValueError("正式外部端点不能使用本机地址。")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and (address.is_loopback or address.is_private or address.is_link_local or address.is_unspecified or address.is_reserved):
        raise ValueError("正式外部端点不能使用回环、私网、链路本地或未指定地址。")
    if parsed.path.rstrip("/").endswith("/rpc"):
        raise ValueError("GONGWEI_PUBLIC_BASE_URL 应为服务基址，不应包含 /rpc。")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("正式外部端点不能包含账号、密码、查询参数或片段。")
    return urlunsplit(("https", parsed.netloc, parsed.path.rstrip("/"), "", ""))


def external_rpc_url(base_url: str | None = None) -> str:
    candidate = str(base_url or os.environ.get("GONGWEI_PUBLIC_BASE_URL") or "").strip()
    if candidate.rstrip("/").endswith("/rpc"):
        raw = candidate.rstrip("/")
        validate_external_base_url(raw.removesuffix("/rpc"))
        return raw
    base = validate_external_base_url(candidate)
    return base + "/rpc"


def runtime_mode() -> str:
    mode = os.environ.get("GONGWEI_RUNTIME_MODE", "local").strip().lower() or "local"
    if mode not in {"local", "external"}:
        raise ValueError("GONGWEI_RUNTIME_MODE 只能是 local 或 external。")
    return mode


def external_runtime_errors() -> list[str]:
    if runtime_mode() != "external":
        return []
    errors: list[str] = []
    for kind, env_name in EXTERNAL_RPC_ENV.items():
        value = os.environ.get(env_name)
        if not value:
            errors.append(f"缺少 {env_name}")
            continue
        try:
            external_rpc_url(value)
        except ValueError as exc:
            errors.append(f"{env_name}: {exc}")
    return errors
