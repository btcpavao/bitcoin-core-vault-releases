"""Consistent wallet snapshot -> RAM -> encrypted archive -> verification."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import tempfile
import time
import runtime
from runtime import ROOT, wallet_digest, file_digest, save_receipt, loaded_wallet_file

import sys
sys.path.insert(0, '/usr/lib/core-vault-backup')
from backup import create_backup, backup_destination, validate_password, consistent_inputs, selected_paths


def media_for(destination):
    """Best-effort location metadata, never permission to create or verify a backup."""
    fallback = str(destination.parent)
    try:
        result = subprocess.run(['/usr/bin/findmnt', '-J', '--uniq', '-T', fallback,
            '-o', 'TARGET,SOURCE,FSTYPE,MAJ:MIN'], capture_output=True, text=True, check=True, timeout=5)
        mount = json.loads(result.stdout)['filesystems'][0]
        label = mount['target']
        if mount['fstype'] in ('tmpfs', 'overlay', 'ramfs'):
            return False, label
        source = mount['source'].split('[')[0]
        if source.startswith('/dev/'):
            result = subprocess.run(['/usr/bin/lsblk', '-s', '-J', '-o', 'NAME,RM,TRAN', source],
                                    capture_output=True, text=True, check=True, timeout=5)
            def external(rows):
                return any(row.get('tran') == 'usb' or row.get('rm') is True or external(row.get('children', [])) for row in rows)
            return external(json.loads(result.stdout)['blockdevices']), label
        return False, label
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, IndexError, TypeError):
        return False, fallback


def receipt_format(receipt):
    if (not isinstance(receipt, dict) or type(receipt.get('schema')) is not int or
            receipt['schema'] != 3 or receipt.get('format') not in ('gpg-tar','gpg-wallet') or
            receipt.get('encryption_profile') not in ('AES256-MDC', 'AES256-OCB') or
            type(receipt.get('layers')) is not int or not 1 <= receipt['layers'] <= 16):
        raise RuntimeError('Invalid GPG backup verification record.')
    return receipt['format']


def verify_export(receipt, passwords, *, progress=None):
    runtime.check_storage()
    receipt_format(receipt)
    from layered_backend import recover_payload, unpack, size_limit, Budget, passphrases, is_direct_wallet, is_tar_payload
    passphrases(passwords)
    path = Path(receipt['archive'])
    from gpg_backend import _path
    path = _path(path)
    if not path.is_file() or path.stat().st_size <= 0:
        raise RuntimeError('The exported encrypted backup is missing.')
    if file_digest(path) != receipt['archive_sha256']:
        raise RuntimeError('The exported backup changed after verification.')
    _, label = media_for(path)
    budget = Budget(progress)
    with tempfile.TemporaryDirectory(prefix='verify-', dir=ROOT / 'export') as temporary:
        recovered = Path(temporary) / 'files'
        with recover_payload(path, passwords, ram_root=ROOT / 'export', progress=budget) as payload:
            if is_direct_wallet(payload):
                if receipt['format'] != 'gpg-wallet':
                    raise RuntimeError('Unexpected wallet backup payload format.')
                recovered.mkdir(mode=0o700)
                destination = recovered/'wallet.dat'
                shutil.copyfile(payload, destination)
                destination.chmod(0o600)
            else:
                if receipt['format'] != 'gpg-tar' or not is_tar_payload(payload):
                    raise RuntimeError('Unexpected archive backup payload format.')
                unpack(payload, recovered, limit=size_limit(ROOT / 'export'), budget=budget)
        contents = list(recovered.iterdir())
        if len(contents) != 1 or contents[0].name != 'wallet.dat' or not contents[0].is_file():
            raise RuntimeError('Expected exactly one wallet.dat in this backup.')
        wallet = contents[0]
        budget.check()
        if (file_digest(wallet) != receipt['wallet_backup_sha256'] or
                wallet_digest(wallet) != receipt['wallet_digest']):
            raise RuntimeError('The backup does not contain the expected wallet snapshot.')
    return label


def export_wallet(wallet, destination, passwords, *, progress=None):
    runtime.check_storage()
    destination = backup_destination(destination)
    _, label = media_for(destination)
    paths = selected_paths([loaded_wallet_file(wallet)])
    with consistent_inputs(paths, runtime) as inputs:
        raw = inputs[0]
        digest = wallet_digest(raw)
        result = create_backup([raw], destination, passwords, policy=runtime, progress=progress)
        receipt = {'schema': 3, 'format': 'gpg-wallet', 'layers': len(passwords),
                   'encryption_profile': 'AES256-MDC',
                   'archive': str(result), 'archive_sha256': file_digest(result),
                   'wallet_backup_sha256': file_digest(raw), 'wallet_digest': digest,
                   'created': int(time.time()), 'media': label}
        verify_export(receipt, passwords, progress=progress)
        save_receipt(wallet, receipt)
        return result
