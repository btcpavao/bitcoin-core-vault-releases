#!/usr/bin/python3
"""User-session RandR controls shared by Bitcoin Core Node and Vault.

The GUI sends only a bounded declarative layout. An independent child process
owns each change and restores the old state if its input closes or confirmation
does not arrive. This module never runs a shell or asks for administrative access.
"""
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import select
import signal
import stat
import subprocess
import sys
import tempfile
import time
from typing import Callable

XRANDR = '/usr/bin/xrandr'
XRDB = '/usr/bin/xrdb'
SCALE_HELPER = '/usr/local/bin/core-display-scale'
PROFILE_KIND = 'bitcoin-core-display-settings'
PROFILE_LIMIT = 32768
MAX_OUTPUTS = 16
CONFIRM_SECONDS = 15
NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:+-]{0,127}\Z')
ROTATIONS = ('normal', 'left', 'right', 'inverted')
ARRANGEMENTS = ('right', 'left', 'above', 'below')
PRESETS = ('built-in', 'mirror', 'extend', 'external', 'custom')
IDENTITY = ('1', '0', '0', '0', '1', '0', '0', '0', '1')


class DisplayError(ValueError):
    """A bounded message that is safe to display to the local user."""


def require(condition, message):
    if not condition:
        raise DisplayError(message)


def product_name(product):
    require(product in ('node', 'vault'), 'Please choose Node or Vault.')
    return product


def validate_scale(value):
    if value == 'auto':
        return 'auto'
    require(not isinstance(value, bool) and isinstance(value, (str, int, float)),
            'Interface size must be Automatic or a number from 100% to 300%.')
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise DisplayError('Interface size must be Automatic or a number from 100% to 300%.') from None
    require(result.is_finite() and 1 <= result <= 3,
            'Interface size must be between 100% and 300%.')
    return format(result.normalize(), 'f')


def rate_text(value):
    require(not isinstance(value, bool) and isinstance(value, (str, int, float)),
            'The display refresh rate is invalid.')
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise DisplayError('The display refresh rate is invalid.') from None
    # Some virtual X11 outputs report a zero clock (automatic/unspecified).
    # Keep that reported mode usable without issuing an explicit --rate value.
    require(number.is_finite() and (number == 0 or 1 <= number <= 1000),
            'The display refresh rate is invalid.')
    return format(number.normalize(), 'f')


def _name(value, description):
    require(isinstance(value, str) and NAME.fullmatch(value),
            'The ' + description + ' name is invalid.')
    return value


def _exact(value, keys, message):
    require(type(value) is dict and set(value) == set(keys), message)


def _integer(value, low, high, message):
    require(type(value) is int and low <= value <= high, message)
    return value


def validate_layout(value):
    _exact(value, ('outputs', 'scale', 'preset', 'arrangement'),
           'The display layout has unsupported or missing settings.')
    require(type(value['outputs']) is list and 1 <= len(value['outputs']) <= MAX_OUTPUTS,
            'Please keep at least one display enabled.')
    outputs = []
    for output in value['outputs']:
        _exact(output, ('name', 'mode', 'rate', 'x', 'y', 'rotation', 'primary'),
               'A display has unsupported or missing settings.')
        require(output['rotation'] in ROTATIONS, 'The display rotation is invalid.')
        require(type(output['primary']) is bool, 'The primary display setting is invalid.')
        outputs.append(dict(name=_name(output['name'], 'display'),
                            mode=_name(output['mode'], 'resolution'),
                            rate=rate_text(output['rate']),
                            x=_integer(output['x'], 0, 65535, 'The horizontal display position is invalid.'),
                            y=_integer(output['y'], 0, 65535, 'The vertical display position is invalid.'),
                            rotation=output['rotation'], primary=output['primary']))
    require(len({o['name'] for o in outputs}) == len(outputs), 'A display is listed more than once.')
    require(sum(o['primary'] for o in outputs) == 1, 'Please choose one primary display.')
    require(value['preset'] in PRESETS, 'The display mode is invalid.')
    require(value['arrangement'] in ARRANGEMENTS, 'The display arrangement is invalid.')
    return dict(outputs=outputs, scale=validate_scale(value['scale']),
                preset=value['preset'], arrangement=value['arrangement'])


def validate_profile(value):
    """Validate an imported/saved profile without using a display connection."""
    _exact(value, ('kind', 'version', 'product', 'hardware', 'layout'),
           'This file is not a supported display settings profile.')
    require(value['kind'] == PROFILE_KIND and type(value['version']) is int and value['version'] == 1,
            'This file is not a supported display settings profile.')
    product_name(value['product'])
    require(type(value['hardware']) is list and 1 <= len(value['hardware']) <= MAX_OUTPUTS,
            'The display profile has an invalid hardware list.')
    hardware = []
    for monitor in value['hardware']:
        _exact(monitor, ('name', 'edid'), 'The display profile has unsupported hardware settings.')
        edid = monitor['edid']
        require(edid is None or (isinstance(edid, str) and re.fullmatch(r'[0-9a-f]{64}', edid)),
                'The display identity is invalid.')
        hardware.append(dict(name=_name(monitor['name'], 'display'), edid=edid))
    require(len({o['name'] for o in hardware}) == len(hardware), 'A display identity is listed more than once.')
    layout = validate_layout(value['layout'])
    require({o['name'] for o in layout['outputs']} <= {o['name'] for o in hardware},
            'The layout refers to a display missing from its hardware list.')
    return dict(kind=PROFILE_KIND, version=1, product=value['product'],
                hardware=sorted(hardware, key=lambda item: item['name']), layout=layout)


