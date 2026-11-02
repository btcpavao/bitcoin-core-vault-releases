#!/usr/bin/python3
"""Qt finish-flow tests; every Core, clipboard and power side effect is mocked."""
import importlib.util
from importlib.machinery import SourceFileLoader
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch, call

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'config/includes.chroot/usr/lib/core-vault'))
source = ROOT / 'config/includes.chroot/usr/local/bin/core-vault-finish'
spec = importlib.util.spec_from_loader('vault_finish', SourceFileLoader('vault_finish', str(source)))
finish = importlib.util.module_from_spec(spec)
spec.loader.exec_module(finish)
from PySide6.QtCore import Qt, QTimer, QEventLoop, QLockFile
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox


class FinishTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(['finish-tests'])
        cls.app.setQuitOnLastWindowClosed(False)
        cls.app.setStyle('Fusion')
        cls.app.setStyleSheet(finish.STYLE)

    def setUp(self):
        # A wiring regression must never call the real power helper or touch Core.
        self.power = patch.object(finish.subprocess, 'run', side_effect=AssertionError('Unexpected power call')).start()
        self.stop = patch.object(finish, 'stop_core', side_effect=AssertionError('Unexpected Core stop')).start()
        self.addCleanup(patch.stopall)
        self.windows = []

    def tearDown(self):
        for window in self.windows:
            window.reject()
            window.deleteLater()
        self.app.processEvents()

    def countdown(self, restart=False):
        clock = Mock(return_value=1000.0)
        window = finish.CountdownDialog(restart, clock=clock)
        self.windows.append(window)
        window.show()
        self.app.processEvents()
        return window, clock

    def test_five_minutes_monotonic_elapsed_time_and_expiry_once(self):
        window, clock = self.countdown()
        accepted = Mock()
        window.accepted.connect(accepted)
        self.assertEqual(window.remaining.text(), '05:00')
        clock.return_value = 1001
        window.tick()
        self.assertEqual(window.remaining.text(), '04:59')
        clock.return_value = 1299.2
        window.tick()
        self.assertEqual(window.remaining.text(), '00:01')
        self.assertEqual(window.result(), QDialog.Rejected)
        clock.return_value = 1300
        window.tick()
        self.assertEqual(window.remaining.text(), '00:00')
        self.assertEqual(window.result(), QDialog.Accepted)
        self.assertFalse(window.timer.isActive())
        window.tick()
        accepted.assert_called_once()

    def test_real_timer_refreshes_once_per_second(self):
        window, clock = self.countdown()
        self.assertEqual(window.timer.interval(), 1000)
        clock.return_value = 1001
        loop = QEventLoop()
        QTimer.singleShot(1150, loop.quit)
        loop.exec()
        self.assertEqual(window.remaining.text(), '04:59')

    def test_cancel_escape_and_close_stop_timer_without_power(self):
        for method in ('button', 'escape', 'close'):
            with self.subTest(method=method):
                window, clock = self.countdown()
                if method == 'button':
                    window.cancel_button.click()
                elif method == 'escape':
                    self.app.sendEvent(window, QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
                else:
                    window.close()
                self.assertEqual(window.result(), QDialog.Rejected)
                self.assertTrue(window.finished_once)
                self.assertFalse(window.timer.isActive())
                clock.return_value = 1500
                window.tick()
                self.assertEqual(window.result(), QDialog.Rejected)
        self.power.assert_not_called()
        self.stop.assert_not_called()

    def test_enter_does_not_skip_countdown(self):
        window, _ = self.countdown()
        self.assertIs(self.app.focusWidget(), window.cancel_button)
        for control in (window, window.now_button):
            self.app.sendEvent(control, QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Return, Qt.NoModifier))
            self.assertFalse(window.finished_once)
        self.assertFalse(window.now_button.isDefault())

    def test_explicit_now_accepts_and_stops_timer_for_both_actions(self):
        for restart, text in ((False, 'Shut down now'), (True, 'Restart now')):
            window, _ = self.countdown(restart)
            self.assertEqual(window.now_button.text(), text)
            window.now_button.click()
            self.assertEqual(window.result(), QDialog.Accepted)
            self.assertFalse(window.timer.isActive())

    def test_first_and_second_confirmation_cancellation_preserve_session(self):
        for answers in ([False], [True, False]):
            with patch.object(finish, 'confirmation', side_effect=answers) as confirm, \
                 patch.object(finish, 'CountdownDialog') as countdown, \
                 patch.object(finish, 'perform_finish') as perform:
                self.assertFalse(finish.finish_session(False))
                self.assertEqual(confirm.call_args_list, [call(False, i + 1) for i in range(len(answers))])
                countdown.assert_not_called()
                perform.assert_not_called()

    def test_cancel_countdown_after_two_confirmations_preserves_session(self):
        with patch.object(finish, 'confirmation', return_value=True) as confirm, \
             patch.object(finish, 'CountdownDialog') as countdown, \
             patch.object(finish, 'perform_finish') as perform:
            countdown.return_value.exec.return_value = QDialog.Rejected
            self.assertFalse(finish.finish_session(True))
            self.assertEqual(confirm.call_args_list, [call(True, 1), call(True, 2)])
            perform.assert_not_called()

    def test_power_action_only_after_both_confirmations_and_countdown(self):
        for restart in (False, True):
            order = []
            with patch.object(finish, 'confirmation', side_effect=lambda r, step: order.append(step) or True), \
                 patch.object(finish, 'CountdownDialog') as countdown, \
                 patch.object(finish, 'perform_finish', side_effect=lambda r: order.append(('finish', r))):
                countdown.return_value.exec.side_effect = lambda: order.append('countdown') or QDialog.Accepted
                self.assertTrue(finish.finish_session(restart))
                self.assertEqual(order, [1, 2, 'countdown', ('finish', restart)])

    def test_core_failure_preserves_clipboard_and_never_invokes_power(self):
        self.stop.side_effect = RuntimeError('Synthetic Core hang')
        with patch.object(finish, 'QApplication') as application:
            with self.assertRaisesRegex(RuntimeError, 'Synthetic Core hang'):
                finish.perform_finish(False)
            application.instance.assert_not_called()
        self.power.assert_not_called()

    def test_cleanup_order_and_exact_power_action(self):
        for restart, action in ((False, 'poweroff'), (True, 'reboot')):
            order = []
            self.stop.side_effect = lambda: order.append('stop')
            self.power.side_effect = lambda *a, **k: order.append('power')
            clipboard = Mock()
            clipboard.supportsSelection.return_value = True
            clipboard.clear.side_effect = lambda mode: order.append('clear')
            with patch.object(finish, 'QApplication') as application:
                application.instance.return_value.clipboard.return_value = clipboard
                finish.perform_finish(restart)
            self.assertEqual(order, ['stop', 'clear', 'clear', 'power'])
            self.power.assert_called_with(['/usr/bin/sudo', '-n', '/usr/local/sbin/core-vault-end-session', action],
                                          check=True, timeout=15)

    def test_confirmation_copy_safe_default_escape_and_explicit_button(self):
        for restart in (False, True):
            for stage in (1, 2):
                results = []
                def inspect_and_cancel():
                    dialog = self.app.activeModalWidget()
                    results.append((dialog.defaultButton().text(), dialog.escapeButton().text(), dialog.text()))
                    dialog.close()
                QTimer.singleShot(0, inspect_and_cancel)
                self.assertFalse(finish.confirmation(restart, stage))
                self.assertEqual(results[0][:2], ('Keep session open', 'Keep session open'))
                self.assertIn('RAM session', results[0][2])
                def choose_proceed():
                    dialog = self.app.activeModalWidget()
                    for button in dialog.buttons():
                        if dialog.buttonRole(button) == QMessageBox.AcceptRole:
                            button.click()
                            return
                    dialog.close()
                QTimer.singleShot(0, choose_proceed)
                self.assertTrue(finish.confirmation(restart, stage))

    def test_shared_lock_refuses_duplicate_and_releases_for_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'finish.lock')
            one, two = QLockFile(path), QLockFile(path)
            one.setStaleLockTime(0)
            two.setStaleLockTime(0)
            self.assertTrue(one.tryLock(0))
            try:
                self.assertFalse(two.tryLock(0))
            finally:
                one.unlock()
            self.assertTrue(two.tryLock(0))
            two.unlock()

    def test_no_backup_or_secret_prompt_dependency(self):
        text = source.read_text()
        for forbidden in ('get_verification_secrets', 'verify_export', 'read_receipts', 'wallet_files'):
            self.assertNotIn(forbidden, text)


if __name__ == '__main__':
    unittest.main(verbosity=2)
