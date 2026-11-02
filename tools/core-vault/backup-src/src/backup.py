#!/usr/bin/python3
"""GPG/TAR backup UI. Wallet snapshots and provisional plaintext stay in verified RAM."""
from __future__ import annotations
from contextlib import contextmanager, nullcontext
import ctypes
import errno
import os
from pathlib import Path
import resource
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time

TITLE = 'Bitcoin Core Vault — Encrypted Backup'
class Cancelled(Exception): pass
class BackupError(Exception): pass

def harden():
    os.umask(0o077)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

def dialog(*args):
    r = subprocess.run(['/usr/bin/zenity', *args], stdout=subprocess.PIPE,
                       stderr=subprocess.DEVNULL, encoding='utf-8')
    if r.returncode != 0: raise Cancelled()
    # Remove exactly Zenity's final line ending, not passphrase whitespace.
    return r.stdout[:-1] if r.stdout.endswith('\n') else r.stdout

def message(text, error=False, *, operation=None):
    from message_dialog import show_message
    options = {'error': error}
    if operation is not None:
        options['operation'] = operation
    show_message(text, **options)

def validate_password(password):
    if not password or len(password.encode('utf-8')) > 512:
        raise BackupError('Use a non-empty passphrase of at most 512 UTF-8 bytes.')
    if any(ord(c) < 32 or ord(c) == 127 for c in password):
        raise BackupError('Control characters and line breaks are not supported in passphrases.')

class Progress:
    def __init__(self):
        self.p = subprocess.Popen(['/usr/bin/zenity', '--progress', '--pulsate',
            '--auto-close', '--no-markup', '--width=480', '--title='+TITLE,
            '--text=Creating and checking the encrypted backup…'],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            text=True)
    def check(self):
        if self.p.poll() is not None: raise Cancelled()
    def update(self, text):
        self.check()
        try:
            self.p.stdin.write('# ' + text.replace('\n', ' ') + '\n')
            self.p.stdin.flush()
        except BrokenPipeError:
            raise Cancelled()
    def close(self):
        if self.p.poll() is None:
            try:
                self.p.stdin.write('100\n'); self.p.stdin.flush()
                self.p.wait(timeout=3)
            except (BrokenPipeError, subprocess.TimeoutExpired): self.p.terminate()
        if self.p.stdin: self.p.stdin.close()





def selected_paths(items):
    if not items: raise BackupError('No files were selected.')
    paths = [Path(os.path.abspath(item)) for item in items]
    from gpg_backend import _path
    paths = [_path(p) for p in paths]
    if len({p.name for p in paths}) != len(paths):
        raise BackupError('Please select items with distinct top-level names.')
    from layered_backend import MAX_BYTES, MAX_ENTRIES
    total = count = 0
    for p in paths:
        count += 1
        total += p.stat().st_size if p.is_file() else 0
        if any(ord(c) < 32 or ord(c) == 127 for c in str(p)):
            raise BackupError('Control characters in file names are not supported.')
        check_regular(p)
        if p.is_dir():
            def onerror(err): raise BackupError('A selected folder cannot be read.')
            for root, dirs, files in os.walk(p, followlinks=False, onerror=onerror):
                for name in dirs + files:
                    item = Path(root)/name
                    check_regular(item)
                    count += 1
                    total += item.stat().st_size if item.is_file() else 0
                    if count > MAX_ENTRIES or total > MAX_BYTES:
                        raise BackupError('Selected data exceed the bounded RAM backup limits. Please split the backup.')
        if count > MAX_ENTRIES or total > MAX_BYTES:
            raise BackupError('Selected data exceed the bounded RAM backup limits. Please split the backup.')
    return paths

def check_regular(p):
    if any(ord(c) < 32 or ord(c) == 127 for c in str(p)):
        raise BackupError('Control characters in file names are not supported.')
    try: mode = p.lstat().st_mode
    except OSError as e: raise BackupError('A selected file is not accessible.') from e
    if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
        raise BackupError('Select regular files or folders, not symbolic links or special files.')

def _selected_wallet_files(paths, policy):
    """Find only selected RAM wallet databases, without scanning unrelated files."""
    found = {}
    roots = (policy.HOME, policy.ROOT, *policy.EXTRA_WALLET_ROOTS)
    for selected in paths:
        candidates = selected.rglob('wallet.dat') if selected.is_dir() else (selected,)
        for source in candidates:
            canonical = policy.canonical_wallet_path(source)
            if source.name != 'wallet.dat' or not any(canonical.is_relative_to(root) for root in roots):
                continue
            check_regular(source)
            if not source.is_file():
                continue
            # Check both aliases: canonicalization must not conceal a redirected
            # original /run/core-vault/home path.
            for path in (source, canonical):
                boundary = next((root for root in roots if path.is_relative_to(root)), None)
                if boundary is None:
                    raise BackupError('A selected wallet path is outside the private session.')
                for parent in (path, *path.parents):
                    if parent.is_symlink():
                        raise BackupError('A selected wallet path contains a symbolic link.')
                    if parent == boundary:
                        break
            found[source] = canonical
    return found

