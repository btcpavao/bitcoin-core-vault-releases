"""Official KeePassXC AppImage releases, verified before extraction or activation."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import urllib.request

FINGERPRINT = 'BF5A669F2272CF4324C1FDA8CFB4C2166397D0D2'
KEY = Path('tools/core-vault/keepassxc-release-key.asc')
RELEASES = Path('/opt/keepassxc')
API = 'https://api.github.com/repos/keepassxreboot/keepassxc/releases/'
DOWNLOAD = 'https://github.com/keepassxreboot/keepassxc/releases/download/'


class UpdateError(Exception):
    pass


def version(value):
    if not isinstance(value, str) or not re.fullmatch(r'[1-9][0-9]?\.[0-9]{1,3}\.[0-9]{1,3}', value):
        raise UpdateError('The official KeePassXC release record is invalid.')
    return tuple(map(int, value.split('.')))


def fetch(url, destination=None, limit=1024*1024):
    request = urllib.request.Request(url, headers={'User-Agent': 'Bitcoin-Core-Vault-Builder/1.0',
                                                  'Accept': 'application/vnd.github+json'})
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            if not response.url.startswith('https://'):
                raise UpdateError('A secure software download was refused.')
            total = 0
            chunks = []
            output = destination.open('wb') if destination else None
            try:
                while True:
                    part = response.read(1024*1024)
                    if not part:
                        break
                    total += len(part)
                    if total > limit:
                        raise UpdateError('The software download exceeds the allowed size.')
                    if output:
                        output.write(part)
                    else:
                        chunks.append(part)
            finally:
                if output:
                    output.close()
            return b''.join(chunks) if destination is None else total
    except (OSError, ValueError) as exc:
        raise UpdateError('The official KeePassXC server could not be reached. Check the connection and system clock, then try again.') from exc


def release_record(record):
    if not isinstance(record, dict) or record.get('draft') is not False or record.get('prerelease') is not False:
        raise UpdateError('Only official stable KeePassXC releases are accepted.')
    number = record.get('tag_name')
    version(number)
    matches = []
    for asset in record.get('assets', []):
        name = asset.get('name', '')
        match = re.fullmatch(r'KeePassXC-' + re.escape(number) + r'(?:-([1-9][0-9]{0,2}))?-x86_64\.AppImage', name)
        if match:
            url = DOWNLOAD + number + '/' + name
            if asset.get('browser_download_url') != url:
                raise UpdateError('An unofficial KeePassXC download was refused.')
            matches.append((int(match[1] or 0), name, url))
    if not matches:
        raise UpdateError('The official release has no supported x86-64 AppImage.')
    _, name, url = max(matches)
    return dict(version=number, name=name, url=url)


def latest_release(number=None):
    if number is not None:
        version(number)
    data = fetch(API + ('latest' if number is None else 'tags/' + number))
    try:
        return release_record(json.loads(data))
    except (ValueError, TypeError, KeyError) as exc:
        raise UpdateError('The official KeePassXC release record could not be read.') from exc


def current_release(root=RELEASES):
    try:
        path = root / 'current/upstream-release.json'
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(root.resolve()) or not resolved.is_file():
            raise ValueError()
        record = json.loads(resolved.read_bytes())
        version(record['version'])
        if record['primary_signer'] != FINGERPRINT or not re.fullmatch('[a-f0-9]{64}', record['sha256']):
            raise ValueError()
        return record
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise UpdateError('The installed KeePassXC release record is unavailable.') from exc


def verify_image(image, signature, key=KEY):
    with tempfile.TemporaryDirectory(prefix='vault-keepass-signature-') as folder:
        result = subprocess.run(['/usr/bin/gpg', '--no-options', '--batch', '--homedir', folder,
                                 '--dearmor'], input=key.read_bytes(), capture_output=True, timeout=30)
        if result.returncode:
            raise UpdateError('The pinned KeePassXC release key could not be read.')
        ring = Path(folder) / 'release.gpg'
        ring.write_bytes(result.stdout)
        result = subprocess.run(['/usr/bin/gpgv', '--homedir', folder, '--keyring', str(ring),
                                 '--status-fd', '1', str(signature), str(image)],
                                capture_output=True, text=True, timeout=60)
        valid = [line.split() for line in result.stdout.splitlines()
                 if line.startswith('[GNUPG:] VALIDSIG ')]
        if result.returncode or not any(row[-1] == FINGERPRINT or row[2] == FINGERPRINT for row in valid):
            raise UpdateError('KeePassXC signature verification failed. The existing version has been kept.')
    with image.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def validate_runtime(directory):
    env = dict(PATH='/usr/sbin:/usr/bin:/sbin:/bin', LANG='C', LC_ALL='C',
               LD_LIBRARY_PATH=str(directory / 'usr/lib'))
    for relative in ('usr/bin/keepassxc', 'usr/plugins/platforms/libqxcb.so'):
        result = subprocess.run(['/usr/bin/ldd', str(directory / relative)], env=env,
                                capture_output=True, text=True, timeout=30)
        if result.returncode or 'not found' in result.stdout + result.stderr:
            raise UpdateError('The verified KeePassXC release needs an unavailable system library. Update Debian or use a reviewed Vault image. The existing release has been kept.')


def public_tree(directory):
    """Extracted software is public; AppImage extraction uses private directories."""
    for path in [directory, *directory.rglob('*')]:
        if path.is_symlink():
            continue
        if path.is_dir():
            path.chmod(0o755)
        elif path.is_file():
            path.chmod(0o755 if path.stat().st_mode & 0o111 else 0o644)


def install_release(candidate, root=RELEASES, key=KEY):
    """Caller is the root-only maintenance service or disposable ISO builder."""
    version(candidate['version'])
    expected = DOWNLOAD + candidate['version'] + '/' + candidate['name']
    if candidate['url'] != expected or not re.fullmatch(
            r'KeePassXC-' + re.escape(candidate['version']) + r'(?:-[1-9][0-9]{0,2})?-x86_64\.AppImage', candidate['name']):
        raise UpdateError('An unofficial KeePassXC release was refused.')
    if (root / 'current').exists() and version(candidate['version']) < version(current_release(root)['version']):
        raise UpdateError('An automatic KeePassXC downgrade was refused.')
    root.mkdir(parents=True, exist_ok=True, mode=0o755)
    root.chmod(0o755)
    with tempfile.TemporaryDirectory(prefix='.staging-', dir=root) as folder:
        staging = Path(folder)
        image = staging / candidate['name']
        signature = staging / (candidate['name'] + '.sig')
        fetch(candidate['url'], image, 256*1024*1024)
        fetch(candidate['url'] + '.sig', signature, 64*1024)
        digest = verify_image(image, signature, key)
        image.chmod(0o700)
        # Never execute an unverified download. AppImage extraction needs no FUSE.
        subprocess.run([str(image), '--appimage-extract'], cwd=staging, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=120)
        extracted = staging / 'squashfs-root'
        binary = extracted / 'usr/bin/keepassxc'
        if not binary.is_file() or not os.access(binary, os.X_OK):
            raise UpdateError('The verified KeePassXC image is incomplete.')
        validate_runtime(extracted)
        icons = sorted(extracted.rglob('keepassxc.png')) + sorted(extracted.rglob('org.keepassxc.KeePassXC.png'))
        icon = next((p for p in icons if p.is_file() and p.resolve().is_relative_to(extracted.resolve())), None)
        if icon is None:
            raise UpdateError('The verified KeePassXC application icon is missing.')
        shutil.copyfile(icon, extracted / 'upstream-icon.png')
        record = dict(version=candidate['version'], sha256=digest,
                      primary_signer=FINGERPRINT, source=candidate['url'])
        (extracted / 'upstream-release.json').write_text(json.dumps(record, indent=2) + '\n')
        destination = root / (candidate['version'] + '-' + digest[:16])
        if destination.exists():
            shutil.rmtree(extracted)
        else:
            extracted.rename(destination)
            destination.chmod(0o755)
        public_tree(destination)
        link = staging / 'current'
        link.symlink_to(destination.name)
        os.replace(link, root / 'current')
        fd = os.open(root, os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    return record
