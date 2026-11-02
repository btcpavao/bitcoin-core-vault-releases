#!/bin/bash
# Resume ONLY the cached Calamares package build. No installation or disk formatting.
set -euo pipefail
MODE=${1:---check}
case "$MODE" in --check|--build) ;; *) echo 'Usage: resume-installer-package.sh [--check|--build]' >&2; exit 2 ;; esac
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PROJECT=$(cd -- "$HERE/../.." && pwd)
if [[ ${EUID} -ne 0 ]]; then
    exec sudo -- /bin/bash "$HERE/resume-installer-package.sh" "$MODE"
fi
WORK="$PROJECT/build-assets/core-offline-calamares"
ROOT="$WORK/root"
OUT="$PROJECT/config/packages.chroot"
[[ -d "$ROOT" && ! -L "$ROOT" ]] || { echo "Cached builder missing: $ROOT" >&2; exit 1; }
[[ -x "$ROOT/usr/bin/python3" && -x "$ROOT/usr/bin/dpkg-buildpackage" ]] || {
    echo 'Cached builder is incomplete; no packages or directories were deleted.' >&2; exit 1;
}
[[ -f "$ROOT/build/calamares_3.3.14-1.dsc" ]] || {
    echo 'Expected original calamares_3.3.14-1.dsc is not in the cache. Stop and inspect; do not guess a version.' >&2; exit 1;
}
if [[ -e "$WORK/build-success" ]]; then
    echo 'This cache already has a completed build. This recovery script only handles the interrupted original build.' >&2
    exit 1
fi
exec 9>"$WORK/.resume-build.lock"
flock -n 9 || { echo 'Another recovery build is running.' >&2; exit 1; }
STAMP=$(date -u +%Y%m%dT%H%M%S)-$$
LOG="$WORK/resume-$STAMP.log"
exec > >(tee "$LOG") 2>&1
printf 'Mode: %s\nCached builder: %s\nLog: %s\n' "$MODE" "$ROOT" "$LOG"

grep -q '^VERSION_ID="13"' "$ROOT/etc/os-release" || { echo 'Not a Debian 13 builder.'; exit 1; }
[[ $(chroot "$ROOT" /usr/bin/dpkg --print-architecture) == amd64 ]] || { echo 'Not an amd64 builder.'; exit 1; }
# Nothing is fetched again. These two reviewed build tools replace their old copies.
install -m 0755 "$HERE/patch_calamares_source.py" "$ROOT/opt/core-offline/patch_calamares_source.py"
install -m 0644 "$HERE/CoreOfflineGuard.h" "$ROOT/opt/core-offline/CoreOfflineGuard.h"

# Use a fresh extraction of the cached, checksummed source instead of layering
# a patch onto a partially edited tree. Keep both trees for inspection.
chroot "$ROOT" /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin \
    HOME=/root LANG=C.UTF-8 LC_ALL=C.UTF-8 \
    /bin/bash -s -- "$STAMP" <<'CHECK'
set -euo pipefail
BASE="/build/core-offline-recovery-$1"
mkdir -m 0755 "$BASE"
SOURCE="$BASE/calamares-3.3.14"
# dpkg-source validates archive checksums against the cached .dsc.
dpkg-source -x /build/calamares_3.3.14-1.dsc "$SOURCE"
cd "$SOURCE"
[[ $(dpkg-parsechangelog -SVersion) == 3.3.14-1 ]] || { echo 'Unexpected source version'; exit 1; }
dpkg-checkbuilddeps
python3 /opt/core-offline/patch_calamares_source.py "$SOURCE" \
    --header /opt/core-offline/CoreOfflineGuard.h --check
CHECK

SOURCE_BASE="/build/core-offline-recovery-$STAMP"
if [[ "$MODE" == --check ]]; then
    echo 'CORE OFFLINE CACHED SOURCE PREFLIGHT PASSED'
    echo 'All patch anchors checked against a fresh extraction of your cached source.'
    echo 'No C++ changes applied, no compilation performed, no target disk touched.'
    echo 'Next: bash tools/core-offline/resume-installer-package.sh --build'
    exit 0
fi

# Register cleanup BEFORE mounting. Never bind-mount a host disk or host root.
PROC_MOUNTED=0
SHM_MOUNTED=0
cleanup() {
    local rc=$?
    trap - EXIT
    if [[ $SHM_MOUNTED == 1 ]]; then
        umount "$ROOT/dev/shm" || echo "WARNING: unable to unmount $ROOT/dev/shm" >&2
    fi
    if [[ $PROC_MOUNTED == 1 ]]; then
        umount "$ROOT/proc" || echo "WARNING: unable to unmount $ROOT/proc" >&2
    fi
    if [[ $rc -ne 0 ]]; then
        echo "Build stopped. Cache and source preserved. Diagnostic log: $LOG" >&2
    fi
    exit "$rc"
}
trap cleanup EXIT
mkdir -p "$ROOT/proc" "$ROOT/dev/shm"
if mountpoint -q "$ROOT/proc" || mountpoint -q "$ROOT/dev/shm"; then
    echo 'Builder mounts are already active. Stop and inspect possible concurrent builds.' >&2
    exit 1
