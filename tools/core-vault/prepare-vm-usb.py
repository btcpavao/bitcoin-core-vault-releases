#!/usr/bin/python3
"""Create/reuse only the designated file-backed FAT32 USB test image.

No host disk, mount or privileged command is used. Existing images are never
formatted again, so exported test backups survive the next VM launch.
"""
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile

SIZE = 4 * 1024**3
ROOT = Path(__file__).resolve().parents[2]


def prepare(directory):
    directory = Path(directory)
    allowed = ROOT / 'build-vm/vault-installer-v1'
    if directory not in (allowed / 'bios', allowed / 'uefi'):
        raise RuntimeError('Only the designated BIOS/UEFI test folder is allowed.')
    if ',' in str(directory):
        raise RuntimeError('A comma in the QEMU test image path is unsupported.')
    for parent in (directory, *directory.parents):
        if parent.is_symlink():
            raise RuntimeError('Symlinked test folders are refused.')
    if not directory.is_dir():
        raise RuntimeError('The VM test folder must exist.')
    image = directory / 'usb-test.raw'
    if not image.exists() and not image.is_symlink():
        formatter = shutil.which('mformat')
        if formatter is None:
            raise RuntimeError('Please install mtools on the build computer: sudo apt install mtools')
        fd, name = tempfile.mkstemp(prefix='.usb-test-', suffix='.raw', dir=directory)
        temporary = Path(name)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.truncate(SIZE)
            subprocess.run([formatter, '-i', str(temporary), '-F', '-v', 'VAULT_TEST', '::'], check=True)
            # Atomic create-new publication: never replace an existing image.
            os.link(temporary, image)
        finally:
            temporary.unlink(missing_ok=True)
    value = image.lstat()
    if (not stat.S_ISREG(value.st_mode) or value.st_uid != os.getuid()
            or value.st_nlink != 1 or value.st_size != SIZE
            or stat.S_IMODE(value.st_mode) != 0o600):
        raise RuntimeError('The virtual USB must be an owned, private, standalone 4 GiB regular file.')
    with image.open('rb') as stream:
        boot = stream.read(512)
    if boot[510:512] != b'\x55\xaa' or boot[82:90] != b'FAT32   ':
        raise RuntimeError('Existing virtual USB is not FAT32; it has not been reformatted.')
    print('Virtual USB test image ready: ' + str(image))
    return image


if __name__ == '__main__':
    try:
        if len(sys.argv) != 2:
            raise RuntimeError('Please provide the designated VM test folder.')
        prepare(sys.argv[1])
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
