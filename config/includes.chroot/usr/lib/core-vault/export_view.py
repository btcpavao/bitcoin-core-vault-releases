"""A read-through view of attached drives with a RAM-only public-export writer.

Only regular-file reads reach the underlying filesystem directly. A prospective
public export and its SQLite rollback journal are kept in a fresh private tmpfs
directory until the completed file passes the independent publication policy.
"""
import errno
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import time

from fusepy import FuseOSError, Operations

from public_export import open_target

PSBT_LIMIT = 100_000_000  # Core's maximum accepted PSBT size (exclusive).
DIR = os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
STAT = ('st_mode', 'st_uid', 'st_gid', 'st_atime', 'st_mtime', 'st_ctime',
        'st_size', 'st_nlink', 'st_ino')


def storage_error(error):
    if error.errno in (errno.ENOSPC, errno.EDQUOT):
        return 'Private RAM is full. Free space in the live session and try again.'
    if error.errno == errno.EFBIG:
        return 'The PSBT exceeds the size supported by Bitcoin Core.'
    return error


class Export:
    def __init__(self, root, key, scratch, replace):
        self.target = open_target(root, Path(key), replace=replace)
        try:
            self.folder = tempfile.TemporaryDirectory(prefix='file-', dir=scratch)
        except BaseException:
            self.target.close()
            raise
        self.main = Path(self.folder.name) / 'export'
        self.journal = self.main.with_name('export-journal')
        self.handles = set()
        self.opened = time.monotonic()
        self.committed = False
        self.failed = False

    def close(self):
        try:
            self.folder.cleanup()
        finally:
            self.target.close()


