#!/bin/bash
# Rebuild only the locally customized Calamares package using the existing Debian-13 builder cache.
set -euo pipefail
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PROJECT=$(cd -- "$HERE/../.." && pwd)
if [[ ${EUID} -ne 0 ]]; then exec sudo -- /bin/bash "$0"; fi
WORK="$PROJECT/build-assets/core-offline-calamares"
ROOT="$WORK/root"
OUT="$PROJECT/config/packages.chroot"
[[ -d "$ROOT" && -x "$ROOT/usr/bin/dpkg-buildpackage" ]] || { echo "Cached Calamares builder missing: $ROOT" >&2; exit 1; }
[[ -f "$ROOT/build/calamares_3.3.14-1.dsc" ]] || { echo "Cached Debian Calamares source archive missing." >&2; exit 1; }
exec 9>"$WORK/.ux-rebuild.lock"; flock -n 9 || { echo "Another Calamares build is running." >&2; exit 1; }
STAMP=$(date -u +%Y%m%dT%H%M%S)-$$
LOG="$WORK/ux-rebuild-$STAMP.log"
exec > >(tee "$LOG") 2>&1
install -m 0755 "$HERE/patch_calamares_source.py" "$ROOT/opt/core-offline/patch_calamares_source.py"
install -m 0644 "$HERE/CoreOfflineGuard.h" "$ROOT/opt/core-offline/CoreOfflineGuard.h"
BASE="/build/bitcoin-core-offline-ux-$STAMP"
chroot "$ROOT" /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin HOME=/root LANG=C.UTF-8 LC_ALL=C.UTF-8 /bin/bash -s -- "$BASE" <<'CHECK'
set -euo pipefail
mkdir -p "$1"
dpkg-source -x /build/calamares_3.3.14-1.dsc "$1/calamares-3.3.14"
cd "$1/calamares-3.3.14"
dpkg-checkbuilddeps
python3 /opt/core-offline/patch_calamares_source.py . --header /opt/core-offline/CoreOfflineGuard.h --check
CHECK
PROC=0; SHM=0
cleanup(){ rc=$?; trap - EXIT; [[ $SHM == 1 ]] && umount "$ROOT/dev/shm" || true; [[ $PROC == 1 ]] && umount "$ROOT/proc" || true; [[ $rc -ne 0 ]] && echo "Build failed; log: $LOG" >&2; exit $rc; }
trap cleanup EXIT
mkdir -p "$ROOT/proc" "$ROOT/dev/shm"
mount -t proc proc "$ROOT/proc"; PROC=1
mount -t tmpfs -o nosuid,nodev,mode=1777 tmpfs "$ROOT/dev/shm"; SHM=1
chroot "$ROOT" /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin HOME=/root DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8 LC_ALL=C.UTF-8 DEBEMAIL=builder@localhost DEBFULLNAME='Bitcoin Core Offline local builder' QT_QPA_PLATFORM=offscreen /bin/bash -s -- "$BASE" <<'BUILD'
set -euo pipefail
cd "$1/calamares-3.3.14"
python3 /opt/core-offline/patch_calamares_source.py . --header /opt/core-offline/CoreOfflineGuard.h
EDITOR=/bin/true VISUAL=/bin/true dpkg-source --commit . bitcoin-core-offline-installer-ux
DISTRIBUTION=trixie dch --newversion '3.3.14-1+coreoffline1' --distribution trixie 'Bitcoin Core Offline installer UX, branding, and disk-safety integration.'
dpkg-buildpackage -us -uc -b -j2
dpkg-query -W > "$1/build-environment.packages"
BUILD
ART="$ROOT$BASE"
mkdir -p "$OUT"
mapfile -t ALL < <(find "$ART" -maxdepth 1 -type f -name '*.deb' -print | sort)
[[ ${#ALL[@]} -gt 0 ]] || { echo 'No .deb packages produced.' >&2; exit 1; }
RUNTIME=(); FOUND=0
for DEB in "${ALL[@]}"; do
  PKG=$(dpkg-deb -f "$DEB" Package); VER=$(dpkg-deb -f "$DEB" Version)
  case "$PKG" in *-dev|*-dbgsym|*-dbg) continue ;; esac
  [[ "$VER" == '3.3.14-1+coreoffline1' ]] || { echo "Unexpected version $PKG $VER" >&2; exit 1; }
  [[ "$PKG" == calamares ]] && FOUND=1
  RUNTIME+=("$DEB")
done
[[ $FOUND == 1 ]] || { echo 'Customized calamares package missing.' >&2; exit 1; }
for DEB in "${RUNTIME[@]}"; do
  PKG=$(dpkg-deb -f "$DEB" Package)
  for OLD in "$OUT"/*.deb; do [[ -e "$OLD" ]] || continue; [[ $(dpkg-deb -f "$OLD" Package 2>/dev/null || true) == "$PKG" ]] && rm -f "$OLD"; done
  install -m 0644 "$DEB" "$OUT/$(basename "$DEB")"
done
: > "$WORK/packages.sha256"
for DEB in "${RUNTIME[@]}"; do (cd "$OUT"; sha256sum "$(basename "$DEB")") >> "$WORK/packages.sha256"; done
(cd "$OUT"; sha256sum -c "$WORK/packages.sha256")
printf 'Bitcoin Core Offline Calamares UX package rebuilt.\n' > "$WORK/build-success"
if [[ -n ${SUDO_UID:-} && -n ${SUDO_GID:-} ]]; then chown -R "$SUDO_UID:$SUDO_GID" "$OUT"; chown "$SUDO_UID:$SUDO_GID" "$WORK/packages.sha256" "$WORK/build-success" "$LOG"; fi
echo 'BITCOIN CORE OFFLINE CALAMARES UX BUILD PASSED'
echo 'Next: bash tools/core-offline/build-iso.sh'
