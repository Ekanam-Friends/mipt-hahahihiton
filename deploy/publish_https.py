"""Add the isolated MIPT upstream to the existing Caddy config, with rollback."""
from datetime import datetime, timezone
from pathlib import Path
import shutil
import subprocess

path = Path('/opt/ikanam/Caddyfile')
domain = 'ai-assist.ekanamfriends.ru'
before = path.read_text()
block = '''
# MIPT regulation navigator, independent Compose project.
ai-assist.ekanamfriends.ru {
    encode gzip
    header {
        X-Robots-Tag "noindex, nofollow"
        Referrer-Policy "same-origin"
        X-Content-Type-Options "nosniff"
        -Server
    }
    reverse_proxy mipt-regnav-web:8000
}
'''
if domain not in before:
    backup = path.with_name('Caddyfile.mipt-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '.bak')
    shutil.copy2(path, backup)
    # Preserve the existing inode used by the container bind mount.
    path.write_text(before.rstrip() + '\n' + block)
    try:
        subprocess.run(['docker', 'exec', '-i', 'ikanam-caddy-1', 'caddy', 'validate', '--config', '/dev/stdin', '--adapter', 'caddyfile'], input=path.read_bytes(), check=True)
        subprocess.run(['docker', 'exec', '-i', 'ikanam-caddy-1', 'caddy', 'reload', '--config', '/dev/stdin', '--adapter', 'caddyfile'], input=path.read_bytes(), check=True)
    except Exception:
        path.write_text(before)
        subprocess.run(['docker', 'exec', 'ikanam-caddy-1', 'caddy', 'reload', '--config', '/etc/caddy/Caddyfile', '--adapter', 'caddyfile'], check=False)
        raise
    for stale in sorted(path.parent.glob('Caddyfile.mipt-*.bak'), reverse=True)[3:]:
        stale.unlink()
print('MIPT route present; existing route blocks preserved')
