#!/usr/bin/python3
"""Render the Guide with synthetic illustrations; never launch custody tools."""
import argparse
import importlib.machinery
import importlib.util
import json
import hashlib
import os
from pathlib import Path
import time

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QTextDocument, QTextTable, QIcon, QTextCursor
from PySide6.QtWidgets import QApplication


def load_source(path):
    loader = importlib.machinery.SourceFileLoader('vault_guide_preview', str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    root = args.project.resolve()
    app = QApplication.instance() or QApplication([])
    app.setStyle('Fusion')
    QIcon.setThemeName('Adwaita')
    QIcon.setFallbackThemeName('hicolor')
    guide = load_source(root / 'config/includes.chroot/usr/local/bin/core-vault-guide')
    app.setFont(guide.UI_FONT)
    assert set(guide.SECTIONS) == set(guide.VISUALS) == set(guide.SECTION_ICONS), 'Every chapter needs an illustration and icon'
    assert len(guide.SECTIONS) == 19, 'Preserve every Vault chapter'
    for relative in ('usr/local/bin/core-vault-guide', 'usr/lib/core-vault/guide_visuals.py'):
        assert (root / 'config/includes.chroot' / relative).read_bytes() == (root / 'tools/core-vault/runtime-template' / relative).read_bytes()
    license_root = root / 'config/includes.chroot/usr/share/core-vault/licenses/elementary-xfce'
    assets = json.loads((license_root / 'guide-icons.json').read_text())
    assert (license_root / 'GUIDE-ICONS-NOTICE.txt').is_file()
    assert (license_root / 'copyright').is_file() and (license_root / 'GPL-3.txt').is_file()
    for asset in assets['assets']:
        active = root / 'config/includes.chroot/usr/share/core-vault' / asset['file']
        template = root / 'tools/core-vault/runtime-template/usr/share/core-vault' / asset['file']
        assert hashlib.sha256(active.read_bytes()).hexdigest() == asset['sha256']
        assert active.read_bytes() == template.read_bytes()
    for section, (asset, _, _) in guide.SECTION_ICONS.items():
        if asset:
            assert (guide.ASSETS / asset).is_file(), (section, 'missing chapter artwork')
    assert 'The save dialog starts in <b>Private Workspace</b>' in guide.SECTIONS['Watch-Only Wallet in Bitcoin Core']
    assert 'USB Media' in guide.SECTIONS['Files'] and 'read-only' in guide.SECTIONS['Files']
    assert 'core-vault-optical-diagnostics' in guide.SECTIONS['Brasero']
    assert 'does not read files from the disc or test burning' in guide.SECTIONS['Brasero']
    assert 'single supported wallet.dat is encrypted directly' in guide.SECTIONS['Encryption security levels']
    assert 'AES-256 CFB with MDC integrity protection' in guide.SECTIONS['Encryption security levels']
    assert 'There is no TAR extraction for this direct-wallet format' in guide.SECTIONS['Recovery / inheritance']
    assert 'Vault backups always use a standard TAR package' not in ''.join(guide.SECTIONS.values())
    assert 'a complete wallet.dat or a TAR package' in guide.VISUALS['Decrypt Backup'][2]
    assert 'wallet.dat or a standard TAR' in (root / 'config/includes.chroot/usr/lib/core-vault/guide_visuals.py').read_text()
    window = guide.Guide()
    for row in range(window.nav.count()):
        assert not window.nav.item(row).icon().isNull()
        assert not window.section_picker.itemIcon(row).isNull()
    output = args.output
    if output:
        output.mkdir(parents=True, exist_ok=True)

    def settle():
        for _ in range(6):
            app.processEvents()
            time.sleep(.015)
        window.render_section()
        app.processEvents()

    records = []
    for width, height in ((800, 600), (1024, 768), (1366, 768), (1920, 1080)):
        window.resize(width, height)
        window.show()
        settle()
        assert window.section_picker.isVisible() == (width < 1000)
        for row, section in enumerate(guide.SECTIONS):
            window.nav.setCurrentRow(row)
            settle()
            assert window.viewer.document().defaultFont().pointSizeF() == 14
            assert window.viewer.horizontalScrollBar().maximum() == 0, (width, section, 'horizontal overflow')
            assert not window.nav.horizontalScrollBar().isVisible(), (width, section, 'horizontal chapter navigation')
            if window.nav.isVisible():
                assert window.nav.visualItemRect(window.nav.item(row)).width() <= window.nav.viewport().width()
            for frame in window.viewer.document().rootFrame().childFrames():
                if isinstance(frame, QTextTable):
                    assert frame.format().topMargin() >= 16 and frame.format().bottomMargin() >= 24
            assert window.current_description in window.viewer.toPlainText(), (section, 'missing readable equivalent')
            resource = window.viewer.document().resource(
                QTextDocument.ResourceType.ImageResource, QUrl('vault-guide:illustration'))
            assert resource is not None and not resource.isNull(), (section, 'missing illustration')
            assert window.demo.isVisible() == (section == 'Encryption security levels')
            if output and width == 1366:
                slug = section.lower().replace(' / ', '-').replace(' & ', '-').replace(' ', '-')
                window.grab().save(str(output / (slug + '.png')))
                (output / (slug + '.svg')).write_text(window.current_svg)
            if output and width == 800:
                slug = section.lower().replace(' / ', '-').replace(' & ', '-').replace(' ', '-')
                window.grab().save(str(output / ('compact-' + slug + '.png')))
            focus = {
                'Watch-Only Wallet in Bitcoin Core': ('The save dialog starts', 'watch-only-default-location'),
                'Brasero': ('If an external writer is missing', 'brasero-troubleshooting'),
                'Recovery / inheritance': ('Example: two-layer single-wallet backup', 'recovery-direct-wallet'),
                'Files': ('The same Places in your applications', 'files-shared-sidebar'),
                'Encryption security levels': ('One GPG layer', 'encryption-current-format'),
            }
            if output and width in (800, 1366) and section in focus:
                phrase, label = focus[section]
                window.viewer.moveCursor(QTextCursor.MoveOperation.Start)
                assert window.viewer.find(phrase), (section, 'required guidance not found')
                app.processEvents()
                window.grab().save(str(output / (label + '-' + str(width) + '.png')))
                window.viewer.moveCursor(QTextCursor.MoveOperation.Start)
                window.viewer.verticalScrollBar().setValue(0)
            records.append({'viewport':[width,height], 'section':section, 'status':'PASS'})
        row = list(guide.SECTIONS).index('Encryption security levels')
        window.nav.setCurrentRow(row)
        settle()
        for count in (3, 2, 1):
            window.layer_buttons.button(count).click()
            settle()
            assert window.layer_count == count and window.layer_buttons.checkedId() == count
            assert window.current_svg.count('GPG layer') == count
            assert window.viewer.horizontalScrollBar().maximum() == 0
            if output and width == 1366 and count == 3:
                window.grab().save(str(output / 'encryption-three-layers.png'))
        # The compact chapter selector changes the same content as the sidebar.
        window.section_picker.setCurrentIndex(0)
        settle()
        assert window.nav.currentRow() == 0
    assert not window.viewer.openExternalLinks() and not window.viewer.openLinks()
    if output:
        (output / 'checks.json').write_text(json.dumps(records, indent=2) + '\n')
    window.close()
    print(f'PASS: {len(guide.SECTIONS)} chapters × 4 sizes, 1/2/3-layer interaction, compact navigation, shared Node icons, current wallet/TAR recovery, readable descriptions, no horizontal overflow')
    print('VAULT GUIDE VISUALS QT CHECK PASSED')


if __name__ == '__main__':
    main()
