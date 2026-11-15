#!/usr/bin/python3
"""Exercise the public export policy and atomic publication using disposable files."""
from contextlib import closing
import errno
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'config/includes.chroot/usr/lib/core-vault'),
                str(ROOT / 'tools/core-vault/backup-src/src')]
import public_export as export


class PublicExportTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.drive = self.root / 'Transfer Drive'
        self.drive.mkdir()
        self.stage = self.root / 'stage'
        self.psbt = b'psbt\xff' + b'synthetic test data'

    def target(self, name):
        fd = os.open(self.drive, os.O_DIRECTORY)
        obj = export.ExternalTarget(self.drive, name, fd, export.identity(fd, name))
        self.addCleanup(obj.close)
        return obj

    def wallet(self, *, flags=export.PUBLIC_FLAGS):
        desc = b'raw(51)'
        tag = b'walletdescriptor'
        with closing(sqlite3.connect(self.stage)) as db, db:
            db.execute('CREATE TABLE main(key BLOB PRIMARY KEY NOT NULL, value BLOB NOT NULL)')
            db.executemany('INSERT INTO main VALUES (?,?)', [
                (b'\x05flags', flags.to_bytes(8, 'little')),
                (bytes([len(tag)]) + tag + bytes(32), bytes([len(desc)]) + desc + bytes(20)),
            ])

    def test_publish_native_watchonly_once(self):
        self.wallet()
        with patch.object(export, 'core_check', return_value={'hasprivatekeys': False}) as core:
            self.target('public.dat').publish(self.stage, 'watchonly')
            core.assert_called_once_with('getdescriptorinfo', b'raw(51)', result=True)
        with self.assertRaises(FileExistsError):
            self.target('public.dat').publish(self.stage, 'watchonly')
        self.assertEqual((self.drive / 'public.dat').read_bytes(), self.stage.read_bytes())

    def test_signing_wallet_cannot_be_exported_as_watchonly(self):
        self.wallet(flags=1 << 34)
        with self.assertRaisesRegex(ValueError, 'watch-only'):
            self.target('private.dat').publish(self.stage, 'watchonly')
        self.assertEqual(list(self.drive.iterdir()), [])

    def test_descriptor_must_be_public(self):
        self.wallet()
        with patch.object(export, 'core_check', return_value={'hasprivatekeys': True}):
            with self.assertRaisesRegex(ValueError, 'private descriptor'):
                self.target('public.dat').publish(self.stage, 'watchonly')
        self.assertEqual(list(self.drive.iterdir()), [])

    def test_core_decode_failure_preserves_existing_psbt(self):
        self.stage.write_bytes(self.psbt)
        previous = self.drive / 'signed.psbt'
        previous.write_bytes(b'original')
        with patch.object(export, 'core_check', side_effect=ValueError('incomplete PSBT')):
            with self.assertRaisesRegex(ValueError, 'incomplete'):
                self.target(previous.name).publish(self.stage, 'psbt')
        self.assertEqual(previous.read_bytes(), b'original')
        self.assertEqual(list(self.drive.iterdir()), [previous])

    def test_changed_destination_preserved(self):
        self.stage.write_bytes(self.psbt)
        target = self.target('signed.psbt')
        late_file = self.drive / 'signed.psbt'
        late_file.write_bytes(b'created meanwhile')
        with patch.object(export, 'core_check'):
            with self.assertRaises(FileExistsError):
                target.publish(self.stage, 'psbt')
        self.assertEqual(late_file.read_bytes(), b'created meanwhile')

    def test_partial_copy_to_full_drive_preserves_previous_file(self):
        self.stage.write_bytes(self.psbt)
        previous = self.drive / 'signed.psbt'
        previous.write_bytes(b'original')

        def fail_after_first_byte(source, dest, *, length):
            dest.write(source.read(1))
            raise OSError(errno.ENOSPC, 'No space left on device')

        with patch.object(export, 'core_check'), patch.object(export.shutil, 'copyfileobj', fail_after_first_byte):
            with self.assertRaises(OSError) as error:
                self.target(previous.name).publish(self.stage, 'psbt')
        self.assertEqual(error.exception.errno, errno.ENOSPC)
        self.assertEqual(previous.read_bytes(), b'original')
        self.assertEqual(list(self.drive.iterdir()), [previous])

    def test_confirmed_psbt_replacement(self):
        self.stage.write_bytes(self.psbt)
        previous = self.drive / 'signed.psbt'
        previous.write_bytes(b'original')
        with patch.object(export, 'core_check') as core:
            self.target(previous.name).publish(self.stage, 'psbt')
            self.assertEqual(core.call_args.args[0], 'decodepsbt')
        self.assertEqual(previous.read_bytes(), self.psbt)
        self.assertEqual(list(self.drive.iterdir()), [previous])


if __name__ == '__main__':
    unittest.main()
