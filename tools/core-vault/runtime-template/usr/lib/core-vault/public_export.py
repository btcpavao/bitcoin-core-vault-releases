"""Validate completed Core exports in private RAM before publishing on removable media."""
import base64
from contextlib import closing, ExitStack
import ctypes
import json
import os
from pathlib import Path
import runpy
import secrets
import shutil
import sqlite3
import stat
import subprocess
import sys

sys.path.insert(0, '/usr/lib/core-vault-backup')
from backup import BackupError, publish_new, confirm_publication
from destinations import MEDIA_ROOTS, _mount_id, destination_directory, require_same_directory

# Rows written by Core 32.1 ExportWatchOnlyWallet (wallet/export.cpp).
PUBLIC_ROWS = frozenset({
    b'flags', b'version', b'minversion', b'walletdescriptor',
    b'walletdescriptorcache', b'walletdescriptorlhcache',
    b'activeexternalspk', b'activeinternalspk', b'name', b'purpose', b'destdata',
    b'bestblock', b'bestblock_nomerkle', b'orderposnext', b'lockedutxo', b'tx', b'wtxvariant',
})
PUBLIC_FLAGS = (1 << 32) | (1 << 34)  # DISABLE_PRIVATE_KEYS and DESCRIPTORS


def core_check(method, argument, *, result=False):
    # stdin keeps the PSBT/descriptor out of process listings and accepts
    # arguments longer than Linux's per-argument limit.
    command = ['/usr/local/bin/bitcoin-cli', '-datadir=/home/vault/.bitcoin',
               '-rpcport=8332', '-rpcclienttimeout=30', '-stdin', method]
    checked = subprocess.run(command, input=argument + b'\n', timeout=40,
                             stdout=subprocess.PIPE if result else subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
    if checked.returncode:
        raise ValueError('Bitcoin Core could not validate this public export.')
    if result:
        return json.loads(checked.stdout)


def descriptor_text(value):
    # Core serializes one CompactSize-prefixed descriptor followed by creation
    # time (uint64), next index, range start and range end (int32 each).
    if not value:
        raise ValueError('Missing public descriptor.')
    prefix = value[0]
    width = {253: 2, 254: 4, 255: 8}.get(prefix, 0)
    length = int.from_bytes(value[1:1+width], 'little') if width else prefix
    start = 1 + width
    if not length or start + length + 20 != len(value):
        raise ValueError('Incomplete wallet descriptor.')
    text = value[start:start+length]
    if not text.isascii() or any(c < 33 or c == 127 for c in text):
        raise ValueError('Unexpected wallet descriptor text.')
    return text


def retain_core_windows(cleanup):
    # Core waits inside the export filesystem while Zenity asks for consent.
    # On the non-composited Vault desktop it cannot repaint exposed regions.
    # Automatic XComposite backing keeps the pixels in the X server until the
    # dialog closes; no window contents are read by the export helper.
    windows = subprocess.run(['/usr/bin/xdotool', 'search', '--onlyvisible', '--class',
                              '^bitcoin-qt$'], capture_output=True, timeout=3)
    if windows.returncode:
        return
    core_windows = [int(line) for line in windows.stdout.splitlines()]
    x11 = runpy.run_path('/usr/local/bin/core-vault-show-home')['X11']()
    cleanup.callback(x11.close)
    composite = ctypes.CDLL('libXcomposite.so.1')
    query = composite.XCompositeQueryExtension
    query.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)]
    query.restype = ctypes.c_int
    if not query(x11.display, ctypes.byref(ctypes.c_int()), ctypes.byref(ctypes.c_int())):
        return
    redirect = composite.XCompositeRedirectWindow
    redirect.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int]
    redirect.restype = None
    for window in core_windows:
        redirect(x11.display, window, 0)  # CompositeRedirectAutomatic
    x11.lib.XSync(x11.display, 0)