def _no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'The settings file repeats a field.')
        result[key] = value
    return result


def decode_json(raw):
    require(isinstance(raw, (str, bytes)) and len(raw) <= PROFILE_LIMIT, 'The settings file is too large.')
    try:
        return json.loads(raw, object_pairs_hook=_no_duplicates,
                          parse_constant=lambda _: (_ for _ in ()).throw(DisplayError('The settings contain an invalid number.')))
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        raise DisplayError('The settings file is not valid JSON.') from None


def read_profile(path):
    """Bounded regular-file read. No pickles, archives, paths or code in profiles."""
    fd = os.open(os.fspath(path), os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        require(stat.S_ISREG(os.fstat(fd).st_mode), 'Please choose a regular display settings file.')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            raw = stream.read(PROFILE_LIMIT + 1)
        return validate_profile(decode_json(raw))
    finally:
        os.close(fd)


def profile_path(product):
    product_name(product)
    home = Path('/home/vault') if product == 'vault' else Path.home()
    return home / '.config/core-desktop/display.json'


def _filesystem_type(path):
    path = Path(path).resolve()
    result, longest = None, -1
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        before, after = line.split(' - ', 1)
        mount = before.split()[4]
        mount = re.sub(r'\\([0-7]{3})', lambda m: chr(int(m[1], 8)), mount)
        if (path == Path(mount) or Path(mount) in path.parents) and len(mount) > longest:
            result, longest = after.split()[0], len(mount)
    return result


def load_saved(product):
    try:
        path = profile_path(product)
        if product == 'vault':
            _assert_vault_profile_path(path)
        value = read_profile(path)
        require(value['product'] == product_name(product), 'This saved profile belongs to a different desktop.')
        return value
    except (OSError, DisplayError):
        return None


def _assert_vault_profile_path(path):
    expected = Path('/home/vault/.config/core-desktop/display.json')
    require(path == expected, 'Vault preferences require the fixed private RAM workspace.')
    for current in (Path('/home/vault'), Path('/home/vault/.config'),
                    Path('/home/vault/.config/core-desktop'), path):
        require(not current.is_symlink(), 'Vault preferences cannot use a symbolic-link destination.')
    require(_filesystem_type(path.parent) == 'tmpfs',
            'Vault display preferences require the private RAM workspace.')


def atomic_write(path, raw):
    """Publish complete local preference files, not partial JSON on interruption."""
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    require(not path.is_symlink(), 'The settings destination must not be a symbolic link.')
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw if isinstance(raw, bytes) else raw.encode())
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def save_profile(product, value):
    value = validate_profile(value)
    value['product'] = product_name(product)
    path = profile_path(product)
    if product == 'vault':
        _assert_vault_profile_path(path)
    atomic_write(path, json.dumps(value, indent=2, sort_keys=True) + '\n')
    return value


def export_profile(path, value):
    value = validate_profile(value)
    atomic_write(path, json.dumps(value, indent=2, sort_keys=True) + '\n')


@dataclass
class Mode:
    name: str
    width: int
    height: int
    rates: list[str] = field(default_factory=list)
    preferred: bool = False


@dataclass
class Output:
    name: str
    connected: bool
    primary: bool = False
    width: int = 0
    height: int = 0
    x: int = 0
    y: int = 0
    rotation: str = 'normal'
    rotations: tuple[str, ...] = ('normal',)
    reflection: str = 'normal'
    mode: str | None = None
    rate: str | None = None
    modes: list[Mode] = field(default_factory=list)
    edid: str | None = None
    millimetres: tuple[int, int] = (0, 0)
    transform: tuple[str, ...] = IDENTITY
    panning: str = '0x0'

    @property
    def active(self):
        return self.connected and self.mode is not None and self.width > 0 and self.height > 0

    @property
    def builtin(self):
        return bool(re.match(r'^(?:eDP|LVDS|DSI)(?:-|\d|$)', self.name))

    @property
    def label(self):
        return ('Built-in display' if self.builtin else 'External display') + ' — ' + self.name

    def find_mode(self, name):
        return next((mode for mode in self.modes if mode.name == name), None)

    def preferred_mode(self):
        return next((mode for mode in self.modes if mode.preferred), self.modes[0] if self.modes else None)


