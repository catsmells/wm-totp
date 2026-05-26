#!/usr/bin/env python3
import sys
import json
import time
import base64
import hmac
import hashlib
import struct
from pathlib import Path
ACCOUNTS_FILE = Path.home() / '.config' / 'wm-totp' / 'accounts.json'
def _load() -> list:
    if ACCOUNTS_FILE.exists():
        return json.loads(ACCOUNTS_FILE.read_text())
    return []
def _save(accounts: list):
    ACCOUNTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    ACCOUNTS_FILE.write_text(json.dumps(accounts, indent=2))
def _hotp(key: bytes, counter: int, digits: int = 6) -> str:
    msg = struct.pack('>Q', counter)
    h = hmac.new(key, msg, digestmod=hashlib.sha1).digest()
    off = h[-1] & 0x0F
    n = struct.unpack('>I', h[off:off+4])[0] & 0x7FFF_FFFF
    return f'{n % 10**digits:0{digits}d}'
def _totp(secret: str, period: int = 30) -> tuple[str, float]:
    key = base64.b32decode(secret.upper().replace(' ', ''))
    now = time.time()
    remaining = period - (now % period)
    return _hotp(key, int(now) // period), remaining
def cmd_add(name: str, secret: str, period: int = 30):
    secret = secret.upper().replace(' ', '')
    try:
        base64.b32decode(secret)
    except Exception:
        sys.exit('Error: invalid base32 secret')
    accounts = _load()
    if any(a['name'] == name for a in accounts):
        sys.exit(f'Error: account {name!r} already exists (remove it first)')
    code, _ = _totp(secret, period)
    accounts.append({'name': name, 'secret': secret, 'period': period})
    _save(accounts)
    print(f'Added {name!r}  (current code: {code[:3]} {code[3:]})')
def cmd_remove(name: str):
    accounts = _load()
    updated  = [a for a in accounts if a['name'] != name]
    if len(updated) == len(accounts):
        sys.exit(f'Not found: {name!r}')
    _save(updated)
    print(f'Removed {name!r}')
def cmd_list():
    accounts = _load()
    if not accounts:
        print('No accounts found. Add one with: manage.py add <name> <secret>.')
        return
    print(f'{"NAME":<20} {"SECRET (first 8)":<18} {"PERIOD":>6}')
    print('─' * 48)
    for a in accounts:
        print(f"{a['name']:<20} {a['secret'][:8]}...  {a.get('period',30):>5}s")
def cmd_test(name: str):
    accounts = _load()
    acc = next((a for a in accounts if a['name'] == name), None)
    if acc is None:
        sys.exit(f'Not found: {name!r}')
    print(f'Live codes for {name!r} (Ctrl-C to stop):')
    last = None
    while True:
        code, remaining = _totp(acc['secret'], acc.get('period', 30))
        bar = '█' * int(remaining / acc.get('period',30) * 20)
        line = f'\r  {code[:3]} {code[3:]}  [{bar:<20}] {remaining:4.1f}s  '
        if code != last:
            print()
        print(line, end='', flush=True)
        last = code
        time.sleep(0.25)
USAGE = __doc__.strip()
if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit(USAGE)
    match sys.argv[1]:
        case 'add':
            if len(sys.argv) < 4:
                sys.exit('Usage: manage.py add <name> <secret> [period]')
            period = int(sys.argv[4]) if len(sys.argv) > 4 else 30
            cmd_add(sys.argv[2], sys.argv[3], period)
        case 'remove':
            if len(sys.argv) < 3:
                sys.exit('Usage: manage.py remove <name>')
            cmd_remove(sys.argv[2])
        case 'list':
            cmd_list()
        case 'test':
            if len(sys.argv) < 3:
                sys.exit('Usage: manage.py test <name>')
            cmd_test(sys.argv[2])
        case _:
            sys.exit(USAGE)
