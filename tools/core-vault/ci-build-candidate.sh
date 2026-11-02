#!/bin/bash
# Only a disposable Debian 13 CI builder. Never publishes a GitHub release.
set -euo pipefail

fail() { printf '%s\n' "$*" >&2; exit 1; }

[[ ${VAULT_CI_BUILD:-} == 1 ]] || fail 'Candidate builds require VAULT_CI_BUILD=1 in the disposable CI builder.'
[[ $(pwd -P) == /work && -d /work/.git && ! -L /work/.git ]] || fail 'Candidate builds require the checked-out Git repository at /work.'
[[ $(id -u) == 0 ]] || fail 'Run inside the disposable CI container as its build account, not on the Vault computer.'
. /etc/os-release
[[ ${ID:-} == debian && ${VERSION_ID:-} == 13 ]] || fail 'The candidate builder must use official Debian 13.'
[[ $(dpkg --print-architecture) == amd64 ]] || fail 'The candidate builder must be amd64.'

umask 022
export DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8 LC_ALL=C.UTF-8
export QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1
GIT=(git -c safe.directory=/work)
ARTIFACTS=/work/candidate-artifacts
[[ ! -e $ARTIFACTS && ! -L $ARTIFACTS ]] || fail 'candidate-artifacts already exists; use a fresh disposable CI checkout.'
[[ ! -e /work/live-image-amd64.hybrid.iso && ! -L /work/live-image-amd64.hybrid.iso ]] || fail 'A pre-existing ISO is not a new CI candidate; use a fresh checkout.'
mkdir -- "$ARTIFACTS"
LOG=$ARTIFACTS/candidate-build.log
SOURCE=$ARTIFACTS/bitcoin-core-vault-gpg-candidate-tracked-source.tar.xz
trap 'result=$?; if (( result != 0 )); then printf "Candidate build failed (exit %s). No acceptance or release is declared; inspect %s.\n" "$result" "$LOG" >&2; fi' EXIT

# tee finishes before the log is hashed. Never add later output to this file.
{
    apt-get -o Acquire::Retries=3 update
    apt-get -o Acquire::Retries=3 install -y --no-install-recommends \
        bash ca-certificates git sudo dpkg util-linux live-build debootstrap \
        xorriso squashfs-tools isolinux syslinux-common syslinux-utils \
        grub-pc-bin grub-efi-amd64-bin mtools dosfstools cpio file xz-utils \
        python3 python3-pil python3-yaml \
        python3-pyside6.qtcore python3-pyside6.qtgui python3-pyside6.qtwidgets \
        fonts-dejavu-core xvfb xauth tar gpg gpgv libusb-1.0-0
} 2>&1 | tee "$LOG"

# A bare Debian container may not initially have git or xz; install them first.
# Exclude only this script's newly created artifact directory from cleanliness.
"${GIT[@]}" diff --quiet && "${GIT[@]}" diff --cached --quiet || fail 'Commit the complete candidate source before building.'
[[ -z $("${GIT[@]}" ls-files --others --exclude-standard -- . ':!candidate-artifacts') ]] || fail 'Untracked source inputs must be committed before building.'
VAULT_CANDIDATE_COMMIT=$("${GIT[@]}" rev-parse --verify HEAD)
export VAULT_CANDIDATE_COMMIT
# Freeze precisely the committed tree, including reviewed tracked build inputs.
# No .git history, untracked files, generated wallets/profiles, or build trees.
"${GIT[@]}" archive --format=tar --prefix=bitcoin-core-vault-gpg-candidate-source/ \
    "$VAULT_CANDIDATE_COMMIT" | xz -T1 > "$SOURCE"
{
    printf 'Bitcoin Core Vault GPG candidate source commit: %s\n' "$VAULT_CANDIDATE_COMMIT"
    printf '%s\n' 'Scope: ISO content gates only; boot, installation and end-to-end recovery acceptance remain pending.'
    dpkg-query -W -f='${Package} ${Version}\n' \
        live-build debootstrap xorriso squashfs-tools python3-pil \
        python3-yaml python3-pyside6.qtwidgets gpg tar
    # Uses all existing source/package, chroot self-test and final ISO gates.
    # The reviewed 0940 hook supplies its own temporary tmpfs for the GPG test.
    bash tools/core-vault/build-live-iso.sh
} 2>&1 | tee -a "$LOG"