def check_watchonly(path):
    # The FUSE caller holds exclusive access to its completed private RAM file.
    # Use immutable here so SQLite never creates a sidecar during validation.
    uri = path.as_uri() + '?mode=ro&immutable=1'
    with closing(sqlite3.connect(uri, uri=True)) as db:
        db.execute('PRAGMA trusted_schema=OFF')
        schema = db.execute('SELECT type,name,sql FROM sqlite_schema ORDER BY type,name').fetchall()
        native_table = 'CREATE TABLE main(key BLOB PRIMARY KEY NOT NULL, value BLOB NOT NULL)'
        if schema != [('index', 'sqlite_autoindex_main_1', None), ('table', 'main', native_table)]:
            raise ValueError('This is not a native Bitcoin Core wallet export.')
        if db.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
            raise ValueError('The public wallet database is incomplete.')
        pages = db.execute('PRAGMA page_count').fetchone()[0]
        size = db.execute('PRAGMA page_size').fetchone()[0]
        if pages * size != path.stat().st_size:
            raise ValueError('Unexpected data after the wallet database.')
        flags = db.execute('SELECT value FROM main WHERE key=?', (b'\x05flags',)).fetchone()
        if not flags or not isinstance(flags[0], bytes) or len(flags[0]) != 8:
            raise ValueError('The wallet flags are missing or invalid.')
        if int.from_bytes(flags[0], 'little') & PUBLIC_FLAGS != PUBLIC_FLAGS:
            raise ValueError('Only a watch-only wallet can be exported here. Use Wallet Backup for a signing wallet.')
        descriptors = 0
        includes_metadata = False
        for (key,) in db.execute('SELECT key FROM main'):
            if not isinstance(key, bytes) or not key or key[0] >= 253 or len(key) < key[0]+1:
                raise ValueError('Invalid wallet record.')
            tag = key[1:1+key[0]]
            if tag not in PUBLIC_ROWS:
                raise ValueError('This wallet contains a record outside the public export format.')
            if tag in (b'name', b'purpose', b'destdata', b'tx', b'wtxvariant'):
                includes_metadata = True
            if tag == b'walletdescriptor':
                value = db.execute('SELECT value FROM main WHERE key=?', (key,)).fetchone()[0]
                if not isinstance(value, bytes):
                    raise ValueError('Invalid wallet descriptor.')
                summary = core_check('getdescriptorinfo', descriptor_text(value), result=True)
                if summary.get('hasprivatekeys') is not False:
                    raise ValueError('This wallet contains a private descriptor.')
                descriptors += 1
        if not descriptors:
            raise ValueError('The public wallet has no descriptors.')
    if includes_metadata:
        # Keep Core's native database intact. Obtain explicit consent before
        # any bytes reach the drive, without displaying the private label text.
        with ExitStack() as cleanup:
            try:
                retain_core_windows(cleanup)
            except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
                pass  # Optional display backing must never bypass the question.
            consent = subprocess.run([
                '/usr/bin/zenity', '--question', '--default-cancel', '--no-markup',
                '--title=Export wallet metadata?', '--ok-label=Export wallet', '--cancel-label=Cancel',
                '--text=This watch-only wallet includes address book or transaction data. '
                       'Any labels, notes or passphrases entered in these fields travel with the file. '
                       'Anyone with the file can read them. Please check these entries before exporting.',
            ], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
        if consent.returncode:
            raise ValueError('Export cancelled before writing wallet metadata to the drive.')


def validate_export(path, kind):
    if kind == 'psbt':
        if not 5 < path.stat().st_size < 100_000_000:
            raise ValueError('Invalid PSBT size.')
        with path.open('rb') as src:
            if src.read(5) != b'psbt\xff':
                raise ValueError('The selected file is not a binary PSBT.')
            src.seek(0)
            core_check('decodepsbt', base64.b64encode(src.read()))
    elif kind == 'watchonly':
        check_watchonly(path)
    else:
        raise ValueError('Unknown public export type.')


def identity(parent, name):
    try:
        info = os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode):
        raise ValueError('Choose a regular file on the transfer drive.')
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


