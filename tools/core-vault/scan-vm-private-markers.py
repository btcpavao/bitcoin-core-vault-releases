#!/usr/bin/python3
"""Offline whole-disk marker scan of a stopped, standalone disposable VM image.

This includes deleted filesystem blocks. A pass covers only the supplied unique
synthetic markers; it is not a general guarantee about every possible secret.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time

BASE = Path('/home/pavao/vault-test-results/ram-session-20261004')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--disk', required=True, type=Path)
    parser.add_argument('--marker', required=True, action='append')
    args = parser.parse_args()
    disk = args.disk
    if disk.is_symlink() or not disk.is_file() or disk.resolve() != disk or disk.parent.parent != BASE or disk.name != 'standalone-24GiB.qcow2':
        raise RuntimeError('Only the designated regular disposable disk image is allowed.')
    for marker in args.marker:
        if len(marker) < 32 or not marker.isascii() or not marker.startswith(('CORE_VAULT_FORENSIC_TEST_', 'cv-forensic-')):
            raise RuntimeError('A unique synthetic marker is required.')
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():
            continue
        try:
            if not (proc / 'comm').read_text().startswith('qemu-system'):
                continue
            if str(disk).encode() in (proc / 'cmdline').read_bytes():
                raise RuntimeError('This test disk is still used by a running VM.')
        except FileNotFoundError:
            continue
    info = json.loads(subprocess.check_output(['qemu-img', 'info', '--output=json', str(disk)]))
    if info['format'] != 'qcow2' or info['virtual-size'] != 24 * 1024**3 or any(key in info for key in ('backing-filename', 'data-file')):
        raise RuntimeError('A standalone 24 GiB disposable qcow2 is required.')
    nonce = str(time.time_ns())
    raw = disk.parent / ('offline-scan-' + nonce + '.raw')
    if raw.exists() or raw.is_symlink():
        raise RuntimeError('Evidence cannot be overwritten.')
    subprocess.run(['qemu-img', 'convert', '-f', 'qcow2', '-O', 'raw', str(disk), str(raw)], check=True, timeout=180)
    raw.chmod(0o600)
    needles = [marker.encode() for marker in args.marker]
    keep = max(map(len, needles)) - 1
    total, overlap, hits = 0, b'', []
    digest = hashlib.sha256()
    with raw.open('rb') as stream:
        while block := stream.read(16 * 1024**2):
            digest.update(block)
            combined = overlap + block
            for needle in needles:
                position = combined.find(needle)
                if position >= 0:
                    hits.append({'marker': needle.decode(), 'offset': total - len(overlap) + position})
            total += len(block)
            overlap = combined[-keep:]
    if total != info['virtual-size']:
        raise RuntimeError('The complete virtual disk was not scanned.')
    result = {'status': 'FAIL_MARKER_FOUND' if hits else 'PASS_NO_SUPPLIED_MARKERS',
              'disk': str(disk), 'raw': str(raw), 'scanned_bytes': total,
              'raw_sha256': digest.hexdigest(), 'markers': args.marker, 'hits': hits,
              'scope': 'Supplied synthetic markers only; includes allocated and deleted blocks.'}
    (disk.parent / ('offline-scan-' + nonce + '.json')).write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))
    if hits:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
