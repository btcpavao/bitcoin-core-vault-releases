"""Offline time settings with explicit clock correction and installed-only saving.

The fixed Polkit helper is the only interactive privileged entry point. A zone
change alone never changes either clock. Live sessions use RAM timezone state
and only the running clock; explicit installed clock corrections also update
and verify the UTC hardware clock. No network time service is enabled.
"""
from datetime import datetime
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import time
from zoneinfo import ZoneInfo, available_timezones

STATE = Path('/run/core-vault-time')
LOCALTIME = Path('/etc/localtime')
TIMEZONE = Path('/etc/timezone')
ZONE_ROOT = Path('/usr/share/zoneinfo')
RTC_ROOT = Path('/sys/class/rtc')
ADJTIME = Path('/etc/adjtime')
CMDLINE = Path('/proc/cmdline')
LIVE_ROOT = Path('/run/live')
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
    for candidate in (STATE / 'zone', TIMEZONE):
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
    if raw is None:
        return value['timezone'], None
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


def _root_directory(path):
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise TimeError('The volatile time-settings directory is not ready.')


def _root_directory_tree(path, root):
    if not path.is_relative_to(root):
        raise TimeError('The volatile time-settings path is not ready.')
    while True:
        _root_directory(path)
        if path == root:
            return
        path = path.parent


def _require_live_ram_etc():
    # Debian live-config recreates /etc/localtime as a zoneinfo symlink.
    # Replacing that directory entry is allowed only in this live RAM layer,
    # never on an installed disk or a persistent live overlay.
    if os.geteuid() != 0 or 'boot=live' not in CMDLINE.read_text().split():
        raise TimeError('The volatile time-settings path is not ready.')
    _root_directory(LOCALTIME.parent)
    result = subprocess.run(
        ['/usr/bin/findmnt', '--json', '-o', 'FSTYPE,OPTIONS', '-T', str(LOCALTIME.parent)],
        text=True, capture_output=True, check=True, timeout=5, env=ENV)
    try:
        rows = json.loads(result.stdout)['filesystems']
        if len(rows) != 1 or rows[0]['fstype'] != 'overlay':
            raise ValueError()
        upper_names = [item[len('upperdir='):] for item in rows[0]['options'].split(',')
                       if item.startswith('upperdir=')]
        if len(upper_names) != 1 or '\\' in upper_names[0]:
            raise ValueError()
        upper = Path(upper_names[0])
        if (not upper.is_absolute() or upper == LIVE_ROOT
                or not upper.is_relative_to(LIVE_ROOT) or upper.resolve(strict=True) != upper):
            raise ValueError()
    except (KeyError, TypeError, ValueError):
        raise TimeError('The live time-settings directory must have a RAM overlay.') from None
    _root_directory_tree(upper, LIVE_ROOT)
    result = subprocess.run(
        ['/usr/bin/findmnt', '-n', '-o', 'FSTYPE', '-T', str(upper)],
        text=True, capture_output=True, check=True, timeout=5, env=ENV)
    if result.stdout.strip() != 'tmpfs':
        raise TimeError('The live time-settings directory must have a RAM overlay.')


def _normalize_live_localtime_link():
    original = LOCALTIME.lstat()
    if not stat.S_ISLNK(original.st_mode) or original.st_uid != 0:
        raise TimeError('The volatile time-settings path is not ready.')
    _require_live_ram_etc()
    source = LOCALTIME.resolve(strict=True)
    if not source.is_relative_to(ZONE_ROOT):
        raise TimeError('The volatile time-settings path is not ready.')
    source = zone_file(source.relative_to(ZONE_ROOT).as_posix())
    _root_directory_tree(source.parent, ZONE_ROOT)
    _regular_root_file(source)
    raw = source.read_bytes()
    # Replace the symlink itself atomically. Never open it for writing or bind
    # onto its zoneinfo target, which is shared by other timezone readers.
    fd, temporary = tempfile.mkstemp(prefix='.core-vault-localtime-', dir=LOCALTIME.parent)
    try:
        with os.fdopen(fd, 'wb') as target:
            os.fchmod(target.fileno(), 0o644)
            target.write(raw)
            target.flush()
            os.fsync(target.fileno())
        current = LOCALTIME.lstat()
        if ((current.st_dev, current.st_ino, current.st_mode, current.st_uid)
                != (original.st_dev, original.st_ino, original.st_mode, original.st_uid)):
            raise TimeError('The volatile time-settings path changed. Please try again.')
        os.replace(temporary, LOCALTIME)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    _regular_root_file(LOCALTIME)


def _prepare_timezone(raw):
    # Installed images retain the regular placeholder. Live-config may replace
    # it with a symlink; normalize only a verified live RAM copy before binding.
    if LOCALTIME.is_symlink():
        _normalize_live_localtime_link()
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


