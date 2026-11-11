#!/usr/bin/python3
"""Read-only checks of this pass. Existing installation safety checks still run."""
from pathlib import Path
import ast
import subprocess
ROOT=Path(__file__).resolve().parents[2]
INC=ROOT/'config/includes.chroot'
CAL=ROOT/'tools/core-vault/calamares'
for path in (CAL/'visual_polish.py',CAL/'patch_calamares_source.py',CAL/'package_state.py'):
    ast.parse(path.read_text(),str(path))
# Direct, input-free Core launching supersedes the old cover/keyboard guard.
import runpy
runpy.run_path(str(ROOT/'tools/core-vault/check-core-startup-v4.py'), run_name='__main__')
v=(CAL/'visual_polish.py').read_text()
assert 'CoreVaultWizardSurface' in v and 'CORE_VAULT_VISUAL_POLISH_V3_PROGRESS' in v
assert 'visual_polish.patch_tree(work)' in (CAL/'patch_calamares_source.py').read_text()
assert "'visual_polish.py'" in (CAL/'package_state.py').read_text()
assert 'visual_polish.py --self-test' in (ROOT/'tools/rebuild/packages/compiler-entry.sh').read_text()
style=(INC/'etc/calamares/branding/core-offline/stylesheet.qss').read_text()
assert 'CORE_VAULT_VISUAL_POLISH_V3' in style
assert 'font-size:13px' in v
assert 'm_failure.has_value()' in v and 'toHtmlEscaped' in v
assert 'coreVaultEraseConsent' in style
print('VAULT INSTALLER POLISH + TARGETED HIDE V3 SOURCE CHECK PASSED')
