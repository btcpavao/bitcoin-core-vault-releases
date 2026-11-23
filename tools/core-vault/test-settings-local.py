#!/usr/bin/python3
"""Vault local Settings checks; hardware calls and privileged time actions mocked."""
import copy
from datetime import datetime, timezone
import io
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import runpy
import stat
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / 'config/includes.chroot/usr/lib/core-vault/settings'
sys.path.insert(0, str(LIB))
import vault_input
import vault_pointer
import vault_input_guard
import vault_time
from PySide6.QtWidgets import QApplication, QWidget, QPushButton, QDialog
from PySide6.QtCore import QPoint, QRect
import vault_settings

APP = QApplication.instance() or QApplication(['vault-settings-test'])
APP.setQuitOnLastWindowClosed(False)


class TimeValidation(unittest.TestCase):
    def test_manual_timestamp_is_timezone_aware_and_no_network_field_accepted(self):
        name, epoch = vault_time.validate_request({'timezone': 'Europe/Zagreb', 'local_time': '2026-11-23 12:30:00'})
        self.assertEqual(name, 'Europe/Zagreb')
        self.assertEqual(datetime.fromtimestamp(epoch, timezone.utc).hour, 11)
        for values in (
                {'timezone': '../etc/passwd', 'local_time': '2026-11-23 12:30:00'},
                {'timezone': 'UTC', 'local_time': '2026-11-23 12:30:00', 'automatic': True},
                {'timezone': 'Europe/Zagreb', 'local_time': '2026-10-25 02:30:00'},
                {'timezone': 'Europe/Zagreb', 'local_time': '2026-03-29 02:30:00'}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                vault_time.validate_request(values)

    def test_invalid_input_has_no_privileged_side_effect(self):
        with patch.object(vault_time, '_prepare_state') as state, \
                patch.object(vault_time.time, 'clock_settime') as clock:
            with self.assertRaises(ValueError):
                vault_time.apply_settings({'timezone': 'UTC', 'local_time': 'invalid'})
            state.assert_not_called(); clock.assert_not_called()

    def test_parser_rejects_duplicates_and_oversize(self):
        for raw in (b'{"timezone":"UTC","timezone":"UTC"}', b'x'*4097):
            with self.assertRaises(ValueError):
                vault_time.read_request(io.BytesIO(raw))

    def test_localtime_symlink_refused_before_bind(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'localtime'; path.symlink_to('/usr/share/zoneinfo/UTC')
            with patch.object(vault_time, 'LOCALTIME', path), \
                    patch.object(vault_time.subprocess, 'run') as run:
                with self.assertRaises(ValueError):
                    vault_time._prepare_timezone(b'not-used')
                run.assert_not_called()

    def test_private_umask_keeps_timezone_readable_and_lock_private(self):
        # Only root identity and privileged operations are simulated. Creation,
        # chmod/fchmod and the restrictive umask use real isolated files.
        class RootFixturePath(type(Path())):
            def lstat(self):
                values = list(super().lstat()); values[4] = 0
                return os.stat_result(values)

        with tempfile.TemporaryDirectory() as directory:
            state = RootFixturePath(directory) / 'state'
            old_mask = os.umask(0o077)
            try:
                with patch.object(vault_time, 'STATE', state), \
                        patch.object(vault_time.subprocess, 'run', return_value=Mock(stdout='tmpfs\n')):
                    vault_time._prepare_state()
                    self.assertEqual(stat.S_IMODE(state.stat().st_mode), 0o755)
                    for name in ('localtime', 'zone'):
                        path = state / name
                        vault_time._write_root_file(path, b'non-secret timezone fixture')
                        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o644)
                        path.chmod(0o600)
                        vault_time._write_root_file(path, b'reapplied timezone fixture')
                        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o644)
                    with patch.object(vault_time.os, 'geteuid', return_value=0), \
                            patch.object(vault_time, '_prepare_timezone'), \
                            patch.object(vault_time.time, 'clock_settime'):
                        vault_time.apply_settings({'timezone': 'Etc/UTC', 'local_time': '2026-11-23 12:30:00'})
                    self.assertEqual(stat.S_IMODE((state/'lock').stat().st_mode), 0o600)
            finally:
                os.umask(old_mask)

    def test_timezone_modes_not_relaxed_for_unsafe_paths(self):
        class UserFixturePath(type(Path())):
            def lstat(self):
                values = list(super().lstat()); values[4] = 12345
                return os.stat_result(values)

        with tempfile.TemporaryDirectory() as directory:
            state = UserFixturePath(directory) / 'state'; state.mkdir()
            with patch.object(vault_time, 'STATE', state), \
                    patch.object(vault_time.os, 'chmod') as chmod:
                with self.assertRaises(ValueError):
                    vault_time._prepare_state()  # Unprivileged owner is rejected.
                chmod.assert_not_called()
            target = Path(directory) / 'target'; target.write_bytes(b'unchanged')
            link = Path(directory) / 'link'; link.symlink_to(target)
            with patch.object(vault_time.os, 'fchmod') as fchmod:
                with self.assertRaises(ValueError):
                    vault_time._write_root_file(link, b'changed')
                fchmod.assert_not_called()
            self.assertEqual(target.read_bytes(), b'unchanged')


