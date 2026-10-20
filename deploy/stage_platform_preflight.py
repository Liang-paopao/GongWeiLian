"""Stage a release for network preflight without switching the live symlink."""
import io
import shlex
import subprocess
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASE = '/opt/gongwei/releases/20261006-hybrid'
SSH = ['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'IdentitiesOnly=yes',
       '-i', str(ROOT.parent / 'gongwei.pem'), 'ubuntu@43.156.60.222']


def main():
    prepare = (f'set -eu; test -d /opt/gongwei/current; '
               f'if test ! -d {RELEASE}; then sudo cp -aL /opt/gongwei/current {RELEASE}; fi; '
               'sudo install -d -m 755 /opt/gongwei/shared/reports/hybrid-platform-20261006')
    subprocess.run(SSH + [prepare], check=True)
    members = ['platform_runtime_config.py', 'scripts/probe_platform_identity.py']
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w') as archive:
        for relative in members:
            data = (ROOT / relative).read_bytes()
            member = tarfile.TarInfo(relative)
            member.size, member.mode = len(data), 0o644
            archive.addfile(member, io.BytesIO(data))
    subprocess.run(SSH + [f'sudo tar --no-same-owner -xpf - -C {RELEASE}'], input=buffer.getvalue(), check=True)
    for role in ('leader', 'resource', 'workorder'):
        command = (f'cd {RELEASE} && sudo env GONGWEI_SECRETS_DIR=/opt/gongwei/secrets/{role} '
                   f'GONGWEI_TRANSPORT_MODE=platform_mq_inbox /opt/gongwei/.venv/bin/python '
                   f'scripts/probe_platform_identity.py --role {role} '
                   f'--output /opt/gongwei/shared/reports/hybrid-platform-20261006/mq-{role}-preflight-server.json')
        result = subprocess.run(SSH + [command], capture_output=True)
        log = ROOT / f'reports/hybrid-platform-20261006/mq-{role}-preflight-server.log'
        log.write_bytes(result.stdout + result.stderr)
        print(f'{role}: preflight exit={result.returncode}; live symlink unchanged')
        # JSON contains public AIC/status/error only, never credentials.
        report = subprocess.run(SSH + [f'cat /opt/gongwei/shared/reports/hybrid-platform-20261006/mq-{role}-preflight-server.json'], capture_output=True, check=True)
        (ROOT / f'reports/hybrid-platform-20261006/mq-{role}-preflight-server.json').write_bytes(report.stdout)
    print(f'Candidate: {RELEASE}')


if __name__ == '__main__':
    main()
