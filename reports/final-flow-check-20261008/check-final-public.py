"""Read public assets and matched statistics; do not send telemetry or secrets."""
import datetime,hashlib,json,urllib.parse,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];FOLDER=Path(__file__).parent
result={'checked_at':datetime.datetime.now().astimezone().isoformat(),'assets':{}}
for name in ['index.html','app.js']:
 url='https://gongwei.yanyi.online/'+('' if name=='index.html' else 'static/'+name)+'?v=precision-20261008-final3'
 with urllib.request.urlopen(url,timeout=25) as response:data=response.read();status=response.status
 local=(ROOT/'web'/name).read_bytes()
 result['assets'][name]={'url':url,'http_status':status,'sha256':hashlib.sha256(data).hexdigest(),'matches_local':data==local}
q=urllib.parse.urlencode({'startAt':'2026-10-08T21:00:00+08:00','endAt':'2026-10-09T01:00:00+08:00','n':200})
url='https://wt.ioa.pub/internal/matched-stats/top?'+q
stats={'url':url,'scope':'Public matched-stats, not a claim about all internal platform access records'}
try:
 with urllib.request.urlopen(url,timeout=25) as response:stats.update(http_status=response.status,response=json.load(response))
 own={x['aic'] for x in json.loads((ROOT/'CHECK_STATUS.json').read_text(encoding='utf-8'))['agents'].values()}
 stats['own_aics_present']=any(aic in json.dumps(stats['response']) for aic in own)
except Exception as error:stats.update(error=type(error).__name__+': '+str(error),own_aics_present=None)
result['statistics']=stats
(FOLDER/'final-public-check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'assets':result['assets'],'statistics':{k:v for k,v in stats.items() if k!='response'}},ensure_ascii=False))
assert all(x['matches_local'] for x in result['assets'].values())
