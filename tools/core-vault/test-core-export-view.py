#!/usr/bin/python3
"""Exercise the public-export filesystem callbacks using synthetic local files."""
import errno
import os
from pathlib import Path
import tempfile
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/core-vault/backup-src/src'))
sys.path.insert(0, str(ROOT / 'config/includes.chroot/usr/lib/core-vault'))
import export_view


class MediaTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.media = Path(temporary.name) / 'media'
        self.work = Path(temporary.name) / 'work'
        self.usb = self.media / 'Transfer'
        self.usb.mkdir(parents=True)
        self.work.mkdir()
        self.view = export_view.MediaView(self.media, self.work)
        self.addCleanup(self.view.destroy, '/')
        self.view.report = mock.Mock()
        self.target = mock.Mock()
        patcher = mock.patch.object(export_view, 'open_target', return_value=self.target)
        self.open_target = patcher.start()
        self.addCleanup(patcher.stop)

    def test_psbt_close_only_once(self):
        path = '/Transfer/signed.psbt'
        fd = self.view.create(path, 0o600)
        self.view.write(path, b'synthetic bytes', 0, fd)
        self.assertEqual(list(self.usb.iterdir()), [])
        self.target.publish.side_effect = lambda file, kind: self.assertEqual(
            (file.read_bytes(), kind), (b'synthetic bytes', 'psbt'))
        self.view.flush(path, fd)
        self.view.flush(path, fd)
        self.view.release(path, fd)
        self.target.publish.assert_called_once()
        self.target.close.assert_called_once()
        self.assertEqual(list(self.work.iterdir()), [])

    def test_invalid_overwrite_preserves_old_file(self):
        path = '/Transfer/signed.psbt'
        original = self.usb / 'signed.psbt'
        original.write_bytes(b'old public file')
        fd = self.view.open(path, os.O_WRONLY | os.O_TRUNC)
        self.open_target.assert_called_once_with(self.media, Path(path[1:]), replace=True)
        self.view.write(path, b'invalid bytes', 0, fd)
        self.target.publish.side_effect = ValueError('invalid PSBT')
        with self.assertRaises(OSError):
            self.view.flush(path, fd)
        self.view.release(path, fd)
        self.assertEqual(original.read_bytes(), b'old public file')
        self.view.report.assert_called_once()
        self.assertEqual(list(self.work.iterdir()), [])

    def test_sqlite_probe_journal_and_close(self):
        path = '/Transfer/online.dat'
        journal = path + '-journal'
        probe = self.view.create(path, 0o600)
        self.view.flush(path, probe)
        self.view.release(path, probe)
        self.target.publish.assert_not_called()
        main = self.view.open(path, os.O_RDWR)
        fd = self.view.create(journal, 0o600)
        self.view.write(journal, b'journal', 0, fd)
        self.view.write(path, b'synthetic completed database', 0, main)
        self.view.flush(journal, fd)
        self.view.release(journal, fd)
        self.assertEqual(list(self.usb.iterdir()), [])
        self.view.unlink(journal)
        self.target.publish.assert_called_once()
        self.assertEqual(self.target.publish.call_args.args[1], 'watchonly')
        self.view.flush(path, main)
        self.target.publish.assert_called_once()
        self.view.release(path, main)
        self.assertEqual(list(self.work.iterdir()), [])

    def test_nonjournaled_wallet_copy_still_validates_on_close(self):
        path = '/Transfer/copy.dat'
        main = self.view.create(path, 0o600)
        self.view.write(path, b'complete file supplied by a copying writer', 0, main)
        self.view.flush(path, main)
        self.view.release(path, main)
        self.target.publish.assert_called_once()
        self.assertEqual(self.target.publish.call_args.args[1], 'watchonly')

    def test_sqlite_cancel_or_drive_failure_is_returned_at_commit(self):
        path = '/Transfer/retry.dat'
        journal = path + '-journal'
        for error in (export_view.ExportCancelled(), OSError(errno.ENOSPC, 'USB full')):
            with self.subTest(error=type(error)):
                self.target.publish.reset_mock()
                self.target.publish.side_effect = error
                self.view.report.reset_mock()
                main = self.view.create(path, 0o600)
                journal_fd = self.view.create(journal, 0o600)
                self.view.write(path, b'completed database', 0, main)
                self.view.release(journal, journal_fd)
                with self.assertRaises(OSError):
                    self.view.unlink(journal)
                self.view.flush(path, main)
                self.view.release(path, main)
                with self.assertRaises(FileNotFoundError):
                    self.view.unlink(path)
                self.target.publish.assert_called_once()
                if isinstance(error, export_view.ExportCancelled):
                    self.view.report.assert_not_called()
                else:
                    self.view.report.assert_called_once()
                self.assertEqual(list(self.work.iterdir()), [])
                self.assertEqual(list(self.usb.iterdir()), [])

    def test_rollback_to_original_empty_database_does_not_publish(self):
        path = '/Transfer/rollback.dat'
        main = self.view.create(path, 0o600)
        journal = self.view.create(path + '-journal', 0o600)
        self.view.write(path, b'abandoned pages', 0, main)
        self.view.truncate(path, 0, main)
        self.view.release(path + '-journal', journal)
        self.view.unlink(path + '-journal')
        self.view.flush(path, main)
        self.view.release(path, main)
        self.view.unlink(path)  # Core removes the failed destination.
        self.target.publish.assert_not_called()
        self.assertEqual(list(self.work.iterdir()), [])

    def test_failed_sqlite_fsync_never_publishes_on_cleanup(self):
        path = '/Transfer/full.dat'
        main = self.view.create(path, 0o600)
        journal = self.view.create(path + '-journal', 0o600)
        self.view.write(path, b'incomplete pages', 0, main)
        with mock.patch.object(export_view.os, 'fsync', side_effect=OSError(errno.EIO, 'sync error')):
            with self.assertRaises(OSError):
                self.view.fsync(path, False, main)
        self.view.release(path + '-journal', journal)
        self.view.unlink(path + '-journal')
        self.view.flush(path, main)
        self.view.release(path, main)
        self.target.publish.assert_not_called()
        self.view.report.assert_called_once()
        self.assertEqual(list(self.work.iterdir()), [])

    def test_directory_and_existing_wallet_remain_read_only(self):
        path = '/Transfer/wallet.dat'
        (self.usb / 'wallet.dat').write_bytes(b'synthetic existing wallet')
        with self.assertRaises(OSError):
            self.view.open(path, os.O_RDWR)
        with self.assertRaises(OSError) as protected:
            self.view.unlink(path)
        self.assertEqual(protected.exception.errno, errno.EROFS)
        with self.assertRaises(OSError):
            self.view.create('/Transfer/other.txt', 0o600)
        self.open_target.assert_not_called()
        fd = self.view.open(path, os.O_RDONLY)
        self.assertEqual(self.view.read(path, 30, 0, fd), b'synthetic existing wallet')
        self.view.release(path, fd)

    def test_out_of_ram_does_not_publish_partial_file(self):
        path = '/Transfer/online.dat'
        fd = self.view.create(path, 0o600)
        with mock.patch.object(export_view.os, 'pwrite', side_effect=OSError(errno.ENOSPC, 'full')):
            with self.assertRaises(OSError):
                self.view.write(path, b'incomplete', 0, fd)
        self.assertIn('Private RAM', self.view.report.call_args.args[1])
        self.view.flush(path, fd)
        self.view.release(path, fd)
        self.target.publish.assert_not_called()
        self.assertEqual(list(self.work.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
