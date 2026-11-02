#!/usr/bin/python3
"""Synthetic workflow probe for the designated disposable QEMU acceptance VM.

Put this developer script on the separate virtual USB fixture. Run from the
guest's temporary diagnostic console, never on the developer host. Output may
be directed to the VM serial port. It never prints wallet keys or passphrases.
Final shutdown, power-loss and offline raw-disk scanning are controller steps.
"""
import argparse
import json
import os
from pathlib import Path
import pwd
import resource
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid

sys.path.insert(0, '/usr/lib/core-vault')
ROOT = Path('/run/core-vault')


def guard():
    if Path('/sys/class/dmi/id/sys_vendor').read_text().strip() != 'QEMU':
        raise RuntimeError('Only the disposable QEMU test VM is allowed.')
    data = json.loads(subprocess.check_output(['lsblk', '-J', '-o', 'NAME,SERIAL'], text=True))
    if not any(row.get('serial') == 'CV_RAM_TEST_INTERNAL' for row in data['blockdevices']):
        raise RuntimeError('Designated standalone virtual disk serial is missing.')
    if not Path('/etc/core-vault/installation.json').is_file():
        raise RuntimeError('This probe requires the installed system, not Live mode.')


def environment():
    account = pwd.getpwnam('vault')
    if (account.pw_uid, account.pw_gid, account.pw_dir) != (1000, 1000, '/home/vault'):
        raise RuntimeError('Unexpected Vault account.')
    auth = Path('/run/lightdm/vault/xauthority')
    if not auth.is_file():
        auth = Path('/home/vault/.Xauthority')
    return dict(os.environ, HOME='/home/vault', XDG_RUNTIME_DIR='/run/user/1000',
                XDG_CONFIG_HOME='/home/vault/.config', XDG_CACHE_HOME='/home/vault/.cache',
                XDG_DATA_HOME='/home/vault/.local/share', XDG_STATE_HOME='/home/vault/.local/state',
                TMPDIR='/run/core-vault/tmp', TMP='/run/core-vault/tmp', TEMP='/run/core-vault/tmp',
                HISTFILE='/dev/null', PYTHONDONTWRITEBYTECODE='1', DISPLAY=':0', XAUTHORITY=str(auth))


def persistent_scan(marker=None, wallet=None):
    """Inspect current internal root files. Offline raw-image scan follows later."""
    device = Path('/').stat().st_dev
    def error(value):
        raise value
    for base, directories, files in os.walk('/', followlinks=False, onerror=error):
        directories[:] = [name for name in directories if not (Path(base) / name).is_symlink()
                           and (Path(base) / name).stat().st_dev == device]
        for name in files:
            path = Path(base) / name
            if path.is_symlink() or not path.is_file():
                continue
            if name == 'wallet.dat' or name.endswith('.core'):
                raise RuntimeError('Wallet/dump filename found on the internal root.')
            if marker or wallet:
                needles = [value.encode() for value in (marker, wallet) if value]
                with path.open('rb') as stream:
                    overlap = b''
                    while block := stream.read(1024 * 1024):
                        block = overlap + block
                        if any(value in block for value in needles):
                            raise RuntimeError('Synthetic private marker found on persistent root.')
                        overlap = block[-512:]
    print('[PASS] Current internal root contains no test wallet/dump or private marker')


