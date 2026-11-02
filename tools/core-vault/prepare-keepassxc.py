#!/usr/bin/python3
"""Fetch the pinned upstream application for an owned ISO build, never at boot."""
from pathlib import Path
import hashlib,json,shutil,tempfile
from keepass_upstream import install_release,FINGERPRINT

ROOT=Path(__file__).resolve().parents[2]
manifest=json.loads((ROOT/'tools/core-vault/manifests/keepassxc-release.json').read_text())
assert manifest['primary_signer']==FINGERPRINT
includes=ROOT/'config/includes.chroot'
target=includes/'opt/keepassxc'
assert not target.is_symlink()
work=ROOT/'build-assets/core-vault-keepassxc';work.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory(prefix='verified-',dir=work) as folder:
    staging=Path(folder)/'release'
    result=install_release(manifest,staging,ROOT/'tools/core-vault/keepassxc-release-key.asc')
    assert result['sha256']==manifest['sha256'],'Upstream release differs from pinned checksum'
    if target.exists():shutil.rmtree(target)
    target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copytree(staging,target,symlinks=True)
binary=includes/'usr/bin/keepassxc'
assert binary.is_symlink() and str(binary.readlink())=='/opt/keepassxc/current/usr/bin/keepassxc'
icon=includes/'usr/share/icons/hicolor/256x256/apps/keepassxc.png'
icon.parent.mkdir(parents=True,exist_ok=True)
shutil.copyfile(target/'current/upstream-icon.png',icon)
(work/'release.json').write_text(json.dumps(result,indent=2)+'\n')
print('VAULT PINNED UPSTREAM KEEPASSXC SIGNATURE AND CHECKSUM VERIFIED',flush=True)
