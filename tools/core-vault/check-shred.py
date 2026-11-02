#!/usr/bin/python3
"""Verify the reviewed permanent-delete runtime, native package and startup."""
from pathlib import Path
import argparse
import ast
import hashlib
import json
import runpy
import subprocess

META = 'usr/share/core-vault/shred-policy.json'
REQUIRED = {
    'usr/local/bin/core-vault-shred',
    'usr/lib/core-vault-shred/engine.py',
    'usr/local/bin/core-vault-file-places',
    'usr/local/bin/core-vault-core-file-dialogs',
    'usr/local/bin/core-vault-guide',
    'usr/lib/core-vault/guide_visuals.py',
    'usr/local/bin/core-vault-home',
    'usr/local/bin/core-vault-session',
}


def require(ok, text):
    if not ok:
        raise RuntimeError(text)


def metadata(root):
    active = root / 'config/includes.chroot'
    template = root / 'tools/core-vault/runtime-template'
    raw = (active / META).read_bytes()
    require(raw == (template / META).read_bytes(), 'Shred policy copies differ')
    value = json.loads(raw)
    require(value.get('schema') == 1 and value.get('name') == 'vault-permanent-delete',
            'Unexpected permanent-delete policy')
    require(REQUIRED == set(value.get('files', {})), 'Incomplete permanent-delete runtime record')
    for name, digest in value['files'].items():
        p = active / name
        require(p.is_file() and not p.is_symlink(), 'Missing regular runtime: ' + name)
        data = p.read_bytes()
        require(data == (template / name).read_bytes(), 'Runtime template differs: ' + name)
        require(hashlib.sha256(data).hexdigest() == digest, 'Reviewed runtime changed: ' + name)
        require(not p.stat().st_mode & 0o022, 'Runtime is writable by group/others: ' + name)
        if name.endswith('core-vault-session'):
            subprocess.run(['/bin/sh', '-n', str(p)], check=True)
        else:
            ast.parse(data, filename=str(p))
    return raw, value


def check(root):
    metadata(root)
    session = (root / 'config/includes.chroot/usr/local/bin/core-vault-session').read_text()
    names = ('core-vault-file-places', 'core-vault-core-file-dialogs')
    for name in names:
        require(session.count('/usr/local/bin/' + name + ' --apply') == 1,
                'Expected exactly one startup call: ' + name)
    private = session.index('PRIVATE="$HOME/Private Workspace"')
    require(all(private < session.index('/usr/local/bin/' + name + ' --apply') for name in names),
            'Prepare Private Workspace before configuring shortcuts')
    thunar = runpy.run_path(str(root / 'tools/core-vault/check-thunar.py'))
    thunar['check'](root)
    print('VAULT PERMANENT DELETE SOURCE + PACKAGE CHECK PASSED')


def verify_payload(root, get, status, manifest):
    raw, value = metadata(root)
    require(get(META) == raw, 'ISO permanent-delete policy differs from reviewed source')
    for name, digest in {META: hashlib.sha256(raw).hexdigest(), **value['files']}.items():
        require(hashlib.sha256(get(name)).hexdigest() == digest, 'ISO runtime mismatch: ' + name)
        require(manifest.get('files', {}).get(name) == digest, 'Installer omits reviewed runtime: ' + name)
    require(get('usr/bin/shred').startswith(b'\x7fELF'), 'ISO lacks the real GNU shred engine')
    para = next((p for p in status.split('\n\n') if p.startswith('Package: bleachbit\n')), '')
    require('Status: install ok installed' not in para.splitlines(),
            'Removed BleachBit package is still installed in the ISO')
    require('usr/bin/shred' in manifest.get('files', {})
            and hashlib.sha256(get('usr/bin/shred')).hexdigest() == manifest['files']['usr/bin/shred'],
            'Installer GNU shred payload mismatch')
    require(not any('bleachbit' in name.lower() for name in manifest.get('files', {})),
            'Installer still includes removed BleachBit payload')
    thunar = runpy.run_path(str(root / 'tools/core-vault/check-thunar.py'))
    thunar['verify_payload'](root, get, status, manifest)
    print('VAULT PERMANENT DELETE ISO PAYLOAD CHECK PASSED')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, default=Path(__file__).resolve().parents[2])
    check(parser.parse_args().project.resolve(strict=True))
