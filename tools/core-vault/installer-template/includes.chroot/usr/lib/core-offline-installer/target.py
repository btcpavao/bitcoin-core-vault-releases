#!/usr/bin/python3
"""Calamares target-only finalization; never operates on the running root."""
from __future__ import annotations
import hashlib, json, os, re, shutil, stat, subprocess
from pathlib import Path

ENV={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LC_ALL':'C.UTF-8','LANG':'C.UTF-8','DEBIAN_FRONTEND':'noninteractive'}
POWER_RULE='Defaults:vault !requiretty\nsigner ALL=(root) NOPASSWD: /usr/bin/systemctl --no-block poweroff\n'
PRESERVED=['usr/local/bin/core-vault-session','usr/local/bin/core-vault-shutdown-dialog',
           'usr/local/bin/core-vault-usb-sidebar','usr/local/bin/bitcoin-qt','usr/local/bin/bitcoin-cli']
class TargetError(RuntimeError): pass

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()

def validate_target(root):
    p=Path(root)
    if not p.is_absolute() or p.resolve()!=p or p==Path('/') or not os.path.ismount(p):
        raise TargetError('Target is not a separate mounted filesystem; refusing to configure it.')
    osrelease=(p/'etc/os-release').read_text()
    if 'ID=debian' not in osrelease or 'VERSION_ID="13"' not in osrelease:
        raise TargetError('Expected a Debian 13 target, not another operating system.')
    return p

def call(root,args,timeout=180):
    p=subprocess.run(['/usr/sbin/chroot',str(root),*args],text=True,
                     stdout=subprocess.PIPE,stderr=subprocess.STDOUT,env=ENV,timeout=timeout)
    if p.returncode:
        raise TargetError('Target command failed: '+repr(args)+'\n'+p.stdout[-12000:])
    return p.stdout

def put(root,name,text,mode=0o644):
    p=root/name.lstrip('/')
    p.parent.mkdir(parents=True,exist_ok=True)
    if p.is_symlink(): p.unlink()
    p.write_text(text);p.chmod(mode);os.chown(p,0,0)

def link(root,name,target):
    p=root/name.lstrip('/');p.parent.mkdir(parents=True,exist_ok=True)
    if p.is_symlink() or p.exists(): p.unlink()
    p.symlink_to(target)

def remove(root,name):
    p=root/name.lstrip('/')
    if p.is_symlink() or p.is_file(): p.unlink()
    elif p.is_dir(): shutil.rmtree(p)

def add_fstab(text):
    lines=[]

    for line in text.splitlines():
        cols=line.split()

        if cols and not line.lstrip().startswith('#'):
            if len(cols)>=3 and (
                cols[2]=='swap'
                or cols[1] in (
                    '/home/vault/Private\040Workspace',
                    '/var/log',
                )
            ):
                continue

        lines.append(line)

    lines += [
        '# Bitcoin Core Vault: persistent home; Private Workspace and logs are volatile.',
        'tmpfs /home/vault/Private\040Workspace tmpfs nosuid,nodev,noexec,mode=0700,uid=1000,gid=1000,size=50% 0 0',
        'tmpfs /var/log tmpfs nosuid,nodev,noexec,mode=0755,size=64M 0 0',
    ]

    return '\n'.join(lines)+'\n'


def configure(root):
    root=validate_target(root)
    # This code only runs after unpackfs copied the immutable image, NOT Live /.
    for name in PRESERVED:
        if not (root/name).is_file() or sha('/'+name)!=sha(root/name):
            raise TargetError('The installed payload does not match the running immutable image: '+name)
    # The immutable image has no live-config-created user. Existing conflicting
    # UID is a hard error, not a silent takeover of another user's files.
    lines=(root/'etc/passwd').read_text().splitlines()
    signers=[x.split(':') for x in lines if x.startswith('vault:')]
    uid1000=[x.split(':') for x in lines if len(x.split(':'))>2 and x.split(':')[2]=='1000']
    if uid1000 and uid1000[0][0]!='vault': raise TargetError('UID 1000 belongs to another account.')
    if not signers:
        call(root,['/usr/sbin/useradd','--create-home','--uid','1000','--user-group',
                   '--shell','/bin/bash','--comment','Bitcoin Core Vault','vault'])
    account=call(root,['/usr/bin/getent','passwd','vault']).strip().split(':')
    if account[2:4]!=['1000','1000']: raise TargetError('vault must have UID/GID 1000.')
    for user in ('root','vault'): call(root,['/usr/bin/passwd','-l',user])
    # No broad groups. Rootless input/storage policy is handled by logind/polkit.
    wanted=[]
    for group in ('audio','video','plugdev','cdrom'):
        if any(x.startswith(group+':') for x in (root/'etc/group').read_text().splitlines()): wanted.append(group)
    call(root,['/usr/sbin/usermod','-G',','.join(wanted),'vault'])
    home=root/'home/vault';home.mkdir(parents=True,exist_ok=True)
    os.chown(home,1000,1000);home.chmod(0o700)

    private_workspace=home/'Private Workspace'
    private_workspace.mkdir(parents=True,exist_ok=True)
    os.chown(private_workspace,1000,1000)
    private_workspace.chmod(0o700)
    # Exact installed-mode policy; no generic root application launcher survives.
    remove(root,'/etc/sudoers.d/80-core-offline-installer')
    remove(root,'/etc/sudoers.d/live')
    put(root,'/etc/sudoers.d/90-core-vault-poweroff',POWER_RULE,0o440)
    for name in ('/etc/skel/.xinitrc','/etc/skel/.xsession','/home/vault/.xinitrc'):
        remove(root,name)
    put(root,'/etc/hostname','core-vault\n')
    put(root,'/etc/hosts','127.0.0.1 localhost\n127.0.1.1 core-vault\n::1 localhost ip6-localhost ip6-loopback\n')
    put(root,'/etc/default/locale','LANG=en_US.UTF-8\nLANGUAGE=en\n')
    put(root,'/etc/locale.gen','en_US.UTF-8 UTF-8\n')
    call(root,['/usr/sbin/locale-gen'])
    put(root,'/etc/timezone','Etc/UTC\n')
    link(root,'/etc/localtime','/usr/share/zoneinfo/Etc/UTC')
    # Keyboard was already written by the upstream keyboard job. Validate it,
    # do not overwrite it with US defaults.
    keyboard=root/'etc/default/keyboard'
    if not keyboard.is_file() or not re.search(r'^XKBLAYOUT=.+',keyboard.read_text(),re.M):
        raise TargetError('The selected keyboard layout was not written.')
    put(root,'/etc/fstab',add_fstab((root/'etc/fstab').read_text()))
    # Installed entry bypasses the Live installer router.
    put(root,'/usr/share/xsessions/core-vault.desktop','''[Desktop Entry]
Name=Bitcoin Core Vault
Comment=Dedicated offline Bitcoin Core Vault environment
Exec=/usr/local/bin/core-vault-session
Type=Application
DesktopNames=CoreVault
''')
    link(root,'/etc/systemd/system/default.target','/usr/lib/systemd/system/graphical.target')
    link(root,'/etc/systemd/system/display-manager.service','/usr/lib/systemd/system/lightdm.service')
    for unit in ('getty@tty1.service','autovt@tty1.service','swap.target',
                 'sleep.target','suspend.target','hibernate.target','hybrid-sleep.target'):
        link(root,'/etc/systemd/system/'+unit,'/dev/null')
    put(root,'/etc/systemd/system/lightdm.service.d/30-core-offline-safety.conf','''[Unit]
Requires=nftables.service core-vault-offline.service core-vault-no-swap.service
After=nftables.service core-vault-offline.service core-vault-no-swap.service
''')
    put(root,'/etc/default/grub.d/core-vault.cfg','''GRUB_DISTRIBUTOR="Bitcoin Core Vault"
GRUB_TIMEOUT_STYLE=hidden
GRUB_TIMEOUT=0
GRUB_CMDLINE_LINUX_DEFAULT="quiet splash loglevel=3 systemd.show_status=false vt.global_cursor_default=0"
GRUB_CMDLINE_LINUX=""
GRUB_DISABLE_OS_PROBER=true
''')
    # Keep root-run launch/display scripts immutable to the regular user.
    display=root/'usr/share/core-vault/lightdm-display-setup.sh'
    os.chown(display,0,0);display.chmod(0o755)
    # Prevent dpkg scripts from starting/stopping services in the installer host.
    policy=root/'usr/sbin/policy-rc.d'
    previous=policy.read_bytes() if policy.is_file() else None
    previous_mode=stat.S_IMODE(policy.stat().st_mode) if policy.is_file() else 0o755
    put(root,'/usr/sbin/policy-rc.d','#!/bin/sh\nexit 101\n',0o755)
    try:
        call(root,['/usr/bin/dpkg','--remove','calamares'],timeout=240)
    finally:
        if previous is None: policy.unlink(missing_ok=True)
        else: policy.write_bytes(previous);policy.chmod(previous_mode)
    for name in ('/etc/calamares','/usr/local/sbin/core-offline-installer',
                 '/usr/local/bin/core-offline-entry','/usr/lib/core-offline-installer'):
        remove(root,name)
    # Do not autoremove dependencies: that risks breaking the Core GUI.
    manifest={'stage':'target-configured','keyboard':keyboard.read_text(),
              'core_payload':{n:sha(root/n) for n in PRESERVED},
              'note':'Installation checks are not proof of physical boot or shutdown.'}
    put(root,'/etc/core-vault/installation.json',json.dumps(manifest,indent=2)+'\n')
    verify_policy(root)
    return None

def verify_policy(root):
    call(root,['/usr/sbin/visudo','-c'])
    # Validate policy as the actual target account, without issuing a poweroff.
    call(root,['/usr/sbin/runuser','-u','vault','--','/usr/bin/sudo','-n','-l','--',
               '/usr/bin/systemctl','--no-block','poweroff'])
    for args in (['/bin/sh'],['/usr/bin/systemctl','--no-block','reboot'],
                 ['/usr/bin/systemctl','--force','poweroff']):
        p=subprocess.run(['/usr/sbin/chroot',str(root),'/usr/sbin/runuser','-u','vault','--',
                          '/usr/bin/sudo','-n','-l','--',*args],env=ENV,
                          capture_output=True,timeout=30)
        if p.returncode==0: raise TargetError('Unexpected broad sudo access: '+repr(args))

def verify(root):
    root=validate_target(root);verify_policy(root)
    for n in PRESERVED:
        if sha('/'+n)!=sha(root/n): raise TargetError('Core payload changed: '+n)
    for missing in ('/etc/sudoers.d/80-core-offline-installer','/usr/bin/calamares',
                    '/usr/local/sbin/core-offline-installer'):
        if (root/missing.lstrip('/')).exists(): raise TargetError('Installer was not removed: '+missing)
    cfg=(root/'boot/grub/grub.cfg').read_text()
    if 'linux' not in cfg or re.search(r'\bboot=live\b|\btoram\b|core-offline\.install=',cfg):
        raise TargetError('Installed GRUB is missing a normal Linux boot or contains Live parameters.')
    if not list((root/'boot').glob('vmlinuz-*')) or not list((root/'boot').glob('initrd.img-*')):
        raise TargetError('Target kernel/initramfs missing.')
    if any(len(x.split())>=3 and x.split()[2]=='swap' for x in (root/'etc/fstab').read_text().splitlines() if not x.lstrip().startswith('#')):
        raise TargetError('Unexpected swap entry.')
    report=root/'etc/core-offline/installation.json'
    obj=json.loads(report.read_text());obj['stage']='installed-checks-passed'
    put(root,'/etc/core-vault/installation.json',json.dumps(obj,indent=2)+'\n')
    return None
