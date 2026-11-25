#!/usr/bin/python3
"""Configure authenticated packages only in the isolated Vault build filesystem."""
from pathlib import Path
import hashlib
import json
import stat
import subprocess

stage = Path('/home/pavao/vault-t2-build-20261124')
root = stage / 'image-work/rootfs'
manifest = stage / 'qml-inputs/installer-runtime-input-manifest.json'
native = stage / 'native-calamares/calamares_3.3.14-1+corevault9localt530fix1_amd64.deb'

def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()

if not native.is_file() or root == Path('/'):
    raise SystemExit('Expected the compiled native package and separate image.')
inputs = json.loads(manifest.read_text())
packages = []
for item in inputs['artifacts']:
    path = Path(item['local_path'])
    if path.parent != stage / 'qml-inputs':
        raise SystemExit('Dependency must be inside the read-only build input mount.')
    if sha(path) != item['verified_sha256'] or path.stat().st_size != item['verified_bytes']:
        raise SystemExit('Authenticated package changed: ' + str(path))
    packages.append('/run/core-vault-build-installer/' + path.name)
for name in ('core-vault-build-inputs', 'core-vault-build-native', 'core-vault-build-installer'):
    (root / 'run' / name).mkdir(exist_ok=True)
policy = root / 'usr/sbin/policy-rc.d'
if policy.exists() or policy.is_symlink():
    raise SystemExit('An existing image service policy requires preservation.')
policy.write_text('#!/bin/sh\n# Temporary image-build policy: do not start services.\nexit 101\n')
policy.chmod(0o755)
prefix = [
    'unshare', '--user', '--map-root-user', '--mount', '--pid', '--fork',
    str(stage / 'image-namespace-inner'), '/usr/bin/dpkg',
]
helper = root / 'usr/sbin/update-smart-drivedb'
helper_mode = None
try:
    subprocess.run(prefix + ['--force-confold', '--no-triggers', '--unpack',
                             *packages, '/run/core-vault-build-native/' + native.name],
                   check=True)
    if helper.is_symlink() or not helper.is_file():
        raise RuntimeError('Expected the packaged SMART database helper.')
    helper_mode = stat.S_IMODE(helper.stat().st_mode)
    # The package postinst has an explicit non-executable-helper fallback that
    # copies the bundled database. Select it to avoid its smartctl validation
    # invocation while the user has requested no runtime tests.
    helper.chmod(helper_mode & ~0o111)
    subprocess.run(prefix + ['--force-confold', '--configure',
                             *[item['Package'] for item in inputs['artifacts']],
                             'calamares'], check=True)
finally:
    if helper_mode is not None:
        helper.chmod(helper_mode)
    policy.unlink()
print('Configured native Calamares and six runtime dependencies inside the image. No host packages, tests or installer execution.')