# The exact gate markers supplement the entrypoint's successful exit status.
for marker in \
    'VAULT REAL GPG AES256-OCB ROUNDTRIP AND AUTHENTICATION TESTS PASSED' \
    'BITCOIN CORE VAULT LIVE ISO CONTENT CHECKS PASSED' \
    'VAULT CALAMARES ISO CONTENT CHECK PASSED' \
    'VAULT RAM-ONLY PRIVATE SESSION ISO CONTENT CHECK PASSED'; do
    grep -Fqx "$marker" "$LOG" || fail "Required candidate gate did not report success: $marker"
done

ISO=/work/live-image-amd64.hybrid.iso
[[ -f $ISO && ! -L $ISO && -s $ISO ]] || fail 'The successful build did not produce a regular nonempty ISO.'
cp --reflink=auto --sparse=always -- "$ISO" "$ARTIFACTS/bitcoin-core-vault-gpg-candidate-amd64.iso"

python3 - <<'PY'
from pathlib import Path
import datetime
import hashlib
import json
import os
import stat

root = Path('/work/candidate-artifacts')
names = ('bitcoin-core-vault-gpg-candidate-amd64.iso',
         'bitcoin-core-vault-gpg-candidate-tracked-source.tar.xz',
         'candidate-build.log')

def metadata(path):
    before = path.stat()
    if path.is_symlink() or not stat.S_ISREG(before.st_mode) or before.st_size <= 0:
        raise RuntimeError('Candidate artifact must be a regular nonempty file.')
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    after = path.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise RuntimeError('Candidate artifact changed while hashing.')
    return {'name': path.name, 'bytes': before.st_size, 'sha256': digest}

assets = [metadata(root / name) for name in names]
# Independently read back the staged ISO against the actual freshly built ISO.
original = metadata(Path('/work/live-image-amd64.hybrid.iso'))
if (assets[0]['bytes'], assets[0]['sha256']) != (original['bytes'], original['sha256']):
    raise RuntimeError('Staged candidate ISO differs from the checked build output.')
manifest = {
    'schema': 1,
    'kind': 'bitcoin-core-vault-gpg-candidate',
    'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'source_commit': os.environ['VAULT_CANDIDATE_COMMIT'],
    'source_archive_scope': 'Exact tracked Git commit; not a complete corresponding-source compliance assertion.',
    'builder': 'Disposable Debian 13 amd64 CI container',
    'assets': assets,
    'validation': {
        'existing_source_and_reviewed_package_gates': 'passed',
        'synthetic_gpg_chroot_roundtrip_and_rejection_tests': 'passed',
        'iso_content_gates': {
            'tools/core-vault/check-live-iso.py': 'passed',
            'tools/core-vault/check-installer-iso.py': 'passed',
            'tools/core-vault/check-private-session.py --iso': 'passed',
        },
        'bios_and_uefi_boot': 'pending',
        'live_ram_and_installed_acceptance': 'pending',
        'end_to_end_wallet_recovery_and_psbt_on_candidate': 'pending',
        'finish_private_session_on_candidate': 'pending',
        'windows_and_macos_recovery': 'unverified',
    },
    'release_published': False,
}
output = root / 'candidate-manifest.json'
with output.open('x') as stream:
    stream.write(json.dumps(manifest, indent=2) + '\n')
assets.append(metadata(output))
with (root / 'SHA256SUMS').open('x') as stream:
    stream.write(''.join(f'{asset["sha256"]}  {asset["name"]}\n' for asset in assets))
print(json.dumps({'iso': assets[0], 'source_commit': manifest['source_commit'],
                  'scope': 'Content gates passed; boot/installation/recovery acceptance pending.'}, indent=2))
PY
printf 'Candidate artifacts staged at %s. No release was published.\n' "$ARTIFACTS"
