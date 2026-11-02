#!/usr/bin/python3
"""Exercise the actual Core launcher inside an unprivileged RAM-only fixture.

Run on the Debian build computer with --core-root ./chroot. The outer bwrap
maps the caller to UID/GID 1000 and isolates host processes/networking. Its
host root is read-only; every writable fixture and all synthetic wallet state
are tmpfs or /dev/shm. The production launcher creates a second, real bwrap.

Only core-vault-storage-check is substituted: the fixture checks RAM backing,
ownership and permissions, but does not certify installed noswap mount flags,
systemd/login ordering, real removable media, power loss or final ISO contents.
The Hide observer is inert by default; --real-observer retains current source.
Only generated immutable fixture source code uses a temporary project folder,
mounted read-only, so /dev/shm's noexec policy does not block its shebangs.
No shutdown, mount, sudo or umount command is issued on the developer host.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import uuid


STORAGE_FIXTURE = '''#!/usr/bin/python3
"""TEST FIXTURE ONLY: installed noswap/systemd layout is not certified."""
import json, os, stat, subprocess, sys
from pathlib import Path
if sys.argv[1:] != ['--session', '--core'] or (os.getuid(), os.getgid()) != (1000, 1000):
    raise SystemExit('Invalid synthetic storage fixture identity or invocation')
root = Path('/run/core-vault')
for path in (root, Path('/home/vault'), Path('/home/vault/.bitcoin'),
             Path('/home/vault/.bitcoin/wallets'),
             Path('/home/vault/Private Workspace'), Path('/home/vault/.config'),
             Path('/home/vault/.cache'), Path('/home/vault/.local'),
             Path('/home/vault/.local/share'), Path('/home/vault/.local/state'),
             root/'export', root/'tmp', root/'state', root/'state/core-runtime',
             Path('/run/user/1000')):
    value = path.lstat()
    row = json.loads(subprocess.check_output(
        ['/usr/bin/findmnt','-J','--uniq','-T',str(path),'-o','FSTYPE'], text=True))['filesystems'][0]
    if not stat.S_ISDIR(value.st_mode) or row['fstype'] != 'tmpfs':
        raise SystemExit('Synthetic private fixture is not a RAM directory')
    if (value.st_uid, value.st_gid, stat.S_IMODE(value.st_mode)) != (1000,1000,0o700):
        raise SystemExit('Synthetic private fixture ownership/mode mismatch')
sys.path.insert(0, '/opt/core-vault')
from runtime import check_core_mounts
try:
    check_core_mounts()
except RuntimeError:
    rows = json.loads(subprocess.check_output(['/usr/bin/findmnt','--uniq','--list','-J',
        '-o','TARGET,FSTYPE,OPTIONS,MAJ:MIN'], text=True))['filesystems']
    roots = (root, Path('/home/vault'), Path('/tmp'), Path('/var/tmp'))
    nested = [row for row in rows if any(Path(row['target']) != base and
        Path(row['target']).is_relative_to(base) for base in roots)]
    print('TEST FIXTURE NESTED MOUNT RECORDS ' + json.dumps(nested), file=sys.stderr)
    raise
print('TEST FIXTURE RAM CHECK PASSED; installed noswap/layout remains untested')
'''


def core_processes():
    result = {}
    for path in Path('/proc').iterdir():
        if not path.name.isdigit():
            continue
        try:
            values = (path / 'cmdline').read_bytes().split(b'\0')
            if values[0] == b'/usr/local/bin/bitcoin-qt':
                result[int(path.name)] = values
        except (OSError, IndexError):
            pass
    return result


def mount_flags(pid, destination):
    """Read effective kernel flags through the actual process root.

    Stacked bwrap binds can have multiple mountinfo records for one path;
    statvfs resolves the visible top mount rather than guessing record order.
    """
    path = str(Path('/proc', str(pid), 'root')) + destination
    return {'ro'} if os.statvfs(path).f_flag & os.ST_RDONLY else {'rw'}


def fixture_mount_diagnostics():
    for target in ('/tmp', '/var/tmp', '/run/user/1000'):
        legacy = subprocess.check_output(
            ['/usr/bin/findmnt', '--noheadings', '--output', 'FSTYPE', '--target', target],
            text=True)
        metadata = json.loads(subprocess.check_output(
            ['/usr/bin/findmnt', '-J', '-T', target, '-o', 'TARGET,FSTYPE,OPTIONS,MAJ:MIN,FSROOT'],
            text=True))
        effective = json.loads(subprocess.check_output(
            ['/usr/bin/findmnt', '-J', '--uniq', '-T', target,
             '-o', 'TARGET,FSTYPE,OPTIONS,MAJ:MIN,FSROOT'], text=True))
        actual = subprocess.check_output(['/usr/bin/stat', '-f', '--format=%T', target], text=True).strip()
        print('[INFO] FIXTURE MOUNTS ' + json.dumps({'target': target,
              'legacy_findmnt_fstype': legacy, 'effective_statfs_fstype': actual,
              'mount_records': metadata['filesystems'],
              'effective_uniq_mount_records': effective['filesystems']}), flush=True)


def guest():
    token = os.environ.get('CORE_VAULT_LAUNCHER_FIXTURE', '')
    marker = Path('/run/core-vault/launcher-fixture-identity')
    if not token or not marker.is_file() or marker.read_text() != token:
        raise RuntimeError('The guest probe requires the uniquely identified outer test fixture.')
    if 'ro' not in mount_flags(os.getpid(), '/'):
        raise RuntimeError('The guest probe requires a read-only outer root filesystem.')
    # This test-only import alias sits below outer tmpfs /opt. The Debian host
    # does not need an existing writable /usr/lib/core-vault directory.
    sys.path.insert(0, '/opt/core-vault')
    import runtime
    if (os.getuid(), os.getgid()) != (1000, 1000):
        raise RuntimeError('The outer fixture did not map the Vault identity.')
    os.umask(0o077)
    Path('/dev/shm/synthetic-forbidden').mkdir(mode=0o700)
    fixture_mount_diagnostics()
    (runtime.CORE / 'bitcoin.conf').write_text('chain=regtest\n')
    output_path = runtime.ROOT / 'launcher-fixture.log'
    output = output_path.open('xb')
    launcher = subprocess.Popen(['/usr/local/bin/core-vault-bitcoin'],
                                stdout=output, stderr=output)
    wallet = 'synthetic-launcher-' + uuid.uuid4().hex
    try:
        for attempt in range(160):
            if launcher.poll() is not None:
                raise RuntimeError('Production launcher exited: ' + output_path.read_text()[-5000:])
            try:
                info = runtime.rpc('getnetworkinfo')
                break
            except RuntimeError:
                time.sleep(.25)
        else:
            raise RuntimeError('The production launcher never provided local RPC.')
        assert info['networkactive'] is False
        processes = core_processes()
        assert len(processes) == 1, 'Expected exactly one official Core process'
        pid, argv = next(iter(processes.items()))
        for flag in (b'-datadir=/home/vault/.bitcoin',
                     b'-walletdir=/home/vault/.bitcoin/wallets', b'-rpcport=8332',
                     b'-rpcbind=127.0.0.1', b'-networkactive=0',
                     b'-settings=/home/vault/.bitcoin/settings.json'):
            assert flag in argv, 'The live Core argv differs from the private launcher policy'
        assert not any(argument.partition(b'=')[0] == b'-nosettings' for argument in argv), \
            'Disabled dynamic settings break the GUI wallet loader'
        assert 'ro' in mount_flags(pid, '/')
        assert 'rw' in mount_flags(pid, str(runtime.WALLETS))
        assert 'rw' in mount_flags(pid, str(runtime.ROOT / 'export'))
        assert 'ro' in mount_flags(pid, '/run/user/1000')
        assert 'rw' in mount_flags(pid, str(runtime.STATE / 'core-runtime'))
        environment = (Path('/proc') / str(pid) / 'environ').read_bytes().split(b'\0')
        assert b'XDG_RUNTIME_DIR=/run/core-vault/state/core-runtime' in environment
        print('[PASS] Actual launcher and helper execute official Core with RAM paths and loopback RPC')
        print('[PASS] Core uses its private writable RAM runtime; shared desktop runtime remains read-only')

        def assert_wallet_state(loaded, startup):
            assert (wallet in runtime.rpc('listwallets')) is loaded
            settings = runtime.CORE / 'settings.json'
            assert settings.is_file() and not settings.is_symlink()
            assert (wallet in json.loads(settings.read_text()).get('wallet', [])) is startup, \
                'RAM settings did not record the requested wallet startup transition'
            assert launcher.poll() is None and core_processes() == processes, \
                'Wallet startup setting transition replaced or stopped the original Core process'

        # The Qt wallet loader always requests load_on_startup=true. RPC's
        # omitted default bypasses settings writes and missed the -nosettings
        # crash, so exercise the same backend path explicitly without UI input.
        runtime.rpc('createwallet', wallet, 'false', 'false', '', 'false', 'true', 'true')
        assert_wallet_state(loaded=True, startup=True)
        runtime.rpc('unloadwallet', wallet, 'false')
        assert_wallet_state(loaded=False, startup=False)
        runtime.rpc('loadwallet', wallet, 'true')
        assert_wallet_state(loaded=True, startup=True)
        runtime.rpc('unloadwallet', wallet, 'true')
        assert_wallet_state(loaded=False, startup=True)
        runtime.rpc('loadwallet', wallet, 'false')
        assert_wallet_state(loaded=True, startup=False)
        print('[PASS] GUI-equivalent wallet creation and load/unload startup transitions write RAM settings and retain the same Core process')
        password = 'Synthetic launcher fixture passphrase ' + uuid.uuid4().hex
        encrypted = subprocess.run(
            ['/usr/local/bin/bitcoin-cli', '-datadir=' + str(runtime.CORE),
             '-rpcport=8332', '-rpcwallet=' + wallet, '-stdin', 'encryptwallet'],
            input=password + '\n', text=True, capture_output=True, timeout=30)
        if encrypted.returncode:
            raise RuntimeError('Synthetic wallet encryption failed.')
        wallet_info = runtime.rpc('getwalletinfo', wallet=wallet)
        assert wallet_info['private_keys_enabled'] is True and wallet_info['unlocked_until'] == 0
        assert_wallet_state(loaded=True, startup=False)
        address = runtime.rpc('getnewaddress', 'synthetic-launcher-fixture', wallet=wallet)
        assert runtime.rpc('getaddressinfo', address, wallet=wallet)['ismine']
        raw = runtime.ROOT / 'export' / 'synthetic-wallet.dat'
        runtime.rpc('backupwallet', raw, wallet=wallet)
        assert raw.is_file() and raw.stat().st_size > 0
        runtime_backup = runtime.STATE / 'core-runtime' / 'synthetic-wallet.dat'
        runtime.rpc('backupwallet', runtime_backup, wallet=wallet)
        assert runtime_backup.is_file() and runtime_backup.stat().st_size > 0
        print('[PASS] Synthetic wallet creation, encryption and official native backup succeed in RAM')
        public = runtime.PRIVATE / 'synthetic-watch-only.dat'
        runtime.rpc('exportwatchonlywallet', public, wallet=wallet)
        assert public.is_file()
        runtime.rpc('restorewallet', 'public-copy', public)
        assert runtime.rpc('getwalletinfo', wallet='public-copy')['private_keys_enabled'] is False
        assert runtime.rpc('getaddressinfo', address, wallet='public-copy')['solvable']
        runtime.rpc('unloadwallet', 'public-copy')
        print('[PASS] Native watch-only export and restore work inside the real Core RAM confinement')

        for parent in (Path('/media/vault/synthetic-usb'),
                       Path('/mnt/synthetic-internal'), Path('/opt/synthetic-temp'),
                       Path('/dev/shm/synthetic-forbidden'), Path('/dev'), Path('/run/user/1000')):
            # The outer process can write these synthetic RAM fixtures; Core's
            # inner namespace must convert exactly these mounts to read-only.
            control = parent / 'outer-writable-marker'
            try:
                control.write_text('Synthetic fixture only')
                control.unlink()
            except PermissionError:
                if parent != Path('/dev'):
                    raise
                print('[INFO] Outer fixture device directory denies app writes before inner confinement')
            assert 'ro' in mount_flags(pid, str(parent)), 'Forbidden Core destination is writable'
            destination = parent / 'synthetic-wallet.dat'
            try:
                runtime.rpc('backupwallet', destination, wallet=wallet)
            except RuntimeError:
                pass
            else:
                raise AssertionError('Native Core backup escaped to a forbidden destination')
            assert not destination.exists(), 'Rejected native backup left a file'
            public_destination = parent / 'synthetic-watch-only.dat'
            try:
                runtime.rpc('exportwatchonlywallet', public_destination, wallet=wallet)
            except RuntimeError:
                pass
            else:
                raise AssertionError('Native watch-only export escaped the RAM policy')
            assert not public_destination.exists(), 'Rejected public export left a file'
            forbidden_wallet = parent / 'synthetic-wallet-path'
            try:
                runtime.rpc('createwallet', forbidden_wallet)
            except RuntimeError:
                pass
            else:
                raise AssertionError('Pathlike wallet creation escaped the RAM policy')
            assert not forbidden_wallet.exists(), 'Rejected wallet creation left a directory'
        device = Path('/dev').stat()
        print('[INFO] Outer fixture /dev uid=' + str(device.st_uid) + ' mode=' + oct(device.st_mode & 0o777)
              + '; live Core /dev mount is read-only')
        print('[PASS] Core rejects native backup and pathlike wallet creation on read-only media/internal/temp/device/shared-runtime fixtures')
        print('[INFO] RPC hides backup errno; live Core mount flags independently prove read-only destinations')

        duplicate = subprocess.run(['/usr/local/bin/core-vault-bitcoin'],
                                   stdout=output, stderr=output, timeout=10)
        assert duplicate.returncode == 0, 'Duplicate launcher did not return through the focus path'
        assert core_processes() == processes, 'Duplicate launch started another Core process'
        locked = subprocess.run(['/usr/bin/flock', '-n',
                                 '/run/user/1000/core-vault-bitcoin.lock', '/usr/bin/true'],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        assert locked.returncode == 1, 'Production bwrap supervisor lost the startup lock'
        print('[PASS] Duplicate startup follows focus branch; supervisor retains lock and one Core process')
        print('[INFO] Window activation itself is not certified without a desktop window manager')

        runtime.rpc('stop')
        assert launcher.wait(timeout=30) == 0
        assert not core_processes()
        unlocked = subprocess.run(['/usr/bin/flock', '-n',
                                   '/run/user/1000/core-vault-bitcoin.lock', '/usr/bin/true'])
        assert unlocked.returncode == 0, 'Launcher lock survived clean Core shutdown'
        print('[PASS] Clean Core shutdown releases the production launcher lock')
        print(json.dumps({'launcher_fixture_only': True,
                          'installed_storage_policy_certified': False,
                          'core_sha256': hashlib.file_digest(
                              Path('/usr/local/bin/bitcoin-qt').open('rb'), 'sha256').hexdigest(),
                          'launcher_sha256': hashlib.file_digest(
                              Path('/usr/local/bin/core-vault-bitcoin').open('rb'), 'sha256').hexdigest(),
                          'inner_helper_sha256': hashlib.file_digest(
                              Path('/usr/local/libexec/core-vault-core-session').open('rb'), 'sha256').hexdigest()}))
    finally:
        if launcher.poll() is None:
            try:
                runtime.rpc('stop')
                launcher.wait(timeout=15)
            except (RuntimeError, subprocess.SubprocessError):
                launcher.terminate()
                try:
                    launcher.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    launcher.kill()
                    launcher.wait(timeout=5)
        output.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--core-root', type=Path,
                        help='Existing read-only Debian build chroot containing official Core binaries')
    parser.add_argument('--real-observer', action='store_true',
                        help='Use current Hide observer instead of the inert fixture; no UI certification')
    parser.add_argument('--guest', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.guest:
        guest()
        return
    if args.core_root is None:
        parser.error('--core-root is required')
    for program in ('bwrap', 'xvfb-run', 'xdotool', 'findmnt', 'flock'):
        if shutil.which(program) is None:
            raise RuntimeError('Required Debian test dependency is missing: ' + program)
    project = Path(__file__).resolve().parents[2]
    inc = project / 'config/includes.chroot'
    core_root = args.core_root.resolve(strict=True)
    payload = {
        '/usr/local/bin/bitcoin-qt': core_root / 'usr/local/bin/bitcoin-qt',
        '/usr/local/bin/bitcoin-cli': core_root / 'usr/local/bin/bitcoin-cli',
        '/usr/local/bin/core-vault-bitcoin': inc / 'usr/local/bin/core-vault-bitcoin',
        '/usr/local/libexec/core-vault-core-session': inc / 'usr/local/libexec/core-vault-core-session',
    }
    for path in payload.values():
        if not path.is_file() or path.is_symlink() or not os.access(path, os.X_OK):
            raise RuntimeError('Required regular executable is unavailable: ' + str(path))
    print('[INFO] Fixture substitutes storage-check; installed noswap/UID layout and final ISO are not certified', flush=True)
    print('[INFO] Hide observer is ' + ('current source; behavior not certified' if args.real_observer
                                        else 'an inert fixture; behavior not tested'), flush=True)
    with tempfile.TemporaryDirectory(prefix='vault-launcher-fixture-code-', dir=project) as code_temporary, \
            tempfile.TemporaryDirectory(prefix='vault-launcher-fixture-', dir='/dev/shm') as temporary:
        ram = Path(temporary)
        code = Path(code_temporary)
        home = ram / 'home'
        runtime_dir = ram / 'runtime'
        for path in (home, runtime_dir, home / '.bitcoin', home / '.bitcoin/wallets',
                     home / 'Private Workspace', home / '.config', home / '.cache',
                     home / '.local', home / '.local/share', home / '.local/state',
                     ram / 'export', ram / 'tmp', ram / 'state', ram / 'state/core-runtime',
                     ram / 'media', ram / 'internal', ram / 'temp-fixture'):
            path.mkdir(mode=0o700, parents=True, exist_ok=True)
            path.chmod(0o700)
        fixture = code / 'storage-fixture.py'
        fixture.write_text(STORAGE_FIXTURE)
        fixture.chmod(0o755)
        token = uuid.uuid4().hex
        (ram / 'launcher-fixture-identity').write_text(token)
        observer = inc / 'usr/local/bin/core-vault-hide-sync'
        if not args.real_observer:
            observer = code / 'inert-observer.sh'
            observer.write_text('#!/bin/sh\n# TEST FIXTURE ONLY: no window input or screenshots.\nexit 0\n')
            observer.chmod(0o755)
        payload['/usr/local/bin/core-vault-storage-check'] = fixture
        payload['/usr/local/bin/core-vault-hide-sync'] = observer
        command = ['/usr/bin/bwrap', '--unshare-all', '--uid', '1000', '--gid', '1000',
                   '--die-with-parent', '--ro-bind', '/', '/', '--proc', '/proc', '--dev', '/dev',
                   '--tmpfs', '/home', '--tmpfs', '/root', '--tmpfs', '/run',
                   '--perms', '1777', '--tmpfs', '/tmp', '--perms', '1777', '--tmpfs', '/var/tmp',
                   '--tmpfs', '/opt', '--tmpfs', '/mnt', '--tmpfs', '/media', '--tmpfs', '/usr/local',
                   '--dir', '/usr/local/bin', '--dir', '/usr/local/libexec',
                   '--bind', str(ram), '/run/core-vault', '--bind', str(home), '/home/vault',
                   '--bind', str(runtime_dir), '/run/user/1000',
                   '--bind', str(ram / 'media'), '/media/vault/synthetic-usb',
                   '--bind', str(ram / 'internal'), '/mnt/synthetic-internal',
                   '--bind', str(ram / 'temp-fixture'), '/opt/synthetic-temp',
                   '--ro-bind', str(inc / 'usr/lib/core-vault'), '/opt/core-vault',
                   '--ro-bind', str(Path(__file__).resolve()), '/opt/test-core-launcher.py']
        for destination, source in payload.items():
            command.extend(['--ro-bind', str(source), destination])
        command.extend(['--clearenv', '--setenv', 'PATH', '/usr/bin:/bin',
                        '--setenv', 'HOME', '/home/vault', '--setenv', 'XDG_RUNTIME_DIR', '/run/user/1000',
                        '--setenv', 'TMPDIR', '/run/core-vault/tmp',
                        '--setenv', 'XDG_CONFIG_HOME', '/home/vault/.config',
                        '--setenv', 'XDG_CACHE_HOME', '/home/vault/.cache',
                        '--setenv', 'XDG_DATA_HOME', '/home/vault/.local/share',
                        '--setenv', 'XDG_STATE_HOME', '/home/vault/.local/state',
                        '--setenv', 'PYTHONDONTWRITEBYTECODE', '1',
                        '--setenv', 'CORE_VAULT_LAUNCHER_FIXTURE', token,
                        '--setenv', 'LC_ALL', 'C.UTF-8'])
        # A descendant mount must be refused even when this particular fixture
        # happens to be RAM. Otherwise recursive bind imports could expose
        # persistent GVFS/portal storage under a writable private directory.
        rejected = subprocess.run(command + ['--bind', str(ram / 'media'),
            '/run/core-vault/nested-media', '--chdir', '/run/core-vault',
            '/usr/local/bin/core-vault-bitcoin'], capture_output=True, text=True, timeout=15)
        if rejected.returncode == 0 or 'nested mount' not in rejected.stderr.lower():
            raise RuntimeError('Production launcher did not reject a nested writable-root mount: '
                               + rejected.stdout[-1000:] + rejected.stderr[-2000:])
        print('[PASS] Production launcher refuses a nested mount before starting Core', flush=True)
        command.extend(['--chdir', '/run/core-vault', '/usr/bin/xvfb-run', '-a',
                        '/usr/bin/python3', '/opt/test-core-launcher.py', '--guest'])
        subprocess.run(command, check=True, timeout=120)


if __name__ == '__main__':
    main()
