#!/usr/bin/python3
"""Stage an explicitly reviewed compiled candidate; never invent a package hash."""
from pathlib import Path
import argparse, hashlib, json, shutil, subprocess
import package_state
p=argparse.ArgumentParser();p.add_argument('deb',type=Path);p.add_argument('--sha256',required=True);a=p.parse_args()
root=Path(__file__).resolve().parents[3]
if not a.deb.is_file() or a.deb.is_symlink(): p.error('Expected a regular compiled .deb file.')
digest=hashlib.sha256(a.deb.read_bytes()).hexdigest()
if digest!=a.sha256: p.error('Reviewed candidate hash does not match the supplied file.')
for field,expected in [('Package','calamares'),('Version',package_state.VERSION),('Architecture','amd64')]:
    value=subprocess.check_output(['dpkg-deb','-f',str(a.deb),field],text=True).strip()
    if value!=expected: p.error('Unexpected '+field+': '+value)
name=f'calamares_{package_state.VERSION}_amd64.deb'
packages=root/'config/packages.chroot';archive=root/'build-assets/previous-installer-packages'
for old in packages.glob('calamares_*.deb'):
    if old.name!=name:
        archive.mkdir(parents=True,exist_ok=True);shutil.move(str(old),archive/old.name)
shutil.copyfile(a.deb,packages/name)
record=root/'build-assets/core-vault-calamares-v1/package.json'
record.write_text(json.dumps(dict(filename=name,version=package_state.VERSION,sha256=digest,input_sha256=package_state.digest(root)),indent=2)+'\n')
package_state.verify(root)
