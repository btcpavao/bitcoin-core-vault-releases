#!/usr/bin/python3
"""Real Core/GPG/TAR interoperability test in a read-only bubblewrap sandbox.

Synthetic wallets only. Writable paths are /dev/shm-backed or namespace tmpfs.
This does not certify installed mount/swap policy or replace ISO acceptance.
The archive destination is actual tmpfs and needs no removable-media override.
"""
import argparse
from contextlib import ExitStack
import stat
import hashlib
import json
import os
import signal
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid


def fixture_stock_gpg(destination):
    """Copy the root-owned stock engine without changing production trust rules.

    Host root is unmapped in an unprivileged user namespace. A current-user
    owned byte-identical copy maps correctly while preserving strict backend
    ownership checks. Keep the public binary copy outside the writable session
    bind and refuse a noexec destination; never relax an existing mount policy.
    """
    source = Path('/usr/bin/gpg')
    descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    created = False
    def identity(info):
        return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
                info.st_ctime_ns, info.st_uid, info.st_mode)
    try:
        with os.fdopen(descriptor, 'rb') as original:
            descriptor = None
            before = os.fstat(original.fileno())
            if (not stat.S_ISREG(before.st_mode) or before.st_uid != 0 or
                    before.st_mode & 0o022 or not os.access(source, os.X_OK)):
                raise RuntimeError('The fixture requires the regular root-owned stock /usr/bin/gpg executable.')
            expected = hashlib.file_digest(original, 'sha256').hexdigest()
            original.seek(0)
            with destination.open('xb') as copy:
                created = True
                while block := original.read(1024 * 1024):
                    copy.write(block)
                copy.flush()
                os.fchmod(copy.fileno(), 0o555)
                os.fsync(copy.fileno())
            with destination.open('rb') as copy:
                actual = hashlib.file_digest(copy, 'sha256').hexdigest()
            if (actual != expected or identity(os.fstat(original.fileno())) != identity(before)
                    or identity(source.lstat()) != identity(before)):
                raise RuntimeError('The stock GPG executable changed during fixture attestation.')
            info = destination.lstat()
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or
                    stat.S_IMODE(info.st_mode) != 0o555 or info.st_size != before.st_size):
                raise RuntimeError('The fixture GPG copy has unexpected ownership or permissions.')
            if not os.access(destination, os.X_OK):
                raise RuntimeError('The public GPG fixture copy cannot execute in host /tmp (possibly noexec). No mount policy was changed.')
            return expected
    except BaseException:
        if created:
            destination.unlink(missing_ok=True)
        raise
    finally:
        if descriptor is not None:
            os.close(descriptor)

