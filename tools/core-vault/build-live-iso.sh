#!/bin/bash
set -euo pipefail

HERE=$(
    cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
    pwd
)

ROOT=$(
    cd -- "$HERE/../.."
    pwd
)

cd "$ROOT"

# Fetch and verify the pinned KeePassXC release in the disposable builder.
python3 tools/core-vault/prepare-keepassxc.py

# Verify the two official Core executables and retired export removal.
python3 tools/core-vault/check-core-release.py

# VAULT_ENCRYPTED_BACKUP_V2_PREFLIGHT
python3 tools/core-vault/check-backup.py --project "$ROOT"

python3 tools/core-vault/generate-branding.py
python3 tools/core-vault/check-private-session.py
python3 tools/core-vault/check-live.py
python3 tools/core-vault/check-media.py
python3 tools/core-vault/check-home-suite.py
python3 tools/core-vault/check-files-recovery.py
python3 tools/core-vault/check-places-v2.py
python3 tools/core-vault/check-core-file-dialogs.py
python3 tools/core-vault/test-core-media-view.py
python3 tools/core-vault/test-optical-diagnostics.py
python3 tools/core-vault/check-shred.py --project "$ROOT"
python3 tools/core-vault/check-bleachbit.py

python3 tools/core-vault/check-installer.py --prebuild

sudo lb clean

STAMP=$(date +%Y%m%d-%H%M%S)

mkdir -p \
  "build-backups/vault-generated-$STAMP"

for F in binary bootstrap chroot common source; do

    if [[ -f "config/$F" ]]; then

        cp -p \
          "config/$F" \
          "build-backups/vault-generated-$STAMP/"

        rm -f "config/$F"

    fi

done

lb config

sudo lb build 2>&1 \
  | tee vault-build.log

python3 \
  tools/core-vault/check-live-iso.py \
  live-image-amd64.hybrid.iso

python3 tools/core-vault/check-installer-iso.py live-image-amd64.hybrid.iso
python3 tools/core-vault/check-private-session.py --iso live-image-amd64.hybrid.iso

ls -lh \
  live-image-amd64.hybrid.iso
