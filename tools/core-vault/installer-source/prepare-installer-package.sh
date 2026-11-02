#!/bin/bash
# Build the version-bounded modified Calamares package in a separate Debian chroot.
# No physical disk is partitioned. This is not a security sandbox for untrusted code.
set -euo pipefail
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PROJECT=$(cd -- "$HERE/../.." && pwd)
if [[ ${EUID} -ne 0 ]]; then exec sudo -- /bin/bash "$0"; fi
[[ $(dpkg --print-architecture) == amd64 ]] || { echo 'Debian amd64 build host required.' >&2; exit 1; }
grep -q '^VERSION_ID="13"' /etc/os-release || { echo 'Debian 13 build host required.' >&2; exit 1; }
command -v debootstrap >/dev/null || { echo 'Install debootstrap on the build host first.' >&2; exit 1; }
[[ -f "$PROJECT/config/binary" && -f "$HERE/patch_calamares_source.py" ]] || exit 1
OUT="$PROJECT/config/packages.chroot"
WORK="$PROJECT/build-assets/core-offline-calamares"
ROOT="$WORK/root"
mkdir -p "$OUT" "$WORK"
if [[ -f "$WORK/build-success" ]]; then
    (cd "$OUT"; sha256sum -c "$WORK/packages.sha256")
    echo 'Existing Core Offline Calamares build verified; no recompilation needed.'
    exit 0
fi
if [[ -e "$ROOT" ]]; then
    echo "Previous unfinished builder remains at $ROOT." >&2
    echo 'Inspect its build.log first. Move the whole core-offline-calamares directory aside before retrying.' >&2
    exit 1
fi
FREE=$(df -PB1 "$WORK" | awk 'NR==2 {print $4}')
(( FREE > 20*1024*1024*1024 )) || { echo 'Allow at least 20 GiB free for the one-time compiler chroot.' >&2; exit 1; }
exec > >(tee "$WORK/build.log") 2>&1
DEBOOTSTRAP_DIR=${DEBOOTSTRAP_DIR:-/usr/share/debootstrap}
export DEBOOTSTRAP_DIR
/usr/sbin/debootstrap --variant=minbase --include=ca-certificates,gnupg \
  trixie "$ROOT" https://deb.debian.org/debian
mkdir -p "$ROOT/opt/core-offline" "$ROOT/proc" "$ROOT/dev/shm"
cp "$HERE/patch_calamares_source.py" "$HERE/CoreOfflineGuard.h" "$ROOT/opt/core-offline/"
cat > "$ROOT/etc/apt/sources.list" <<'EOF'
deb https://deb.debian.org/debian trixie main
deb-src https://deb.debian.org/debian trixie main
deb https://security.debian.org/debian-security trixie-security main
EOF
cat > "$ROOT/usr/sbin/policy-rc.d" <<'EOF'
#!/bin/sh
exit 101
EOF
chmod 0755 "$ROOT/usr/sbin/policy-rc.d"
# Only these two temporary mounts are created; never bind the host root or a disk.
mount -t proc proc "$ROOT/proc"
mount -t tmpfs -o nosuid,nodev,mode=1777 tmpfs "$ROOT/dev/shm"
cleanup() {
    mountpoint -q "$ROOT/dev/shm" && umount "$ROOT/dev/shm" || true
    mountpoint -q "$ROOT/proc" && umount "$ROOT/proc" || true
}
trap cleanup EXIT
chroot "$ROOT" /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin \
    DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8 LC_ALL=C.UTF-8 \
    DEBEMAIL=builder@localhost DEBFULLNAME='Core Offline local builder' \
    QT_QPA_PLATFORM=offscreen /bin/bash -s <<'INNER'
set -euo pipefail
apt-get update
apt-get install -y --no-install-recommends build-essential dpkg-dev devscripts equivs python3 ca-certificates
apt-get build-dep -y calamares
mkdir -p /build
cd /build
apt-get source calamares
mapfile -t SOURCES < <(find /build -mindepth 1 -maxdepth 1 -type d -name 'calamares-*')
[[ ${#SOURCES[@]} -eq 1 ]] || { echo 'Ambiguous source directory'; exit 1; }
cd "${SOURCES[0]}"
OLD=$(dpkg-parsechangelog -SVersion)
[[ "$OLD" == 3.3.14-* ]] || { echo "Review source patch for changed version $OLD"; exit 1; }
python3 /opt/core-offline/patch_calamares_source.py . --header /opt/core-offline/CoreOfflineGuard.h
# Preserve the source changes as a Debian source patch, then record a local version.
EDITOR=true dpkg-source --commit . core-offline-ui-and-disk-safety
DISTRIBUTION=trixie dch --newversion "${OLD}+coreoffline1" --distribution trixie \
  'Core Offline installer UI restrictions, branding and pre-write disk identity guard.'
dpkg-buildpackage -us -uc -b -j2
# Keep source with the exact modifications alongside the binary artifacts.
# Source-package rebuild intentionally omitted here.
# dpkg-buildpackage -b already produced the runtime binaries;
# rebuilding source from a binary-build tree would include
# debhelper staging artifacts.
dpkg-query -W > /build/build-environment.packages
INNER
# Copy runtime packages built from this source; never copy debug or development packages.
: > "$WORK/packages.sha256"
FOUND=0
for DEB in "$ROOT"/build/*.deb; do
    PKG=$(dpkg-deb -f "$DEB" Package)
    case "$PKG" in *-dev|*-dbgsym|*-dbg) continue ;; esac
    VERSION=$(dpkg-deb -f "$DEB" Version)
    [[ "$VERSION" == *+coreoffline1 ]] || { echo 'Unexpected package version'; exit 1; }
    cp "$DEB" "$OUT/"
    (cd "$OUT"; sha256sum "$(basename "$DEB")") >> "$WORK/packages.sha256"
    [[ "$PKG" == calamares ]] && FOUND=1
done
[[ $FOUND == 1 ]] || { echo 'No Calamares runtime package was built'; exit 1; }
mkdir -p "$WORK/source-artifacts"
find "$ROOT/build" -maxdepth 1 -type f \( -name '*.dsc' -o -name '*.tar.*' -o -name '*.buildinfo' -o -name '*.changes' -o -name '*.packages' \) \
    -exec cp {} "$WORK/source-artifacts/" \;
printf 'Calamares 3.3.14 Core Offline local package built.\n' > "$WORK/build-success"
if [[ -n ${SUDO_UID:-} && -n ${SUDO_GID:-} ]]; then
    chown -R "$SUDO_UID:$SUDO_GID" "$OUT" "$WORK/source-artifacts"
    chown "$SUDO_UID:$SUDO_GID" "$WORK" "$WORK/build-success" "$WORK/packages.sha256" "$WORK/build.log"
fi
echo 'CORE OFFLINE CALAMARES PACKAGE BUILD PASSED'
