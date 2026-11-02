#!/usr/bin/python3
"""No-secrets fixture for Wallet Backup success handoff and icon transparency."""
import ast
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import Mock
import os
from PIL import Image
ROOT=Path(__file__).resolve().parents[2]
REL='usr/local/bin/core-vault-wallet-backup'
for folder in ('config/includes.chroot','tools/core-vault/runtime-template'):
    path=ROOT/folder/REL
    tree=ast.parse(path.read_text())
    method=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
    fn=compile(ast.Module(body=[method],type_ignores=[]),str(path),'exec')
    with tempfile.TemporaryDirectory(prefix='vault-handoff-') as folder:
        root=Path(folder)
        private=root/'Private Workspace';private.mkdir(mode=0o700)
        removable=root/'Removable Disk';removable.mkdir(mode=0o700)
        nested=private/'nested';nested.mkdir(mode=0o700)
        wallet=root/'wallet.dat'
        for destination,opens in ((private/'wallet-backup.gpg',True),
                                  (nested/'wallet-backup.gpg',True),
                                  (removable/'wallet-backup.gpg',False)):
            actions=[];windows=[];valid=Mock()
            class Progress:
                def __init__(self):actions.append('progress-open')
                def close(self):actions.append('progress-closed')
            def do_export(wallet_name,path,password,progress):
                assert actions[-1]=='progress-open'
                actions.append('encrypted-verified')
                return path
            def popup(*args,**kw):actions.append('message')
            def spawn(cmd,**kw):
                assert actions[-1]=='progress-closed', 'Thunar opened before progress/dialog closed'
                windows.append((cmd,kw));actions.append('thunar')
            module=SimpleNamespace(Popen=spawn, DEVNULL=object())
            env=dict(os=os,Path=Path,PRIVATE=private,subprocess=module,
                harden=lambda:None,check_storage=lambda:None,
                wallet_files=lambda:{'test-wallet':wallet},check_loaded_wallet_coverage=lambda w:None,
                dialog=lambda *a:'0',get_backup_request=lambda *a,**kw:(destination,['fixture-passphrase']),
                validate_password=lambda a:None,backup_destination=lambda p:p,
                Progress=Progress, export_wallet=do_export, message=popup,
                Cancelled=type('Cancelled',(Exception,),{}),BackupError=Exception,RuntimeError=RuntimeError)
            exec(fn,env)
            env['main']()
            assert windows==([(['/usr/bin/thunar',str(private)],windows[0][1])] if opens else []), (destination,windows)
            if opens:
                assert actions==['progress-open','encrypted-verified','progress-closed','thunar'],actions
                assert windows[0][1]['start_new_session'] and windows[0][1]['close_fds']
            else:
                assert actions==['progress-open','encrypted-verified','progress-closed','message'],actions
            print('PASS:',path.name,destination.parent.name, 'workspace-open' if opens else 'external-message')
        print('PASS: no plaintext, no destination relocation, no Thunar open for external media')
for name in ('decrypt-backup.png','print-labels.png'):
    for folder in ('config/includes.chroot','tools/core-vault/runtime-template'):
        png=ROOT/folder/'usr/share/core-vault/icons'/name
        with Image.open(png) as img:
            im=img.convert('RGBA')
            assert im.size==(128,128)
            assert all(im.getpixel(p)[3]==0 for p in ((0,0),(127,0),(0,127),(127,127)))
            assert any(im.getpixel(p)[3]>200 for p in ((64,64),(64,48),(40,50),(64,95)))
        print('PASS: transparent icon',folder,name)
print('VAULT POST-BACKUP HANDOFF AND ICON TESTS PASSED')