class ExternalTarget:
    def __init__(self, parent, name, fd, original):
        self.parent, self.name, self.fd, self.original = parent, name, fd, original

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def publish(self, staged_path, kind):
        path = Path(staged_path)
        suffix = {'psbt': '.psbt', 'watchonly': '.dat'}.get(kind)
        if suffix is None or not self.name.lower().endswith(suffix):
            raise ValueError('The export format and filename do not match.')
        if kind == 'watchonly' and self.original is not None:
            raise FileExistsError('Choose a new watch-only wallet filename.')
        try:
            validate_export(path, kind)
        except (sqlite3.Error, subprocess.SubprocessError) as err:
            raise ValueError('The completed public file could not be validated.') from err
        require_same_directory(self.parent, self.fd)
        if identity(self.fd, self.name) != self.original:
            raise FileExistsError('The destination changed. Choose the filename again.')
        # On FAT and exFAT, publish_new uses the atomic Linux RENAME_NOREPLACE.
        temporary = '.vault-export-' + secrets.token_hex(12)
        tempfd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=self.fd)
        try:
            with os.fdopen(tempfd, 'wb') as dest, path.open('rb') as src:
                shutil.copyfileobj(src, dest, length=1024*1024)
                dest.flush()
                os.fsync(dest.fileno())
            require_same_directory(self.parent, self.fd)
            if identity(self.fd, self.name) != self.original:
                raise FileExistsError('The destination changed while saving. Choose another filename.')
            if self.original is None:
                pinned = Path('/proc/self/fd') / str(self.fd)
                try:
                    publish_new(pinned / temporary, pinned / self.name)
                except BackupError as err:
                    raise OSError('This filesystem could not safely publish a new export.') from err
            else:
                os.replace(temporary, self.name, src_dir_fd=self.fd, dst_dir_fd=self.fd)
            try:
                confirm_publication(self.fd, self.parent / self.name)
            except BackupError as err:
                raise OSError('The file was renamed on the drive, but the final write could not be confirmed. Verify the file before using it.') from err
        finally:
            try:
                os.unlink(temporary, dir_fd=self.fd)
            except FileNotFoundError:
                pass


def kernel_external(device, sysfs=Path('/sys')):
    """Look for a positive hardware-bus signal, never a generic hotplug hint."""
    link = sysfs / 'dev/block' / device
    try:
        physical = link.resolve(strict=True)
        for ancestor in physical.parents:
            subsystem = ancestor / 'subsystem'
            if not subsystem.is_symlink():
                continue
            bus = subsystem.resolve().name
            if bus in ('usb', 'firewire'):
                return True
            if bus == 'pci' and (ancestor / 'removable').is_file():
                if (ancestor / 'removable').read_text().strip() == 'removable':
                    return True
    except OSError:
        pass
    return False


def physical_drives(source, *, boot=False, seen=()):
    # The source field can include a btrfs subvolume suffix. lsblk's inverse
    # dependency tree follows partitions and unlocked encrypted external drives.
    block = source.split('[', 1)[0]
    if not block.startswith('/dev/'):
        raise ValueError('The selected filesystem is not on a local block device.')
    if block in seen or len(seen) >= 8:
        raise ValueError('The backing disk could not be identified.')
    result = subprocess.run(['/usr/bin/lsblk', '--inverse', '--json', '--output',
                             'NAME,TYPE,RM,TRAN,MAJ:MIN,FSTYPE', '--', block],
                            capture_output=True, text=True, check=True, timeout=5)
    devices = json.loads(result.stdout)['blockdevices']
    drives = {}
    while devices:
        row = devices.pop()
        if row.get('children'):
            devices.extend(row['children'])
            continue
        if row['type'] == 'loop' and boot:
            # File-backed Live ISO. Find the physical disk that hosts the ISO,
            # including a preserved findiso/fromiso carrier mount.
            sysnode = Path('/sys/dev/block') / row['maj:min']
            backing = (sysnode / 'loop/backing_file').read_text().strip()
            if not Path(backing).is_absolute() or not Path(backing).is_file():
                raise ValueError('The backing file for the loop device is unavailable.')
            owner = subprocess.run(['/usr/bin/findmnt', '--uniq', '--json', '--target',
                                    backing, '--output', 'SOURCE'], capture_output=True,
                                   text=True, check=True, timeout=5)
            carrier = json.loads(owner.stdout)['filesystems']
            if len(carrier) != 1:
                raise ValueError('The ISO carrier mount is ambiguous.')
            drives.update(physical_drives(carrier[0]['source'], boot=True, seen=(*seen, block)))
            continue
        if row['type'] not in ('disk', 'rom') or not row['maj:min']:
            raise ValueError('The physical transfer drive could not be identified.')
        identity = row['maj:min']
        # A directly flashed Vault ISO is an isohybrid whole device. Refuse
        # all partitions of that physical drive, including its writable EFI
        # partition, even after live-boot has replaced the medium with tmpfs.
        external = row['rm'] is True or row['tran'] in ('usb', 'sbp') or kernel_external(identity)
        drives[identity] = external and row.get('fstype') != 'iso9660'
    if not drives:
        raise ValueError('The physical transfer drive is unavailable.')
    return drives


