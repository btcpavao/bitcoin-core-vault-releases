"""Wallet input consistency, RAM staging and unchanged generic selection tests."""
import importlib.util
import hashlib
from pathlib import Path
import sqlite3
import tempfile
import types
import unittest
import sys
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))
spec = importlib.util.spec_from_file_location('wallet_backup', ROOT / 'src/backup.py')
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)


def database(path, payload=b'plain synthetic private record'):
    con = sqlite3.connect(path)
    con.execute('CREATE TABLE main (key BLOB PRIMARY KEY, value BLOB)')
    con.execute('INSERT INTO main VALUES (?,?)', (b'synthetic-key', payload))
    con.commit()
    con.close()

def digest(path):
    con = sqlite3.connect(path)
    try:
        return con.execute('SELECT value FROM main').fetchone()[0]
    finally:
        con.close()


class WalletInputsTests(unittest.TestCase):
    def setUp(self):
        # This fixture exercises real GPG: CI /tmp may be disk-backed.
        self.tmp = tempfile.TemporaryDirectory(dir='/dev/shm')
        root = Path(self.tmp.name)
        home = root / 'home'
        wallets = home / '.bitcoin/wallets'
        self.folder = wallets / 'nested name' / 'wallet one'
        self.folder.mkdir(parents=True)
        (root / 'export').mkdir(mode=0o700)
        self.wallet = self.folder / 'wallet.dat'
        database(self.wallet)
        self.policy = types.SimpleNamespace(
            ROOT=root, HOME=home, PRIVATE=home / "Private Workspace", WALLETS=wallets, EXTRA_WALLET_ROOTS=(),
            check_storage=Mock(), canonical_wallet_path=lambda path: Path(path),
            loaded_wallet_file=lambda name: wallets / name / 'wallet.dat',
            wallet_digest=digest,
            file_digest=lambda path: hashlib.sha256(path.read_bytes()).hexdigest(),
            wallet_files=lambda: {self.name: self.wallet}, save_receipt=Mock())
        self.name = str(self.folder.relative_to(wallets))

    def tearDown(self):
        self.tmp.cleanup()

    def test_live_wallet_uses_official_backup_without_direct_sqlite_read(self):
        calls = []
        def rpc(method, *args, wallet=None):
            calls.append((method, args, wallet))
            if method == 'listwallets': return [self.name]
            if method == 'backupwallet': database(args[0])
        self.policy.rpc = rpc
        with b.consistent_inputs([self.wallet], self.policy) as inputs:
            self.assertEqual(inputs[0].name, 'wallet.dat')
            self.assertTrue(inputs[0].is_relative_to(self.policy.ROOT / 'export'))
            self.assertEqual(inputs[0].read_bytes()[:16], b'SQLite format 3\0')
        self.assertEqual([call[0] for call in calls], ['listwallets', 'backupwallet'])
        self.assertEqual(calls[1][2], self.name)
        self.assertEqual(list((self.policy.ROOT / 'export').iterdir()), [])

    def test_unloaded_wallet_is_readonly_without_load_or_startup_changes(self):
        calls = []
        def rpc(method, *args, wallet=None):
            calls.append((method, args, wallet))
            if method == 'listwallets': return []
            raise AssertionError('Unloaded wallet must not be loaded or modified')
        self.policy.rpc = rpc
        original = self.wallet.read_bytes()
        with b.consistent_inputs([self.wallet], self.policy): pass
        self.assertEqual([call[0] for call in calls], ['listwallets'])
        self.assertEqual(self.wallet.read_bytes(), original)

    def test_closed_core_readonly_sqlite_snapshot_keeps_original_bytes(self):
        original = self.wallet.read_bytes()
        self.policy.rpc = Mock(side_effect=RuntimeError('Core closed'))
        with b.consistent_inputs([self.wallet], self.policy) as inputs:
            self.assertEqual(self.policy.wallet_digest(inputs[0]), b'plain synthetic private record')
        self.assertEqual(self.wallet.read_bytes(), original)
        self.assertEqual(list((self.policy.ROOT / 'export').iterdir()), [])

    def test_closed_snapshot_includes_committed_wal_records(self):
        self.policy.rpc = Mock(side_effect=RuntimeError('Core closed'))
        writer = sqlite3.connect(self.wallet)
        try:
            self.assertEqual(writer.execute('PRAGMA journal_mode=WAL').fetchone(), ('wal',))
            writer.execute('PRAGMA wal_autocheckpoint=0')
            writer.execute('UPDATE main SET value=?', (b'committed synthetic WAL record',))
            writer.commit()
            source_bytes = self.wallet.read_bytes()
            self.assertTrue(self.wallet.with_name('wallet.dat-wal').stat().st_size > 0)
            with b.consistent_inputs([self.wallet], self.policy) as inputs:
                self.assertEqual(digest(inputs[0]), b'committed synthetic WAL record')
            self.assertEqual(self.wallet.read_bytes(), source_bytes)
        finally:
            writer.close()

    def test_mixed_folder_snapshot_omits_journals_and_keeps_structure(self):
        self.policy.rpc = Mock(side_effect=RuntimeError('Core closed'))
        (self.folder / 'notes.txt').write_text('synthetic companion')
        for suffix in ('-wal', '-shm', '-journal'):
            (self.wallet.with_name('wallet.dat' + suffix)).write_bytes(b'')
        # An empty SQLite sidecar is harmless to a normal read-only transaction.
        with b.consistent_inputs([self.folder], self.policy) as inputs:
            self.assertEqual(inputs[0].name, self.folder.name)
            self.assertEqual(sorted(p.name for p in inputs[0].iterdir()), ['notes.txt', 'wallet.dat'])
            self.assertEqual((inputs[0] / 'notes.txt').read_text(), 'synthetic companion')
        for suffix in ('-wal', '-shm', '-journal'):
            self.assertTrue(self.wallet.with_name('wallet.dat' + suffix).exists())

    def test_generic_file_avoids_rpc_and_plaintext_staging(self):
        source = self.folder / 'ordinary.txt'
        source.write_text('synthetic generic data')
        self.policy.rpc = Mock(side_effect=AssertionError('No Core operation'))
        with b.consistent_inputs([source], self.policy) as inputs:
            self.assertEqual(inputs, [source])
        self.policy.rpc.assert_not_called()
        self.assertEqual(list((self.policy.ROOT / 'export').iterdir()), [])

    def test_failure_does_not_unload_wallet_and_removes_ram_stage(self):
        calls = []
        def rpc(method, *args, wallet=None):
            calls.append(method)
            if method == 'listwallets': return [self.name]
            if method == 'backupwallet': raise RuntimeError('Synthetic failure')
        self.policy.rpc = rpc
        with self.assertRaises(RuntimeError):
            with b.consistent_inputs([self.wallet], self.policy): pass
        self.assertEqual(calls, ['listwallets', 'backupwallet'])
        self.assertEqual(list((self.policy.ROOT / 'export').iterdir()), [])

    def test_bad_storage_stops_before_scanning_or_rpc(self):
        self.policy.check_storage.side_effect = RuntimeError('Not RAM')
        self.policy.rpc = Mock()
        with self.assertRaises(RuntimeError):
            with b.consistent_inputs([self.wallet], self.policy): pass
        self.policy.rpc.assert_not_called()

    def test_selected_ram_ancestor_cannot_include_its_own_staging_directory(self):
        self.policy.rpc = Mock()
        with self.assertRaises(b.BackupError):
            with b.consistent_inputs([self.policy.ROOT], self.policy): pass
        self.policy.rpc.assert_not_called()
        self.assertEqual(list((self.policy.ROOT / 'export').iterdir()), [])

    def test_ancestor_symlink_is_refused(self):
        link = self.policy.WALLETS / 'alias'
        link.symlink_to(self.folder, target_is_directory=True)
        self.policy.rpc = Mock()
        with self.assertRaises(b.BackupError):
            with b.consistent_inputs([link / 'wallet.dat'], self.policy): pass
        self.policy.rpc.assert_not_called()

    def test_original_home_alias_symlink_is_not_hidden_by_canonicalization(self):
        old_home = self.policy.HOME
        actual_home = old_home.with_name('actual-home')
        old_home.rename(actual_home)
        old_home.symlink_to(actual_home, target_is_directory=True)
        self.policy.HOME = actual_home
        self.policy.WALLETS = actual_home / '.bitcoin/wallets'
        self.policy.canonical_wallet_path = lambda path: actual_home / path.relative_to(old_home) if path.is_relative_to(old_home) else path
        self.policy.rpc = Mock()
        with self.assertRaises(b.BackupError):
            with b.consistent_inputs([self.wallet], self.policy): pass
        self.policy.rpc.assert_not_called()

    def test_strict_wallet_create_ui_uses_one_backup_request(self):
        def rpc(method, *args, wallet=None):
            if method == 'listwallets': return [self.name]
            if method == 'backupwallet': database(args[0])
        self.policy.rpc = rpc
        destination = self.policy.ROOT / 'right-click.gpg'
        provider = Mock(return_value=(destination, ['synthetic independent archive password']))
        original_exists = Path.exists
        def exists(path):
            return True if str(path) == '/etc/core-vault-backup.require-private-workspace' else original_exists(path)
        verify = Mock()
        modules = {'runtime': self.policy,
                   'password_dialog': types.SimpleNamespace(get_backup_request=provider),
                   'export': types.SimpleNamespace(media_for=lambda path: (False, 'RAM workspace'), verify_export=verify)}
        with patch.dict(sys.modules, modules), patch.object(Path, 'exists', exists), \
             patch.object(b, 'dialog', return_value=str(destination)) as dialog, \
             patch.object(b, 'Progress') as progress, patch.object(b, 'message') as message:
            b.create_ui([str(self.wallet)])
        dialog.assert_not_called()
        provider.assert_called_once()
        self.assertTrue(destination.is_file())
        self.assertTrue(message.call_args.args[0].startswith('Encrypted backup created and tested:'))
        progress.return_value.close.assert_called_once()
        self.assertEqual(list((self.policy.ROOT / 'export').iterdir()), [])
        verify.assert_called_once()
        self.policy.save_receipt.assert_called_once()
        self.assertEqual(self.policy.save_receipt.call_args.args[0], self.name)
        self.assertNotIn('internal_override', self.policy.save_receipt.call_args.args[1])

    def test_receipt_allowed_in_ram_and_internal_folders_without_approval(self):
        archive = self.policy.ROOT / 'synthetic.gpg'
        archive.write_bytes(b'fake archive for control flow only')
        for location in ('RAM workspace', 'internal folder', 'external media'):
            with self.subTest(location=location):
                self.policy.save_receipt.reset_mock()
                verify = Mock()
                with patch.dict(sys.modules, {'export': types.SimpleNamespace(
                        media_for=lambda path: (location == 'external media', location),
                        verify_export=verify)}):
                    self.assertTrue(b.record_wallet_export(
                        [self.wallet], [self.wallet], archive, ['test'], self.policy))
                verify.assert_called_once()
                record = self.policy.save_receipt.call_args.args[1]
                self.assertEqual(record['media'], location)
                self.assertNotIn('internal_override', record)

    def test_direct_gpg_wallet_receipt_identifies_profile_and_same_snapshot(self):
        archive = self.policy.ROOT / 'synthetic.gpg'
        archive.write_bytes(b'ciphertext producer control-flow fixture')
        snapshot = self.policy.ROOT / 'export' / 'wallet.dat'
        database(snapshot, b'different consistent snapshot record')
        verify = Mock()
        with patch.dict(sys.modules, {'export': types.SimpleNamespace(
                media_for=lambda path: (True, 'synthetic media'), verify_export=verify)}):
            self.assertTrue(b.record_wallet_export([self.wallet], [snapshot], archive, ['test'],
                                                  self.policy))
        receipt = self.policy.save_receipt.call_args.args[1]
        self.assertEqual(receipt['schema'], 3)
        self.assertEqual(receipt['format'], 'gpg-wallet')
        self.assertEqual(receipt['encryption_profile'], 'AES256-MDC')
        self.assertEqual(receipt['wallet_backup_sha256'], self.policy.file_digest(snapshot))
        self.assertEqual(receipt['wallet_digest'], b'different consistent snapshot record')
        verify.assert_called_once_with(receipt, ['test'])

    def test_mixed_and_folder_selections_do_not_claim_finish_receipt(self):
        with patch.dict(sys.modules, {'export': types.SimpleNamespace(media_for=Mock(side_effect=AssertionError('No receipt')))}):
            self.assertFalse(b.record_wallet_export([self.wallet, self.wallet.with_name('notes.txt')], [], Path('unused'), ['test'], self.policy))
            self.assertFalse(b.record_wallet_export([self.folder], [], Path('unused'), ['test'], self.policy))
        self.policy.save_receipt.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
