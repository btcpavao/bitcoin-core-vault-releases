#!/usr/bin/python3
"""Verify the Num Lock helper and its one-time desktop/installer startup calls."""
import argparse
import ast
from pathlib import Path
import stat
import subprocess


def check(root):
    inc = root / 'config/includes.chroot'
    template = root / 'tools/core-vault/runtime-template'
    helper = inc / 'usr/local/bin/core-vault-numlock'
    assert helper.is_file() and not helper.is_symlink()
    assert stat.S_IMODE(helper.stat().st_mode) == 0o755
    assert helper.read_bytes() == (template / 'usr/local/bin/core-vault-numlock').read_bytes()
    source = helper.read_text()
    ast.parse(source, str(helper))
    for symbol in ('XkbKeysymToModifiers', 'XkbLockModifiers', 'XkbGetState', 'signal.alarm(3)'):
        assert symbol in source, symbol
    for forbidden in ('XSendEvent', 'XTestFakeKeyEvent', 'xdotool', 'subprocess'):
        assert forbidden not in source, forbidden
    call = '/usr/local/bin/core-vault-numlock >'
    for name in ('core-vault-session', 'core-vault-installer-session'):
        path = inc / 'usr/local/bin' / name
        text = path.read_text()
        subprocess.run(['/bin/sh', '-n', str(path)], check=True)
        assert text.count(call) == 1, name
        assert text.index(call) < text.index('/usr/bin/openbox'), name
        assert 'core-vault-numlock.log' in text
    assert (inc / 'usr/local/bin/core-vault-session').read_bytes() == \
        (template / 'usr/local/bin/core-vault-session').read_bytes()
    print('VAULT NUM LOCK DESKTOP + INSTALLER SOURCE CHECK PASSED')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, default=Path(__file__).resolve().parents[2])
    check(parser.parse_args().project.resolve(strict=True))
