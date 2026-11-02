#!/usr/bin/python3
from pathlib import Path
import ast, subprocess
ROOT=Path(__file__).resolve().parents[2]
INC=ROOT/'config/includes.chroot'
home=INC/'usr/local/bin/core-vault-home'
core=INC/'usr/local/bin/core-vault-bitcoin'
rule=INC/'etc/sudoers.d/91-core-vault-poweroff'
for p in (home,core,rule):
    assert p.is_file(), p
ast.parse(home.read_text(),str(home))
subprocess.run(['/bin/sh','-n',str(core)],check=True)
s=home.read_text()
for marker in ('VAULT_POWER_CONTROLS_V1', 'self.restart_button = HintButton(', "def restart(self):",
               "'/usr/local/bin/core-vault-finish'", "'--restart'"):
    assert marker in s, marker
c=core.read_text()
# VAULT_CORE_STARTUP_CHECK_MIGRATION_V41
# Keep restart/shutdown, exact sudo rules and installer permission checks below.
# Startup wiring is now checked against V4, not the retired AT-SPI launcher.
import runpy
runpy.run_path(str(ROOT / 'tools/core-vault/check-core-startup-v4.py'), run_name='__main__')
r=rule.read_text()
assert r.count('vault ALL=(root) NOPASSWD: /usr/local/sbin/core-vault-end-session poweroff')==1
assert r.count('vault ALL=(root) NOPASSWD: /usr/local/sbin/core-vault-end-session reboot')==1
subprocess.run(['/usr/sbin/visudo','-cf',str(rule)],check=True,stdout=subprocess.DEVNULL)
t=ROOT/'tools/core-vault/runtime-template/usr/local/bin'
for name in ('core-vault-home','core-vault-bitcoin'):
    assert (INC/'usr/local/bin'/name).read_bytes()==(t/name).read_bytes(), name
tr=ROOT/'tools/core-vault/runtime-template/etc/sudoers.d/91-core-vault-poweroff'
assert tr.read_bytes()==rule.read_bytes()
target=INC/'usr/lib/core-vault-installer/target.py'
if target.is_file():
    body=target.read_text()
    allowed="['/usr/local/sbin/core-vault-end-session','reboot']"
    assert allowed in body
    # Reboot must not remain in the explicit-deny tuple.
    deny=body.split('for cmd in (',2)[2].split('):',1)[0] if body.count('for cmd in (')>=2 else ''
    assert "['/usr/bin/systemctl','--no-block','reboot']" in deny
install_check=INC/'usr/local/bin/core-vault-install-check'
if install_check.is_file():
    assert "'/usr/local/sbin/core-vault-end-session','reboot'" in install_check.read_text()
print('VAULT POWER CONTROLS + CORE STARTUP CHECK PASSED')
