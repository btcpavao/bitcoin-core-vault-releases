#!/usr/bin/python3
"""Pin both official Core executables and reject the retired Vault exporter."""
import argparse, hashlib, json, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXPECTED = {
    'bitcoin-qt': 'd43632a3e54dfb181ba045db2a5b1ec2396a1acdda010e3b6d07b2e21c69c183',
    'bitcoin-cli': '83dad233fb62b1b2931efd446f7c66fe02585055143e0f0087c742732c75b52d',
}
RETIRED = ('usr/local/bin/core-vault-watch-only',
           'usr/lib/core-vault/watch_only.py', 'usr/lib/core-vault/watch_only_dialog.py')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--squashfs', type=Path)
    args = parser.parse_args()
    if args.squashfs:
        def read(name):
            return subprocess.check_output(['unsquashfs', '-cat', str(args.squashfs), name], stderr=subprocess.PIPE)
        listing = subprocess.check_output(['unsquashfs', '-ll', str(args.squashfs)], text=True)
        for name in RETIRED: assert 'squashfs-root/'+name not in listing, name
    else:
        base = ROOT/'config/includes.chroot'
        def read(name): return (base/name).read_bytes()
        for tree in (base, ROOT/'tools/core-vault/runtime-template'):
            for name in RETIRED: assert not (tree/name).exists(), name
        manifest = json.loads((ROOT/'provenance/32.1/verification.json').read_text())
        assert manifest['version'] == '32.1' and manifest['binaries'] == EXPECTED
        assert len(set(manifest['verified_signers'])) >= 2
    for name, digest in EXPECTED.items():
        assert hashlib.sha256(read('usr/local/bin/'+name)).hexdigest() == digest, name
    home = read('usr/local/bin/core-vault-home').decode()
    assert 'WATCH_ONLY_TOOL' not in home and 'wallet_probe' not in home
    guide = read('usr/local/bin/core-vault-guide').decode()
    assert 'File → Export watch-only wallet' in guide and 'File → Restore Wallet' in guide
    assert 'watch-only.json' not in guide
    print('VAULT CORE 32.1 IDENTITY AND NATIVE WATCH-ONLY CHECK PASSED')


if __name__ == '__main__': main()
