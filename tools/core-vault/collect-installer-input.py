#!/usr/bin/python3
"""Collect selected installer/build sources for review; never run an installer.

No project home directories, wallet databases, encryption containers, ISO images,
.deb payloads, VM disks, package caches or Git credentials are exported.
Symlinks are recorded as metadata only and are never traversed.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
import tarfile
import tempfile
import zipfile

MAX_FILE = 4 * 1024 * 1024
MAX_TOTAL = 32 * 1024 * 1024
EXCLUDED_NAMES = {'bitcoin-qt', 'bitcoin-cli', 'bitcoind', '.cookie', 'wallet.dat',
                  'debug.log', 'id_rsa', 'id_ed25519', 'shadow', 'gshadow'}
EXCLUDED_DIRS = {'__pycache__', '.git', 'backups', '.bitcoin', 'wallets', 'Private Workspace',
                 'cache', 'chroot', 'binary', 'build-vm', 'release', '.build'}
SECRET_SUFFIXES = {'.dat', '.psbt', '.kdbx', '.hc', '.key', '.pem', '.iso', '.deb', '.qcow2', '.img', '.log', '.pyc'}
TEXT_SUFFIXES = {'.py', '.sh', '.h', '.hpp', '.cpp', '.md', '.txt', '.conf', '.cfg', '.json',
                 '.yaml', '.yml', '.xml', '.qss', '.qml', '.desc', '.desktop', '.rules',
                 '.service', '.socket', '.target', '.mount', '.timer', '.path', '.chroot',
                 '.chroot_install', '.binary', '.sha256'}
IMAGE_SUFFIXES = {'.png', '.webp', '.svg', '.jpg', '.jpeg'}
EXTRA_NAMES = {'config', 'themerc', 'tint2rc', 'build-success', 'shutdown-version', 'fstab',
               'hostname', 'hosts', 'locale.gen', 'settings', 'keyboard'}

PROJECT_TREES = (
    'auto', 'config/package-lists', 'config/hooks',
    'config/includes.chroot/etc',
    'config/includes.chroot/usr/local/bin', 'config/includes.chroot/usr/local/sbin',
    'config/includes.chroot/usr/lib/core-offline-installer',
    'config/includes.chroot/usr/lib/core-vault-installer',
    'config/includes.chroot/usr/share/core-vault',
    'config/includes.chroot/usr/share/core-signer',
    'config/includes.chroot/usr/share/plymouth/themes/core-signer',
    'config/includes.chroot/usr/share/plymouth/themes/core-vault',
    'config/includes.chroot/usr/share/xsessions',
    'config/includes.chroot/usr/share/themes/CoreVault',
    'tools/core-vault/installer-source', 'tools/core-vault/installer-template',
    'tools/core-vault/runtime-template', 'tools/core-vault/manifests',
    'tools/core-vault/docs', 'tools/core-offline/branding', 'tools/core-offline/docs',
)
REQUIRED = (
    'auto/config',
    'config/includes.chroot/usr/local/bin/core-vault-session',
    'config/includes.chroot/usr/local/bin/core-vault-file-places',
    'tools/core-vault/build-live-iso.sh',
    'tools/core-vault/installer-source/patch_calamares_source.py',
    'tools/core-vault/installer-source/CoreOfflineGuard.h',
    'tools/core-vault/installer-template/includes.chroot/etc/calamares/settings.conf',
    'tools/core-vault/installer-template/includes.chroot/etc/calamares/modules/partition.conf',
    'tools/core-vault/installer-template/includes.chroot/usr/lib/core-offline-installer/target.py',
)
OLD_PREFIXES = (
    'tools/core-offline/', 'config/includes.chroot/etc/calamares/',
    'config/includes.chroot/usr/lib/core-offline-installer/',
    'config/includes.chroot/etc/sudoers.d/',
)
OLD_EXACT = {
    'config/includes.chroot/usr/local/bin/core-offline-entry',
    'config/includes.chroot/usr/local/sbin/core-offline-installer',
    'config/hooks/live/0950-core-offline-installer-check.hook.chroot',
    'config/package-lists/core-offline-installer.list.chroot',
    'config/package-lists/core-offline-installed.list.chroot_install',
}


def allowed_name(name: str) -> bool:
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or any(p in EXCLUDED_DIRS for p in path.parts):
        return False
    if path.name in EXCLUDED_NAMES or path.suffix.lower() in SECRET_SUFFIXES:
        return False
    return (path.suffix.lower() in TEXT_SUFFIXES | IMAGE_SUFFIXES or
            path.name in EXTRA_NAMES or path.name.startswith(('core-vault-', 'core-signer-', 'core-offline-')) or
            '/sudoers.d/' in '/' + name or '/etc/skel/' in '/' + name)


def command(args: list[str], timeout: int = 20) -> dict:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                                env=dict(os.environ, LC_ALL='C', LANG='C'))
        return {'exit': result.returncode, 'stdout': result.stdout[-12000:], 'stderr': result.stderr[-2000:]}
    except (OSError, subprocess.SubprocessError) as exc:
        return {'error': str(exc)}


class Bundle:
    def __init__(self):
        self.files = {}
        self.links = {}
        self.skipped = []
        self.total = 0

    def add(self, name: str, data: bytes, mode: int = 0o644):
        if name in self.files:
            if self.files[name][0] != data:
                raise RuntimeError('Conflicting source path: ' + name)
            return
        if len(data) > MAX_FILE:
            self.skipped.append(name + ' (too large)'); return
        if PurePosixPath(name).suffix.lower() not in IMAGE_SUFFIXES:
            try:
                text = data.decode('utf-8')
            except UnicodeDecodeError:
                self.skipped.append(name + ' (not source text)'); return
            if '\0' in text:
                self.skipped.append(name + ' (binary data)'); return
        if self.total + len(data) > MAX_TOTAL:
            raise RuntimeError('Source bundle exceeds 32 MiB; no archive was written.')
        self.files[name] = (data, mode & 0o777)
        self.total += len(data)

    def add_path(self, root: Path, path: Path, prefix: str):
        relative = path.relative_to(root).as_posix()
        if not allowed_name(relative):
            return
        name = prefix + '/' + relative
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            self.links[name] = os.readlink(path)
            return
        if not stat.S_ISREG(info.st_mode):
            self.skipped.append(name + ' (not a regular file)'); return
        if not path.resolve().is_relative_to(root):
            raise RuntimeError('Refusing external source: ' + str(path))
        if info.st_size > MAX_FILE:
            self.skipped.append(name + ' (too large)'); return
        # Do not follow a leaf link replaced between lstat() and open().
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, 'rb') as stream:
            data = stream.read(MAX_FILE + 1)
        self.add(name, data, info.st_mode)

    def add_tree(self, root: Path, relative: str, prefix: str):
        tree = root / relative
        if tree.is_symlink():
            self.links[prefix + '/' + relative] = os.readlink(tree); return
        if not tree.is_dir():
            return
        for directory, dirs, files in os.walk(tree, followlinks=False):
            for part in list(dirs):
                p = Path(directory) / part
                if part in EXCLUDED_DIRS:
                    dirs.remove(part)
                elif p.is_symlink():
                    self.links[prefix + '/' + p.relative_to(root).as_posix()] = os.readlink(p)
                    dirs.remove(part)
            for part in files:
                self.add_path(root, Path(directory) / part, prefix)


def collect(root: Path, snapshot: Path | None) -> tuple[Bundle, dict]:
    bundle = Bundle()
    for relative in PROJECT_TREES:
        bundle.add_tree(root, relative, 'project')
    # Root-level build/test tools only: not arbitrary backup/build workspaces.
    for relative in ('tools/core-vault', 'tools/core-offline'):
        parent = root / relative
        if parent.is_dir() and not parent.is_symlink():
            for p in sorted(parent.iterdir()):
                if p.is_file() or p.is_symlink():
                    bundle.add_path(root, p, 'project')
    for relative in ('VAULT-V1.md', 'SIGNER-RC1.md'):
        p = root / relative
        if p.is_file():
            bundle.add_path(root, p, 'project')

    metadata = {
        'created_utc': datetime.now(timezone.utc).isoformat(),
        'purpose': 'Source review for Calamares integration; not an installable image.',
        'missing_current_sources': [s for s in REQUIRED if 'project/' + s not in bundle.files],
        'branch': command(['git', '-C', str(root), 'branch', '--show-current']),
        'commit': command(['git', '-C', str(root), 'rev-parse', 'HEAD']),
        'package_candidates': command(['apt-cache', 'policy', 'calamares', 'live-build', 'python3-yaml']),
        'legacy_snapshot': None,
        'cached_package_metadata': [],
    }
    # Inspect known cache markers, not the builder chroot.
    for relative in ('build-assets/core-offline-calamares/build-success',
                     'build-assets/core-offline-calamares/packages.sha256'):
        p = root / relative
        if p.is_file() and not p.is_symlink() and p.stat().st_size <= MAX_FILE:
            bundle.add('build-metadata/' + p.name, p.read_bytes())
    cache = root / 'config/packages.chroot'
    if cache.is_dir() and not cache.is_symlink():
        for p in sorted(cache.glob('*calamares*.deb')):
            if p.is_file() and not p.is_symlink():
                metadata['cached_package_metadata'].append({
                    'name': p.name, 'size_bytes': p.stat().st_size,
                    'metadata': command(['dpkg-deb', '-f', str(p), 'Package', 'Version', 'Architecture']),
                })
    if snapshot is not None and snapshot.is_file() and not snapshot.is_symlink():
        metadata['legacy_snapshot'] = snapshot.name
        # Read allowed members directly; do not extract or follow archive symlinks.
        with tarfile.open(snapshot, 'r:gz') as archive:
            for member in archive:
                name = str(PurePosixPath(member.name))
                if name not in OLD_EXACT and not name.startswith(OLD_PREFIXES):
                    continue
                if not allowed_name(name):
                    continue
                if member.issym() or member.islnk():
                    bundle.links['legacy/' + name] = member.linkname
                elif member.isfile() and member.size <= MAX_FILE:
                    handle = archive.extractfile(member)
                    if handle is not None:
                        with handle:
                            bundle.add('legacy/' + name, handle.read(MAX_FILE + 1), member.mode)
    return bundle, metadata


def write_bundle(bundle: Bundle, metadata: dict, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    name = 'bitcoin-core-vault-installer-input-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.zip'
    output = destination / name
    metadata['symlinks_not_followed'] = bundle.links
    metadata['skipped'] = bundle.skipped
    metadata['files'] = {name: {'sha256': hashlib.sha256(value[0]).hexdigest(), 'bytes': len(value[0]), 'mode': oct(value[1])}
                         for name, value in sorted(bundle.files.items())}
    fd, tmp = tempfile.mkstemp(prefix='.' + name, dir=destination)
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for name, (data, mode) in sorted(bundle.files.items()):
                info = zipfile.ZipInfo(name)
                info.external_attr = (stat.S_IFREG | mode) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, data)
            archive.writestr('MANIFEST.json', json.dumps(metadata, indent=2, ensure_ascii=False) + '\n')
            archive.writestr('README.txt', 'Source bundle for review only. No installer was started.\n'
                             'project/ = current selected build sources\nlegacy/ = selected original installer sources\n'
                             'Symlinks are metadata only in MANIFEST.json. No symlinks were traversed.\n'
                             'Review the archive before sharing; source files can contain manually added private text.\n')
        os.chmod(tmp, 0o600)
        os.replace(tmp, output)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--output-dir', type=Path, default=Path.home() / 'Downloads')
    parser.add_argument('--legacy-snapshot', type=Path,
                        default=Path.home() / 'core-signer-os-backups/before-live-only-20260929-103645.tar.gz')
    args = parser.parse_args()
    if os.geteuid() == 0:
        raise RuntimeError('Run without sudo, on the build computer.')
    root = args.project.expanduser().resolve(strict=True)
    if not (root / 'auto/config').is_file():
        raise RuntimeError('Not the expected build project.')
    bundle, metadata = collect(root, args.legacy_snapshot.expanduser())
    output = write_bundle(bundle, metadata, args.output_dir.expanduser())
    print('VAULT INSTALLER SOURCE BUNDLE CREATED')
    print(output)
    print(f'Files: {len(bundle.files)}; archive: {output.stat().st_size / 1024:.0f} KiB')
    print('SHA256:', hashlib.sha256(output.read_bytes()).hexdigest())
    if metadata['missing_current_sources']:
        print('Missing current installer files (legacy may contain them):')
        for relative in metadata['missing_current_sources']:
            print('  ' + relative)
    print('Only selected sources collected; no installation, disk formatting or ISO build was run.')
    print('Review this ZIP, then upload it to this conversation.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, tarfile.TarError, zipfile.BadZipFile) as exc:
        print('COLLECTION STOPPED:', exc, file=sys.stderr)
        raise SystemExit(1)
