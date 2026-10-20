"""Upload only required identities to the authorized server over SSH stdin.

No secret archive is written to disk. CLI tokens, EAB and ACME account keys
are deliberately absent. Existing files must match: never overwrite a
different server identity through this bootstrap utility.
"""
import io
import json
import subprocess
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SSH_KEY = ROOT.parent / 'gongwei.pem'


def main():
    files = {}
    for role, stem in [('leader', 'leader'), ('resource', 'resource_partner'), ('workorder', 'workorder')]:
        for name in ['aics.json', 'certs/trust-bundle.pem', f'certs/{stem}.crt', f'certs/private/{stem}.key']:
            files[f'{role}/{name}'] = ROOT / 'secrets' / name
    for name in ['certs/leader-server.crt', 'certs/private/leader-server.key', 'certs/leader-server-trust.pem']:
        files[f'leader/{name}'] = ROOT / 'secrets' / name
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w') as archive:
        for target, source in files.items():
            content = source.read_bytes()
            member = tarfile.TarInfo(target)
            member.size = len(content)
            member.mode = 0o600
            archive.addfile(member, io.BytesIO(content))
    # This small receiver never prints file contents, keys, certs or tokens.
    receiver = '''import sys,tarfile,pathlib,os,hashlib,json
root=pathlib.Path('/opt/gongwei/secrets')
root.mkdir(mode=0o700,parents=True,exist_ok=True)
os.chmod(root,0o700)
rows=[]
with tarfile.open(fileobj=sys.stdin.buffer,mode='r|') as archive:
 for item in archive:
  if not item.isfile() or item.name.startswith('/') or '..' in pathlib.PurePosixPath(item.name).parts: raise RuntimeError('unsafe archive member')
  target=root/item.name
  data=archive.extractfile(item).read()
  if target.exists() and target.read_bytes()!=data: raise RuntimeError('existing identity differs; explicit rotation required')
  target.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
  for parent in target.parents:
   if parent==root: break
   os.chmod(parent,0o700)
  fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
  with os.fdopen(fd,'wb') as output: output.write(data)
  os.chmod(target,0o600)
  rows.append({'file':item.name,'permissions':'0600'})
print(json.dumps({'uploaded':rows,'root':'/opt/gongwei/secrets','root_permissions':'0700'}))
'''
    import shlex
    command = ['ssh', '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes', '-o', 'StrictHostKeyChecking=yes',
               '-i', str(SSH_KEY), 'ubuntu@43.156.60.222', 'sudo python3 -c ' + shlex.quote(receiver)]
    result = subprocess.run(command, input=buffer.getvalue(), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        raise RuntimeError(result.stderr.decode('utf-8', errors='replace'))
    summary = json.loads(result.stdout)
    report = ROOT / 'reports/hybrid-platform-20261006/secret-upload-metadata.json'
    report.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Uploaded {len(summary["uploaded"])} required files, root-owned 0600; no secret values printed.')


if __name__ == '__main__':
    main()
