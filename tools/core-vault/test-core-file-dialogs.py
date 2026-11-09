#!/usr/bin/python3
"""Exercise file chooser places on synthetic profiles, never a real wallet."""
from __future__ import annotations
import argparse
import hashlib
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
import tempfile

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QByteArray, QSettings, QStandardPaths, Qt
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
        module.MEDIA_ROOTS = (root / 'media/vault', root / 'run/media/vault')
        for media_root in module.MEDIA_ROOTS:
            media_root.mkdir(parents=True)
        module.MOUNTINFO = root / 'mountinfo'
        module.MOUNTINFO.write_text('')
        home, runtime, config = profile(root / 'fresh')
        os.environ.update(HOME=str(home), XDG_CONFIG_HOME=str(config), XDG_RUNTIME_DIR=str(runtime))
        documents_config = ROOT / 'config/includes.chroot/etc/skel/.config/user-dirs.dirs'
        (config / 'user-dirs.dirs').write_bytes(documents_config.read_bytes())
        app = QApplication([])
        assert QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation) == str(home / 'Private Workspace')
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
        assert labels == ['Bitcoin Core', 'Private Workspace', 'USB Media'], labels
        assert sidebar.width() >= 315
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

        # A real running Qt application must read the desktop watcher's changes
        # when its next chooser opens, without restarting the application.
        external = module.MEDIA_ROOTS[0] / 'Hotplug USB'
        external.mkdir()
        escaped = str(external).replace(' ', r'\040')
        module.MOUNTINFO.write_text(f'42 22 8:1 / {escaped} rw - vfat /dev/sdb1 rw\n')
        refresh_code = """import sys
from pathlib import Path
namespace = {'__name__': 'vault_external_dialog_refresh'}
helper = Path(sys.argv[1])
exec(compile(helper.read_text(), str(helper), 'exec'), namespace)
base = Path(sys.argv[2])
namespace['MEDIA_ROOTS'] = (base / 'media/vault', base / 'run/media/vault')
namespace['MOUNTINFO'] = base / 'mountinfo'
namespace['configure'](base / 'fresh/home', base / 'fresh/runtime', base / 'fresh/home/.config')
"""
        subprocess.run([sys.executable, '-c', refresh_code, str(HELPER), str(root)], check=True)
        reopened = QFileDialog()
        reopened.setOption(QFileDialog.DontUseNativeDialog)
        reopened.show()
        app.processEvents()
        model = reopened.findChild(QListView, 'sidebar').model()
        assert [model.index(i, 0).data(Qt.DisplayRole) for i in range(model.rowCount())] == [
            'Bitcoin Core', 'Private Workspace', 'Hotplug USB', 'USB Media']
        reopened.setDirectory(str(external))
        app.processEvents()
        assert reopened.directory().absolutePath() == str(external)
        reopened.reject()
        del reopened
        app.processEvents()
        module.MOUNTINFO.write_text('')
        module.configure(home, runtime, config)

        h, r, c = profile(root / 'existing')
        custom = h / 'USB Backup, (sample)'
        custom.mkdir()
        settings = module.settings_at(c / 'QtProject.conf')
        settings.setValue(module.KEY, ['file:', h.as_uri(), (h / '.bitcoin').as_uri(),
                                      custom.as_uri(), custom.as_uri()])
        settings.setValue(module.WIDTH, 450)
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
            (h / 'Private Workspace').as_uri(),
            (r / module.ALIAS_DIR / 'USB Media').as_uri(), custom.as_uri()]
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
        assert int(after.value(module.WIDTH)) == 320
        assert after.value('FileDialog/viewMode') == 'Detail'
        assert after.value('Unrelated/list') == ['keep, comma', 'keep space']
        saved = (c / 'QtProject.conf').read_bytes()
        module.configure(h, r, c)
        assert (c / 'QtProject.conf').read_bytes() == saved

        h, r, c = profile(root / 'usb-hotplug')
        primary, secondary = module.MEDIA_ROOTS
        drive = primary / 'USB Backup, sample'
        alternate = secondary / 'Alternate USB'
        stale = primary / 'Unplugged USB'
        live = primary / 'Live Boot'
        long_label = primary / ('A long removable disk name ' * 3)
        for entry in (drive, alternate, stale, live, long_label):
            entry.mkdir()
        linked = primary / 'Redirected USB'
        linked.symlink_to(stale, target_is_directory=True)
        outside = root / 'internal-disk'
        outside.mkdir()
        def record(path, source, options='rw'):
            escaped = str(path).replace(' ', r'\040')
            return f'42 22 8:1 / {escaped} {options} - vfat {source} {options}\n'
        metadata = (record(drive, '/dev/sdb1') + record(alternate, '/dev/sdc1', 'ro') +
                    record(drive, '/dev/sdb1') + record(linked, '/dev/sdd1') +
                    record(outside, '/dev/sda1') + record(live, '/dev/sde1') +
                    record(Path('/run/live/medium'), '/dev/sde1', 'ro'))
        module.MOUNTINFO.write_text(metadata)
        assert module.mounted_media() == [alternate, drive]
        module.configure(h, r, c)
        hot = module.settings_at(c / 'QtProject.conf')
        current = module.urls(hot.value(module.KEY))
        assert current == [(r / module.ALIAS_DIR / 'Bitcoin Core').as_uri(),
                           (h / 'Private Workspace').as_uri(), alternate.as_uri(), drive.as_uri(),
                           (r / module.ALIAS_DIR / 'USB Media').as_uri()]
        assert int(hot.value(module.WIDTH)) == 320
        assert (r / module.ALIAS_DIR / 'USB Media').readlink() == primary
        module.MOUNTINFO.write_text(metadata + record(long_label, '/dev/sdf1'))
        module.configure(h, r, c)
        assert int(module.settings_at(c / 'QtProject.conf').value(module.WIDTH)) == 420
        module.MOUNTINFO.write_text('')
        module.configure(h, r, c)
        unplugged = module.settings_at(c / 'QtProject.conf')
        assert module.urls(unplugged.value(module.KEY)) == [
            (r / module.ALIAS_DIR / 'Bitcoin Core').as_uri(),
            (h / 'Private Workspace').as_uri(), (r / module.ALIAS_DIR / 'USB Media').as_uri()]
        assert int(unplugged.value(module.WIDTH)) == 420
        assert stale.is_dir() and drive.is_dir()  # No mount or file operation occurred.

        h, r, c = profile(root / 'usb-alias-conflict')
        d = r / module.ALIAS_DIR
        d.mkdir(mode=0o700)
        (d / 'USB Media').symlink_to(root, target_is_directory=True)
        expect_error(lambda: module.configure(h, r, c))
        assert not (c / 'QtProject.conf').exists()

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
            'tests': ['native_Qt_DocumentsLocation_is_Private_Workspace',
                      'fresh_sidebar_labels_and_navigation', 'idempotent_reapply',
                      'native_Qt_URL_roundtrip', 'custom_favorites_and_typed_preferences_preserved',
                      'one_original_settings_backup', 'minimum_sidebar_width_and_wider_width_preserved',
                      'external_refresh_visible_in_reopened_native_Qt_dialog',
                      'mounted_USB_hotplug_and_removal', 'read_only_secondary_media_root',
                      'stale_symlink_internal_and_boot_media_excluded', 'long_USB_label_width',
                      'USB_alias_conflict_refused', 'unexpected_alias_refused',
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
