"""Generate Group/Inbox ACS only from operator-provided official parameters."""
from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "reports" / "platform_mq_acs"
# The reviewed MQ cards are the single maintained ACS source. Historical
# localhost cards live under archive/legacy and are never used for generation.
ACS_DIR = DEFAULT_OUTPUT
REQUIRED = (
    "GONGWEI_MQ_BROKER_URL",
    "GONGWEI_MQ_AUTH_SERVICE_URL",
    "GONGWEI_MQ_VHOST",
    "GONGWEI_MQ_TLS_MODE",
    "GONGWEI_MQ_INBOX_ENDPOINT",
)

ALIASES = {
    "GONGWEI_MQ_BROKER_URL": "MQ_BROKER_URL",
    "GONGWEI_MQ_AUTH_SERVICE_URL": "MQ_AUTH_SERVICE_URL",
    "GONGWEI_MQ_VHOST": "MQ_VHOST",
    "GONGWEI_MQ_TLS_MODE": "MQ_TLS_MODE",
    "GONGWEI_MQ_INBOX_ENDPOINT": "MQ_INBOX_ENDPOINT",
}


def _require(params: dict[str, str], name: str) -> str:
    value = str(params.get(name, "")).strip()
    if not value:
        raise ValueError(f"{name} 必须由平台或部署系统提供。")
    return value


def _validate_url(name: str, value: str, schemes: set[str]) -> None:
    parsed = urlsplit(value)
    if parsed.scheme not in schemes or not parsed.hostname:
        raise ValueError(f"{name} 必须是完整的 {'/'.join(sorted(schemes))} URL。")
    if parsed.hostname in {"localhost", "localhost.localdomain"} or parsed.hostname.startswith("127."):
        raise ValueError(f"{name} 不能使用本机地址。")
    if parsed.username or parsed.password:
        raise ValueError(f"{name} 不得把凭证写入 ACS。")


def _operator_value(params: dict[str, str], name: str) -> str:
    return str(params.get(name) or params.get(ALIASES[name]) or "").strip()


def build_group_acs(output_dir: Path, params: dict[str, str]) -> list[Path]:
    values = {name: _operator_value(params, name) for name in REQUIRED}
    for name in REQUIRED:
        if not values[name]:
            raise ValueError(f"{name} 必须由平台或部署系统提供。")
    _validate_url("GONGWEI_MQ_BROKER_URL", values["GONGWEI_MQ_BROKER_URL"], {"amqps"})
    _validate_url("GONGWEI_MQ_AUTH_SERVICE_URL", values["GONGWEI_MQ_AUTH_SERVICE_URL"], {"https"})
    _validate_url("GONGWEI_MQ_INBOX_ENDPOINT", values["GONGWEI_MQ_INBOX_ENDPOINT"], {"amqp", "amqps"})
    if "{AIC}" not in values["GONGWEI_MQ_INBOX_ENDPOINT"] and "{aic}" not in values["GONGWEI_MQ_INBOX_ENDPOINT"]:
        raise ValueError("GONGWEI_MQ_INBOX_ENDPOINT 必须包含 {AIC} 占位符。")
    if values["GONGWEI_MQ_TLS_MODE"].lower() != "mtls":
        raise ValueError("GONGWEI_MQ_TLS_MODE 必须是 mtls。")
    if not values["GONGWEI_MQ_VHOST"].startswith("/"):
        values["GONGWEI_MQ_VHOST"] = "/" + values["GONGWEI_MQ_VHOST"]

    output_dir.mkdir(parents=True, exist_ok=True)
    generated: list[Path] = []
    for filename in ("leader.json", "resource_partner.json", "work_order_partner.json"):
        payload = json.loads((ACS_DIR / filename).read_text(encoding="utf-8"))
        payload["endPoints"] = [{
            "url": values["GONGWEI_MQ_INBOX_ENDPOINT"],
            "transport": "AMQP",
            "security": [{"mtls": []}],
        }]
        payload["capabilities"]["messageQueue"] = ["rabbitmq:>=4.2"]
        for skill in payload.get("skills", []):
            if isinstance(skill, dict):
                skill.setdefault("version", payload.get("version", "1.0.0"))
        description = payload.get("description", "")
        description = description.replace(
            "当前运行端点为本机阶段三准备环境，正式外部访问需在审核后配置证书和可访问部署。",
            "",
        ).strip()
        payload["description"] = (
            description
            + " 使用 ACPS v2.2.0 Group/Inbox；群组准入由官方 mq-auth-server 完成。"
        )
        target = output_dir / filename
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        generated.append(target)
    # Keep deployment parameters separate from ACS.  The official ACS schema has
    # no top-level auth_service_url or broker credential fields.
    (output_dir / "mq-runtime-parameters.json").write_text(
        json.dumps({
            "brokerUrl": values["GONGWEI_MQ_BROKER_URL"],
            "authServiceUrl": values["GONGWEI_MQ_AUTH_SERVICE_URL"],
            "vhost": values["GONGWEI_MQ_VHOST"],
            "tlsMode": values["GONGWEI_MQ_TLS_MODE"],
            "inboxEndpointTemplate": values["GONGWEI_MQ_INBOX_ENDPOINT"],
            "platformVerified": False,
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return generated


def main() -> int:
    params = {name: os.environ.get(name, os.environ.get(ALIASES[name], "")) for name in REQUIRED}
    for path in build_group_acs(DEFAULT_OUTPUT, params):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
