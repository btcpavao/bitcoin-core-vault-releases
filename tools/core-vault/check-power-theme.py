#!/usr/bin/python3
"""Verify exact bundled host-panel power artwork and its redistribution files."""
from pathlib import Path
import argparse, ast, hashlib, json, xml.etree.ElementTree as ET

EXPECTED = {
    'icons/system-reboot.svg': 'adb5fcda8ef29b73de9e24481c1f439a92c29c8fa5952ae1a5c225f8a86da1df',
    'icons/system-shutdown.svg': '6591117fa3fa622a1214f7fca180e39b138aeffca11cbef4913b5bfa0ba95144',
    'licenses/elementary-xfce/copyright': '0d8480ec725c5e7817126e09aced20c5854586b1a783156e78278e060109f1f5',
    'licenses/elementary-xfce/GPL-3.txt': '3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986',
    'licenses/elementary-xfce/NOTICE.txt': '94b42ddf794bcd1ae8034ee22621b5b2e7600a5953a23ad0cee1a4291956b4a5',
}


def verify_payload(home, read_asset, installer_manifest=None):
    tree = ast.parse(home)
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'power_icon')
    text = ast.unparse(function)
    for token in ('VAULT_POWER_THEME_ICONS_V2', 'VAULT_POWER_ICON_BUTTONS_V1'):
        assert token in home, token
    for token in ('system-reboot.svg', 'system-shutdown.svg', 'QIcon(str(path))'):
        assert token in text, token
    assert not any(isinstance(n, ast.Name) and n.id == 'QPainter' for n in ast.walk(function)), 'Power icons must use unchanged SVG artwork'
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'VaultHome')
    for token in ('VAULT_HOME_DARK_DIALOGS_V1', 'QMessageBox { background-color: #191919;', 'QMessageBox QLabel { background: transparent; color: #f0f0f0;'):
        assert token in home, 'Home dialog theme missing: ' + token
    for call in ast.walk(cls):
        if isinstance(call, ast.Call) and ast.unparse(call.func) in ('QMessageBox.question', 'QMessageBox.warning', 'QMessageBox.information'):
            assert call.args and isinstance(call.args[0], ast.Name) and call.args[0].id == 'self', 'Home message must inherit the dark Home theme'
    for action in ('restart', 'shutdown'):
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == action)
        text = ast.unparse(method)
        assert '/usr/local/bin/core-vault-finish' in text, action + ' must use the verified finish flow'
        if action == 'restart':
            assert '--restart' in text, 'Restart must request the finish flow restart mode'
    question = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'PowerQuestion')
    text = ast.unparse(question)
    for token in ('setDefaultButton(QMessageBox.No)', 'setEscapeButton(QMessageBox.No)', 'self.isActiveWindow()', 'remember_cancel_focus'):
        assert token in text, 'Power question keyboard/cancel safety missing: ' + token
    flow = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'power_question')
    text = ast.unparse(flow)
    for token in ('PowerQuestion(self, title, message)', 'home_was_active = self.isActiveWindow()', 'answer == QMessageBox.No and home_was_active', 'dialog.cancel_from_active_dialog', 'self.activateWindow()'):
        assert token in text, 'Guarded Home keyboard return missing: ' + token
    config=ET.fromstring(read_asset('openbox.xml'))
    ns={'o':'http://openbox.org/3.4/rc'}
    f12=config.findall("o:keyboard/o:keybind[@key='F12']",ns)
    assert len(f12)==1 and [a.attrib.get('name') for a in f12[0]]==['ToggleShowDesktop'], 'F12 must use the valid native Openbox action'
    rule=config.find("o:applications/o:application[@title='Bitcoin Core Vault'][@type='desktop']",ns)
    assert rule is not None and rule.find('o:focus',ns).text=='no', 'Home startup focus policy changed'
    record = json.loads(read_asset('icons/power-icons.json'))
    assert record.get('schema') == 1 and record.get('render_size') == 44
    assert record.get('theme') == 'elementary-xfce-hidpi'
    assert record.get('package') == 'elementary-xfce-icon-theme' and record.get('version') == '0.21-1'
    assert record.get('license') == 'GPL-3.0-or-later'
    assert record.get('files') == EXPECTED, 'Unexpected bundled power-artwork manifest'
    for relative, digest in EXPECTED.items():
        actual = hashlib.sha256(read_asset(relative)).hexdigest()
        assert actual == digest, 'Bundled original changed or license missing: ' + relative
        if installer_manifest is not None:
            absolute = 'usr/share/core-vault/' + relative
            assert installer_manifest['files'].get(absolute) == digest, 'Installer omits power asset: ' + absolute
    if installer_manifest is not None:
        relative = 'icons/power-icons.json'
        absolute = 'usr/share/core-vault/' + relative
        assert installer_manifest['files'].get(absolute) == hashlib.sha256(read_asset(relative)).hexdigest(), 'Installer omits power icon manifest'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, default=Path(__file__).resolve().parents[2])
    root = parser.parse_args().project.resolve()
    active = root / 'config/includes.chroot'
    template = root / 'tools/core-vault/runtime-template'
    relative_home = 'usr/local/bin/core-vault-home'
    assert (active / relative_home).read_bytes() == (template / relative_home).read_bytes(), 'Home templates differ'
    for base in (active, template):
        assets = base / 'usr/share/core-vault'
        verify_payload((base / relative_home).read_text(), lambda relative: (assets / relative).read_bytes())
    for relative in ('config/package-lists/core-vault.list.chroot', 'tools/core-vault/manifests/core-vault.list.chroot'):
        packages = [line.split('#', 1)[0].strip() for line in (root / relative).read_text().splitlines()]
        assert 'qt6-svg-plugins' in packages, 'SVG icon engine missing: ' + relative
    print('VAULT EXACT HOST POWER ICONS + LICENSE SOURCE CHECK PASSED')


if __name__ == '__main__':
    main()
