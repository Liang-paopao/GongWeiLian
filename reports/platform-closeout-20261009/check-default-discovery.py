"""Read-only exact AIC discovery, with no extFilter or local fallback."""
import datetime
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FOLDER = Path(__file__).parent
ENDPOINT = 'https://wt.ioa.pub/discovery/acps-adp-v2/discover'

agents = json.loads((ROOT / 'CHECK_STATUS.json').read_text(encoding='utf-8'))['agents']
results = []
for role, agent in agents.items():
    query = {'type': 'filtered', 'limit': 10, 'filter': {'logic': 'and', 'conditions': [
        {'field': 'aic', 'op': 'eq', 'value': agent['aic']}]}}
    record = {'checked_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'endpoint': ENDPOINT, 'query': query, 'role': role, 'browser_test': False}
    request = urllib.request.Request(ENDPOINT, data=json.dumps(query).encode(),
                                   headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            record.update(http_status=response.status, response=json.load(response))
        acs = record['response'].get('result', {}).get('acsMap', {}).get(agent['aic'])
        record['own_aic_returned'] = bool(acs and acs.get('active') is True)
    except Exception as exc:
        record.update(error_type=type(exc).__name__, own_aic_returned=False)
    (FOLDER / ('discovery-' + role + '.json')).write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    results.append({k: v for k, v in record.items() if k not in {'response', 'query'}})
print(json.dumps(results, ensure_ascii=False))
if not all(r['own_aic_returned'] for r in results):
    raise SystemExit(1)
