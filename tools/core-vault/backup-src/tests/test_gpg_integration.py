"""Publication and wallet-receipt regressions for the shared GPG/TAR backend."""
import hashlib
import importlib.util
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[4]
SRC=ROOT/'tools/core-vault/backup-src/src'
RUNTIME=ROOT/'config/includes.chroot/usr/lib/core-vault'
sys.path.insert(0,str(SRC));sys.path.insert(1,str(RUNTIME))
import backup
import runtime
import export
import layered_backend as layers

def digest(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir='/dev/shm')
        self.root=Path(self.tmp.name)
        (self.root/'export').mkdir(mode=0o700)
        self.source=self.root/'wallet.dat'
        with sqlite3.connect(self.source) as db:
            db.execute('CREATE TABLE main (key BLOB PRIMARY KEY, value BLOB)')
            db.execute('INSERT INTO main VALUES (?,?)',(b'synthetic',b'disposable data'))
        db.close()
        self.policy=types.SimpleNamespace(ROOT=self.root,check_storage=Mock(),file_digest=digest)
        self.passwords=['independent synthetic alpha','independent synthetic beta']
        self.destination=self.root/'backup.gpg'

    def tearDown(self):
        self.tmp.cleanup()

    def create(self):
        return backup.create_backup([self.source],self.destination,self.passwords,policy=self.policy)

    def receipt(self,path):
        return dict(schema=3,format='gpg-wallet',layers=2,encryption_profile='AES256-MDC',
            archive=str(path),archive_sha256=digest(path),wallet_backup_sha256=digest(self.source),
            wallet_digest=runtime.wallet_digest(self.source))

    def test_complete_publication_and_receipt(self):
        before=self.source.read_bytes();path=self.create()
        self.assertEqual(before,self.source.read_bytes())
        receipt=self.receipt(path)
        with patch.object(runtime,'check_storage'),patch.object(export,'ROOT',self.root),patch.object(export,'media_for',return_value=(True,'test-media')):
            self.assertEqual(export.verify_export(receipt,list(reversed(self.passwords))),'test-media')
            for changes in ({'wallet_backup_sha256':'0'*64},{'wallet_digest':'wrong'}):
                with self.assertRaises(RuntimeError):export.verify_export(dict(receipt,**changes),self.passwords)
            with self.assertRaises(RuntimeError):export.verify_export(receipt,['wrong'])
        self.assertEqual(list((self.root/'export').iterdir()),[])

    def test_existing_and_publish_race_never_overwrite(self):
        self.destination.write_bytes(b'existing')
        with self.assertRaises(backup.BackupError):self.create()
        self.assertEqual(self.destination.read_bytes(),b'existing')
        candidate=self.root/'candidate';candidate.write_bytes(b'new')
        with self.assertRaises(FileExistsError):backup.publish_new(candidate,self.destination)
        self.assertEqual(self.destination.read_bytes(),b'existing')

    def test_corrupted_copy_never_published(self):
        def corrupt(source,output,progress=None):output.write(b'broken ciphertext')
        with patch.object(backup,'copy_ciphertext',corrupt):
            with self.assertRaises(backup.BackupError):self.create()
        self.assertFalse(self.destination.exists())
        self.assertFalse(list(self.root.glob('.vault-backup-*')))
        self.assertEqual(list((self.root/'export').iterdir()),[])

    def test_cancel_before_publication_cleans_all(self):
        def cancel(*args,**kwargs):raise backup.Cancelled()
        with patch.object(backup,'copy_ciphertext',cancel):
            with self.assertRaises(backup.Cancelled):self.create()
        self.assertFalse(self.destination.exists())
        self.assertFalse(list(self.root.glob('.vault-backup-*')))
        self.assertEqual(list((self.root/'export').iterdir()),[])

    def test_storage_failure_precedes_crypto(self):
        self.policy.check_storage.side_effect=RuntimeError('synthetic storage failure')
        with patch.object(layers,'create_layers') as engine:
            with self.assertRaises(RuntimeError):self.create()
        engine.assert_not_called()

    def test_internal_receipt_allowed_but_storage_and_integrity_remain_required(self):
        path=self.create();receipt=self.receipt(path)
        with patch.object(runtime,'check_storage'),patch.object(export,'ROOT',self.root),patch.object(export,'media_for',return_value=(False,'internal')):
            self.assertEqual(export.verify_export(receipt,self.passwords), 'internal')
        with patch.object(runtime,'check_storage',side_effect=RuntimeError('bad storage')):
            with self.assertRaises(RuntimeError):export.verify_export(receipt,self.passwords)
        with patch.object(runtime,'check_storage'),patch.object(export,'ROOT',self.root),patch.object(export,'media_for',return_value=(True,'external')):
            with path.open('ab') as stream:stream.write(b'tamper')
            with self.assertRaises(RuntimeError):export.verify_export(receipt,self.passwords)

    def test_wallet_export_to_private_workspace_without_media_override(self):
        workspace = self.root / 'Private Workspace'
        workspace.mkdir(mode=0o700)
        destination = workspace / 'wallet backup.gpg'
        before = self.source.read_bytes()
        with patch.object(runtime, 'check_storage'), patch.object(runtime, 'ROOT', self.root), \
             patch.object(export, 'ROOT', self.root), \
             patch.object(export, 'loaded_wallet_file', return_value=self.source), \
             patch.object(runtime, 'rpc', side_effect=RuntimeError('Closed synthetic Core')), \
             patch.object(export, 'save_receipt') as save:
            # Uses real findmnt on tmpfs: the old implementation refused here.
            self.assertFalse(export.media_for(destination)[0])
            self.assertEqual(export.export_wallet('synthetic', destination, self.passwords), destination)
            receipt = save.call_args.args[1]
            self.assertEqual(receipt['archive'], str(destination))
            self.assertNotIn('internal_override', receipt)
            self.assertTrue(export.verify_export(receipt, list(reversed(self.passwords))))
            copy = workspace / 'organized' / destination.name
            copy.parent.mkdir()
            copy.write_bytes(destination.read_bytes())
            self.assertTrue(export.verify_export(dict(receipt, archive=str(copy)), self.passwords))
        self.assertEqual(self.source.read_bytes(), before)
        self.assertEqual(list((self.root / 'export').iterdir()), [])

    def test_location_detection_is_metadata_only(self):
        for filesystem in ('tmpfs', 'ramfs', 'overlay', 'ext4'):
            with self.subTest(filesystem=filesystem):
                result = types.SimpleNamespace(stdout=__import__('json').dumps({
                    'filesystems': [{'target': '/chosen', 'source': 'fixture',
                                     'fstype': filesystem}]}))
                with patch.object(export.subprocess, 'run', return_value=result):
                    self.assertEqual(export.media_for(self.destination), (False, '/chosen'))
        path = self.create()
        receipt = self.receipt(path)
        real_run = export.subprocess.run
        def without_mount_metadata(args, **kwargs):
            if args[0] == '/usr/bin/findmnt':
                raise OSError('Synthetic metadata failure')
            return real_run(args, **kwargs)
        with patch.object(runtime, 'check_storage'), patch.object(export, 'ROOT', self.root), \
             patch.object(export.subprocess, 'run', side_effect=without_mount_metadata):
            self.assertEqual(export.verify_export(receipt, self.passwords), str(path.parent))

    def test_wrong_wallet_and_extra_files_not_accepted(self):
        other=self.root/'notes.txt';other.write_text('synthetic note')
        path=backup.create_backup([self.source,other],self.destination,self.passwords,policy=self.policy)
        with patch.object(runtime,'check_storage'),patch.object(export,'ROOT',self.root),patch.object(export,'media_for',return_value=(True,'external')):
            with self.assertRaises(RuntimeError):export.verify_export(self.receipt(path),self.passwords)

    def test_unknown_receipt_rejected(self):
        for receipt in ({},{'schema':1},{'schema':2},{'schema':3,'format':'gpg-tar','layers':True}):
            with self.assertRaises(RuntimeError):export.receipt_format(receipt)

    def test_secret_in_args_or_environment_forbidden(self):
        import gpg_backend
        original=gpg_backend.subprocess.Popen
        def inspect(args,**kwargs):
            for secret in self.passwords:
                self.assertNotIn(secret,str(args))
                self.assertNotIn(secret,str(kwargs.get('env',{})))
            self.assertIn('--passphrase-fd',args)
            return original(args,**kwargs)
        with patch.object(gpg_backend.subprocess,'Popen',inspect):
            self.create()
        self.assertEqual(list((self.root/'export').iterdir()),[])

    def test_no_plaintext_outside_ram_staging(self):
        original=backup.copy_ciphertext
        def inspect(source,output,progress=None):
            self.assertNotEqual(Path(source.name).read_bytes(),self.source.read_bytes())
            self.assertTrue(Path(source.name).is_relative_to(self.root/'export'))
            return original(source,output,progress)
        with patch.object(backup,'copy_ciphertext',inspect):self.create()

if __name__=='__main__':unittest.main()
