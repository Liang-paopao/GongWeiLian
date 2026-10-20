"""One read-only retry after the recorded platform TLS timeout."""
import datetime,json,urllib.request
from pathlib import Path
FOLDER=Path(__file__).parent
src=json.loads((FOLDER/'final-public-check.json').read_text(encoding='utf-8'))['statistics']
result={'url':src['url'],'checked_at':datetime.datetime.now().astimezone().isoformat(),'previous_error':src.get('error')}
try:
 with urllib.request.urlopen(result['url'],timeout=25) as response:result.update(http_status=response.status,response=json.load(response))
 own={x['aic'] for x in json.loads((FOLDER.parents[1]/'CHECK_STATUS.json').read_text(encoding='utf-8'))['agents'].values()}
 result['own_aics_present']=any(a in json.dumps(result['response']) for a in own)
except Exception as error:result['error']=type(error).__name__+': '+str(error)
(FOLDER/'platform-statistics-final-retry.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in result.items() if k!='response'},ensure_ascii=False))