@dataclass
class Snapshot:
    outputs: list[Output]
    maximum: tuple[int, int] = (32767, 32767)

    @property
    def connected(self):
        return [output for output in self.outputs if output.connected]

    @property
    def active(self):
        return [output for output in self.outputs if output.active]

    def find(self, name):
        return next((output for output in self.outputs if output.name == name and output.connected), None)

    def hardware(self):
        return sorted([dict(name=output.name, edid=output.edid) for output in self.connected],
                      key=lambda item: item['name'])

    def topology(self):
        data = [(o.name, o.edid, [(m.name, m.rates) for m in o.modes]) for o in self.connected]
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def parse_query(text):
    """Parse xrandr --query --props, including connected but disabled outputs."""
    require(isinstance(text, str) and len(text) <= 1024 * 1024, 'The display query is too large.')
    outputs, current, edid_lines = [], None, None
    maximum = (32767, 32767)

    def finish_edid():
        nonlocal edid_lines
        if current is not None and edid_lines:
            data = ''.join(edid_lines)
            if len(data) >= 256 and len(data) % 256 == 0 and len(data) <= 8192:
                current.edid = hashlib.sha256(bytes.fromhex(data)).hexdigest()
        edid_lines = None

    for line in text.splitlines():
        screen = re.match(r'^Screen .*maximum (\d+) x (\d+)', line)
        if screen:
            maximum = tuple(min(65535, int(n)) for n in screen.groups())
        header = re.match(r'^(\S+) (connected|disconnected)(?: (primary))?(?: (\d+)x(\d+)([+-]\d+)([+-]\d+))?(.*)$', line)
        if header:
            finish_edid()
            name, state, primary, width, height, x, y, rest = header.groups()
            _name(name, 'display')
            require(len(outputs) < MAX_OUTPUTS, 'Too many display outputs were reported.')
            current = Output(name=name, connected=state == 'connected', primary=bool(primary))
            if width:
                current.width, current.height = int(width), int(height)
                current.x, current.y = int(x), int(y)
            prefix = rest.split('(', 1)[0]
            rotation = re.search(r'\b(normal|left|right|inverted)\b', prefix)
            if rotation:
                current.rotation = rotation[1]
            capabilities = re.search(r'\((normal(?:\s+\w+)*)\)', rest)
            if capabilities:
                current.rotations = tuple(word for word in capabilities[1].split() if word in ROTATIONS)
            if 'x axis' in prefix and 'y axis' in prefix:
                current.reflection = 'xy'
            elif 'x axis' in prefix:
                current.reflection = 'x'
            elif 'y axis' in prefix:
                current.reflection = 'y'
            size = re.search(r'(\d+)mm x (\d+)mm', rest)
            if size:
                current.millimetres = tuple(int(n) for n in size.groups())
            outputs.append(current)
            continue
        if current is None:
            continue
        if line.strip() == 'EDID:':
            finish_edid()
            edid_lines = []
            continue
        if edid_lines is not None:
            if re.fullmatch(r'\s+[0-9a-fA-F]{32}\s*', line):
                edid_lines.append(line.strip().lower())
                continue
            finish_edid()
        candidate = re.match(r'^\s{2,}(\S+)\s+((?:\d+(?:\.\d+)?[+*]*\s*)+)$', line)
        if candidate:
            mode_name, values = candidate.groups()
            geometry = re.match(r'^(\d+)x(\d+)', mode_name)
            if not geometry or not NAME.fullmatch(mode_name):
                continue
            rates, preferred = [], False
            for value in values.split():
                rate = rate_text(value.rstrip('*+'))
                if rate not in rates:
                    rates.append(rate)
                if '+' in value:
                    preferred = True
                if '*' in value:
                    current.mode, current.rate = mode_name, rate
            current.modes.append(Mode(mode_name, int(geometry[1]), int(geometry[2]), rates, preferred))
    finish_edid()
    require(outputs, 'No display outputs were reported by the X server.')
    require(all(not o.active or o.rate is not None for o in outputs), 'An active display has no reported refresh rate.')
    return Snapshot(outputs, maximum)


def add_transforms(snapshot, verbose):
    """Retain transforms/panning for rollback; profiles cannot request these."""
    current, matrix = None, []
    expected = {o.name for o in snapshot.connected}
    seen = set()
    for line in verbose.splitlines():
        header = re.match(r'^(\S+) (connected|disconnected)\b', line)
        if header:
            current = snapshot.find(header[1])
            if header[2] == 'connected':
                seen.add(header[1])
            matrix = []
            continue
        if current is None:
            continue
        transform = re.match(r'^\s*Transform:\s*(.*)$', line)
        if transform:
            matrix = transform[1].split()
            continue
        if matrix and len(matrix) < 9:
            matrix.extend(line.strip().split())
            if len(matrix) == 9:
                try:
                    values = [float(v) for v in matrix]
                except ValueError:
                    raise DisplayError('The current display transform could not be read.') from None
                require(all(math.isfinite(v) and abs(v) <= 65536 for v in values),
                        'The current display transform is invalid.')
                current.transform = tuple(matrix)
            elif len(matrix) > 9:
                raise DisplayError('The current display transform could not be read.')
            continue
        panning = re.match(r'^\s*Panning:?\s*(\d+x\d+(?:[+-]\d+[+-]\d+)?)', line, re.IGNORECASE)
        if panning:
            current.panning = panning[1]
    require(seen == expected, 'The connected displays changed. Please refresh the list.')