def _closed_wallet_snapshot(source, destination):
    """Take a consistent read-only SQLite snapshot; never bypass an open DB lock."""
    deadline = time.monotonic() + 15
    connection = sqlite3.connect(source.resolve(strict=True).as_uri() + '?mode=ro',
                                 uri=True, timeout=5)
    try:
        connection.execute('PRAGMA query_only=ON')
        connection.execute('BEGIN')
        # Establish the read transaction before copying, including WAL records.
        connection.execute('SELECT name FROM sqlite_master LIMIT 1').fetchall()
        target = sqlite3.connect(destination)
        try:
            def progress(status, remaining, total):
                if time.monotonic() >= deadline:
                    raise BackupError('The selected wallet is busy. Please close its Bitcoin Core instance and try again.')
            connection.backup(target, pages=256, progress=progress, sleep=.1)
        finally:
            target.close()
    finally:
        connection.close()

def _wallet_snapshot(source, destination, loaded, policy):
    actual = None if loaded is None else next(
        (name for name in loaded if policy.loaded_wallet_file(name) == source), None)
    if actual is None:
        _closed_wallet_snapshot(source, destination)
    else:
        policy.rpc('backupwallet', destination, wallet=actual)
    # A successful command is not sufficient proof of a usable wallet DB.
    return policy.wallet_digest(destination)

@contextmanager
def consistent_inputs(paths, policy):
    """Replace selected Core wallet files with verified snapshots in private RAM.

    Generic inputs retain the direct path when no wallet is selected. Mixed
    selections keep their names and folder structure in the temporary RAM copy.
    Related SQLite sidecars are excluded because the snapshot is self-contained.
    """
    policy.check_storage()
    wallets = _selected_wallet_files(paths, policy)
    if not wallets:
        yield paths
        return
    staging_root = (policy.ROOT / 'export').resolve(strict=True)
    if any(source.is_dir() and staging_root.is_relative_to(source.resolve(strict=True)) for source in paths):
        raise BackupError('Please select a wallet folder or individual files outside the private backup staging directory.')
    try:
        loaded = policy.rpc('listwallets')
    except RuntimeError:
        loaded = None  # Closed Core: SQLite's normal read-only locking applies.
    if loaded is not None and (not isinstance(loaded, list) or not all(isinstance(name, str) for name in loaded)):
        raise BackupError('Bitcoin Core returned an unexpected wallet inventory.')
    ignored = {wallet.with_name(wallet.name + ending) for wallet in wallets
               for ending in ('-wal', '-shm', '-journal')}
    with tempfile.TemporaryDirectory(prefix='thunar-wallet-', dir=policy.ROOT / 'export') as tmp:
        stage = Path(tmp)
        def copy(source, destination):
            check_regular(source)
            if source in ignored:
                return
            if source in wallets:
                _wallet_snapshot(wallets[source], destination, loaded, policy)
            elif source.is_dir():
                destination.mkdir(mode=0o700)
                for child in source.iterdir():
                    copy(child, destination / child.name)
            else:
                shutil.copyfile(source, destination, follow_symlinks=False)
                destination.chmod(0o600)
        for source in paths:
            copy(source, stage / source.name)
        yield [stage / source.name for source in paths if source not in ignored]

def record_wallet_export(paths, inputs, archive, password, policy, *, progress=None):
    """Record verified contents of a direct single-wallet backup at any location.

    The receipt describes the archived RAM snapshot, not durable storage.
    Mixed/folder selections retain generic file semantics.
    """
    if len(paths) != 1 or not paths[0].is_file():
        return False
    wallets = _selected_wallet_files(paths, policy)
    if paths[0] not in wallets:
        return False
    from export import media_for, verify_export
    _, label = media_for(archive)
    try:
        source = wallets[paths[0]]
        names = [name for name, path in policy.wallet_files().items()
                 if policy.canonical_wallet_path(path) == source]
        if len(names) != 1:
            raise RuntimeError('The selected wallet inventory is ambiguous.')
        raw = inputs[0]
        receipt = {'schema': 3, 'format': 'gpg-wallet', 'layers': len(password),
                   'archive': str(archive), 'archive_sha256': policy.file_digest(archive),
                   'wallet_backup_sha256': policy.file_digest(raw), 'wallet_digest': policy.wallet_digest(raw),
                   'created': int(time.time()), 'media': label}
        receipt['encryption_profile'] = 'AES256-MDC'
        verify_export(receipt, password, **({'progress': progress} if progress is not None else {}))
        policy.save_receipt(names[0], receipt)
    except (RuntimeError, OSError, sqlite3.Error, subprocess.SubprocessError) as exc:
        raise BackupError('The encrypted backup was created, but its wallet verification could not be recorded. Please keep the archive and verify it before relying on it.') from exc
    return True

