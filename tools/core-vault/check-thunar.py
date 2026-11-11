#!/usr/bin/python3
"""Verify the native Thunar permanent-delete package and corresponding source."""
from pathlib import Path
import argparse, hashlib, io, json, re, subprocess, tarfile

VERSION='4.20.2-1+deb13u1+corevault2'
META='usr/share/core-vault/thunar-shred.json'
DOC='usr/share/doc/thunar/core-vault-source/'

def require(ok,message):
    if not ok:raise RuntimeError(message)

def metadata(root):
    active=root/'config/includes.chroot'/META
    template=root/'tools/core-vault/runtime-template'/META
    raw=active.read_bytes()
    require(raw==template.read_bytes(),'Thunar permanent-delete active/template mismatch')
    value=json.loads(raw)
    require(value.get('schema')==1 and value.get('package')=='thunar'
            and value.get('version')==VERSION and value.get('architecture')=='amd64',
            'Unexpected native Thunar package identity')
    require(value.get('fix')=='native-permanent-delete-helper','Missing Thunar patch marker')
    require(value.get('package_file')=='config/packages.chroot/thunar_'+VERSION+'_amd64.deb',
            'Unexpected Thunar package path')
    require(value.get('stock_regular_payload_changed')==['usr/bin/thunar']
            and value.get('stock_dependencies_unchanged') is True,
            'Native Thunar must preserve the other official package payload/dependencies')
    docs=[value[k] for k in ('source_archive','patch','build_recipe')]
    require(len(set(docs))==3 and all(p.startswith(DOC) and '..' not in Path(p).parts for p in docs),
            'Invalid Thunar corresponding-source references')
    required={'usr/bin/thunar','usr/share/doc/thunar/copyright',*docs}
    require(required.issubset(value['files']),'Incomplete Thunar binary/license/source manifest')
    require(all(p in required or (p.startswith(DOC) and '..' not in Path(p).parts)
                for p in value['files']),'Unexpected source payload path')
    require(all(re.fullmatch(r'[0-9a-f]{64}',h) for h in [value['package_sha256'],*value['files'].values()]),
            'Invalid Thunar payload digest')
    for name,digest in value['source_input_files'].items():
        p=Path(name)
        require(p.parts[:3]==('tools','core-vault','thunar') and '..' not in p.parts
                and len(p.parts)==4 and p.suffix=='.py','Invalid source input path')
        require(hashlib.sha256((root/p).read_bytes()).hexdigest()==digest,
                'Thunar package source input changed: '+name)
    native_build = (root/'tools/rebuild/packages/build.sh').read_bytes()
    require(hashlib.sha256(native_build).hexdigest() == value['native_build_sha256'],
            'Native Thunar compiler recipe changed.')
    return raw,value

def check(root):
    _,value=metadata(root)
    package=root/value['package_file']
    require(package.is_file() and not package.is_symlink(),'Missing native Thunar package')
    require(hashlib.sha256(package.read_bytes()).hexdigest()==value['package_sha256'],
            'Native Thunar package checksum mismatch')
    require(list((root/'config/packages.chroot').glob('thunar_*.deb'))==[package],
            'Unexpected additional local Thunar package')
    for field,expected in [('Package','thunar'),('Version',VERSION),('Architecture','amd64')]:
        actual=subprocess.check_output(['dpkg-deb','-f',str(package),field],text=True).strip()
        require(actual==expected,'Thunar package identity mismatch: '+field)
    depends=subprocess.check_output(['dpkg-deb','-f',str(package),'Depends'],text=True)
    require('thunar-data (= 4.20.2-1+deb13u1)' in depends,
            'Native Thunar must retain its official ABI/data dependency')
    data=subprocess.check_output(['dpkg-deb','--fsys-tarfile',str(package)])
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        members={m.name.removeprefix('./'):m for m in archive.getmembers()}
        for name,digest in value['files'].items():
            member=members.get(name)
            require(member is not None and member.isfile(),'Missing native payload: '+name)
            require(member.uid==member.gid==0 and not (member.mode&0o022),
                    'Unsafe payload ownership/mode: '+name)
            if name=='usr/bin/thunar':
                require((member.mode&0o7777)==0o755,'Thunar executable mode must be 0755')
            payload=archive.extractfile(member).read()
            require(hashlib.sha256(payload).hexdigest()==digest,'Thunar payload mismatch: '+name)
            if name=='usr/bin/thunar':
                require(payload.startswith(b'\x7fELF') and b'/usr/local/bin/core-vault-shred\0' in payload
                        and 'Permanently _Delete…'.encode() in payload,
                        'Thunar lacks the actual native permanent-delete dispatch')
    print('VAULT THUNAR PERMANENT-DELETE SOURCE + PACKAGE CHECK PASSED')

def verify_payload(root,get,status,manifest):
    raw,value=metadata(root)
    require(get(META)==raw,'ISO Thunar permanent-delete metadata differs from tested source')
    para=next((p for p in status.split('\n\n') if p.startswith('Package: thunar\n')),'')
    require('Status: install ok installed' in para.splitlines() and 'Version: '+VERSION in para.splitlines(),
            'ISO lacks the reviewed native Thunar version')
    for name,digest in {META:hashlib.sha256(raw).hexdigest(),**value['files']}.items():
        require(hashlib.sha256(get(name)).hexdigest()==digest,'ISO native Thunar mismatch: '+name)
        require(manifest.get('files',{}).get(name)==digest,
                'Installed native Thunar/source manifest mismatch: '+name)
    print('VAULT THUNAR PERMANENT-DELETE LIVE + INSTALLER PAYLOAD CHECK PASSED')

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,default=Path(__file__).resolve().parents[2])
    check(parser.parse_args().project.resolve(strict=True))