class InputPolicy(unittest.TestCase):
    def test_vault_adapter_has_no_system_keyboard_writer(self):
        self.assertFalse(hasattr(vault_input, 'apply_system_layout'))
        self.assertNotIn('/etc/', str(vault_input.PREFS))
        self.assertIn('bitcoin-core-vault', str(vault_pointer.PREFS))
        with patch.object(vault_input, 'require_ram_home', side_effect=ValueError('RAM required')), \
                patch.object(vault_input, 'apply_keyboard') as apply:
            with self.assertRaises(ValueError):
                vault_input.apply_local_layout({'model':'pc105','layout':'us','variant':'','options':''}, vault_input.DEFAULTS['keyboard'])
            apply.assert_not_called()

    def test_regular_host_home_is_not_an_implicit_persistence_fallback(self):
        with patch.object(vault_input_guard.Path, 'home', return_value=Path('/home/someone')), \
                patch.object(vault_input_guard.subprocess, 'run') as run:
            with self.assertRaises(ValueError):
                vault_input_guard.require_ram_home()
            run.assert_not_called()

    def test_preference_path_cannot_escape_ram_home(self):
        from types import SimpleNamespace
        with patch.object(vault_input_guard,'require_ram_home'), \
                patch.object(vault_input_guard.os,'stat') as stat:
            for path in ('/tmp/input.json','/home/vault/../outside.json'):
                with self.assertRaises(ValueError):
                    vault_input_guard.require_ram_path(path)
            stat.assert_not_called()
        with patch.object(vault_input_guard,'require_ram_home'), \
                patch.object(vault_input_guard.Path,'is_symlink',return_value=False), \
                patch.object(vault_input_guard.Path,'exists',return_value=True), \
                patch.object(vault_input_guard.os,'stat',side_effect=[SimpleNamespace(st_dev=3),SimpleNamespace(st_dev=4)]):
            with self.assertRaises(ValueError):
                vault_input_guard.require_ram_path('/home/vault/.config/input.json')