def publish_new(src, dst):
    """Atomic, no-overwrite publication on Linux. Never remove an older backup."""
    libc = ctypes.CDLL(None, use_errno=True)
    rename = getattr(libc, 'renameat2', None)
    if rename is not None:
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        if rename(-100, os.fsencode(src), -100, os.fsencode(dst), 1) == 0: return
        code = ctypes.get_errno()
        if code not in (errno.ENOSYS, errno.EINVAL, errno.EOPNOTSUPP):
            raise OSError(code, os.strerror(code))
    # Also atomic/no-overwrite, but unavailable on some removable filesystems.
    os.link(src, dst)
    os.unlink(src)





def backup_destination(destination):
    path = Path(os.path.abspath(destination))
    return path if path.suffix.lower() == '.gpg' else Path(str(path) + '.gpg')

def copy_ciphertext(source, output, progress=None):
    """Poll cancellation between encrypted blocks; never copy plaintext here."""
    deadline = time.monotonic() + 300
    while True:
        if progress:
            progress.check()
        if time.monotonic() >= deadline:
            raise BackupError('Copying the encrypted backup exceeded the operation time limit.')
        block = source.read(1024 * 1024)
        if not block:
            return
        output.write(block)

def create_backup(items, destination, passwords, *, progress=None, policy=None):
    from layered_backend import create_layers, passphrases, LayerError
    from gpg_backend import GPGError, _path
    passphrases(passwords)
    paths = selected_paths(items)
    if policy is None:
        sys.path.insert(0, '/usr/lib/core-vault')
        import runtime as policy
    policy.check_storage()
    dest = _path(backup_destination(destination))
    if not dest.parent.is_dir() or os.path.lexists(dest):
        raise BackupError('Please choose a new backup name in an existing destination folder.')
    for source in paths:
        if source.is_dir() and dest.is_relative_to(source):
            raise BackupError('Please save the backup outside the selected folder.')
    ram_root = policy.ROOT / 'export'
    try:
        with tempfile.TemporaryDirectory(prefix='gpg-create-', dir=ram_root) as tmp:
            ciphertext = Path(tmp) / 'new.gpg'
            create_layers(paths, ciphertext, passwords, ram_root=ram_root, progress=progress)
            # Destination staging contains only fully verified ciphertext.
            with tempfile.TemporaryDirectory(prefix='.vault-backup-', dir=dest.parent) as target:
                work = Path(target) / 'new.gpg'
                with ciphertext.open('rb') as source, work.open('xb') as output:
                    copy_ciphertext(source, output, progress)
                    output.flush()
                    os.fsync(output.fileno())
                if policy.file_digest(work) != policy.file_digest(ciphertext):
                    raise BackupError('The encrypted copy failed verification. No backup was published.')
                if progress:
                    progress.check()
                try:
                    publish_new(work, dest)
                except FileExistsError:
                    raise BackupError('That backup already exists; it was left untouched.') from None
                try:
                    fd = os.open(dest.parent, os.O_DIRECTORY | os.O_NOFOLLOW)
                    try:
                        os.fsync(fd)
                    finally:
                        os.close(fd)
                except OSError:
                    pass
    except (GPGError, LayerError) as exc:
        raise BackupError(str(exc)) from None
    return dest

