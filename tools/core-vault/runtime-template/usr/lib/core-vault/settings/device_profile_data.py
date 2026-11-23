"""Portable, strictly allowlisted display/keyboard/pointer preferences.

This is not a home-directory backup. No clock timestamp, network credential,
wallet data, arbitrary filename or executable command can occur in the schema.
The same file format is used by Node and Vault; application remains local.
"""
import importlib
import json
import math
import os
from pathlib import Path
import stat
import sys

MAX_BYTES = 131072
KIND = 'bitcoin-core-device-settings'


class ProfileError(ValueError):
    pass


def require(value, message='Please choose a valid device-settings profile.'):
    if not value:
        raise ProfileError(message)


def backends(product):
    require(product in ('node', 'vault'))
    return (importlib.import_module('desktop_input' if product == 'node' else 'vault_input'),
            importlib.import_module('pointer_control' if product == 'node' else 'vault_pointer'))


def display_backend(product):
    directory = Path('/usr/share/core-desktop')
    if not directory.is_dir():
        own = Path(__file__).resolve()
        directory = (own.parents[1] / 'runtime/usr/share/core-desktop' if product == 'node'
                     else own.parents[3] / 'share/core-desktop')
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))
    return importlib.import_module('core_display')


def validate_pointer(value):
    require(isinstance(value, dict) and set(value) == {'schema', 'devices'})
    require(type(value['schema']) is int and value['schema'] == 1)
    devices = value['devices']
    require(isinstance(devices, dict) and len(devices) <= 32)
    for name, speed in devices.items():
        require(isinstance(name, str) and 1 <= len(name) <= 200
                and not any(ord(c) < 32 or ord(c) == 127 for c in name))
        require(type(speed) in (int, float) and math.isfinite(speed) and -1 <= speed <= 1)
    return {'schema': 1, 'devices': {name: round(float(speed), 2) for name, speed in devices.items()}}


def validate(value, product):
    require(isinstance(value, dict) and set(value) == {'kind', 'version', 'input', 'display'})
    require(value['kind'] == KIND and type(value['version']) is int and value['version'] == 1)
    data = value['input']
    require(isinstance(data, dict) and set(data) == {'layout', 'preferences', 'pointer'})
    inputs, _ = backends(product)
    result = {'kind': KIND, 'version': 1, 'input': {
        'layout': inputs.validate_layout(data['layout']),
        'preferences': inputs.validate(data['preferences']),
        'pointer': validate_pointer(data['pointer'])}, 'display': None}
    if value['display'] is not None:
        result['display'] = display_backend(product).validate_profile(value['display'])
    return result


def snapshot(product):
    inputs, pointer = backends(product)
    layout = inputs.read_system_layout() if product == 'node' else inputs.load_layout()
    return validate({'kind': KIND, 'version': 1,
        'input': {'layout': layout, 'preferences': inputs.load(),
                  'pointer': {'schema': 1, 'devices': pointer.load_preferences()}},
        'display': display_backend(product).load_saved(product)}, product)


def read(path, product):
    require(Path(path).is_absolute())
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as source:
        info = os.fstat(source.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_size <= MAX_BYTES)
        raw = source.read(MAX_BYTES + 1)
        require(len(raw) <= MAX_BYTES)
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result)
            result[key] = value
        return result
    try:
        data = json.loads(raw, object_pairs_hook=unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(ProfileError('Invalid number.')))
        return validate(data, product)
    except (ValueError, TypeError, UnicodeError):
        raise ProfileError('Please choose a valid device-settings profile.') from None


def write(path, value, product):
    value = validate(value, product)
    path = Path(path)
    require(path.is_absolute())
    raw = (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()
    require(len(raw) <= MAX_BYTES)
    # A mistaken destination must never replace an existing wallet or backup.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'wb') as target:
            target.write(raw); target.flush(); os.fsync(target.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise


def apply_input(value, product):
    value = validate(value, product)
    inputs, pointer = backends(product)
    request = value['input']
    if product == 'node':
        from ui import admin
        admin('keyboard-settings', request['layout'])
        inputs.apply_keyboard(request['preferences']['keyboard'], layout=request['layout'])
    else:
        inputs.apply_local_layout(request['layout'], request['preferences']['keyboard'])
    inputs.save(request['preferences'])
    inputs.atomic(pointer.PREFS, (json.dumps(request['pointer'], sort_keys=True) + '\n').encode())
    matched = 0
    for device in pointer.get_devices():
        name = device['name']
        if name in request['pointer']['devices']:
            pointer.set_speed(device['id'], request['pointer']['devices'][name]); matched += 1
        if name in request['preferences']['devices']:
            inputs.apply_device(device['id'], request['preferences']['devices'][name])
    return {'ok': True, 'matching_pointer_devices': matched}
