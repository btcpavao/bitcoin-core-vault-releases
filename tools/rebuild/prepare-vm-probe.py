#!/usr/bin/python3
"""Bind the archived v0.4.0 VM checks to the independently reviewed candidate sources."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[2]
SOURCE_FILES = {
    'usr/lib/core-vault/runtime.py': 'config/includes.chroot/usr/lib/core-vault/runtime.py',
    'usr/lib/core-vault/export.py': 'config/includes.chroot/usr/lib/core-vault/export.py',
    'usr/lib/core-vault-backup/destinations.py': 'tools/core-vault/backup-src/src/destinations.py',
    'usr/lib/core-vault-backup/backup.py': 'tools/core-vault/backup-src/src/backup.py',
    'usr/lib/core-vault-backup/gpg_backend.py': 'tools/core-vault/backup-src/src/gpg_backend.py',
    'usr/lib/core-vault-backup/layered_backend.py': 'tools/core-vault/backup-src/src/layered_backend.py',
    'usr/local/bin/core-vault-bitcoin': 'config/includes.chroot/usr/local/bin/core-vault-bitcoin',
    'usr/local/bin/core-vault-finish': 'config/includes.chroot/usr/local/bin/core-vault-finish',
}
CORE_BINARIES = ('bitcoin-qt', 'bitcoin-cli')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def committed(revision, path):
    return subprocess.check_output(['git', '-C', str(ROOT), 'show', f'{revision}:{path}'])


def replace_assignment(text, name, value):
    result, count = re.subn(rf'^{name} = .+$', lambda _: f'{name} = {value!r}', text, flags=re.M)
    if count != 1:
        raise ValueError(f'Expected one archived assignment for {name}')
    return result


def prepare(directory, revision):
    if not re.fullmatch('[0-9a-f]{40}', revision):
        raise ValueError('Use the full candidate source commit ID.')
    expected = {name: digest(committed(revision, path)) for name, path in SOURCE_FILES.items()}
    binaries = json.loads(committed(revision, 'provenance/32.1/verification.json'))['binaries']
    for name in CORE_BINARIES:
        if not re.fullmatch('[0-9a-f]{64}', binaries[name]):
            raise ValueError(f'Invalid upstream digest for {name}')
        expected['usr/local/bin/' + name] = binaries[name]

    # The workflow validates the entire release archive before extraction. Check
    # the three inputs we rewrite as well, so reused or unknown helpers fail closed.
    files = {
        'ci-vm-guest-probe.py': '06f1142a507f6447550d0158bac3e381b13deeb004235dcaf84154169bcb7ff0',
        'ci-vm-reset-runner.py': '9144e141094e7caad7ce0d521c1d18a9ffd2a077f317a30c5e171ff18f68e31d',
        'ci-vm-acceptance.py': '2ee009d46bc32ef1ba51ffcb7d1dca07bf4d138aa1ac1cc5d2cf181fcc24163e',
    }
    original = {}
    for name, archive_hash in files.items():
        data = (directory / name).read_bytes()
        if digest(data) != archive_hash:
            raise ValueError(f'Unexpected archived {name}')
        original[name] = data.decode()

    probe = replace_assignment(original['ci-vm-guest-probe.py'], 'EXPECTED_RUNTIME_SHA256', expected)
    probe = replace_assignment(probe, 'QA_SOURCE_COMMIT', revision)
    # Keep the nine legacy identity keys used by cold-reset and forensic proofs.
    # Attest the new destination policy through the same three-way comparison.
    for original_line, new_line in (
        ('    for relative in required:\n', "    for relative in (*required, 'usr/lib/core-vault-backup/destinations.py'):\n"),
        ("    REPORT['runtime_sha256'] = hashes\n",
         "    REPORT['usb_destination_policy_sha256'] = hashes.pop('usr/lib/core-vault-backup/destinations.py')\n"
         "    REPORT['runtime_sha256'] = hashes\n"),
    ):
        if probe.count(original_line) != 1:
            raise ValueError('Unexpected archived production module check')
        probe = probe.replace(original_line, new_line)
    probe_bytes = probe.encode()
    probe_hash = digest(probe_bytes)
    runner = replace_assignment(original['ci-vm-reset-runner.py'], 'PROBE_SHA', probe_hash)
    runner = replace_assignment(runner, 'PROBE_BYTES', len(probe_bytes))
    controller = replace_assignment(original['ci-vm-acceptance.py'], 'RESET_PROBE_SHA256', probe_hash)
    controller = replace_assignment(controller, 'RESET_RUNNER_SHA256', digest(runner.encode()))
    updates = {'ci-vm-guest-probe.py': probe, 'ci-vm-reset-runner.py': runner,
               'ci-vm-acceptance.py': controller}
    for name, text in updates.items():
        ast.parse(text, filename=name)
    for name, text in updates.items():
        (directory / name).write_bytes(text.encode())
    print(json.dumps({'candidate_commit': revision, 'runtime_sha256': expected,
                      'guest_probe_sha256': probe_hash}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('harness_directory', type=Path)
    parser.add_argument('source_commit')
    args = parser.parse_args()
    prepare(args.harness_directory, args.source_commit)