def create_ui(items):
    if not items:
        # Single selection avoids separator ambiguity in arbitrary file names.
        items = [dialog('--file-selection', '--title=Select a file to back up')]
    paths = selected_paths(items)
    strict = True
    policy = None
    if strict:
        sys.path.insert(0, '/usr/lib/core-vault')
        import runtime as policy
        policy.check_storage()
    folder = policy.PRIVATE
    default = folder/('backup-'+time.strftime('%Y%m%d-%H%M%S')+'.gpg')
    from password_dialog import get_backup_request
    def validate_for_gui(value):
        try:
            validate_password(value)
        except BackupError as exc:
            raise ValueError(str(exc)) from None
    request = get_backup_request(validate_for_gui, default, items=paths)
    if request is None:
        raise Cancelled()
    dest, password = request
    request = None
    dest = backup_destination(dest)
    for secret in password:
        validate_password(secret)
    progress = Progress()
    try:
        # This check must use the original paths, before RAM snapshot staging.
        destination = Path(dest).absolute()
        destination = destination.parent.resolve(strict=True) / destination.name
        for source in paths:
            if source.is_dir() and destination.is_relative_to(source.resolve()):
                raise BackupError('Please save the backup outside the folder being backed up.')
        prepared = consistent_inputs(paths, policy) if strict else nullcontext(paths)
        try:
            with prepared as inputs:
                result = create_backup(inputs, dest, password, progress=progress, policy=policy)
                if strict:
                    record_wallet_export(paths, inputs, result, password, policy,
                                         progress=progress)
        except (RuntimeError, sqlite3.Error) as exc:
            raise BackupError('A consistent wallet backup could not be prepared. Please close any other Bitcoin Core instance using this wallet and try again.') from exc
    finally:
        progress.close(); password = None
    message('Encrypted backup created and tested:\n'+str(result)+
            '\n\nOriginal files were NOT deleted or encrypted in place.\nKeep each passphrase separately from the backup.')

def verified_workspace():
    """Use Vault's existing storage policy; do not mount or change any filesystem."""
    helper = '/usr/local/bin/core-vault-storage-check'
    if not os.access(helper, os.X_OK):
        raise BackupError('The Vault storage checker is missing. Opening was stopped.')
    result = subprocess.run([helper, '--session'], stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, timeout=15)
    if result.returncode:
        raise BackupError('Vault storage verification failed. Opening was stopped.')
    workspace = Path.home()/'Private Workspace'
    if workspace.is_symlink() or not workspace.is_dir():
        raise BackupError('Private Workspace is missing or is a symbolic link.')
    info = workspace.stat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise BackupError('Private Workspace ownership or permissions are incorrect.')
    return workspace







def decrypt_ui(items):
    if not items:
        items = [dialog('--file-selection', '--title=Select an encrypted backup')]
    if len(items) != 1:
        raise BackupError('Please select one encrypted backup at a time.')
    paths = selected_paths(items)
    if not paths[0].is_file():
        raise BackupError('Please select a regular encrypted backup file.')
    sys.path.insert(0, '/usr/lib/core-vault')
    import runtime as policy
    policy.check_storage()
    workspace = verified_workspace()
    from recovery_dialog import get_recovery_request
    from layered_backend import recover_files, MorePassphrases, LayerError
    from gpg_backend import GPGError
    def validate(value):
        try:
            validate_password(value)
        except BackupError as exc:
            raise ValueError(str(exc)) from None
    previous, error = [], ''
    suggested = 'recovered-' + time.strftime('%Y%m%d-%H%M%S')
    while True:
        request = get_recovery_request(validate, workspace, suggested,
                                      source=paths[0], previous=previous, error=error)
        previous = []
        if request is None:
            raise Cancelled()
        destination, passwords, ordinary = request
        request = None
        progress = Progress()
        try:
            policy.check_storage()
            result = recover_files(paths[0], destination, passwords,
                ram_root=policy.ROOT / 'export', workspace=workspace, progress=progress, ordinary=ordinary)
        except MorePassphrases as exc:
            previous, error = passwords, str(exc)
            suggested = destination.name
            continue
        except (LayerError, GPGError) as exc:
            raise BackupError(str(exc)) from None
        finally:
            passwords = None
            progress.close()
        break
    message('Files recovered into Private Workspace:\n' + str(result) +
            '\n\nThese plaintext files stay in RAM until you explicitly export them. '
            'For a wallet, please restore wallet.dat in Bitcoin Core and check its addresses.',
            operation='recovery')


def main():
    harden()
    mode = sys.argv[1] if len(sys.argv) > 1 else 'decrypt'
    try:
        if os.geteuid() == 0:
            raise BackupError('Please run backup tools as the normal desktop user.')
        if mode == 'create':
            create_ui(sys.argv[2:])
        elif mode == 'decrypt':
            decrypt_ui(sys.argv[2:])
        else:
            raise BackupError('Unknown action.')
    except Cancelled:
        return 0
    except (BackupError, RuntimeError, sqlite3.Error, OSError, subprocess.SubprocessError):
        # Never interpolate third-party exceptions or backend transcripts.
        error = sys.exc_info()[1]
        text = str(error) if isinstance(error, BackupError) else 'The operation could not be completed. Originals and existing backups remain available.'
        message(text, error=True, operation='recovery' if mode == 'decrypt' else None)
        return 1
    return 0
if __name__ == '__main__': sys.exit(main())
