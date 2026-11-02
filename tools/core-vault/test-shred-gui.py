#!/usr/bin/python3
"""Isolated GUI behavior checks; never invokes the real deletion engine.

Use an owned Xvfb display. Only synthetic plans and temporary lock fixtures are
used. The public entry-point/account/storage checks are mocked, so these tests
never inspect host wallets, profiles, physical disks, or the user's desktop.
"""
from __future__ import annotations

import argparse
import ast
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
import hashlib
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtCore import QObject, QPointF, Qt, Signal, QTimer
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QPlainTextEdit

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / 'config/includes.chroot/usr/local/bin/core-vault-shred'


def load_helper():
    loader = importlib.machinery.SourceFileLoader('vault_shred_gui_test_subject', str(HELPER))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


@dataclass
class Result:
    status: str
    completed_files: int
    completed_links: int
    message: str
    leftover_paths: list[str]
    completed_dirs: int = 0


class SyntheticWorker(QObject):
    progress = Signal(dict)
    done = Signal(object)

    def __init__(self):
        super().__init__()
        self.cancel_event = threading.Event()


def key(app, widget, code):
    app.sendEvent(widget, QKeyEvent(QKeyEvent.Type.KeyPress, code, Qt.KeyboardModifier.NoModifier))
    app.sendEvent(widget, QKeyEvent(QKeyEvent.Type.KeyRelease, code, Qt.KeyboardModifier.NoModifier))
    app.processEvents()


def mouse_click(app, widget):
    point = QPointF(widget.rect().center())
    app.sendEvent(widget, QMouseEvent(QMouseEvent.Type.MouseButtonPress, point,
                    Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                    Qt.KeyboardModifier.NoModifier))
    app.sendEvent(widget, QMouseEvent(QMouseEvent.Type.MouseButtonRelease, point,
                    Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
                    Qt.KeyboardModifier.NoModifier))
    app.processEvents()


