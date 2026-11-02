#!/usr/bin/python3
"""Source/ISO coherence gate; runtime and forensic acceptance run separately."""
import argparse
import ast
import configparser
import hashlib
import posixpath
from pathlib import Path
import shlex
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[2]
INC=ROOT/'config/includes.chroot'
REQUIRED=(
    'usr/lib/core-vault/runtime.py','usr/lib/core-vault/export.py',
    'usr/local/libexec/core-vault-prepare','usr/local/libexec/core-vault-destroy',
    'usr/local/sbin/core-vault-end-session','usr/local/bin/core-vault-finish',
    'usr/local/bin/core-vault-wallet-backup','usr/local/bin/core-vault-security-check',
    'usr/local/bin/core-vault-storage-check','usr/local/bin/core-vault-session',
    'usr/local/bin/core-vault-bitcoin','usr/local/bin/core-vault-keepassxc',
    'usr/local/bin/core-vault-numlock','usr/local/bin/core-vault-open-passphrase',
    'usr/local/bin/core-vault-taskbar',
    'usr/local/bin/core-vault-show-home',
    'usr/share/core-vault/icons/debian-white.svg','usr/share/core-vault/icons/debian-white.png',
    'usr/local/libexec/core-vault-core-session','usr/lib/core-vault-installer/target.py',
    'usr/local/bin/core-vault-install-check',
    'etc/systemd/system/home-vault.mount',r'etc/systemd/system/run-core\x2dvault.mount',
    'etc/systemd/system/tmp.mount','etc/systemd/system/var-tmp.mount',
    'etc/systemd/system/core-vault-prepare.service','etc/systemd/system/core-vault-end-session@.service',
    'etc/systemd/system/core-vault-workspace-check.service',
    'etc/systemd/system/lightdm.service.d/35-core-vault-safety.conf',
    'etc/initramfs-tools/conf.d/core-vault-noresume',
    'etc/sysctl.d/80-core-vault-memory.conf','etc/security/limits.d/core-vault.conf',
    'etc/systemd/system.conf.d/core-vault.conf','etc/systemd/logind.conf.d/core-vault.conf',
    'etc/sudoers.d/91-core-vault-poweroff')
SOURCE_ONLY=(
    'etc/systemd/coredump.conf.d/core-signer.conf',
    'etc/systemd/journald.conf.d/core-signer.conf',
    'etc/systemd/sleep.conf.d/core-signer.conf',
    'etc/systemd/system/core-signer-no-swap.service',
    'usr/lib/core-vault-installer/disk_safety.py',
    'usr/local/bin/core-vault-installer-session',
    'usr/local/sbin/core-vault-installer')

