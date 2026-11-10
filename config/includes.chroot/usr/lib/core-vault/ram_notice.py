"""Read-only, metadata-only detection of user files in Vault's RAM session.

No wallet RPC, file-content reads, backup validation, names in results/logs, or
persistent state. This is a reminder, not proof that a session is safe to end.
"""
from __future__ import annotations
import os
from pathlib import Path
import re
import stat
import time

HOME = Path('/home/vault')
RAM = Path('/run/core-vault')
ROOTS = ((HOME, 'home', True), (RAM, 'session', True),
         (Path('/tmp'), 'scratch', False), (Path('/var/tmp'), 'scratch', False),
         (Path('/run/user/1000'), 'runtime', False))
NOTICE = ('Files are stored in this private RAM session.\n'
          'Please back up what you need before restarting or shutting down.\n'
          'Files kept only in RAM will be lost.')
UNCERTAIN = ('Private-session files could not all be checked.\n'
             'Please save any work before restarting or shutting down.\n'
             'Files kept only in RAM will be lost.')
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
HOME_DEFAULTS = frozenset(('.bash_logout', '.bashrc', '.profile', '.bash_history',
    '.Xauthority', '.ICEauthority', '.dmrc', '.xsession-errors', '.xsession-errors.old',
    '.lesshst', '.wget-hsts'))
CORE_RUNTIME_FILES = frozenset(('.lock', '.cookie', '.cookie.tmp', 'debug.log',
    'settings.json', 'settings.json.bak', 'settings.json.tmp', 'bitcoin.conf',
    'peers.dat', 'anchors.dat', 'banlist.json', 'mempool.dat', 'fee_estimates.dat',
    'ip_asn.map'))
CORE_RUNTIME_DIRS = frozenset(('blocks', 'chainstate', 'indexes', 'chainstate_snapshot'))
X11_DIRS = frozenset(('.X11-unix', '.ICE-unix', '.XIM-unix', '.font-unix', '.Test-unix'))


def _unescape(value):
    return re.sub(r'\\(040|011|012|134)', lambda m: chr(int(m[1], 8)), value)


def _mount_table():
    """Kernel mount metadata, not the contents of any user's file."""
    result = {}
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        fields = line.split(); split = fields.index('-')
        result[int(fields[0])] = dict(device=fields[2], root=_unescape(fields[3]),
            target=_unescape(fields[4]), kind=fields[split+1],
            options=set(fields[5].split(',')) | set(fields[split+3].split(',')))
    return result


def _mount_id(fd):
    lines = Path('/proc/self/fdinfo', str(fd)).read_text().splitlines()
    return int(next(line.split()[1] for line in lines if line.startswith('mnt_id:')))


def _ignored(parts, scope, is_dir):
    # Never blanket-ignore user dotfiles or zero-byte documents. Only these
    # known app/profile areas do not need a wallet/document backup reminder.
    if scope == 'home':
        if parts[0] in ('.config', '.cache'):
            return True
        if len(parts) == 1 and not is_dir and parts[0] in HOME_DEFAULTS:
            return True
        if parts[:2] == ('.local', 'state'):
            return True
        if len(parts) >= 3 and parts[:2] == ('.local', 'share'):
            if parts[2] in ('gvfs-metadata', 'recently-used.xbel', 'keyrings', 'icc',
                            'mime', 'applications', 'xfce4', 'mousepad', 'keepassxc'):
                return True
            if parts[2:4] == ('Trash', 'info'):
                return True
        if parts[0] == '.bitcoin':
            tail = parts[1:]
            if tail and tail[0] in ('testnet3', 'testnet4', 'signet', 'regtest'):
                tail = tail[1:]
            if len(tail) == 1:
                return tail[0] in (CORE_RUNTIME_DIRS if is_dir else CORE_RUNTIME_FILES)
    if scope == 'session':
        if parts[0] == 'home':
            return True  # Same RAM files already scanned through /home/vault.
        if parts[0] == 'state':
            if parts[1:2] == ('core-runtime',):
                return True
            if len(parts) == 2 and parts[1] in ('exports.json', 'exports.new'):
                return True
    if scope == 'runtime':
        if parts[0] in ('dconf', 'at-spi', 'gvfs', 'gvfsd', 'pulse', 'gnupg',
                         'systemd', 'dbus-1', 'keyring', 'doc', 'gcr'):
            return True
        if len(parts) == 1 and parts[0].startswith(('core-vault-', 'core-display-')):
            return parts[0].endswith(('.log', '.lock', '.json', '.pid'))
    if scope in ('scratch', 'session'):
        if parts[-1] in X11_DIRS or parts[-1] in ('.Xauthority', '.ICEauthority'):
            return True
        if re.fullmatch(r'\.X\d+-lock', parts[-1]):
            return True
    return False


