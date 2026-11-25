#!/usr/bin/python3
"""Assemble a local Vault BIOS candidate; file operations only, no tests.

Run under the same fakeroot state used to unpack the base. This script never
runs Calamares, installer jobs, or programs from the unpacked image.
"""
from pathlib import Path, PurePosixPath
import argparse, datetime, hashlib, io, json, os, shutil, stat, subprocess, tarfile

def sha(path):
    digest=hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024*1024), b''):digest.update(block)
    return digest.hexdigest()

def fields(text):
    result={};current=None
    for line in text.splitlines():
        if line.startswith((' ', '\t')) and current:
            result[current]+='\n'+line
        elif ':' in line:
            current,value=line.split(':',1);result[current]=value.lstrip(' ')
    return result

def target(root, relative):
    p=root/relative
    if not p.resolve(strict=False).is_relative_to(root):
        raise ValueError('Target path escapes the unpacked image: '+relative)
    return p

def copy_overlay(root, src, relative):
    destination=target(root,relative);destination.parent.mkdir(parents=True,exist_ok=True)
    original=destination.lstat() if destination.exists() else None
    if original and not stat.S_ISREG(original.st_mode):
        raise ValueError('Expected regular overlay target: '+relative)
    destination.write_bytes((src/'config/includes.chroot'/relative).read_bytes())
    destination.chmod(stat.S_IMODE(original.st_mode) if original else 0o644);os.chown(destination,0,0)

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ('rootfs','source','deb','evidence'):ap.add_argument(name,type=Path)
    args=ap.parse_args()
    root=args.rootfs.resolve();src=args.source.resolve();deb=args.deb.resolve()
    evidence=args.evidence.resolve();evidence.mkdir(parents=True,exist_ok=True)
    if root==Path('/') or not root.is_dir() or 'VERSION_ID="13"' not in target(root,'etc/os-release').read_text():
        raise ValueError('Expected a separate unpacked Debian 13 root.')
    control_dir=evidence/'calamares-control';control_dir.mkdir(exist_ok=True)
    subprocess.run(['dpkg-deb','--control',str(deb),str(control_dir)],check=True)
    control=fields((control_dir/'control').read_text())
    version='3.3.14-1+corevault7localbios1'
    if (control.get('Package'),control.get('Version'),control.get('Architecture'))!=('calamares',version,'amd64'):
        raise ValueError('Unexpected locally compiled package.')
    payload_tar=subprocess.check_output(['dpkg-deb','--fsys-tarfile',str(deb)])
    with tarfile.open(fileobj=io.BytesIO(payload_tar),mode='r:') as archive:
        names=[]
        for item in archive:
            name=item.name
            if name in ('.','./'):names.append('/.');continue
            if name.startswith('./'):name=name[2:]
            rel=PurePosixPath(name)
            if rel.is_absolute() or '..' in rel.parts:raise ValueError('Unsafe package member.')
            names.append('/'+str(rel))
    info=target(root,'var/lib/dpkg/info');old_list=info/'calamares.list'
    previous=old_list.read_text().splitlines() if old_list.exists() else [];fresh=set(names)
    for name in previous:
        if name not in fresh and name not in ('/','/.'):
            p=root/name.lstrip('/')
            if not p.parent.resolve().is_relative_to(root):raise ValueError('Unsafe old package path.')
            if p.is_symlink() or p.is_file():p.unlink()
    subprocess.run(['dpkg-deb','--extract',str(deb),str(root)],check=True)
    old_list.write_text('\n'.join(names)+'\n');old_list.chmod(0o644);os.chown(old_list,0,0)
    for item in control_dir.iterdir():
        if item.name=='control':continue
        p=info/('calamares.'+item.name)
        p.write_bytes(item.read_bytes());p.chmod(stat.S_IMODE(item.stat().st_mode));os.chown(p,0,0)
    status=target(root,'var/lib/dpkg/status');paragraphs=status.read_text().rstrip().split('\n\n')
    replaced=False
    for i,text in enumerate(paragraphs):
        old=fields(text)
        if old.get('Package')!='calamares':continue
        if replaced:raise ValueError('Duplicate Calamares package record.')
        new=dict(control);new['Status']='install ok installed'
        if old.get('Conffiles'):new['Conffiles']=old['Conffiles']
        paragraphs[i]='\n'.join(key+': '+value for key,value in new.items());replaced=True
    if not replaced:raise ValueError('The base did not contain Calamares.')
    status.write_text('\n\n'.join(paragraphs)+'\n')
    # Restore custom configuration after extracting Debian package defaults.
    for p in (src/'config/includes.chroot/etc/calamares').rglob('*'):
        if p.is_file() and not p.is_symlink():
            copy_overlay(root,src,str(p.relative_to(src/'config/includes.chroot')))
    runtime=['usr/lib/core-vault-installer/'+name for name in
        ('disk_safety.py','install_plan.py','boot_finalize.py')]
    for relative in runtime:copy_overlay(root,src,relative)
    cache=target(root,'usr/lib/core-vault-installer/__pycache__')
    if cache.is_dir():shutil.rmtree(cache)
    input_files=runtime+[
        'tools/core-vault/calamares/advanced_patch.py',
        'tools/core-vault/calamares/shared/PartitionPage.cpp',
        'tools/core-vault/calamares/shared/PlanMethods.cpp.inc',
        'tools/core-vault/calamares/shared/Review.cpp.inc',
        'tools/core-vault/calamares/shared/CoreOfflineGuard.h']
    source_hashes={}
    for relative in input_files:
        p=src/relative if relative.startswith('tools/') else src/'config/includes.chroot'/relative
        source_hashes[relative]=sha(p)
    record={
        'schema':1,'product':'vault','candidate':'local-bios-advanced-20261124',
        'built_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'base_source_commit':'b5ca3eaed69e9c0af47cd783ef3ae6a2d58da741',
        'base_iso_sha256':'651f0d0a19489acf4cb4f28f2c72f8bb3461d6a1f920026f89f90ce048e35546',
        'calamares_version':version,'calamares_sha256':sha(deb),'source_files':source_hashes,
        'source_state':'local uncommitted changes',
        'tests_run':False,'vm_installations_run':False,'github_push':False,'signed':False,
        'publication':'local only; manual hardware trial pending',
        'architecture':'amd64','firmware_modes':['x86_64 UEFI','Legacy BIOS'],
        'advanced_tables':{'efi':['gpt'],'bios':['gpt','dos']}}
    marker=target(root,'etc/core-vault/local-build.json')
    marker.write_text(json.dumps(record,indent=2,sort_keys=True)+'\n');marker.chmod(0o644);os.chown(marker,0,0)
    manifest=target(root,'etc/core-vault/installer-payload.json');payload=json.loads(manifest.read_text())
    payload['calamares_version']=version
    # Installer internals are intentionally removed from the installed OS.
    for relative in list(payload['files']):
        if relative in runtime or relative.startswith('etc/calamares/'):
            payload['files'][relative]=sha(target(root,relative))
    payload['files']['etc/core-vault/local-build.json']=sha(marker)
    payload['files']=dict(sorted(payload['files'].items()))
    manifest.write_text(json.dumps(payload,indent=2)+'\n')
    (evidence/'local-build.json').write_text(json.dumps(record,indent=2,sort_keys=True)+'\n')
    packages=[]
    for text in paragraphs:
        p=fields(text)
        if p.get('Status')=='install ok installed':packages.append(p['Package']+'\t'+p['Version'])
    (evidence/'image-packages.tsv').write_text('\n'.join(sorted(packages))+'\n')
    print('Local image files assembled; no tests or installer execution.')

if __name__=='__main__':main()
