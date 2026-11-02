"""Read-only private session policy and minimal wallet/archive state helpers."""
from pathlib import Path
import hashlib
import json
import os
import sqlite3
import stat
import subprocess
import tempfile

ROOT = Path('/run/core-vault')
HOME = Path('/home/vault')
CORE = HOME / '.bitcoin'
WALLETS = CORE / 'wallets'
PRIVATE = HOME / 'Private Workspace'
STATE = ROOT / 'state'
EXTRA_WALLET_ROOTS = (Path('/tmp'), Path('/var/tmp'))

def mount_at(path, exact=False):
    result = subprocess.run(['/usr/bin/findmnt', '-J', '--uniq', '-M' if exact else '-T', str(path),
                             '-o', 'TARGET,FSTYPE,OPTIONS,MAJ:MIN,FSROOT'],
                            capture_output=True, text=True, timeout=5, check=True)
    rows = json.loads(result.stdout)['filesystems']
    if len(rows) != 1:
        raise RuntimeError('Ambiguous filesystem.')
    return rows[0]

def check_storage():
    if Path('/proc/swaps').read_text().splitlines()[1:]:
        raise RuntimeError('Swap is active.')
    ram, home = mount_at(ROOT, True), mount_at(HOME, True)
    if ram['fstype'] != 'tmpfs' or ram['target'] != str(ROOT):
        raise RuntimeError('The private workspace is not its own RAM filesystem.')
    if not {'noswap', 'nosuid', 'nodev', 'noexec'}.issubset(ram['options'].split(',')):
        raise RuntimeError('Private workspace mount protection is incomplete.')
    if home['fstype'] != 'tmpfs' or home['maj:min'] != ram['maj:min'] or home['fsroot'] != '/home':
        raise RuntimeError('The account HOME is not bound to the private RAM workspace.')
    for path in (ROOT, HOME, CORE, WALLETS, PRIVATE, HOME / '.config', HOME / '.cache',
                 HOME / '.local', HOME / '.local/share', HOME / '.local/state',
                 ROOT / 'export', ROOT / 'tmp', STATE, STATE / 'core-runtime'):
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or (info.st_uid, info.st_gid) != (1000, 1000) or stat.S_IMODE(info.st_mode) != 0o700:
            raise RuntimeError('Private directory ownership or permissions are incorrect.')
        if mount_at(path)['maj:min'] != ram['maj:min']:
            raise RuntimeError('A private directory is outside the RAM mount.')

def _visible_mount_id(path):
    """Read the visible kernel mount ID without reading any file contents.

    A mountinfo record can survive underneath an overmounted ancestor. O_PATH
    resolves the current path, and fdinfo identifies its actual visible mount.
    Only a missing target path is ignorable; metadata errors remain failures.
    """
    try:
        descriptor = os.open(path, os.O_PATH | os.O_CLOEXEC)
    except FileNotFoundError:
        return None
    try:
        rows = (Path('/proc/self/fdinfo') / str(descriptor)).read_text().splitlines()
        values = [row.split() for row in rows if row.startswith('mnt_id:')]
        if len(values) != 1 or len(values[0]) != 2 or not values[0][1].isdigit():
            raise RuntimeError('The visible Core filesystem mount identity could not be verified.')
        return int(values[0][1])
    finally:
        os.close(descriptor)

def check_core_mounts():
    """Reject child mounts that a recursive writable Core bind could expose.

    The normal storage check verifies the private RAM roots. Core also needs
    their complete mount topology: a portal, GVFS mount or even another tmpfs
    beneath a writable root would cross the audited filesystem boundary.
    This additional restriction applies only to the Core launch workflow.
    """
    result = subprocess.run(['/usr/bin/findmnt', '--uniq', '--list', '-J', '-o', 'TARGET,ID'],
                            capture_output=True, text=True, timeout=5, check=True)
    rows = json.loads(result.stdout).get('filesystems')
    if not isinstance(rows, list) or not rows:
        raise RuntimeError('The Core filesystem mount topology could not be verified.')
    roots = (ROOT, HOME, *EXTRA_WALLET_ROOTS)
    for row in rows:
        target = row.get('target') if isinstance(row, dict) else None
        if not isinstance(target, str) or not Path(target).is_absolute() or row.get('children'):
            raise RuntimeError('The Core filesystem mount topology could not be verified.')
        path = Path(target)
        if any(path != root and path.is_relative_to(root) for root in roots):
            identity = row.get('id')
            if type(identity) is not int or identity <= 0:
                raise RuntimeError('The Core filesystem mount topology could not be verified.')
            if _visible_mount_id(path) == identity:
                raise RuntimeError('A nested mount is present inside a private Core writable directory. Please unmount it before opening Bitcoin Core.')

def canonical_wallet_path(path):
    """Unify the two aliases of the RAM home without following user links."""
    path = Path(os.path.abspath(path))
    ram_home = ROOT / 'home'
    if path.is_relative_to(ram_home):
        path = HOME / path.relative_to(ram_home)
    return path

def loaded_wallet_file(name):
    path = canonical_wallet_path(Path(name) if Path(name).is_absolute() else WALLETS / name)
    return path if path.is_file() else path / 'wallet.dat'

def loaded_wallet_name(wallet, loaded):
    expected = loaded_wallet_file(wallet)
    return next((name for name in loaded if loaded_wallet_file(name) == expected), None)

