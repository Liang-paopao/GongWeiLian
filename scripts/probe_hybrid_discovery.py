"""Compare indexed ACS with default live discovery; never infer callability."""
import argparse
import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from acps_sdk.adp import DiscoveryRequest, DiscoveryResponse

ROOT = Path(__file__).resolve().parents[1]
ENDPOINT = 'https://wt.ioa.pub/discovery/acps-adp-v2/discover'


def build_query(aic, *, catalog=False):
    query = json.loads(DiscoveryRequest(type='filtered', filter={'conditions': [
        {'field': 'aic', 'op': 'eq', 'value': aic}]}, limit=10).to_json())
    if catalog:
        # Deployed Discovery OpenAPI extension, not an ADP standard field.
        # Catalog diagnostics must not change production Partner selection.
        query['extFilter'] = {'conditions': [{'field': 'alive', 'op': 'in',
                                             'value': ['online', 'offline', 'unknown']}]}
    return query


def summarize_lookup(default, catalog):
    return {'indexed': catalog.get('target_found') if catalog.get('success') else None,
            'default_discoverable': default.get('target_found') if default.get('success') else None,
            'dingdang_verified': False}


def fetch(aic, *, catalog=False):
    query = build_query(aic, catalog=catalog)
    request = urllib.request.Request(ENDPOINT, data=json.dumps(query).encode('utf-8'),
                                     headers={'Content-Type': 'application/json'})
    report = {'checked_at': datetime.now(timezone.utc).isoformat(), 'endpoint': ENDPOINT,
              'query': query, 'dingdang_verified': False}
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read().decode('utf-8')
            report['http_status'] = response.status
            report['response'] = json.loads(raw)
            report['success'] = DiscoveryResponse.from_json(raw).is_success()
            report['target_found'] = aic in report['response'].get('result', {}).get('acsMap', {})
    except urllib.error.HTTPError as exc:
        report.update(http_status=exc.code, response=exc.read().decode('utf-8', errors='replace'), success=False)
    except Exception as exc:
        report.update(success=False, error=f'{type(exc).__name__}: {exc}')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--identities-file', required=True, type=Path,
                        help='Explicit identity generation; never silently probe retired AICs')
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args()
    identities = json.loads(args.identities_file.read_text(encoding='utf-8'))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    names = [('leader', '工维联核心业务 Leader'), ('resource', '工维联资源协调 Partner'), ('workorder', '工维联工单处理 Partner')]
    for role, name in names:
        identity = identities[name]
        if identity.get('approval_status') != 'APPROVED' or identity.get('is_active') is not True or not identity.get('aic'):
            report = {'role': role, 'skipped': 'identity not approved and active', 'dingdang_verified': False}
        else:
            aic = identity['aic']
            default, catalog = fetch(aic), fetch(aic, catalog=True)
            report = {'role': role, 'aic': aic, 'default_query': default, 'catalog_query': catalog,
                      **summarize_lookup(default, catalog)}
        (args.output_dir/f'discovery-{role}.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        print(json.dumps({key: value for key, value in report.items() if key not in ('default_query', 'catalog_query')}))


if __name__ == '__main__':
    main()