fi
mount -t proc proc "$ROOT/proc"
PROC_MOUNTED=1
mount -t tmpfs -o nosuid,nodev,mode=1777 tmpfs "$ROOT/dev/shm"
SHM_MOUNTED=1

chroot "$ROOT" /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin \
    HOME=/root DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8 LC_ALL=C.UTF-8 \
    DEBEMAIL=builder@localhost DEBFULLNAME='Core Offline local builder' \
    QT_QPA_PLATFORM=offscreen /bin/bash -s -- "$SOURCE_BASE" <<'BUILD'
set -euo pipefail
cd "$1/calamares-3.3.14"
python3 /opt/core-offline/patch_calamares_source.py . --header /opt/core-offline/CoreOfflineGuard.h
EDITOR=/bin/true VISUAL=/bin/true dpkg-source --commit . core-offline-ui-and-disk-safety
DISTRIBUTION=trixie dch --newversion '3.3.14-1+coreoffline1' --distribution trixie \
    'Core Offline UI restrictions, branding and disk identity guard; corrected source-definition matching.'
dpkg-buildpackage -us -uc -b -j2
# Source-package rebuild intentionally omitted here.
# dpkg-buildpackage -b already produced the runtime binaries;
# rebuilding source from a binary-build tree would include
# debhelper staging artifacts.
dpkg-query -W > "$1/build-environment.packages"
BUILD

# Only publish runtime binary packages after the WHOLE package build succeeds.
ARTIFACTS="$ROOT$SOURCE_BASE"
mkdir -p "$OUT"
shopt -s nullglob
ALL=("$ARTIFACTS"/*.deb)
[[ ${#ALL[@]} -gt 0 ]] || { echo 'No binary packages were produced.' >&2; exit 1; }
RUNTIME=()
FOUND=0
for DEB in "${ALL[@]}"; do
    PKG=$(dpkg-deb -f "$DEB" Package)
    case "$PKG" in *-dev|*-dbgsym|*-dbg) continue ;; esac
    [[ $(dpkg-deb -f "$DEB" Version) == '3.3.14-1+coreoffline1' ]] || { echo "Unexpected package version: $DEB"; exit 1; }
    RUNTIME+=("$DEB")
    if [[ "$PKG" == calamares ]]; then FOUND=1; fi
    # Do not silently leave a second, conflicting local package in the ISO input.
    for OLD in "$OUT"/*.deb; do
        if [[ $(dpkg-deb -f "$OLD" Package) == "$PKG" && $(basename "$OLD") != $(basename "$DEB") ]]; then
            echo "A different local version already exists: $OLD. No files removed. Resolve it before retrying." >&2
            exit 1
        fi
    done
done
[[ $FOUND == 1 ]] || { echo 'No calamares runtime package found.' >&2; exit 1; }
SUMS="$WORK/packages.sha256.tmp-$STAMP"
: > "$SUMS"
for DEB in "${RUNTIME[@]}"; do
    install -m 0644 "$DEB" "$OUT/$(basename "$DEB")"
    (cd "$OUT"; sha256sum "$(basename "$DEB")") >> "$SUMS"
done
mv "$SUMS" "$WORK/packages.sha256"
(cd "$OUT"; sha256sum -c "$WORK/packages.sha256")
mkdir -p "$WORK/source-artifacts"
find "$ARTIFACTS" -maxdepth 1 -type f \
    \( -name '*.dsc' -o -name '*.tar.*' -o -name '*.buildinfo' -o -name '*.changes' -o -name '*.packages' \) \
    -exec cp {} "$WORK/source-artifacts/" \;
printf 'Calamares 3.3.14 Core Offline local package built after source matcher repair.\n' > "$WORK/build-success"
if [[ -n ${SUDO_UID:-} && -n ${SUDO_GID:-} ]]; then
    chown -R "$SUDO_UID:$SUDO_GID" "$OUT" "$WORK/source-artifacts"
    chown "$SUDO_UID:$SUDO_GID" "$WORK/build-success" "$WORK/packages.sha256" "$LOG"
fi
echo 'CORE OFFLINE CALAMARES PACKAGE BUILD PASSED'
echo 'Next: bash tools/core-offline/build-iso.sh'
echo 'Test installation on a virtual disk before any physical installation.'
