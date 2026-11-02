#!/usr/bin/python3
from pathlib import Path
import py_compile
import ast

ROOT = Path(__file__).resolve().parents[2]
INC = ROOT / 'config/includes.chroot'

home = INC / 'usr/local/bin/core-vault-home'
guide = INC / 'usr/local/bin/core-vault-guide'
printing = INC / 'usr/local/bin/core-vault-print'

for path in (home, guide, printing):
    assert path.is_file(), path
    py_compile.compile(str(path), doraise=True)

s = home.read_text()
for title in (
    'Bitcoin Core', 'KeePassXC', 'Decrypt Backup', 'Brasero', 'Print & Labels',
    'Files', 'Editor', 'Terminal', 'Wallet Backup', 'Vault Guide',
):
    assert title in s, title
tree = ast.parse(s)
tools = next(n.value for n in tree.body if isinstance(n, ast.Assign)
             and any(isinstance(t, ast.Name) and t.id == 'TOOLS' for t in n.targets))
assert len(tools.elts) == 10
names = [ast.literal_eval(next(v for k, v in zip(n.keys, n.values)
                              if ast.literal_eval(k) == 'title')) for n in tools.elts]
assert names == ['Bitcoin Core', 'Wallet Backup', 'Decrypt Backup', 'KeePassXC', 'Editor', 'Brasero', 'Print & Labels', 'Files', 'Terminal', 'Vault Guide']
assert 'HOVER_DELAY_MS = 800' in s
assert 'QFrame#HoverPopup' in s
assert "columns = 5 if width >= 680 else 2" in s
assert '/usr/local/bin/core-vault-print' in s
assert '/usr/local/bin/core-vault-guide' in s

cups = (INC / 'etc/cups/cupsd.conf').read_text()
assert 'Listen localhost:631' in cups
assert 'Browsing No' in cups
assert 'DefaultShared No' in cups
assert 'WebInterface No' in cups

rule = (INC / 'etc/polkit-1/rules.d/49-core-vault-printer.rules').read_text()
assert 'subject.user == "vault"' in rule
assert 'org.opensuse.cupspkhelper.mechanism.' in rule

packages = (ROOT / 'config/package-lists/core-vault.list.chroot').read_text().splitlines()
for package in (
    'cups', 'cups-client', 'cups-pk-helper', 'system-config-printer',
    'printer-driver-gutenprint', 'python3-pyside6.qtprintsupport',
):
    assert package in packages, package

print('VAULT HOME + GUIDE + PRINTING SOURCE CHECK PASSED')

# VAULT_WINDOW_CHECK_V12
import runpy
runpy.run_path(str(ROOT / 'tools/core-vault/check-window-behavior.py'), run_name='__main__')

# VAULT_POWER_CORE_CHECK_V1
import runpy
runpy.run_path(str(ROOT / 'tools/core-vault/check-power-core.py'), run_name='__main__')

# VAULT_MENU_PROGRESS_V2
import runpy
runpy.run_path(str(ROOT/'tools/core-vault/check-menu-progress.py'), run_name='__main__')

# VAULT_POLISH_CHECK_V3
import runpy
runpy.run_path(str(ROOT/'tools/core-vault/check-polish-v3.py'), run_name='__main__')

# VAULT_CORE_STARTUP_GUARD_V4
import runpy
runpy.run_path(str(ROOT/'tools/core-vault/check-core-startup-v4.py'), run_name='__main__')

# VAULT_UI_POLISH_V4
runpy.run_path(str(ROOT/'tools/core-vault/check-ui-polish-v4.py'), run_name='__main__')

# VAULT_BLEACHBIT_REMOVAL_V1
runpy.run_path(str(ROOT / "tools/core-vault/check-bleachbit.py"), run_name="__main__")

# VAULT_KEEPASS_GENERATOR_V1
runpy.run_path(str(ROOT / 'tools/core-vault/check-keepass-generator.py'), run_name='__main__')
