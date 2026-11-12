"""UI route cancellation and non-destructive fresh-image setup."""
import importlib.util
import runpy
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock,patch
SRC=Path(__file__).resolve().parents[1]/'src'
sys.path.insert(0,str(SRC))
import backup

class RouteTests(unittest.TestCase):
    def test_explicit_cli_recovery_route(self):
        with patch.object(sys,'argv',['core-vault-backup','decrypt','input.gpg']),patch.object(backup.os,'geteuid',return_value=1000),patch.object(backup,'decrypt_ui') as recover:
            self.assertEqual(backup.main(),0)
        recover.assert_called_once_with(['input.gpg'])

    def test_recovery_cancel_never_starts_crypto(self):
        with tempfile.TemporaryDirectory(dir='/dev/shm') as d:
            root=Path(d);source=root/'test.gpg';source.write_bytes(b'synthetic')
            with patch.dict(sys.modules,{'runtime':types.SimpleNamespace(check_storage=Mock(),ROOT=root,PRIVATE=root),
                    'recovery_dialog':types.SimpleNamespace(get_recovery_request=Mock(return_value=None))}),patch.object(backup,'verified_workspace',return_value=root),patch.object(backup,'Progress') as progress:
                with self.assertRaises(backup.Cancelled):backup.decrypt_ui([source])
                progress.assert_not_called()

    def test_create_cancel_never_starts_crypto(self):
        with tempfile.TemporaryDirectory(dir='/dev/shm') as d:
            root=Path(d);source=root/'test';source.write_bytes(b'synthetic')
            with patch.dict(sys.modules,{'runtime':types.SimpleNamespace(check_storage=Mock(),ROOT=root,PRIVATE=root),
                    'password_dialog':types.SimpleNamespace(get_backup_request=Mock(return_value=None))}),patch.object(backup,'Progress') as progress:
                with self.assertRaises(backup.Cancelled):backup.create_ui([source])
                progress.assert_not_called()

    def test_home_backup_accepts_chosen_folder_without_media_prompt(self):
        with tempfile.TemporaryDirectory(dir='/dev/shm') as d:
            root = Path(d)
            workspace = root / 'Private Workspace'
            workspace.mkdir()
            wallet = root / 'wallet.dat'
            wallet.write_bytes(b'UI route fixture only')
            for folder in (workspace, root / 'other folder'):
                folder.mkdir(exist_ok=True)
                destination = folder / 'chosen.gpg'
                request = Mock(return_value=(destination, ['synthetic passphrase']))
                export_wallet = Mock(return_value=destination)
                modules = {
                    'runtime': types.SimpleNamespace(check_storage=Mock(), PRIVATE=workspace,
                        wallet_files=lambda: {'synthetic': wallet}, check_loaded_wallet_coverage=Mock()),
                    'password_dialog': types.SimpleNamespace(get_backup_request=request),
                    'export': types.SimpleNamespace(export_wallet=export_wallet)}
                with self.subTest(folder=folder), patch.dict(sys.modules, modules), \
                     patch.object(backup, 'harden'), patch.object(backup.os, 'geteuid', return_value=1000), \
                     patch.object(backup, 'dialog') as dialog, patch.object(backup, 'message'), \
                     patch.object(backup, 'Progress'), patch('subprocess.Popen') as launch:
                    runpy.run_path(str(SRC.parents[3] /
                        'config/includes.chroot/usr/local/bin/core-vault-wallet-backup'))
                if folder == workspace:
                    self.assertEqual(launch.call_count, 1)
                    self.assertEqual(launch.call_args.args, (['/usr/bin/thunar', str(workspace)],))
                else:
                    launch.assert_not_called()
                dialog.assert_not_called()
                self.assertEqual(request.call_args.args[1], workspace / 'wallet.dat.gpg')
                self.assertEqual(export_wallet.call_args.args,
                                 ('synthetic', destination, ['synthetic passphrase']))
                self.assertNotIn('internal_override', export_wallet.call_args.kwargs)

    def test_setup_preserves_unrelated_actions_and_invalid_xml(self):
        spec=importlib.util.spec_from_file_location('vault_setup',SRC/'setup.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);uca=root/'.config/Thunar/uca.xml';uca.parent.mkdir(parents=True)
            uca.write_text('<actions><action><name>Unrelated</name><command>custom-command</command></action></actions>')
            module.setup(root);module.setup(root)
            text=uca.read_text()
            self.assertIn('custom-command',text)
            self.assertEqual(text.count('Create Encrypted Backup</name>'),1)
            self.assertEqual(text.count('Decrypt Encrypted Backup</name>'),1)
            uca.write_text('<broken')
            with self.assertRaises(Exception):module.setup(root)
            self.assertEqual(uca.read_text(),'<broken')

    def test_fixed_validation_messages_do_not_echo_secret(self):
        value='PRIVATE-TEST-MARKER\n'
        with self.assertRaises(backup.BackupError) as result:backup.validate_password(value)
        self.assertNotIn('PRIVATE-TEST-MARKER',str(result.exception))

if __name__=='__main__':unittest.main()
