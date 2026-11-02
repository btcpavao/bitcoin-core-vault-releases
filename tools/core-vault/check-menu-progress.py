#!/usr/bin/python3
"""Source gate for the menu-safe startup and installer presentation pass."""
from pathlib import Path
import ast
import subprocess

ROOT = Path(__file__).resolve().parents[2]
INC = ROOT/'config/includes.chroot'
wrapper = INC/'usr/local/bin/core-vault-bitcoin'
helper = INC/'usr/local/bin/core-vault-hide-sync'
base = ROOT/'tools/core-vault/calamares/base_patch.py'
subprocess.run(['/bin/sh', '-n', str(wrapper)], check=True)
c = wrapper.read_text()
# VAULT_CORE_NATIVE_HIDE_V2: targeted native Hide; no global keyboard/cover helpers.
import runpy
runpy.run_path(str(ROOT/'tools/core-vault/check-core-startup-v4.py'), run_name='__main__')
s = base.read_text()
ast.parse(s, str(base))
for name in ('vault_refine_execution', 'vault_refine_window', 'vault_test_progress_geometry'):
    assert f'def {name}(' in s
assert 'CORE_VAULT_SIMPLE_DISK_UI_V1' in s
assert 'Technical details: whole-disk installation' not in s
assert 'progressLogo' not in s
for rel in ('config/package-lists/core-vault.list.chroot', 'tools/core-vault/manifests/core-vault.list.chroot'):
    packages = (ROOT/rel).read_text().splitlines()
    for name in ('tesseract-ocr', 'tesseract-ocr-eng', 'python3-pyside6.qtwidgets'):
        assert name in packages
print('VAULT MENU-SAFE CORE + INSTALLER LAYOUT SOURCE CHECK PASSED')