def layout_from_snapshot(snapshot, scale='auto'):
    outputs = []
    for monitor in snapshot.active:
        outputs.append(dict(name=monitor.name, mode=monitor.mode, rate=monitor.rate,
                            x=max(0, monitor.x), y=max(0, monitor.y), rotation=monitor.rotation,
                            primary=monitor.primary))
    require(outputs, 'No active display is available.')
    if not any(output['primary'] for output in outputs):
        outputs[0]['primary'] = True
    elif sum(output['primary'] for output in outputs) != 1:
        first = next(output['name'] for output in outputs if output['primary'])
        for output in outputs:
            output['primary'] = output['name'] == first
    preset = 'custom'
    if len(outputs) == 1:
        preset = 'built-in' if snapshot.find(outputs[0]['name']).builtin else 'external'
    elif all((o['x'], o['y'], o['mode']) == (outputs[0]['x'], outputs[0]['y'], outputs[0]['mode']) for o in outputs):
        preset = 'mirror'
    else:
        preset = 'extend'
    return validate_layout(dict(outputs=outputs, scale=scale, preset=preset, arrangement='right'))


def make_profile(product, snapshot, layout):
    return validate_profile(dict(kind=PROFILE_KIND, version=1, product=product_name(product),
                                 hardware=snapshot.hardware(), layout=layout))


def matches_hardware(profile, snapshot, automatic=False):
    profile = validate_profile(profile)
    hardware = profile['hardware']
    if automatic and any(monitor['edid'] is None for monitor in hardware):
        return False
    return hardware == snapshot.hardware()


def validate_live_layout(layout, snapshot):
    layout = validate_layout(layout)
    width, height = 0, 0
    for config in layout['outputs']:
        output = snapshot.find(config['name'])
        require(output is not None, 'A selected display is no longer connected. Please refresh the list.')
        mode = output.find_mode(config['mode'])
        require(mode is not None, 'The selected resolution is no longer available.')
        require(config['rate'] in mode.rates, 'The selected refresh rate is no longer available.')
        require(config['rotation'] in output.rotations, 'The selected display does not support this orientation.')
        w, h = (mode.height, mode.width) if config['rotation'] in ('left', 'right') else (mode.width, mode.height)
        width, height = max(width, config['x'] + w), max(height, config['y'] + h)
    require(width <= snapshot.maximum[0] and height <= snapshot.maximum[1],
            'This arrangement is larger than the graphics hardware supports.')
    if layout['preset'] == 'mirror':
        first = layout['outputs'][0]
        first_mode = snapshot.find(first['name']).find_mode(first['mode'])
        require(all((snapshot.find(o['name']).find_mode(o['mode']).width,
                     snapshot.find(o['name']).find_mode(o['mode']).height,
                     o['rate'], o['x'], o['y'], o['rotation']) ==
                    (first_mode.width, first_mode.height, first['rate'], first['x'], first['y'], first['rotation'])
                    for o in layout['outputs']),
                'Mirrored displays need a shared resolution, refresh rate and orientation.')
    return layout


def command_for_layout(layout, snapshot):
    layout = validate_live_layout(layout, snapshot)
    # RandR stores one primary output globally. --primary replaces it; combining
    # it with --noprimary causes xrandr to clear the result at the end.
    args = [XRANDR]
    enabled = {item['name'] for item in layout['outputs']}
    # Configure enabled outputs before disabled ones; xrandr commits one request.
    for item in layout['outputs']:
        args += ['--output', item['name'], '--mode', item['mode']]
        if item['rate'] != '0':
            args += ['--rate', item['rate']]
        args += ['--rotate', item['rotation'], '--reflect', 'normal', '--transform', 'none',
                 '--pos', str(item['x']) + 'x' + str(item['y'])]
        if _panning_enabled(snapshot.find(item['name']).panning):
            args += ['--panning', '0x0']
        if item['primary']:
            args.append('--primary')
    for output in snapshot.connected:
        if output.name not in enabled:
            args += ['--output', output.name, '--off']
    return args


def _panning_enabled(value):
    size = re.match(r'^(\d+)x(\d+)', value)
    return size is not None and (int(size[1]) != 0 or int(size[2]) != 0)


def _transform_argument(values):
    return 'none' if tuple(float(v) for v in values) == tuple(float(v) for v in IDENTITY) else ','.join(values)


def active_matches(layout, snapshot):
    expected = {item['name'] for item in layout['outputs']}
    if expected != {output.name for output in snapshot.active}:
        return False
    for item in layout['outputs']:
        output = snapshot.find(item['name'])
        if not output or (output.mode, output.x, output.y, output.rotation, output.primary) != (
                item['mode'], item['x'], item['y'], item['rotation'], item['primary']):
            return False
        if output.rate is None or abs(float(output.rate) - float(item['rate'])) > 0.025:
            return False
    return True


