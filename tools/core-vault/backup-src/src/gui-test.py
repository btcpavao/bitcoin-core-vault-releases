#!/usr/bin/python3
"""Offscreen Qt tests: layer fields, validation, focus, cancellation and layout."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import unittest
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from password_dialog import ensure_app, PassphraseDialog
from recovery_dialog import RecoveryDialog
from backup import validate_password, BackupError

def validate(value):
    try:
        validate_password(value)
    except BackupError as exc:
        raise ValueError(str(exc)) from None

class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=ensure_app()

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.window=PassphraseDialog(validate,destination=self.root/'backup.gpg',items=[self.root/'wallet.dat'])
        self.window.show();self.app.processEvents()

    def tearDown(self):
        self.window.reject();self.window.deleteLater();self.app.processEvents();self.tmp.cleanup()

    def fill(self,count=1):
        while len(self.window.rows)<count:self.window.add_row()
        for i,row in enumerate(self.window.rows):
            row.password.setText('synthetic independent '+str(i))
            row.confirm.setText('synthetic independent '+str(i))
        self.app.processEvents()

    def test_empty_mismatch_duplicates_and_valid(self):
        self.assertFalse(self.window.create_button.isEnabled())
        self.fill(3);self.assertTrue(self.window.create_button.isEnabled())
        self.window.rows[1].confirm.setText('wrong');self.assertFalse(self.window.create_button.isEnabled())
        self.fill(3)
        for edit in (self.window.rows[1].password,self.window.rows[1].confirm):edit.setText('synthetic independent 0')
        self.assertFalse(self.window.create_button.isEnabled())

    def test_ten_layers_keyboard_names_and_removal(self):
        self.fill(10)
        self.assertTrue(self.window.create_button.isEnabled())
        for row in self.window.rows:
            self.assertTrue(row.password.accessibleName());self.assertTrue(row.confirm.accessibleName())
        first=self.window.rows[0];first.password.setFocus()
        self.app.sendEvent(first.password,QKeyEvent(QKeyEvent.Type.KeyPress,Qt.Key.Key_Return,Qt.KeyboardModifier.NoModifier))
        self.assertIs(self.app.focusWidget(),first.confirm)
        self.window.remove_row(self.window.rows[4])
        self.assertEqual(len(self.window.rows),9)
        self.assertEqual(self.window.rows[4].title.text(),'Passphrase 5')

    def test_show_hide_and_cancel_clear(self):
        self.fill()
        row=self.window.rows[0]
        row.show_secret.setChecked(True)
        self.assertEqual(row.password.echoMode(),row.password.EchoMode.Normal)
        self.window.reject()
        self.assertIsNone(self.window.value)
        self.assertFalse(row.password.text());self.assertFalse(row.confirm.text())

    def test_accept_preserves_order_and_clears_widgets(self):
        self.fill(3);self.window.accept()
        self.assertEqual(self.window.value,['synthetic independent '+str(i) for i in range(3)])
        self.assertEqual(self.window.destination_value,self.root/'backup.tar.gpg.gpg.gpg')
        self.assertTrue(all(not row.password.text() for row in self.window.rows))
        self.window.value=None

    def test_existing_and_relative_destination(self):
        self.fill()
        self.window.destination.setText('relative')
        self.assertFalse(self.window.create_button.isEnabled())
        (self.root/'exists.tar.gpg').write_bytes(b'existing')
        self.window.destination.setText(str(self.root/'exists.gpg'))
        self.assertFalse(self.window.create_button.isEnabled())

    def test_small_layout_keeps_actions_visible(self):
        self.fill(10)
        self.window.resize(640,600);self.app.processEvents()
        button=self.window.create_button
        point=button.mapTo(self.window,button.rect().bottomRight())
        self.assertLess(point.y(),self.window.height())
        self.assertLess(point.x(),self.window.width())
        self.assertGreater(self.window.scroll.verticalScrollBar().maximum(),0)

    def test_recovery_any_order_more_secrets_and_default_safe_mode(self):
        window=RecoveryDialog(validate,self.root,source=self.root/'backup.gpg',
                              previous=['synthetic second','synthetic first'])
        self.assertFalse(window.ordinary.isChecked())
        self.assertEqual(len(window.rows),2)
        self.assertTrue(window.create_button.isEnabled())
        self.assertIsNone(window.rows[0].confirm)
        window.destination.setText('../outside')
        self.assertFalse(window.create_button.isEnabled())
        window.reject();window.deleteLater()

    def test_one_label_numbering_and_return_to_single_in_both_modes(self):
        from PySide6.QtWidgets import QLabel
        recovery=RecoveryDialog(validate,self.root,source=self.root/'backup.gpg')
        try:
            for window in (self.window,recovery):
                row=window.rows[0]
                self.assertEqual(row.title.text(),'Passphrase')
                self.assertEqual(row.password.accessibleName(),'Passphrase')
                self.assertEqual(row.show_secret.text(),'Show')
                self.assertEqual([l.text() for l in row.findChildren(QLabel) if 'passphrase' in l.text().lower()],['Passphrase'])
                window.add_row()
                self.assertEqual([r.title.text() for r in window.rows],['Passphrase 1','Passphrase 2'])
                window.remove_row(window.rows[0])
                self.assertEqual(window.rows[0].title.text(),'Passphrase')
                self.assertEqual(window.rows[0].password.accessibleName(),'Passphrase')
        finally:
            recovery.reject();recovery.deleteLater()

    def test_dark_result_dialog(self):
        from message_dialog import ResultDialog
        for error in (False,True):
            window=ResultDialog('<b>synthetic text</b>',error=error,operation='recovery')
            window.show();self.app.processEvents()
            self.assertEqual(window.body.textFormat(),Qt.TextFormat.PlainText)
            self.assertFalse(window.icon_label.pixmap().isNull())
            self.assertIn('#111111',window.styleSheet())
            window.accept();window.deleteLater()

if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(GuiTests))
    if result.wasSuccessful():print('VAULT MULTILAYER QT DIALOG TESTS PASSED')
    raise SystemExit(0 if result.wasSuccessful() else 1)
