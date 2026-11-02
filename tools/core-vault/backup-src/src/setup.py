#!/usr/bin/python3
"""Merge backup/recovery actions and associations; never replace other actions."""
import argparse
import configparser
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET

CREATE = '/usr/bin/core-vault-backup create %F'
DECRYPT_GPG = '/usr/bin/core-vault-backup decrypt %f'

def write_changed(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() == data: return False
    if path.is_symlink(): raise RuntimeError('Refusing to replace a symlink: '+str(path))
    if path.exists():
        backup = path.with_name(path.name+'.pre-core-vault-backup')
        if not backup.exists(): shutil.copy2(path, backup)
    fd, tmp = tempfile.mkstemp(prefix='.'+path.name+'-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f: f.write(data)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)
    return True

def setup(home):
    config = home/'.config'
    uca = config/'Thunar/uca.xml'
    if uca.exists():
        tree = ET.parse(uca)  # Invalid XML is an error, never permission to erase it.
        root = tree.getroot()
        if root.tag != 'actions': raise RuntimeError('Unexpected Thunar configuration format.')
    else: root = ET.Element('actions'); tree = ET.ElementTree(root)
    for action in list(root.findall('action')):
        cmd = action.findtext('command','')
        name = action.findtext('name','')
        if cmd in (CREATE,DECRYPT_GPG):
            root.remove(action)
    for name,cmd,pattern,uid in [
        ('Create Encrypted Backup', CREATE, '*', '1730000000000000-1'),
        ('Decrypt Encrypted Backup', DECRYPT_GPG, '*.gpg;*.GPG', '1730000000000000-3')]:
        a = ET.SubElement(root,'action')
        for tag,value in [('icon','document-decrypt' if cmd==DECRYPT_GPG else 'document-encrypt'),('name',name),('submenu',''),
            ('unique-id',uid),('command',cmd),('description',name),
            ('range','*' if cmd==CREATE else '1'),('patterns',pattern)]:
            ET.SubElement(a,tag).text=value
        for tag in ['audio-files','image-files','other-files','text-files','video-files']:
            ET.SubElement(a,tag)
        if cmd==CREATE: ET.SubElement(a,'directories')
    ET.indent(tree, space='  ')
    changed = write_changed(uca, ET.tostring(root,encoding='utf-8',xml_declaration=True)+b'\n')
    mime = config/'mimeapps.list'
    cfg = configparser.RawConfigParser(strict=False); cfg.optionxform=str
    if mime.exists(): cfg.read(mime, encoding='utf-8')
    if not cfg.has_section('Default Applications'): cfg.add_section('Default Applications')
    for kind in ('application/pgp-encrypted', 'application/x-gpg'):
        cfg.set('Default Applications', kind, 'core-vault-decrypt-gpg.desktop')
    import io
    out=io.StringIO(); cfg.write(out,space_around_delimiters=False)
    changed = write_changed(mime,out.getvalue().encode()) or changed
    return changed

def main():
    p=argparse.ArgumentParser(); p.add_argument('--home',type=Path); p.add_argument('--refresh',action='store_true')
    a=p.parse_args()
    if os.getuid()==0 and a.home is None:
        raise SystemExit('Run as the desktop user, not sudo (or specify --home for image provisioning).')
    setup(a.home or Path(os.environ.get('HOME',str(Path.home()))))
    if a.refresh:
        # Explicitly requested refresh only, never terminate sessions at every login.
        subprocess.run(['thunar','-q'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        # Do not introduce xfdesktop into Vault's Openbox/tint2 session.
        if shutil.which('xfdesktop') and shutil.which('pgrep'):
            active=subprocess.run(['pgrep','-u',str(os.getuid()),'-x','xfdesktop'],stdout=subprocess.DEVNULL).returncode==0
            if active:
                subprocess.run(['xfdesktop','--quit'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                subprocess.Popen(['xfdesktop'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
    print('Core Vault backup actions and .gpg associations configured.')
if __name__=='__main__': main()
