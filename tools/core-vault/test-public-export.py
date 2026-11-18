#!/usr/bin/python3
"""Exercise the public export policy and atomic publication using disposable files."""
from contextlib import closing
import errno
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

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

    def test_external_transport_and_internal_negative(self):
        def disk(transport, *, removable=False):
            return {'type': 'disk', 'rm': removable, 'tran': transport, 'maj:min': '8:0'}
        cases = [('usb', False, True), ('sbp', False, True), ('mmc', True, True),
                 ('nvme', False, False), ('sata', False, False), ('mmc', False, False)]
        for transport, removable, allowed in cases:
            with self.subTest(transport=transport, removable=removable):
                leaf = disk(transport, removable=removable)
                row = {'type': 'part', 'children': [leaf]}
                result = Mock(stdout=json.dumps({'blockdevices': [row]}))
                with patch.object(export.subprocess, 'run', return_value=result), \
                        patch.object(export, 'kernel_external', return_value=False):
                    self.assertEqual(export.physical_drives('/dev/test'), {'8:0': allowed})

    def test_kernel_external_pci_and_firewire(self):
        sysfs = self.root / 'sys'
        devlink = sysfs / 'dev/block'
        devlink.mkdir(parents=True)
        busdir = sysfs / 'bus'
        device = sysfs / 'devices/rootport/endpoint'
        block = device / 'nvme/nvme0n1'
        block.mkdir(parents=True)
        (devlink / '8:0').symlink_to(block)
        for name in ('pci', 'firewire'):
            (busdir / name).mkdir(parents=True)
        subsystem = device / 'subsystem'
        subsystem.symlink_to(busdir / 'pci')
        for value in ('', 'fixed', 'unknown', '1', 'removable'):
            with self.subTest(pci=value):
                (device / 'removable').write_text(value)
                self.assertEqual(export.kernel_external('8:0', sysfs), value == 'removable')
        (device / 'removable').unlink()
        subsystem.unlink()
        subsystem.symlink_to(busdir / 'firewire')
        self.assertTrue(export.kernel_external('8:0', sysfs))
        self.assertFalse(export.kernel_external('8:1', sysfs))

    def test_boot_and_mixed_internal_disks_rejected(self):
        mounts = [{'id': 45, 'target': '/media/vault/disk', 'source': '/dev/test1', 'fstype': 'exfat'},
                  {'id': 55, 'target': '/run/live/medium', 'source': '/dev/test2', 'fstype': 'iso9660'}]
        result = Mock(stdout=json.dumps({'filesystems': mounts}))
        for disks, error in (([{'8:0': True}, {'8:0': True}], 'boot medium'),
                             ([{'8:0': True, '8:16': False}], 'removable')):
            with self.subTest(disks=disks), patch.object(export, '_mount_id', return_value='45'), \
                    patch.object(export.subprocess, 'run', return_value=result), \
                    patch.object(export, 'physical_drives', side_effect=disks):
                with self.assertRaisesRegex(ValueError, error):
                    export.require_external_volume(0)

    def test_toram_and_iso_whole_disk(self):
        live = {'id': 55, 'target': '/run/live/medium', 'source': 'tmpfs', 'fstype': 'tmpfs'}
        usb = {'id': 45, 'target': '/media/vault/test', 'source': '/dev/test1', 'fstype': 'vfat'}
        with patch.object(export, '_mount_id', return_value='45'), \
                patch.object(export.subprocess, 'run', return_value=Mock(stdout=json.dumps({'filesystems': [usb, live]}))), \
                patch.object(export, 'physical_drives', return_value={'8:0': True}), \
                patch.object(Path, 'read_text', return_value='boot=live toram'), \
                patch.object(Path, 'exists', return_value=False):
            export.require_external_volume(0)
        leaf = {'type': 'disk', 'rm': True, 'tran': 'usb', 'maj:min': '8:0', 'fstype': 'iso9660'}
        result = Mock(stdout=json.dumps({'blockdevices': [{'type': 'part', 'children': [leaf]}]}))
        with patch.object(export.subprocess, 'run', return_value=result):
            self.assertEqual(export.physical_drives('/dev/test1'), {'8:0': False})

    def test_detached_file_boot_without_medium_mount(self):
        usb = {'id': 45, 'target': '/media/vault/test', 'source': '/dev/test1', 'fstype': 'exfat'}
        mounts = [usb, {'id': 1, 'target': '/', 'source': 'overlay', 'fstype': 'overlay'}]
        with patch.object(export, '_mount_id', return_value='45'), \
                patch.object(export.subprocess, 'run', return_value=Mock(stdout=json.dumps({'filesystems': mounts}))), \
                patch.object(export, 'physical_drives', return_value={'8:0': True}), \
                patch.object(Path, 'read_text', return_value='boot=live toram findiso=/vault.iso'):
            with self.assertRaisesRegex(ValueError, 'boot drive could not be identified'):
                export.require_external_volume(0)

    def test_live_iso_carrier_and_installed_root(self):
        usb = {'id': 45, 'target': '/media/vault/test', 'source': '/dev/test1', 'fstype': 'exfat'}
        loop = {'id': 54, 'target': '/run/live/medium', 'source': '/dev/loop0', 'fstype': 'iso9660'}
        for boot in ('/run/live/findiso', '/'):
            real = {'id': 55, 'target': boot, 'source': '/dev/test2', 'fstype': 'ext4'}
            mounts = [usb, loop, real] if boot != '/' else [usb, real]
            with self.subTest(boot=boot), patch.object(export, '_mount_id', return_value='45'), \
                    patch.object(export.subprocess, 'run', return_value=Mock(stdout=json.dumps({'filesystems': mounts}))), \
                    patch.object(export, 'physical_drives', side_effect=[{'8:0': True}, {'8:0': True}]) as disks:
                with self.assertRaisesRegex(ValueError, 'boot medium'):
                    export.require_external_volume(0)
                self.assertEqual(disks.call_args.args[0], '/dev/test2')

    def test_publish_native_watchonly_once(self):
        self.wallet()
        with patch.object(export, 'core_check', return_value={'hasprivatekeys': False}) as core:
            self.target('public.dat').publish(self.stage, 'watchonly')
            core.assert_called_once_with('getdescriptorinfo', b'raw(51)', result=True)
        with self.assertRaises(FileExistsError):
            self.target('public.dat').publish(self.stage, 'watchonly')
        self.assertEqual((self.drive / 'public.dat').read_bytes(), self.stage.read_bytes())

    def test_watchonly_metadata_needs_explicit_consent(self):
        self.wallet()
        with closing(sqlite3.connect(self.stage)) as db, db:
            db.execute('INSERT INTO main VALUES (?,?)', (b'\x04nameaddress', b'example label'))
        with patch.object(export, 'core_check', return_value={'hasprivatekeys': False}), \
                patch.object(export, 'retain_core_windows', side_effect=OSError('No XComposite')), \
                patch.object(export.subprocess, 'run', return_value=Mock(returncode=1)) as question:
            with self.assertRaisesRegex(export.ExportCancelled, 'cancelled'):
                self.target('public.dat').publish(self.stage, 'watchonly')
            self.assertEqual(list(self.drive.iterdir()), [])
            self.assertIn('--default-cancel', question.call_args.args[0])
            self.assertNotIn('example label', str(question.call_args))
            question.return_value = Mock(returncode=-15)
            with self.assertRaisesRegex(ValueError, 'could not confirm permission'):
                self.target('public.dat').publish(self.stage, 'watchonly')
            self.assertEqual(list(self.drive.iterdir()), [])
            question.return_value = Mock(returncode=0)
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
