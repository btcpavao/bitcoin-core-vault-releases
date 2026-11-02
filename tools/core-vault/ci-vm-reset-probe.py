#!/usr/bin/python3
"""QA-only RAM reset evidence in an owned offline QEMU fixture.

arm-existing runs after the existing production guest probe and before native
GUI acceptance. arm-fresh creates a separate synthetic abrupt-loss fixture,
without invoking Finish or UI. probe performs only observations before Core,
backup, decryption, or a new wallet is launched. No VM is stopped here.

The controller separately proves same disk/USB/OVMF files, genuine Finish or
identity-guarded SIGKILL, reaping and a new QEMU process. This helper does not
claim physical DRAM sanitization, a disk scan, or successful poweroff.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
HEX = re.compile(r'[0-9a-f]{64}')
NONCE = re.compile(r'[0-9a-f]{32}')
BOOT = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')
WALLET = re.compile(r'cv-forensic-ci-(?:7z|gpg)-[0-9a-f]{32}')
ROOT = Path('/run/core-vault')
HOME = Path('/home/vault')
CORE = HOME / '.bitcoin'
WALLETS = CORE / 'wallets'
PRIVATE = HOME / 'Private Workspace'
STATE = ROOT / 'state'
MAX_JSON = 128 * 1024
TIMEOUT = 1200


class ResetFailure(RuntimeError):
    """Fixed public labels; native diagnostics and secrets are never emitted."""


class ResetDeadline(BaseException):
    pass


def require(condition, label):
    if not condition:
        raise ResetFailure(label)


def fingerprint(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def checked_path(value):
    path = Path(os.path.abspath(value))
    require(not any(ord(c) < 32 or ord(c) == 127 for c in str(path)), 'unsafe-path')
    for part in (path, *path.parents):
        require(not part.is_symlink(), 'symlinked-path')
    return path


def owned_bytes(path, limit, expected=None):
    """Read one bounded no-follow owned file with stable FD/path identity."""
    path = checked_path(path)
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid() and
            before.st_nlink == 1 and 0 < before.st_size <= limit, 'unsafe-public-file')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    try:
        require(fingerprint(os.fstat(fd)) == fingerprint(before), 'public-file-open-race')
        parts, total = [], 0
        while True:
            block = os.read(fd, min(65536, limit + 1 - total))
            if not block:
                break
            parts.append(block)
            total += len(block)
            require(total <= limit, 'public-file-too-large')
        data = b''.join(parts)
        require(len(data) == before.st_size and fingerprint(os.fstat(fd)) == fingerprint(before)
                and fingerprint(path.lstat()) == fingerprint(before), 'public-file-read-race')
    finally:
        os.close(fd)
    sha = hashlib.sha256(data).hexdigest()
    require(expected is None or HEX.fullmatch(expected) and sha == expected, 'public-file-sha256-mismatch')
    return data, sha


def read_json(path, expected=None):
    data, sha = owned_bytes(path, MAX_JSON, expected)
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'duplicate-json-key')
            result[key] = value
        return result
    value = json.loads(data, object_pairs_hook=unique)
    require(isinstance(value, dict), 'public-json-is-not-object')
    return value, sha


def absent(path):
    """Only genuine ENOENT means absent. Links/errors/special files all fail."""
    path = Path(path)
    for parent in path.parents:
        info = parent.lstat()
        require(stat.S_ISDIR(info.st_mode), 'absence-parent-is-not-directory')
    try:
        path.lstat()
    except FileNotFoundError:
        return
    raise ResetFailure('old-private-path-survived')


def boot_id(path=Path('/proc/sys/kernel/random/boot_id')):
    value = path.read_text().strip()
    require(BOOT.fullmatch(value) and value != '00000000-0000-0000-0000-000000000000', 'invalid-boot-id')
    return value


def same_runtime(runtime):
    require(all(getattr(runtime, key) == value for key, value in
                (('ROOT', ROOT), ('HOME', HOME), ('CORE', CORE), ('WALLETS', WALLETS),
                 ('PRIVATE', PRIVATE), ('STATE', STATE))), 'unexpected-production-private-paths')


def paths(phase, case, nonce):
    require(phase in ('live', 'installed') and case in ('normal', 'abrupt') and NONCE.fullmatch(nonce),
            'invalid-reset-fixture-identity')
    stem = 'ci-reset-' + phase + '-' + case + '-' + nonce
    return {'stem': stem,
            'sentinels': [STATE / (stem + '-sentinel'), ROOT / 'tmp' / (stem + '-nonce'),
                          HOME / '.cache' / (stem + '-nonce')],
            'recovered': PRIVATE / (stem + '-recovered.dat'),
            'gui_recovered': PRIVATE / ('ci-gui-recovered-' + phase + '.dat')}


def fixed_absence(phase, case, nonce, wallets):
    selected = paths(phase, case, nonce)
    return [*selected['sentinels'], selected['recovered'], selected['gui_recovered'],
            STATE / 'exports.json', STATE / 'exports.new',
            STATE / 'core-runtime/core-vault-hide-sync.log', CORE / 'debug.log',
            CORE / '.cookie', CORE / 'settings.json',
            *[WALLETS / name for name in sorted(wallets)]]


def validate_ready(value, args):
    fields = {'schema', 'status', 'case', 'nonce', 'phase', 'firmware', 'source_boot_id',
              'execution_uid', 'target_serial', 'fixture_serial', 'helper_sha256',
              'guest_probe_sha256', 'runtime_sha256', 'usb_control', 'wallets', 'archives',
              'core_state', 'armed', 'scope'}
    require(set(value) == fields and type(value['schema']) is int and value['schema'] == 1
            and value['status'] == 'USBREADY', 'invalid-ready-schema')
    require(all(value[key] == getattr(args, key) for key in ('case', 'nonce', 'phase', 'firmware')),
            'ready-fixture-identity-mismatch')
    require(value['execution_uid'] == 1000 and type(value['execution_uid']) is int and
            value['target_serial'] == 'CV_RAM_TEST_INTERNAL' and value['fixture_serial'] == 'CV_RAM_TEST_USB',
            'ready-machine-identity-mismatch')
    require(value['helper_sha256'] == args.helper_sha256 and value['guest_probe_sha256'] == args.probe_sha256,
            'ready-helper-identity-mismatch')
    require(isinstance(value['source_boot_id'], str) and BOOT.fullmatch(value['source_boot_id']) and
            value['source_boot_id'] != '00000000-0000-0000-0000-000000000000', 'invalid-source-boot-id')
    require(isinstance(value['runtime_sha256'], dict) and len(value['runtime_sha256']) == 8 and
            all(isinstance(key, str) and isinstance(sha, str) and HEX.fullmatch(sha)
                for key, sha in value['runtime_sha256'].items()), 'invalid-runtime-hash-set')
    wallets = value['wallets']
    require(isinstance(wallets, list) and len(wallets) == 2 and len(set(wallets)) == 2 and
            all(isinstance(name, str) and WALLET.fullmatch(name) for name in wallets) and
            {name.split('-')[3] for name in wallets} == {'7z', 'gpg'}, 'invalid-ready-wallets')
    archives = value['archives']
    require(isinstance(archives, list) and len(archives) == 2 and
            all(isinstance(item, dict) and set(item) == {'format', 'name', 'sha256'} and
                item['format'] in ('7z', 'gpg') and isinstance(item['name'], str) and
                re.fullmatch(r'cv-forensic-ci-(?:7z|gpg)-[0-9a-f]{32}-encrypted\.(?:7z|gpg)', item['name']) and
                isinstance(item['sha256'], str) and HEX.fullmatch(item['sha256']) and
                item['name'] == next(name for name in wallets if name.startswith('cv-forensic-ci-' + item['format'] + '-'))
                               + '-encrypted.' + item['format'] for item in archives) and
            {item['format'] for item in archives} == {'7z', 'gpg'}, 'invalid-ready-archives')
    require(value['armed'] == {'wallet_inventory_present': True, 'receipts_present': True,
                             'recovered_snapshot_authenticated': True, 'sentinels_present': True,
                             'core_ram_logs_present': True, 'core_state_observed': True,
                             'finish_invoked_by_reset_helper': False}
            and all(type(flag) is bool for flag in value['armed'].values()), 'ready-was-not-armed')
    require(value['core_state'] in ('closed', 'running-loaded', 'running-unloaded') and
            (args.case != 'abrupt' or value['core_state'] == 'running-loaded'), 'invalid-ready-core-state')
    control = value['usb_control']
    selected = paths(args.phase, args.case, args.nonce)
    expected = ('CORE_VAULT_USBREADY_' + args.phase + '_' + args.case + '_' + args.nonce + '\n').encode()
    require(isinstance(control, dict) and set(control) == {'name', 'sha256', 'bytes'} and
            control['name'] == selected['stem'] + '-USBREADY.txt' and
            control['sha256'] == hashlib.sha256(expected).hexdigest() and
            type(control['bytes']) is int and control['bytes'] == len(expected), 'invalid-usb-control')
    return wallets


def fsync_public(path, payload):
    require(0 < len(payload) <= MAX_JSON, 'oversized-public-write')
    path = checked_path(path)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        with os.fdopen(fd, 'wb', closefd=False) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(fd)
    finally:
        os.close(fd)
    parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        os.fsync(parent)
    finally:
        os.close(parent)
    return hashlib.sha256(payload).hexdigest()


def load_public_probe(args):
    require(HEX.fullmatch(args.helper_sha256) and HEX.fullmatch(args.probe_sha256), 'invalid-helper-sha256')
    here = checked_path(__file__)
    owned_bytes(here, 256 * 1024, args.helper_sha256)
    source = here.parent / 'ci-vm-guest-probe.py'
    source_bytes, _ = owned_bytes(source, 256 * 1024, args.probe_sha256)
    # Execute the exact bytes that were FD-bound and hashed, rather than
    # reopening the writable USB pathname in an import loader.
    spec = importlib.util.spec_from_loader('core_vault_ci_reset_public_probe', loader=None, origin=str(source))
    require(spec is not None, 'guest-probe-cannot-load')
    module = importlib.util.module_from_spec(spec)
    module.__file__ = str(source)
    sys.modules[spec.name] = module
    exec(compile(source_bytes, str(source), 'exec'), module.__dict__)
    require(Path(module.__file__) == source, 'unexpected-guest-probe-module')
    return module


def fixture_context(args, public):
    require(os.getuid() == os.geteuid() == 1000, 'reset-requires-normal-vault-account')
    _, fixture = public.machine_guard(args.phase, args.firmware)
    media, mount = public.fixture_mount(fixture, args.media)
    require(checked_path(__file__).parent == media, 'reset-helper-is-not-on-designated-usb')
    public.REPORT = {'checks': []}
    runtime, export, gpg = public.production_modules()
    same_runtime(runtime)
    public.policy_attestation(runtime, args.phase)
    return runtime, export, gpg, media, mount


def no_core_process(proc=Path('/proc')):
    """Fail closed when any actual Core process is already present."""
    for directory in proc.iterdir():
        if not directory.name.isdigit():
            continue
        try:
            comm = (directory / 'comm').read_text().strip()
        except FileNotFoundError:
            continue  # A vanished process is not an existing Core instance.
        require(comm not in ('bitcoin-qt', 'bitcoind', 'bitcoin-cli'), 'core-already-present-before-reset-probe')


def read_only_reset(runtime, value, args, current_boot, no_core=no_core_process):
    wallets = validate_ready(value, args)
    require(BOOT.fullmatch(current_boot) and current_boot != '00000000-0000-0000-0000-000000000000'
            and current_boot != value['source_boot_id'], 'boot-id-did-not-change')
    same_runtime(runtime)
    no_core()
    require(runtime.wallet_files() == {} and runtime.read_receipts() == {}, 'old-wallet-inventory-or-receipts-survived')
    for path in fixed_absence(args.phase, args.case, args.nonce, wallets):
        absent(path)
    for directory in (runtime.WALLETS, runtime.ROOT / 'export', runtime.STATE / 'core-runtime'):
        require(not any(directory.iterdir()), 'private-core-directory-is-not-empty')
    return {'old_wallet_inventory_absent': True, 'old_receipts_absent': True,
            'all_scoped_old_paths_absent': True, 'private_core_directories_empty': True,
            'core_not_started': True, 'new_boot_id': True}


def source_exports(args, public, runtime, export, gpg, media):
    if args.mode == 'arm-existing':
        source, _ = read_json(media / (args.firmware + '-' + args.phase + '-result.json'))
        require(source.get('status') == 'passed-covered-checks' and source.get('phase') == args.phase and
                source.get('firmware') == args.firmware and source.get('execution_uid') == 1000 and
                source.get('target_serial') == 'CV_RAM_TEST_INTERNAL' and source.get('fixture_serial') == 'CV_RAM_TEST_USB' and
                source.get('helper_sha256', {}).get('ci-vm-guest-probe.py') == args.probe_sha256 and
                source.get('runtime_sha256') == public.REPORT['runtime_sha256'], 'existing-probe-is-not-matching-success')
        stopped = [check for check in source.get('checks', []) if isinstance(check, dict) and
                   check.get('check') == 'production-finish-verifies-both-formats-and-final-wallet-flush']
        require(len(stopped) == 1 and stopped[0].get('status') == 'PASS' and
                stopped[0].get('actual_core_shutdown') is True and
                stopped[0].get('final_power_request_intercepted') is True, 'existing-probe-core-stop-proof-is-missing')
        exports = source.get('exports')
    else:
        # Do not call user_workflow(), Finish, signing helpers or native UI.
        require(runtime.wallet_files() == {} and runtime.read_receipts() == {}, 'fresh-abrupt-session-is-not-empty')
        for path in (STATE / 'exports.json', STATE / 'exports.new'):
            absent(path)
        no_core_process()
        public.REPORT.update(firmware=args.firmware, phase=args.phase, exports=[], stage_progress=[])
        public.WORKFLOW_CLOCK = None
        public.start_core(runtime)
        for backup_format in ('7z', 'gpg'):
            public.format_workflow(runtime, export, gpg, media, backup_format, args.nonce)
        exports = public.REPORT['exports']
    require(isinstance(exports, list) and len(exports) == 2 and all(isinstance(item, dict) for item in exports)
            and {item.get('format') for item in exports} == {'7z', 'gpg'}, 'source-export-set-is-invalid')
    return exports


def arm_core_state(runtime, names, mode, no_core=no_core_process):
    """Observe existing state; never start, load, unload or stop to force it."""
    require(mode in ('arm-existing', 'arm-fresh'), 'invalid-arm-mode')
    try:
        loaded = runtime.rpc('listwallets')
    except RuntimeError:
        require(mode == 'arm-existing', 'fresh-abrupt-core-is-not-running')
        no_core()
        return 'closed'
    require(isinstance(loaded, list) and all(isinstance(name, str) for name in loaded), 'arm-loaded-state-is-invalid')
    actual = {runtime.loaded_wallet_name(name, loaded) for name in names}
    present = {name for name in actual if name is not None}
    require(set(loaded) == present and (not present or len(present) == len(names)),
            'arm-loaded-wallets-are-missing-partial-or-unrelated')
    require(mode != 'arm-fresh' or len(present) == len(names), 'fresh-abrupt-original-wallets-are-not-loaded')
    info = runtime.rpc('getnetworkinfo')
    require(info.get('networkactive') is False and info.get('connections') == 0 and
            runtime.rpc('getblockchaininfo').get('chain') == 'main', 'arm-core-is-not-offline-mainnet')
    return 'running-loaded' if present else 'running-unloaded'


def arm(args, public, runtime, export, gpg, media):
    selected = paths(args.phase, args.case, args.nonce)
    for path in (*selected['sentinels'], selected['recovered'],
                 media / (selected['stem'] + '-USBREADY.txt'), media / (selected['stem'] + '-ready.json')):
        absent(path)
    exports = source_exports(args, public, runtime, export, gpg, media)
    wallets = runtime.wallet_files()
    receipts = runtime.read_receipts()
    names = {item.get('wallet') for item in exports}
    require(len(names) == 2 and all(isinstance(name, str) and WALLET.fullmatch(name) for name in names)
            and set(wallets) == set(receipts) == names, 'arm-wallet-inventory-or-receipts-mismatch')
    core_state = arm_core_state(runtime, names, args.mode)
    archives = []
    for item in exports:
        name, fmt = item['wallet'], item['format']
        record = receipts[name]
        archive = checked_path(record['archive'])
        expected = media / (name + '-encrypted.' + fmt)
        require(archive == expected and export.receipt_format(record) == fmt and
                runtime.file_digest(archive) == record.get('archive_sha256') == item.get('archive_sha256'),
                'arm-export-or-receipt-does-not-match')
        archives.append({'format': fmt, 'name': archive.name, 'sha256': record['archive_sha256']})
    gpg_wallet = next(item['wallet'] for item in exports if item['format'] == 'gpg')
    record = receipts[gpg_wallet]
    require(gpg.decrypt_file(Path(record['archive']), selected['recovered'], public.EXPORT_PHRASES['gpg'],
                             ram_root=PRIVATE) == 'AES256-OCB', 'arm-recovered-gpg-profile-mismatch')
    require(runtime.file_digest(selected['recovered']) == record['wallet_backup_sha256'] and
            runtime.wallet_digest(selected['recovered']) == record['wallet_digest'], 'arm-recovered-snapshot-mismatch')
    require(runtime.wallet_files() == wallets and runtime.read_receipts() == receipts, 'arm-changed-original-wallets-or-receipts')
    # Metadata-only positive controls for the two known Core RAM logs; no log
    # content or hashes are exported. They must be absent in the next boot.
    for log in (STATE / 'core-runtime/core-vault-hide-sync.log', CORE / 'debug.log'):
        info = checked_path(log).lstat()
        require(stat.S_ISREG(info.st_mode) and info.st_uid == 1000 and info.st_nlink == 1 and
                runtime.mount_at(log)['maj:min'] == runtime.mount_at(ROOT, exact=True)['maj:min'],
                'arm-core-log-is-not-owned-private-ram')
    marker = ('CORE_VAULT_RESET_RAM_' + args.nonce + '\n').encode()
    for path in selected['sentinels']:
        require(runtime.mount_at(path.parent)['maj:min'] == runtime.mount_at(ROOT, exact=True)['maj:min'],
                'arm-sentinel-is-not-on-private-ram')
        fsync_public(path, marker)
        require(owned_bytes(path, 256)[0] == marker, 'arm-sentinel-readback-mismatch')
    control = ('CORE_VAULT_USBREADY_' + args.phase + '_' + args.case + '_' + args.nonce + '\n').encode()
    control_path = media / (selected['stem'] + '-USBREADY.txt')
    control_sha = fsync_public(control_path, control)
    require(owned_bytes(control_path, 256, control_sha)[0] == control, 'usb-control-readback-mismatch')
    value = {'schema': 1, 'status': 'USBREADY', 'case': args.case, 'nonce': args.nonce,
             'phase': args.phase, 'firmware': args.firmware, 'source_boot_id': boot_id(),
             'execution_uid': 1000, 'target_serial': 'CV_RAM_TEST_INTERNAL', 'fixture_serial': 'CV_RAM_TEST_USB',
             'helper_sha256': args.helper_sha256, 'guest_probe_sha256': args.probe_sha256,
             'runtime_sha256': public.REPORT['runtime_sha256'],
             'usb_control': {'name': control_path.name, 'sha256': control_sha, 'bytes': len(control)},
             'wallets': sorted(names), 'archives': sorted(archives, key=lambda item: item['format']),
             'core_state': core_state,
             'armed': {'wallet_inventory_present': True, 'receipts_present': True,
                       'recovered_snapshot_authenticated': True, 'sentinels_present': True,
                       'core_ram_logs_present': True, 'core_state_observed': True,
                       'finish_invoked_by_reset_helper': False},
             'scope': 'Public synthetic fixture arm only; reset, same-file continuity and stop/reap require controller evidence.'}
    validate_ready(value, args)
    payload = (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()
    sha = fsync_public(media / (selected['stem'] + '-ready.json'), payload)
    require(read_json(media / (selected['stem'] + '-ready.json'), sha)[0] == value, 'ready-readback-mismatch')
    print('VAULT_RESET_USBREADY=' + json.dumps({'case': args.case, 'nonce': args.nonce, 'ready_sha256': sha},
                                             separators=(',', ':')), flush=True)


def probe(args, public, runtime, media, mount):
    require(args.ready_sha256 is not None and HEX.fullmatch(args.ready_sha256), 'probe-needs-bound-ready-sha256')
    selected = paths(args.phase, args.case, args.nonce)
    value, sha = read_json(media / (selected['stem'] + '-ready.json'), args.ready_sha256)
    validate_ready(value, args)
    require(value['runtime_sha256'] == public.REPORT['runtime_sha256'], 'reboot-runtime-identity-changed')
    control = value['usb_control']
    data, _ = owned_bytes(media / control['name'], 256, control['sha256'])
    require(len(data) == control['bytes'], 'usb-control-size-changed')
    for item in value['archives']:
        archive = checked_path(media / item['name'])
        info = archive.lstat()
        require(stat.S_ISREG(info.st_mode) and info.st_uid == 1000 and info.st_nlink == 1 and
                0 < info.st_size <= 64 * 1024 * 1024, 'surviving-usb-archive-is-unsafe')
        owned_bytes(archive, 64 * 1024 * 1024, item['sha256'])
    current = boot_id()
    checks = read_only_reset(runtime, value, args, current)
    checks.update(usb_ready_control_survived=True, encrypted_usb_archives_unchanged=True,
                  production_runtime_unchanged=True, private_storage_policy_passed=True)
    result = {'schema': 1, 'status': 'passed-reset-observations', 'case': args.case, 'nonce': args.nonce,
              'phase': args.phase, 'firmware': args.firmware, 'execution_uid': 1000,
              'source_boot_id': value['source_boot_id'], 'current_boot_id': current,
              'ready_sha256': sha, 'helper_sha256': args.helper_sha256, 'guest_probe_sha256': args.probe_sha256,
              'runtime_sha256': public.REPORT['runtime_sha256'], 'fixture_mount': mount, 'checks': checks,
              'scope': 'Before Core/backup writes, prior synthetic RAM files and inventory are absent in a new guest boot. '
                       'USB controls and encrypted archives survive. Same disk/USB/OVMF, shutdown reason and fresh QEMU '
                       'require separate controller proof; no physical DRAM sanitization or forensic disk-scan claim.'}
    # The observation is complete before this first, public-only USB output.
    out_sha = fsync_public(media / (selected['stem'] + '-probe.json'),
                          (json.dumps(result, sort_keys=True, indent=2) + '\n').encode())
    print('VAULT_RESET_PROBE_PASS=' + json.dumps({'case': args.case, 'nonce': args.nonce,
                                                'probe_sha256': out_sha}, separators=(',', ':')), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--mode', choices=('arm-existing', 'arm-fresh', 'probe'))
    parser.add_argument('--phase', choices=('live', 'installed'))
    parser.add_argument('--firmware', choices=('bios', 'uefi'))
    parser.add_argument('--case', choices=('normal', 'abrupt'))
    parser.add_argument('--nonce')
    parser.add_argument('--helper-sha256')
    parser.add_argument('--probe-sha256')
    parser.add_argument('--ready-sha256')
    parser.add_argument('--media', type=Path)
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    require(all(getattr(args, key) is not None for key in
                ('mode', 'phase', 'firmware', 'case', 'nonce', 'helper_sha256', 'probe_sha256')), 'missing-reset-arguments')
    require((args.mode != 'arm-existing' or args.case == 'normal') and
            (args.mode != 'arm-fresh' or args.case == 'abrupt'), 'arm-mode-case-mismatch')
    paths(args.phase, args.case, args.nonce)
    os.umask(0o077)
    def deadline(signum, frame):
        raise ResetDeadline()
    signal.signal(signal.SIGALRM, deadline)
    signal.alarm(TIMEOUT)
    try:
        public = load_public_probe(args)
        runtime, export, gpg, media, mount = fixture_context(args, public)
        if args.mode == 'probe':
            probe(args, public, runtime, media, mount)
        else:
            arm(args, public, runtime, export, gpg, media)
        return 0
    finally:
        signal.alarm(0)


def self_test():
    """Source-only policy probes; never manufacture actual VM acceptance."""
    import copy
    from unittest.mock import Mock

    def example():
        args = SimpleNamespace(phase='live', firmware='uefi', case='normal', nonce='a' * 32,
                               helper_sha256='1' * 64, probe_sha256='2' * 64)
        selected = paths(args.phase, args.case, args.nonce)
        wallets = ['cv-forensic-ci-' + fmt + '-' + 'b' * 32 for fmt in ('7z', 'gpg')]
        control = ('CORE_VAULT_USBREADY_live_normal_' + args.nonce + '\n').encode()
        value = {'schema': 1, 'status': 'USBREADY', 'case': args.case, 'nonce': args.nonce,
                 'phase': args.phase, 'firmware': args.firmware,
                 'source_boot_id': '12345678-1234-4321-abcd-123456789abc', 'execution_uid': 1000,
                 'target_serial': 'CV_RAM_TEST_INTERNAL', 'fixture_serial': 'CV_RAM_TEST_USB',
                 'helper_sha256': args.helper_sha256, 'guest_probe_sha256': args.probe_sha256,
                 'runtime_sha256': {str(number): '3' * 64 for number in range(8)},
                 'usb_control': {'name': selected['stem'] + '-USBREADY.txt',
                                 'sha256': hashlib.sha256(control).hexdigest(), 'bytes': len(control)},
                 'wallets': wallets,
                 'archives': [{'format': fmt, 'name': wallets[index] + '-encrypted.' + fmt, 'sha256': '4' * 64}
                              for index, fmt in enumerate(('7z', 'gpg'))],
                 'core_state': 'closed',
                 'armed': {'wallet_inventory_present': True, 'receipts_present': True,
                           'recovered_snapshot_authenticated': True, 'sentinels_present': True,
                           'core_ram_logs_present': True, 'core_state_observed': True,
                           'finish_invoked_by_reset_helper': False}, 'scope': 'public-test'}
        return args, value

    class Tests(unittest.TestCase):
        def test_absence_accepts_only_enoent(self):
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'old'
                absent(path)
                for kind in ('file', 'directory', 'broken-link', 'fifo'):
                    if kind == 'file': path.write_bytes(b'public')
                    elif kind == 'directory': path.mkdir()
                    elif kind == 'broken-link': path.symlink_to('missing')
                    else: os.mkfifo(path)
                    with self.assertRaises(ResetFailure): absent(path)
                    if kind == 'directory': path.rmdir()
                    else: path.unlink()
                with patch.object(Path, 'lstat', side_effect=PermissionError):
                    with self.assertRaises(PermissionError): absent(path)

        def test_parent_link_or_error_is_not_absence(self):
            with tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                (base / 'link').symlink_to(base, target_is_directory=True)
                with self.assertRaises(ResetFailure): absent(base / 'link' / 'missing')
                with self.assertRaises(FileNotFoundError): absent(base / 'missing-parent' / 'missing')

        def test_public_file_nooverwrite_integrity_and_duplicate_keys(self):
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'ready.json'
                payload = b'{"public":true}\n'
                sha = fsync_public(path, payload)
                self.assertEqual(read_json(path, sha)[0], {'public': True})
                with self.assertRaises(FileExistsError): fsync_public(path, payload)
                with self.assertRaises(ResetFailure): read_json(path, '0' * 64)
                path.write_text('{"public":true,"public":false}')
                with self.assertRaises(ResetFailure): read_json(path)
                path.unlink(); path.symlink_to('missing')
                with self.assertRaises(ResetFailure): owned_bytes(path, MAX_JSON)

        def test_boot_nonce_and_private_scope(self):
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'boot'
                path.write_text('12345678-1234-4321-abcd-123456789abc\n')
                self.assertEqual(boot_id(path), '12345678-1234-4321-abcd-123456789abc')
                for value in ('same', '00000000-0000-0000-0000-000000000000', 'A' * 36):
                    path.write_text(value)
                    with self.assertRaises(ResetFailure): boot_id(path)
            for nonce in ('../escape', 'a' * 31, 'A' * 32):
                with self.assertRaises(ResetFailure): paths('live', 'normal', nonce)
            selected = fixed_absence('installed', 'abrupt', 'a' * 32, ['cv-forensic-ci-gpg-' + 'b' * 32])
            self.assertIn(PRIVATE / 'ci-gui-recovered-installed.dat', selected)
            self.assertIn(STATE / 'exports.new', selected)
            self.assertIn(STATE / 'core-runtime/core-vault-hide-sync.log', selected)
            self.assertTrue(all(path.is_relative_to(ROOT) or path.is_relative_to(HOME) for path in selected))

        def test_no_core_process(self):
            with tempfile.TemporaryDirectory() as directory:
                proc = Path(directory)
                (proc / '1').mkdir(); (proc / '1/comm').write_text('public-test\n')
                no_core_process(proc)
                for name in ('bitcoin-qt', 'bitcoind', 'bitcoin-cli'):
                    (proc / '1/comm').write_text(name)
                    with self.assertRaises(ResetFailure): no_core_process(proc)
                with patch.object(Path, 'read_text', side_effect=PermissionError):
                    with self.assertRaises(PermissionError): no_core_process(proc)

        def test_ready_identity_and_positive_source_schema(self):
            args, value = example()
            self.assertEqual(validate_ready(value, args), value['wallets'])
            mutations = [lambda v: v.update(case='abrupt'), lambda v: v.update(nonce='c' * 32),
                         lambda v: v.update(phase='installed'), lambda v: v.update(firmware='bios'),
                         lambda v: v.update(helper_sha256='5' * 64),
                         lambda v: v.update(guest_probe_sha256='5' * 64),
                         lambda v: v.update(execution_uid=True), lambda v: v.update(schema=True),
                         lambda v: v.update(source_boot_id='not-uuid'),
                         lambda v: v.update(target_serial='OTHER'), lambda v: v.update(fixture_serial='OTHER'),
                         lambda v: v['armed'].update(sentinels_present=False),
                         lambda v: v['armed'].update(sentinels_present=1),
                         lambda v: v['armed'].update(finish_invoked_by_reset_helper=True),
                         lambda v: v.update(core_state='unknown'),
                         lambda v: v['usb_control'].update(name='../escape'),
                         lambda v: v['usb_control'].update(sha256='5' * 64),
                         lambda v: v['archives'][0].update(name='../escape.7z'),
                         lambda v: v['archives'][0].update(format='gpg'),
                         lambda v: v['wallets'].append(v['wallets'][0]),
                         lambda v: v.update(extra='unexpected')]
            for mutation in mutations:
                changed = copy.deepcopy(value); mutation(changed)
                with self.assertRaises(ResetFailure): validate_ready(changed, args)

        def test_core_closed_boundary_and_fresh_loaded_requirement(self):
            args, value = example()
            names = set(value['wallets'])
            runtime = SimpleNamespace(rpc=Mock(side_effect=RuntimeError('private-native-output-not-logged')),
                                      loaded_wallet_name=lambda name, loaded: name if name in loaded else None)
            stopped = Mock()
            self.assertEqual(arm_core_state(runtime, names, 'arm-existing', stopped), 'closed')
            stopped.assert_called_once_with()
            self.assertEqual(runtime.rpc.call_args_list[0].args, ('listwallets',))
            with self.assertRaises(ResetFailure): arm_core_state(runtime, names, 'arm-fresh', stopped)
            with self.assertRaises(ResetFailure):
                arm_core_state(runtime, names, 'arm-existing', Mock(side_effect=ResetFailure('core-still-present')))
            def rpc(method):
                if method == 'listwallets': return list(names)
                if method == 'getnetworkinfo': return {'networkactive': False, 'connections': 0}
                if method == 'getblockchaininfo': return {'chain': 'main'}
                raise AssertionError('Unexpected mutation RPC')
            runtime.rpc = Mock(side_effect=rpc)
            self.assertEqual(arm_core_state(runtime, names, 'arm-fresh'), 'running-loaded')
            self.assertEqual({call.args[0] for call in runtime.rpc.call_args_list},
                             {'listwallets', 'getnetworkinfo', 'getblockchaininfo'})
            for loaded in (['unrelated-wallet'], [next(iter(names))], None, [True]):
                runtime.rpc = Mock(return_value=loaded)
                with self.assertRaises(ResetFailure): arm_core_state(runtime, names, 'arm-fresh')
            runtime.rpc = Mock(side_effect=lambda method: [] if method == 'listwallets' else rpc(method))
            self.assertEqual(arm_core_state(runtime, names, 'arm-existing'), 'running-unloaded')
            with self.assertRaises(ResetFailure): arm_core_state(runtime, names, 'arm-fresh')
            args.case = 'abrupt'
            value['case'] = 'abrupt'
            with self.assertRaises(ResetFailure): validate_ready(value, args)

        def test_readonly_gate_and_all_survival_mutations(self):
            args, value = example()
            runtime = SimpleNamespace(ROOT=ROOT, HOME=HOME, CORE=CORE, WALLETS=WALLETS, PRIVATE=PRIVATE,
                                      STATE=STATE, wallet_files=Mock(return_value={}), read_receipts=Mock(return_value={}))
            other_boot = '87654321-4321-1234-dcba-cba987654321'
            no_core = Mock()
            with patch(__name__ + '.absent') as missing, patch.object(Path, 'iterdir', return_value=iter(())):
                result = read_only_reset(runtime, value, args, other_boot, no_core)
                self.assertTrue(all(flag is True for flag in result.values()))
                no_core.assert_called_once_with()
                expected = fixed_absence(args.phase, args.case, args.nonce, value['wallets'])
                self.assertEqual([call.args[0] for call in missing.call_args_list], expected)
                self.assertNotIn('rpc', vars(runtime))  # No Core/backup/decrypt API is available to the gate.
            with self.assertRaises(ResetFailure): read_only_reset(runtime, value, args, value['source_boot_id'], no_core)
            for field in ('wallet_files', 'read_receipts'):
                getattr(runtime, field).return_value = {'survivor': 'synthetic'}
                with self.assertRaises(ResetFailure): read_only_reset(runtime, value, args, other_boot, no_core)
                getattr(runtime, field).return_value = {}
            for survived in fixed_absence(args.phase, args.case, args.nonce, value['wallets']):
                def fail_one(path):
                    if path == survived:
                        raise ResetFailure('old-private-path-survived')
                with patch(__name__ + '.absent', side_effect=fail_one):
                    with self.assertRaises(ResetFailure): read_only_reset(runtime, value, args, other_boot, no_core)
            with patch(__name__ + '.absent'), patch.object(Path, 'iterdir', return_value=iter([Path('survivor')])):
                with self.assertRaises(ResetFailure): read_only_reset(runtime, value, args, other_boot, no_core)
            runtime.CORE = Path('/unexpected')
            with self.assertRaises(ResetFailure): read_only_reset(runtime, value, args, other_boot, no_core)

        def test_helper_loader_executes_only_bound_bytes(self):
            with tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                helper, source = base / 'ci-vm-reset-probe.py', base / 'ci-vm-guest-probe.py'
                helper.write_bytes(b'public-helper')
                source.write_bytes(b'PUBLIC_VALUE = 42\n')
                args = SimpleNamespace(helper_sha256=hashlib.sha256(helper.read_bytes()).hexdigest(),
                                       probe_sha256=hashlib.sha256(source.read_bytes()).hexdigest())
                with patch(__name__ + '.__file__', str(helper)):
                    module = load_public_probe(args)
                    self.assertEqual(module.PUBLIC_VALUE, 42)
                    source.write_bytes(b'PUBLIC_VALUE = 99\n')
                    with self.assertRaises(ResetFailure): load_public_probe(args)

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(Tests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    try:
        exit_code = main()
    except (Exception, ResetDeadline, KeyboardInterrupt) as error:
        label = error.args[0] if isinstance(error, ResetFailure) else type(error).__name__
        print('VAULT_RESET_FAIL=' + json.dumps({'status': 'failed', 'failure': label}, separators=(',', ':')), flush=True)
        raise SystemExit(1)
    raise SystemExit(exit_code)
