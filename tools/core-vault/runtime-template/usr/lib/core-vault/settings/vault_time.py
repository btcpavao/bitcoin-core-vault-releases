"""Offline manual clock and volatile timezone preferences for Bitcoin Core Vault.

Only apply_settings() needs root. Its caller is a fixed Polkit-authorized helper.
No NTP service, hardware-clock command, network operation or persistent config
write is used. The timezone bind source is a root-owned file on /run tmpfs.
"""
from datetime import datetime
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import time
from zoneinfo import ZoneInfo, available_timezones

STATE = Path('/run/core-vault-time')
LOCALTIME = Path('/etc/localtime')
ZONE_ROOT = Path('/usr/share/zoneinfo')
ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8'}


class TimeError(ValueError):
    pass


def zone_names():
    return sorted(x for x in available_timezones()
                  if x not in ('localtime', 'posixrules') and not x.startswith(('right/', 'posix/')))


def zone_file(value):
    if (not isinstance(value, str) or len(value) > 128
            or value in ('localtime', 'posixrules')
            or value.startswith(('right/', 'posix/'))
            or not re.fullmatch(r'[A-Za-z0-9_+.-]+(?:/[A-Za-z0-9_+.-]+)*', value)
            or any(part in ('.', '..') for part in value.split('/'))):
        raise TimeError('Please select an available time zone.')
    try:
        path = (ZONE_ROOT / value).resolve(strict=True)
        if not path.is_relative_to(ZONE_ROOT) or not path.is_file():
            raise ValueError()
        raw = path.read_bytes()
        if not raw.startswith(b'TZif') or not 44 <= len(raw) <= 1048576:
            raise ValueError()
        return path
    except (OSError, ValueError):
        raise TimeError('Please select an available time zone.') from None


def zone(value):
    with zone_file(value).open('rb') as source:
        return ZoneInfo.from_file(source, key=value)


def snapshot():
    name = 'Etc/UTC'
    for candidate in (STATE / 'zone', Path('/etc/timezone')):
        try:
            text = candidate.read_text()[:129].strip()
            zone_file(text)
            name = text
            break
        except (OSError, ValueError):
            pass
    return {'timezone': name, 'automatic': False}


def validate_request(value):
    if not isinstance(value, dict) or set(value) != {'timezone', 'local_time'}:
        raise TimeError('Invalid offline date and time request.')
    chosen = zone(value['timezone'])
    raw = value['local_time']
    if not isinstance(raw, str) or not re.fullmatch(r'\d{4}-\d\d-\d\d \d\d:\d\d:\d\d', raw):
        raise TimeError('Please enter a valid date and time.')
    try:
        local = datetime.strptime(raw, '%Y-%m-%d %H:%M:%S')
        if not 2000 <= local.year <= 2100:
            raise ValueError()
    except ValueError:
        raise TimeError('Please enter a valid date between 2000 and 2100.') from None
    candidates = {int(local.replace(tzinfo=chosen, fold=fold).timestamp())
                  for fold in (0, 1)
                  if datetime.fromtimestamp(local.replace(tzinfo=chosen, fold=fold).timestamp(), chosen)
                  .replace(tzinfo=None) == local}
    if not candidates:
        raise TimeError('That time is skipped by a daylight-saving change. Please choose another time.')
    if len(candidates) != 1:
        raise TimeError('That time occurs twice during a daylight-saving change. Please choose another time.')
    return value['timezone'], candidates.pop()


def _regular_root_file(path, allow_missing=False):
    try:
        info = path.lstat()
    except FileNotFoundError:
        if allow_missing:
            return
        raise
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise TimeError('The volatile time-settings path is not ready.')


def _write_root_file(path, raw):
    _regular_root_file(path, allow_missing=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o644)
    with os.fdopen(fd, 'wb') as target:
        # The private desktop uses umask 077. These non-secret timezone files
        # must remain readable by ordinary applications after the RAM bind.
        os.fchmod(target.fileno(), 0o644)
        target.write(raw)
        target.flush()


def _prepare_state():
    STATE.mkdir(mode=0o755, exist_ok=True)
    info = STATE.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise TimeError('The volatile time-settings directory is not ready.')
    result = subprocess.run(['/usr/bin/findmnt', '-n', '-o', 'FSTYPE', '-T', str(STATE)],
                            text=True, capture_output=True, check=True, timeout=5, env=ENV)
    if result.stdout.strip() != 'tmpfs':
        raise TimeError('The time-settings workspace must be in RAM.')
    # Apply the intended traversal permission only after validating this
    # fixed, root-owned, non-writable directory and its RAM filesystem.
    os.chmod(STATE, 0o755, follow_symlinks=False)


def _prepare_timezone(raw):
    # /etc/localtime is made a regular file in the image chroot. Mounting over
    # a symlink would accidentally cover a shared zoneinfo file, so reject it.
    _regular_root_file(LOCALTIME)
    source = STATE / 'localtime'
    # An existing bind remains on the same inode, so update only this bounded
    # root-owned non-secret file rather than replacing it under the mount.
    _write_root_file(source, raw)
    mounts = []
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        before, after = line.split(' - ', 1)
        fields = before.split()
        if fields[4] == str(LOCALTIME):
            mounts.append((fields[3], after.split()[0]))
    if mounts:
        if mounts[-1] != ('/core-vault-time/localtime', 'tmpfs'):
            raise TimeError('An unexpected mount covers the system timezone.')
    else:
        subprocess.run(['/usr/bin/mount', '--bind', str(source), str(LOCALTIME)],
                       check=True, capture_output=True, timeout=10, env=ENV)


def apply_settings(value):
    name, epoch = validate_request(value)
    if os.geteuid() != 0:
        raise TimeError('Please use the local Vault time-settings helper.')
    raw = zone_file(name).read_bytes()
    try:
        _prepare_state()
        lock_path = STATE / 'lock'
        _regular_root_file(lock_path, allow_missing=True)
        with os.fdopen(os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600), 'w') as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            before = snapshot()['timezone']
            old_raw = zone_file(before).read_bytes()
            _prepare_timezone(raw)
            try:
                time.clock_settime(time.CLOCK_REALTIME, epoch)
            except (OSError, PermissionError):
                _prepare_timezone(old_raw)
                raise
            _write_root_file(STATE / 'zone', (name + '\n').encode())
        return {'ok': True, 'time': {'timezone': name, 'automatic': False}}
    except (OSError, subprocess.SubprocessError):
        raise TimeError('Date and time could not be applied. Please reopen the settings to check the current state.') from None


def read_request(stream):
    raw = stream.read(4097)
    if len(raw) > 4096:
        raise TimeError('Invalid date and time request.')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise TimeError('Invalid date and time request.')
            result[key] = value
        return result
    try:
        return json.loads(raw, object_pairs_hook=unique)
    except (ValueError, TypeError):
        raise TimeError('Invalid date and time request.') from None
