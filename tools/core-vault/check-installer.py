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


def launcher_manifest_contract(tree):
    """Inspect the launcher contract without importing or executing the launcher."""
    functions={node.name:node for node in tree.body if isinstance(node,ast.FunctionDef)}
    if not {'main','reviewed_calamares_version'}.issubset(functions):
        raise RuntimeError('Installer launcher must read the image manifest package pin.')
    main=functions['main'];reader=functions['reviewed_calamares_version']

    def signature(node):
        return ast.dump(node,include_attributes=False)

    def expression(text):
        return signature(ast.parse(text,mode='eval').body)

    def contains(function,text):
        expected=expression(text)
        return any(signature(node)==expected for node in ast.walk(function))

    def guarded(function,text):
        expected=expression(text)
        for node in ast.walk(function):
            if isinstance(node,ast.If) and signature(node.test)==expected:
                if any(isinstance(child,ast.Raise) for statement in node.body for child in ast.walk(statement)):
                    return True
        return False

    main_guards=(
        'os.geteuid() != 0 or len(sys.argv) != 1',
        '"boot=live" not in cmdline or "core-vault.install=1" not in cmdline',
        'not squashfs.is_file()',
        'pathlib.Path("/etc/core-vault/installation.json").exists()',
        'len(mount_info) != 2 or "ro" not in mount_info[1].split(",")',
        'package.returncode != 0 or len(fields) != 2 or status != "install ok installed" or version != expected_version',
    )
    if not all(guarded(main,text) for text in main_guards):
        raise RuntimeError('Installer launcher root, Live-medium or installed-package guard changed.')
    if not any(isinstance(node,ast.Assign) and len(node.targets)==1
               and isinstance(node.targets[0],ast.Name) and node.targets[0].id=='expected_version'
               and signature(node.value)==expression('reviewed_calamares_version()') for node in main.body):
        raise RuntimeError('Installer launcher version must come from the reviewed image manifest.')
    queries=[node for node in ast.walk(main) if isinstance(node,ast.Call)
             and isinstance(node.func,ast.Attribute) and isinstance(node.func.value,ast.Name)
             and node.func.value.id=='subprocess' and node.func.attr=='run' and node.args
             and isinstance(node.args[0],ast.List)
             and any(isinstance(item,ast.Constant) and item.value=='/usr/bin/dpkg-query' for item in node.args[0].elts)]
    expected_query=['/usr/bin/dpkg-query','-W','-f=${Status}\n${Version}\n','calamares']
    if len(queries)!=1 or ast.literal_eval(queries[0].args[0])!=expected_query:
        raise RuntimeError('Installer launcher must query both Calamares status and exact version.')
    reader_guards=(
        'not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022',
        'not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022 or not 0 < info.st_size <= limit',
        'len(raw) > limit',
        'not isinstance(payload, dict) or type(payload.get("schema")) is not int or payload["schema"] != 1',
    )
    reader_expressions=(
        'pathlib.Path("/etc/core-vault/installer-payload.json")',
        'os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)',
        'os.fstat(source.fileno())', 'source.read(limit + 1)',
        'payload.get("calamares_version")',
    )
    if (not all(guarded(reader,text) for text in reader_guards)
            or not all(contains(reader,text) for text in reader_expressions)
            or not any(isinstance(node,ast.Assign) and len(node.targets)==1
                       and isinstance(node.targets[0],ast.Name) and node.targets[0].id=='limit'
                       and isinstance(node.value,ast.Constant) and node.value.value==1048576 for node in reader.body)):
        raise RuntimeError('Installer manifest reader must remain bounded and controlled by root.')


def source_check():
    cfg=yaml.safe_load((INC/'etc/calamares/settings.conf').read_text())
    expected=['partition','mount','unpackfs','machineid','keyboard','fstab',
        'corevault@target','initramfs','bootloader','corevault@verify','umount']
    if cfg['sequence'][0]['show']!=['keyboard','partition','summary'] or cfg['sequence'][1]['exec']!=expected:
        raise RuntimeError('Unexpected installer execution order.')
    if cfg.get('prompt-install') is not True: raise RuntimeError('Final install prompt was disabled.')
    for p in (INC/'etc/calamares').rglob('*.conf'): yaml.safe_load(p.read_text())
    part=yaml.safe_load((INC/'etc/calamares/modules/partition.conf').read_text())
    if part['userSwapChoices']!=['none'] or part['enableLuksAutomatedPartitioning'] is not False or part['allowManualPartitioning'] is not True:
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
    if body.count('core-vault.install=1')!=1 or body.count('core-vault-storage-check --session')!=2:
        raise RuntimeError('Installer routing or storage gate missing/duplicated.')
    restore_gate='''    if /usr/local/bin/core-vault-storage-check --session >/dev/null 2>&1; then
        /usr/local/bin/core-display-settings --product vault --restore || true
    fi'''
    mandatory_gate='''if ! /usr/local/bin/core-vault-storage-check --session >"$XDG_RUNTIME_DIR/core-vault-storage.log" 2>&1; then
    /usr/bin/zenity --error --no-markup --title="Bitcoin Core Vault — Storage check" \\
        --text="Private Workspace or storage policy is not ready. The Vault desktop will not open. See core-vault-storage.log in the runtime directory." || true
    exit 1
fi'''
    if body.count(restore_gate)!=1 or body.count(mandatory_gate)!=1:
        raise RuntimeError('Display restore or mandatory fail-closed RAM storage guard changed.')
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
    launcher=INC/'usr/local/sbin/core-vault-installer'
    launcher_manifest_contract(ast.parse(launcher.read_text(),str(launcher)))
    for relative in ('usr/local/sbin/core-vault-installer','usr/local/bin/core-vault-installer-session'):
        if (INC/relative).read_bytes()!=(ROOT/'tools/core-vault/runtime-template'/relative).read_bytes():
            raise RuntimeError('Installer launcher/session template mismatch: '+relative)
    hook=(ROOT/'config/hooks/live/0950-core-vault-installer-check.hook.chroot').read_text()
    import re
    hook_versions=re.findall(r"^test .*dpkg-query.* calamares\)\" = '([^']+)'$",hook,re.M)
    manifest_versions=re.findall(r"'calamares_version':'([^']+)'",hook)
    if hook_versions!=[expected_version] or manifest_versions!=[expected_version]:
        raise RuntimeError('ISO build hook package/manifest version differs from reviewed package.')
    # Installer control assets must survive regeneration with identical templates.
    brand=INC/'etc/calamares/branding/core-offline'
    template_brand=ROOT/'tools/core-vault/installer-template/includes.chroot/etc/calamares/branding/core-offline'
    for name in ('stylesheet.qss','checkmark.svg','checkmark.png','spin-up.svg','spin-down.svg'):
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
