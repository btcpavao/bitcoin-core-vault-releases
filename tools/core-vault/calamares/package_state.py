#!/usr/bin/python3
from pathlib import Path
import hashlib,json,subprocess
VERSION='3.3.14-1+corevault5'
INPUTS = (
    'tools/rebuild/inputs.env', 'tools/rebuild/InRelease.sha256',
    'tools/rebuild/packages/build.sh', 'tools/rebuild/packages/compiler-entry.sh',
    'tools/rebuild/compile-package.sh', 'tools/core-vault/prepare-installer.sh',
)
# These patch records and assets feed the native Qt geometry and styling test.
PATCH_INPUTS = ('base_patch.py', 'patch_calamares_source.py', 'CoreOfflineGuard.h',
                'package_state.py', 'visual_polish.py')
BRANDING = ('stylesheet.qss', 'checkmark.svg', 'checkmark.png', 'bitcoin.png', 'debian.png'
)


def digest(root):
    result = hashlib.sha256()
    paths = list(INPUTS)
    paths.extend('tools/core-vault/calamares/' + name for name in PATCH_INPUTS)
    paths.extend('config/includes.chroot/etc/calamares/branding/core-offline/' + name for name in BRANDING)
    for name in paths:
        result.update(name.encode() + b'\0')
        result.update((root / name).read_bytes())
    return result.hexdigest()

def verify(root):
    work=root/'build-assets/core-vault-calamares-v1'
    obj=json.loads((work/'package.json').read_text())
    if obj['input_sha256']!=digest(root): raise RuntimeError('Calamares sources changed; rerun prepare-installer.sh.')
    name=obj['filename']
    if Path(name).name!=name or not name.startswith('calamares_') or not name.endswith('_amd64.deb'):
        raise RuntimeError('Unexpected Calamares package name.')
    package=root/'config/packages.chroot'/name
    if not package.is_file() or package.is_symlink(): raise RuntimeError('Calamares package missing or unsafe.')
    if hashlib.sha256(package.read_bytes()).hexdigest()!=obj['sha256']:
        raise RuntimeError('Calamares package checksum mismatch.')
    for field,want in [('Package','calamares'),('Version',VERSION),('Architecture','amd64')]:
        got=subprocess.check_output(['dpkg-deb','-f',str(package),field],text=True).strip()
        if got!=want: raise RuntimeError('Unexpected '+field+': '+got)
    other=[p for p in package.parent.glob('calamares_*.deb') if p!=package]
    if other: raise RuntimeError('Another Calamares package is staged; move it aside before building: '+str(other))
    print('VAULT CALAMARES PACKAGE CHECK PASSED')
    return obj
