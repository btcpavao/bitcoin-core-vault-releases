#!/bin/bash
# Run under fakeroot in the v0.8.0 Debian packaging environment.
set -euo pipefail
umask 022
base=$(realpath -e "$1")
out=$(realpath -m "$2")
src=$(cd "$(dirname "$0")/../.." && pwd -P)
[[ ! -e $out && ! -L $2 ]]
export TZ=UTC LC_ALL=C
unset SOURCE_DATE_EPOCH
work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT
cd "$work"
printf '%s  %s\n' d88a386619a1654d62504606385f993823a931c13d59c1cb680a17b6083837ce "$base" | sha256sum --strict --check
xorriso -abort_on SORRY -osirrox on -indev "$base" \
    -extract /live/filesystem.squashfs base.sqfs -extract /sha256sum.txt base.files.sha -end
unsquashfs -processors 2 -no-progress -d rootfs base.sqfs
python3 "$src/tools/rebuild/apply-release-ui.py" rootfs "$src"
mksquashfs rootfs final.sqfs -noappend -comp xz -b 131072 -mkfs-time 1794268800 -processors 2 -mem 256M -no-progress
old=$(sha256sum base.sqfs | cut -d' ' -f1)
new=$(sha256sum final.sqfs | cut -d' ' -f1)
[[ $(grep -Fxc "$old  ./live/filesystem.squashfs" base.files.sha) == 1 ]]
sed "s|^$old  \./live/filesystem\.squashfs\$|$new  ./live/filesystem.squashfs|" base.files.sha > final.files.sha

# The hardware-tested ISO went through two xorriso sessions. Replaying both
# preserves the BIOS/EFI file order. Pin the final GPT identifier and the
# ISO status-change timestamp of the two replaced files (2026-11-18 14:09:28 UTC).
paths=(/live/filesystem.squashfs /sha256sum.txt --)
repack() {
    xorriso -abort_on SORRY -indev "$1" -outdev "$2" \
        -map final.sqfs /live/filesystem.squashfs -map final.files.sha /sha256sum.txt \
        -chown 0 "${paths[@]}" -chgrp 0 "${paths[@]}" -chmod 0444 "${paths[@]}" \
        -alter_date b =1794268800 "${paths[@]}" -alter_date c =1795010968 "${paths[@]}" \
        -boot_image any replay -boot_image any gpt_disk_guid=ddbe1eac863b37419f12d8bf589b8fd0 -commit -end
}
repack "$base" first.iso
repack first.iso final.iso
echo '0bc142508a35172ea92f645decc31be1373b05956e9a17d0ad01cee9bab84857  final.iso' | sha256sum --strict --check
mv --no-clobber -- final.iso "$out"
[[ ! -e final.iso ]]
