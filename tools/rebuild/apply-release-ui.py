#!/usr/bin/python3
"""Apply v0.8.0's tested USB export changes to its unpacked review base."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat


RUNTIME_FILES = (
    'usr/lib/core-vault/export_view.py',
    'usr/lib/core-vault/public_export.py',
    'usr/share/core-vault/openbox.xml',
)


def replace_bytes(path, content):
    # Updating an existing inode preserves its owner, mode and extended attributes.
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError(f'Expected a single regular file at {path}')
    path.write_bytes(content)
    os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('rootfs', type=Path, help='unpacked review-base filesystem')
    parser.add_argument('source_root', type=Path, help='v0.8.0 source checkout')
    args = parser.parse_args()
    index = args.rootfs / 'etc/core-vault/installer-payload.json'
    payload = json.loads(index.read_text(encoding='utf-8'))
    for name in RUNTIME_FILES:
        path = args.rootfs / name
        if hashlib.sha256(path.read_bytes()).hexdigest() != payload['files'][name]:
            raise ValueError(f'Input does not match the installer manifest: {name}')
        data = (args.source_root / 'config/includes.chroot' / name).read_bytes()
        replace_bytes(path, data)
        payload['files'][name] = hashlib.sha256(data).hexdigest()
    payload['files'] = dict(sorted(payload['files'].items()))
    replace_bytes(index, (json.dumps(payload, indent=2) + '\n').encode('utf-8'))


if __name__ == '__main__':
    main()