class Backend:
    def __init__(self, runner=None):
        self.runner = runner or subprocess.run

    def _run(self, args, input=None, timeout=8):
        try:
            result = self.runner(args, input=input, capture_output=True, text=True, timeout=timeout,
                                 env=dict(os.environ, LC_ALL='C', LANG='C'))
        except (OSError, subprocess.TimeoutExpired):
            raise DisplayError('The display service did not respond. Please try again.') from None
        require(result.returncode == 0, 'The graphics hardware could not apply these display settings.')
        return result.stdout

    def probe(self, transforms=False):
        snapshot = parse_query(self._run([XRANDR, '--query', '--props']))
        if transforms:
            add_transforms(snapshot, self._run([XRANDR, '--verbose']))
        return snapshot

    def apply(self, layout, snapshot=None):
        snapshot = snapshot or self.probe(transforms=True)
        self._run(command_for_layout(layout, snapshot))

    def capture_scale(self):
        resources = self._run([XRDB, '-query'])
        match = re.search(r'^Xft\.dpi:\s*(\d+(?:\.\d+)?)\s*$', resources, re.MULTILINE)
        dpi = float(match[1]) if match else 96
        require(math.isfinite(dpi) and 24 <= dpi <= 1000, 'The current interface size could not be read.')
        return dpi

    def capture_runtime_scale(self):
        runtime = os.environ.get('XDG_RUNTIME_DIR')
        if runtime:
            try:
                with (Path(runtime) / 'core-display-scale.json').open('rb') as stream:
                    raw = stream.read(PROFILE_LIMIT + 1)
                if len(raw) <= PROFILE_LIMIT:
                    return raw
            except OSError:
                pass
        return None

    def set_scale(self, scale):
        self._run([SCALE_HELPER, '--scale', validate_scale(scale)])

    def restore_scale(self, dpi):
        require(isinstance(dpi, (float, int)) and math.isfinite(dpi) and 24 <= dpi <= 1000,
                'The previous interface size is invalid.')
        if getattr(self, 'restored_to_fallback', False):
            # A removed high-DPI monitor may have left only a small laptop panel.
            # Reuse the existing fit cap instead of making controls unreachable.
            self.set_scale(str(max(1, min(3, dpi / 96))))
            return
        self._run([XRDB, '-nocpp', '-merge'], input='Xft.dpi: ' + str(dpi) + '\n')
        runtime = os.environ.get('XDG_RUNTIME_DIR')
        if runtime and hasattr(self, 'scale_record'):
            path = Path(runtime) / 'core-display-scale.json'
            if self.scale_record is not None:
                atomic_write(path, self.scale_record)
            else:
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass

    def fallback(self, snapshot=None):
        self.restored_to_fallback = True
        snapshot = snapshot or self.probe()
        candidates = [o for o in snapshot.connected if o.modes]
        require(candidates, 'No usable display is connected.')
        monitor = next((o for o in candidates if o.builtin), next((o for o in candidates if o.active), candidates[0]))
        # Keep other working outputs; enable the built-in/available screen safely.
        args = [XRANDR, '--output', monitor.name, '--auto', '--primary', '--rotate', 'normal',
                '--reflect', 'normal', '--transform', 'none', '--pos', '0x0']
        if _panning_enabled(monitor.panning):
            args += ['--panning', '0x0']
        self._run(args)

    def restore(self, before):
        self.restored_to_fallback = False
        current = self.probe(transforms=True)
        compatible = []
        for previous in before.active:
            now = current.find(previous.name)
            if (now is not None and now.edid == previous.edid and now.find_mode(previous.mode)
                    and previous.rate in now.find_mode(previous.mode).rates):
                compatible.append(previous)
        if not compatible:
            self.fallback(current)
            return
        self.restored_to_fallback = {o.name for o in compatible} != {o.name for o in before.active}
        names = {output.name for output in compatible}
        args = [XRANDR]
        if not any(o.primary for o in compatible) and not self.restored_to_fallback:
            args.append('--noprimary')
        for output in compatible:
            args += ['--output', output.name, '--mode', output.mode]
            if output.rate != '0':
                args += ['--rate', output.rate]
            args += ['--rotate', output.rotation, '--reflect', output.reflection,
                     '--transform', _transform_argument(output.transform),
                     '--pos', str(max(0, output.x)) + 'x' + str(max(0, output.y))]
            if _panning_enabled(output.panning) or _panning_enabled(current.find(output.name).panning):
                args += ['--panning', output.panning]
            if output.primary or (self.restored_to_fallback and not any(o.primary for o in compatible) and output is compatible[0]):
                args.append('--primary')
        # A newly connected output is left alone; only outputs present in the
        # original snapshot are restored to their original disabled state.
        for output in current.connected:
            previous = before.find(output.name)
            if output.name not in names and previous is not None and output.edid == previous.edid:
                args += ['--output', output.name, '--off']
        try:
            self._run(args)
        except DisplayError:
            self.fallback()


def runtime_directory():
    base = os.environ.get('XDG_RUNTIME_DIR')
    require(base and os.path.isabs(base), 'A local desktop session is required.')
    base = Path(base)
    info = base.stat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid() and not (info.st_mode & 0o077),
            'The desktop runtime directory is not private.')
    directory = base / 'core-display'
    directory.mkdir(mode=0o700, exist_ok=True)
    info = directory.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid() and not (info.st_mode & 0o077),
            'The display runtime directory is not private.')
    return directory


