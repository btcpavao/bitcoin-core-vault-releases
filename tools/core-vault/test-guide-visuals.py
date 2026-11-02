#!/usr/bin/python3
"""Render the Guide with synthetic illustrations; never launch custody tools."""
import argparse
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import time

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QTextDocument
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
    guide = load_source(root / 'config/includes.chroot/usr/local/bin/core-vault-guide')
    app.setFont(guide.UI_FONT)
    assert set(guide.SECTIONS) == set(guide.VISUALS), 'Every chapter needs an illustration'
    window = guide.Guide()
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
            assert window.current_description in window.viewer.toPlainText(), (section, 'missing readable equivalent')
            resource = window.viewer.document().resource(
                QTextDocument.ResourceType.ImageResource, QUrl('vault-guide:illustration'))
            assert resource is not None and not resource.isNull(), (section, 'missing illustration')
            assert window.demo.isVisible() == (section == 'Encryption security levels')
            if output and width == 1366:
                slug = section.lower().replace(' / ', '-').replace(' & ', '-').replace(' ', '-')
                window.grab().save(str(output / (slug + '.png')))
                (output / (slug + '.svg')).write_text(window.current_svg)
            if output and width == 800 and section in ('Encryption security levels', 'Recovery / inheritance'):
                window.grab().save(str(output / ('compact-' + section.split()[0].lower() + '.png')))
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
    print(f'PASS: {len(guide.SECTIONS)} chapters × 4 sizes, 1/2/3-layer interaction, compact navigation, readable descriptions, no horizontal overflow')
    print('VAULT GUIDE VISUALS QT CHECK PASSED')


if __name__ == '__main__':
    main()
