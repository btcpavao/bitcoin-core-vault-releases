#!/usr/bin/python3
from pathlib import Path
import hashlib,json,subprocess
VERSION='3.3.14-1+corevault4'
INPUTS=('base_patch.py','patch_calamares_source.py','CoreOfflineGuard.h','package_state.py','visual_polish.py')

def digest(root):
    h=hashlib.sha256()
    for name in INPUTS:
        h.update(name.encode()+b'\0');h.update((root/'tools/core-vault/calamares'/name).read_bytes())
    h.update((root/'tools/core-vault/prepare-installer.sh').read_bytes())
    # These exact resources are consumed by the styled native Qt self-test.
    for name in ('stylesheet.qss','checkmark.svg','checkmark.png','bitcoin.png','debian.png'):
        path='config/includes.chroot/etc/calamares/branding/core-offline/'+name
        h.update(path.encode()+b'\0');h.update((root/path).read_bytes())
    return h.hexdigest()

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
