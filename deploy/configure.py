"""Generate private single-owner deployment config; never prints secrets."""
import ipaddress
import os
from pathlib import Path
import re
import secrets
import sys

if len(sys.argv) != 3:
    raise SystemExit('Usage: python configure.py play.your-domain.com PUBLIC_IPV4')
domain, public_ip = sys.argv[1:]
if not re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9.-]*[a-zA-Z0-9])?', domain) or '.' not in domain:
    raise SystemExit('Enter a valid DNS hostname')
ipaddress.IPv4Address(public_ip)
root = Path(__file__).resolve().parent
files = ['.env', 'Caddyfile', 'turnserver.conf', 'PAIRING-KEYS.txt']
if any((root / f).exists() for f in files):
    raise SystemExit('Configuration exists. Back it up and remove it before regenerating keys.')
host, phone, turn = (secrets.token_urlsafe(32) for _ in range(3))
values = {
'.env': f'HOST_TOKEN={host}\nPHONE_TOKEN={phone}\nTURN_SECRET={turn}\nTURN_URLS=turn:{domain}:3478?transport=udp,turn:{domain}:3478?transport=tcp\nSTUN_URL=stun:{domain}:3478\n',
'Caddyfile': f'''{domain} {{
    header {{
        X-Content-Type-Options nosniff
        Referrer-Policy no-referrer
        X-Frame-Options DENY
        Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self' wss://{domain}; media-src 'self' blob:; object-src 'none'; frame-ancestors 'none'"
    }}
    reverse_proxy 127.0.0.1:8080
}}
''',
 'turnserver.conf': f'''listening-port=3478
external-ip={public_ip}
min-port=49160
max-port=49260
fingerprint
use-auth-secret
static-auth-secret={turn}
realm={domain}
no-cli
no-tls
no-dtls
no-multicast-peers
denied-peer-ip=127.0.0.0-127.255.255.255
denied-peer-ip=::1
denied-peer-ip=10.0.0.0-10.255.255.255
denied-peer-ip=172.16.0.0-172.31.255.255
denied-peer-ip=192.168.0.0-192.168.255.255
denied-peer-ip=169.254.0.0-169.254.255.255
user-quota=8
total-quota=16
max-bps=2500000
simple-log
log-file=stdout
''',
 'PAIRING-KEYS.txt': f'FarPlay private setup — do not upload to GitHub\nService: https://{domain}\nHost key: {host}\nPhone key: {phone}\n\nAnyone with the phone key can control the PC while the host is running.\nStop the host to revoke live access; rotate PHONE_TOKEN to revoke the key.\n'
}
for name, value in values.items():
    path = root / name
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as out:
        out.write(value)
# coturn runs unprivileged in its container; requires read access to its mounted config.
(root / 'turnserver.conf').chmod(0o644)
print('Configuration created. Read PAIRING-KEYS.txt privately to pair your devices.')
