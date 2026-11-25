"""Installed-only, allowlisted device preferences; private user files stay in RAM.

The privileged entry point accepts typed values, never a source/destination path.
Only this small root-owned record is persistent. Live boots cannot read or write
it, and no wall-clock timestamp, wallet, password or home backup is in its schema.
"""
from __future__ import annotations
import fcntl
import importlib
import json
import os
from pathlib import Path
import pwd
import re
import secrets
import stat
import subprocess
import sys

MARKER = Path('/etc/core-vault/installation.json')
CMDLINE = Path('/proc/cmdline')
MOUNTINFO = Path('/proc/self/mountinfo')
STATE_DIR = Path('/var/lib/core-vault-device-settings')
STATE_FILE = 'preferences.json'
RAM_HOME = Path('/run/core-vault/home')
LIMIT = 131072
COMPONENTS = frozenset(('layout', 'input', 'pointer', 'display', 'timezone'))


class DeviceStateError(ValueError):
    pass


def require(value, message='Device preferences could not be saved. Please try again.'):
    if not value:
        raise DeviceStateError(message)


def _decode(raw):
    require(isinstance(raw, (str, bytes)) and len(raw) <= LIMIT)
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'A device-settings field is repeated.')
            result[key] = value
        return result
    try:
        return json.loads(raw, object_pairs_hook=unique,
            parse_constant=lambda _: (_ for _ in ()).throw(DeviceStateError('Invalid device-settings number.')))
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        raise DeviceStateError('The saved device preferences are not valid.') from None


def _filesystem_type(path):
    path = Path(path)
    result, length = None, -1
    for line in MOUNTINFO.read_text().splitlines():
        before, after = line.split(' - ', 1)
        name = re.sub(r'\\([0-7]{3})', lambda m: chr(int(m[1], 8)), before.split()[4])
        mount = Path(name)
        if (path == mount or mount in path.parents) and len(name) > length:
            result, length = after.split()[0], len(name)
    return result


def _root_directory(path):
    info = Path(path).lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022,
            'The device-settings directory is not protected.')


def _protected_parents(path):
    for current in reversed(Path(path).parents):
        _root_directory(current)


def _read_at(directory, name, *, private=True, absent=False):
    try:
        fd = os.open(name, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK,
                     dir_fd=directory)
    except FileNotFoundError:
        if absent:
            return None
        raise
    with os.fdopen(fd, 'rb') as source:
        info = os.fstat(source.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and info.st_nlink == 1
                and info.st_size <= LIMIT and not info.st_mode & (0o077 if private else 0o022),
                'The saved device-settings file is not protected.')
        raw = source.read(LIMIT + 1)
        require(len(raw) <= LIMIT)
    return _decode(raw)


def installed_mode():
    """Read-only installed detection, also safe to call from the regular UI."""
    try:
        if 'boot=live' in CMDLINE.read_text().split() or _filesystem_type(Path('/')) != 'ext4':
            return False
        _protected_parents(MARKER)
        directory = os.open(MARKER.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            marker = _read_at(directory, MARKER.name, private=False)
        finally:
            os.close(directory)
        return (isinstance(marker, dict) and type(marker.get('schema')) is int
                and marker['schema'] == 1 and marker.get('stage') == 'installed-checks-passed'
                and marker.get('storage') == 'persistent-os-with-ram-only-private-home-v1')
    except (OSError, ValueError, IndexError):
        return False


def notice():
    return ('Device preferences are saved on this installed Vault and restored after restart.'
            if installed_mode() else 'Device preferences stay in RAM for this live session.')


def applied_message(subject):
    return subject + (' applied and saved on this Vault.' if installed_mode()
                      else ' applied for this session.')


def _display():
    directory = Path('/usr/share/core-desktop')
    if not directory.is_dir():
        directory = Path(__file__).resolve().parents[3] / 'share/core-desktop'
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))
    return importlib.import_module('core_display')


