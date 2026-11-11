#!/bin/bash
# Recreate a missing Calamares input from the same frozen native sources used
# by the ISO compiler; preserve a staged file that already verifies.
set -euo pipefail
cd "$(dirname -- "$0")/../.."
if python3 tools/core-vault/check-installer.py --prebuild; then exit 0; fi
work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT
git -c tar.umask=0022 archive --format=tar HEAD > "$work/source.tar"
bash tools/rebuild/compile-package.sh calamares "$work/source.tar" "$work/result"
read -r expected filename < <(python3 - <<'PY'
import json
from pathlib import Path
record=json.loads(Path('build-assets/core-vault-calamares-v1/package.json').read_text())
print(record['sha256'],record['filename'])
PY
)
printf '%s  %s\n' "$expected" "$work/result/calamares-rebuilt.deb" | sha256sum --check
install -m 0644 "$work/result/calamares-rebuilt.deb" "config/packages.chroot/$filename"
python3 tools/core-vault/check-installer.py --prebuild
