#!/usr/bin/python3
"""Source/package gate. No target disk, wallet, network or installer is opened."""
from pathlib import Path
import argparse,ast,importlib.util,json,subprocess,sys
import yaml
ROOT=Path(__file__).resolve().parents[2]
INC=ROOT/'config/includes.chroot'

def module(path):
    spec=importlib.util.spec_from_file_location('vault_target_check',path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def source_check():
    cfg=yaml.safe_load((INC/'etc/calamares/settings.conf').read_text())
    expected=['partition','mount','unpackfs','machineid','keyboard','fstab',
        'corevault@target','initramfs','bootloader','corevault@verify','umount']
    if cfg['sequence'][0]['show']!=['keyboard','partition','summary'] or cfg['sequence'][1]['exec']!=expected:
        raise RuntimeError('Unexpected installer execution order.')
    if cfg.get('prompt-install') is not True: raise RuntimeError('Final install prompt was disabled.')
    for p in (INC/'etc/calamares').rglob('*.conf'): yaml.safe_load(p.read_text())
    part=yaml.safe_load((INC/'etc/calamares/modules/partition.conf').read_text())
    if part['userSwapChoices']!=['none'] or part['enableLuksAutomatedPartitioning'] is not False or part['allowManualPartitioning'] is not False:
        raise RuntimeError('Unexpected partition/FDE/swap choices.')
    if part['partitionLayout'][0]['mountPoint']!='/' or part['defaultFileSystemType']!='ext4':
        raise RuntimeError('Expected ext4 dedicated root.')
    unpack=yaml.safe_load((INC/'etc/calamares/modules/unpackfs.conf').read_text())
    if unpack['unpack']!=[{'source':'/run/live/medium/live/filesystem.squashfs','sourcefs':'squashfs','destination':''}]:
        raise RuntimeError('Must install immutable SquashFS, not a working Live session.')
    lib=INC/'usr/lib/core-vault-installer'
    for p in lib.rglob('*.py'): ast.parse(p.read_text(),str(p))
    for name in ('core-vault-installer','../bin/core-vault-storage-check','../bin/core-vault-install-check'):
        p=INC/'usr/local/sbin'/name;ast.parse(p.read_text(),str(p))
    for p in (INC/'usr/local/bin/core-vault-session', INC/'usr/local/bin/core-vault-installer-session',
              ROOT/'tools/core-vault/prepare-installer.sh', ROOT/'tools/core-vault/vm-installer-test.sh',
              ROOT/'config/hooks/live/0990-core-offline-boot-menu.hook.binary'):
        interpreter='/bin/bash' if p.read_text().startswith('#!/bin/bash') else '/bin/sh'
        subprocess.run([interpreter,'-n',str(p)],check=True)
    target=module(lib/'target.py')
    result=target.add_fstab('UUID=x / ext4 defaults 0 1\nUUID=y none swap sw 0 0\n')
    rows=[l.split() for l in result.splitlines() if l and not l.startswith('#')]
    if target.add_fstab(result)!=result: raise RuntimeError('fstab policy must be idempotent.')
    if any(r[1] in ('/home','/home/vault',target.PRIVATE_FSTAB) or r[2]=='swap' for r in rows):
        raise RuntimeError('Unexpected home mount conflicting with native RAM units, or swap.')
    for unit in ('home-vault.mount', r'run-core\x2dvault.mount', 'core-vault-prepare.service'):
        if not (INC/'etc/systemd/system'/unit).is_file(): raise RuntimeError('Missing RAM session unit '+unit)
    for unit in ('core-signer-offline.service','core-signer-no-swap.service'):
        if not (INC/'etc/systemd/system'/unit).is_file(): raise RuntimeError('Missing actual inherited unit '+unit)
    body=(INC/'usr/local/bin/core-vault-session').read_text()
    if body.count('core-vault.install=1')!=1 or body.count('core-vault-storage-check --session')!=1:
        raise RuntimeError('Installer routing or storage gate missing/duplicated.')
    template=ROOT/'tools/core-vault/runtime-template/usr/local/bin'
    for name in ('core-vault-session','core-vault-storage-check','core-vault-install-check'):
        if (INC/'usr/local/bin'/name).read_bytes()!=(template/name).read_bytes():
            raise RuntimeError('Runtime template mismatch: '+name)
    if (INC/'etc/core-vault/installation.json').exists(): raise RuntimeError('Installed marker in source image is forbidden.')
    rule=(INC/'etc/sudoers.d/80-core-vault-installer').read_text()
    if 'vault ALL=(root) NOPASSWD: /usr/local/sbin/core-vault-installer ""' not in rule:
        raise RuntimeError('Installer rule must be exact, with no arguments.')
    subprocess.run(['/usr/sbin/visudo','-cf',str(INC/'etc/sudoers.d/80-core-vault-installer')],check=True,
                   stdout=subprocess.DEVNULL)
    # All executable package-version gates must agree before the expensive ISO build.
    expected_version=module(ROOT/'tools/core-vault/calamares/package_state.py').VERSION
    wrapper=ast.parse((INC/'usr/local/sbin/core-vault-installer').read_text())
    guarded_versions=[node.comparators[0].value for node in ast.walk(wrapper)
        if isinstance(node,ast.Compare) and isinstance(node.left,ast.Name)
        and node.left.id=='version' and len(node.ops)==1 and isinstance(node.ops[0],ast.NotEq)
        and len(node.comparators)==1 and isinstance(node.comparators[0],ast.Constant)]
    if guarded_versions!=[expected_version]:
        raise RuntimeError('Installer launcher package-version guard differs from reviewed package.')
    hook=(ROOT/'config/hooks/live/0950-core-vault-installer-check.hook.chroot').read_text()
    import re
    hook_versions=re.findall(r"^test .*dpkg-query.* calamares\)\" = '([^']+)'$",hook,re.M)
    manifest_versions=re.findall(r"'calamares_version':'([^']+)'",hook)
    if hook_versions!=[expected_version] or manifest_versions!=[expected_version]:
        raise RuntimeError('ISO build hook package/manifest version differs from reviewed package.')
    # Installer control assets must survive regeneration with identical templates.
    brand=INC/'etc/calamares/branding/core-offline'
    template_brand=ROOT/'tools/core-vault/installer-template/includes.chroot/etc/calamares/branding/core-offline'
    for name in ('stylesheet.qss','checkmark.svg','checkmark.png'):
        if (brand/name).read_bytes()!=(template_brand/name).read_bytes():
            raise RuntimeError('Installer branding template mismatch: '+name)
    import xml.etree.ElementTree as ET
    if ET.parse(brand/'checkmark.svg').getroot().tag!='{http://www.w3.org/2000/svg}svg':
        raise RuntimeError('Invalid acknowledgement indicator SVG.')
    print('VAULT CALAMARES SOURCE CHECK PASSED')

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--source',action='store_true');a.add_argument('--prebuild',action='store_true');o=a.parse_args()
    source_check()
    if o.prebuild:
        sys.path.insert(0,str(ROOT/'tools/core-vault/calamares'))
        from package_state import verify
        verify(ROOT)