def scan_roots(roots, *, uid, root_check, max_entries=40000, seconds=0.8):
    """Return only 'files', 'empty' or 'unknown'. Never return file names.

    Each openat is no-follow, traversal stays on its original mount, and a
    bounded failure returns a caution rather than incorrectly claiming empty.
    Separate descriptors handle concurrent file moves/removals safely.
    """
    deadline = time.monotonic() + seconds
    entries = 0; uncertain = False; visited = set()

    def visit(fd, prefix, scope, mount, device):
        nonlocal entries, uncertain
        if len(prefix) > 64:
            raise TimeoutError('Directory depth bound')
        ident = os.fstat(fd)
        key = (ident.st_dev, ident.st_ino)
        if key in visited:
            return False
        visited.add(key)
        with os.scandir(fd) as iterator:
            for entry in iterator:
                entries += 1
                if entries > max_entries or time.monotonic() > deadline:
                    raise TimeoutError('Bounded metadata scan')
                parts = prefix + (entry.name,)
                try:
                    info = entry.stat(follow_symlinks=False)
                except FileNotFoundError:
                    continue
                is_dir = stat.S_ISDIR(info.st_mode)
                if _ignored(parts, scope, is_dir) or info.st_dev != device:
                    continue
                if stat.S_ISREG(info.st_mode):
                    # A copied read-only/zero-byte file still matters. No file
                    # contents are opened, and sockets/FIFOs/devices are ignored.
                    if info.st_uid == uid:
                        return True
                elif is_dir:
                    if info.st_uid != uid:
                        continue  # System-owned private scratch is not user work.
                    child = None
                    try:
                        child = os.open(entry.name, DIR_FLAGS, dir_fd=fd)
                        current = os.fstat(child)
                        if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
                            uncertain = True; continue
                        if _mount_id(child) != mount:
                            continue  # Do not enter USB/bind/GVFS child mounts.
                        if visit(child, parts, scope, mount, device):
                            return True
                    except FileNotFoundError:
                        pass
                    except OSError:
                        uncertain = True
                    finally:
                        if child is not None:
                            os.close(child)
        return False

    for path, scope, required in roots:
        fd = None
        try:
            if time.monotonic() > deadline:
                return 'unknown'
            fd = os.open(path, DIR_FLAGS)
            mount = _mount_id(fd); info = os.fstat(fd)
            if not root_check(path, scope, mount, info):
                uncertain = True; continue
            if visit(fd, (), scope, mount, info.st_dev):
                return 'files'
        except FileNotFoundError:
            uncertain = uncertain or required
        except (OSError, ValueError, StopIteration):
            uncertain = True
        finally:
            if fd is not None:
                os.close(fd)
    return 'unknown' if uncertain else 'empty'


def session_files():
    """Run only for the checked Vault account; never scan a developer's home."""
    if os.getuid() != 1000 or Path.home() != HOME:
        return 'unknown'
    try:
        mounts = _mount_table()
        # Root mount and bound home must still refer to the same protected RAM.
        ram = next(row for row in mounts.values() if row['target'] == str(RAM))
        home = next(row for row in mounts.values() if row['target'] == str(HOME))
        if (ram['kind'] != 'tmpfs' or home['kind'] != 'tmpfs'
                or ram['device'] != home['device'] or home['root'] != '/home'
                or not {'noswap', 'nodev', 'nosuid', 'noexec'} <= ram['options']):
            return 'unknown'

        def check(path, scope, mount, info):
            row = mounts.get(mount, {})
            valid = row.get('kind') == 'tmpfs' and row.get('target') == str(path)
            if scope in ('home', 'session'):
                valid = valid and info.st_uid == 1000 and row.get('device') == ram['device']
            return valid
        return scan_roots(ROOTS, uid=os.getuid(), root_check=check)
    except (OSError, ValueError, StopIteration, IndexError):
        return 'unknown'