def _prepare_zone_name(name):
    # A regular placeholder is supplied in the image, so the selected name
    # remains in RAM in live mode and is visible to Qt and other readers.
    _regular_root_file(TIMEZONE)
    source = STATE / 'zone'
    _write_root_file(source, (name + '\n').encode())
    mounts = []
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        before, after = line.split(' - ', 1)
        fields = before.split()
        if fields[4] == str(TIMEZONE):
            mounts.append((fields[3], after.split()[0]))
    if mounts:
        if mounts[-1] != ('/core-vault-time/zone', 'tmpfs'):
            raise TimeError('An unexpected mount covers the system timezone name.')
    else:
        subprocess.run(['/usr/bin/mount', '--bind', str(source), str(TIMEZONE)],
                       check=True, capture_output=True, timeout=10, env=ENV)


def _hardware_epoch():
    """Read the RTC used for boot; fixed sysfs paths, never a caller filename."""
    try:
        devices = [p for p in RTC_ROOT.iterdir()
                   if re.fullmatch(r'rtc[0-9]{1,3}', p.name) and p.is_dir()]
        if len(devices) > 32:
            raise ValueError()
        primary = []
        for path in devices:
            try:
                if (path / 'hctosys').read_text().strip() == '1':
                    primary.append(path)
            except OSError:
                pass
        if len(primary) == 1:
            device = primary[0]
        else:
            device = next(p for p in devices if p.name == 'rtc0')
        raw = (device / 'since_epoch').read_text()[:64].strip()
        if not re.fullmatch(r'[0-9]{1,12}', raw):
            raise ValueError()
        return int(raw)
    except (OSError, ValueError, StopIteration):
        raise TimeError('The running clock was updated, but this device has no readable hardware clock. '
                        'The time may be incorrect after restarting.') from None


def _set_installed_clock(epoch):
    """Explicit installed action only. timedated can ignore RTC errors: verify."""
    try:
        # Do not pass --adjust-system-clock: the user's entered time is the
        # authority. UTC avoids local-RTC/DST reinterpretation on the next boot.
        subprocess.run(['/usr/bin/timedatectl', '--no-ask-password', 'set-local-rtc', '0'],
                       check=True, text=True, capture_output=True, timeout=10, env=ENV)
        try:
            lines = ADJTIME.read_text().splitlines()
        except FileNotFoundError:
            lines = ['0', '0', 'UTC']  # systemd/hwclock's default when absent.
        if len(lines) < 3 or lines[2].strip() != 'UTC':
            raise TimeError('The hardware clock could not be configured for UTC. '
                            'Please reopen Date & Time to check the current state.')
        subprocess.run(['/usr/bin/timedatectl', '--no-ask-password', 'set-time', '@' + str(epoch)],
                       check=True, text=True, capture_output=True, timeout=10, env=ENV)
    except (OSError, subprocess.SubprocessError):
        raise TimeError('Manual clock correction could not be completed. '
                        'Please reopen Date & Time to check the current clock.') from None
    try:
        if abs(_hardware_epoch() - time.time()) > 5:
            raise TimeError('The running clock was updated, but the hardware clock did not keep the new time. '
                            'The time may be incorrect after restarting.')
    except TimeError as error:
        return str(error)
    return None


def _apply_runtime(name, epoch, installed_clock=False):
    if os.geteuid() != 0:
        raise TimeError('Please use the local Vault time-settings helper.')
    raw = zone_file(name).read_bytes()
    warning = None
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
                _prepare_zone_name(name)
                time.tzset()
                if epoch is not None:
                    if installed_clock:
                        warning = _set_installed_clock(epoch)
                    else:
                        time.clock_settime(time.CLOCK_REALTIME, epoch)
            except (TimeError, OSError, subprocess.SubprocessError):
                _prepare_timezone(old_raw)
                _prepare_zone_name(before)
                time.tzset()
                raise
        return warning
    except (OSError, subprocess.SubprocessError):
        raise TimeError('Date and time changes could not be completed. '
                        'Please reopen the settings to check the current state.') from None


def apply_timezone_only(name):
    """Boot restore: RAM timezone only; never touch the clocks or saved store."""
    name, _ = validate_request({'timezone': name, 'local_time': None})
    _apply_runtime(name, None)
    return {'ok': True, 'time': {'timezone': name, 'automatic': False}}


def apply_settings(value):
    name, epoch = validate_request(value)
    if os.geteuid() != 0:
        raise TimeError('Please use the local Vault time-settings helper.')
    from vault_device_state import installed_mode, save_component
    installed = installed_mode()
    warning = _apply_runtime(name, epoch, installed_clock=installed and epoch is not None)
    if installed:
        try:
            save_component('timezone', name)
        except (OSError, ValueError, RuntimeError):
            message = 'The time zone was applied, but it could not be saved for the next startup.'
            if warning:
                message += ' ' + warning
            raise TimeError(message + ' Please check the current settings.') from None
    if warning:
        # Surface partial success through the helper and GUI instead of hiding
        # it behind timedated's successful exit code.
        raise TimeError('The time zone was saved. ' + warning)
    return {'ok': True, 'time': {'timezone': name, 'automatic': False},
            'persistent': installed, 'clock_changed': epoch is not None,
            'rtc_saved': installed and epoch is not None}


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
