#!/bin/bash
# Provision the release packaging tools inside the pinned disposable builder.
set -euo pipefail
umask 022
source /src/tools/rebuild/inputs.env
export DEBIAN_FRONTEND=noninteractive TZ=UTC LC_ALL=C
archive="https://snapshot.debian.org/archive/debian/$SNAPSHOT"
security="https://snapshot.debian.org/archive/debian-security/$SNAPSHOT"
key=/usr/share/keyrings/debian-archive-keyring.gpg
rm -f /etc/apt/sources.list.d/debian.sources
for suite in trixie trixie-updates trixie-security; do
    mirror=$archive
    if [[ $suite == trixie-security ]]; then mirror=$security; fi
    printf 'deb [check-valid-until=no signed-by=%s] %s %s main\n' "$key" "$mirror" "$suite"
done > /etc/apt/sources.list
bash /src/tools/rebuild/apt-pin-config.sh > /etc/apt/apt.conf.d/99vault-snapshot.conf
apt-get -o Acquire::Retries=4 update
apt-get -o Acquire::Retries=4 install -y --no-install-recommends python3 xorriso squashfs-tools fakeroot
install -d -o nobody -g nogroup /work /evidence
install -m 0444 /base.iso /work/base.iso
dpkg-query -W -f='${binary:Package}\t${Version}\n' xorriso squashfs-tools liblzma5 fakeroot > /evidence/packaging-tools.tsv
# All image ownership, capabilities and device nodes are virtualized for this
# process. No extracted program or device from the ISO is ever executed.
exec runuser -u nobody -- fakeroot -- bash /src/tools/rebuild/pack-release.sh /work/base.iso /evidence/bitcoin-core-vault-amd64.iso
