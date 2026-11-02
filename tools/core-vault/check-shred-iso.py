#!/usr/bin/python3
"""Read-only SquashFS verification for the reviewed delete/places/Guide changes."""
from pathlib import Path
import argparse
import json
import runpy
import subprocess


def check(squash):
    def get(path):
        return subprocess.check_output(['unsquashfs', '-cat', str(squash), path],
                                       stderr=subprocess.PIPE, timeout=90)
    root = Path(__file__).resolve().parents[2]
    checker = runpy.run_path(str(root / 'tools/core-vault/check-shred.py'))
    listing = subprocess.check_output(['unsquashfs', '-ll', str(squash)],
                                      text=True, stderr=subprocess.PIPE, timeout=90)
    checker['require']('bleachbit' not in listing.lower(),
                       'Removed BleachBit files remain in the ISO filesystem')
    status = get('var/lib/dpkg/status').decode()
    manifest = json.loads(get('etc/core-vault/installer-payload.json'))
    checker['verify_payload'](root, get, status, manifest)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--squashfs', required=True, type=Path)
    check(parser.parse_args().squashfs.resolve(strict=True))
