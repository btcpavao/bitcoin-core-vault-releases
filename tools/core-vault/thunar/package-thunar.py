#!/usr/bin/python3
"""Repack the official Thunar package with its reviewed native Vault executable."""
from pathlib import Path
import argparse, hashlib, io, json, math, shutil, subprocess, tarfile

VERSION='4.20.2-1+deb13u1+corevault1'
DOC='usr/share/doc/thunar/core-vault-source/'
META='usr/share/core-vault/thunar-shred.json'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('evidence',type=Path)
    p.add_argument('project',type=Path)
    a=p.parse_args();b=a.evidence.resolve(strict=True);r=a.project.resolve(strict=True)
    scripts=r/'tools/core-vault/thunar'
    proof=json.loads((b/'build-acceptance.json').read_text())
    binary=b/'thunar-vault'
    assert proof['status']=='PASS_BUILD_DISPATCH_AND_ABI' and sha(binary)==proof['binary_sha256']
    assert sha(b/'Thunar-core-vault-source.tar.xz')==proof['source_archive_sha256']
    # The original DSC and both archives must match Debian's authenticated APT Sources index.
    apt_source=(b/'apt-source-metadata.txt').read_text()
    archives=[b/'thunar_4.20.2-1+deb13u1.dsc',b/'thunar_4.20.2.orig.tar.bz2',b/'thunar_4.20.2-1+deb13u1.debian.tar.xz']
    for f in archives: assert ' '+sha(f)+' '+str(f.stat().st_size)+' '+f.name in apt_source
    stock=next(x for x in (b/'debs').glob('thunar_*.deb'))
    stock_sha=sha(stock)
    assert 'SHA256: '+stock_sha in subprocess.check_output(['apt-cache','show','thunar=4.20.2-1+deb13u1'],text=True)
    tree=b/'package-tree';assert not tree.exists()
    subprocess.run(['dpkg-deb','-R',str(stock),str(tree)],check=True)
    original={}
    for f in tree.rglob('*'):
        if f.is_file() and not f.is_symlink() and 'DEBIAN' not in f.relative_to(tree).parts:
            original[str(f.relative_to(tree))]=sha(f)
    shutil.copy2(binary,tree/'usr/bin/thunar');(tree/'usr/bin/thunar').chmod(0o755)
    docs=tree/DOC;docs.mkdir(parents=True)
    sources={
        'Thunar-core-vault-source.tar.xz':b/'Thunar-core-vault-source.tar.xz',
        'core-vault-permanent-delete.patch':b/'core-vault-permanent-delete.patch',
        'corresponding-source-manifest.json':b/'corresponding-source-manifest.json',
        'deps-manifest.json':b/'deps-manifest.json',
        'apt-source-metadata.txt':b/'apt-source-metadata.txt',
        'private-prefix-runtime-links.json':b/'private-prefix-runtime-links.json',
        'build-acceptance.json':b/'build-acceptance.json',
        **{f.name:f for f in archives},
        **{name:scripts/name for name in ['patch-thunar.py','build-thunar.py','prepare-private-prefix.py','test-dispatch.py','package-thunar.py']},
    }
    for name,f in sources.items():shutil.copy2(f,docs/name);(docs/name).chmod(0o644)
    (docs/'README.md').write_text("""# Bitcoin Core Vault native Thunar permanent deletion

The upstream application is Debian Thunar 4.20.2-1+deb13u1. The local package
replaces the native Move to Trash menu with Permanently Delete and routes native
trash/delete actions, Delete, Shift+Delete, tree-view and D-Bus deletion through
/usr/local/bin/core-vault-shred. Its GUI confirmation and filesystem checks are
owned by the separate Vault runtime helper. No ordinary delete fallback exists.
Copy, move, rename, extension ABI, official translations and other package files
remain unchanged. Permanent deletion is not added to the Undo operation log.

The complete corresponding source, official Debian original source/DSC/patches,
native patch, exact dependency manifest and build recipes are included here.
The original archives match Debian's authenticated APT Sources checksums. The
official base binary package and private dependency downloads match APT hashes.

To reproduce on Debian 13 amd64 with GCC, make, dpkg-dev and the standard XFCE
runtime libraries installed:
1. python3 prepare-private-prefix.py deps-manifest.json PRIVATE_BUILD_DIRECTORY
2. tar -xJf Thunar-core-vault-source.tar.xz into a new source directory
3. python3 build-thunar.py Thunar-core-vault-source PRIVATE_BUILD_DIRECTORY/prefix
4. python3 test-dispatch.py Thunar-core-vault-source PRIVATE_BUILD_DIRECTORY/prefix TEST_OUTPUT
5. strip --strip-unneeded Thunar-core-vault-source/thunar/.libs/thunar

The source archive is already patched; do not apply the patch again.
The private build prefix is used only for compilation. No private libraries are
installed in Vault and the executable has no private RPATH/RUNPATH.
This package modifies Vault image inputs, never the host's installed Thunar.
""")
    for f in docs.rglob('*'):
        if f.is_file():f.chmod(0o644)
        elif f.is_dir():f.chmod(0o755)
    docs.chmod(0o755)
    changed=[n for n,h in original.items() if sha(tree/n)!=h]
    assert changed==['usr/bin/thunar'],changed
    files={str(f.relative_to(tree)):sha(f) for f in sorted(tree.rglob('*')) if f.is_file() and not f.is_symlink() and 'DEBIAN' not in f.relative_to(tree).parts}
    control=tree/'DEBIAN/control'
    text=control.read_text()
    assert 'Version: 4.20.2-1+deb13u1\n' in text
    depends=next(x for x in text.splitlines() if x.startswith('Depends:'))
    assert 'thunar-data (= 4.20.2-1+deb13u1)' in depends
    size=math.ceil(sum((tree/n).stat().st_size for n in files)/1024)
    text=text.replace('Version: 4.20.2-1+deb13u1\n','Version: '+VERSION+'\n')
    text='\n'.join('Installed-Size: '+str(size) if x.startswith('Installed-Size:') else x for x in text.splitlines())+'\n'
    control.write_text(text)
    (tree/'DEBIAN/md5sums').write_text(''.join(hashlib.md5((tree/n).read_bytes()).hexdigest()+'  '+n+'\n' for n in sorted(files)))
    out=b/('thunar_'+VERSION+'_amd64.deb');assert not out.exists()
    subprocess.run(['dpkg-deb','--root-owner-group','--build',str(tree),str(out)],check=True)
    required={'usr/bin/thunar','usr/share/doc/thunar/copyright',*[DOC+name for name in sources],DOC+'README.md'}
    metadata={'schema':1,'package':'thunar','version':VERSION,'architecture':'amd64',
              'package_file':'config/packages.chroot/'+out.name,'package_sha256':sha(out),
              'fix':'native-permanent-delete-helper','source_archive':DOC+'Thunar-core-vault-source.tar.xz',
              'patch':DOC+'core-vault-permanent-delete.patch','build_recipe':DOC+'README.md',
              'files':{n:files[n] for n in sorted(required)},
              'stock_package_sha256':stock_sha,'stock_regular_payload_changed':changed,
              'stock_dependencies_unchanged':True,'source_input_files':{str(f.relative_to(r)):sha(f) for f in sorted(scripts.glob('*.py'))}}
    raw=json.dumps(metadata,indent=2)+'\n'
    (b/'thunar-shred.json').write_text(raw)
    dest=r/'config/packages.chroot'/out.name;assert not dest.exists()
    assert not list((r/'config/packages.chroot').glob('thunar_*.deb'))
    shutil.copy2(out,dest);dest.chmod(0o644)
    for base in [r/'config/includes.chroot',r/'tools/core-vault/runtime-template']:
        target=base/META;target.parent.mkdir(parents=True,exist_ok=True);assert not target.exists()
        target.write_text(raw);target.chmod(0o644)
    (b/'package-result.json').write_text(json.dumps({'status':'PASS_STAGED_NATIVE_THUNAR','package_sha256':sha(out),'package_bytes':out.stat().st_size,'binary_sha256':sha(binary),'official_payload_changed':changed,'no_host_package_install':True,'new_iso_built':False},indent=2)+'\n')
    print('STAGED',dest,'SHA256',sha(out))

if __name__=='__main__':
    main()
