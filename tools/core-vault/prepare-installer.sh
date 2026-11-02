#!/bin/bash
# Compile reviewed Calamares source in a dedicated Debian builder chroot.
# Does not run an installer, partition a disk, or install compiler deps on host.
set -euo pipefail
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
ROOT_PROJECT=$(cd -- "$HERE/../.." && pwd)
if [[ $EUID -ne 0 ]]; then exec sudo -- /bin/bash "$HERE/prepare-installer.sh"; fi
[[ $(dpkg --print-architecture) == amd64 ]] || { echo 'Debian amd64 host required'; exit 1; }
grep -q '^VERSION_ID="13"' /etc/os-release || { echo 'Debian 13 host required'; exit 1; }
for cmd in debootstrap mount umount chroot python3 dpkg-deb; do command -v "$cmd" >/dev/null || { echo "Missing host tool: $cmd"; exit 1; }; done
cd "$ROOT_PROJECT"
python3 tools/core-vault/check-installer.py --source
WORK="$ROOT_PROJECT/build-assets/core-vault-calamares-v1"
BUILDER="$WORK/root"
OUT="$ROOT_PROJECT/config/packages.chroot"
mkdir -p "$WORK" "$OUT"
[[ ! -L "$WORK" && ! -L "$BUILDER" && ! -L "$OUT" ]] || { echo 'Symlinked builder/output refused'; exit 1; }
if [[ -f "$WORK/package.json" ]] && python3 tools/core-vault/check-installer.py --prebuild; then
    echo 'Reviewed Calamares package is already built.'; exit 0
fi
FREE=$(df -PB1 "$WORK" | awk 'NR==2 {print $4}')
(( FREE > 20*1024*1024*1024 )) || { echo 'Please allow at least 20 GiB free space.'; exit 1; }
LOG="$WORK/build-$(date +%Y%m%d-%H%M%S).log"
exec > >(tee "$LOG") 2>&1
if [[ ! -e "$BUILDER" ]]; then
    debootstrap --variant=minbase --include=ca-certificates,gnupg trixie "$BUILDER" https://deb.debian.org/debian
elif [[ ! -f "$BUILDER/etc/debian_version" ]]; then
    echo "Incomplete builder: $BUILDER. Inspect it; do not reuse it automatically."; exit 1
fi
if findmnt -rn -o TARGET | grep -F "$BUILDER/"; then
    echo 'Stale builder mounts found; inspect before retrying.'; exit 1
fi
mkdir -p "$BUILDER/opt/vault-calamares" "$BUILDER/proc" "$BUILDER/dev/shm"
cp "$HERE"/calamares/{base_patch.py,patch_calamares_source.py,visual_polish.py,CoreOfflineGuard.h} "$BUILDER/opt/vault-calamares/"
# Stage exact runtime branding for native Qt geometry/control verification.
mkdir -p "$BUILDER/opt/vault-calamares/branding"
cp "$ROOT_PROJECT/config/includes.chroot/etc/calamares/branding/core-offline/"{stylesheet.qss,checkmark.svg,checkmark.png,bitcoin.png,debian.png} "$BUILDER/opt/vault-calamares/branding/"
cat > "$BUILDER/etc/apt/sources.list" <<'APT'
deb https://deb.debian.org/debian trixie main
deb-src https://deb.debian.org/debian trixie main
deb https://security.debian.org/debian-security trixie-security main
APT
printf '#!/bin/sh\nexit 101\n' > "$BUILDER/usr/sbin/policy-rc.d"
chmod 0755 "$BUILDER/usr/sbin/policy-rc.d"
PROC=0;SHM=0
cleanup() {
    [[ $SHM == 0 ]] || umount "$BUILDER/dev/shm" || true
    [[ $PROC == 0 ]] || umount "$BUILDER/proc" || true
}
trap cleanup EXIT
mount -t proc proc "$BUILDER/proc";PROC=1
mount -t tmpfs -o nosuid,nodev,mode=1777 tmpfs "$BUILDER/dev/shm";SHM=1
chroot "$BUILDER" /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin \
  LANG=C.UTF-8 LC_ALL=C.UTF-8 DEBIAN_FRONTEND=noninteractive \
  DEBEMAIL=builder@localhost DEBFULLNAME='Bitcoin Core Vault local builder' \
  QT_QPA_PLATFORM=offscreen /bin/bash -s <<'BUILD'