def guest(regtest=False):
    backup_format='gpg'
    sys.path.insert(0, '/opt/core-vault')
    sys.path.insert(1, '/opt/backup')
    import runtime
    import export
    import gpg_backend
    os.umask(0o077)
    # Only this unprivileged fixture substitutes storage attestation: all
    # private paths are synthetic /dev/shm binds rather than installed mounts.
    runtime.check_storage = lambda: None
    for path in (runtime.CORE, runtime.WALLETS, runtime.ROOT / 'export', runtime.STATE):
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if regtest:
        (runtime.CORE / 'bitcoin.conf').write_text('chain=regtest\n')
    marker = 'CORE_VAULT_FORENSIC_TEST_' + uuid.uuid4().hex
    name = 'synthetic-' + uuid.uuid4().hex
    wallet_password = 'synthetic-wallet-' + uuid.uuid4().hex
    archive_password = ['synthetic-archive-' + uuid.uuid4().hex, 'synthetic-independent-' + uuid.uuid4().hex]
    def archive_path(stem):
        return runtime.ROOT / (stem + '.' + backup_format)
    def export_wallet(wallet, destination, password):
        return export.export_wallet(wallet, destination, password)
    def recover(archive, destination, password):
        from layered_backend import recover_payload, unpack, size_limit, Budget
        destination.rmdir()  # This fixture pre-creates an empty output directory.
        with recover_payload(archive, password, ram_root=runtime.ROOT / 'export') as payload:
            unpack(payload, destination, limit=size_limit(runtime.ROOT / 'export'), budget=Budget())
    flags = ['-datadir=' + str(runtime.CORE), '-walletdir=' + str(runtime.WALLETS),
             '-server=1', '-rpcport=8332', '-rpcbind=127.0.0.1', '-rpcallowip=127.0.0.1',
             '-connect=0', '-listen=0', '-listenonion=0', '-discover=0', '-dnsseed=0',
             '-fixedseeds=0', '-natpmp=0', '-maxconnections=0', '-nosettings', '-networkactive=0', '-prune=550',
             '-dbcache=32', '-maxmempool=5', '-splash=0']
    output = (runtime.ROOT / 'core-test-output.log').open('xb')
    core = subprocess.Popen(['/opt/bitcoin-qt', *flags], stdout=output, stderr=output)
    try:
        for attempt in range(120):
            if core.poll() is not None:
                # This is before RPC is ready or any synthetic wallet exists.
                # Expose only initial loader/platform diagnostics, not later
                # wallet, signing or passphrase operation output.
                output.flush()
                print((runtime.ROOT / 'core-test-output.log').read_text()[-5000:])
                for log in (runtime.CORE / 'debug.log', runtime.CORE / 'regtest/debug.log'):
                    if log.exists():
                        print(log.read_text()[-5000:])
                # Reproduce only the failed startup: no wallet has ever been
                # created and no wallet/export passphrase is given to gdb.
                if os.access('/usr/bin/gdb', os.X_OK):
                    diagnostic = subprocess.Popen([
                        '/usr/bin/gdb', '-nh', '-nx', '--batch',
                        '-ex', 'set auto-load off', '-ex', 'run', '-ex', 'bt',
                        '--args', '/opt/bitcoin-qt', *flags],
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        text=True, start_new_session=True)
                    try:
                        trace, _ = diagnostic.communicate(timeout=20)
                        print(trace[-8000:])
                    except subprocess.TimeoutExpired:
                        os.killpg(diagnostic.pid, signal.SIGKILL)
                        trace, _ = diagnostic.communicate(timeout=5)
                        print(trace[-8000:])
                raise RuntimeError('Core exited before synthetic wallet creation (exit ' + str(core.returncode) + ').')
            try:
                runtime.rpc('getnetworkinfo')
                break
            except RuntimeError:
                time.sleep(.25)
        else:
            output.flush()
            print((runtime.ROOT / 'core-test-output.log').read_text()[-5000:])
            if (runtime.CORE / 'debug.log').exists():
                print((runtime.CORE / 'debug.log').read_text()[-5000:])
            raise RuntimeError('Core RPC did not become ready.')
        runtime.rpc('createwallet', name)
        path = runtime.wallet_files()[name]
        before = runtime.current_wallet_digest(name, path)
        # Archive encryption is independent of Core's private-key encryption.
        # Exercise the exact live SQLite export before encryptwallet is called.
        assert 'unlocked_until' not in runtime.rpc('getwalletinfo', wallet=name)
        plain_address = runtime.rpc('getnewaddress', marker + '-plain', wallet=name)
        plain_archive = export_wallet(name, archive_path('plain-wallet'), archive_password)
        plain_record = runtime.read_receipts()[name]
        assert export.verify_export(plain_record, archive_password) == '/run/core-vault'
        plain_recovery = runtime.ROOT / 'export' / 'plain-restore'
        plain_recovery.mkdir()
        recover(plain_archive, plain_recovery, archive_password)
        plain_restored = name + '-plain-restored'
        runtime.rpc('restorewallet', plain_restored, plain_recovery / 'wallet.dat')
        assert runtime.rpc('getaddressinfo', plain_address, wallet=plain_restored)['ismine']
        assert 'unlocked_until' not in runtime.rpc('getwalletinfo', wallet=plain_restored)
        runtime.rpc('unloadwallet', plain_restored, 'false')
        print('[PASS] Unencrypted Core wallet -> encrypted ' + backup_format + ' -> restored labelled wallet')
        runtime.rpc('unloadwallet', name, 'false')
        export_wallet(name, archive_path('plain-unloaded'), archive_password)
        assert name not in runtime.rpc('listwallets'), 'Backup must not load an unloaded wallet'
        assert export.verify_export(runtime.read_receipts()[name], archive_password)
        runtime.rpc('loadwallet', name, 'false')
        print('[PASS] Unloaded unencrypted wallet exports without load/unload side effects')
        # The synthetic wallet passphrase is sent on stdin, never in argv.
        command = ['/usr/local/bin/bitcoin-cli', '-datadir=' + str(runtime.CORE),
                   '-rpcport=8332', '-rpcwallet=' + name, '-stdin', 'encryptwallet']
        result = subprocess.run(command, input=wallet_password + '\n', text=True,
                                capture_output=True, timeout=30)
        if result.returncode:
            raise RuntimeError('Official Core wallet encryption failed.')
        address = runtime.rpc('getnewaddress', marker, wallet=name)
        if regtest:
            runtime.rpc('generatetoaddress', '101', address)
            unlock = ['/usr/local/bin/bitcoin-cli', '-datadir=' + str(runtime.CORE),
                      '-rpcport=8332', '-rpcwallet=' + name, '-stdin', 'walletpassphrase']
            result = subprocess.run(unlock, input=wallet_password + '\n60\n',
                                    text=True, capture_output=True, timeout=30)
            assert result.returncode == 0
            recipient = runtime.rpc('getnewaddress', wallet=name)
            funded = runtime.rpc('walletcreatefundedpsbt', '[]', json.dumps([{recipient: 1}]), '0', json.dumps({'fee_rate': 2}), wallet=name)
            signed = runtime.rpc('walletprocesspsbt', funded['psbt'], wallet=name)
            final = runtime.rpc('finalizepsbt', signed['psbt'])
            assert signed['complete'] and final['complete']
            accepted = runtime.rpc('testmempoolaccept', json.dumps([final['hex']]))
            assert accepted[0]['allowed'], 'Signed synthetic regtest transaction rejected'
            runtime.rpc('walletlock', wallet=name)
            print('[PASS] Synthetic regtest funding and PSBT signing validated by Core')
        after = runtime.current_wallet_digest(name, path)
        assert before != after, 'Wallet mutation must change logical digest'
        destination = archive_path('synthetic-backup')
        archive = export_wallet(name, destination, archive_password)
        record = runtime.read_receipts()[name]
        assert runtime.current_wallet_digest(name, path) == record['wallet_digest']
        assert export.verify_export(record, archive_password) == '/run/core-vault'
        # Core supports wallet paths outside -walletdir. They must remain in
        # the inventory even after unloading and retain their RPC alias while
        # loaded so export never tries to load the same exclusive SQLite DB twice.
        relative = str(runtime.WALLETS.parent / ('outside-' + uuid.uuid4().hex))
        runtime.rpc('createwallet', relative)
        encrypt = ['/usr/local/bin/bitcoin-cli', '-datadir=' + str(runtime.CORE),
                   '-rpcport=8332', '-rpcwallet=' + relative, '-stdin', 'encryptwallet']
        result = subprocess.run(encrypt, input=wallet_password + '\n', text=True,
                                capture_output=True, timeout=30)
        assert result.returncode == 0
        outside_path = runtime.WALLETS.parent / Path(relative).name / 'wallet.dat'
        outside_name = str(outside_path.parent)
        assert runtime.wallet_files()[outside_name] == outside_path
        runtime.check_loaded_wallet_coverage(runtime.wallet_files())
        outside_archive = archive_path('outside-wallet')
        export_wallet(outside_name, outside_archive, archive_password)
        outside_record = runtime.read_receipts()[outside_name]
        assert runtime.current_wallet_digest(outside_name, outside_path) == outside_record['wallet_digest']
        runtime.rpc('unloadwallet', relative, 'false')
        assert runtime.wallet_files()[outside_name] == outside_path
        assert export.verify_export(outside_record, archive_password) == '/run/core-vault'
        print('[PASS] Absolute-path wallet is inventoried and exported while loaded and unloaded')
        try:
            export.verify_export(record, ['deliberately-wrong-test-passphrase'])
        except Exception:
            pass
        else:
            raise AssertionError('Wrong archive passphrase was accepted')
        # Restore the decrypted exported archive, rather than a second unrelated
        # backup, and prove the recovered wallet knows the labelled address.
        raw = runtime.ROOT / 'export' / 'restore-wallet.dat'
        restore_dir = runtime.ROOT / 'export' / 'restore'
        restore_dir.mkdir()
        recover(archive, restore_dir, archive_password)
        (restore_dir / 'wallet.dat').rename(raw)
        restored = name + '-restored'
        runtime.rpc('restorewallet', restored, raw)
        assert runtime.rpc('getaddressinfo', address, wallet=restored)['ismine']
        labels = runtime.rpc('getaddressesbylabel', marker, wallet=restored)
        assert address in labels
        if regtest:
            unlock = ['/usr/local/bin/bitcoin-cli', '-datadir=' + str(runtime.CORE),
                      '-rpcport=8332', '-rpcwallet=' + restored, '-stdin', 'walletpassphrase']
            result = subprocess.run(unlock, input=wallet_password + '\n60\n',
                                    text=True, capture_output=True, timeout=30)
            assert result.returncode == 0
            recovered_signed = runtime.rpc('walletprocesspsbt', funded['psbt'], wallet=restored)
            recovered_final = runtime.rpc('finalizepsbt', recovered_signed['psbt'])
            assert recovered_signed['complete'] and recovered_final['complete']
            accepted = runtime.rpc('testmempoolaccept', json.dumps([recovered_final['hex']]))
            assert accepted[0]['allowed'], 'PSBT signed by recovered wallet was rejected'
            runtime.rpc('walletlock', wallet=restored)
            print('[PASS] Recovered encrypted wallet signs a funded PSBT accepted by Core')
        print('[PASS] Official Core creates and encrypts a descriptor/SQLite wallet')
        print('[PASS] Official backupwallet -> ' + backup_format + ' -> verified wallet read-back')
        print('[PASS] Wrong archive passphrase rejected')
        print('[PASS] Official restorewallet recovers the labelled address')
        closed_name = 'closed-plain-' + uuid.uuid4().hex
        runtime.rpc('createwallet', closed_name)
        closed_address = runtime.rpc('getnewaddress', marker + '-closed', wallet=closed_name)
        closed_path = runtime.wallet_files()[closed_name]
        assert 'unlocked_until' not in runtime.rpc('getwalletinfo', wallet=closed_name)
        runtime.rpc('stop')
        core.wait(timeout=30)
        assert runtime.wallet_digest(path) == record['wallet_digest'], 'Core final flush changed the exported wallet'
        print('[PASS] Export digest remains valid after clean Core shutdown')
        closed_archive = export_wallet(closed_name, archive_path('plain-closed'), archive_password)
        closed_record = runtime.read_receipts()[closed_name]
        assert export.verify_export(closed_record, archive_password)
        assert runtime.wallet_digest(closed_path) == closed_record['wallet_digest']
        recovery = runtime.ROOT / 'export' / 'closed-restore'
        recovery.mkdir()
        recover(closed_archive, recovery, archive_password)
        core = subprocess.Popen(['/opt/bitcoin-qt', *flags], stdout=output, stderr=output)
        for attempt in range(120):
            try:
                runtime.rpc('getnetworkinfo')
                break
            except RuntimeError:
                time.sleep(.25)
        else:
            raise RuntimeError('Core RPC did not restart for closed-wallet recovery.')
        recovered_name = closed_name + '-restored'
        runtime.rpc('restorewallet', recovered_name, recovery / 'wallet.dat')
        assert runtime.rpc('getaddressinfo', closed_address, wallet=recovered_name)['ismine']
        assert 'unlocked_until' not in runtime.rpc('getwalletinfo', wallet=recovered_name)
        runtime.rpc('stop')
        core.wait(timeout=30)
        print('[PASS] Closed Core unencrypted wallet -> encrypted ' + backup_format + ' -> restored labelled wallet')
        print(json.dumps({'application_test_only': True,
                          'backup_format': backup_format,
                          'core_sha256': hashlib.file_digest(Path('/opt/bitcoin-qt').open('rb'), 'sha256').hexdigest(),
                          'wallet_digest': record['wallet_digest'], 'archive_sha256': record['archive_sha256']}))
    finally:
        if core.poll() is None:
            core.terminate()
            try:
                core.wait(timeout=15)
            except subprocess.TimeoutExpired:
                core.kill()
                core.wait(timeout=5)
        output.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--core-root', type=Path)
    parser.add_argument('--guest', action='store_true')
    parser.add_argument('--regtest', action='store_true')
    args = parser.parse_args()
    if args.guest:
        guest(args.regtest)
        return
    if not args.core_root:
        parser.error('--core-root must identify the existing read-only build chroot')
    project = Path(__file__).resolve().parents[2]
    core_root = args.core_root.resolve(strict=True)
    qt = core_root / 'usr/local/bin/bitcoin-qt'
    cli = core_root / 'usr/local/bin/bitcoin-cli'
    for path in (qt, cli):
        if not path.is_file() or path.is_symlink():
            raise RuntimeError('Official Core binaries must be regular files.')
    # The host root is read-only. HOME found via either environment or passwd,
    # temporary directories and /run are all replaced inside the namespace.
    with ExitStack() as resources:
        tmp = resources.enter_context(tempfile.TemporaryDirectory(
            prefix='vault-core-application-', dir='/dev/shm'))
        sandbox = Path(tmp)
        ram = sandbox / 'session'
        ram.mkdir(mode=0o700)
        (ram / 'home').mkdir(mode=0o700)
        trusted_gpg = None
        if os.geteuid() != 0:
            # Public engine bytes only: never stage wallets, passwords, GPG HOME
            # or temporary plaintext here. /dev/shm can correctly be noexec.
            binaries = Path(resources.enter_context(tempfile.TemporaryDirectory(
                prefix='vault-public-gpg-fixture-', dir='/tmp')))
            trusted_gpg = binaries / 'stock-gpg'
            stock_hash = fixture_stock_gpg(trusted_gpg)
            print(json.dumps({'application_test_only': True,
                              'fixture_gpg_ownership_adaptation': True,
                              'public_binary_copy_only': True,
                              'stock_gpg_sha256': stock_hash}), flush=True)
        else:
            # A root host's user namespace already maps the stock owner: keep
            # the actual unmodified /usr/bin/gpg supplied by its Debian image.
            print(json.dumps({'application_test_only': True,
                              'fixture_gpg_ownership_adaptation': False}), flush=True)
        command = ['bwrap', '--unshare-all', '--die-with-parent', '--ro-bind', '/', '/',
                   '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp',
                   '--tmpfs', '/var/tmp', '--tmpfs', '/run', '--tmpfs', '/home',
                   '--tmpfs', '/opt', '--tmpfs', '/usr/local',
                   '--bind', str(ram), '/run/core-vault',
                   '--bind', str(ram / 'home'), '/home/vault',
                   '--bind', str(ram / 'home'), str(Path.home()),
                   '--ro-bind', str(project / 'config/includes.chroot/usr/lib/core-vault'), '/opt/core-vault',
                   '--ro-bind', str(project / 'tools/core-vault/backup-src/src'), '/opt/backup',
                   '--ro-bind', str(qt), '/opt/bitcoin-qt',
                   *(['--ro-bind', str(trusted_gpg), '/usr/bin/gpg'] if trusted_gpg is not None else []),
                   '--ro-bind', str(cli), '/usr/local/bin/bitcoin-cli',
                   '--ro-bind', str(Path(__file__).resolve()), '/opt/workflow.py',
                   '--setenv', 'HOME', '/home/vault', '--setenv', 'TMPDIR', '/tmp',
                   '--setenv', 'XDG_CONFIG_HOME', '/home/vault/.config',
                   '--setenv', 'XDG_CACHE_HOME', '/home/vault/.cache',
                   '--setenv', 'XDG_DATA_HOME', '/home/vault/.local/share',
                   '--setenv', 'XDG_STATE_HOME', '/home/vault/.local/state',
                   '--setenv', 'PYTHONDONTWRITEBYTECODE', '1',
                   '--chdir', '/run/core-vault', '/usr/bin/xvfb-run', '-a',
                   '/usr/bin/python3', '/opt/workflow.py', '--guest']
        if args.regtest:
            command.append('--regtest')
        subprocess.run(command, check=True, timeout=300)


if __name__ == '__main__':
    main()
