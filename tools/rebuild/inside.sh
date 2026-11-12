#!/bin/bash
# Internal entry point in a new privileged-capability build container.
set -euo pipefail
umask 022
[[ $PWD == /work && -f /source.tar && $(id -u) == 0 && $(dpkg --print-architecture) == amd64 ]]
[[ ${VAULT_REVISION:-} =~ ^[0-9a-f]{40}$ ]]
source tools/rebuild/inputs.env
export SOURCE_DATE_EPOCH TZ=UTC LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONHASHSEED=0
export QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 DEBIAN_FRONTEND=noninteractive
export MKSQUASHFS_OPTIONS='-processors 1'
debian="https://snapshot.debian.org/archive/debian/$SNAPSHOT"
security="https://snapshot.debian.org/archive/debian-security/$SNAPSHOT"
mkdir -p /evidence/archives
keyring=/usr/share/keyrings/debian-archive-keyring.gpg
for suite in trixie trixie-updates trixie-security; do
    base=$debian
    if [[ $suite == trixie-security ]]; then base=$security; fi
    index="/evidence/archives/$suite.InRelease"
    curl --fail --silent --show-error --location --retry 4 -o "$index" "$base/dists/$suite/InRelease"
done
(cd /evidence/archives && sha256sum --check /work/tools/rebuild/InRelease.sha256)
# The snapshot is frozen in time. Its archive signatures and package hashes stay mandatory.
rm -f /etc/apt/sources.list.d/debian.sources
cat > /etc/apt/sources.list <<SOURCES
deb [check-valid-until=no signed-by=$keyring] $debian trixie main
deb [check-valid-until=no signed-by=$keyring] $debian trixie-updates main
deb [check-valid-until=no signed-by=$keyring] $security trixie-security main
SOURCES
apt-get -o Acquire::Retries=4 update
# apt has already authenticated all three InRelease files with its bundled verifier.
# Bind the package solver's local files to the exact metadata fetched above.
for suite in trixie trixie-updates trixie-security; do
    indexes=(/var/lib/apt/lists/*_dists_"${suite}"_InRelease)
    [[ ${#indexes[@]} == 1 ]]
    cmp -- "/evidence/archives/$suite.InRelease" "${indexes[0]}"
done
apt-get -o Acquire::Retries=4 install -y --no-install-recommends \
    sudo live-build debootstrap debian-archive-keyring \
    apt-utils ca-certificates wget rsync xorriso squashfs-tools isolinux syslinux-common \
    syslinux-utils grub-pc-bin grub-efi-amd64-bin mtools dosfstools cpio file xz-utils \
    python3 python3-pil python3-yaml python3-pyside6.qtcore python3-pyside6.qtgui \
    python3-pyside6.qtwidgets fonts-dejavu-core xvfb xauth gpg gpgv libusb-1.0-0 \
    libgl1 libxcb-cursor0 libxkbcommon-x11-0 libfuse2t64
for index in /evidence/archives/*.InRelease; do
    gpgv --keyring "$keyring" "$index"
done
dpkg-query -W -f='${binary:Package}\t${Version}\n' | LC_ALL=C sort > /evidence/builder-packages.tsv
# Every ISO uses two new locally compiled packages. Their expected artifacts
# are stored in the checkout so a change to a compiler or native source fails
# before image assembly unless it reproduces the reviewed bytes.
for kind in calamares thunar; do
    staged=(config/packages.chroot/"$kind"_*.deb)
    [[ ${#staged[@]} == 1 && -f ${staged[0]} ]]
    cmp "/verified-native/$kind/$kind-rebuilt.deb" "${staged[0]}"
    install -m 0644 "/verified-native/$kind/$kind-rebuilt.deb" "${staged[0]}"
    touch -d "@$SOURCE_DATE_EPOCH" "${staged[0]}"
done
mkdir /evidence/native
cp -a /verified-native/{calamares,thunar} /evidence/native/
# live-build rewrites sources.list for the installed system and then fetches
# current archive indexes even when configured to discard them. Omit that final
# lookup only. All package fetching and index checks at install time remain active.
echo 'ec430b43463d06183c22cf982969b9f2bbbfbe85eea8da1295faa9b1843b9415  /usr/lib/live/build/chroot_archives' | sha256sum --check
python3 - <<'PYCODE'
from pathlib import Path
path = Path('/usr/lib/live/build/chroot_archives')
script = path.read_text()
before = '\t\t# Updating indices\n\t\tApt chroot update\n'
after = '\t\tif [ "${LB_APT_INDICES}" != false ]; then Apt chroot update; fi\n'
if script.count(before) != 1:
    raise SystemExit("Unrecognized live-build archive update block")
script = script.replace(before, after)
# Debian's cache-less cleanup uses a plain mkdir for partial. Recreate both
# APT sandbox directories with Debian's required owner and permissions.
before = '\t\t\tmkdir -p chroot/var/lib/apt/lists/partial\n'
after = (
    '\t\t\tChroot chroot "install -d -m 0700 -o _apt -g root /var/lib/apt/lists/partial"\n'
    '\t\t\tChroot chroot "install -d -m 0755 -o _apt -g root /var/lib/apt/lists/auxfiles"\n'
)
if script.count(before) != 1:
    raise SystemExit("Unrecognized live-build APT cache cleanup")
path.write_text(script.replace(before, after))
PYCODE
backup=core-vault-backup_0.7.5_all.deb
bash tools/core-vault/backup-src/build-package.sh
cmp -- "tools/core-vault/backup-src/$backup" "config/packages.chroot/$backup"
sha256sum "tools/core-vault/backup-src/$backup" > /evidence/vault-backup-package.sha256
bash tools/core-vault/build-live-iso.sh \
    --mirror-bootstrap "$debian" --mirror-chroot "$debian" --mirror-chroot-security "$security" \
    --parent-mirror-bootstrap "$debian" --parent-mirror-chroot "$debian" \
    --parent-mirror-chroot-security "$security" --debootstrap-options '--include=ca-certificates' \
    --apt-options '--yes -o Acquire::Retries=4 -o Acquire::Check-Valid-Until=false' \
    --updates true --backports false --security true --apt-indices false
# SquashFS skips only APT's machine-generated binary lookup caches. Check
# the exact packed filesystem rather than the build-time package-manager state.
unsquashfs -ls -no-wildcards binary/live/filesystem.squashfs var/cache/apt > /tmp/apt-cache-list
if grep -Eq '/(pkgcache|srcpkgcache)\.bin$' /tmp/apt-cache-list; then
    echo 'A build-machine APT binary cache entered the ISO.' >&2
    exit 1
fi
mv live-image-amd64.hybrid.iso /evidence/bitcoin-core-vault-amd64.iso
cp /work/vault-build.log /evidence/build.log
cp /work/live-image-amd64.packages /evidence/image-packages.tsv
printf 'source_commit=%s\nbuilder_image=%s\ndebian_snapshot=%s\nsource_date_epoch=%s\n' \
    "$VAULT_REVISION" "$BUILDER_IMAGE" "$SNAPSHOT" "$SOURCE_DATE_EPOCH" > /evidence/build-inputs.txt
(cd /evidence && sha256sum bitcoin-core-vault-amd64.iso > SHA256SUMS)