set -euo pipefail
apt-get update
apt-get install -y --no-install-recommends build-essential dpkg-dev devscripts python3 ca-certificates
apt-get build-dep -y calamares=3.3.14-1
mkdir -p /build
RUN=$(mktemp -d /build/core-vault.XXXXXXXX)
cd "$RUN"
apt-get source --download-only calamares=3.3.14-1
[[ -f calamares_3.3.14-1.dsc ]] || { echo 'Expected Debian source version is unavailable'; exit 1; }
dpkg-source -x calamares_3.3.14-1.dsc source
cd source
python3 /opt/vault-calamares/patch_calamares_source.py . --check
python3 /opt/vault-calamares/patch_calamares_source.py .
# VAULT_MENU_PROGRESS_V2: test the exact Qt progress widget before compiling the package.
# VAULT_VISUAL_BUILDER_V3
python3 /opt/vault-calamares/visual_polish.py --self-test
EDITOR=true dpkg-source --commit . core-vault-installer
DISTRIBUTION=trixie dch --newversion '3.3.14-1+corevault4' --distribution trixie \
    'Bitcoin Core Vault installer UI, erase acknowledgement and pre-write disk guard.'
# Keep the exact patched source before the binary build creates staging files.
tar -cJf "$RUN/core-vault-patched-source.tar.xz" .
dpkg-buildpackage -us -uc -b -j2
cd "$RUN"
dpkg-query -W > build-environment.packages
[[ -f calamares_3.3.14-1+corevault4_amd64.deb ]] || { echo 'Expected Calamares binary was not produced'; exit 1; }
printf '%s\n' "$RUN" > /build/core-vault-last-success
BUILD
RUN=$(cat "$BUILDER/build/core-vault-last-success")
[[ "$RUN" =~ ^/build/core-vault\.[A-Za-z0-9]+$ ]] || { echo 'Invalid builder result directory'; exit 1; }
DEB="$BUILDER$RUN/calamares_3.3.14-1+corevault4_amd64.deb"
[[ -f "$DEB" && ! -L "$DEB" ]] || exit 1
# Only now stage the new runtime package; keep any earlier local runtime in WORK.
mkdir -p "$WORK/previous-packages" "$WORK/source-artifacts"
for old in "$OUT"/calamares_*.deb; do
    [[ -e "$old" ]] || continue
    mv "$old" "$WORK/previous-packages/$(date +%Y%m%d-%H%M%S)-$(basename "$old")"
done
cp "$DEB" "$OUT/"
find "$BUILDER$RUN" -maxdepth 1 -type f \( -name '*.dsc' -o -name '*.tar.*' -o -name '*.buildinfo' -o -name '*.changes' -o -name '*.packages' \) -exec cp {} "$WORK/source-artifacts/" \;
python3 - "$ROOT_PROJECT" <<'PY'
import sys,json,hashlib
from pathlib import Path
root=Path(sys.argv[1]);sys.path.insert(0,str(root/'tools/core-vault/calamares'))
import package_state
p=root/'config/packages.chroot/calamares_3.3.14-1+corevault4_amd64.deb'
obj={'filename':p.name,'version':package_state.VERSION,'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),
     'input_sha256':package_state.digest(root)}
(root/'build-assets/core-vault-calamares-v1/package.json').write_text(json.dumps(obj,indent=2)+'\n')
package_state.verify(root)
PY
if [[ -n ${SUDO_UID:-} && -n ${SUDO_GID:-} ]]; then
    chown "$SUDO_UID:$SUDO_GID" "$OUT/$(basename "$DEB")" "$WORK/package.json" "$LOG"
    chown -R "$SUDO_UID:$SUDO_GID" "$WORK/source-artifacts"
fi
echo 'VAULT CALAMARES PACKAGE BUILD PASSED'
echo "Build log: $LOG"
