#!/usr/bin/env python3
"""Compare the Vault native source bundles against authenticated Debian source trees."""
import argparse
import hashlib
import json
import lzma
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
MIRROR = 'https://snapshot.debian.org/archive/debian/20261109T000000Z'
KEYRING = '/usr/share/keyrings/debian-archive-keyring.gpg'
VERSIONS = {'calamares': '3.3.14-1', 'thunar': '4.20.2-1+deb13u1'}


def check_digest(path, expected):
    with path.open('rb') as stream:
        actual = hashlib.file_digest(stream, 'sha256').hexdigest()
    if expected != actual:
        raise ValueError(f'SHA-256 mismatch: {path.name}')


def get(path, remote, expected):
    subprocess.run(['curl', '--fail', '--location', '--retry', '4', '--silent', '--show-error',
                    '--output', path, f'{MIRROR}/{remote}'], check=True)
    check_digest(path, expected)


def sha_entries(value):
    return {name: digest for digest, size, name in (line.split() for line in value.splitlines() if line.strip())}


def fields(paragraph):
    result = {}
    for line in paragraph.splitlines():
        if line.startswith((' ', '\t')):
            result[name] += '\n' + line.strip()
        else:
            name, value = line.split(':', 1)
            result[name] = value.strip()
    return result


def index(work):
    envelope = work / 'InRelease'
    release = work / 'Release'
    expected = (ROOT / 'InRelease.sha256').read_text().splitlines()[0].split()[0]
    get(envelope, 'dists/trixie/InRelease', expected)
    home = work / 'gnupg'
    home.mkdir(mode=0o700)
    subprocess.run(['gpg', '--no-options', '--batch', '--homedir', home, '--no-default-keyring',
                    '--keyring', KEYRING, '--output', release, '--decrypt', envelope], check=True)
    expected = sha_entries(fields(release.read_text())['SHA256'])['main/source/Sources.xz']
    source_index = work / 'Sources.xz'
    get(source_index, 'dists/trixie/main/source/Sources.xz', expected)
    records = {}
    with lzma.open(source_index, 'rt') as stream:
        for paragraph in stream.read().split('\n\n'):
            name = paragraph.split('\n', 1)[0].removeprefix('Package: ')
            if name in VERSIONS:
                record = fields(paragraph)
                if record['Version'] == VERSIONS[name]:
                    records[name] = record
    if records.keys() != VERSIONS.keys():
        raise ValueError('Missing pinned source versions in Debian archive')
    return records


def file_states(root):
    entries = {}
    for p in root.rglob('*'):
        rel = p.relative_to(root)
        if rel.parts[0] == '.pc':
            continue
        mode = p.lstat().st_mode
        if stat.S_ISLNK(mode):
            state = {'symlink': os.readlink(p)}
        elif stat.S_ISREG(mode):
            state = {'sha256': hashlib.sha256(p.read_bytes()).hexdigest(), 'executable': bool(mode & 0o111)}
        elif stat.S_ISDIR(mode):
            continue
        else:
            raise ValueError(f'Unexpected file type for {rel}')
        entries[str(rel)] = state
    return entries


def compare(work, output, name, record, bundle):
    build = work / name
    build.mkdir()
    for filename, expected in sha_entries(record['Checksums-Sha256']).items():
        get(build / filename, f"{record['Directory']}/{filename}", expected)
    dsc = next(build.glob('*.dsc'))
    debian, vault = build / 'debian', build / 'vault'
    subprocess.run(['dpkg-source', '--no-check', '-x', dsc, debian], cwd=build, check=True)
    vault.mkdir()
    if name == 'calamares':
        subprocess.run(['tar', '-xJf', bundle, '--strip-components=2', '-C', vault,
                        bundle.name.removesuffix('.tar.xz') + '/source'], check=True)
    else:
        member = bundle.name.removesuffix('.tar.xz') + '/corresponding-source/Thunar-core-vault-source.tar.xz'
        inner = build / 'patched.tar.xz'
        with inner.open('wb') as stream:
            subprocess.run(['tar', '-xOJf', bundle, member], stdout=stream, check=True)
        subprocess.run(['tar', '-xJf', inner, '--strip-components=1', '-C', vault], check=True)
    a, b = file_states(debian), file_states(vault)
    changed = {p: {'debian': a.get(p), 'vault': b.get(p)} for p in sorted(a.keys() | b.keys()) if a.get(p) != b.get(p)}
    # .pc holds dpkg-source's internal quilt patch bookkeeping. Its applied source changes are compared.
    for tree in (debian, vault):
        if (tree / '.pc').exists():
            shutil.rmtree(tree / '.pc')
    with (output / f'{name}.patch').open('wb') as stream:
        result = subprocess.run(['git', '-c', 'core.fileMode=true', '-c', 'core.autocrlf=false', 'diff',
                                 '--no-index', '--no-ext-diff', '--no-textconv', '--binary', '--full-index',
                                 '--no-renames', '--no-color', '--diff-algorithm=myers', '-U3',
                                 '--src-prefix=', '--dst-prefix=', 'debian', 'vault'], cwd=build, stdout=stream)
    if result.returncode not in (0, 1):
        raise RuntimeError(f'git diff failed for {name}')
    return {'debian_version': record['Version'], 'upstream_files': sha_entries(record['Checksums-Sha256']),
            'debian_paths': len(a), 'vault_paths': len(b), 'changed_paths': changed}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundles', type=Path, help='Folder with the two Vault source-only .tar.xz files')
    parser.add_argument('output', type=Path, help='New output directory for the two patches and inventory')
    args = parser.parse_args()
    expected = (ROOT / 'packages/evidence/938a22ba-sources.SHA256SUMS').read_text()
    archives = {line.split()[1]: line.split()[0] for line in expected.splitlines()}
    for filename, digest in archives.items():
        check_digest(args.bundles / filename, digest)
    result = {}
    output = args.output.resolve()
    if output.exists():
        parser.error('Use a new output directory')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory(dir=output.parent) as staging:
        work = Path(tmp)
        records = index(work)
        stage = Path(staging) / 'review'
        stage.mkdir()
        for name, record in records.items():
            bundle = args.bundles.resolve() / next(f for f in archives if f.startswith(name + '-'))
            result[name] = compare(work, stage, name, record, bundle)
        (stage / 'files.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
        stage.rename(output)
    for name, entry in result.items():
        print(f"{name}: {len(entry['changed_paths'])} changed paths. Read {output}/{name}.patch")


if __name__ == '__main__':
    main()
