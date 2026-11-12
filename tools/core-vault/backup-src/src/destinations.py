"""Destination policy for Vault's file pickers and final output publication."""
from contextlib import contextmanager
import os
from pathlib import Path
import re

MEDIA_ROOTS = (Path('/media/vault'), Path('/run/media/vault'))
MOUNTINFO = Path('/proc/self/mountinfo')


def backup_output_path(value):
    """Expand only the display alias created by core-vault-core-file-dialogs."""
    path = Path(value)
    if (not path.is_absolute() or '..' in path.parts or
            any(ord(c) < 32 or ord(c) == 127 for c in str(path))):
        raise ValueError('Please select a full path without parent references or control characters.')
    runtime = Path(os.environ.get('XDG_RUNTIME_DIR', ''))
    alias = runtime / 'core-vault-core-file-dialogs' / 'USB Media'
    if runtime.is_absolute() and path.is_relative_to(alias):
        try:
            if (alias.parent.resolve(strict=True) != alias.parent or
                    alias.parent.stat().st_uid != os.getuid() or
                    alias.readlink() != MEDIA_ROOTS[0]):
                raise ValueError('The USB Media shortcut has changed. Please select the mounted drive again.')
        except OSError:
            raise ValueError('The USB Media shortcut is unavailable. Please select the mounted drive again.') from None
        path = MEDIA_ROOTS[0] / path.relative_to(alias)
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError('Please select the actual destination without symbolic links.')
    return path


def _mounts():
    rows = {}
    def unescape(field):
        return re.sub(r'\\([0-7]{3})', lambda m: chr(int(m[1], 8)), field)
    for line in MOUNTINFO.read_text().splitlines():
        before, _ = line.split(' - ', 1)
        mount_id, _, device, _, target, options, *_ = before.split()
        rows[mount_id] = (Path(unescape(target)), device, options.split(','))
    return rows


def _mount_id(fd):
    for line in Path(f'/proc/self/fdinfo/{fd}').read_text().splitlines():
        field, _, value = line.partition(':')
        if field == 'mnt_id':
            return value.strip()
    raise ValueError('The selected drive could not be identified.')


@contextmanager
def _directory(path):
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open('/', flags)
    try:
        for part in path.parts[1:]:
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


def _media_root(path):
    return next((root for root in MEDIA_ROOTS if path.is_relative_to(root)), None)


def _checked_media(parent, fd, root, removable):
    rows = _mounts()
    info = rows.get(_mount_id(fd))
    if info is None or info[0].parent != root or not parent.is_relative_to(info[0]):
        raise ValueError('Please select a folder on a currently mounted drive.')
    target, device, options = info
    if 'rw' not in options or os.fstatvfs(fd).f_flag & os.ST_RDONLY:
        raise ValueError('The selected drive is read-only. Please select a writable drive.')
    boot_devices = {dev for point, dev, _ in rows.values()
                    if point in (Path('/run/live/medium'), Path('/lib/live/mount/medium'))}
    if device in boot_devices:
        raise ValueError('Please select a drive other than the Vault boot medium.')
    if removable:
        # Use the same block-device ancestry detection as verified wallet exports.
        from export import media_for
        external, location = media_for(target / '.vault-destination')
        if not external or Path(location) != target:
            raise ValueError('Please select a mounted USB or removable drive for recovered files.')


def mounted_usb_volumes():
    """Return canonical writable removable volumes offered by the desktop."""
    result = set()
    try:
        candidates = _mounts().values()
    except (OSError, ValueError):
        return []
    for target, _, _ in candidates:
        if target.parent not in MEDIA_ROOTS:
            continue
        try:
            with _directory(target) as fd:
                _checked_media(target, fd, target.parent, removable=True)
                if os.access(target, os.W_OK | os.X_OK):
                    result.add(target)
        except (ValueError, OSError, ImportError):
            continue
    return sorted(result, key=lambda p: (p.name.casefold(), str(p)))


@contextmanager
def destination_directory(path, *, removable=False):
    """Pin the actual parent during staging, verification and publication."""
    root = _media_root(path)
    if removable and root is None:
        raise ValueError('Please select Private Workspace or a mounted USB drive.')
    with _directory(path) as fd:
        if root is not None:
            _checked_media(path, fd, root, removable)
        if not os.access(f'/proc/self/fd/{fd}', os.W_OK | os.X_OK):
            raise ValueError('The selected folder is not writable.')
        yield fd


def require_same_directory(path, pinned):
    """Refuse publication to a detached or replaced mount or a renamed parent."""
    with _directory(path) as current:
        if (_mount_id(current) != _mount_id(pinned) or
                not os.path.samestat(os.fstat(current), os.fstat(pinned))):
            raise ValueError('The destination changed. Please reconnect the drive and try again.')


def recovery_destination(value, workspace):
    path = backup_output_path(value)
    if not path.name or path == workspace or os.path.lexists(path):
        raise ValueError('That recovery folder already exists. Please choose a new folder name.')
    try:
        with destination_directory(path.parent, removable=path.parent != workspace):
            return path
    except OSError:
        raise ValueError('The selected recovery folder is unavailable. Please select the drive again.') from None
