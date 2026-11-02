#!/usr/bin/python3
"""Read-only source/package gate for Encrypted Backup. Does not open a wallet."""
from pathlib import Path
import argparse, ast, hashlib, io, runpy, subprocess, tarfile
VERSION='0.7.3'
PACKAGE_SHA='5a4bae7b3d77576ca961d1e116907430af292d4c67732a46215976dcf8e056ab'

def require(ok, text):
    if not ok: raise RuntimeError(text)

def check(root):
    inc=root/'config/includes.chroot'; template=root/'tools/core-vault/runtime-template'
    package=root/f'config/packages.chroot/core-vault-backup_{VERSION}_all.deb'
    require(package.is_file() and not package.is_symlink(),'Missing local backup package')
    require(hashlib.sha256(package.read_bytes()).hexdigest()==PACKAGE_SHA,'Local backup package checksum mismatch')
    for field,value in [('Package','core-vault-backup'),('Version',VERSION),('Architecture','all')]:
        got=subprocess.check_output(['dpkg-deb','-f',str(package),field],text=True).strip()
        require(got==value,'Local package identity mismatch: '+field)
    require(list((root/'config/packages.chroot').glob('core-vault-backup_*.deb'))==[package],
            'Remove the retired local backup package version from packages.chroot')
    require(not list((root/'config/packages.chroot').glob('*veracrypt*.deb')),'Retired upstream package is still staged')
    for rel in ['etc/sudoers.d/92-core-vault-veracrypt','etc/modules-load.d/core-vault-veracrypt.conf',
                'etc/core-vault/veracrypt-build.json','usr/local/bin/core-vault-veracrypt-check',
                'usr/bin/veracrypt']:
        for base in (inc,template):
            p=base/rel;require(not p.exists() and not p.is_symlink(),'Retired file remains: '+str(p))
    recovery=inc/'usr/share/core-vault/recovery/veracrypt'
    require(not recovery.exists() or not list(recovery.iterdir()),'Retired recovery files remain')
    require(not (root/'config/hooks/live/0998-core-vault-backup.hook.chroot').exists(),'Old hook order remains')
    require(not (root/'config/hooks/live/0935-core-vault-veracrypt-check.hook.chroot').exists(),'Retired build hook remains')
    for name in ['core-vault-home','core-vault-guide','core-vault-print','core-vault-session',
                 'core-vault-desktop-check','core-vault-install-check']:
        a=inc/'usr/local/bin'/name;b=template/'usr/local/bin'/name
        require(a.read_bytes()==b.read_bytes(),'Active/template mismatch: '+name)
        if a.read_text().startswith('#!/usr/bin/python3'):ast.parse(a.read_text(),str(a))
    home=(inc/'usr/local/bin/core-vault-home').read_text()
    tree=ast.parse(home)
    tools=next(n.value for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='TOOLS' for t in n.targets))
    require(isinstance(tools,ast.List) and len(tools.elts)==10,'Home must contain ten cards')
    names=[];cmd=None
    for item in tools.elts:
        pairs={ast.literal_eval(k):v for k,v in zip(item.keys,item.values)}
        title=ast.literal_eval(pairs['title']);names.append(title)
        if title=='Decrypt Backup':cmd=ast.literal_eval(pairs['command'])
    require(names[2]=='Decrypt Backup' and names.count('Decrypt Backup')==1,'Backup card placement mismatch')
    require(cmd==['/usr/bin/core-vault-backup','decrypt'],'Backup card command mismatch')
    t=ast.parse((inc/'usr/lib/core-vault-installer/target.py').read_text())
    policy=next(n for n in t.body if isinstance(n,ast.FunctionDef) and n.name=='verify_policy')
    loops=[n for n in policy.body if isinstance(n,ast.For) and isinstance(n.target,ast.Name) and n.target.id=='cmd']
    allowed=ast.literal_eval(loops[0].iter);denied=ast.literal_eval(loops[1].iter)
    require(allowed==(['/usr/local/sbin/core-vault-end-session','poweroff'],['/usr/local/sbin/core-vault-end-session','reboot']),
            'Unexpected allowed sudo command')
    for command in [['/bin/sh'],['/usr/bin/true'],['/usr/bin/veracrypt','--core-service'],['/usr/bin/7z'],['/usr/bin/arqiver']]:
        require(command in denied,'Missing explicit sudo denial: '+repr(command))
    for rel in ['config/package-lists/core-vault.list.chroot','tools/core-vault/manifests/core-vault.list.chroot']:
        packages=[l.split('#',1)[0].strip() for l in (root/rel).read_text().splitlines()]
        for p in ('tar','gpg','zenity','exfatprogs','xdg-utils'):require(p in packages,'Missing runtime package: '+p)
    source=root/'tools/core-vault/backup-src'
    raw=subprocess.check_output(['dpkg-deb','--fsys-tarfile',str(package)])
    with tarfile.open(fileobj=io.BytesIO(raw)) as tar:
        members={m.name.removeprefix('./'):m for m in tar.getmembers()}
        for name in ('backup.py','setup.py','self-test.py','password_dialog.py','message_dialog.py','gui-test.py',
                     'gpg_backend.py','gpg-self-test.py','recovery_dialog.py','layered_backend.py'):
            data=(source/'src'/name).read_bytes();ast.parse(data)
            member=members['usr/lib/core-vault-backup/'+name]
            require(member.isfile() and tar.extractfile(member).read()==data,'Package/source mismatch: '+name)
    session=(inc/'usr/local/bin/core-vault-session').read_text()
    require(session.count('/usr/bin/core-vault-backup-setup ')==1,'Expected one explicit session provisioning call')
    for rel in ['config/hooks/live/0940-core-vault-backup.hook.chroot',
                'config/hooks/live/0950-core-vault-installer-check.hook.chroot',
                'config/includes.chroot/usr/local/bin/core-vault-session']:
        subprocess.run(['/bin/sh','-n',str(root/rel)],check=True)
    hook=(root/'config/hooks/live/0940-core-vault-backup.hook.chroot').read_text()
    require('/usr/bin/timeout 600 /usr/bin/core-vault-backup-self-test' in hook,'Real engine test gate missing')
    require('/usr/bin/timeout 180 /usr/bin/core-vault-gpg-self-test' in hook,'Real GPG test gate missing')
    hook0950=(root/'config/hooks/live/0950-core-vault-installer-check.hook.chroot').read_text()
    for rel in ('/usr/bin/core-vault-backup','/usr/lib/core-vault-backup/backup.py','/etc/core-vault/backup-build.json'):
        require(repr(rel) in hook0950,'Missing installer payload record: '+rel)
    require('/usr/bin/core-vault-backup-gui-test' in hook, 'Paired dialog Qt test is not gated in the image')
    require(repr('/usr/lib/core-vault-backup/password_dialog.py') in hook0950,'Paired dialog missing from installer manifest')
    require('python3-pyside6.qtwidgets' in subprocess.check_output(['dpkg-deb','-f',str(package),'Depends'],text=True),'Missing declared Qt dependency')
    require(repr('/usr/lib/core-vault-backup/message_dialog.py') in hook0950,'Dark dialog missing from installer manifest')
    for rel in ('/usr/bin/gpg','/usr/lib/core-vault-backup/gpg_backend.py',
                '/usr/lib/core-vault-backup/recovery_dialog.py',
                '/usr/share/applications/core-vault-decrypt-gpg.desktop',
                '/usr/bin/core-vault-gpg-self-test'):
        require(repr(rel) in hook0950,'GPG runtime missing from installer manifest: '+rel)
    depends=subprocess.check_output(['dpkg-deb','-f',str(package),'Depends'],text=True)
    require('gpg (>= 2.4)' in depends,'Missing supported GnuPG dependency')

    require(not list((root/'config/packages.chroot').glob('arqiver_*.deb')), 'Obsolete archive manager remains staged')
    for forbidden in ('7zip', 'arqiver'):
        require(forbidden not in depends, 'Obsolete encryption dependency remains')
    require('ClearClipboard=false' in (inc/'etc/skel/.config/keepassxc/keepassxc.ini').read_text(),
            'Fresh KeePassXC profile must disable automatic clipboard clearing')
    require((inc/'etc/skel/.config/keepassxc/keepassxc.ini').read_bytes() ==
            (template/'etc/skel/.config/keepassxc/keepassxc.ini').read_bytes(), 'KeePassXC profile mismatch')
    require('usr/lib/core-vault-backup/layered_backend.py' in hook0950, 'Layered backend missing from installer payload')

    print('VAULT ENCRYPTED BACKUP SOURCE + PACKAGE CHECK PASSED')
    print('Real GPG/TAR testing runs separately and in the chroot hook. GUI/boot recovery remains a VM test.')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project',type=Path,default=Path(__file__).resolve().parents[2])
    args=p.parse_args();check(args.project.expanduser().resolve(strict=True))
