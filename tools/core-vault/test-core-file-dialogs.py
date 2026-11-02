#!/usr/bin/python3
"""Exercise file chooser places on synthetic profiles, never a real wallet."""
from __future__ import annotations
import argparse
import hashlib
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import tempfile

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QByteArray, QSettings, Qt
from PySide6.QtWidgets import QApplication, QFileDialog, QListView

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / 'config/includes.chroot/usr/local/bin/core-vault-core-file-dialogs'


def load():
    loader = importlib.machinery.SourceFileLoader('vault_core_file_dialogs', str(HELPER))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def profile(root):
    home, runtime = root / 'home', root / 'runtime'
    config = home / '.config'
    for path in (config, home / '.bitcoin', home / 'Private Workspace', runtime):
        path.mkdir(parents=True, mode=0o700, exist_ok=True)
        path.chmod(0o700)
    (home / '.bitcoin/synthetic-folder').mkdir(mode=0o700)
    (home / 'Private Workspace/synthetic.dat').write_bytes(b'NOT A WALLET\n')
    return home, runtime, config


def expect_error(call):
    try:
        call()
    except (OSError, RuntimeError, ValueError):
        return
    raise AssertionError('Expected refusal of an unexpected managed object.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--json', type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    module = load()
    with tempfile.TemporaryDirectory(prefix='vault-core-file-dialogs-test-') as temporary:
        root = Path(temporary)
        home, runtime, config = profile(root / 'fresh')
        os.environ.update(HOME=str(home), XDG_CONFIG_HOME=str(config), XDG_RUNTIME_DIR=str(runtime))
        app = QApplication([])
        module.configure(home, runtime, config)
        path = config / 'QtProject.conf'
        seeded = module.settings_at(path)
        seeded.setValue('Unrelated/opaque', QByteArray(b'opaque\x00bytes'))
        seeded.setValue('Unrelated/list', ['keep, comma', 'keep space'])
        seeded.setValue('Unrelated/integer', 42)
        seeded.sync()
        initial = path.read_bytes()
        assert path.stat().st_mode & 0o777 == 0o600
        module.configure(home, runtime, config)
        assert path.read_bytes() == initial
        dialog = QFileDialog()
        dialog.setOption(QFileDialog.DontUseNativeDialog)
        dialog.show()
        app.processEvents()
        sidebar = dialog.findChild(QListView, 'sidebar')
        model = sidebar.model()
        labels = [model.index(i, 0).data(Qt.DisplayRole) for i in range(model.rowCount())]
        assert labels == ['Bitcoin Core', 'Private Workspace'], labels
        assert sidebar.width() >= 175
        alias = runtime / module.ALIAS_DIR / 'Bitcoin Core'
        dialog.setDirectory(str(alias))
        app.processEvents()
        assert dialog.directory().exists('synthetic-folder')
        dialog.setDirectory(str(home / 'Private Workspace'))
        app.processEvents()
        assert dialog.directory().exists('synthetic.dat')
        dialog.reject()
        del dialog
        app.processEvents()
        # Native Qt serializes URLs with decoded spaces; accept its output too.
        module.check(home, runtime, config)
        native_saved = path.read_bytes()
        native_settings = module.settings_at(path)
        native_values = {k: native_settings.value(k) for k in native_settings.allKeys()}
        assert native_values['Unrelated/opaque'] == QByteArray(b'opaque\x00bytes')
        assert native_values['Unrelated/list'] == ['keep, comma', 'keep space']
        assert int(native_values['Unrelated/integer']) == 42
        module.configure(home, runtime, config)
        assert path.read_bytes() == native_saved
        reloaded = module.settings_at(path)
        assert {k: reloaded.value(k) for k in reloaded.allKeys()} == native_values

        h, r, c = profile(root / 'existing')
        custom = h / 'USB Backup, (sample)'
        custom.mkdir()
        settings = module.settings_at(c / 'QtProject.conf')
        settings.setValue(module.KEY, ['file:', h.as_uri(), (h / '.bitcoin').as_uri(),
                                      custom.as_uri(), custom.as_uri()])
        settings.setValue(module.WIDTH, 245)
        settings.setValue('FileDialog/history', [custom.as_uri()])
        settings.setValue('FileDialog/viewMode', 'Detail')
        settings.setValue('Unrelated/opaque', QByteArray(b'opaque\x00bytes'))
        settings.setValue('Unrelated/list', ['keep, comma', 'keep space'])
        settings.sync()
        before = (c / 'QtProject.conf').read_bytes()
        wanted = {k: settings.value(k) for k in settings.allKeys() if k != module.KEY}
        module.configure(h, r, c)
        after = module.settings_at(c / 'QtProject.conf')
        assert module.urls(after.value(module.KEY)) == [
            (r / module.ALIAS_DIR / 'Bitcoin Core').as_uri(),
            (h / 'Private Workspace').as_uri(), custom.as_uri()]
        assert {k: after.value(k) for k in wanted} == wanted
        assert (c / module.BACKUP).read_bytes() == before
        saved = (c / 'QtProject.conf').read_bytes()
        module.configure(h, r, c)
        assert (c / 'QtProject.conf').read_bytes() == saved
        assert (c / module.BACKUP).read_bytes() == before

        h, r, c = profile(root / 'narrow-sidebar')
        settings = module.settings_at(c / 'QtProject.conf')
        settings.setValue(module.WIDTH, 77)
        settings.setValue('FileDialog/viewMode', 'Detail')
        settings.setValue('Unrelated/list', ['keep, comma', 'keep space'])
        settings.sync()
        module.configure(h, r, c)
        after = module.settings_at(c / 'QtProject.conf')
        assert int(after.value(module.WIDTH)) == 180
        assert after.value('FileDialog/viewMode') == 'Detail'
        assert after.value('Unrelated/list') == ['keep, comma', 'keep space']
        saved = (c / 'QtProject.conf').read_bytes()
        module.configure(h, r, c)
        assert (c / 'QtProject.conf').read_bytes() == saved

        h, r, c = profile(root / 'conflict')
        d = r / module.ALIAS_DIR
        d.mkdir(mode=0o700)
        (d / 'Bitcoin Core').mkdir()
        expect_error(lambda: module.configure(h, r, c))
        assert not (c / 'QtProject.conf').exists()

        h, r, c = profile(root / 'symlink-settings')
        sentinel = c / 'sentinel'
        sentinel.write_text('unchanged')
        (c / 'QtProject.conf').symlink_to(sentinel)
        expect_error(lambda: module.configure(h, r, c))
        assert sentinel.read_text() == 'unchanged'

        h, r, c = profile(root / 'unsafe-private')
        (h / 'Private Workspace').chmod(0o755)
        expect_error(lambda: module.configure(h, r, c))
        assert not (c / 'QtProject.conf').exists()

        result = {
            'status': 'PASS',
            'helper_sha256': hashlib.sha256(HELPER.read_bytes()).hexdigest(),
            'source_sha256': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in (HELPER,
                                        ROOT / 'tools/core-vault/runtime-template/usr/local/bin/core-vault-core-file-dialogs',
                                        ROOT / 'tools/core-vault/test-core-file-dialogs.py',
                                        ROOT / 'tools/core-vault/check-core-file-dialogs.py')},
            'official_core_sha256': hashlib.sha256((ROOT / 'config/includes.chroot/usr/local/bin/bitcoin-qt').read_bytes()).hexdigest(),
            'labels': labels,
            'tests': ['fresh_sidebar_labels_and_navigation', 'idempotent_reapply',
                      'native_Qt_URL_roundtrip', 'custom_favorites_and_typed_preferences_preserved',
                      'one_original_settings_backup', 'minimum_sidebar_width_and_wider_width_preserved',
                      'unexpected_alias_refused',
                      'symlink_settings_refused', 'disk_workspace_fallback_not_created'],
            'scope': 'isolated synthetic profiles and stock Qt6 QFileDialog; no real wallet opened',
        }
        output = json.dumps(result, indent=2) + '\n'
        if args.json:
            with args.json.open('x') as stream:
                stream.write(output)
        print(output, end='')


if __name__ == '__main__':
    main()
