#!/bin/bash
# Local ISO packaging; targeted runtime validation is recorded separately. No signing or publishing.
set -euo pipefail
umask 022
stage=/home/pavao/vault-t2-build-20261124
src=/home/pavao/vault-t2-auto-20261124
base=/home/pavao/vault-bios-advanced-20261124/output/bitcoin-core-vault-legacy-advanced-20261124-amd64.iso
out=/dev/shm/core-vault-desktop-v2-build-20261124/bitcoin-core-vault-t2-auto-desktop-tuning-v2-20261124-amd64.iso
destination=$src/output/bitcoin-core-vault-t2-auto-desktop-tuning-v2-20261124-amd64.iso
cd "$stage/image-work"
if [[ -e "$destination" || -e "$out" || -e /dev/shm/core-vault-desktop-v2-build-20261124/filesystem.squashfs ]]; then
    printf '%s\n' 'Refusing to replace an existing candidate or packed filesystem.' >&2
    exit 1
fi
python3 "$src/tools/local-build/assemble-t2-candidate.py" \
    "$stage/image-work/rootfs" "$src" "$stage/kernel-inputs/kernel-input-manifest.json" \
    "$stage/native-calamares/calamares_3.3.14-1+corevault10localrolesfix1_amd64.deb" \
    "$src/output/build-evidence-desktop-tuning-v2" \
    --installer-input-manifest "$stage/qml-inputs/installer-runtime-input-manifest.json" \
    --candidate-metadata "$stage/desktop-tuning-v2/candidate-metadata.json"
python3 -B "$src/tools/local-build/write-live-boot-menu.py" \
    --models "$src/config/includes.chroot/usr/share/core-vault/t2-models.json" \
    --grub-output "$stage/image-work/grub.cfg"
mksquashfs rootfs /dev/shm/core-vault-desktop-v2-build-20261124/filesystem.squashfs -noappend -comp xz -b 131072 -processors 4 -mem 512M -no-progress
python3 - <<'PY'
from pathlib import Path
import hashlib
import json
import subprocess

def sha(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as source:
        for part in iter(lambda:source.read(1024*1024),b''):
            digest.update(part)
    return digest.hexdigest()

source=Path('/home/pavao/vault-t2-auto-20261124')
base=Path('/home/pavao/vault-bios-advanced-20261124/output/bitcoin-core-vault-legacy-advanced-20261124-amd64.iso')
if sha(base) != 'cee87635f966e1cce4576abe9723ea99155da4a3f65217accf38521471a0a8b3':
    raise SystemExit('The original base ISO checksum changed.')
base_manifest=Path('/dev/shm/core-vault-desktop-v2-build-20261124/base.files.sha')
subprocess.run(['xorriso','-abort_on','SORRY','-osirrox','on','-indev',str(base),'-extract','/sha256sum.txt',str(base_manifest)],check=True)
rows={}
for line in base_manifest.read_text().splitlines():
    digest,path=line.split('  ',1)
    if path in rows:raise SystemExit('Duplicate path in base ISO manifest.')
    rows[path]=digest
Path('filesystem.packages').write_text(
    (source/'output/build-evidence-desktop-tuning-v2/image-packages.tsv').read_text().replace('\t',' '))
changes={
    './live/filesystem.squashfs':Path('/dev/shm/core-vault-desktop-v2-build-20261124/filesystem.squashfs'),
    './live/filesystem.packages':Path('filesystem.packages'),
    './boot/grub/grub.cfg':Path('grub.cfg'),
    './live/t2/vmlinuz':Path('rootfs/boot/vmlinuz-6.18.64-1-t2-trixie'),
    './live/t2/initrd.img':Path('rootfs/boot/initrd.img-6.18.64-1-t2-trixie'),
}
for name,path in changes.items():
    rows[name]=sha(path)
Path('final.files.sha').write_text('\n'.join(
    digest+'  '+path for path,digest in sorted(rows.items()))+'\n')
(source/'output/build-evidence-desktop-tuning-v2/iso-file-updates.json').write_text(json.dumps(
    {name:{'sha256':rows[name],'bytes':path.stat().st_size} for name,path in changes.items()},
    indent=2)+'\n')
PY
xorriso -abort_on SORRY -indev "$base" -outdev "stdio:$out" \
    -map /dev/shm/core-vault-desktop-v2-build-20261124/filesystem.squashfs /live/filesystem.squashfs \
    -map filesystem.packages /live/filesystem.packages \
    -map grub.cfg /boot/grub/grub.cfg \
    -map rootfs/boot/vmlinuz-6.18.64-1-t2-trixie /live/t2/vmlinuz \
    -map rootfs/boot/initrd.img-6.18.64-1-t2-trixie /live/t2/initrd.img \
    -map final.files.sha /sha256sum.txt \
    -chown 0 /live/t2 /live/t2/vmlinuz /live/t2/initrd.img /live/filesystem.squashfs /live/filesystem.packages /boot/grub/grub.cfg /sha256sum.txt -- \
    -chgrp 0 /live/t2 /live/t2/vmlinuz /live/t2/initrd.img /live/filesystem.squashfs /live/filesystem.packages /boot/grub/grub.cfg /sha256sum.txt -- \
    -chmod 0555 /live/t2 -- \
    -chmod 0444 /live/t2/vmlinuz /live/t2/initrd.img /live/filesystem.squashfs /live/filesystem.packages /boot/grub/grub.cfg /sha256sum.txt -- \
    -boot_image any replay -commit -end
sha256sum "$out" > "$out.sha256"
printf '%s\n' 'Local Vault desktop-tuning-v2 ISO packed in RAM; verify and promote before delivery.'
