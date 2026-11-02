#!/usr/bin/python3
"""Calamares target finalization. Requires a separate ext4 target and install boot.
No partitioning here: Calamares and its pre-write disk guard own that operation.
"""
from __future__ import annotations
import hashlib,json,os,re,shutil,stat,subprocess
from pathlib import Path
ENV={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LC_ALL':'C.UTF-8','LANG':'C.UTF-8','DEBIAN_FRONTEND':'noninteractive'}
PAYLOAD=Path('/etc/core-vault/installer-payload.json')
REPORT='etc/core-vault/installation.json'
PRIVATE='/home/vault/Private Workspace'
PRIVATE_FSTAB=r'/home/vault/Private\040Workspace'
OFFLINE_UNITS=('NetworkManager.service','ModemManager.service','bluetooth.service','iwd.service',
    'networking.service','systemd-networkd.service','systemd-networkd.socket',
    'systemd-networkd-wait-online.service','wpa_supplicant.service')
BLOCKED_UNITS=('getty@tty1.service','autovt@tty1.service','swap.target','sleep.target',
    'suspend.target','hibernate.target','hybrid-sleep.target','suspend-then-hibernate.target')
class TargetError(RuntimeError): pass

def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()

def safe(root,name):
    """Allow merged-/usr links inside target, but never follow links outside it."""
    p=root/name.lstrip('/')
    if not p.resolve(strict=False).is_relative_to(root):
        raise TargetError('Path escapes the target: '+name)
    return p

def validate_target(root):
    if not isinstance(root,(str,Path)) or not str(root): raise TargetError('No target root supplied.')
    p=Path(root)
    if not p.is_absolute() or p==Path('/') or p.resolve()!=p or not os.path.ismount(p):
        raise TargetError('Not a separate mounted target. Refusing to touch it.')
    if os.geteuid()!=0: raise TargetError('Target jobs must be called by the installer as root.')
    flags=Path('/proc/cmdline').read_text().split()
    if 'boot=live' not in flags or 'core-vault.install=1' not in flags:
        raise TargetError('Not running in the dedicated Live installation session.')
    result=subprocess.run(['/usr/bin/findmnt','--json','--mountpoint',str(p),
        '--output','TARGET,SOURCE,FSTYPE'],capture_output=True,text=True,check=True,timeout=5,env=ENV)
    rows=json.loads(result.stdout).get('filesystems',[])
    if len(rows)!=1 or rows[0]['fstype']!='ext4' or rows[0]['target']!=str(p):
        raise TargetError('The target must be a separate ext4 filesystem.')
    source=rows[0]['source'].split('[')[0]
    if not source.startswith('/dev/') or not stat.S_ISBLK(os.stat(source).st_mode):
        raise TargetError('The installed root is not backed by a block device.')
    release=safe(p,'etc/os-release').read_text()
    if not re.search(r'^ID=\"?debian\"?$',release,re.M) or 'VERSION_ID="13"' not in release:
        raise TargetError('Expected Debian 13 target.')
    return p

def call(root,args,timeout=180,allow_failure=False):
    result=subprocess.run(['/usr/sbin/chroot',str(root),*args],text=True,capture_output=True,
        env=ENV,timeout=timeout)
    if result.returncode and not allow_failure:
        raise TargetError('Target command failed: '+repr(args)+'\n'+(result.stdout+result.stderr)[-12000:])
    return result if allow_failure else result.stdout

def put(root,name,text,mode=0o644):
    p=safe(root,name);p.parent.mkdir(parents=True,exist_ok=True)
    if p.is_symlink(): p.unlink()
    p.write_text(text);p.chmod(mode);os.chown(p,0,0)

def link(root,name,target):
    p=root/name.lstrip('/')
    if not p.parent.resolve().is_relative_to(root): raise TargetError('Escaping symlink parent.')
    p.parent.mkdir(parents=True,exist_ok=True)
    if p.is_symlink() or p.is_file(): p.unlink()
    if p.exists(): raise TargetError('Unexpected directory at symlink destination: '+name)
    p.symlink_to(target)

def remove(root,name):
    p=root/name.lstrip('/')
    if not p.parent.resolve().is_relative_to(root): raise TargetError('Escaping removal parent.')
    if p.is_symlink() or p.is_file(): p.unlink()
    elif p.is_dir(): shutil.rmtree(p)

def add_fstab(text):
    """Preserve root/EFI records; replace only our volatile mounts and remove swap."""
    out=[]
    for line in text.splitlines():
        cols=line.split()
        if line.startswith('# Bitcoin Core Vault volatile'): continue
        if cols and not line.lstrip().startswith('#'):
            if len(cols)<6: raise TargetError('Malformed fstab entry: '+line)
            mount=cols[1].replace(r'\040',' ')
            if cols[2]=='swap' or mount in (PRIVATE,'/var/log','/tmp','/var/tmp','/media','/var/spool/cups','/var/cache/cups'): continue
            if mount in ('/home','/home/vault'):
                raise TargetError('Unexpected separate or volatile home mount in dedicated-disk layout.')
        out.append(line)
    out += ['# Bitcoin Core Vault volatile system scratch; private home uses native mount units.',
        'tmpfs /var/log tmpfs noswap,nosuid,nodev,noexec,mode=0755,size=64M 0 0',
        'tmpfs /tmp tmpfs noswap,nosuid,nodev,noexec,mode=1777,size=10% 0 0',
        'tmpfs /var/tmp tmpfs noswap,nosuid,nodev,noexec,mode=1777,size=5% 0 0',
        # UDisks creates mountpoint names from removable-media labels/UUIDs.
        # Keep those session metadata off the internal filesystem too. Actual
        # USB/external filesystems are still mounted normally below /media.
        'tmpfs /media tmpfs noswap,nosuid,nodev,noexec,mode=0755,size=8M 0 0',
        'tmpfs /var/spool/cups tmpfs noswap,nosuid,nodev,noexec,mode=0710,uid=0,gid=7,size=32M 0 0',
        'tmpfs /var/cache/cups tmpfs noswap,nosuid,nodev,noexec,mode=0770,uid=0,gid=7,size=16M 0 0']
    return '\n'.join(out)+'\n'

def payload_verify(root):
    obj=json.loads(PAYLOAD.read_text()); files=obj.get('files',{})
    if obj.get('schema')!=1 or not {'usr/local/bin/bitcoin-qt','usr/local/bin/bitcoin-cli',
        'usr/local/bin/core-vault-home','usr/local/bin/core-vault-session',
        'usr/bin/core-vault-backup','usr/lib/core-vault-backup/backup.py',
        'usr/bin/gpg','usr/lib/core-vault-backup/gpg_backend.py',
        'usr/lib/core-vault-backup/recovery_dialog.py',
        'usr/lib/core-vault-backup/layered_backend.py','usr/bin/tar',
        'usr/share/applications/core-vault-decrypt-gpg.desktop',
        'etc/core-vault-backup.require-private-workspace'}.issubset(files):
        raise TargetError('Incomplete immutable payload manifest.')
    for name,digest in files.items():
        if not re.fullmatch(r'[0-9a-f]{64}',digest): raise TargetError('Bad payload digest.')
        p=safe(root,name)
        if not p.is_file() or sha(p)!=digest:
            raise TargetError('Installed payload differs from the build image: '+name)
    return files

def verify_policy(root):
    call(root,['/usr/sbin/visudo','-c'])
    prefix=['/usr/sbin/runuser','-u','vault','--','/usr/bin/sudo','-n','-l','--']
    for cmd in (['/usr/local/sbin/core-vault-end-session','poweroff'],
                ['/usr/local/sbin/core-vault-end-session','reboot']):
        call(root,prefix+cmd)
    for cmd in (['/bin/sh'],['/usr/bin/veracrypt'],['/usr/bin/veracrypt','--core-service'],
                ['/usr/bin/true'],['/usr/bin/true','unexpected'],
                ['/usr/bin/7z'],['/usr/bin/gpg'],['/usr/bin/arqiver'],['/usr/bin/core-vault-backup'],
                ['/usr/bin/systemctl','--force','poweroff'],
                ['/usr/bin/systemctl','--no-block','poweroff'],
                ['/usr/bin/systemctl','--no-block','reboot'],
                ['/usr/local/sbin/core-vault-end-session','poweroff','unexpected'],
                ['/usr/local/sbin/core-vault-installer']):
        if call(root,prefix+cmd,allow_failure=True).returncode==0:
            raise TargetError('Unexpected privileged command permitted: '+repr(cmd))
    for name in ('usr/bin/veracrypt','etc/sudoers.d/92-core-vault-veracrypt',
                 'etc/modules-load.d/core-vault-veracrypt.conf'):
        p=safe(root,name)
        if p.exists() or p.is_symlink():
            raise TargetError('Retired container integration remained in target: '+name)
    for unit in OFFLINE_UNITS+BLOCKED_UNITS:
        p=root/'etc/systemd/system'/unit
        if not p.is_symlink() or os.readlink(p)!='/dev/null':
            raise TargetError('Expected systemd mask missing: '+unit)
    for user in ('root','vault'):
        line=next((x for x in safe(root,'etc/shadow').read_text().splitlines() if x.startswith(user+':')),None)
        if not line or not line.split(':')[1].startswith(('!','*')):
            raise TargetError('Password login must remain locked for '+user)

def configure(root):
    root=validate_target(root)
    files=payload_verify(root)
    # Refuse an unexpected immutable account; no takeover of existing user data.
    passwd=[x.split(':') for x in safe(root,'etc/passwd').read_text().splitlines()]
    if any(len(x)>2 and x[2]=='1000' and x[0]!='vault' for x in passwd):
        raise TargetError('UID 1000 belongs to another account.')
    groups=[x.split(':') for x in safe(root,'etc/group').read_text().splitlines()]
    if any(len(x)>2 and x[2]=='1000' and x[0]!='vault' for x in groups):
        raise TargetError('GID 1000 belongs to another group.')
    if not any(x[0]=='vault' for x in groups):
        call(root,['/usr/sbin/groupadd','--gid','1000','vault'])
    if not any(x[0]=='vault' for x in passwd):
        call(root,['/usr/sbin/useradd','--create-home','--uid','1000','--gid','1000',
            '--home-dir','/home/vault','--shell','/bin/bash','--comment','Bitcoin Core Vault','vault'])
    account=call(root,['/usr/bin/getent','passwd','vault']).strip().split(':')
    if len(account)<7 or account[2:4]!=['1000','1000'] or account[5]!='/home/vault':
        raise TargetError('Vault account identity/home differs from expected values.')
    for user in ('root','vault'): call(root,['/usr/bin/passwd','-l',user])
    present={g[0] for g in groups}
    wanted=[g for g in ('audio','video','plugdev','cdrom','lp') if g in present]
    call(root,['/usr/sbin/usermod','-G',','.join(wanted),'vault'])
    home=safe(root,'home/vault');home.mkdir(parents=True,exist_ok=True)
    # This underlying disk directory must never be a writable fallback.
    # Static defaults are copied from /etc/skel into RAM by core-vault-prepare.
    os.chown(home,0,0);home.chmod(0o000)
    for name in ('etc/sudoers.d/80-core-vault-installer','etc/sudoers.d/80-core-offline-installer',
                 'etc/sudoers.d/live','etc/sudoers.d/90-core-signer-poweroff',
                 'etc/skel/.xinitrc','etc/skel/.xsession','home/vault/.xinitrc',
                 'usr/share/xsessions/core-signer.desktop','etc/default/grub.d/core-signer.cfg'):
        remove(root,name)
    # Existing exact Vault poweroff/reboot permissions are copied, not broadened.
    put(root,'etc/hostname','core-vault\n')
    put(root,'etc/hosts','127.0.0.1 localhost\n127.0.1.1 core-vault\n::1 localhost ip6-localhost ip6-loopback\n')
    put(root,'etc/default/locale','LANG=en_US.UTF-8\nLANGUAGE=en\n')
    keyboard=safe(root,'etc/default/keyboard')
    if not keyboard.is_file() or not re.search(r'^XKBLAYOUT="?[A-Za-z0-9_,+-]+"?$',keyboard.read_text(),re.M):
        raise TargetError('The selected keyboard layout was not saved.')
    put(root,'etc/fstab',add_fstab(safe(root,'etc/fstab').read_text()))
    # Keep the working display-setup helper at its REAL inherited path.
    lightdm=safe(root,'etc/lightdm/lightdm.conf.d/50-core-signer.conf').read_text()
    if not all(x in lightdm for x in ('autologin-user=vault','autologin-session=core-vault',
        'display-setup-script=/usr/share/core-signer/lightdm-display-setup.sh')):
        raise TargetError('Autologin/display setup differs from reviewed Vault settings.')
    for unit in OFFLINE_UNITS+BLOCKED_UNITS:
        link(root,'etc/systemd/system/'+unit,'/dev/null')
    link(root,'etc/systemd/system/default.target','/usr/lib/systemd/system/graphical.target')
    link(root,'etc/systemd/system/display-manager.service','/usr/lib/systemd/system/lightdm.service')
    for unit in ('core-signer-offline.service','core-signer-no-swap.service'):
        link(root,'etc/systemd/system/multi-user.target.wants/'+unit,'../'+unit)
    link(root,'etc/systemd/system/multi-user.target.wants/nftables.service','/usr/lib/systemd/system/nftables.service')
    put(root,'etc/default/grub.d/core-vault.cfg',
        'GRUB_DISTRIBUTOR="Bitcoin Core Vault"\nGRUB_TIMEOUT_STYLE=hidden\nGRUB_TIMEOUT=0\n'
        'GRUB_CMDLINE_LINUX_DEFAULT="quiet splash loglevel=3 systemd.show_status=false vt.global_cursor_default=0"\n'
        'GRUB_CMDLINE_LINUX="noresume"\nGRUB_DISABLE_OS_PROBER=true\n')
    # Drop only Calamares itself. Avoid risky dependency autoremove.
    policy=safe(root,'usr/sbin/policy-rc.d')
    previous=policy.read_bytes() if policy.is_file() else None
    mode=stat.S_IMODE(policy.stat().st_mode) if policy.is_file() else 0o755
    put(root,'usr/sbin/policy-rc.d','#!/bin/sh\nexit 101\n',0o755)
    try:
        call(root,['/usr/bin/dpkg','--remove','calamares'],timeout=300)
    finally:
        if previous is None: policy.unlink(missing_ok=True)
        else: policy.write_bytes(previous);policy.chmod(mode)
    for name in ('etc/calamares','usr/local/sbin/core-vault-installer',
                 'usr/local/bin/core-vault-installer-session','usr/lib/core-vault-installer'):
        remove(root,name)
    report={'schema':1,'stage':'target-configured','keyboard':keyboard.read_text(),
            'payload_files':files,'storage':'persistent-os-with-ram-only-private-home-v1',
            'runtime_acceptance':'PENDING: reboot without ISO and complete VM tests'}
    put(root,REPORT,json.dumps(report,indent=2)+'\n')
    verify_policy(root)

def verify(root):
    root=validate_target(root);verify_policy(root);payload_verify(root)
    for name in ('usr/bin/calamares','etc/calamares','usr/lib/core-vault-installer',
                 'usr/local/sbin/core-vault-installer','etc/sudoers.d/80-core-vault-installer'):
        p=root/name
        if p.exists() or p.is_symlink(): raise TargetError('Installer remained in target: '+name)
    cfg=safe(root,'boot/grub/grub.cfg').read_text()
    linux_lines=[l for l in cfg.splitlines() if re.match(r'^\s*linux(?:efi|16)?\s',l)]
    if not linux_lines or any(re.search(r'\bboot=live\b|\btoram\b|core-(?:vault|offline)\.install=',l) for l in linux_lines):
        raise TargetError('Installed boot entries are missing or still use Live parameters.')
    if not list((root/'boot').glob('vmlinuz-*')) or not list((root/'boot').glob('initrd.img-*')):
        raise TargetError('Installed kernel or initramfs is missing.')
    if Path('/sys/firmware/efi').is_dir():
        # Fallback loader permits boot even without a retained firmware NVRAM entry.
        fallback=root/'boot/efi/EFI/BOOT/BOOTX64.EFI'
        if not fallback.is_file(): raise TargetError('UEFI fallback bootloader is missing.')
    rows=[l.split() for l in safe(root,'etc/fstab').read_text().splitlines()
          if l.strip() and not l.lstrip().startswith('#')]
    if any(r[2]=='swap' or r[1] in ('/home','/home/vault',PRIVATE_FSTAB) for r in rows):
        raise TargetError('Unexpected swap or a mount conflicting with the private home units.')
    media=[r for r in rows if r[1]=='/media']
    if len(media)!=1 or media[0][0]!='tmpfs' or media[0][2]!='tmpfs' or not {'noswap','nosuid','nodev','noexec'}.issubset(media[0][3].split(',')):
        raise TargetError('Removable-media mountpoint metadata must remain in protected RAM storage.')
    for unit in ('home-vault.mount', r'run-core\x2dvault.mount', 'core-vault-prepare.service'):
        if not safe(root,'etc/systemd/system/'+unit).is_file():
            raise TargetError('Private session unit is missing: '+unit)
    base=safe(root,'home/vault').stat()
    if base.st_uid!=0 or stat.S_IMODE(base.st_mode)!=0:
        raise TargetError('The persistent home fallback must be inaccessible to Vault.')
    report=json.loads(safe(root,REPORT).read_text());report['stage']='installed-checks-passed'
    put(root,REPORT,json.dumps(report,indent=2)+'\n')
