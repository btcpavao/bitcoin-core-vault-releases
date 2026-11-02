#!/usr/bin/python3
"""Read-only v4 UI wiring gate. Existing Core/installer safety checks still run."""
from pathlib import Path
import ast, subprocess
ROOT=Path(__file__).resolve().parents[2]
INC=ROOT/'config/includes.chroot'
TEMPLATE=ROOT/'tools/core-vault/runtime-template'
home=INC/'usr/local/bin/core-vault-home';s=home.read_text();t=ast.parse(s)
assert home.read_bytes()==(TEMPLATE/'usr/local/bin/core-vault-home').read_bytes()
for marker in ('VAULT_OPTICAL_ICONS_V1','VAULT_POWER_ICON_BUTTONS_V1','optical_icon(icon)',
               "setAccessibleName('Restart')","setAccessibleName('Finish & Shut Down')"):
    assert marker in s,marker
assert "self.shutdown_button = HintButton(" in s
assert s.count('setFixedSize(48, 48)')==2
assert "self.restart_button.clicked.connect(self.restart)" in s
assert "self.shutdown_button.clicked.connect(self.shutdown)" in s
cls=next(n for n in t.body if isinstance(n,ast.ClassDef) and n.name=='VaultHome')
for name in ('restart','shutdown'):
    n=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name==name)
    assert '/usr/local/bin/core-vault-finish' in ast.unparse(n)
subprocess.run(['/usr/bin/python3',str(ROOT/'tools/core-vault/check-power-theme.py'),'--project',str(ROOT)],check=True)
subprocess.run(['/usr/bin/python3',str(ROOT/'tools/core-vault/check-keyboard.py'),'--project',str(ROOT)],check=True)
source=ROOT/'tools/core-vault/backup-src/src'
b=(source/'backup.py').read_text();ast.parse(b)
assert 'from message_dialog import show_message' in b
assert 'from password_dialog import get_backup_request' in b
assert 'from recovery_dialog import get_recovery_request' in b
for marker in ('create_backup(inputs, dest, password', 'recover_files('):
    assert marker in b,marker
creation=(source/'password_dialog.py').read_text();ast.parse(creation)
for marker in ('def get_verification_secrets(', 'def get_backup_request(', 'class SecretRow(', '+ Add Encryption Layer'):
    assert marker in creation,marker
text=(source/'message_dialog.py').read_text();ast.parse(text)
for marker in ('lockIcon','#111111','Qt.PlainText'):
    assert marker in text
for rel in ('config/package-lists/core-vault.list.chroot','tools/core-vault/manifests/core-vault.list.chroot'):
    packages=[line.split('#',1)[0].strip() for line in (ROOT/rel).read_text().splitlines()]
    for p in ('python3-pyside6.qtwidgets','qt6-svg-plugins'):
        assert p in packages,p
subprocess.run(['/bin/sh','-n',str(INC/'usr/local/bin/core-vault-bitcoin')],check=True)
print('VAULT UI POLISH 0.4.1 SOURCE CHECK PASSED')

assert 'VAULT_CORE_NATIVE_HIDE_V2' in (INC/'usr/local/libexec/core-vault-core-session').read_text()
print('Core launch wiring uses the native Hide startup helper.')

# GTK4 menus must be opaque in the noncomposited native Save chooser.
relative = 'etc/skel/.config/gtk-4.0/gtk.css'
css = (INC / relative).read_text()
assert (INC / relative).read_bytes() == (TEMPLATE / relative).read_bytes()
for marker in ('VAULT_NATIVE_POPOVER_OPAQUE_V1', 'popover.background {',
               'popover.background > contents {', 'background-color: @popover_bg_color;',
               'background-image: none;'):
    assert marker in css, marker
for marker in ('border-radius: 0;', 'box-shadow: none;', 'margin: 0;'):
    assert css.count(marker) == 2, marker
print('VAULT NATIVE GTK4 MENU SOURCE CHECK PASSED')
