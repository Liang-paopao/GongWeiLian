"""Read-only post-reboot verification and official statistics response capture."""
import datetime
import json
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FOLDER = Path(__file__).parent
# Read-only public checks use direct HTTPS with normal certificate validation.
# Windows' implicit system proxy produced TLS EOF for unrelated hosts alike.
HTTPS = urllib.request.build_opener(urllib.request.ProxyHandler({}))
REMOTE = r'''
import datetime,json,sqlite3,subprocess,sys
from pathlib import Path
sys.path.insert(0,'/opt/gongwei/tools/amp-metadata')
import amp_metadata_forwarder as f
own=['web','resource','workorder','audio','leader','resource-inbox','workorder-inbox','amp-heartbeat','amp-metadata']
others=['nginx','mysql','postgresql','php8.3-fpm','pm2-ubuntu','gaokao-backend','gaokao-frontend']
def props(name):
 return dict(x.split('=',1) for x in subprocess.check_output(['systemctl','show',name,'-p','ActiveState','-p','SubState','-p','UnitFileState','-p','MainPID'],text=True).splitlines())
r={'checked_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'own_services':{x:props('gongwei-'+x) for x in own},'other_services':{x:props(x) for x in others},'platform_verified':False}
with sqlite3.connect('file:/opt/gongwei/shared/data/stage2.db?mode=ro',uri=True) as db:
 db.row_factory=sqlite3.Row
 r['business']={'integrity':db.execute('PRAGMA integrity_check').fetchone()[0],'orders':[dict(x) for x in db.execute('SELECT id,number,status,plan_id,request_id FROM work_orders')],'reservation_counts':dict(db.execute('SELECT status,count(*) FROM reservations GROUP BY status')),'inventory':[dict(x) for x in db.execute('SELECT id,category,available_qty,total_qty FROM inventory_items')]}
r['amqps_connections']=[x for x in subprocess.check_output(['ss','-Htnp'],text=True).splitlines() if ':5671' in x]
r['inbox_events']={}
for role in ['leader','resource-inbox','workorder-inbox']:
 lines=subprocess.check_output(['journalctl','-b','-u','gongwei-'+role,'--no-pager','-o','cat'],text=True).splitlines()
 r['inbox_events'][role]=[line for line in lines if any(s in line.lower() for s in ['inbox','connected','listening']) and not any(s in line.lower() for s in ['private key','access_token','refresh_token','authorization:'])][-30:]
r['metadata_ack_events']=[]
for line in subprocess.check_output(['journalctl','-b','-u','gongwei-amp-metadata','--no-pager','-o','cat'],text=True).splitlines():
 try:
  item=json.loads(line)
  if isinstance(item,dict) and set(item)<={'log_type','log_id','aic','partition','offset','error_type'}:r['metadata_ack_events'].append(item)
 except ValueError:pass
config=json.loads(Path('/etc/gongwei/amp-metadata.json').read_text())
r['metadata_sources']=[]
for source in f.metadata_sources(config):
 role,aic,path=source['role'],source['aic'],source['log_path']
 if path.is_file():
  valid=0;types=set();tasks=set();errors=0
  for raw in path.read_bytes().splitlines():
   try:
    item=json.loads(raw);kind=item['log_type'];f.validate_record(raw,kind,aic);valid+=1;types.add(kind)
    if item.get('correlation_id'):tasks.add(item['correlation_id'])
   except Exception:errors+=1
  r['metadata_sources'].append({'role':role,'file':str(path),'validated_records':valid,'invalid_records':errors,'types':sorted(types),'correlation_ids':sorted(tasks)})
r['all_services_active_enabled']=all(p['ActiveState']=='active' and p['UnitFileState']=='enabled' for p in list(r['own_services'].values())+list(r['other_services'].values()))
print(json.dumps(r,ensure_ascii=False))
'''


def main():
    ssh = ['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o',
           'IdentitiesOnly=yes', '-i', str(ROOT.parent / 'gongwei.pem'),
           'ubuntu@43.156.60.222', 'sudo /opt/gongwei/.venv/bin/python -']
    completed = subprocess.run(ssh, input=REMOTE.encode(), capture_output=True, timeout=40)
    completed.check_returncode()
    result = json.loads(completed.stdout)
    before = json.loads((FOLDER / 'reboot-request.json').read_text())
    result['boot_before'] = before['boot_before']
    result['actual_reboot_verified'] = result['boot_id'] != result['boot_before']
    (FOLDER / 'reboot-final.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    sites = []
    for host in ['app.yanyi.online', 'gongwei.yanyi.online', 'taluo.yanyi.online',
                 'www.yanyi.online', 'xiaoyi.yanyi.online']:
        row = {'host': host}
        try:
            with HTTPS.open('https://' + host + '/', timeout=20) as response:
                row.update(http_status=response.status, final_url=response.url)
        except Exception as exc:
            row['error_type'] = type(exc).__name__
        sites.append(row)
    (FOLDER / 'other-sites-after-reboot.json').write_text(json.dumps(sites, indent=2), encoding='utf-8')
    now = datetime.datetime.now().astimezone()
    params = {'startAt': '2026-10-09T01:00:00+08:00',
              'endAt': (now.replace(minute=0, second=0, microsecond=0) + datetime.timedelta(hours=1)).isoformat(), 'n': 200}
    statistics = {'url': 'https://wt.ioa.pub/internal/matched-stats/top?' + urllib.parse.urlencode(params),
                  'checked_at': now.isoformat(), 'scope': 'formal SDK diagnostics and real DingDang sessions 1841/1842; aggregate counts are not individual business-operation counts'}
    try:
        with HTTPS.open(statistics['url'], timeout=25) as response:
            statistics.update(http_status=response.status, response=json.load(response))
        own = {x['aic'] for x in json.loads((ROOT / 'CHECK_STATUS.json').read_text(encoding='utf-8'))['agents'].values()}
        statistics['own_entries'] = {key: [row for row in value if isinstance(row, dict) and row.get('aic') in own]
                                    for key, value in statistics['response'].items() if isinstance(value, list)}
        statistics['own_aics_present'] = any(statistics['own_entries'].values())
    except Exception as exc:
        statistics['error_type'] = type(exc).__name__
    (FOLDER / 'platform-statistics.json').write_text(json.dumps(statistics, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'reboot_verified': result['actual_reboot_verified'],
                      'services_active_enabled': result['all_services_active_enabled'],
                      'amqps_connections': len(result['amqps_connections']),
                      'metadata_sources': result['metadata_sources'],
                      'metadata_acks': len(result['metadata_ack_events']), 'sites': sites,
                      'statistics': {k: v for k, v in statistics.items() if k != 'response'}}, ensure_ascii=False))
    assert result['actual_reboot_verified'] and result['all_services_active_enabled']
    assert all(x.get('http_status') == 200 for x in sites)


if __name__ == '__main__':
    main()
