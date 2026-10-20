"""Transport selection for the existing business workflow.

The business layer is shared by both transports.  ``local_rpc`` remains the
safe default for the browser and regression scripts; ``platform_mq_inbox`` is
enabled only when the operator supplies the official MQ/ACL configuration.
"""
from __future__ import annotations

import os
from urllib.parse import urlsplit

from platform_runtime import external_rpc_url

SUPPORTED_MODES = frozenset({"local_rpc", "platform_mq_inbox", "platform_https_rpc"})


class TransportModeError(ValueError):
    pass


def get_transport_mode() -> str:
    mode = os.environ.get("GONGWEI_TRANSPORT_MODE", "local_rpc").strip().lower()
    if mode not in SUPPORTED_MODES:
        raise TransportModeError(
            "GONGWEI_TRANSPORT_MODE 必须是 local_rpc、platform_mq_inbox 或 platform_https_rpc。"
        )
    return mode


def _env(name: str) -> str | None:
    value = os.environ.get(name)
    return value.strip() if value and value.strip() else None


def _first_env(*names: str) -> str | None:
    """Read the project-prefixed name first, then the operator alias."""
    for name in names:
        value = _env(name)
        if value:
            return value
    return None


def _safe_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlsplit(value)
    if parsed.username or parsed.password:
        return f"{parsed.scheme}://<credentials-redacted>@{parsed.hostname or '<host>'}"
    return value


def mq_configuration_status() -> dict[str, object]:
    mode = get_transport_mode()
    required = {
        "broker_url": _first_env("GONGWEI_MQ_BROKER_URL", "MQ_BROKER_URL"),
        "auth_service_url": _first_env("GONGWEI_MQ_AUTH_SERVICE_URL", "MQ_AUTH_SERVICE_URL"),
        "vhost": _first_env("GONGWEI_MQ_VHOST", "MQ_VHOST"),
        "tls_mode": _first_env("GONGWEI_MQ_TLS_MODE", "MQ_TLS_MODE"),
        "inbox_endpoint_template": _first_env("GONGWEI_MQ_INBOX_ENDPOINT", "MQ_INBOX_ENDPOINT"),
    }
    missing = [key for key, value in required.items() if not value]
    invalid: list[str] = []
    if required["broker_url"]:
        invalid.extend(_validate_mq_url("broker_url", str(required["broker_url"]), {"amqps"}))
    if required["auth_service_url"]:
        invalid.extend(_validate_mq_url("auth_service_url", str(required["auth_service_url"]), {"https"}))
    if required["inbox_endpoint_template"]:
        endpoint = str(required["inbox_endpoint_template"])
        invalid.extend(_validate_mq_url("inbox_endpoint_template", endpoint, {"amqp", "amqps"}))
        if "{AIC}" not in endpoint and "{aic}" not in endpoint:
            invalid.append("inbox_endpoint_template: 必须包含 {AIC} 占位符")
    if required["tls_mode"] and str(required["tls_mode"]).lower() != "mtls":
        invalid.append("tls_mode: platform_mq_inbox 必须使用 mtls")
    return {
        "mode": mode,
        "configured": mode == "local_rpc" or not missing and not invalid,
        "missing": missing if mode == "platform_mq_inbox" else [],
        "invalid": invalid if mode == "platform_mq_inbox" else [],
        "broker_url": _safe_url(required["broker_url"]),
        "auth_service_url": _safe_url(required["auth_service_url"]),
        "vhost": required["vhost"],
        "tls_mode": required["tls_mode"],
        "inbox_endpoint_template": _safe_url(required["inbox_endpoint_template"]),
        "platform_verified": False,
    }


def _validate_mq_url(name: str, value: str, schemes: set[str]) -> list[str]:
    parsed = urlsplit(value)
    errors: list[str] = []
    if parsed.scheme not in schemes or not parsed.hostname:
        errors.append(f"{name}: 必须是完整的 {'/'.join(sorted(schemes))} URL")
        return errors
    if parsed.username or parsed.password:
        errors.append(f"{name}: URL 不得包含用户名或密码")
    hostname = parsed.hostname.lower()
    if hostname in {"localhost", "localhost.localdomain"} or hostname.startswith("127."):
        errors.append(f"{name}: 不能使用本机地址")
    return errors