class SettingsUI(unittest.TestCase):
    def test_four_local_categories_and_independent_single_instance(self):
        home = QWidget()
        menu = vault_settings.open_window(home, 'settings', lambda: vault_settings.VaultSettingsDialog(home))
        try:
            APP.processEvents()
            again = vault_settings.open_window(home, 'settings', lambda: self.fail('duplicate Settings'))
            self.assertIs(menu, again)
            self.assertFalse(menu.isModal())
            self.assertEqual(menu.card_order, ('Display Settings','Keyboard and Mouse','Date & Time','Backup and Restore'))
            self.assertFalse(any('Network' in name or 'Bluetooth' in name or 'Updates' in name for name in menu.cards))
            for width, height in ((760, 550),(960,555)):
                menu.resize(width,height)
                for _ in range(4): APP.processEvents()
                self.assertEqual(menu.scroll.verticalScrollBar().maximum(),0)
                for card in menu.cards.values():
                    pos=card.mapTo(menu,QPoint())
                    self.assertGreaterEqual(pos.x(),0)
                    self.assertLessEqual(pos.x()+card.width(),menu.width())
                    self.assertLessEqual(pos.y()+card.height(),menu.exit_button.y())
            with patch.object(vault_pointer,'get_devices',return_value=[]):
                dialog=menu.keyboard();APP.processEvents()
                self.assertFalse(dialog.isModal())
                self.assertEqual(dialog.save.text(),'Apply for this session')
                self.assertNotIn('Bluetooth Devices', ' '.join(label.text() for label in dialog.findChildren(__import__('PySide6.QtWidgets',fromlist=['QLabel']).QLabel)))
                dialog.close_button.click();APP.processEvents()
                self.assertTrue(menu.isVisible())
            backups=menu.backups();APP.processEvents()
            with patch.object(vault_settings.subprocess,'Popen') as launch:
                next(b for b in backups.findChildren(QPushButton) if b.text()=='Wallet Backup').click()
                launch.assert_called_once_with(['/usr/local/bin/core-vault-wallet-backup'],start_new_session=True)
            backups.reject();APP.processEvents()
        finally:
            menu.reject();home.deleteLater();APP.processEvents()

    def test_home_footer_settings_restart_shutdown_order(self):
        source=ROOT/'config/includes.chroot/usr/local/bin/core-vault-home'
        assets=ROOT/'config/includes.chroot/usr/share/core-vault'
        with patch.object(sys,'argv',[str(source),'--self-test','--assets',str(assets)]):
            namespace=runpy.run_path(str(source),run_name='settings_home_fixture')
        home=namespace['VaultHome']();home._test_size=(800,600);home.fit_screen();home.show()
        try:
            for _ in range(6):APP.processEvents()
            controls=(home.settings_button,home.restart_button,home.shutdown_button)
            self.assertEqual([c.accessibleName() for c in controls],['Settings','Restart','Finish & Shut Down'])
            self.assertTrue(all(c.width()==48 and c.height()==48 and not c.icon().isNull() for c in controls))
            self.assertLess(controls[0].x(),controls[1].x());self.assertLess(controls[1].x(),controls[2].x())
            self.assertEqual(len({c.mapTo(home,QPoint()).y() for c in controls}),1)
            child=QDialog();child.resize(980,660);child.move(1900,900);child.show();APP.processEvents()
            home.recover_windows([QRect(0,0,800,560)]);APP.processEvents()
            self.assertLessEqual(child.frameGeometry().right(),799)
            self.assertLessEqual(child.frameGeometry().bottom(),559)
            self.assertGreaterEqual(child.frameGeometry().left(),0)
            child.close();child.deleteLater()
            from types import SimpleNamespace
            module=SimpleNamespace(launch_environment=lambda:{'GDK_SCALE':'2','GDK_DPI_SCALE':'0.5'})
            with patch.dict(sys.modules,{'core_display':module}), \
                    patch.dict(os.environ,{'GDK_SCALE':'1','QT_SCALE_FACTOR':'2'}):
                home.refresh_launch_environment()
                self.assertEqual(os.environ['GDK_SCALE'],'2')
                self.assertNotIn('QT_SCALE_FACTOR',os.environ)
        finally:
            home.reaper.stop();home.notice_timer.stop();home.hide();home.deleteLater();APP.processEvents()


if __name__=='__main__':
    unittest.main(verbosity=2)