class SessionLock:
    def __enter__(self):
        self.fd = os.open(runtime_directory() / 'settings.lock',
                          os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
        info = os.fstat(self.fd)
        try:
            require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid(), 'The display lock is invalid.')
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, DisplayError):
            os.close(self.fd)
            self.fd = None
            raise DisplayError('Another display change is in progress. Please finish or cancel it first.') from None
        return self

    def __exit__(self, *_):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


def _read_line(fd, timeout, limit=PROFILE_LIMIT):
    deadline, data = time.monotonic() + timeout, bytearray()
    while time.monotonic() < deadline:
        available, _, _ = select.select([fd], [], [], max(0, deadline - time.monotonic()))
        if not available:
            break
        chunk = os.read(fd, 1)
        if not chunk:
            return None
        if chunk == b'\n':
            return bytes(data)
        data.extend(chunk)
        require(len(data) <= limit, 'The display request is too large.')
    return None


def _emit(value):
    try:
        sys.stdout.write(json.dumps(value, separators=(',', ':')) + '\n')
        sys.stdout.flush()
    except (BrokenPipeError, OSError):
        pass


def _pending_path():
    return runtime_directory() / 'pending.json'


def _read_pending(product):
    path = _pending_path()
    try:
        fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid(), 'The pending display change is invalid.')
        raw = os.read(fd, PROFILE_LIMIT + 1)
    finally:
        os.close(fd)
    data = decode_json(raw)
    _exact(data, ('version', 'product', 'before', 'transforms', 'dpi', 'previous_profile',
                  'runtime_scale', 'replacing_preferences'), 'The pending display change has unsupported fields.')
    require(type(data['version']) is int and data['version'] == 1 and data['product'] == product_name(product),
            'The pending display change belongs to a different desktop.')
    data['before'] = validate_profile(data['before'])
    require(type(data['dpi']) in (int, float) and math.isfinite(data['dpi']) and 24 <= data['dpi'] <= 1000,
            'The pending interface size is invalid.')
    require(type(data['replacing_preferences']) is bool, 'The pending display state is invalid.')
    if data['previous_profile'] is not None:
        data['previous_profile'] = validate_profile(data['previous_profile'])
    if data['runtime_scale'] is not None:
        require(isinstance(data['runtime_scale'], str), 'The previous interface preferences are invalid.')
        old = decode_json(data['runtime_scale'])
        require(type(old) is dict and 'scale' in old, 'The previous interface preferences are invalid.')
        validate_scale(old['scale'])
    require(type(data['transforms']) is list and len(data['transforms']) <= MAX_OUTPUTS,
            'The pending display transforms are invalid.')
    seen = set()
    for item in data['transforms']:
        _exact(item, ('name', 'matrix', 'reflection', 'panning', 'primary'), 'The pending display transform is invalid.')
        require(type(item['primary']) is bool, 'The previous primary output setting is invalid.')
        _name(item['name'], 'display')
        require(item['name'] not in seen, 'The pending display transform is repeated.')
        seen.add(item['name'])
        require(type(item['matrix']) is list and len(item['matrix']) == 9, 'The pending display matrix is invalid.')
        for value in item['matrix']:
            require(isinstance(value, str) and re.fullmatch(r'-?\d+(?:\.\d+)?', value),
                    'The pending display matrix is invalid.')
            require(math.isfinite(float(value)) and abs(float(value)) <= 65536,
                    'The pending display matrix is invalid.')
        require(item['reflection'] in ('normal', 'x', 'y', 'xy'), 'The pending reflection is invalid.')
        require(isinstance(item['panning'], str) and re.fullmatch(r'\d{1,5}x\d{1,5}(?:[+-]\d{1,5}[+-]\d{1,5})?', item['panning']),
                'The pending display panning is invalid.')
    require(seen == {o['name'] for o in data['before']['layout']['outputs']},
            'The pending display transform list does not match its outputs.')
    return data


def _write_pending(product, before, dpi, backend):
    runtime_scale = getattr(backend, 'scale_record', None)
    if runtime_scale is not None:
        try:
            raw = decode_json(runtime_scale)
            validate_scale(raw['scale'])
            runtime_scale = runtime_scale.decode()
        except (DisplayError, UnicodeError, KeyError, TypeError):
            runtime_scale = None
    data = dict(version=1, product=product_name(product),
                before=make_profile(product, before, layout_from_snapshot(before)),
                transforms=[dict(name=o.name, matrix=list(o.transform), reflection=o.reflection, primary=o.primary,
                                 panning=o.panning) for o in before.active],
                dpi=dpi, previous_profile=load_saved(product), runtime_scale=runtime_scale,
                replacing_preferences=False)
    raw = json.dumps(data, separators=(',', ':')) + '\n'
    require(len(raw.encode()) <= PROFILE_LIMIT, 'The current display configuration is too large to save safely.')
    atomic_write(_pending_path(), raw)


