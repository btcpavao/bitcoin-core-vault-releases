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
    gpgv --keyring "$keyring" "$index"
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
apt-get -o Acquire::Retries=4 install -y --no-install-recommends \
    sudo live-build debootstrap debian-archive-keyring \
    apt-utils ca-certificates wget rsync xorriso squashfs-tools isolinux syslinux-common \
    syslinux-utils grub-pc-bin grub-efi-amd64-bin mtools dosfstools cpio file xz-utils \
    python3 python3-pil python3-yaml python3-pyside6.qtcore python3-pyside6.qtgui \
    python3-pyside6.qtwidgets fonts-dejavu-core xvfb xauth gpg gpgv libusb-1.0-0 \
    libgl1 libxcb-cursor0 libxkbcommon-x11-0 libfuse2t64
dpkg-query -W -f='${binary:Package}\t${Version}\n' | LC_ALL=C sort > /evidence/builder-packages.tsv
# debootstrap uses the frozen mirror, and apt selects the same main, updates and security
# archives throughout the image build. Keep live-build's normal end-user APT mirrors.
bash tools/core-vault/build-live-iso.sh \
    --mirror-bootstrap "$debian" --mirror-chroot "$debian" --mirror-chroot-security "$security" \
    --parent-mirror-bootstrap "$debian" --parent-mirror-chroot "$debian" \
    --parent-mirror-chroot-security "$security" --debootstrap-options '--include=ca-certificates' \
    --apt-options '--yes -o Acquire::Retries=4 -o Acquire::Check-Valid-Until=false' \
    --updates true --backports false --security true
mv live-image-amd64.hybrid.iso /evidence/bitcoin-core-vault-amd64.iso
cp /work/vault-build.log /evidence/build.log
cp /work/live-image-amd64.packages /evidence/image-packages.tsv
printf 'source_commit=%s\nbuilder_image=%s\ndebian_snapshot=%s\nsource_date_epoch=%s\n' \
    "$VAULT_REVISION" "$BUILDER_IMAGE" "$SNAPSHOT" "$SOURCE_DATE_EPOCH" > /evidence/build-inputs.txt
(cd /evidence && sha256sum bitcoin-core-vault-amd64.iso > SHA256SUMS)
