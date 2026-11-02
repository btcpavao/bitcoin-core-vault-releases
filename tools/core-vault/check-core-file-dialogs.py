#!/usr/bin/python3
"""Check the additive Vault Qt file chooser configuration without opening Core."""
from pathlib import Path
import ast
import hashlib
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
ACTIVE = ROOT / 'config/includes.chroot/usr/local/bin/core-vault-core-file-dialogs'
TEMPLATE = ROOT / 'tools/core-vault/runtime-template/usr/local/bin/core-vault-core-file-dialogs'
CORE = ROOT / 'config/includes.chroot/usr/local/bin/bitcoin-qt'
OFFICIAL_CORE_SHA256 = 'd43632a3e54dfb181ba045db2a5b1ec2396a1acdda010e3b6d07b2e21c69c183'


def main():
    assert ACTIVE.read_bytes() == TEMPLATE.read_bytes(), 'Runtime helper copies differ'
    for path in (ACTIVE, TEMPLATE):
        assert path.stat().st_mode & 0o777 == 0o755, 'Runtime helper must be executable'
        ast.parse(path.read_text(), filename=str(path))
    assert hashlib.sha256(CORE.read_bytes()).hexdigest() == OFFICIAL_CORE_SHA256, 'Official Core binary changed'
    environment = dict(os.environ, QT_QPA_PLATFORM='offscreen')
    subprocess.run([sys.executable, str(ROOT / 'tools/core-vault/test-core-file-dialogs.py')],
                   env=environment, check=True)
    print('VAULT CORE FILE DIALOG SOURCE CHECK PASSED')


if __name__ == '__main__':
    main()
