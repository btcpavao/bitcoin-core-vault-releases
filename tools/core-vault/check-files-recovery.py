#!/usr/bin/python3
"""Source-only checks. No wallet, device, desktop or printer is opened."""
import ast
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
INC = ROOT / 'config/includes.chroot'
BIN = INC / 'usr/local/bin'
TEMPLATE = ROOT / 'tools/core-vault/runtime-template/usr/local/bin'
NEW_STEP = '3. Use Bitcoin Core to restore the wallet.dat backup file.'


def main():
    for name in ('core-vault-file-places', 'core-vault-print'):
        p = BIN / name
        compile(p.read_text(encoding='utf-8'), str(p), 'exec')
        if not (p.stat().st_mode & 0o111):
            raise RuntimeError('Not executable: ' + str(p))
        if p.read_bytes() != (TEMPLATE / name).read_bytes():
            raise RuntimeError('Runtime template differs: ' + name)
    session = BIN / 'core-vault-session'
    s = session.read_text(encoding='utf-8')
    if s.count('/usr/local/bin/core-vault-file-places --apply') != 1:
        raise RuntimeError('Places initialization must run exactly once per session.')
    subprocess.run(['/bin/sh', '-n', str(session)], check=True)
    if session.read_bytes() != (TEMPLATE / session.name).read_bytes():
        raise RuntimeError('Session runtime template differs.')
    tree = ast.parse((BIN / 'core-vault-print').read_text(encoding='utf-8'))
    values = [ast.literal_eval(n.value) for n in tree.body
              if isinstance(n, ast.Assign)
              and any(isinstance(t, ast.Name) and t.id == 'RECOVERY_TEMPLATE' for t in n.targets)]
    if len(values) != 1 or NEW_STEP not in values[0].splitlines():
        raise RuntimeError('Recovery template must explicitly restore wallet.dat in Bitcoin Core.')
    if 'software normally used for this wallet' in values[0]:
        raise RuntimeError('Old ambiguous recovery instruction remains.')
    for relative in ('config/package-lists/core-vault.list.chroot',
                     'tools/core-vault/manifests/core-vault.list.chroot'):
        packages = [(line.split('#', 1)[0]).strip() for line in (ROOT / relative).read_text().splitlines()]
        if 'xfconf' not in packages:
            raise RuntimeError('Missing explicit xfconf package in ' + relative)
    print('VAULT FILES + RECOVERY SOURCE CHECK PASSED')


if __name__ == '__main__':
    main()
