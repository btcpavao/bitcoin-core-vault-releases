#!/bin/bash
# Local file-only repack. No test suites, VM runs, publication or signing.
set -euo pipefail
umask 022
stage=/home/pavao/vault-bios-build-20261124
src=/home/pavao/vault-bios-advanced-20261124
base=/home/pavao/iso-settings-dualboot-20261123/vault-b5ca3ea/bitcoin-core-vault-amd64.iso
deb=$stage/compiler-root/build/calamares_3.3.14-1+corevault7localbios1_amd64.deb
out=$src/output/bitcoin-core-vault-legacy-advanced-20261124-amd64.iso
cd "$stage/image-work"
if [[ -e "$out" ]]; then
    printf '%s\n' 'Refusing to replace an existing candidate ISO.' >&2
    exit 1
fi
python3 "$src/tools/local-build/assemble-bios-candidate.py" "$stage/image-work/rootfs" "$src" "$deb" "$src/output/build-evidence"
mksquashfs rootfs final.squashfs -noappend -comp xz -b 131072 -processors 2 -mem 256M -no-progress
python3 - <<'PY'
from pathlib import Path
import hashlib
def sha(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as source:
        for part in iter(lambda:source.read(1024*1024),b''):digest.update(part)
    return digest.hexdigest()
old=sha('base.squashfs');new=sha('final.squashfs')
lines=Path('base.files.sha').read_text().splitlines()
needle=old+'  ./live/filesystem.squashfs'
if lines.count(needle)!=1:raise SystemExit('The base ISO filesystem manifest is ambiguous.')
Path('final.files.sha').write_text('\n'.join(new+'  ./live/filesystem.squashfs' if line==needle else line for line in lines)+'\n')
PY
xorriso -abort_on SORRY -indev "$base" -outdev "$out" \
    -map final.squashfs /live/filesystem.squashfs \
    -map final.files.sha /sha256sum.txt \
    -chown 0 /live/filesystem.squashfs /sha256sum.txt -- \
    -chgrp 0 /live/filesystem.squashfs /sha256sum.txt -- \
    -chmod 0444 /live/filesystem.squashfs /sha256sum.txt -- \
    -boot_image any replay -commit -end
cd "$src/output"
sha256sum bitcoin-core-vault-legacy-advanced-20261124-amd64.iso > SHA256SUMS
printf '%s\n' 'Local Vault candidate assembled. Manual hardware trial pending; no tests were run.'