def _snapshot_from_pending(data):
    hardware = {item['name']: item['edid'] for item in data['before']['hardware']}
    transforms = {item['name']: item for item in data['transforms']}
    configs = {item['name']: item for item in data['before']['layout']['outputs']}
    outputs = []
    for name, edid in hardware.items():
        output = Output(name=name, connected=True, edid=edid)
        if name in configs:
            item = configs[name]
            dimensions = re.match(r'^(\d+)x(\d+)', item['mode'])
            require(dimensions is not None, 'The previous display mode cannot be restored.')
            width, height = int(dimensions[1]), int(dimensions[2])
            require(0 < width <= 65535 and 0 < height <= 65535, 'The previous display size is invalid.')
            output.modes = [Mode(item['mode'], width, height, [item['rate']])]
            output.mode, output.rate = item['mode'], item['rate']
            output.width, output.height = (height, width) if item['rotation'] in ('left', 'right') else (width, height)
            output.x, output.y = item['x'], item['y']
            output.rotation, output.primary = item['rotation'], transforms[name]['primary']
            output.transform = tuple(transforms[name]['matrix'])
            output.reflection = transforms[name]['reflection']
            output.panning = transforms[name]['panning']
        outputs.append(output)
    return Snapshot(outputs)


def _clear_pending():
    try:
        _pending_path().unlink()
    except FileNotFoundError:
        pass


def _recover_pending_locked(product, backend):
    data = _read_pending(product)
    if data is None:
        return False
    before = _snapshot_from_pending(data)
    backend.scale_record = data['runtime_scale'].encode() if data['runtime_scale'] is not None else None
    backend.restore(before)
    backend.restore_scale(data['dpi'])
    if data['replacing_preferences']:
        if data['previous_profile'] is not None:
            save_profile(product, data['previous_profile'])
        else:
            try:
                profile_path(product).unlink()
            except FileNotFoundError:
                pass
    _clear_pending()
    return True


def recover_abandoned(product, backend=None):
    """Recover a dead worker. The session lock proves no live worker owns it."""
    with SessionLock():
        return _recover_pending_locked(product_name(product), backend or Backend())


def transaction(product, backend=None, timeout=CONFIRM_SECONDS):
    """Own apply, confirmation and rollback in a process independent of Qt."""
    product_name(product)
    backend = backend or Backend()
    before, old_dpi, applied, kept, lock = None, None, False, False, None
    reason = 'Display changes were reverted.'
    fd = sys.stdin.fileno()
    try:
        raw = _read_line(fd, 5)
        require(raw is not None, 'No display settings were received.')
        profile = validate_profile(decode_json(raw))
        lock = SessionLock()
        lock.__enter__()
        _recover_pending_locked(product, backend)
        # Keep the session lock held through both normal and exceptional
        # rollback, so a second Apply can never race restoration.
        before = backend.probe(transforms=True)
        require(matches_hardware(profile, before), 'The connected displays changed. Please refresh the list.')
        layout = validate_live_layout(profile['layout'], before)
        old_dpi = backend.capture_scale()
        if hasattr(backend, 'capture_runtime_scale'):
            backend.scale_record = backend.capture_runtime_scale()
        _write_pending(product, before, old_dpi, backend)
        applied = True  # xrandr can partly change outputs even when it fails.
        backend.apply(layout, before)
        after = backend.probe()
        require(before.topology() == after.topology() and active_matches(layout, after),
                'The graphics hardware did not accept the complete display layout.')
        backend.set_scale(layout['scale'])
        deadline = time.monotonic() + timeout
        _emit(dict(state='pending', seconds=timeout))
        last_check = time.monotonic()
        while time.monotonic() < deadline:
            readable, _, _ = select.select([fd], [], [], min(0.25, max(0, deadline - time.monotonic())))
            if readable:
                action = _read_line(fd, max(0, deadline - time.monotonic()), limit=16)
                if action == b'keep':
                    actual = backend.probe()
                    require(actual.topology() == before.topology() and active_matches(layout, actual),
                            'A display changed before confirmation. The previous layout will be restored.')
                    journal = _read_pending(product)
                    require(journal is not None, 'The display safety record is unavailable.')
                    journal['replacing_preferences'] = True
                    atomic_write(_pending_path(), json.dumps(journal, separators=(',', ':')) + '\n')
                    save_profile(product, make_profile(product, actual, layout))
                    _clear_pending()
                    kept = True
                    _emit(dict(state='kept', message='Display settings applied and saved.' if product == 'node'
                               else 'Display settings applied for this private session.'))
                    return 0
                if action is None or action == b'revert':
                    break
                raise DisplayError('The display confirmation was invalid.')
            if time.monotonic() - last_check >= 1:
                require(backend.probe().topology() == before.topology(),
                        'A display disconnected or changed. The previous layout will be restored.')
                last_check = time.monotonic()
        if time.monotonic() >= deadline:
            reason = 'Confirmation timed out. The previous display settings were restored.'
        if applied and not kept:
            _recover_pending_locked(product, backend)
            applied = False
            _emit(dict(state='reverted', message=reason))
        return 0
    except (DisplayError, OSError, KeyboardInterrupt) as exc:
        reason = str(exc) if isinstance(exc, DisplayError) else 'The display change could not be completed.'
        _emit(dict(state='error', message=reason))
        return 1
    finally:
        if applied and not kept and before is not None:
            try:
                _recover_pending_locked(product, backend)
            except (DisplayError, OSError):
                try:
                    backend.fallback()
                except (DisplayError, OSError):
                    pass
            if old_dpi is not None:
                try:
                    backend.restore_scale(old_dpi)
                except (DisplayError, OSError):
                    pass
        if lock is not None and getattr(lock, 'fd', None) is not None:
            try:
                lock.__exit__(None, None, None)
            except OSError:
                pass