def wallet_files():
    """Inventory RAM wallets, including Core's supported absolute/../ paths.

    Only the default wallet directory gets relative RPC names. Other discovered
    databases get an absolute RAM path for Core's official load/backup workflow.
    Helper snapshots are removed after use. Any wallet left in export/scratch
    must remain inventoried, including a pathlike wallet unloaded by the user.
    """
    result = {}
    if WALLETS.is_symlink():
        raise RuntimeError('The wallet directory is redirected.')
    roots = (WALLETS, HOME, ROOT, *EXTRA_WALLET_ROOTS)
    for root in roots:
        if not root.exists():
            continue
        def unreadable(error):
            raise RuntimeError('A private directory could not be inventoried. Normal session destruction has been stopped.') from error
        for base, dirs, files in os.walk(root, followlinks=False, onerror=unreadable):
            if root == ROOT and Path(base) == ROOT:
                dirs[:] = [name for name in dirs if name != 'home']
            for name in dirs + files:
                path = Path(base) / name
                if path.is_symlink() or not (path.is_dir() or path.is_file()):
                    # Desktop caches can contain harmless links. Core's wallet
                    # directory remains strictly link-free, including its root.
                    if Path(base).is_relative_to(WALLETS):
                        raise RuntimeError('A wallet directory contains a link or special object.')
            def visible_directory(name):
                path = Path(base) / name
                if path.is_symlink():
                    return False
                # systemd's root-only private scratch directories cannot hold a
                # Vault-created wallet and need not block normal finish. A
                # Vault-owned unreadable directory or writable blind directory
                # remains a failure rather than hiding a possible wallet.
                return (path.stat().st_uid == os.getuid() or
                        os.access(path, os.R_OK | os.X_OK) or
                        os.access(path, os.W_OK | os.X_OK))
            dirs[:] = [name for name in dirs if visible_directory(name)]
            if 'wallet.dat' in files:
                path = canonical_wallet_path(Path(base) / 'wallet.dat')
                if path.is_symlink() or not path.is_file():
                    raise RuntimeError('A wallet database is redirected or is not a regular file.')
                if path.is_relative_to(WALLETS):
                    name = str(path.parent.relative_to(WALLETS))
                    name = '' if name == '.' else name
                else:
                    name = str(path.parent)
                result[name] = path
    return result

def check_loaded_wallet_coverage(wallets):
    """Refuse normal finish if Core loaded a wallet our RAM inventory missed."""
    try:
        loaded = rpc('listwallets')
    except RuntimeError:
        return  # Closed Core still has the full filesystem inventory above.
    if not isinstance(loaded, list) or not all(isinstance(name, str) for name in loaded):
        raise RuntimeError('Bitcoin Core returned an unexpected wallet inventory.')
    known = {canonical_wallet_path(path) for path in wallets.values()}
    if any(loaded_wallet_file(name) not in known for name in loaded):
        raise RuntimeError('Bitcoin Core has a wallet outside the supported private workspace. Please make a verified backup before finishing; normal session destruction has been stopped.')

def wallet_digest(path):
    """Hash SQLite logical records in RAM, independent of WAL/checkpoint layout.
    Export uses Core's backupwallet RPC, never a copy of a live database.
    Refuse unrecognized/legacy databases instead of declaring them verified.
    """
    if path.is_symlink() or not path.is_file():
        raise RuntimeError('Wallet database is missing or redirected.')
    connection = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=5)
    try:
        connection.execute('PRAGMA query_only=ON')
        connection.execute('BEGIN')
        if connection.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
            raise RuntimeError('Wallet database validation failed.')
        tables = connection.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
        if tables != [('main',)]:
            raise RuntimeError('Unsupported wallet database layout.')
        digest = hashlib.sha256()
        for key, value in connection.execute('SELECT key,value FROM main ORDER BY key'):
            for blob in (key, value):
                if not isinstance(blob, bytes):
                    raise RuntimeError('Unsupported wallet record.')
                digest.update(len(blob).to_bytes(8, 'big'))
                digest.update(blob)
        return digest.hexdigest()
    finally:
        connection.close()

def file_digest(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()

def rpc(method, *params, wallet=None):
    command = ['/usr/local/bin/bitcoin-cli', '-datadir=' + str(CORE), '-rpcport=8332']
    if wallet is not None:
        command.append('-rpcwallet=' + wallet)
    command.extend([method, *[str(value) for value in params]])
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise RuntimeError('Bitcoin Core could not complete the requested wallet operation.')
    value = result.stdout.strip()
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        # bitcoin-cli prints JSON string results as plain text (e.g. stop and
        # getnewaddress), while objects/arrays/numbers retain JSON formatting.
        return value

def current_wallet_digest(wallet, path):
    """Use Core's consistent RAM backup for its exclusively locked open SQLite DB.
    Closed/unloaded wallets are read directly. Never bypass SQLite locks or hash
    a potentially inconsistent live database with immutable=1.
    """
    try:
        loaded = rpc('listwallets')
    except RuntimeError:
        # With Core closed, a normal read-only connection is safe. If another
        # process still holds the database, SQLite refuses it and finish fails.
        return wallet_digest(path)
    actual = loaded_wallet_name(wallet, loaded)
    if actual is None:
        return wallet_digest(path)
    with tempfile.TemporaryDirectory(prefix='wallet-state-', dir=ROOT / 'export') as tmp:
        raw = Path(tmp) / 'wallet.dat'
        rpc('backupwallet', raw, wallet=actual)
        return wallet_digest(raw)

def read_receipts():
    path = STATE / 'exports.json'
    if not path.exists():
        return {}
    if path.is_symlink() or path.stat().st_uid != os.getuid():
        raise RuntimeError('Unexpected export verification record.')
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise RuntimeError('Invalid export verification record.')
    return value

def save_receipt(wallet, value):
    receipts = read_receipts()
    receipts[wallet] = value
    path = STATE / 'exports.json'
    temporary = STATE / 'exports.new'
    with open(temporary, 'x', encoding='utf-8', opener=lambda p, f: os.open(p, f | os.O_NOFOLLOW, 0o600)) as stream:
        json.dump(receipts, stream)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