def workflow(media):
    from runtime import (check_storage, check_core_mounts, rpc, wallet_files,
                         current_wallet_digest, wallet_digest, read_receipts, mount_at, WALLETS)
    from export import export_wallet, verify_export, media_for
    from layered_backend import recover_payload, unpack, size_limit, Budget
    if os.getuid() != 1000 or os.environ.get('HOME') != '/home/vault':
        raise RuntimeError('The workflow must run as the unprivileged Vault account.')
    check_storage()
    if resource.getrlimit(resource.RLIMIT_CORE) != (0, 0):
        raise RuntimeError('Core dump limits are not zero.')
    external, label = media_for(media / 'exports' / 'synthetic-wallet.gpg')
    if not external or (media / 'exports').is_symlink():
        raise RuntimeError('The separate virtual USB fixture is required.')
    marker = 'CORE_VAULT_FORENSIC_TEST_' + uuid.uuid4().hex
    wallet = 'cv-forensic-' + uuid.uuid4().hex
    os.umask(0o077)
    Path('/home/vault/Private Workspace/synthetic-marker.txt').write_text(marker)
    for path in (Path('/home/vault/.cache/forensic-marker'), ROOT / 'tmp' / 'forensic-marker'):
        path.write_text(marker)
        assert mount_at(path)['fstype'] == 'tmpfs'
    # This intentionally crashed synthetic process must never create a dump.
    crashed = subprocess.run(['/usr/bin/python3', '-c',
                              'import os,sys; marker=sys.stdin.read(); assert marker; os.abort()'],
                             input=marker, text=True, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
    assert crashed.returncode == -signal.SIGABRT
    print('[PASS] Synthetic process holds the unique private marker in memory and aborts with zero dump limits')
    subprocess.Popen(['/usr/local/bin/core-vault-bitcoin'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for attempt in range(160):
        try:
            rpc('getnetworkinfo')
            break
        except RuntimeError:
            time.sleep(.25)
    else:
        raise RuntimeError('The installed Core launcher did not provide local RPC.')
    rpc('createwallet', wallet)
    command = ['/usr/local/bin/bitcoin-cli', '-datadir=/home/vault/.bitcoin',
               '-rpcport=8332', '-rpcwallet=' + wallet, '-stdin', 'encryptwallet']
    result = subprocess.run(command, input='Synthetic wallet passphrase 2026!\n',
                            text=True, capture_output=True, timeout=30)
    if result.returncode:
        raise RuntimeError('Core wallet encryption failed.')
    address = rpc('getnewaddress', marker, wallet=wallet)
    destination = media / 'exports' / ('synthetic-wallet-' + uuid.uuid4().hex + '.gpg')
    password = ['Synthetic archive passphrase 2026!', 'Independent second synthetic phrase!']
    archive = export_wallet(wallet, destination, password)
    receipt = read_receipts()[wallet]
    assert current_wallet_digest(wallet, wallet_files()[wallet]) == receipt['wallet_digest']
    assert verify_export(receipt, password) == label
    try:
        verify_export(receipt, ['deliberately-wrong-synthetic-password'])
    except Exception:
        pass
    else:
        raise RuntimeError('Wrong passphrase was accepted.')
    # Recover the actual exported USB archive, never a second backup. Keep both
    # the extraction and the restored Core wallet within the verified RAM mount.
    initial_wallets, initial_receipts = set(wallet_files()), read_receipts()
    restored = wallet + '-restored-' + uuid.uuid4().hex
    restored_directory = WALLETS / restored
    if restored_directory.exists() or restored_directory.is_symlink():
        raise RuntimeError('The synthetic restored-wallet path already exists.')
    try:
        with tempfile.TemporaryDirectory(prefix='acceptance-restore-', dir=ROOT / 'export') as temporary:
            recovery = Path(temporary)
            assert mount_at(recovery)['fstype'] == 'tmpfs'
            assert mount_at(recovery)['maj:min'] == mount_at(ROOT, True)['maj:min']
            recovery = recovery / 'files'
            with recover_payload(archive, password, ram_root=ROOT / 'export') as payload:
                unpack(payload, recovery, limit=size_limit(ROOT / 'export'), budget=Budget())
            recovered = recovery / 'wallet.dat'
            if recovered.is_symlink() or not recovered.is_file() or wallet_digest(recovered) != receipt['wallet_digest']:
                raise RuntimeError('The archive recovery wallet differs from its verified logical digest.')
            print('[PASS] Actual exported USB archive recovers the verified wallet digest in RAM')
            rpc('restorewallet', restored, recovered, 'false')
            if not rpc('getaddressinfo', address, wallet=restored)['ismine']:
                raise RuntimeError('Official Core restore did not recover ownership of the synthetic address.')
            if address not in rpc('getaddressesbylabel', marker, wallet=restored):
                raise RuntimeError('Official Core restore did not recover the synthetic address label.')
            restored_info = rpc('getwalletinfo', wallet=restored)
            if not restored_info.get('private_keys_enabled', False) or restored_info.get('unlocked_until') != 0:
                raise RuntimeError('The restored Core wallet is not an encrypted, locked private-key wallet.')
            # Core may update bookkeeping when loading a restored database.
            # The extracted archive digest was checked before loading; compare
            # deterministic public receive/change descriptors after loading.
            def public_descriptors(name):
                entries = rpc('listdescriptors', 'false', wallet=name)['descriptors']
                if (not entries or any(not isinstance(entry.get('desc'), str) for entry in entries)
                        or not {False, True}.issubset({entry.get('internal', False) for entry in entries})):
                    raise RuntimeError('The Core wallet lacks public receive/change descriptors.')
                return sorted((entry.get('internal', False), entry['desc']) for entry in entries)
            if public_descriptors(restored) != public_descriptors(wallet):
                raise RuntimeError('The restored Core wallet differs from the original public receive/change descriptors.')
            print('[PASS] Official Core restorewallet recovers the address, label, public descriptors and locked encrypted wallet')
    finally:
        if restored in rpc('listwallets'):
            rpc('unloadwallet', restored, 'false')
        if restored_directory.exists() or restored_directory.is_symlink():
            # A failed safety check deliberately leaves the synthetic wallet in
            # RAM; do not recursively remove an unverified or loaded location.
            check_storage()
            check_core_mounts()
            if (restored_directory.is_symlink() or not restored_directory.is_dir()
                    or restored_directory.resolve(strict=True) != WALLETS.resolve(strict=True) / restored
                    or restored_directory.stat().st_uid != os.getuid()
                    or mount_at(restored_directory)['fstype'] != 'tmpfs'
                    or mount_at(restored_directory)['maj:min'] != mount_at(ROOT, True)['maj:min']):
                raise RuntimeError('The restored-wallet cleanup location is not the expected private RAM directory.')
            shutil.rmtree(restored_directory)
    if set(wallet_files()) != initial_wallets or read_receipts() != initial_receipts:
        raise RuntimeError('Recovery probe changed the original wallet inventory or export receipts.')
    print('[PASS] Recovery scratch wallet is unloaded and removed from confirmed RAM; Finish inventory and receipts are unchanged')
    proof = {'marker': marker, 'wallet': wallet, 'archive': str(archive), 'media': str(media)}
    (ROOT / 'state' / 'acceptance-test.json').write_text(json.dumps(proof))
    print('[PASS] Installed Core launcher, encryption, official backup and USB archive verification')
    print('[PASS] Installed verification rejects the wrong archive passphrase')
    print('FORENSIC_EXPECTATIONS=' + json.dumps(proof))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('diagnostics', 'workflow', 'empty', 'user-workflow'))
    parser.add_argument('--media', type=Path)
    args = parser.parse_args()
    guard()
    if args.action == 'user-workflow':
        workflow(args.media)
        return
    if os.geteuid() != 0:
        raise RuntimeError('Developer diagnostics require the disposable guest root console.')
    env = environment()
    command = ['/usr/sbin/runuser', '-u', 'vault', '--']
    if args.action == 'workflow':
        subprocess.run(command + ['/usr/bin/python3', str(Path(__file__).resolve()),
                                  'user-workflow', '--media', str(args.media)], env=env, check=True, timeout=120)
        proof = json.loads((ROOT / 'state' / 'acceptance-test.json').read_text())
        persistent_scan(proof['marker'], proof['wallet'])
    else:
        subprocess.run(command + ['/usr/local/bin/core-vault-security-check'], env=env, check=True)
        for path in ('/var/log', '/tmp', '/var/tmp', '/var/spool/cups', '/var/cache/cups'):
            data = json.loads(subprocess.check_output(['findmnt', '-J', '-T', path, '-o', 'FSTYPE,OPTIONS'], text=True))['filesystems'][0]
            assert data['fstype'] == 'tmpfs' and 'noswap' in data['options'].split(',')
        print('[PASS] System temporary files, logs and printer spools are noswap tmpfs')
        persistent_scan()
        if args.action == 'empty':
            assert not list(Path('/home/vault/.bitcoin/wallets').iterdir())
            assert not (ROOT / 'state' / 'exports.json').exists()
            assert not Path('/home/vault/Private Workspace/synthetic-marker.txt').exists()
            print('[PASS] New boot has empty wallets, receipts and private marker state')


if __name__ == '__main__':
    main()
