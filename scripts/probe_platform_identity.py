"""Real official-SDK MQ preflight; no business writes or credential output.

Run once per role (separate process). Leader additionally attempts an isolated
temporary ACL membership through the configured official auth endpoint.
"""
import argparse
import asyncio
import json
import logging
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from acps_sdk.aip.aip_group_auth import GroupAclClient
from mq_group_transport import OfficialMqPartnerRuntime, _runtime_rabbitmq_config
from platform_runtime_config import configure_platform_environment


async def probe(role):
    identity = configure_platform_environment(role)
    config = _runtime_rabbitmq_config()
    result = {'checked_at': datetime.now(timezone.utc).isoformat(), 'role': role,
              'aic': identity['aic'], 'broker': f"amqps://{config['host']}:{config['port']}",
              'auth_service_url': config['auth_service_url'], 'sdk_vhost': config['vhost'],
              'identity_binding_enabled': True, 'platform_verified': False}
    runtime = OfficialMqPartnerRuntime(partner_aic=identity['aic'], rabbitmq_config=config)
    async def reject_unrelated_invitation(invitation):
        # This preflight must not consume or acknowledge real business tasks.
        raise RuntimeError('Preflight received a live invitation; use the long-running service.')
    try:
        await asyncio.wait_for(runtime.start_inbox(reject_unrelated_invitation), timeout=25)
        result['amqps_and_inbox'] = 'PASS'
    except Exception as exc:
        result['amqps_and_inbox'] = 'FAIL'
        result['connection_error'] = f'{type(exc).__name__}: {exc}'
    finally:
        await runtime.close()
    if role == 'leader':
        client = GroupAclClient(base_url=config['auth_service_url'], ssl_context=config['ssl_context'])
        group_id = str(uuid.uuid4())
        result['acl_probe_group_id'] = group_id
        added = False
        try:
            await client.add_member(leader_aic=identity['aic'], group_id=group_id, member_aic=identity['aic'])
            added = True
            result['group_acl'] = 'PASS'
        except Exception as exc:
            result['group_acl'] = 'FAIL'
            result['acl_error'] = f'{type(exc).__name__}: {exc}'
        finally:
            if added:
                try:
                    await client.delete_group(leader_aic=identity['aic'], group_id=group_id)
                    result['probe_cleanup'] = 'PASS'
                except Exception as exc:
                    result['probe_cleanup'] = f'FAIL: {type(exc).__name__}: {exc}'
            await client.aclose()
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--role', choices=['leader', 'resource', 'workorder'], required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s')
    result = asyncio.run(probe(args.role))
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get('amqps_and_inbox') == 'PASS' and result.get('group_acl', 'PASS') == 'PASS' else 2


if __name__ == '__main__':
    raise SystemExit(main())
