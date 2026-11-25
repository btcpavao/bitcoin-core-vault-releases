#!/bin/bash
# Local ISO packaging only: no boot/installation tests, signing or publishing.
set -euo pipefail
umask 022
stage=/home/pavao/vault-t2-build-20261124
src=/home/pavao/vault-t2-auto-20261124
base=/home/pavao/vault-bios-advanced-20261124/output/bitcoin-core-vault-legacy-advanced-20261124-amd64.iso
out=$src/output/bitcoin-core-vault-t2-auto-20261124-amd64.iso
cd "$stage/image-work"
if [[ -e "$out" || -e final.squashfs ]]; then
    printf '%s\n' 'Refusing to replace an existing candidate or packed filesystem.' >&2
    exit 1
fi
python3 "$src/tools/local-build/assemble-t2-candidate.py" \
    "$stage/image-work/rootfs" "$src" "$stage/kernel-inputs/kernel-input-manifest.json" \
    "$stage/native-calamares/calamares_3.3.14-1+corevault8localt2auto1_amd64.deb" \
    "$src/output/build-evidence"
python3 -B "$src/tools/local-build/write-live-boot-menu.py" \
    --models "$src/config/includes.chroot/usr/share/core-vault/t2-models.json" \
    --grub-output "$stage/image-work/grub.cfg"
mksquashfs rootfs final.squashfs -noappend -comp xz -b 131072 -processors 4 -mem 512M -no-progress
python3 - <<'PY'
from pathlib import Path
import hashlib
import json

def sha(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as source:
        for part in iter(lambda:source.read(1024*1024),b''):
            digest.update(part)
    return digest.hexdigest()

source=Path('/home/pavao/vault-t2-auto-20261124')
rows={}
for line in Path('base.files.sha').read_text().splitlines():
    digest,path=line.split('  ',1)
    if path in rows:raise SystemExit('Duplicate path in base ISO manifest.')
    rows[path]=digest
if rows.get('./live/filesystem.squashfs') != sha('base.squashfs'):
    raise SystemExit('Base filesystem does not match its ISO manifest.')
Path('filesystem.packages').write_text(
    (source/'output/build-evidence/image-packages.tsv').read_text().replace('\t',' '))
changes={
    './live/filesystem.squashfs':Path('final.squashfs'),
    './live/filesystem.packages':Path('filesystem.packages'),
    './boot/grub/grub.cfg':Path('grub.cfg'),
    './live/t2/vmlinuz':Path('rootfs/boot/vmlinuz-6.18.64-1-t2-trixie'),
    './live/t2/initrd.img':Path('rootfs/boot/initrd.img-6.18.64-1-t2-trixie'),
}
for name,path in changes.items():
    rows[name]=sha(path)
Path('final.files.sha').write_text('\n'.join(
    digest+'  '+path for path,digest in sorted(rows.items()))+'\n')
(source/'output/build-evidence/iso-file-updates.json').write_text(json.dumps(
    {name:{'sha256':rows[name],'bytes':path.stat().st_size} for name,path in changes.items()},
    indent=2)+'\n')
PY
xorriso -abort_on SORRY -indev "$base" -outdev "$out" \
    -map final.squashfs /live/filesystem.squashfs \
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
cd "$src/output"
sha256sum bitcoin-core-vault-t2-auto-20261124-amd64.iso > SHA256SUMS
printf '%s\n' 'Local Vault T2 ISO complete. Manual hardware trial pending; no tests were run.'
