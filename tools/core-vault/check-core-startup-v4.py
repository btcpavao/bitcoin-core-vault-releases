#!/usr/bin/python3
"""Verify scoped native Hide launcher wiring and unchanged offline arguments.
Static checks complement actual Core transition tests; they do not prove GUI.
"""
from pathlib import Path
import ast
import hashlib
import subprocess

ROOT=Path(__file__).resolve().parents[2]
INC=ROOT/'config/includes.chroot'
p=INC/'usr/local/bin/core-vault-bitcoin';s=p.read_text()
subprocess.run(['/bin/sh','-n',str(p)],check=True)
inner=INC/'usr/local/libexec/core-vault-core-session';i=inner.read_text()
subprocess.run(['/bin/sh','-n',str(inner)],check=True)
assert 'exec /usr/bin/bwrap' in s and '--ro-bind / /' in s and '--sync-fd 3' in s
assert 'VAULT_CORE_NATIVE_HIDE_V2' in i
assert i.count('exec /usr/local/bin/bitcoin-qt \\\n')==1
assert 'exec 3>"$LOCK"' in s and 'flock -n 3' in s
assert '/usr/local/bin/core-vault-hide-sync --pid "$$"' in i
assert '>"$XDG_RUNTIME_DIR/core-vault-hide-sync.log" 2>&1 3>&- &' in i
for flag in ('-datadir="$HOME/.bitcoin"','-networkactive=0','-maxconnections=0',
             '-listen=0','-listenonion=0','-dns=0','-dnsseed=0','-fixedseeds=0',
             '-discover=0','-natpmp=0','-walletbroadcast=0','-prune=550','-splash=0','-lang=en'):
    assert flag in i,flag
for forbidden in ('core-vault-core-cover','core-vault-core-startup-guard',
                  'xdotool key','xdotool type','AT_SPI_BUS_ADDRESS','COVER_PID','GUARD_STATUS'):
    assert forbidden not in s+i,forbidden
assert s.count('\n    focus_core\n')==1
assert s.index('if ! flock -n 3; then')<s.index('\n    focus_core\n')<s.index('exit 0')
helper=INC/'usr/local/bin/core-vault-hide-sync';source=helper.read_text();ast.parse(source)
for required in ('XSendEvent','CORE_SHA256','read_birth','os.getuid()',
                 '_NET_CLIENT_LIST','WM_TRANSIENT_FOR','self.children(self.root)',
                 'PANEL_PHRASES','grabWindow','--timeout','deadline','recognizer.hidden'):
    assert required in source,required
for required in ('--ocr-worker', 'PR_SET_PDEATHSIG', 'OCR_MAX_PNG', 'OCR_MAX_TSV',
                 'response != request', 'os.set_blocking', 'select.select',
                 'TessBaseAPIClearAdaptiveClassifier', 'TessBaseAPIClear',
                 "TessBaseAPIInit3(api, None, b'eng')", 'TessBaseAPISetPageSegMode(api, 11)',
                 'hashlib.file_digest', 'except BrokenPipeError', 'worker.kill()'):
    assert required in source,required
for forbidden in ('XTestFake','XWarpPointer','XSetInputFocus','requestActivate(',
                  'xdotool','LD_PRELOAD','get_action_iface','Atspi.init'):
    assert forbidden not in source,forbidden
assert hashlib.sha256((INC/'usr/local/bin/bitcoin-qt').read_bytes()).hexdigest()==(
    'd43632a3e54dfb181ba045db2a5b1ec2396a1acdda010e3b6d07b2e21c69c183')
for base in (INC,ROOT/'tools/core-vault/runtime-template'):
    for name in ('core-vault-core-cover','core-vault-core-startup-guard'):
        assert not (base/'usr/local/bin'/name).exists()
for name in ('core-vault-bitcoin','core-vault-hide-sync'):
    assert (INC/'usr/local/bin'/name).read_bytes()==(
        ROOT/'tools/core-vault/runtime-template/usr/local/bin'/name).read_bytes()
assert inner.read_bytes()==(ROOT/'tools/core-vault/runtime-template/usr/local/libexec/core-vault-core-session').read_bytes()
print('VAULT CORE NATIVE HIDE SOURCE CHECK PASSED (actual GUI test still required)')