def start_transaction(product, profile):
    value = validate_profile(profile)
    value['product'] = product_name(product)
    process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), 'transaction', '--product', product],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               start_new_session=True, bufsize=0)
    try:
        process.stdin.write((json.dumps(value, separators=(',', ':')) + '\n').encode())
        process.stdin.flush()
    except Exception:
        process.stdin.close()
        raise
    return process


def restore_saved(product, backend=None):
    """Called before DPI selection. Unsupported/missing hardware keeps its mode."""
    backend = backend or Backend()
    with SessionLock():
        _recover_pending_locked(product, backend)
        profile = load_saved(product)
        if profile is None:
            return False
        before = backend.probe(transforms=True)
        if not matches_hardware(profile, before, automatic=True):
            if not before.active:
                backend.fallback(before)
            return False
        try:
            layout = validate_live_layout(profile['layout'], before)
            backend.apply(layout, before)
            require(active_matches(layout, backend.probe()), 'The saved display layout could not be restored.')
            return True
        except (DisplayError, OSError):
            backend.restore(before)
            return False


def launch_environment():
    """Apply the confirmed runtime DPI to newly launched Qt/GTK applications.

    Xft.dpi changes can be observed live by Qt; GTK's integer widget multiplier
    is an environment setting, so a restarted application must inherit it again.
    No process is stopped and no session is restarted here.
    """
    env = os.environ.copy()
    runtime = env.get('XDG_RUNTIME_DIR')
    try:
        if not runtime:
            return env
        path = Path(runtime) / 'core-display-scale.json'
        with path.open('rb') as stream:
            raw = stream.read(PROFILE_LIMIT + 1)
        result = decode_json(raw)
        require(type(result) is dict and 'scale' in result, 'The current display scale is unavailable.')
        scale = float(validate_scale(result['scale']))
    except (OSError, DisplayError, ValueError, TypeError):
        return env
    env.update(QT_ENABLE_HIGHDPI_SCALING='1', QT_SCALE_FACTOR_ROUNDING_POLICY='PassThrough')
    for key in ('QT_SCALE_FACTOR', 'QT_SCREEN_SCALE_FACTORS', 'QT_FONT_DPI',
                'QT_AUTO_SCREEN_SCALE_FACTOR', 'QT_USE_PHYSICAL_DPI'):
        env.pop(key, None)
    integer = max(1, int(scale))
    env.update(GDK_SCALE=str(integer), GDK_DPI_SCALE=str(1 / integer))
    return env


def watch(product, backend=None, interval=2):
    """Recover a usable primary output after hotplug; never interrupt a change."""
    product_name(product)
    backend = backend or Backend()
    previous = None
    while True:
        try:
            with SessionLock():
                _recover_pending_locked(product, backend)
                state = backend.probe()
                topology = state.topology()
                changed = previous is not None and previous != topology
                if state.connected and (not state.active or (changed and not any(o.primary for o in state.active))):
                    backend.fallback(state)
                # A saved multi-monitor layout can be restored only on an exact
                # EDID+connector match. Unknown displays keep their current mode.
                if changed:
                    saved = load_saved(product)
                    if saved is not None and matches_hardware(saved, state, automatic=True):
                        before = backend.probe(transforms=True)
                        try:
                            backend.apply(validate_live_layout(saved['layout'], before), before)
                            require(active_matches(saved['layout'], backend.probe()),
                                    'The saved display arrangement could not be restored.')
                        except (DisplayError, OSError):
                            backend.restore(before)
                    # Keep the shared UI scale usable on the remaining/new
                    # primary display without restarting any applications.
                    backend.set_scale(saved['layout']['scale'] if saved is not None else 'auto')
                previous = topology
        except (DisplayError, OSError):
            pass
        time.sleep(interval)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('transaction', 'restore', 'watch', 'query', 'recover'))
    parser.add_argument('--product', choices=('node', 'vault'), required=True)
    args = parser.parse_args(argv)
    # SIGTERM is also a rollback request, rather than an unhandled termination.
    def interrupted(*_):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, interrupted)
    try:
        if args.action == 'transaction':
            return transaction(args.product)
        if args.action == 'restore':
            restore_saved(args.product)
        elif args.action == 'recover':
            recover_abandoned(args.product)
        elif args.action == 'watch':
            watch(args.product)
        else:
            state = Backend().probe()
            print(json.dumps(dict(hardware=state.hardware(),
                                  layout=layout_from_snapshot(state) if state.active else None,
                                  displays=[dict(name=o.name, connected=o.connected, active=o.active,
                                                 primary=o.primary, builtin=o.builtin,
                                                 modes=[dict(name=m.name, width=m.width, height=m.height,
                                                             rates=m.rates, preferred=m.preferred) for m in o.modes])
                                            for o in state.outputs]), indent=2))
        return 0
    except (DisplayError, OSError) as exc:
        print(str(exc) if isinstance(exc, DisplayError) else 'Display settings are unavailable in this session.', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