def require_external_volume(fd):
    # Match the pinned directory's kernel mount ID, including on FUSE-backed
    # NTFS and btrfs where st_dev can differ from the drive's device number.
    try:
        result = subprocess.run(['/usr/bin/findmnt', '--list', '--json', '--output',
                                 'ID,TARGET,SOURCE,FSTYPE'], capture_output=True, text=True,
                                check=True, timeout=5)
        mounts = json.loads(result.stdout)['filesystems']
        current_id = _mount_id(fd)
        selected = next(row for row in mounts if str(row['id']) == current_id)
        drives = physical_drives(selected['source'])
        if not all(drives.values()):
            raise ValueError('Choose a drive connected through USB, FireWire or a port Linux marks as removable.')
        boot_paths = ('/run/live/medium', '/lib/live/mount/medium',
                      '/run/live/findiso', '/run/live/fromiso')
        boot_mounts = [row for row in mounts if row['target'] in boot_paths]
        if not boot_mounts:
            boot_mounts = [row for row in mounts if row['target'] == '/'
                           and row['source'].startswith('/dev/')]
        carriers = [row for row in boot_mounts if row['fstype'] not in ('tmpfs', 'ramfs')]
        image_hosts = [row for row in carriers if row['target'] in ('/run/live/findiso', '/run/live/fromiso')]
        if image_hosts:
            carriers = image_hosts  # Use the real filesystem hosting the ISO.
        if not carriers:
            # Default toram flashes are covered by the whole-device ISO check.
            # A detached *file* boot loses that signature, so don't guess its
            # physical carrier when live-boot no longer exposes it.
            args = Path('/proc/cmdline').read_text().split()
            if any(arg.startswith(('findiso=', 'fromiso=', 'iso-scan/filename=', 'vtoy'))
                   for arg in args) or Path('/dev/mapper/ventoy').exists():
                raise ValueError('The file-backed Vault boot drive could not be identified. Use Private Workspace.')
        for row in carriers:
            if drives.keys() & physical_drives(row['source'], boot=True).keys():
                raise ValueError('Choose a transfer drive other than the Vault boot medium.')
    except (OSError, subprocess.SubprocessError, KeyError, StopIteration) as err:
        raise ValueError('Vault could not identify the external transfer drive.') from err


def open_target(media_root, relative, *, replace):
    root, relative = Path(media_root), Path(relative)
    if (root not in MEDIA_ROOTS or relative.is_absolute() or len(relative.parts) < 2
            or '..' in relative.parts or any(ord(c)<32 or ord(c)==127 for c in str(relative))):
        raise ValueError('Choose a file on a mounted removable drive.')
    parent = root / relative.parent
    # The shared policy still pins and checks the writable desktop mount.
    # Public Core exports additionally accept proven external FireWire and
    # tunneled PCIe enclosures; encrypted backup policy stays independent.
    with destination_directory(parent) as fd:
        require_external_volume(fd)
        previous = identity(fd, relative.name)
        if previous is not None and (not replace or relative.suffix.lower() != '.psbt'):
            raise FileExistsError('Choose a new export filename.')
        if replace:
            if previous is None:
                raise FileNotFoundError('The selected file has disappeared.')
            if not os.access(relative.name, os.W_OK, dir_fd=fd, follow_symlinks=False):
                raise PermissionError('The selected PSBT is read-only. Please choose a new filename.')
        return ExternalTarget(parent, relative.name, os.dup(fd), previous)