def check():
    for relative in REQUIRED+SOURCE_ONLY:
        path=INC/relative
        if not path.is_file() or path.is_symlink():
            raise RuntimeError('Missing private-session source: '+relative)
        text=path.read_text() if path.suffix != '.png' else ''
        if path.suffix=='.py' or text.startswith('#!/usr/bin/python3'):
            ast.parse(text,relative)
        if text.startswith('#!/bin/sh'):
            subprocess.run(['/bin/sh','-n',str(path)],check=True)
        template=ROOT/'tools/core-vault/runtime-template'/relative
        if relative in REQUIRED and (not template.is_file() or template.read_bytes()!=path.read_bytes()):
            raise RuntimeError('Private-session runtime template mismatch: '+relative)
    text=(INC/'etc/systemd/system'/r'run-core\x2dvault.mount').read_text()
    if 'noswap,nodev,nosuid,noexec' not in text or 'Where=/run/core-vault' not in text:
        raise RuntimeError('RAM mount protection is incomplete.')
    for name, target, size in (('tmp.mount','/tmp','10%%'),('var-tmp.mount','/var/tmp','5%%')):
        unit=configparser.ConfigParser(interpolation=None)
        unit.read(INC/'etc/systemd/system'/name)
        if (unit.get('Mount','What')!='tmpfs' or unit.get('Mount','Type')!='tmpfs'
                or unit.get('Mount','Where')!=target
                or set(unit.get('Mount','Options').split(','))!=
                    {'noswap','nosuid','nodev','noexec','mode=1777','size='+size}
                or 'local-fs.target' not in unit.get('Install','WantedBy').split()
                or unit.get('Unit','DefaultDependencies')!='no'
                or 'local-fs-pre.target' not in unit.get('Unit','After').split()
                or 'local-fs.target' in unit.get('Unit','After').split()
                or 'umount.target' not in unit.get('Unit','Conflicts').split()
                or not {'local-fs.target','umount.target','systemd-tmpfiles-setup.service',
                        'core-vault-prepare.service','core-vault-workspace-check.service','lightdm.service'}
                    .issubset(unit.get('Unit','Before').split())):
            raise RuntimeError('Live/installed protected system temporary mount is incomplete: '+name)
        for relative in ('etc/systemd/system/core-vault-prepare.service',
                         'etc/systemd/system/core-vault-workspace-check.service',
                         'etc/systemd/system/lightdm.service.d/35-core-vault-safety.conf'):
            dependency=configparser.ConfigParser(interpolation=None)
            dependency.read(INC/relative)
            if any(name not in dependency.get('Unit',field).split() for field in ('Requires','After')):
                raise RuntimeError('System temporary mount dependency missing in '+relative+': '+name)
    hook=ROOT/'config/hooks/live/0948-core-vault-private-session.hook.chroot'
    hook_text=hook.read_text()
    if not any(line.startswith('systemctl enable ') and {'tmp.mount','var-tmp.mount'}.issubset(line.split())
               for line in hook_text.splitlines()):
        raise RuntimeError('Both protected system temporary mounts must be enabled in the image hook.')
    subprocess.run(['/bin/sh','-n',str(hook)],check=True)
    finish=(INC/'usr/local/bin/core-vault-finish').read_text()
    for token in ('COUNTDOWN_SECONDS = 300', 'confirmation(restart, 1)', 'confirmation(restart, 2)',
                  'countdown.exec()', 'stop_core()', 'clipboard.clear', 'lock.tryLock(0)',
                  'setDefaultButton(cancel)', 'setEscapeButton(cancel)'):
        if token not in finish: raise RuntimeError('Finish confirmation check missing: '+token)
    for token in ('get_verification_secrets', 'verify_export', 'read_receipts'):
        if token in finish: raise RuntimeError('Finish must not request or verify backup secrets: '+token)
    for relative in ('usr/local/bin/core-vault-bitcoin','usr/lib/core-vault/export.py'):
        if 'shred' in (INC/relative).read_text():
            raise RuntimeError('Wallet lifecycle must not rely on shredding.')
    wrapper=(INC/'usr/local/bin/core-vault-bitcoin').read_text()
    if 'exec /usr/bin/bwrap' not in wrapper or '--ro-bind / /' not in wrapper or '--sync-fd 3' not in wrapper:
        raise RuntimeError('Core write confinement or session lock is missing.')
    if ('--bind /run/user/1000 /run/user/1000' in wrapper or
            '--setenv XDG_RUNTIME_DIR /run/core-vault/state/core-runtime' not in wrapper):
        raise RuntimeError('Core must use its own private RAM runtime and keep the shared desktop runtime read-only.')
    for relative in ('usr/local/bin/core-vault-bitcoin', 'usr/local/libexec/core-vault-core-session'):
        if 'core-vault-storage-check --session --core' not in (INC/relative).read_text():
            raise RuntimeError('Core recursive-bind mount gate is missing: '+relative)
    helper=shlex.split((INC/'usr/local/libexec/core-vault-core-session').read_text(),comments=True)
    if ([word for word in helper if word.startswith('-settings=')]!=
            ['-settings=/home/vault/.bitcoin/settings.json']
            or any(word.partition('=')[0]=='-nosettings' for word in helper)):
        raise RuntimeError('Core GUI wallet loading requires enabled dynamic settings in the private RAM datadir.')
    storage=(INC/'usr/local/bin/core-vault-storage-check').read_text()
    runtime=(INC/'usr/lib/core-vault/runtime.py').read_text()
    prepare=(INC/'usr/local/libexec/core-vault-prepare').read_text()
    if "EXTRA_WALLET_ROOTS = (Path('/tmp'), Path('/var/tmp'))" not in runtime:
        raise RuntimeError('Wallet inventory must follow only Core-writable RAM scratch roots.')
    for token in ("'home/.local'", "'state/core-runtime'"):
        if token not in prepare:
            raise RuntimeError('Private RAM directory preparation missing: '+token)
    for token in ("HOME / '.local'", "HOME / '.local/share'", "HOME / '.local/state'", "STATE / 'core-runtime'"):
        if token not in runtime:
            raise RuntimeError('Private RAM directory validation missing: '+token)
    if "parser.add_argument('--core'" not in storage or 'check_core_mounts()' not in storage:
        raise RuntimeError('Core storage checker omits the nested mount policy.')
    if 'def check_core_mounts():' not in runtime or "'--uniq', '--list', '-J'" not in runtime:
        raise RuntimeError('Core mount topology validation is missing.')
    for relative in ('config/package-lists/core-vault.list.chroot','tools/core-vault/manifests/core-vault.list.chroot'):
        if 'bubblewrap' not in (ROOT/relative).read_text().splitlines():
            raise RuntimeError('Core filesystem isolation dependency is missing.')
    print('VAULT RAM-ONLY PRIVATE SESSION SOURCE CHECK PASSED')

def iso_check(iso):
    with tempfile.TemporaryDirectory(prefix='vault-ram-iso-') as tmp:
        squash=Path(tmp)/'root.squashfs'
        subprocess.run(['xorriso','-osirrox','on','-indev',str(iso),'-extract','/live/filesystem.squashfs',str(squash)],
                       stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,check=True)
        for relative in REQUIRED+SOURCE_ONLY:
            data=subprocess.check_output(['unsquashfs','-no-wildcards','-cat',str(squash),relative],stderr=subprocess.PIPE)
            if data!=(INC/relative).read_bytes():
                raise RuntimeError('Stale private session payload in ISO: '+relative)
        isolation=subprocess.check_output(['unsquashfs','-no-wildcards','-cat',str(squash),'usr/bin/bwrap'],stderr=subprocess.PIPE)
        if not isolation.startswith(b'\x7fELF'):
            raise RuntimeError('ISO lacks the native Debian bubblewrap executable.')
        links=Path(tmp)/'enabled-mounts'
        required_links=['etc/systemd/system/local-fs.target.wants/'+name for name in ('tmp.mount','var-tmp.mount')]
        subprocess.run(['unsquashfs','-no-progress','-no-wildcards','-d',str(links),str(squash),*required_links],
                       stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,check=True)
        for relative in required_links:
            link=links/relative
            if not link.is_symlink():
                raise RuntimeError('ISO does not enable the protected temporary mount: '+relative)
            target=str(link.readlink())
            resolved=posixpath.normpath(target if target.startswith('/') else '/'+posixpath.dirname(relative)+'/'+target)
            if resolved!='/etc/systemd/system/'+link.name:
                raise RuntimeError('ISO temporary mount enable link targets the wrong unit: '+relative)
    print('VAULT RAM-ONLY PRIVATE SESSION ISO CONTENT CHECK PASSED')

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--iso',type=Path)
    args=parser.parse_args()
    check()
    if args.iso: iso_check(args.iso.resolve(strict=True))