def geometry(widget):
    g = widget.geometry()
    return [g.x(), g.y(), g.width(), g.height()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not os.environ.get('DISPLAY') or os.environ.get('DISPLAY') == ':0':
        raise RuntimeError('Run only on an owned Xvfb display, never the host desktop.')
    args.output.mkdir(parents=True, exist_ok=False)
    helper = load_helper()
    actual_engine = helper.load_engine()
    ResultClass = actual_engine.Result
    app = QApplication(['isolated-shred-gui-tests'])
    app.setStyle('Fusion')
    from PySide6.QtGui import QFont
    app.setFont(QFont('DejaVu Sans', 10))
    evidence = {
        'status': 'RUNNING',
        'test_source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'source_sha256': hashlib.sha256(HELPER.read_bytes()).hexdigest(),
        'engine_sha256': hashlib.sha256(Path(actual_engine.__file__).read_bytes()).hexdigest(),
        'display': os.environ['DISPLAY'],
        'screen_size': [app.primaryScreen().size().width(), app.primaryScreen().size().height()],
        'scope': 'Synthetic GUI plans, fake erase engine, temporary session-lock fixtures only.',
        'real_erase_called': False,
        'host_desktop_accessed': False,
        'checks': [],
        'screenshots': [],
    }
    failures = []

    def check(name, condition, detail=None):
        item = {'name': name, 'pass': bool(condition)}
        if detail is not None:
            item['detail'] = detail
        evidence['checks'].append(item)
        if not condition:
            failures.append(name)

    def show(dialog):
        dialog.move(70, 35)
        dialog.show()
        app.processEvents()
        app.processEvents()

    def screenshot(dialog, name):
        path = args.output / name
        if not dialog.grab().save(str(path), 'PNG'):
            raise RuntimeError('Could not save isolated dialog PNG.')
        evidence['screenshots'].append({
            'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'dialog_geometry': geometry(dialog), 'frame_geometry': [dialog.frameGeometry().x(), dialog.frameGeometry().y(),
                 dialog.frameGeometry().width(), dialog.frameGeometry().height()],
        })

    def fits(dialog):
        g = dialog.frameGeometry()
        screen = app.primaryScreen().availableGeometry()
        return (g.left() >= screen.left() and g.top() >= screen.top()
                and g.right() <= screen.right() and g.bottom() <= screen.bottom())

    strange = '/synthetic/wallets/<b>wallet</b>\\backup\n\x1b\t'
    long_path = '/synthetic/' + '/'.join(['wallet-' + ('a' * 230)] * 10) + '/wallet.dat'
    plan = SimpleNamespace(display_paths=[strange, long_path],
                           files_count=27, dirs_count=4, links_count=2,
                           total_bytes=12345678)

    confirm = helper.ConfirmDialog(plan)
    accepted = []
    confirm.accepted.connect(lambda: accepted.append(True))
    show(confirm)
    check('confirmation fits 800x600 with long literal paths', fits(confirm), geometry(confirm))
    check('initial focus is Cancel', app.focusWidget() is confirm.cancel_button)
    check('Cancel is default; delete is not default',
          confirm.cancel_button.isDefault() and not confirm.delete_button.isDefault())
    check('names are plain text with control characters escaped',
          confirm.paths.toPlainText().startswith(helper.plain(strange))
          and '<b>wallet</b>' in confirm.paths.toPlainText()
          and '\n\x1b\t' not in confirm.paths.toPlainText())
    check('warning states permanence and SSD USB backup limitations',
          'no Undo' in helper.EXPLANATION and 'SSDs' in helper.LIMITS
          and 'USB' in helper.LIMITS and 'Backups' in helper.LIMITS
          and 'snapshots' in helper.LIMITS and 'may remain' in helper.LIMITS)
    check('all ordinary labels force plain text',
          all(widget.textFormat() == Qt.TextFormat.PlainText
              for widget in confirm.findChildren(QLabel)))
    screenshot(confirm, 'confirmation-long-literal-paths.png')
    key(app, app.focusWidget() or confirm, Qt.Key.Key_Return)
    check('opening confirmation then Enter cancels without acceptance',
          not accepted and not confirm.isVisible() and confirm.result() == QDialog.DialogCode.Rejected)

    confirm = helper.ConfirmDialog(plan)
    accepted = []
    confirm.accepted.connect(lambda: accepted.append(True))
    show(confirm)
    key(app, confirm, Qt.Key.Key_Escape)
    check('Escape cancels confirmation without acceptance',
          not accepted and not confirm.isVisible() and confirm.result() == QDialog.DialogCode.Rejected)

    confirm = helper.ConfirmDialog(plan)
    accepted = []
    confirm.accepted.connect(lambda: accepted.append(True))
    show(confirm)
    mouse_click(app, confirm.delete_button)
    check('explicit delete mouse action accepts', len(accepted) == 1
          and not confirm.isVisible() and confirm.result() == QDialog.DialogCode.Accepted)

    for action in ('Stop', 'Escape', 'WindowClose'):
        worker = SyntheticWorker()
        progress = helper.ProgressDialog(worker, plan)
        show(progress)
        worker.progress.emit({'phase': 'overwriting', 'path': strange,
                              'completed_files': 3, 'total_files': 27})
        app.processEvents()
        check(action + ' progress text is literal',
              progress.current.toPlainText() == helper.plain(strange)
              and progress.current.isReadOnly())
        if action == 'Stop':
            mouse_click(app, progress.stop_button)
        elif action == 'Escape':
            key(app, progress, Qt.Key.Key_Escape)
        else:
            progress.close()
            app.processEvents()
        check(action + ' requests cancellation and waits for worker',
              worker.cancel_event.is_set() and progress.isVisible() and progress.result is None
              and not progress.stop_button.isEnabled())
        worker.done.emit(ResultClass('cancelled', 3, 0, 'Synthetic cancelled result.', []))
        app.processEvents()
        check(action + ' closes only after worker result',
              not progress.isVisible() and progress.result.status == 'cancelled')

    worker = SyntheticWorker()
    progress = helper.ProgressDialog(worker, plan)
    show(progress)
    worker.progress.emit({'phase': 'overwriting', 'path': long_path,
                          'completed_files': 3, 'total_files': 27})
    app.processEvents()
    app.processEvents()
    check('progress fits 800x600 even for long current path', fits(progress), geometry(progress))
    screenshot(progress, 'progress-long-current-path.png')
    check('long current path remains complete and scrollable',
          progress.current.toPlainText() == helper.plain(long_path)
          and progress.current.isReadOnly() and progress.current.verticalScrollBar().maximum() > 0)
    progress.current.verticalScrollBar().setValue(progress.current.verticalScrollBar().maximum())
    app.processEvents()
    check('long current path can scroll to final basename',
          progress.current.cursorForPosition(progress.current.viewport().rect().bottomLeft()).block().text().endswith('/wallet.dat')
          and progress.current.verticalScrollBar().value() == progress.current.verticalScrollBar().maximum())
    screenshot(progress, 'progress-long-current-path-scrolled-to-basename.png')
    worker.done.emit(ResultClass('cancelled', 3, 0, 'Synthetic cancelled result.', []))
    app.processEvents()

    for raises in (False, True):
        class FakeEngine:
            Result = ResultClass

            @staticmethod
            def erase(received_plan, cancel_event, callback):
                check('Worker passed exact plan and cancellation token ' + str(raises),
                      received_plan is plan and isinstance(cancel_event, threading.Event))
                if raises:
                    raise RuntimeError('<b>synthetic engine error</b>\n')
                callback({'phase': 'removing', 'path': strange, 'completed_files': 27})
                return ResultClass('completed', 27, 2, 'Synthetic completion.', [], 4)
        thread = helper.Worker(FakeEngine, plan)
        results = []
        thread.done.connect(results.append)
        thread.start()
        limit = time.monotonic() + 3
        while (thread.isRunning() or not results) and time.monotonic() < limit:
            app.processEvents()
            time.sleep(0.01)
        thread.wait(1000)
        app.processEvents()
        check('Worker returns safe synthetic result ' + str(raises),
              len(results) == 1 and results[0].status == ('error' if raises else 'completed'))
        if results and raises:
            check('unexpected Worker error is escaped and has no delete fallback',
                  'synthetic engine error' in results[0].message
                  and results[0].completed_files == 0 and results[0].leftover_paths == [])

    check('actual engine Result supports GUI error fallback API',
          ResultClass(status='error', completed_files=0, completed_links=0,
                      message='Synthetic error', leftover_paths=[]).completed_dirs == 0)

    original_confirm = helper.ConfirmDialog
    for action in ('Enter', 'Escape', 'ExplicitDelete'):
        calls = []
        messages = []
        class SyntheticMainEngine:
            Result = ResultClass

            @staticmethod
            @contextmanager
            def build_plan(paths):
                calls.append(('plan', paths))
                yield plan

            @staticmethod
            def erase(received_plan, cancel_event, callback):
                calls.append(('erase', received_plan is plan))
                return ResultClass('completed', 27, 2, 'Synthetic completion.', [], 4)

        def confirmation(received_plan):
            dialog = original_confirm(received_plan)
            def activate():
                if action == 'ExplicitDelete':
                    mouse_click(app, dialog.delete_button)
                else:
                    key(app, dialog.cancel_button if action == 'Enter' else dialog,
                        Qt.Key.Key_Return if action == 'Enter' else Qt.Key.Key_Escape)
            QTimer.singleShot(0, activate)
            return dialog

        with tempfile.TemporaryDirectory(prefix='main-fixture-', dir=args.output) as temp:
            lock_fd = os.open(Path(temp) / 'synthetic-lock', os.O_CREAT | os.O_RDWR, 0o600)
            with ExitStack() as stack:
                stack.enter_context(patch.object(sys, 'argv', ['core-vault-shred', '/synthetic/wallet.dat']))
                stack.enter_context(patch.object(helper, 'QApplication', return_value=app))
                stack.enter_context(patch.object(helper, 'vault_paths', return_value=['/synthetic/wallet.dat']))
                stack.enter_context(patch.object(helper, 'session_lock', return_value=lock_fd))
                stack.enter_context(patch.object(helper, 'load_engine', return_value=SyntheticMainEngine))
                stack.enter_context(patch.object(helper, 'ConfirmDialog', side_effect=confirmation))
                stack.enter_context(patch.object(helper, 'message', side_effect=lambda *args: messages.append(args)))
                code = helper.main()
            check('main ' + action + ' reaches erase only after explicit consent',
                  code == 0 and sum(1 for c in calls if c[0] == 'erase') ==
                  (1 if action == 'ExplicitDelete' else 0) and not messages)
            try:
                os.fstat(lock_fd)
            except OSError:
                check('main ' + action + ' closes its session lock', True)
            else:
                os.close(lock_fd)
                check('main ' + action + ' closes its session lock', False)

    long_error = 'Deletion stopped. Remaining items:\n' + '\n'.join(
        '/synthetic/' + str(i) + '/' + 'a' * 220 + '/wallet.dat' for i in range(20))
    def inspect_error_message():
        dialog = app.activeModalWidget()
        fields = dialog.findChildren(QPlainTextEdit)
        check('incomplete result dialog fits 800x600', fits(dialog), geometry(dialog))
        check('long incomplete result remains complete and read-only scrollable',
              len(fields) == 1 and fields[0].isReadOnly()
              and fields[0].toPlainText() == long_error
              and fields[0].verticalScrollBar().maximum() > 0)
        screenshot(dialog, 'incomplete-result-long-paths.png')
        if fields:
            fields[0].verticalScrollBar().setValue(fields[0].verticalScrollBar().maximum())
            app.processEvents()
            check('remaining list can scroll to last item',
                  fields[0].verticalScrollBar().value() == fields[0].verticalScrollBar().maximum()
                  and fields[0].cursorForPosition(fields[0].viewport().rect().bottomLeft()).block().text().endswith('/wallet.dat'))
            screenshot(dialog, 'incomplete-result-long-paths-scrolled-to-last.png')
        dialog.accept()
    QTimer.singleShot(0, inspect_error_message)
    helper.message('Deletion incomplete', long_error)

    account = SimpleNamespace(pw_name='vault', pw_uid=1000, pw_dir='/home/vault')
    def account_call(uid=1000, euid=1000, acct=account, storage=0, values=None, home='/home/vault'):
        with ExitStack() as stack:
            stack.enter_context(patch.object(helper.os, 'getuid', return_value=uid))
            stack.enter_context(patch.object(helper.os, 'geteuid', return_value=euid))
            stack.enter_context(patch.object(helper.pwd, 'getpwuid', return_value=acct))
            stack.enter_context(patch.object(helper.Path, 'home', return_value=Path(home)))
            proc = stack.enter_context(patch.object(helper.subprocess, 'run',
                         return_value=SimpleNamespace(returncode=storage)))
            try:
                result = helper.vault_paths(values or ['/home/vault/.bitcoin/wallets/synthetic/wallet.dat'])
                return True, result, proc.call_args
            except Exception as exc:
                return False, str(exc), proc.call_args

    valid, result, call = account_call()
    check('Vault account uses exact session storage guard',
          valid and call.args[0] == ['/usr/local/bin/core-vault-storage-check', '--session']
          and call.kwargs['timeout'] == 15 and call.kwargs['capture_output'] is True)
    for name, kwargs in [
        ('root rejected', {'euid': 0}),
        ('other account rejected', {'acct': SimpleNamespace(pw_name='other', pw_uid=1000, pw_dir='/home/vault')}),
        ('other account UID rejected', {'acct': SimpleNamespace(pw_name='vault', pw_uid=1001, pw_dir='/home/vault')}),
        ('wrong home rejected', {'home': '/synthetic/home'}),
        ('unready storage rejected', {'storage': 1}),
        ('relative path rejected', {'values': ['relative/wallet.dat']}),
        ('parent traversal rejected', {'values': ['/home/vault/../wallet.dat']}),
    ]:
        valid, detail, call = account_call(**kwargs)
        check(name, not valid, detail)

    with tempfile.TemporaryDirectory(prefix='shred-gui-lock-fixture-', dir=args.output) as temp:
        runtime = Path(temp)
        real_path = helper.Path
        def fixture_path(value):
            return runtime if str(value) == '/run/user/1000' else real_path(value)
        with patch.object(helper, 'Path', side_effect=fixture_path):
            fd = helper.session_lock()
            try:
                try:
                    extra = helper.session_lock()
                except RuntimeError as exc:
                    check('concurrent session lock refused', 'already open' in str(exc))
                else:
                    os.close(extra)
                    check('concurrent session lock refused', False)
            finally:
                os.close(fd)
            lock = runtime / 'core-vault-shred.lock'
            check('new lock is private regular owned file', lock.stat().st_mode & 0o777 == 0o600)
            lock.unlink()
            target = runtime / 'synthetic-target'
            target.write_text('must remain untouched')
            lock.symlink_to(target)
            try:
                bad = helper.session_lock()
            except OSError:
                check('symlink session lock refused without modifying target',
                      target.read_text() == 'must remain untouched')
            else:
                os.close(bad)
                check('symlink session lock refused without modifying target', False)

    source = HELPER.read_text()
    tree = ast.parse(source)
    forbidden = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in ('eval', 'exec'):
                forbidden.append(node.func.id)
            if isinstance(node.func, ast.Attribute) and node.func.attr in ('system', 'popen', 'unlink', 'remove', 'rmdir'):
                forbidden.append(node.func.attr)
            for kw in node.keywords:
                if kw.arg == 'shell' and isinstance(kw.value, ast.Constant) and kw.value.value:
                    forbidden.append('shell=True')
    check('UI has no shell invocation or ordinary-delete fallback', not forbidden, forbidden)
    check('helper source unchanged throughout GUI checks',
          hashlib.sha256(HELPER.read_bytes()).hexdigest() == evidence['source_sha256'])
    check('engine source unchanged throughout API-only checks',
          hashlib.sha256(Path(actual_engine.__file__).read_bytes()).hexdigest() == evidence['engine_sha256'])
    evidence['status'] = 'PASS' if not failures else 'FAIL'
    evidence['failures'] = failures
    proof = args.output / 'gui-behavior-proof.json'
    proof.write_text(json.dumps(evidence, indent=2) + '\n')
    print(json.dumps({'status': evidence['status'], 'checks': len(evidence['checks']),
                      'failures': failures, 'proof': str(proof)}, indent=2))
    return 0 if not failures else 1


if __name__ == '__main__':
    raise SystemExit(main())
