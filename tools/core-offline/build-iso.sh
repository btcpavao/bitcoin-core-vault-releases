#!/bin/bash
set -euo pipefail

HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PROJECT=$(cd -- "$HERE/../.." && pwd)

cd "$PROJECT"

python3 tools/core-offline/generate-branding.py
python3 tools/core-offline/check-project.py

sudo lb clean

STAMP=$(date +%Y%m%d-%H%M%S)

mkdir -p "build-backups/generated-$STAMP"

for F in binary bootstrap chroot common source; do
    if [[ -f "config/$F" ]]; then
        cp -p \
          "config/$F" \
          "build-backups/generated-$STAMP/"

        rm -f "config/$F"
    fi
done

lb config
sudo lb build 2>&1 | tee build.log

python3 \
  tools/core-offline/check-iso.py \
  live-image-amd64.hybrid.iso

ls -lh live-image-amd64.hybrid.iso