def _bounded_component(name, value):
    # Match the exact format written into RAM and each existing loader limit.
    limits = {'layout': 4096, 'input': 32768, 'pointer': 8192, 'display': 32768}
    raw = (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()
    require(len(raw) <= limits[name],
            'There are too many device preferences to save. Please reduce the saved device list.')
    return value


def validate_component(name, value):
    require(isinstance(name, str) and name in COMPONENTS, 'That device preference cannot be stored.')
    if name == 'layout':
        return _bounded_component(name, importlib.import_module('vault_input').validate_layout(value))
    if name == 'input':
        return _bounded_component(name, importlib.import_module('vault_input').validate(value))
    if name == 'pointer':
        return _bounded_component(name, importlib.import_module('device_profile_data').validate_pointer(value))
    if name == 'display':
        if value is None:
            return None
        profile = _display().validate_profile(value)
        require(profile['product'] == 'vault', 'The saved display profile must belong to Vault.')
        return _bounded_component(name, profile)
    try:
        # The root store and boot restore must accept the same named zones.
        importlib.import_module('vault_time').zone_file(value)
    except (OSError, ValueError):
        raise DeviceStateError('Please choose a supported time zone.') from None
    return value


def _validate_record(data):
    require(isinstance(data, dict) and set(data) == {'schema', 'preferences'}
            and type(data['schema']) is int and data['schema'] == 1
            and isinstance(data['preferences'], dict)
            and set(data['preferences']) <= COMPONENTS,
            'The saved device preferences are not supported.')
    return {'schema': 1, 'preferences': {
        key: validate_component(key, value) for key, value in data['preferences'].items()}}


def _state_directory(create=False):
    _protected_parents(STATE_DIR)
    if create:
        STATE_DIR.mkdir(mode=0o700, exist_ok=True)
    elif not STATE_DIR.exists():
        return None
    _root_directory(STATE_DIR)
    info = STATE_DIR.lstat()
    require(stat.S_IMODE(info.st_mode) == 0o700, 'The device-settings directory is not private.')
    return os.open(STATE_DIR, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)


def _write_at(directory, name, value, *, owner=0):
    raw = (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()
    require(len(raw) <= LIMIT)
    temporary = '.device-' + secrets.token_hex(12)
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                 0o600, dir_fd=directory)
    try:
        with os.fdopen(fd, 'wb') as target:
            os.fchown(target.fileno(), owner, owner)
            os.fchmod(target.fileno(), 0o600)
            target.write(raw); target.flush(); os.fsync(target.fileno())
        os.replace(temporary, name, src_dir_fd=directory, dst_dir_fd=directory)
        os.fsync(directory)
    finally:
        try:
            os.unlink(temporary, dir_fd=directory)
        except FileNotFoundError:
            pass


def save_component(name, value):
    """Root-only store used by the fixed helper and the time helper."""
    require(os.geteuid() == 0 and installed_mode(),
            'Persistent device preferences require an installed Vault.')
    value = validate_component(name, value)
    directory = _state_directory(create=True)
    lock = None
    try:
        lock = os.open('.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
                       0o600, dir_fd=directory)
        info = os.fstat(lock)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and info.st_nlink == 1
                and not info.st_mode & 0o077, 'The device-settings lock is not protected.')
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = _read_at(directory, STATE_FILE, absent=True)
        state = _validate_record(state) if state is not None else {'schema': 1, 'preferences': {}}
        if name == 'display' and value is None:
            state['preferences'].pop(name, None)
        else:
            state['preferences'][name] = value
        _write_at(directory, STATE_FILE, state)
    finally:
        if lock is not None:
            os.close(lock)
        os.close(directory)
    return True


def persist_component(name, value):
    """Regular-session save: live sessions never invoke the privileged helper."""
    value = validate_component(name, value)
    if not installed_mode():
        return False
    raw = json.dumps({'schema': 1, 'component': name, 'value': value}, separators=(',', ':'))
    require(len(raw.encode()) <= LIMIT)
    try:
        result = subprocess.run(['/usr/bin/pkexec', '/usr/local/libexec/core-vault-device-settings'],
            input=raw, capture_output=True, text=True, timeout=10,
            env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C.UTF-8'})
        require(result.returncode == 0 and _decode(result.stdout) == {'ok': True, 'persistent': True},
                'Device preferences could not be saved for restart. Please try Apply again.')
    except (OSError, subprocess.SubprocessError):
        raise DeviceStateError('Device preferences could not be saved for restart. Please try Apply again.') from None
    return True


def read_request(source):
    data = _decode(source.read(LIMIT + 1))
    require(isinstance(data, dict) and set(data) == {'schema', 'component', 'value'}
            and type(data['schema']) is int and data['schema'] == 1,
            'Please use Device Settings in the active local Vault session.')
    return data['component'], validate_component(data['component'], data['value'])


def _restore_ram_file(relative, value):
    require(_filesystem_type(RAM_HOME) == 'tmpfs', 'Device preferences require the private RAM home.')
    directory = os.open(RAM_HOME, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        home = os.fstat(directory)
        require(home.st_uid == 1000 and stat.S_IMODE(home.st_mode) == 0o700)
        parts = relative.split('/')
        for component in parts[:-1]:
            try:
                os.mkdir(component, mode=0o700, dir_fd=directory)
            except FileExistsError:
                pass
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                            dir_fd=directory)
            info = os.fstat(child)
            require(info.st_uid in (0, 1000) and not info.st_mode & 0o077,
                    'A private settings directory has unsafe ownership or permissions.')
            os.fchown(child, 1000, 1000)
            os.close(directory); directory = child
        try:
            info = os.stat(parts[-1], dir_fd=directory, follow_symlinks=False)
            require(stat.S_ISREG(info.st_mode) and info.st_uid in (0, 1000) and info.st_nlink == 1,
                    'A private settings file is not a regular owned file.')
        except FileNotFoundError:
            pass
        _write_at(directory, parts[-1], value, owner=1000)
    finally:
        os.close(directory)


def restore_at_boot():
    """Called by core-vault-prepare before LightDM; never restores a saved home."""
    require(os.geteuid() == 0)
    if not installed_mode():
        return False
    account = pwd.getpwnam('vault')
    require((account.pw_uid, account.pw_gid, account.pw_dir) == (1000, 1000, '/home/vault'))
    directory = _state_directory()
    if directory is None:
        return False
    try:
        record = _read_at(directory, STATE_FILE, absent=True)
    finally:
        os.close(directory)
    if record is None:
        return False
    data = _validate_record(record)['preferences']
    destinations = {
        'layout': '.config/bitcoin-core-vault/keyboard-layout.json',
        'input': '.config/bitcoin-core-vault/input.json',
        'pointer': '.config/bitcoin-core-vault/pointer.json',
        'display': '.config/core-desktop/display.json',
    }
    for name, relative in destinations.items():
        if name in data and data[name] is not None:
            _restore_ram_file(relative, data[name])
    if 'timezone' in data:
        importlib.import_module('vault_time').apply_timezone_only(data['timezone'])
    return True