class MediaView(Operations):
    def __init__(self, root, scratch):
        self.root = Path(root)
        self.root_fd = os.open(root, DIR)
        self.scratch = scratch
        self.files = {}
        self.handles = {}
        self.errors = []

    @staticmethod
    def key(path):
        if not path.startswith('/') or any(p in ('.', '..') for p in path.split('/')):
            raise FuseOSError(errno.EINVAL)
        return path.strip('/')

    def parent(self, key):
        """Walk the backing directories without traversing device-supplied links."""
        parent = os.dup(self.root_fd)
        try:
            for part in Path(key).parts[:-1]:
                child = os.open(part, DIR, dir_fd=parent)
                os.close(parent)
                parent = child
            return parent
        except BaseException:
            os.close(parent)
            raise

    def backing_stat(self, key):
        if not key:
            return os.fstat(self.root_fd)
        parent = self.parent(key)
        try:
            return os.stat(Path(key).name, dir_fd=parent, follow_symlinks=False)
        finally:
            os.close(parent)

    def open_backing(self, key, flags):
        if not key:
            return os.dup(self.root_fd)
        parent = self.parent(key)
        try:
            return os.open(Path(key).name, flags | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        finally:
            os.close(parent)

    def staged(self, key):
        if key in self.files:
            return self.files[key], self.files[key].main
        if key.endswith('-journal'):
            record = self.files.get(key[:-8])
            if record and key[:-8].lower().endswith('.dat'):
                return record, record.journal
        return None, None

    def forget(self, key):
        self.files.pop(key).close()

    def sweep(self):
        # The watch-only exporter first creates and closes an empty placeholder.
        # Aborted probes disappear without touching the drive.
        for key, record in list(self.files.items()):
            if not record.handles and time.monotonic() - record.opened > 300:
                self.forget(key)

    def report(self, key, error):
        # Core 32.1 can display "PSBT saved to disk" even on an I/O failure.
        # Surface the actual failure from the broker outside the confined GUI.
        self.errors[:] = [p for p in self.errors if p.poll() is None]
        if len(self.errors) < 3:
            try:
                self.errors.append(subprocess.Popen([
                    '/usr/bin/zenity', '--error', '--title=External export failed', '--no-markup',
                    '--text=Vault could not confirm the external export.\n\n' +
                    str(self.root / key) + '\n\n' + str(error)
                ], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
            except OSError:
                pass

    def getattr(self, path, fh=None):
        key = self.key(path)
        record, stage = self.staged(key)
        if fh is not None:
            info = os.fstat(fh)
        elif record:
            info = stage.stat()
        else:
            info = self.backing_stat(key)
        return {k: getattr(info, k) for k in STAT}

    def readlink(self, path):
        # Return the link text only. The calling kernel resolves it inside
        # Core's own namespace; backing file opens still refuse symlinks.
        key = self.key(path)
        parent = self.parent(key)
        try:
            return os.readlink(Path(key).name, dir_fd=parent)
        finally:
            os.close(parent)

    def readdir(self, path, fh):
        key = self.key(path)
        fd = self.open_backing(key, DIR)
        try:
            # Qt and fusepy use UTF-8. A byte-only filename on a Linux drive
            # must not make the rest of the directory disappear from the picker.
            names = {name for name in os.listdir(fd) if os.fsencode(name).decode('utf-8', 'ignore') == name}
        finally:
            os.close(fd)
        for candidate in self.files:
            parent, _, leaf = candidate.rpartition('/')
            if key == parent:
                names.add(leaf)
        return ['.', '..', *sorted(names)]

    def statfs(self, path):
        try:
            fd = self.open_backing(self.key(path), os.O_PATH)
        except FileNotFoundError:
            fd = self.parent(self.key(path))
        try:
            result = os.fstatvfs(fd)
            return {key: getattr(result, key) for key in dir(result) if key.startswith('f_')}
        finally:
            os.close(fd)

    def access(self, path, mode):
        info = self.getattr(path)
        if mode & os.W_OK:
            key = self.key(path)
            if stat.S_ISDIR(info['st_mode']):
                if not key or not self.writable_dir(key):
                    raise FuseOSError(errno.EROFS)
            elif not self.staged(key)[0] and not key.lower().endswith('.psbt'):
                raise FuseOSError(errno.EROFS)
        return 0

    def writable_dir(self, key):
        fd = self.open_backing(key, DIR)
        try:
            return not os.fstatvfs(fd).f_flag & os.ST_RDONLY and os.access('.', os.W_OK, dir_fd=fd)
        finally:
            os.close(fd)

    def allocate(self, key, replace):
        self.sweep()
        try:
            if len(self.files) >= 32:
                raise OSError(errno.EBUSY, 'Too many pending external exports.')
            if '/' not in key or Path(key).suffix.lower() not in ('.psbt', '.dat'):
                raise OSError(errno.EROFS, 'Choose a .psbt or a new watch-only .dat file on a mounted drive.')
            record = Export(self.root, key, self.scratch, replace=replace)
        except (OSError, RuntimeError, ValueError) as exc:
            self.report(key, exc)
            raise FuseOSError(getattr(exc, 'errno', None) or errno.EACCES) from exc
        self.files[key] = record
        return record

    def writable(self, key, flags, creating):
        record, stage = self.staged(key)
        if record is None:
            replace = not creating
            if replace and not key.lower().endswith('.psbt'):
                raise FuseOSError(errno.EROFS)
            if replace and not flags & os.O_TRUNC:
                # SQLite attempting to open a real wallet read-write must fall
                # back to its read-only import path, not get a writable copy.
                raise FuseOSError(errno.EROFS)
            record = self.allocate(key, replace)
            stage = record.main
        elif stage == record.main and (record.handles or record.committed or record.failed):
            raise FuseOSError(errno.EBUSY)
        try:
            fd = os.open(stage, flags | (os.O_CREAT if creating or not stage.exists() else 0)
                         | os.O_NOFOLLOW, 0o600)
        except OSError:
            if stage == record.main and not record.handles:
                self.forget(key)
            raise
        self.handles[fd] = (record, key, True)
        record.handles.add(fd)
        return fd

    def create(self, path, mode):
        return self.writable(self.key(path), os.O_RDWR | os.O_CREAT | os.O_EXCL, True)

    def open(self, path, flags):
        key = self.key(path)
        if flags & (os.O_ACCMODE | os.O_TRUNC):
            return self.writable(key, flags, False)
        record, stage = self.staged(key)
        if record:
            fd = os.open(stage, os.O_RDONLY | os.O_NOFOLLOW)
            record.handles.add(fd)
        else:
            fd = self.open_backing(key, os.O_RDONLY)
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                os.close(fd)
                raise FuseOSError(errno.EACCES)
        self.handles[fd] = (record, key, False)
        return fd

    def read(self, path, size, offset, fh):
        return os.pread(fh, size, offset)

    def write(self, path, data, offset, fh):
        record, key, writable = self.handles[fh]
        if not writable or record is None or record.failed or record.committed:
            raise FuseOSError(errno.EROFS)
        try:
            if offset < 0 or (key.lower().endswith('.psbt') and offset + len(data) >= PSBT_LIMIT):
                raise FuseOSError(errno.EFBIG)
            count = os.pwrite(fh, data, offset)
            if count != len(data):
                raise FuseOSError(errno.ENOSPC)
            return count
        except OSError as exc:
            record.failed = True
            self.report(key, storage_error(exc))
            raise

    def truncate(self, path, length, fh=None):
        key = self.key(path)
        record, stage = self.staged(key)
        if not record:
            # Some libfuse/kernel pairs send a separate truncate before open.
            # Admit only a regular existing PSBT and defer the actual truncate
            # until a new write handle exists in RAM.
            if length == 0 and key.lower().endswith('.psbt') and stat.S_ISREG(self.backing_stat(key).st_mode):
                record = self.allocate(key, True)
                stage = record.main
                stage.touch(mode=0o600)
            else:
                raise FuseOSError(errno.EROFS)
        if record.committed or record.failed:
            raise FuseOSError(errno.EROFS)
        try:
            if length < 0 or (key.lower().endswith('.psbt') and length >= PSBT_LIMIT):
                raise FuseOSError(errno.EFBIG)
            os.truncate(stage, length)
        except OSError as exc:
            record.failed = True
            self.report(key, storage_error(exc))
            raise
        return 0

    def fsync(self, path, datasync, fh):
        os.fsync(fh)
        return 0

    def flush(self, path, fh):
        record, key, writable = self.handles[fh]
        if writable and record and not record.failed and not record.committed:
            _, stage = self.staged(key)
            if stage == record.main:
                if key.lower().endswith('.dat') and os.fstat(fh).st_size == 0:
                    return 0  # Core's initial create probe, no durable write.
                try:
                    if record.journal.exists():
                        raise RuntimeError('The wallet database transaction is incomplete.')
                    kind = 'psbt' if key.lower().endswith('.psbt') else 'watchonly'
                    record.target.publish(record.main, kind)
                    record.committed = True
                except Exception as exc:
                    record.failed = True
                    self.report(key, exc)
                    raise FuseOSError(getattr(exc, 'errno', None) or errno.EIO) from exc
        return 0

    def release(self, path, fh):
        record, key, _ = self.handles.pop(fh)
        os.close(fh)
        if record:
            record.handles.discard(fh)
            if not record.handles and (record.committed or record.failed):
                owner = key[:-8] if key.endswith('-journal') else key
                self.forget(owner)
        return 0

    def unlink(self, path):
        key = self.key(path)
        record, stage = self.staged(key)
        if not record or record.committed:
            raise FuseOSError(errno.EROFS)
        if stage == record.journal:
            stage.unlink()
        elif not record.handles:
            self.forget(key)
        else:
            raise FuseOSError(errno.EBUSY)
        return 0

    def destroy(self, path):
        for fd in list(self.handles):
            os.close(fd)
        self.handles.clear()
        for key in list(self.files):
            self.forget(key)
        os.close(self.root_fd)
