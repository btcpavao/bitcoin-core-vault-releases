#!/usr/bin/python3
"""Inspect final ISO contents, without booting/installing it."""
from pathlib import Path
import hashlib,json,runpy,subprocess,sys,tempfile
iso=Path(sys.argv[1]).resolve()
root=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(root/'tools/core-vault/calamares'))
import package_state
reviewed_package=package_state.verify(root)
with tempfile.TemporaryDirectory(prefix='vault-installer-iso-') as td:
    d=Path(td)
    for src,dst in [('/isolinux/isolinux.cfg','bios'),('/boot/grub/grub.cfg','uefi'),('/live/filesystem.squashfs','root.squashfs')]:
        subprocess.run(['xorriso','-osirrox','on','-indev',str(iso),'-extract',src,str(d/dst)],check=True,
            stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    runpy.run_path(str(root/'tools/core-vault/check-squashfs-ownership.py'))['verify'](d/'root.squashfs')
    for name in ('bios','uefi'):
        text=(d/name).read_text()
        if text.count('Install Bitcoin Core Vault')!=1 or 'Start Bitcoin Core Vault (Live RAM)' not in text:
            raise RuntimeError('Expected exactly one Live and one Install entry.')
        boot=[l for l in text.splitlines() if 'boot=live' in l]
        if len(boot)!=2 or 'toram' not in boot[0] or 'toram' in boot[1] or 'core-vault.install=1' not in boot[1]:
            raise RuntimeError('Live/installer flags are not separated.')
    def cat(path):
        return subprocess.check_output(['unsquashfs','-no-wildcards','-cat',str(d/'root.squashfs'),path],stderr=subprocess.PIPE)
    # Pin the exact verified archive bytes before extraction (same-version cache guard).
    package=root/'config/packages.chroot'/reviewed_package['filename']
    package_data=package.read_bytes()
    if hashlib.sha256(package_data).hexdigest()!=reviewed_package['sha256']:
        raise RuntimeError('Staged Calamares package changed after verification.')
    pinned_package=d/'reviewed-calamares.deb'
    pinned_package.write_bytes(package_data)
    package_root=d/'calamares-payload'
    subprocess.run(['dpkg-deb','-x',str(pinned_package),str(package_root)],check=True,
                   stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    expected_elf={}
    for path in sorted(package_root.rglob('*')):
        if path.is_symlink() or not path.is_file():
            continue
        data=path.read_bytes()
        if data.startswith(b'\x7fELF'):
            relative=path.relative_to(package_root).as_posix()
            expected_elf[relative]=hashlib.sha256(data).hexdigest()
    if not expected_elf:
        raise RuntimeError('Reviewed Calamares package contains no regular ELF files.')
    if 'usr/bin/calamares' not in expected_elf:
        raise RuntimeError('Reviewed Calamares executable is missing from ELF payload.')
    for path,want in expected_elf.items():
        if hashlib.sha256(cat(path)).hexdigest()!=want:
            raise RuntimeError('Staged Calamares ELF differs in ISO: '+path)
    status=cat('var/lib/dpkg/status').decode()
    para=next((p for p in status.split('\n\n') if p.startswith('Package: calamares\n')),None)
    if not para or 'Version: '+package_state.VERSION+'\n' not in para+'\n':
        raise RuntimeError('Wrong Calamares package in ISO.')
    for path in ('usr/local/sbin/core-vault-installer','usr/local/bin/core-vault-installer-session',
                 'usr/local/bin/core-vault-storage-check','usr/local/bin/core-vault-install-check',
                 'usr/lib/core-vault-installer/target.py','usr/lib/core-vault-installer/disk_safety.py'):
        if cat(path)!=(root/'config/includes.chroot'/path).read_bytes():
            raise RuntimeError('Stale installer/runtime file in ISO: '+path)
    for name in ('stylesheet.qss','checkmark.svg','checkmark.png'):
        path='etc/calamares/branding/core-offline/'+name
        if cat(path)!=(root/'config/includes.chroot'/path).read_bytes():
            raise RuntimeError('Installer control asset missing or differs in ISO: '+name)
    manifest=json.loads(cat('etc/core-vault/installer-payload.json'))
    if manifest.get('calamares_version')!=package_state.VERSION:
        raise RuntimeError('Installer payload manifest package-version mismatch.')
    if len(manifest.get('files',{}))<15: raise RuntimeError('Incomplete installed payload manifest.')
    # Verify the actual immutable payload, including root-controlled session
    # scripts and dependencies, rather than trusting manifest declarations.
    import re
    files=manifest['files']
    for name,digest in files.items():
        if (not isinstance(name,str) or name.startswith('/') or
            any(part in ('','..','.') for part in name.split('/')) or
            not isinstance(digest,str) or not re.fullmatch(r'[0-9a-f]{64}',digest)):
            raise RuntimeError('Invalid installer payload manifest record.')
    required={'usr/bin/bwrap','usr/local/libexec/core-vault-core-session',
        'usr/local/bin/core-vault-home','usr/local/bin/core-vault-guide'}
    # Every shipped Vault helper must be covered, including newly split Guide
    # text and the RAM reminder. Outer ISO checksums cannot validate this inner
    # manifest: a local remaster must rebuild it from its final reviewed tree.
    required.update(p.relative_to(root/'config/includes.chroot').as_posix()
        for p in (root/'config/includes.chroot/usr/lib/core-vault').glob('*.py'))
    for name in sorted(required):
        if name not in files: raise RuntimeError('Installer manifest omits runtime dependency: '+name)
    payload=d/'installed-payload'
    subprocess.run(['unsquashfs','-no-progress','-no-wildcards','-d',str(payload),
                    str(d/'root.squashfs'),*files],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    for name,digest in files.items():
        path=payload/name
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(payload):
            raise RuntimeError('Installer payload file is missing or redirected: '+name)
        if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
            raise RuntimeError('Installer payload digest mismatch: '+name)
        source=root/'config/includes.chroot'/name
        if source.is_file() and not source.is_symlink() and path.read_bytes()!=source.read_bytes():
            raise RuntimeError('ISO installer payload differs from current source: '+name)
    print('VAULT INSTALLER PAYLOAD SHA256 CHECK PASSED ('+str(len(files))+' files)')
    if b'corevault@verify' not in cat('etc/calamares/settings.conf'):
        raise RuntimeError('Installed verification job is missing.')
    print('VAULT CALAMARES STAGED ELF ISO CHECK PASSED ('+str(len(expected_elf))+' files)')
print('VAULT CALAMARES ISO CONTENT CHECK PASSED')
print('Boot/installation acceptance is still required in disposable BIOS and UEFI VMs.')
