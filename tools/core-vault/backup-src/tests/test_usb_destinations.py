"""Check verified USB copy, removal, collisions and trusted display paths."""
from contextlib import contextmanager
import hashlib
import io
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

SRC = Path(__file__).resolve().parents[1] / 'src'
sys.path.insert(0, str(SRC))
sys.path.insert(1, str(SRC.parents[3] / 'config/includes.chroot/usr/lib/core-vault'))
import backup
import destinations
import export
import layered_backend as layers


class USBTests(unittest.TestCase):
    def setUp(self):
        self.ram = tempfile.TemporaryDirectory(dir='/dev/shm')
        self.addCleanup(self.ram.cleanup)
        self.root = Path(self.ram.name)
        self.workspace = self.root / 'workspace'
        self.workspace.mkdir(mode=0o700)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.media = Path(self.temp.name) / 'media'
        self.drive = self.media / 'Test Drive'
        self.drive.mkdir(parents=True)
        with destinations._directory(self.drive) as fd:
            self.mid = destinations._mount_id(fd)
        self.records = {self.mid: (self.drive, '8:1', ['rw'])}
        for override in (patch.object(destinations, 'MEDIA_ROOTS', (self.media,)),
                         patch.object(destinations, '_mounts', return_value=self.records),
                         patch.object(export, 'media_for', return_value=(True, str(self.drive)))):
            override.start()
            self.addCleanup(override.stop)
        self.payload = self.root / 'payload.tar'
        with tarfile.open(self.payload, 'w') as archive:
            for name, data in [('notes/with spaces', b'public test input' * 100), ('empty', b'')]:
                entry = tarfile.TarInfo(name)
                entry.size = len(data)
                archive.addfile(entry, io.BytesIO(data))

    def recover(self, target, progress=None):
        @contextmanager
        def authenticated(*args, **kwargs):
            yield self.payload
        with patch.object(layers, 'recover_payload', authenticated):
            return layers.recover_files(self.root/'fixture.gpg', target, ['synthetic'],
                                        workspace=self.workspace, ram_root=self.root, progress=progress)

    def test_writable_removable_mount_only(self):
        self.assertEqual(destinations.mounted_usb_volumes(), [self.drive])
        proposed = self.drive / 'recovered'
        self.assertEqual(backup.recovery_destination(proposed, self.workspace), proposed)
        for records in ({}, {self.mid: (self.drive, '8:1', ['ro'])},
                        {self.mid: (self.drive, '8:1', ['rw']), '5': (Path('/run/live/medium'), '8:1', ['ro'])}):
            with patch.object(destinations, '_mounts', return_value=records):
                with self.assertRaises(ValueError):
                    backup.recovery_destination(proposed, self.workspace)
                self.assertEqual(destinations.mounted_usb_volumes(), [])
        with patch.object(export, 'media_for', return_value=(False, str(self.drive))):
            with self.assertRaises(ValueError):
                backup.recovery_destination(proposed, self.workspace)
        with self.assertRaises(ValueError):
            backup.recovery_destination(self.root / 'unselected-internal-location', self.workspace)

    def test_double_slash_and_stale_read_dont_fall_back_to_host_directory(self):
        source = self.drive / 'selected.gpg'
        source.write_bytes(b'stale backing file')
        doubled = '//' + str(source).lstrip('/')
        self.assertEqual(backup.backup_output_path(doubled), source)
        with patch.object(destinations, '_mounts', return_value={}):
            with self.assertRaises(backup.BackupError):
                backup.selected_paths([doubled])
            with self.assertRaises(ValueError):
                with destinations.destination_directory(backup.backup_output_path(doubled).parent):
                    self.fail('Reached the backing directory.')
            with source.open('rb') as raw, self.assertRaises(ValueError):
                destinations.check_media_input(source, raw.fileno())
        with patch.object(destinations, '_mounts', return_value={self.mid: (self.drive, '8:1', ['ro'])}):
            self.assertEqual(backup.selected_paths([str(source)]), [source])

    def test_published_output_kept_if_final_directory_sync_fails(self):
        target = self.drive / 'kept'
        actual = os.fsync
        def unavailable(fd):
            if os.path.samestat(os.fstat(fd), self.drive.stat()):
                raise OSError('fixture device error')
            return actual(fd)
        with patch.object(os, 'fsync', unavailable), self.assertRaises(backup.BackupError) as error:
            self.recover(target)
        self.assertIn(str(target), str(error.exception))
        self.assertIn('published', str(error.exception))
        self.assertEqual((target/'notes'/'with spaces').read_bytes(), b'public test input' * 100)
        with self.assertRaises(layers.LayerError):
            self.recover(target)

    def test_only_managed_alias_is_expanded(self):
        runtime = self.root / 'runtime'
        alias = runtime / 'core-vault-core-file-dialogs' / 'USB Media'
        alias.parent.mkdir(parents=True)
        alias.symlink_to(self.media)
        other = alias.parent / 'unmanaged'
        other.symlink_to(self.media)
        with patch.dict(os.environ, {'XDG_RUNTIME_DIR': str(runtime)}):
            self.assertEqual(backup.backup_output_path(alias/'Test Drive'/'new'), self.drive/'new')
            self.assertEqual(backup.recovery_destination(alias/'Test Drive'/'new', self.workspace), self.drive/'new')
            with self.assertRaises(ValueError):
                backup.backup_output_path(other/'Test Drive'/'new')
            alias.unlink()
            alias.symlink_to(self.root)
            with self.assertRaises(ValueError):
                backup.backup_output_path(alias/'Test Drive'/'new')

    def test_recovered_tree_and_existing_folder(self):
        target = self.drive / 'verified'
        self.assertEqual(self.recover(target), target)
        self.assertEqual((target/'notes/with spaces').read_bytes(), b'public test input' * 100)
        self.assertEqual((target/'empty').read_bytes(), b'')
        with self.assertRaises(layers.LayerError):
            self.recover(target)
        self.assertFalse(list(self.drive.glob('.vault-recovery-*')))

    def test_partial_copy_cancel_and_failed_readback(self):
        target = self.drive / 'cancelled'
        def cancel_during_copy(src, dst, budget):
            dst.mkdir()
            (dst / 'partial').write_bytes(b'test')
            raise backup.Cancelled()
        with patch.object(layers, '_copy_recovered_tree', cancel_during_copy), self.assertRaises(backup.Cancelled):
            self.recover(target)
        with patch.object(layers, 'digest', return_value=hashlib.sha256(b'wrong').digest()), self.assertRaises(layers.LayerError):
            self.recover(target)
        self.assertEqual(list(self.drive.iterdir()), [])
        self.assertEqual(list(self.workspace.iterdir()), [])

    def test_replaced_mount_cannot_redirect_writes(self):
        target = self.drive / 'verified'
        old_volume = self.media / 'old'
        original_copy = layers._copy_recovered_tree
        def replace_mount(source, dest, budget):
            original_copy(source, dest, budget)
            self.drive.rename(old_volume)
            self.drive.mkdir()
        with patch.object(layers, '_copy_recovered_tree', replace_mount), self.assertRaises(layers.LayerError):
            self.recover(target)
        self.assertEqual(list(self.drive.iterdir()), [])
        self.assertEqual(list(old_volume.iterdir()), [])

    def test_no_usb_plaintext_until_authentication(self):
        with patch.object(layers, 'recover_payload', side_effect=layers.MorePassphrases('missing')), \
                self.assertRaises(layers.MorePassphrases):
            layers.recover_files(self.root/'fixture.gpg', self.drive/'new', ['wrong'],
                                 workspace=self.workspace, ram_root=self.root)
        self.assertEqual(list(self.drive.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
