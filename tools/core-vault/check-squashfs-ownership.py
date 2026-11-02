#!/usr/bin/python3
"""Verify numeric ownership and mode of critical live-system paths.

Catches remasters that accidentally rewrite all non-root ownership to root:root,
which prevents dbus-daemon-launch-helper from starting the KPMcore D-Bus helper,
leaving Calamares' disk selector empty. Read-only; no disk modifications.
"""
from pathlib import Path
import argparse,json,re,subprocess

ROOT=Path(__file__).resolve().parents[2]
BASELINE=ROOT/'tools/core-vault/manifests/critical-ownership-debian13.json'

def verify(squashfs):
    image=Path(squashfs).resolve(strict=True)
    expected=json.loads(BASELINE.read_text())['required']
    proc=subprocess.run(['unsquashfs','-lln',str(image),*sorted(expected)],
                        stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=90)
    if proc.returncode:
        raise RuntimeError('SquashFS numeric ownership inspection failed: '+proc.stderr[-500:])
    rows={}
    for line in proc.stdout.splitlines():
        if 'squashfs-root/' not in line:continue
        m=re.match(r'^([dlcbps-][rwxstST-]{9})\s+(\d+)/(\d+)\s+',line)
        if m:
            path=line.split('squashfs-root/',1)[1].split(' -> ')[0]
            rows[path]={'uid':int(m[2]),'gid':int(m[3]),'mode':m[1]}
    wrong=[(p,rec,rows.get(p)) for p,rec in expected.items() if rows.get(p)!=rec]
    if wrong:
        raise RuntimeError('Unsafe SquashFS ownership/mode regression: '+repr(wrong[:6]))
    helper=rows['usr/lib/dbus-1.0/dbus-daemon-launch-helper']
    if not helper['mode'][3]=='s' or not helper['mode'][6]=='x':
        raise RuntimeError('D-Bus launch helper must remain setuid-root and group executable')
    print('VAULT CRITICAL SQUASHFS UID/GID/MODE CHECK PASSED ('+str(len(expected))+' paths)')
    return len(expected)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--squashfs',required=True,type=Path)
    verify(p.parse_args().squashfs)
