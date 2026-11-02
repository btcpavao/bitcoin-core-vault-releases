#!/usr/bin/python3
"""Test Num Lock only on a newly started private Xvfb; never the host display."""
import argparse
import ctypes as C
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
import time
import uuid


def exercise(helper, output, token):
    if (os.environ.get('CORE_VAULT_NUMLOCK_TEST_TOKEN') != token or
            os.environ.get('XAUTHORITY') != str(output / 'xauthority')):
        raise RuntimeError('This probe requires its own authenticated Xvfb fixture.')
    symbols = runpy.run_path(str(helper))
    Keyboard, core, num_lock = (symbols[name] for name in ('Keyboard', 'XKB_CORE_KEYBOARD', 'NUM_LOCK'))
    results = {'private_xvfb_only': True, 'tests': [], 'helper_ms': []}

    def passed(name):
        results['tests'].append(name)
        print('[PASS] ' + name, flush=True)

    def run_helper(success=True, environment=None):
        start = time.monotonic()
        result = subprocess.run([sys.executable, str(helper)], capture_output=True, text=True,
                                timeout=5, env=environment)
        results['helper_ms'].append(round((time.monotonic() - start) * 1000, 3))
        assert (result.returncode == 0) is success, result.stderr
        return result

    keyboard = Keyboard()
    try:
        mask = keyboard.x.XkbKeysymToModifiers(keyboard.display, num_lock)
        assert mask and not mask & 6, 'Private fixture must have a distinct Num Lock modifier'
        # Lock Caps Lock and Control on our private display. Num Lock alone
        # should change, including when it is initially off or already on.
        assert keyboard.x.XkbLockModifiers(keyboard.display, core, 255, 6)
        keyboard.x.XSync(keyboard.display, 0)
        assert keyboard.state().locked_mods == 6
        run_helper()
        assert keyboard.state().locked_mods == 6 | mask
        passed('Num Lock turns on and preserves unrelated locked modifiers')
        run_helper()
        assert keyboard.state().locked_mods == 6 | mask
        passed('Repeated startup is idempotent and keeps Num Lock on')

        # Verify a separate XKB indicator query, independent of State's ABI.
        x = keyboard.x
        x.XInternAtom.restype, x.XInternAtom.argtypes = C.c_ulong, [C.c_void_p, C.c_char_p, C.c_int]
        x.XkbGetNamedIndicator.restype = C.c_int
        x.XkbGetNamedIndicator.argtypes = [C.c_void_p, C.c_ulong, C.POINTER(C.c_int),
                                         C.POINTER(C.c_int), C.c_void_p, C.POINTER(C.c_int)]
        atom = x.XInternAtom(keyboard.display, b'Num Lock', 1)
        index, active, real = C.c_int(), C.c_int(), C.c_int()
        assert atom and x.XkbGetNamedIndicator(keyboard.display, atom, C.byref(index),
                                             C.byref(active), None, C.byref(real))
        assert active.value
        passed('Native Num Lock indicator independently confirms enabled state')
    finally:
        keyboard.close()

    # Move Num_Lock away from its usual Mod2 slot on this private X server.
    modifier_names = ('shift', 'lock', 'control', 'mod1', 'mod2', 'mod3', 'mod4', 'mod5')
    target = 32 if mask != 32 else 64
    commands = ['remove ' + name + ' = Num_Lock' for bit, name in enumerate(modifier_names)
                if mask & (1 << bit)]
    commands.append('add ' + modifier_names[target.bit_length() - 1] + ' = Num_Lock')
    args = ['xmodmap']
    for command in commands:
        args.extend(['-e', command])
    subprocess.run(args, check=True, timeout=5)
    keyboard = Keyboard()
    try:
        assert keyboard.x.XkbKeysymToModifiers(keyboard.display, num_lock) == target
        assert keyboard.x.XkbLockModifiers(keyboard.display, core, 255, 6)
        keyboard.x.XSync(keyboard.display, 0)
        run_helper()
        assert keyboard.state().locked_mods == 6 | target
        passed('Num Lock follows a remapped modifier instead of assuming Mod2')
    finally:
        keyboard.close()

    subprocess.run(['xmodmap', '-e', 'remove ' + modifier_names[target.bit_length() - 1] +
                    ' = Num_Lock'], check=True, timeout=5)
    keyboard = Keyboard()
    try:
        before = keyboard.state().locked_mods
        result = run_helper(success=False)
        assert 'no Num Lock modifier mapping' in result.stderr
        assert keyboard.state().locked_mods == before
        passed('Unavailable Num Lock mapping fails without changing other modifiers')
    finally:
        keyboard.close()
    environment = dict(os.environ)
    environment.pop('DISPLAY', None)
    result = run_helper(success=False, environment=environment)
    assert 'X11 session is unavailable' in result.stderr
    passed('Missing display fails promptly without a fallback connection')
    (output / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
    print(json.dumps(results), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--helper', type=Path, default=Path(__file__).resolve().parents[2] /
                        'config/includes.chroot/usr/local/bin/core-vault-numlock')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    for program in ('xvfb-run', 'Xvfb', 'xauth', 'xmodmap'):
        if shutil.which(program) is None:
            raise RuntimeError('Private Xvfb test dependency is missing: ' + program)
    with tempfile.TemporaryDirectory(prefix='vault-numlock-test-') as temporary:
        output = (args.output or Path(temporary)).resolve()
        output.mkdir(parents=True, exist_ok=True)
        token = uuid.uuid4().hex
        environment = dict(os.environ, CORE_VAULT_NUMLOCK_TEST_TOKEN=token,
                           PYTHONDONTWRITEBYTECODE='1')
        # The probe only runs inside this new server and its unique auth file.
        command = ['xvfb-run', '-a', '-f', str(output / 'xauthority'),
                   '-s', '-screen 0 640x480x24 -nolisten tcp -noreset', sys.executable, '-c',
                   "import runpy,sys; from pathlib import Path; runpy.run_path(sys.argv[1])"
                   "['exercise'](Path(sys.argv[2]),Path(sys.argv[3]),sys.argv[4])",
                   str(Path(__file__).resolve()), str(args.helper.resolve(strict=True)),
                   str(output), token]
        subprocess.run(command, check=True, timeout=30, env=environment)


if __name__ == '__main__':
    main()
