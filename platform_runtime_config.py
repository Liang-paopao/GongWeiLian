"""Load approved public AICs and local certificate paths for MQ processes.

Only file paths and public AIC identifiers are placed in the process
environment.  Private key and certificate contents stay inside ``secrets/``.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

ROOT = Path(__file__).resolve().parent
SECRETS = ROOT / "secrets"
AICS_FILE = SECRETS / "aics.json"


def validate_identity_certificate(cert_file: str | Path, key_file: str | Path, aic: str,
                                  *, usage: str = "clientAuth", hostname: str | None = None) -> None:
    """Fail closed before using another role's identity or an unsuitable keypair.

    CA-chain/revocation verification remains the responsibility of the actual
    TLS peer. This validates the local identity and key without logging them.
    """
    try:
        cert = x509.load_pem_x509_certificate(Path(cert_file).read_bytes())
        key = serialization.load_pem_private_key(Path(key_file).read_bytes(), password=None)
    except (OSError, ValueError, TypeError) as exc:
        raise RuntimeError("无法读取有效证书或私钥。") from exc
    cn = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    if len(cn) != 1 or cn[0].value != aic:
        raise RuntimeError("证书 CN 与该服务的真实 AIC 不一致。")
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except x509.ExtensionNotFound:
        san = x509.SubjectAlternativeName([])
    aic_uris = [v for v in san.get_values_for_type(x509.UniformResourceIdentifier) if v.startswith("acps://")]
    if aic_uris and aic_uris != [f"acps://{aic}"]:
        raise RuntimeError("证书 URI SAN 与真实 AIC 不一致。")
    if hostname and hostname.lower() not in [v.lower() for v in san.get_values_for_type(x509.DNSName)]:
        raise RuntimeError(f"serverAuth 证书缺少域名 DNS SAN：{hostname}")
    now = datetime.now(timezone.utc)
    if not cert.not_valid_before_utc <= now < cert.not_valid_after_utc:
        raise RuntimeError("证书不在有效期内。")
    eku_oid = {"clientAuth": ExtendedKeyUsageOID.CLIENT_AUTH, "serverAuth": ExtendedKeyUsageOID.SERVER_AUTH}[usage]
    try:
        eku = cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
    except x509.ExtensionNotFound as exc:
        raise RuntimeError(f"证书缺少 {usage} 用途。") from exc
    if eku_oid not in eku:
        raise RuntimeError(f"证书不允许 {usage} 用途。")
    public_format = (serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    if key.public_key().public_bytes(*public_format) != cert.public_key().public_bytes(*public_format):
        raise RuntimeError("证书与私钥不匹配。")


def _configured(name: str, alias: str, default: str) -> str:
    return os.environ.get(name) or os.environ.get(alias) or default


def configure_platform_environment(role: str) -> dict[str, str]:
    if role not in {"leader", "resource", "workorder"}:
        raise ValueError("role 必须是 leader、resource 或 workorder")
    secrets = Path(os.environ.get("GONGWEI_SECRETS_DIR") or SECRETS).resolve()
    # systemd LoadCredential flattens nested paths into credential IDs.
    # An explicit identity file must never fall back to a retired generation.
    aics_file = Path(os.environ.get("GONGWEI_AICS_FILE") or secrets / "aics.json")
    if not aics_file.is_file():
        raise RuntimeError("缺少 secrets/aics.json，不能猜测 AIC。")
    records = json.loads(aics_file.read_text(encoding="utf-8"))
    names = {"leader": "工维联核心业务 Leader", "resource": "工维联资源协调 Partner", "workorder": "工维联工单处理 Partner"}
    record = records.get(names[role]) or {}
    aic = str(record.get("aic") or "")
    if not aic or record.get("approval_status") != "APPROVED" or record.get("is_active") is not True:
        raise RuntimeError(f"{names[role]} 没有 APPROVED/active 的真实 AIC。")
    cert_stem = {"leader": "leader", "resource": "resource_partner", "workorder": "workorder"}[role]
    values = {
        "GONGWEI_TRANSPORT_MODE": "platform_mq_inbox",
        "GONGWEI_MQ_BROKER_URL": _configured("GONGWEI_MQ_BROKER_URL", "MQ_BROKER_URL", "amqps://wt.ioa.pub:5671"),
        "GONGWEI_MQ_AUTH_SERVICE_URL": _configured("GONGWEI_MQ_AUTH_SERVICE_URL", "MQ_AUTH_SERVICE_URL", "https://wt.ioa.pub:9007"),
        "GONGWEI_MQ_VHOST": _configured("GONGWEI_MQ_VHOST", "MQ_VHOST", "/acps"),
        "GONGWEI_MQ_TLS_MODE": "mtls",
        "GONGWEI_MQ_INBOX_ENDPOINT": _configured("GONGWEI_MQ_INBOX_ENDPOINT", "MQ_INBOX_ENDPOINT", "amqps://wt.ioa.pub:5671/acps?inbox=inbox_{AIC}"),
        "GONGWEI_MQ_CA_FILE": _configured("GONGWEI_MQ_CA_FILE", "MQ_CA_FILE", str(secrets / "certs" / "trust-bundle.pem")),
        "GONGWEI_MQ_CERT_FILE": _configured("GONGWEI_MQ_CERT_FILE", "MQ_CERT_FILE", str(secrets / "certs" / f"{cert_stem}.crt")),
        "GONGWEI_MQ_KEY_FILE": _configured("GONGWEI_MQ_KEY_FILE", "MQ_KEY_FILE", str(secrets / "certs" / "private" / f"{cert_stem}.key")),
        "AGENT_AIC": aic,
        "MQ_INBOX": f"inbox_{aic}",
        f"GONGWEI_MQ_{role.upper()}_AIC": aic,
    }
    for other_role, other_name in names.items():
        other_record = records.get(other_name) or {}
        other_aic = str(other_record.get("aic") or "")
        if not other_aic or other_record.get("approval_status") != "APPROVED" or other_record.get("is_active") is not True:
            raise RuntimeError(f"缺少 {other_name} 的 APPROVED/active 真实 AIC。")
        values[f"GONGWEI_MQ_{other_role.upper()}_AIC"] = other_aic
    if len({values[f"GONGWEI_MQ_{r.upper()}_AIC"] for r in names}) != len(names):
        raise RuntimeError("三个智能体不能共用 AIC。")
    for name in ("AGENT_AIC", "MQ_INBOX", *(f"GONGWEI_MQ_{r.upper()}_AIC" for r in names)):
        if os.environ.get(name) and os.environ[name] != values[name]:
            raise RuntimeError(f"配置 {name} 与当前角色真实身份不一致。")
    for name, scheme in (("GONGWEI_MQ_BROKER_URL", "amqps"), ("GONGWEI_MQ_AUTH_SERVICE_URL", "https")):
        parsed = urlsplit(values[name])
        if parsed.scheme != scheme or not parsed.hostname or parsed.username or parsed.password:
            raise RuntimeError(f"{name} 必须是无内嵌凭据的 {scheme} URL。")
    for key in ("GONGWEI_MQ_CA_FILE", "GONGWEI_MQ_CERT_FILE", "GONGWEI_MQ_KEY_FILE"):
        if not Path(values[key]).is_file():
            raise RuntimeError(f"缺少证书文件：{key}")
    validate_identity_certificate(values["GONGWEI_MQ_CERT_FILE"], values["GONGWEI_MQ_KEY_FILE"], aic)
    os.environ.update(values)
    return {"role": role, "aic": aic, "cert_file": values["GONGWEI_MQ_CERT_FILE"], "key_file": values["GONGWEI_MQ_KEY_FILE"]}
