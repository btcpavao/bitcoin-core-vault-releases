#!/usr/bin/python3
"""Synthetic secrets only. Negative policy tests plus real GPG/TAR verification."""
from pathlib import Path
import importlib.util
import ast
import json
import os
import stat
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock
from types import SimpleNamespace
from contextlib import contextmanager

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / 'config/includes.chroot/usr/lib/core-vault'))
sys.path.insert(0, str(PROJECT / 'tools/core-vault/backup-src/src'))
import runtime
import export
import backup

@contextmanager
def connection(path):
    db = sqlite3.connect(path)
    try:
        with db:
            yield db
    finally:
        db.close()

def database(path, data=b'CORE_VAULT_FORENSIC_TEST_SYNTHETIC_ONLY'):
    with connection(path) as db:
        db.execute('CREATE TABLE main(key BLOB PRIMARY KEY, value BLOB)')
        db.execute('INSERT INTO main VALUES(?,?)', (b'fake-test-record', data))

class PrivateSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='vault-tests-', dir='/dev/shm')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_logical_wallet_digest_survives_checkpoint(self):
        path = self.root / 'wallet.dat'
        database(path)
        before = runtime.wallet_digest(path)
        with connection(path) as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        self.assertEqual(before, runtime.wallet_digest(path))
        with connection(path) as db:
            db.execute('UPDATE main SET value=?', (b'new-sensitive-state',))
        self.assertNotEqual(before, runtime.wallet_digest(path))

    def test_unsupported_database_is_not_accepted(self):
        path = self.root / 'wallet.dat'
        with connection(path) as db:
            db.execute('CREATE TABLE unexpected(data TEXT)')
        with self.assertRaises(RuntimeError):
            runtime.wallet_digest(path)

    def test_wallet_inventory_rejects_symlink(self):
        walletdir = self.root / 'wallets'
        walletdir.mkdir()
        (walletdir / 'unexpected').symlink_to('/tmp')
        with patch.object(runtime, 'WALLETS', walletdir):
            with self.assertRaises(RuntimeError):
                runtime.wallet_files()

    def test_wallet_inventory_includes_absolute_and_parent_paths(self):
        home = self.root / 'home'
        wallets = home / '.bitcoin' / 'wallets'
        normal = wallets / 'normal' / 'wallet.dat'
        outside = home / '.bitcoin' / 'outside' / 'wallet.dat'
        private = home / 'Private Workspace' / 'imported' / 'wallet.dat'
        staged = self.root / 'export' / 'temporary' / 'wallet.dat'
        for path in (normal, outside, private, staged):
            path.parent.mkdir(parents=True, exist_ok=True)
            database(path)
        with patch.multiple(runtime, ROOT=self.root, HOME=home, WALLETS=wallets, EXTRA_WALLET_ROOTS=()):
            inventory = runtime.wallet_files()
            self.assertEqual(inventory, {'normal': normal, str(outside.parent): outside,
                                        str(private.parent): private, str(staged.parent): staged})
            self.assertEqual(runtime.loaded_wallet_name(str(outside.parent), ['../outside']), '../outside')
            with patch.object(runtime, 'rpc', return_value=['normal', '../outside', str(private.parent)]):
                runtime.check_loaded_wallet_coverage(inventory)
            with patch.object(runtime, 'rpc', return_value=['/tmp/uninventoried-wallet']):
                with self.assertRaisesRegex(RuntimeError, 'outside the supported'):
                    runtime.check_loaded_wallet_coverage(inventory)

    def test_unloaded_wallet_in_system_ram_scratch_is_inventoried(self):
        extra = self.root / 'scratch'
        path = extra / 'outside' / 'wallet.dat'
        path.parent.mkdir(parents=True)
        database(path)
        with patch.multiple(runtime, ROOT=self.root / 'absent', HOME=self.root / 'no-home',
                            WALLETS=self.root / 'no-wallets', EXTRA_WALLET_ROOTS=(extra,)):
            self.assertEqual(runtime.wallet_files(), {str(path.parent): path})

    def test_shared_systemd_inaccessible_directory_is_outside_wallet_inventory(self):
        self.assertEqual(runtime.EXTRA_WALLET_ROOTS, (Path('/tmp'), Path('/var/tmp')))
        shared = self.root / 'shared-runtime' / 'systemd' / 'inaccessible' / 'dir'
        shared.mkdir(mode=0o700, parents=True)
        shared.chmod(0)
        self.addCleanup(shared.chmod, 0o700)
        home, private, wallets = self.root / 'home', self.root / 'private', self.root / 'home/.bitcoin/wallets'
        scratch = (self.root / 'tmp', self.root / 'var-tmp')
        for path in (home, private, wallets, *scratch):
            path.mkdir(mode=0o700, parents=True, exist_ok=True)
        scanned = []
        scandir = os.scandir
        def observe(path):
            scanned.append(Path(path))
            if Path(path) == shared:
                raise PermissionError(13, 'Synthetic systemd inaccessible placeholder', str(shared))
            return scandir(path)
        with patch.multiple(runtime, ROOT=private, HOME=home, WALLETS=wallets,
                            EXTRA_WALLET_ROOTS=scratch), \
                patch.object(runtime.os, 'scandir', side_effect=observe):
            self.assertEqual(runtime.wallet_files(), {})
        self.assertNotIn(shared, scanned)
        self.assertTrue({home, private, wallets, *scratch}.issubset(scanned))

    def test_unknown_owned_unreadable_ram_directory_still_blocks_inventory(self):
        blind = self.root / 'scratch' / 'unknown-unreadable'
        blind.mkdir(mode=0o700, parents=True)
        database(blind / 'wallet.dat')
        scandir = os.scandir
        def deny(path):
            if Path(path) == blind:
                raise PermissionError(13, 'Synthetic own-UID unreadable directory', str(blind))
            return scandir(path)
        with patch.multiple(runtime, ROOT=self.root / 'private', HOME=self.root / 'home',
                            WALLETS=self.root / 'wallets', EXTRA_WALLET_ROOTS=(blind.parent,)), \
                patch.object(runtime.os, 'scandir', side_effect=deny):
            with self.assertRaisesRegex(RuntimeError, 'could not be inventoried'):
                runtime.wallet_files()

    def test_wallet_inventory_unifies_bind_aliases(self):
        with patch.multiple(runtime, ROOT=self.root, HOME=Path('/home/vault')):
            path = self.root / 'home' / '.bitcoin' / 'wallets' / 'a' / 'wallet.dat'
            self.assertEqual(runtime.canonical_wallet_path(path), Path('/home/vault/.bitcoin/wallets/a/wallet.dat'))

    def test_disk_home_and_missing_noswap_are_rejected(self):
        ram = {'target':'/run/core-vault', 'fstype':'tmpfs', 'options':'noswap,nodev,nosuid,noexec', 'maj:min':'0:123', 'fsroot':'/'}
        disk = dict(ram, target='/home/vault', fstype='ext4', fsroot='/home')
        with patch.object(runtime.Path, 'read_text', return_value='Filename Type Size Used Priority\n'), patch.object(runtime, 'mount_at', side_effect=[ram, disk]):
            with self.assertRaisesRegex(RuntimeError, 'account HOME'):
                runtime.check_storage()
        with patch.object(runtime.Path, 'read_text', return_value='Filename Type Size Used Priority\n'), patch.object(runtime, 'mount_at', side_effect=[dict(ram, options='nodev,nosuid,noexec'),disk]):
            with self.assertRaisesRegex(RuntimeError, 'mount protection'):
                runtime.check_storage()

    def test_active_disk_swap_is_rejected_before_private_paths(self):
        with patch.object(runtime.Path, 'read_text', return_value='Filename Type Size Used Priority\n/swapfile file 1024 1 -2\n'):
            with self.assertRaisesRegex(RuntimeError, 'Swap is active'):
                runtime.check_storage()

    def test_xdg_parent_and_private_core_runtime_permissions_are_validated(self):
        ram = {'target':str(runtime.ROOT), 'fstype':'tmpfs',
               'options':'noswap,nosuid,nodev,noexec', 'maj:min':'0:123', 'fsroot':'/'}
        home = dict(ram, target=str(runtime.HOME), fsroot='/home')
        def mount(path, exact=False):
            return home if path == runtime.HOME else ram
        safe = SimpleNamespace(st_mode=stat.S_IFDIR | 0o700, st_uid=1000, st_gid=1000)
        for bad_path in (runtime.HOME / '.local', runtime.STATE / 'core-runtime'):
            with self.subTest(path=bad_path):
                def metadata(path):
                    return SimpleNamespace(st_mode=stat.S_IFDIR | 0o700, st_uid=0, st_gid=0) if path == bad_path else safe
                with patch.object(runtime.Path, 'read_text', return_value='Filename Type Size Used Priority\n'), \
                        patch.object(runtime, 'mount_at', side_effect=mount), \
                        patch.object(runtime.Path, 'lstat', autospec=True, side_effect=metadata):
                    with self.assertRaisesRegex(RuntimeError, 'ownership or permissions'):
                        runtime.check_storage()
        with patch.object(runtime.Path, 'read_text', return_value='Filename Type Size Used Priority\n'), \
                patch.object(runtime, 'mount_at', side_effect=mount), \
                patch.object(runtime.Path, 'lstat', return_value=safe):
            runtime.check_storage()

    def test_core_mount_topology_allows_roots_and_unrelated_media(self):
        targets = ['/', str(runtime.ROOT), str(runtime.HOME),
                   *map(str, runtime.EXTRA_WALLET_ROOTS), '/media/vault/USB',
                   '/tmp-other', '/run/core-vault-other']
        result = SimpleNamespace(stdout=json.dumps({'filesystems':
                                 [{'target': target} for target in targets]}))
        with patch.object(runtime.subprocess, 'run', return_value=result) as command:
            runtime.check_core_mounts()
        command.assert_called_once_with(
            ['/usr/bin/findmnt', '--uniq', '--list', '-J', '-o', 'TARGET,ID'],
            capture_output=True, text=True, timeout=5, check=True)

    def test_core_mount_topology_rejects_every_nested_filesystem(self):
        for root in (runtime.ROOT, runtime.HOME, *runtime.EXTRA_WALLET_ROOTS):
            for kind in ('fuse.gvfsd-fuse', 'tmpfs'):
                with self.subTest(root=root, kind=kind):
                    result = SimpleNamespace(stdout=json.dumps({'filesystems':[
                        {'target': str(root)},
                        {'target': str(root / 'nested-storage'), 'fstype': kind, 'id': 17}]}))
                    with patch.object(runtime.subprocess, 'run', return_value=result), \
                            patch.object(runtime, '_visible_mount_id', return_value=17):
                        with self.assertRaisesRegex(RuntimeError, 'nested mount'):
                            runtime.check_core_mounts()

    def test_core_mount_topology_ignores_hidden_descendant_records(self):
        result = SimpleNamespace(stdout=json.dumps({'filesystems':[
            {'target': str(runtime.ROOT), 'id': 19},
            {'target': str(runtime.STATE / 'core-runtime' / 'hidden'), 'id': 17}]}))
        # The inherited portal target may be absent from the new RAM overlay,
        # or an ordinary directory can exist there on the overlay's mount.
        for visible in (None, 19):
            with self.subTest(visible=visible):
                with patch.object(runtime.subprocess, 'run', return_value=result), \
                        patch.object(runtime, '_visible_mount_id', return_value=visible):
                    runtime.check_core_mounts()

    def test_core_mount_identity_uses_kernel_fdinfo_and_closes_descriptor(self):
        target = Path('/run/user/1000/doc')
        with patch.object(runtime.os, 'open', return_value=42) as opened, \
                patch.object(runtime.Path, 'read_text', return_value='pos:\t0\nflags:\t012000000\nmnt_id:\t17\nino:\t1\n'), \
                patch.object(runtime.os, 'close') as closed:
            self.assertEqual(runtime._visible_mount_id(target), 17)
        opened.assert_called_once_with(target, os.O_PATH | os.O_CLOEXEC)
        closed.assert_called_once_with(42)

    def test_core_mount_topology_fails_without_kernel_mount_identity(self):
        result = SimpleNamespace(stdout=json.dumps({'filesystems':[
            {'target': str(runtime.STATE / 'core-runtime' / 'nested'), 'id': 17}]}))
        with patch.object(runtime.subprocess, 'run', return_value=result), \
                patch.object(runtime.os, 'open', return_value=42), \
                patch.object(runtime.Path, 'read_text', return_value='pos:\t0\nino:\t1\n'), \
                patch.object(runtime.os, 'close') as closed:
            with self.assertRaisesRegex(RuntimeError, 'mount identity'):
                runtime.check_core_mounts()
        closed.assert_called_once_with(42)

    def test_core_mount_identity_only_ignores_missing_target_path(self):
        target = Path('/run/user/1000/doc')
        with patch.object(runtime.os, 'open', side_effect=FileNotFoundError):
            self.assertIsNone(runtime._visible_mount_id(target))
        with patch.object(runtime.os, 'open', side_effect=PermissionError):
            with self.assertRaises(PermissionError):
                runtime._visible_mount_id(target)
        # Missing fdinfo is an inspection failure, not a hidden target.
        with patch.object(runtime.os, 'open', return_value=42), \
                patch.object(runtime.Path, 'read_text', side_effect=FileNotFoundError), \
                patch.object(runtime.os, 'close') as closed:
            with self.assertRaises(FileNotFoundError):
                runtime._visible_mount_id(target)
        closed.assert_called_once_with(42)

    def test_receipt_atomic_write_and_link_refusal(self):
        state = self.root / 'state'
        state.mkdir(mode=0o700)
        with patch.object(runtime, 'STATE', state):
            runtime.save_receipt('synthetic-wallet', {'schema': 1, 'wallet_digest': 'synthetic'})
            self.assertEqual(runtime.read_receipts(), {'synthetic-wallet': {'schema': 1, 'wallet_digest': 'synthetic'}})
            self.assertEqual((state / 'exports.json').stat().st_mode & 0o777, 0o600)
            self.assertFalse((state / 'exports.new').exists())
            victim = self.root / 'untouched'
            victim.write_text('must remain unchanged')
            (state / 'exports.new').symlink_to(victim)
            with self.assertRaises(FileExistsError):
                runtime.save_receipt('second-wallet', {'schema': 1})
            self.assertEqual(victim.read_text(), 'must remain unchanged')

    def test_encrypted_export_real_engine_and_reverification(self):
        raw = self.root / 'wallet.dat'
        database(raw)
        # The test output archive is also in volatile memory. Destination media
        # classification is mocked only here, never in the production launcher.
        password = ['synthetic-test-archive-passphrase ž ']
        (self.root / 'export').mkdir(mode=0o700)
        policy = SimpleNamespace(ROOT=self.root,check_storage=lambda:None,file_digest=runtime.file_digest)
        archive = backup.create_backup([raw], self.root / 'wallet.gpg', password, policy=policy)
        # Backup 0.7.3 encrypts a single wallet directly with AES256-MDC.
        receipt = {'schema':3,'format':'gpg-wallet','layers':1,'encryption_profile':'AES256-MDC','archive':str(archive), 'archive_sha256':runtime.file_digest(archive),
            'wallet_backup_sha256':runtime.file_digest(raw), 'wallet_digest':runtime.wallet_digest(raw)}
        with patch.object(export, 'ROOT', self.root), patch.object(export, 'media_for', return_value=(True,'test-media')), \
                patch.object(runtime, 'check_storage'):
            self.assertEqual(export.verify_export(receipt,password),'test-media')
            with self.assertRaisesRegex(RuntimeError, 'Unexpected wallet backup payload format'):
                export.verify_export(dict(receipt, format='gpg-tar'), password)
            with self.assertRaises(Exception):
                export.verify_export(receipt,['deliberately-wrong-password'])
            wrong = dict(receipt, wallet_backup_sha256='0'*64)
            with self.assertRaises(RuntimeError):
                export.verify_export(wrong,password)
            with archive.open('ab') as stream:
                stream.write(b'tampered-test-data')
            with self.assertRaises(RuntimeError):
                export.verify_export(receipt,password)

    def test_plaintext_payload_is_rejected(self):
        from layered_backend import recover_payload, MorePassphrases
        raw = self.root / 'wallet.dat'
        database(raw)
        (self.root / 'export').mkdir(mode=0o700)
        with self.assertRaises(MorePassphrases):
            with recover_payload(raw, ['synthetic-password'], ram_root=self.root / 'export'):
                self.fail('Plaintext was accepted as an encrypted backup')

if __name__ == '__main__':
    unittest.main(verbosity=2)