HTTPS_URLS = {
    "leader_rpc_url": "GONGWEI_PUBLIC_LEADER_RPC_URL",
    "resource_rpc_url": "GONGWEI_PUBLIC_RESOURCE_RPC_URL",
    "workorder_rpc_url": "GONGWEI_PUBLIC_WORKORDER_RPC_URL",
}
HTTPS_AICS = {
    "leader_aic": "GONGWEI_LEADER_AIC",
    "resource_aic": "GONGWEI_RESOURCE_AIC",
    "workorder_aic": "GONGWEI_WORKORDER_AIC",
}
HTTPS_FILES = {
    "server_cert_file": "GONGWEI_SERVER_CERT_FILE",
    "client_cert_file": "GONGWEI_CLIENT_CERT_FILE",
    "private_key_file": "GONGWEI_PRIVATE_KEY_FILE",
    "trust_bundle_file": "GONGWEI_TRUST_BUNDLE_FILE",
}


def _validate_https_rpc_url(value: str) -> str:
    """Validate a configured RPC URL without accepting placeholders."""
    hostname = (urlsplit(value).hostname or "").lower()
    if hostname.endswith((".example.com", ".example.org", ".example.net", ".example.invalid")):
        raise ValueError("示例域名不能作为正式端点")
    return external_rpc_url(value)


def https_configuration_status() -> dict[str, object]:
    """Return redacted readiness for the formal HTTPS direct-RPC route."""
    mode = get_transport_mode()
    values = {key: _env(env_name) for key, env_name in {**HTTPS_URLS, **HTTPS_AICS, **HTTPS_FILES}.items()}
    missing = [key for key, value in values.items() if not value]
    invalid: list[str] = []
    urls: dict[str, str | None] = {}
    for key, value in ((key, values[key]) for key in HTTPS_URLS):
        if not value:
            urls[key] = None
            continue
        try:
            urls[key] = _validate_https_rpc_url(value)
        except ValueError as exc:
            invalid.append(f"{key}: {exc}")
            urls[key] = _safe_url(value)
    for key, value in values.items():
        if key in HTTPS_URLS or not value:
            continue
        if key.endswith("_file") and not os.path.isfile(value):
            invalid.append(f"{key}: 文件不存在")
    return {
        "mode": mode,
        "configured": mode == "local_rpc" or (not missing and not invalid),
        "missing": missing if mode == "platform_https_rpc" else [],
        "invalid": invalid if mode == "platform_https_rpc" else [],
        "urls": urls,
        "aics": {key: values[key] for key in HTTPS_AICS},
        "certificate_files": {key: values[key] for key in HTTPS_FILES},
        "platform_verified": False,
    }


def require_https_configuration() -> dict[str, str]:
    status = https_configuration_status()
    if status["mode"] != "platform_https_rpc":
        raise TransportModeError("当前传输模式不是 platform_https_rpc。")
    if status["missing"] or status["invalid"]:
        problems = [*(str(item) for item in status["missing"]), *(str(item) for item in status["invalid"])]
        raise TransportModeError("platform_https_rpc 配置不完整：" + "、".join(problems))
    return {
        **{key: str(value) for key, value in status["urls"].items()},
        **{key: str(value) for key, value in status["aics"].items()},
        **{key: str(value) for key, value in status["certificate_files"].items()},
    }


def require_mq_configuration() -> dict[str, str]:
    status = mq_configuration_status()
    if status["mode"] != "platform_mq_inbox":
        raise TransportModeError("当前传输模式不是 platform_mq_inbox。")
    if status["missing"] or status["invalid"]:
        raise TransportModeError(
            "platform_mq_inbox 配置不完整："
            + "、".join([*(str(item) for item in status["missing"]), *(str(item) for item in status["invalid"])])
        )
    values = {
        "broker_url": _first_env("GONGWEI_MQ_BROKER_URL", "MQ_BROKER_URL"),
        "auth_service_url": _first_env("GONGWEI_MQ_AUTH_SERVICE_URL", "MQ_AUTH_SERVICE_URL"),
        "vhost": _first_env("GONGWEI_MQ_VHOST", "MQ_VHOST"),
        "tls_mode": _first_env("GONGWEI_MQ_TLS_MODE", "MQ_TLS_MODE"),
        "inbox_endpoint_template": _first_env("GONGWEI_MQ_INBOX_ENDPOINT", "MQ_INBOX_ENDPOINT"),
    }
    return {
        **{key: str(value) for key, value in values.items()},
    }
