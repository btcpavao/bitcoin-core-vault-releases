#!/usr/bin/python3
"""Read-only source gate for complete removal of the BleachBit integration."""
from pathlib import Path
import argparse
import ast


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def check(root):
    inc = root / 'config/includes.chroot'
    template = root / 'tools/core-vault/runtime-template'
    helper_rel = 'usr/local/bin/core-vault-bleachbit-setup'
    for base in (inc, template):
        helper = base / helper_rel
        require(not helper.exists() and not helper.is_symlink(),
                'Removed BleachBit setup helper remains: ' + str(helper))
        for rel in ('usr/local/bin/core-vault-session',
                    'usr/local/bin/core-vault-guide',
                    'usr/share/core-vault/shred-policy.json'):
            require('bleachbit' not in (base / rel).read_text().lower(),
                    'Removed BleachBit integration remains: ' + str(base / rel))
        require(not any(base.rglob('*bleachbit*')),
                'Removed BleachBit runtime payload remains: ' + str(base))

    home = inc / 'usr/local/bin/core-vault-home'
    require(home.read_bytes() == (template / 'usr/local/bin/core-vault-home').read_bytes(),
            'Home active/template mismatch')
    home_tree = ast.parse(home.read_text(), str(home))
    tools = next(n.value for n in home_tree.body if isinstance(n, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == 'TOOLS' for t in n.targets))
    require(isinstance(tools, ast.List) and len(tools.elts) == 10,
            'Expected ten Home applications')
    cards = []
    for node in tools.elts:
        pairs = {ast.literal_eval(k): v for k, v in zip(node.keys, node.values)}
        cards.append((ast.literal_eval(pairs['title']), pairs))
    names = [title for title, pairs in cards]
    require(names == ['Bitcoin Core', 'Wallet Backup', 'Decrypt Backup', 'KeePassXC', 'Editor', 'Brasero', 'Print & Labels', 'Files', 'Terminal', 'Vault Guide'],
            'Unexpected Home card order')
    require('BleachBit' not in names and 'Private Workspace' not in names,
            'Removed Home buttons must remain absent')

    for rel in ('config/package-lists/core-vault.list.chroot',
                'tools/core-vault/manifests/core-vault.list.chroot'):
        packages = [line.split('#', 1)[0].strip()
                    for line in (root / rel).read_text().splitlines()]
        require('bleachbit' not in packages, 'Removed BleachBit package remains in ' + rel)
        require(packages.count('coreutils') == 1, 'Expected one GNU shred runtime package: coreutils')
    require(not list((root / 'config/packages.chroot').glob('*bleachbit*.deb')),
            'Removed BleachBit package is still staged')
    hook = root / 'config/hooks/live/0950-core-vault-installer-check.hook.chroot'
    require('bleachbit' not in hook.read_text().lower(),
            'Removed BleachBit installer payload expectation remains')
    print('VAULT BLEACHBIT REMOVAL SOURCE CHECK PASSED')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    check(args.project.expanduser().resolve(strict=True))
