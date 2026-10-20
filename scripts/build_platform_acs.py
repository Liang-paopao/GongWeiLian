"""Generate review-ready ACS files from a real external HTTPS deployment.

The checked-in ACS files remain local smoke descriptors.  This command never
guesses a public host, certificate or AIC.  It only runs when the operator
provides a real HTTPS base URL through the environment.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from platform_runtime import validate_external_base_url  # noqa: E402

ACS_DIR = ROOT / "platform" / "approved_acs"
DEFAULT_OUTPUT = ROOT / "reports" / "platform_acs_external"
ROUTES = {"leader.json": "leader", "resource_partner.json": "resource", "work_order_partner.json": "work-order"}
ENDPOINT_VARS = {"leader.json": "GONGWEI_PUBLIC_LEADER_RPC_URL", "resource_partner.json": "GONGWEI_PUBLIC_RESOURCE_RPC_URL", "work_order_partner.json": "GONGWEI_PUBLIC_WORKORDER_RPC_URL"}
AICS = {"leader.json": "GONGWEI_LEADER_AIC", "resource_partner.json": "GONGWEI_RESOURCE_AIC", "work_order_partner.json": "GONGWEI_WORKORDER_AIC"}
CERT_VARS = ("GONGWEI_SERVER_CERT_FILE", "GONGWEI_CLIENT_CERT_FILE", "GONGWEI_PRIVATE_KEY_FILE", "GONGWEI_TRUST_BUNDLE_FILE")


def _is_example_host(host: str) -> bool:
    host = host.lower().rstrip('.')
    return any(host == name or host.endswith('.' + name) for name in ('example.com', 'example.org', 'example.net', 'invalid', 'test', 'example'))


def build(output_dir: Path, base_url: str | None = None) -> list[Path]:
    inputs = {(ACS_DIR / name).resolve() for name in ROUTES}
    if any((output_dir / name).resolve() in inputs for name in ROUTES):
        raise ValueError('不能覆盖当前已批准 ACS 输入。')
    raw_base = (base_url or os.environ.get("GONGWEI_PUBLIC_BASE_URL") or "").strip()
    host = (urlsplit(raw_base).hostname or "").lower()
    if _is_example_host(host):
        raise ValueError("示例域名不能生成正式 HTTPS ACS")
    base = validate_external_base_url(raw_base)
    missing_aic = [name for name in AICS.values() if not os.environ.get(name, "").strip()]
    if missing_aic:
        raise ValueError("正式 HTTPS ACS 缺少 AIC：" + "、".join(missing_aic))
    missing_cert = [name for name in CERT_VARS if not os.path.isfile(os.environ.get(name, ""))]
    if missing_cert:
        raise ValueError("正式 HTTPS ACS 缺少有效证书文件：" + "、".join(missing_cert))
    # The active deployment uses HTTPS Leader + MQ Partners. A base URL alone
    # is not evidence that three legacy /{role}/rpc routes exist.
    missing_endpoint = [name for name in ENDPOINT_VARS.values() if not os.environ.get(name, '').strip()]
    if missing_endpoint:
        raise ValueError('HTTPS endpoint 必须显式配置：' + '、'.join(missing_endpoint))
    cards = {}
    for filename in ROUTES:
        source = json.loads((ACS_DIR / filename).read_text(encoding='utf-8'))
        if source.get('aic') != os.environ[AICS[filename]].strip():
            raise ValueError(f'{filename} AIC 与当前批准身份不一致')
        endpoint = os.environ[ENDPOINT_VARS[filename]].strip().rstrip('/')
        validate_external_base_url(endpoint.removesuffix('/rpc'))
        if _is_example_host(urlsplit(endpoint).hostname or ''):
            raise ValueError('示例 endpoint 不能生成正式 ACS')
        source['endPoints'] = [{'url': endpoint, 'transport': 'JSONRPC', 'security': [{'mtls': []}]}]
        source['certificate'] = {'altNames': {'dns': [urlsplit(endpoint).hostname]}}
        cards[filename] = source
    output_dir.mkdir(parents=True, exist_ok=True)
    generated: list[Path] = []
    for filename, route in ROUTES.items():
        source = cards[filename]
        source["aic"] = os.environ[AICS[filename]].strip()
        source["securitySchemes"] = {"mtls": {"type": "mutualTLS"}}
        target = output_dir / filename
        target.write_text(json.dumps(source, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        generated.append(target)
    return generated


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    files = build(args.output_dir)
    print("GENERATED EXTERNAL ACS:")
    for path in files:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
