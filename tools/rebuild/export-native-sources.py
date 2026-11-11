#!/usr/bin/env python3
"""Export the corresponding Vault native sources without installing either package."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request

REVISION = '938a22bafc25843f44dfeeabf4dcdb8625cbf61d'
EPOCH = 1794268800
COMPANION = 'bitcoin-core-vault-v0.4.0-calamares-source'
URL = 'https://github.com/btcpavao/bitcoin-core-vault-releases/releases/download/v0.5.0/' + COMPANION + '.tar.xz'
COMPANION_HASH = '62faea95f14b7d4314931d434fb647ee51e9430d7b83154681615487dddf8e6d'
CALAMARES_SOURCE_HASH = 'de3a01497ef80f2ada39ed9dbcee0478beea8a5386665293d4c9dd8b98c2c9f8'
THUNAR_NAME = 'thunar_4.20.2-1+deb13u1+corevault1_amd64.deb'
THUNAR_HASH = '1cf16b20f4b72e9bf0c4cee76630e51d72bf3026057269df193d724a29f7cbf5'
THUNAR_SOURCE_HASH = '1136ba32c8a8c9e7ea4b31115dfa8afa523dd3c46e91330943b5d8c85a02b6e8'


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify(path, expected):
    if digest(path) != expected:
        raise ValueError(f'Unexpected SHA-256 for {path.name}')


def git_file(repo, name):
    return subprocess.check_output(['git', '-C', repo, 'show', f'{REVISION}:{name}'])


def export_recipes(repo, directory):
    for name in ('inputs.env', 'InRelease.sha256', 'packages/build.sh', 'packages/report.py', 'packages/compare-trees.py'):
        target = directory / 'recipes' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(git_file(repo, 'tools/rebuild/' + name))


def pack(source, path):
    cmd = ['tar', '--sort=name', '--format=gnu', '--numeric-owner', '--owner=0', '--group=0',
           f'--mtime=@{EPOCH}', '--mode=u+rwX,go+rX,go-w', '-C', source.parent, '-cf', '-', source.name]
    with path.open('xb') as out, subprocess.Popen(cmd, stdout=subprocess.PIPE) as archive:
        subprocess.run(['xz', '--threads=1', '--check=crc64', '-6', '-c'], stdin=archive.stdout, stdout=out, check=True)
        archive.stdout.close()
        if archive.wait() != 0:
            raise RuntimeError('GNU tar could not create the source archive')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path, help='New output directory')
    parser.add_argument('--companion', type=Path, help='Already downloaded historical Calamares source companion')
    options = parser.parse_args()
    output = options.output.resolve()
    if output.exists():
        parser.error('Choose a new output directory')
    repo = Path(__file__).resolve().parents[2]
    # Validate that the complete frozen compiler revision is present in this checkout.
    recipe = git_file(repo, 'tools/rebuild/packages/build.sh').decode()
    with tempfile.TemporaryDirectory(prefix='vault-source-') as tmp:
        work = Path(tmp)
        exports = work / 'exports'
        exports.mkdir()
        calamares = work / 'calamares-3.3.14-1+corevault5-source'
        thunar = work / 'thunar-4.20.2-1+deb13u1+corevault2-source'
        calamares.mkdir()
        thunar.mkdir()
        companion = options.companion or work / (COMPANION + '.tar.xz')
        if not options.companion:
            with urllib.request.urlopen(URL, timeout=90) as response, companion.open('wb') as stream:
                shutil.copyfileobj(response, stream)
        verify(companion, COMPANION_HASH)
        with tarfile.open(companion) as outer:
            raw = outer.extractfile(COMPANION + '/historical/patched-calamares-main-source.tar.gz')
            source = work / 'historical-calamares.tar.gz'
            with raw, source.open('wb') as stream:
                shutil.copyfileobj(raw, stream)
            with outer.extractfile(COMPANION + '/README.md') as plain:
                (calamares / 'HISTORICAL-README.md').write_bytes(plain.read())
        verify(source, CALAMARES_SOURCE_HASH)
        with tarfile.open(source) as archive:
            archive.extractall(calamares, filter='data')
        # Copy the exact concrete changelog stanza emitted by the frozen public build recipe.
        start = recipe.index('calamares (3.3.14-1+corevault5) trixie;')
        end = recipe.index('\nENTRY\n', start)
        date = subprocess.check_output(['date', '-u', '-R', '-d', f'@{EPOCH}'], text=True,
                                       env={'LC_ALL': 'C', 'PATH': '/usr/bin:/bin'}).strip()
        stanza = recipe[start:end].replace('$date_utc', date) + '\n'
        changelog = calamares / 'source/debian/changelog'
        changelog.write_bytes(stanza.encode() + changelog.read_bytes())
        package = work / THUNAR_NAME
        package.write_bytes(git_file(repo, 'config/packages.chroot/' + THUNAR_NAME))
        verify(package, THUNAR_HASH)
        subprocess.run(['dpkg-deb', '-x', package, work / 'reference'], check=True)
        docs = work / 'reference/usr/share/doc/thunar/core-vault-source'
        verify(docs / 'Thunar-core-vault-source.tar.xz', THUNAR_SOURCE_HASH)
        shutil.copytree(docs, thunar / 'corresponding-source')
        # The tar.xz in corresponding-source is the complete patched tree compiled by build.sh.
        for root, records in [(calamares, {'historical_companion_sha256': COMPANION_HASH,
                                           'historical_patched_tree_sha256': CALAMARES_SOURCE_HASH}),
                              (thunar, {'historical_source_package_container_sha256': THUNAR_HASH,
                                        'patched_tree_sha256': THUNAR_SOURCE_HASH})]:
            export_recipes(repo, root)
            if root == thunar:
                scripts = root / 'recipes/thunar'
                scripts.mkdir()
                for name in ('prepare-private-prefix.py', 'build-thunar.py', 'test-dispatch.py'):
                    (scripts / name).write_bytes(git_file(repo, 'tools/core-vault/thunar/' + name))
            info = {'compiler_repository': 'https://github.com/btcpavao/bitcoin-core-vault-releases',
                    'compiler_commit': REVISION, 'source_date_epoch': EPOCH, 'sources': records}
            (root / 'PROVENANCE.json').write_text(json.dumps(info, indent=2, sort_keys=True) + '\n')
            pack(root, exports / (root.name + '.tar.xz'))
        files = sorted(exports.glob('*.tar.xz'))
        (exports / 'SHA256SUMS').write_text(''.join(f'{digest(f)}  {f.name}\n' for f in files))
        # A partial export never takes the name of the requested output directory.
        with tempfile.TemporaryDirectory(dir=output.parent, prefix='.source-export-') as staging:
            final = Path(staging) / 'ready'
            shutil.copytree(exports, final)
            final.rename(output)
        print((output / 'SHA256SUMS').read_text(), end='')


if __name__ == '__main__':
    main()
