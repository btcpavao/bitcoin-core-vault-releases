#!/usr/bin/python3
"""Download APT-verified Debian packages into a private build prefix, never install.

Use the corresponding-source deps-manifest.json from the reviewed build. Run as
a regular Debian 13 amd64 user with official runtime libraries and GCC installed.
Debian's own authenticated APT package indexes are required. Nothing under /usr,
/etc, /var, or the caller's application data is modified.
"""
from pathlib import Path
import argparse, hashlib, json, shutil, subprocess

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('manifest',type=Path)
    p.add_argument('destination',type=Path)
    a=p.parse_args()
    a.destination.mkdir(parents=True,exist_ok=True)
    debs=a.destination/'debs';debs.mkdir(exist_ok=True)
    prefix=a.destination/'prefix';prefix.mkdir(exist_ok=True)
    records=json.loads(a.manifest.read_text())
    subprocess.run(['apt-get','download',*[r['package']+'='+r['version'] for r in records]],cwd=debs,check=True)
    for r in records:
        f=debs/r['file']
        if hashlib.sha256(f.read_bytes()).hexdigest()!=r['sha256']:
            raise RuntimeError('Pinned Debian dependency digest mismatch: '+r['file'])
        metadata=subprocess.check_output(['apt-cache','show',r['package']+'='+r['version']],text=True)
        if 'SHA256: '+r['sha256'] not in metadata:
            raise RuntimeError('Dependency missing from authenticated APT indexes: '+r['file'])
        if r['package']!='thunar':
            subprocess.run(['dpkg-deb','-x',str(f),str(prefix)],check=True)
    # Development symlinks point to the matching installed Debian runtime SONAME.
    links=[]
    for f in (prefix/'usr/lib/x86_64-linux-gnu').glob('*.so'):
        if f.is_symlink() and not f.exists():
            system=Path('/usr/lib/x86_64-linux-gnu')/f.readlink()
            if system.exists():
                f.unlink();f.symlink_to(system)
                links.append({'link':str(f.relative_to(prefix)),'readonly_host_target':str(system)})
    share=prefix/'usr/share/pkgconfig';share.mkdir(parents=True,exist_ok=True)
    for f in Path('/usr/share/pkgconfig').glob('*.pc'):
        if not (share/f.name).exists(): shutil.copy2(f,share/f.name)
    (a.destination/'private-runtime-links.json').write_text(json.dumps(links,indent=2)+'\n')
    print('Private Debian dependency prefix:',prefix)

if __name__=='__main__':
    main()
