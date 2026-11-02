#!/usr/bin/python3
"""Real right-click wallet snapshot/GPG/TAR test, synthetic RAM wallets only.

Own unprivileged bubblewrap namespace and Xvfb. The entire host is read-only;
Core, plaintext snapshots, restored wallets and test archives are in RAM. The
storage-check function is explicitly replaced only because this application
fixture has a different mount layout. It does not certify ISO mount policy.
"""
import shutil
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid


def guest():
    sys.path.insert(0, '/opt/core-vault')
    sys.path.insert(1, '/opt/backup')
    import runtime
    import backup
    import export
    os.umask(0o077)
    for path in (runtime.CORE, runtime.WALLETS, runtime.ROOT / 'export', runtime.STATE):
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    runtime.check_storage = lambda: None  # Explicit fixture-only substitution.
    name = 'nested-' + uuid.uuid4().hex + '/wallet with spaces'
    marker = 'THUNAR_SYNTHETIC_' + uuid.uuid4().hex
    password = ['synthetic-archive-' + uuid.uuid4().hex, 'independent-' + uuid.uuid4().hex]
    flags = ['-datadir=' + str(runtime.CORE), '-walletdir=' + str(runtime.WALLETS),
             '-server=1', '-rpcport=8332', '-rpcbind=127.0.0.1', '-rpcallowip=127.0.0.1',
             '-connect=0', '-listen=0', '-listenonion=0', '-discover=0', '-dnsseed=0',
             '-fixedseeds=0', '-natpmp=0', '-maxconnections=0',
             '-settings=' + str(runtime.CORE / 'settings.json'), '-networkactive=0',
             '-prune=550', '-dbcache=32', '-maxmempool=5', '-splash=0']
    output = (runtime.ROOT / 'core-output.log').open('xb')
    core = subprocess.Popen(['/opt/bitcoin-qt', *flags], stdout=output, stderr=output)
    checks = []
    def passed(text):
        checks.append(text)
        print('[PASS] ' + text, flush=True)
    def archive(source, destination, *, receipt=False):
        with backup.consistent_inputs(backup.selected_paths(source), runtime) as prepared:
            result = backup.create_backup(prepared, destination, password, policy=runtime)
            if receipt:
                assert backup.record_wallet_export(source, prepared, result, password, runtime)
        assert list((runtime.ROOT / 'export').glob('thunar-wallet-*')) == []
        return result
    try:
        for attempt in range(120):
            assert core.poll() is None, 'Official Core exited during synthetic fixture'
            try:
                runtime.rpc('getnetworkinfo')
                break
            except RuntimeError:
                time.sleep(.25)
        else:
            raise RuntimeError('Official Core RPC did not become ready')
        runtime.rpc('createwallet', name)
        path = runtime.loaded_wallet_file(name)
        info = runtime.rpc('getwalletinfo', wallet=name)
        assert info['private_keys_enabled'] and 'unlocked_until' not in info
        address = runtime.rpc('getnewaddress', marker, wallet=name)
        try:
            runtime.wallet_digest(path)
        except sqlite3.OperationalError:
            passed('Live Core SQLite database is exclusively locked; raw read is unavailable')
        else:
            raise AssertionError('Fixture did not hold the expected live Core database lock')
        original = runtime.current_wallet_digest(name, path)
        direct = archive([path], runtime.ROOT / 'thunar-direct.gpg', receipt=True)
        record = runtime.read_receipts()[name]
        assert record['archive'] == str(direct)
        assert runtime.current_wallet_digest(name, path) == record['wallet_digest']
        assert export.verify_export(record, password) == '/run/core-vault'
        passed('Direct right-click wallet export records and re-verifies the same snapshot in RAM')
        real_rpc = runtime.rpc
        def unavailable(method, *args, **kwargs):
            if method == 'listwallets': raise RuntimeError('Synthetic unreachable RPC')
            return real_rpc(method, *args, **kwargs)
        runtime.rpc = unavailable
        try:
            started = time.monotonic()
            try:
                archive([path], runtime.ROOT / 'unreachable-live-must-not-exist.gpg')
            except sqlite3.OperationalError:
                assert time.monotonic() - started < 8
            else:
                raise AssertionError('Unreachable live Core wallet was copied without a consistent snapshot')
        finally:
            runtime.rpc = real_rpc
        assert not (runtime.ROOT / 'unreachable-live-must-not-exist.gpg').exists()
        passed('Official live Core exclusive lock refuses snapshot when its RPC is unreachable')
        (path.parent / 'notes.txt').write_text('synthetic companion text')
        destination = archive([path, path.parent / 'notes.txt'], runtime.ROOT / 'thunar-live.gpg')
        assert runtime.current_wallet_digest(name, path) == original
        assert runtime.rpc('listwallets') == [name]
        passed('Plain Core wallet right-click mixed selection uses a consistent RPC snapshot without modifying records or loaded state')
        from layered_backend import recover_payload, unpack, size_limit, Budget, MorePassphrases
        try:
            with recover_payload(destination, ['wrong synthetic passphrase'], ram_root=runtime.ROOT / 'export'):
                raise AssertionError('Wrong passphrase accepted')
        except MorePassphrases:
            passed('Wrong archive passphrase is rejected')
        restore = runtime.ROOT / 'export' / 'restore'
        with recover_payload(destination, password, ram_root=runtime.ROOT / 'export') as payload:
            unpack(payload, restore, limit=size_limit(runtime.ROOT / 'export'), budget=Budget())
        assert sorted(p.name for p in restore.iterdir()) == ['notes.txt', 'wallet.dat']
        assert runtime.wallet_digest(restore / 'wallet.dat') == original
        runtime.rpc('restorewallet', 'restored-synthetic', restore / 'wallet.dat')
        assert runtime.rpc('getaddressinfo', address, wallet='restored-synthetic')['ismine']
        assert address in runtime.rpc('getaddressesbylabel', marker, wallet='restored-synthetic')
        passed('Decrypted archive restores the labelled address in official Bitcoin Core')
        runtime.rpc('unloadwallet', 'restored-synthetic', 'false')
        runtime.rpc('unloadwallet', name, 'false')
        unloaded_before = runtime.wallet_digest(path)
        unloaded_bytes = path.read_bytes()
        archive([path.parent], runtime.ROOT / 'thunar-unloaded.gpg')
        assert runtime.rpc('listwallets') == []
        assert runtime.wallet_digest(path) == unloaded_before
        assert path.read_bytes() == unloaded_bytes
        passed('Unloaded wallet folder is backed up read-only without loading or changing source bytes')
        settings_before = (runtime.CORE / 'settings.json').read_bytes()
        runtime.rpc('stop')
        core.wait(timeout=30)
        source_before = path.read_bytes()
        archive([path], runtime.ROOT / 'thunar-closed.gpg')
        assert path.read_bytes() == source_before
        assert (runtime.CORE / 'settings.json').read_bytes() == settings_before
        assert runtime.wallet_digest(path) == unloaded_before
        passed('Closed Core read-only SQLite snapshot leaves wallet and settings bytes unchanged')
        # A lock outside the reachable Core RPC must cause a failure, never a
        # raw-file fallback. The normal SQLite connection timeout is bounded.
        connection = sqlite3.connect(path)
        try:
            connection.execute('BEGIN EXCLUSIVE')
            started = time.monotonic()
            try:
                archive([path], runtime.ROOT / 'must-not-exist.gpg')
            except sqlite3.OperationalError:
                assert time.monotonic() - started < 8
            else:
                raise AssertionError('Locked database was copied without a consistent snapshot')
        finally:
            connection.close()
        assert not (runtime.ROOT / 'must-not-exist.gpg').exists()
        assert list((runtime.ROOT / 'export').glob('thunar-wallet-*')) == []
        passed('Unreachable exclusive wallet lock fails safely and cleans RAM staging')
        print(json.dumps({'application_test_only': True, 'checks': checks,
                          'core_sha256': hashlib.file_digest(Path('/opt/bitcoin-qt').open('rb'), 'sha256').hexdigest()}))
    finally:
        if core.poll() is None:
            core.terminate()
            try: core.wait(timeout=15)
            except subprocess.TimeoutExpired:
                core.kill()
                core.wait(timeout=5)
        output.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--core-root', type=Path)
    parser.add_argument('--backup-source', type=Path)
    parser.add_argument('--runtime-source', type=Path)
    parser.add_argument('--guest', action='store_true')
    args = parser.parse_args()
    if args.guest:
        guest()
        return
    if not args.core_root:
        parser.error('--core-root must identify an existing read-only build chroot')
    project = Path(__file__).resolve().parents[2]
    core_root = args.core_root.resolve(strict=True)
    backup_source = (args.backup_source or project / 'tools/core-vault/backup-src/src').resolve(strict=True)
    runtime_source = (args.runtime_source or project / 'config/includes.chroot/usr/lib/core-vault').resolve(strict=True)
    qt = core_root / 'usr/local/bin/bitcoin-qt'
    cli = core_root / 'usr/local/bin/bitcoin-cli'
    for path in (qt, cli):
        if not path.is_file() or path.is_symlink():
            raise RuntimeError('Official Core binaries must be regular files')
    with tempfile.TemporaryDirectory(prefix='.stock-gpg-fixture-', dir=project) as engine_dir, tempfile.TemporaryDirectory(prefix='vault-thunar-test-', dir='/dev/shm') as tmp:
        engine = Path(engine_dir) / 'gpg'
        shutil.copyfile('/usr/bin/gpg', engine)
        engine.chmod(0o755)
        assert engine.read_bytes() == Path('/usr/bin/gpg').read_bytes()
        ram = Path(tmp)
        (ram / 'home').mkdir(mode=0o700)
        command = ['bwrap', '--unshare-all', '--die-with-parent', '--ro-bind', '/', '/',
                   '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp',
                   '--tmpfs', '/var/tmp', '--tmpfs', '/run', '--tmpfs', '/home',
                   '--tmpfs', '/opt', '--tmpfs', '/usr/local',
                   '--bind', str(ram), '/run/core-vault',
                   '--bind', str(ram / 'home'), '/home/vault',
                   '--bind', str(ram / 'home'), str(Path.home()),
                   '--ro-bind', str(runtime_source), '/opt/core-vault',
                   '--ro-bind', str(backup_source), '/opt/backup',
                   '--ro-bind', str(qt), '/opt/bitcoin-qt',
                   '--ro-bind', str(engine), '/usr/bin/gpg',
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
        subprocess.run(command, check=True, timeout=180)


if __name__ == '__main__':
    main()
