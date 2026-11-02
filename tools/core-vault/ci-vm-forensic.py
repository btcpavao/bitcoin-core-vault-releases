#!/usr/bin/python3
"""Scan exact synthetic markers in a stopped, owned candidate VM's virtual disk.

An overall successful ci-vm-acceptance root or an explicitly completed phase
with genuine native Finish poweroff is required. Live phase scans must happen
before any installer stage exists. This
does not mount images, inspect host disks, scan USB, repair images or stop VMs.
It creates a separate exclusive raw copy and result inside that evidence root.
Absence covers only the supplied fixture nonces in current guest-visible disk
bytes, including deleted filesystem blocks still mapped there. It does not
cover discarded/unmapped QCOW clusters, snapshots, memory or physical hardware.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import selectors
import signal
import stat
import subprocess
import sys
import tempfile
import time
import uuid

VIRTUAL_SIZE = 24 * 1024**3
CHUNK_SIZE = 16 * 1024**2
JSON_LIMIT = 2 * 1024**2
TOTAL_SECONDS = 900
MAX_HITS = 256
HELPERS = {'ci-vm-guest-probe.py', 'ci-vm-psbt.py'}
GUI_HELPER = 'ci-vm-gui-actions.py'
MARKER = re.compile(r'CORE_VAULT_FORENSIC_TEST_[0-9a-f]{32}')
WALLET = re.compile(r'cv-forensic-ci-(?:7z|gpg)-[0-9a-f]{32}')
HEX = re.compile(r'[0-9a-f]{64}')
sys.dont_write_bytecode = True


class ForensicFailure(RuntimeError):
    """Fixed public labels, without native tool output or secret values."""


class ForensicInterrupted(BaseException):
    """Global bounds bypass ordinary error handlers and reach owned cleanup."""


def require(condition, label):
    if not condition:
        raise ForensicFailure(label)


def deadline_check(deadline):
    require(time.monotonic() < deadline, 'forensic-deadline-exceeded')


def plain(value):
    path = Path(os.path.abspath(value))
    require(',' not in str(path) and not any(ord(c) < 32 or ord(c) == 127 for c in str(path)), 'unsafe-evidence-path')
    for part in (path, *path.parents):
        require(not part.is_symlink(), 'symlinked-evidence-path')
    return path


def identity(info):
    return {'device': info.st_dev, 'inode': info.st_ino, 'bytes': info.st_size,
            'mtime_ns': info.st_mtime_ns, 'ctime_ns': info.st_ctime_ns,
            'uid': info.st_uid, 'mode': stat.S_IMODE(info.st_mode), 'links': info.st_nlink}


def regular(info, *, mode=None):
    require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and info.st_nlink == 1,
            'evidence-file-is-not-regular-single-link-own-uid')
    require(not stat.S_IMODE(info.st_mode) & 0o022, 'evidence-file-is-writable-by-others')
    if mode is not None:
        require(stat.S_IMODE(info.st_mode) == mode, 'evidence-file-mode-is-not-exact')


def same_file(path, descriptor, expected, *, mode=None):
    require(not path.is_symlink(), 'evidence-file-became-symlink')
    current = path.lstat()
    regular(current, mode=mode)
    opened = os.fstat(descriptor)
    regular(opened, mode=mode)
    require(identity(current) == expected and identity(opened) == expected, 'evidence-file-identity-changed')


def hash_fd(descriptor, deadline):
    digest = hashlib.sha256()
    offset = 0
    while True:
        deadline_check(deadline)
        block = os.pread(descriptor, CHUNK_SIZE, offset)
        if not block:
            return digest.hexdigest()
        digest.update(block)
        offset += len(block)


def read_json(path):
    path = plain(path)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        before = os.fstat(descriptor)
        regular(before)
        require(0 < before.st_size <= JSON_LIMIT, 'evidence-json-size-is-not-bounded')
        payload = os.pread(descriptor, JSON_LIMIT + 1, 0)
        require(len(payload) == before.st_size, 'evidence-json-length-changed')
        same_file(path, descriptor, identity(before))
        value = json.loads(payload)
        require(isinstance(value, dict), 'evidence-json-is-not-an-object')
        return value, {'file': str(path), 'sha256': hashlib.sha256(payload).hexdigest(),
                       'identity': identity(before)}
    finally:
        os.close(descriptor)


def helper_hashes(value):
    require(isinstance(value, dict) and set(value) == HELPERS and
            all(isinstance(digest, str) and HEX.fullmatch(digest) for digest in value.values()),
            'evidence-helper-hash-set-is-invalid')
    return value


def code_proof(path):
    path = plain(path)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        before = os.fstat(descriptor)
        regular(before)
        require(0 < before.st_size <= JSON_LIMIT, 'delivered-helper-size-is-not-bounded')
        payload = os.pread(descriptor, JSON_LIMIT + 1, 0)
        require(len(payload) == before.st_size, 'delivered-helper-length-changed')
        same_file(path, descriptor, identity(before))
        return {'file': str(path), 'sha256': hashlib.sha256(payload).hexdigest(),
                'identity': identity(before)}
    finally:
        os.close(descriptor)


def genuine_finish(stage, phase):
    require(stage.get('genuine_finish_shutdown') == 'passed' and
            stage.get('genuine_finish_dialogs_and_session_destruction') == 'passed' and
            stage.get('gui_status') == 'passed-covered-checks', 'phase-did-not-attest-genuine-finish')
    gui = stage.get('genuine_gui')
    require(isinstance(gui, dict) and gui.get('status') == 'passed-covered-checks' and
            gui.get('phase') == phase and gui.get('poweroff_observed') is True,
            'phase-gui-did-not-attest-native-poweroff')
    checks = gui.get('checks')
    require(isinstance(checks, list) and checks and checks == stage.get('gui_checks') and
            all(isinstance(check, dict) and check.get('status') == 'PASS' and
                check.get('phase') == phase and isinstance(check.get('check'), str) for check in checks),
            'native-gui-checks-are-not-complete-success')
    summary = [check for check in checks if check['check'] ==
               'native-finish-verifies-both-formats-and-prompts-final-confirmation']
    power = [check for check in checks if check['check'] == 'native-verified-finish-powers-off-owned-guest']
    require(len(summary) == len(power) == 1 and type(power[0].get('qemu_exit_code')) is int and
            power[0]['qemu_exit_code'] == 0 and power[0].get('controller_quit_used') is False,
            'native-finish-exit-or-controller-quit-proof-is-invalid')


def validate_evidence(root, disk, phase=None):
    top, top_proof = read_json(root / 'vm-result.json')
    require(type(top.get('schema')) is int and top['schema'] == 2 and
            (top.get('status') == 'passed-covered-checks' if phase is None else
             top.get('status') in ('running', 'passed-covered-checks')),
            'controller-evidence-is-not-complete-success')
    require(phase in (None, 'live', 'installed'), 'unsupported-forensic-phase')
    firmware = top.get('firmware')
    require(firmware in ('bios', 'uefi') and top.get('accelerator') in ('kvm', 'tcg'), 'controller-firmware-or-accelerator-is-invalid')
    require(isinstance(top.get('iso_sha256'), str) and HEX.fullmatch(top['iso_sha256']) and
            isinstance(top.get('harness_sha256'), str) and HEX.fullmatch(top['harness_sha256']), 'controller-source-hashes-are-invalid')
    hashes = helper_hashes(top.get('helper_sha256'))
    require(top.get('guest_probe_sha256') == hashes['ci-vm-guest-probe.py'], 'controller-probe-hash-does-not-match')
    gui_hash = top.get('gui_helper_sha256')
    require(isinstance(gui_hash, str) and HEX.fullmatch(gui_hash), 'controller-gui-helper-hash-is-invalid')
    require(top.get('kernel_debug_options_added') is False and top.get('guest_network_devices') is False,
            'controller-did-not-attest-normal-offline-boot')
    delivery = root / 'fixture-delivery'
    require(delivery.is_dir() and delivery.stat().st_uid == os.getuid() and
            stat.S_IMODE(delivery.stat().st_mode) == 0o700 and not delivery.is_symlink(), 'unsafe-helper-delivery-directory')
    manifest, manifest_proof = read_json(delivery / 'ci-helper-sha256.json')
    require(set(manifest) == {'schema', 'helpers'} and type(manifest['schema']) is int and
            manifest['schema'] == 1 and helper_hashes(manifest['helpers']) == hashes, 'helper-delivery-manifest-does-not-match')
    code = [code_proof(delivery / name) for name in sorted(HELPERS | {GUI_HELPER})]
    expected_code = dict(hashes, **{GUI_HELPER: gui_hash})
    require(all(record['sha256'] == expected_code[Path(record['file']).name] for record in code),
            'delivered-helper-bytes-do-not-match-controller')
    stages = top.get('stages')
    require(isinstance(stages, dict) and set(stages) in ({'live'}, {'live', 'installer', 'installed'}), 'controller-phase-set-is-incomplete')
    if phase == 'live':
        require(set(stages) == {'live'} and not (root / 'installer').exists() and
                not (root / 'installed').exists(), 'live-scan-is-not-before-installation')
    elif phase == 'installed':
        require(set(stages) == {'live', 'installer', 'installed'}, 'installed-phase-is-not-complete')
    selected = [name for name in ('live', 'installed') if name in stages and (phase is None or name == phase)]
    proofs, qemu_records, needles = [top_proof, manifest_proof], [], {}
    for name in ('live', 'installer', 'installed'):
        if name not in stages:
            continue
        directory = plain(root / name)
        require(directory.is_dir() and directory.stat().st_uid == os.getuid() and
                stat.S_IMODE(directory.stat().st_mode) == 0o700, 'unsafe-phase-evidence-directory')
        stage, stage_proof = read_json(directory / 'phase-result.json')
        require(stage == stages[name] and stage.get('status') == 'passed-covered-checks' and
                stage.get('evidence_directory') == name and stage.get('iso_sha256_after_vm') == top['iso_sha256'],
                'phase-evidence-does-not-match-controller')
        proofs.append(stage_proof)
        qemu = stage.get('qemu')
        require(isinstance(qemu, dict) and type(qemu.get('pid')) is int and qemu['pid'] > 1 and
                isinstance(qemu.get('start_ticks'), str) and re.fullmatch(r'[0-9]{1,24}', qemu['start_ticks']) and
                isinstance(qemu.get('argv'), list) and 1 <= len(qemu['argv']) <= 160 and
                all(isinstance(arg, str) and len(arg) <= 8192 and '\0' not in arg for arg in qemu['argv']), 'invalid-owned-qemu-evidence')
        arguments = qemu['argv']
        require(Path(arguments[0]).name == 'qemu-system-x86_64' and arguments.count('-nic') == 1 and
                arguments.index('-nic') + 1 < len(arguments) and arguments[arguments.index('-nic') + 1] == 'none' and
                arguments.count('file=' + str(disk) + ',if=none,id=target,format=qcow2') == 1 and
                arguments.count('file=' + str(root / 'fixture.raw') + ',if=none,id=fixture,format=raw') == 1 and
                arguments.count('virtio-blk-pci,drive=target,serial=CV_RAM_TEST_INTERNAL') == 1 and
                arguments.count('usb-storage,bus=usb.0,drive=fixture,removable=on,serial=CV_RAM_TEST_USB') == 1,
                'qemu-evidence-is-not-the-owned-file-backed-fixture')
        qemu_records.append({'phase': name, 'pid': qemu['pid'], 'start_ticks': qemu['start_ticks']})
        if name == 'installer':
            require(stage.get('genuine_installer_restart') == 'passed', 'installer-did-not-attest-restart')
            continue
        genuine_finish(stage, name)
        guest, guest_proof = read_json(directory / f'{firmware}-{name}-result.json')
        proofs.append(guest_proof)
        require(guest == stage.get('guest_probe') and type(guest.get('schema')) is int and guest['schema'] == 1 and
                guest.get('status') == 'passed-covered-checks' and guest.get('phase') == name and
                guest.get('firmware') == firmware and type(guest.get('execution_uid')) is int and guest['execution_uid'] == 1000 and
                guest.get('target_serial') == 'CV_RAM_TEST_INTERNAL' and guest.get('fixture_serial') == 'CV_RAM_TEST_USB' and
                guest.get('helper_sha256') == hashes and isinstance(guest.get('covered'), list) and guest['covered'],
                'guest-evidence-is-not-validated-production-probe')
        checks = guest.get('checks')
        require(isinstance(checks, list) and checks and all(isinstance(check, dict) and
                check.get('status') == 'PASS' and isinstance(check.get('check'), str) for check in checks) and
                guest['covered'] == [check['check'] for check in checks], 'guest-covered-checks-do-not-match-successes')
        signing = guest.get('psbt_signing')
        require(isinstance(signing, dict) and signing.get('status') == 'passed' and
                isinstance(signing.get('proofs'), list) and len(signing['proofs']) == 2 and
                all(isinstance(item, dict) for item in signing['proofs']) and
                {item.get('backup_format') for item in signing['proofs']} == {'7z', 'gpg'} and
                all(item.get('chain') == 'main' and item.get('fresh_recovery_signed') is True and
                    item.get('blockchain_funding_proven') is False and item.get('broadcast') is False
                    for item in signing['proofs']), 'guest-signing-evidence-is-incomplete')
        exports = guest.get('exports')
        require(isinstance(exports, list) and len(exports) == 2 and
                all(isinstance(record, dict) for record in exports) and
                {record.get('format') for record in exports} == {'7z', 'gpg'}, 'guest-export-evidence-is-incomplete')
        for record in exports:
            marker, wallet = record.get('marker'), record.get('wallet')
            require(isinstance(marker, str) and MARKER.fullmatch(marker) and
                    isinstance(wallet, str) and WALLET.fullmatch(wallet) and
                    wallet.startswith('cv-forensic-ci-' + record['format'] + '-'), 'guest-marker-or-wallet-nonce-is-invalid')
            require(all(isinstance(record.get(key), str) and HEX.fullmatch(record[key])
                        for key in ('archive_sha256', 'wallet_backup_sha256', 'wallet_digest')), 'guest-export-hashes-are-invalid')
            if name not in selected:
                continue
            for field, nonce in (('marker', marker), ('wallet', wallet)):
                needles.setdefault(nonce, []).append({'phase': name, 'format': record['format'], 'field': field,
                                                      'guest_json_sha256': guest_proof['sha256']})
    require(len(needles) == 4 * len(selected), 'exact-marker-set-is-incomplete-or-reused')
    return {'firmware': firmware, 'iso_sha256': top['iso_sha256'], 'harness_sha256': top['harness_sha256'],
            'helper_sha256': hashes, 'gui_helper_sha256': gui_hash, 'source_json': proofs, 'source_code': code,
            'scanned_phases': selected, 'live_before_installation': phase == 'live',
            'controller_snapshot': top, 'owned_qemu': qemu_records,
            'markers': [{'value': value, 'origins': origins} for value, origins in sorted(needles.items())]}


def proc_birth(directory):
    payload = (directory / 'stat').read_text()
    require(len(payload) <= 8192, 'oversized-process-metadata')
    return payload.rsplit(') ', 1)[1].split()[19]


def stopped_qemu(proof, disk, proc_root=Path('/proc')):
    """Inspect recorded PIDs and own-UID QEMU only; never other users' argv."""
    for record in proof['owned_qemu']:
        directory = proc_root / str(record['pid'])
        try:
            if directory.stat().st_uid == os.getuid():
                require(proc_birth(directory) != record['start_ticks'], 'recorded-qemu-has-not-been-reaped')
        except FileNotFoundError:
            pass
    needle = os.fsencode(disk)
    for directory in proc_root.iterdir():
        if not directory.name.isdigit():
            continue
        try:
            if directory.stat().st_uid != os.getuid():
                continue
            comm = (directory / 'comm').read_text()
            if not comm.startswith('qemu-system'):
                continue
            with (directory / 'cmdline').open('rb') as stream:
                arguments = stream.read(256 * 1024 + 1)
            require(len(arguments) <= 256 * 1024, 'own-qemu-argv-is-oversized')
            require(needle not in arguments, 'owned-test-image-is-still-used-by-qemu')
        except FileNotFoundError:
            continue


def validate_header(payload):
    require(len(payload) >= 72 and payload[:4] == b'QFI\xfb', 'invalid-qcow-header')
    number = lambda start, end: int.from_bytes(payload[start:end], 'big')
    version, cluster_bits = number(4, 8), number(20, 24)
    require(version in (2, 3) and 9 <= cluster_bits <= 21, 'unsupported-qcow-header-version-or-cluster')
    require(number(8, 16) == number(16, 20) == 0, 'qcow-header-has-backing-reference')
    require(number(24, 32) == VIRTUAL_SIZE and number(32, 36) == 0, 'qcow-header-size-or-encryption-is-invalid')
    require(number(60, 64) == 0, 'qcow-header-has-internal-snapshots')
    if version == 3:
        require(len(payload) >= 104, 'truncated-qcow-v3-header')
        # Default standalone fixture needs none of these features. In
        # particular dirty=0x1, corrupt=0x2 and external-data=0x4 are rejected
        # before qemu-img can follow a header-supplied external reference.
        require(number(72, 80) == 0, 'qcow-header-has-incompatible-dirty-corrupt-or-external-feature')
        length = number(100, 104)
        require(104 <= length <= 1 << cluster_bits and length % 8 == 0, 'invalid-qcow-v3-header-length')
    return {'version': version, 'cluster_bits': cluster_bits, 'virtual_bytes': VIRTUAL_SIZE,
            'backing_reference': False, 'external_data_feature': False, 'internal_snapshots': False, 'encrypted': False}


def validate_image_info(chain, source_label):
    require(isinstance(chain, list) and len(chain) == 1 and isinstance(chain[0], dict), 'image-is-not-a-single-standalone-chain')
    info = chain[0]
    require(info.get('filename') == source_label and info.get('format') == 'qcow2' and
            type(info.get('virtual-size')) is int and info['virtual-size'] == VIRTUAL_SIZE, 'image-format-path-or-virtual-size-mismatch')
    require(not any(key in info for key in ('backing-filename', 'full-backing-filename', 'backing-filename-format', 'backing-image')),
            'image-info-has-backing-reference')
    require(info.get('snapshots', []) == [], 'image-info-has-snapshots')
    for key in ('encrypted', 'dirty-flag'):
        require(key not in info or info[key] is False, 'image-info-is-encrypted-or-dirty')
    specific = info.get('format-specific')
    require(isinstance(specific, dict) and specific.get('type') == 'qcow2' and
            isinstance(specific.get('data'), dict), 'qcow-format-specific-metadata-missing')
    data = specific['data']
    require('data-file' not in data and 'encrypt' not in data, 'qcow-info-has-external-data-or-encryption')
    for key in ('corrupt', 'data-file-raw'):
        require(key not in data or data[key] is False, 'qcow-info-is-corrupt-or-external-raw')
    return info


def run_tool(arguments, *, pass_fds, timeout, failure_label):
    process = subprocess.Popen(arguments, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, start_new_session=True, pass_fds=pass_fds,
                               env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8'})
    output = bytearray()
    until = time.monotonic() + timeout
    selector = selectors.DefaultSelector()
    try:
        os.set_blocking(process.stdout.fileno(), False)
        selector.register(process.stdout, selectors.EVENT_READ)
        while True:
            require(time.monotonic() < until, failure_label)
            if not selector.select(min(.2, max(.01, until - time.monotonic()))):
                continue
            block = os.read(process.stdout.fileno(), 65536)
            if not block:
                break
            output.extend(block)
            require(len(output) <= JSON_LIMIT, failure_label)
        process.wait(timeout=max(.01, until - time.monotonic()))
        require(process.returncode == 0, failure_label)
        return bytes(output)
    except BaseException:
        # The unreaped owned leader reserves its PID/PGID. Never signal a
        # process group after Popen has reaped that leader.
        if process.returncode is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        process.wait(timeout=15)
        raise
    finally:
        selector.close()
        process.stdout.close()


def reserve_raw(path, size=VIRTUAL_SIZE):
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        os.ftruncate(descriptor, size)
        regular(os.fstat(descriptor), mode=0o600)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def scan_stream(stream, needles, deadline, *, chunk_size=CHUNK_SIZE, hit_limit=MAX_HITS):
    require(needles and all(isinstance(needle, bytes) and needle for needle in needles), 'invalid-scan-needles')
    keep = max(map(len, needles)) - 1
    digest, total, overlap, hits, count = hashlib.sha256(), 0, b'', [], 0
    while True:
        deadline_check(deadline)
        block = stream.read(chunk_size)
        if not block:
            break
        digest.update(block)
        combined = overlap + block
        for needle in needles:
            first = 0
            while True:
                index = combined.find(needle, first)
                if index < 0:
                    break
                offset = total - len(overlap) + index
                # Shorter needles wholly within the carry were already
                # counted. Cross-boundary and self-overlapping hits remain.
                if offset + len(needle) > total:
                    count += 1
                    if len(hits) < hit_limit:
                        hits.append({'marker': needle.decode('ascii'), 'offset': offset})
                first = index + 1
        total += len(block)
        overlap = combined[-keep:] if keep else b''
    return {'scanned_bytes': total, 'raw_sha256': digest.hexdigest(), 'hit_count': count,
            'hits': hits, 'hits_truncated': count > len(hits)}


def write_new_json(path, value):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write((json.dumps(value, indent=2) + '\n').encode())
        stream.flush()
        os.fsync(stream.fileno())


def seal_boundary(path, value):
    write_new_json(path, value)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        regular(os.fstat(descriptor), mode=0o600)
        os.fchmod(descriptor, 0o400)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return read_json(path)[1]


def recheck_json(proof):
    for original in proof['source_json']:
        _, current = read_json(Path(original['file']))
        require(current == original, 'source-json-evidence-changed-during-scan')
    for original in proof.get('source_code', []):
        require(code_proof(Path(original['file'])) == original, 'delivered-helper-evidence-changed-during-scan')


def forensic(root, phase=None):
    require(os.getuid() == os.geteuid() and os.getuid() != 0, 'run-forensics-as-the-ordinary-test-account')
    require(int(Path('/proc/self/stat').read_text().split('(', 1)[0]) == os.getpid(), 'proc-is-not-the-current-pid-namespace')
    root = plain(root)
    info = root.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid() and
            stat.S_IMODE(info.st_mode) == 0o700, 'evidence-root-is-not-private-owned-directory')
    disk = plain(root / 'target.qcow2')
    descriptor = os.open(disk, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    raw_descriptor = None
    output = None
    result = {'schema': 1, 'status': 'running', 'scope': 'Exact synthetic nonce markers in current guest-visible '
              'internal virtual disk bytes only; includes deleted filesystem blocks still mapped. Excludes USB, '
              'discarded/unmapped QCOW clusters, image metadata, snapshots, memory sanitization and physical hardware.',
              'requested_phase': phase or 'overall'}
    deadline = time.monotonic() + TOTAL_SECONDS
    def interrupted(signum, frame):
        raise ForensicInterrupted('forensic-interrupted-or-deadline')
    previous = {sig: signal.signal(sig, interrupted) for sig in (signal.SIGALRM, signal.SIGTERM)}
    signal.alarm(TOTAL_SECONDS)
    try:
        source_info = os.fstat(descriptor)
        regular(source_info, mode=0o600)
        require(0 < source_info.st_size <= VIRTUAL_SIZE + 1024**3, 'qcow-container-size-is-not-bounded')
        source_identity = identity(source_info)
        same_file(disk, descriptor, source_identity, mode=0o600)
        header = validate_header(os.pread(descriptor, 104, 0))
        proof = validate_evidence(root, disk, phase)
        stopped_qemu(proof, disk)
        source_sha256 = hash_fd(descriptor, deadline)
        same_file(disk, descriptor, source_identity, mode=0o600)
        executable = Path('/usr/bin/qemu-img')
        require(executable.is_file() and not executable.is_symlink() and executable.stat().st_uid == 0 and
                not stat.S_IMODE(executable.stat().st_mode) & 0o022 and os.access(executable, os.X_OK), 'trusted-qemu-img-is-not-available')
        source_label = f'/proc/self/fd/{descriptor}'
        image_info = validate_image_info(json.loads(run_tool([str(executable), 'info', '-f', 'qcow2',
            '--output=json', '--backing-chain', source_label], pass_fds=(descriptor,), timeout=30,
            failure_label='qemu-image-info-failed')), source_label)
        same_file(disk, descriptor, source_identity, mode=0o600)
        stopped_qemu(proof, disk)
        output = root / ('forensic-' + uuid.uuid4().hex)
        output.mkdir(mode=0o700)
        output.chmod(0o700)
        # A phase boundary is exclusive and remains independent of the mutable
        # controller report when subsequent installer/reboot stages are added.
        boundary = output / 'phase-boundary.json'
        boundary_proof = seal_boundary(boundary, {'schema': 1, 'status': 'validated-genuine-finish-boundary',
            'requested_phase': phase or 'overall', 'evidence': proof,
            'disk_identity': source_identity, 'disk_sha256': source_sha256,
            'disk_header': header, 'disk_qemu_info': image_info})
        proof['source_json'].append(boundary_proof)
        raw = output / 'internal-virtual-disk.raw'
        raw_descriptor = reserve_raw(raw)
        raw_before = identity(os.fstat(raw_descriptor))
        result.update(evidence=proof, source_disk={'file': str(disk), 'identity': source_identity,
                      'sha256_before': source_sha256, 'header': header, 'qemu_info': image_info},
                      immutable_boundary=boundary_proof, output_directory=str(output), raw_file=str(raw))
        run_tool([str(executable), 'convert', '-n', '-f', 'qcow2', '-O', 'raw', '-S', '4k',
                  source_label, f'/proc/self/fd/{raw_descriptor}'], pass_fds=(descriptor, raw_descriptor),
                 timeout=min(300, max(1, deadline - time.monotonic())), failure_label='qemu-image-conversion-failed')
        same_file(disk, descriptor, source_identity, mode=0o600)
        raw_info = os.fstat(raw_descriptor)
        regular(raw_info, mode=0o600)
        require((raw_info.st_dev, raw_info.st_ino, raw_info.st_size) ==
                (raw_before['device'], raw_before['inode'], VIRTUAL_SIZE), 'raw-output-inode-or-size-changed')
        raw_identity = identity(raw_info)
        same_file(raw, raw_descriptor, raw_identity, mode=0o600)
        os.lseek(raw_descriptor, 0, os.SEEK_SET)
        with os.fdopen(os.dup(raw_descriptor), 'rb') as stream:
            scan = scan_stream(stream, [entry['value'].encode('ascii') for entry in proof['markers']], deadline)
        require(scan['scanned_bytes'] == VIRTUAL_SIZE, 'complete-virtual-disk-was-not-scanned')
        same_file(raw, raw_descriptor, raw_identity, mode=0o600)
        same_file(disk, descriptor, source_identity, mode=0o600)
        source_after = hash_fd(descriptor, deadline)
        same_file(disk, descriptor, source_identity, mode=0o600)
        require(source_after == source_sha256, 'source-qcow-bytes-changed-during-scan')
        stopped_qemu(proof, disk)
        recheck_json(proof)
        result.update(scan, raw_identity=raw_identity, source_qcow_sha256_after=source_after,
                      all_owned_qemu_reaped=True, no_active_own_qemu_referencing_image=True,
                      source_json_unchanged=True, source_and_raw_identities_unchanged=True,
                      status='FAIL_EXACT_MARKER_FOUND' if scan['hit_count'] else 'PASS_NO_EXACT_SUPPLIED_MARKERS')
        write_new_json(output / 'scan-result.json', result)
        print(json.dumps({'status': result['status'], 'result': str(output / 'scan-result.json'),
                          'scanned_bytes': scan['scanned_bytes'], 'hit_count': scan['hit_count'], 'scope': result['scope']}), flush=True)
        return 1 if scan['hit_count'] else 0
    except BaseException as error:
        result.update(status='FAIL', failure=error.args[0] if isinstance(error, (ForensicFailure, ForensicInterrupted)) else type(error).__name__)
        if output is not None:
            write_new_json(output / 'scan-result.json', result)
        print(json.dumps({'status': 'FAIL', 'failure': result['failure'], 'output_directory': str(output) if output else None}), flush=True)
        return 1
    finally:
        signal.alarm(0)
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        if raw_descriptor is not None:
            os.close(raw_descriptor)
        os.close(descriptor)


def self_test():
    """Synthetic bytes and fresh temporary files only; never invoke QEMU."""
    import unittest
    from unittest.mock import patch
    class Tests(unittest.TestCase):
        def save_metadata(self, root, top):
            (root / 'vm-result.json').write_text(json.dumps(top))
            (root / 'vm-result.json').chmod(0o600)
            for name, stage in top['stages'].items():
                directory = root / name
                directory.mkdir(mode=0o700, exist_ok=True)
                directory.chmod(0o700)
                (directory / 'phase-result.json').write_text(json.dumps(stage))
                (directory / 'phase-result.json').chmod(0o600)
                if name != 'installer':
                    path = directory / ('bios-' + name + '-result.json')
                    path.write_text(json.dumps(stage['guest_probe']))
                    path.chmod(0o600)

        def metadata(self, root, *, installed=False):
            root.chmod(0o700)
            delivery = root / 'fixture-delivery'; delivery.mkdir(mode=0o700)
            hashes = {}
            for name in sorted(HELPERS | {GUI_HELPER}):
                path = delivery / name
                path.write_bytes(('Public synthetic module fixture: ' + name).encode())
                path.chmod(0o600)
                hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
            helpers = {name: hashes[name] for name in HELPERS}
            write_new_json(delivery / 'ci-helper-sha256.json', {'schema': 1, 'helpers': helpers})
            top = {'schema': 2, 'status': 'running', 'firmware': 'bios', 'accelerator': 'tcg',
                   'iso_sha256': '1' * 64, 'harness_sha256': '2' * 64, 'helper_sha256': helpers,
                   'guest_probe_sha256': helpers['ci-vm-guest-probe.py'], 'gui_helper_sha256': hashes[GUI_HELPER],
                   'kernel_debug_options_added': False, 'guest_network_devices': False, 'stages': {}}
            names = ('live', 'installer', 'installed') if installed else ('live',)
            for number, name in enumerate(names, 1):
                stage = {'status': 'passed-covered-checks', 'evidence_directory': name,
                         'iso_sha256_after_vm': top['iso_sha256'],
                         'qemu': {'pid': 100000 + number, 'start_ticks': '123', 'argv': [
                             '/usr/bin/qemu-system-x86_64', '-nic', 'none',
                             'file=' + str(root / 'target.qcow2') + ',if=none,id=target,format=qcow2',
                             'file=' + str(root / 'fixture.raw') + ',if=none,id=fixture,format=raw',
                             'virtio-blk-pci,drive=target,serial=CV_RAM_TEST_INTERNAL',
                             'usb-storage,bus=usb.0,drive=fixture,removable=on,serial=CV_RAM_TEST_USB']}}
                if name == 'installer':
                    stage['genuine_installer_restart'] = 'passed'
                else:
                    checks = [{'check': 'native-finish-verifies-both-formats-and-prompts-final-confirmation',
                               'status': 'PASS', 'phase': name},
                              {'check': 'native-verified-finish-powers-off-owned-guest', 'status': 'PASS',
                               'phase': name, 'qemu_exit_code': 0, 'controller_quit_used': False}]
                    stage.update(genuine_finish_shutdown='passed',
                                 genuine_finish_dialogs_and_session_destruction='passed',
                                 gui_status='passed-covered-checks', gui_checks=checks,
                                 genuine_gui={'status': 'passed-covered-checks', 'phase': name,
                                              'poweroff_observed': True, 'checks': checks})
                    guest_checks = [{'status': 'PASS', 'check': 'synthetic-metadata-probe'}]
                    guest = {'schema': 1, 'status': 'passed-covered-checks', 'phase': name,
                             'firmware': 'bios', 'execution_uid': 1000, 'target_serial': 'CV_RAM_TEST_INTERNAL',
                             'fixture_serial': 'CV_RAM_TEST_USB', 'helper_sha256': helpers,
                             'covered': ['synthetic-metadata-probe'], 'checks': guest_checks,
                             'psbt_signing': {'status': 'passed', 'proofs': [
                                 {'backup_format': fmt, 'chain': 'main', 'fresh_recovery_signed': True,
                                  'blockchain_funding_proven': False, 'broadcast': False} for fmt in ('7z', 'gpg')]},
                             'exports': []}
                    for index, fmt in enumerate(('7z', 'gpg')):
                        nonce = format(number * 2 + index, '032x')
                        guest['exports'].append({'format': fmt,
                            'marker': 'CORE_VAULT_FORENSIC_TEST_' + nonce,
                            'wallet': 'cv-forensic-ci-' + fmt + '-' + nonce,
                            'archive_sha256': '3' * 64, 'wallet_backup_sha256': '4' * 64,
                            'wallet_digest': '5' * 64})
                    stage['guest_probe'] = guest
                top['stages'][name] = stage
            self.save_metadata(root, top)
            return top

        def test_live_phase_can_precede_overall_success_but_not_installation(self):
            with tempfile.TemporaryDirectory(prefix='cv-forensic-unit-') as directory:
                root = Path(directory); top = self.metadata(root)
                proof = validate_evidence(root, root / 'target.qcow2', 'live')
                self.assertEqual(proof['scanned_phases'], ['live'])
                self.assertTrue(proof['live_before_installation'])
                self.assertEqual(len(proof['markers']), 4)
                with self.assertRaisesRegex(ForensicFailure, 'controller-evidence-is-not-complete-success'):
                    validate_evidence(root, root / 'target.qcow2')
                (root / 'installer').mkdir(mode=0o700)
                with self.assertRaisesRegex(ForensicFailure, 'live-scan-is-not-before-installation'):
                    validate_evidence(root, root / 'target.qcow2', 'live')

        def test_installed_phase_selects_only_its_nonces_and_overall_selects_both(self):
            with tempfile.TemporaryDirectory(prefix='cv-forensic-unit-') as directory:
                root = Path(directory); top = self.metadata(root, installed=True)
                proof = validate_evidence(root, root / 'target.qcow2', 'installed')
                self.assertEqual(proof['scanned_phases'], ['installed'])
                self.assertEqual(len(proof['markers']), 4)
                self.assertTrue(all(origin['phase'] == 'installed' for item in proof['markers'] for origin in item['origins']))
                top['status'] = 'passed-covered-checks'; self.save_metadata(root, top)
                self.assertEqual(len(validate_evidence(root, root / 'target.qcow2')['markers']), 8)
                with self.assertRaisesRegex(ForensicFailure, 'live-scan-is-not-before-installation'):
                    validate_evidence(root, root / 'target.qcow2', 'live')

        def test_mocked_only_finish_controller_quit_and_nonzero_exit_rejected(self):
            with tempfile.TemporaryDirectory(prefix='cv-forensic-unit-') as directory:
                root = Path(directory); top = self.metadata(root)
                original = json.loads(json.dumps(top))
                mutations = (
                    lambda s: s.pop('genuine_finish_shutdown'),
                    lambda s: s['genuine_gui'].update(poweroff_observed=False),
                    lambda s: s['gui_checks'][-1].update(controller_quit_used=True),
                    lambda s: s['gui_checks'][-1].update(qemu_exit_code=-9),
                    lambda s: s['gui_checks'][-1].update(qemu_exit_code=False),
                    lambda s: s['gui_checks'].append(dict(s['gui_checks'][-1])),
                    lambda s: s['genuine_gui'].update(phase='installed'),
                )
                for mutate in mutations:
                    top = json.loads(json.dumps(original))
                    # Preserve the actual returned/checklist relationship.
                    stage = top['stages']['live']; stage['genuine_gui']['checks'] = stage['gui_checks']
                    mutate(stage); self.save_metadata(root, top)
                    with self.assertRaises(ForensicFailure):
                        validate_evidence(root, root / 'target.qcow2', 'live')

        def test_all_modes_reject_mocked_only_success(self):
            with tempfile.TemporaryDirectory(prefix='cv-forensic-unit-') as directory:
                root = Path(directory); top = self.metadata(root)
                top['status'] = 'passed-covered-checks'
                top['stages']['live'].pop('genuine_gui'); self.save_metadata(root, top)
                for phase in (None, 'live'):
                    with self.assertRaisesRegex(ForensicFailure, 'phase-gui-did-not-attest-native-poweroff'):
                        validate_evidence(root, root / 'target.qcow2', phase)

        def test_failed_controller_guest_and_incomplete_installed_phase_rejected(self):
            with tempfile.TemporaryDirectory(prefix='cv-forensic-unit-') as directory:
                root = Path(directory); top = self.metadata(root)
                with self.assertRaisesRegex(ForensicFailure, 'installed-phase-is-not-complete'):
                    validate_evidence(root, root / 'target.qcow2', 'installed')
                top['status'] = 'failed'; self.save_metadata(root, top)
                with self.assertRaisesRegex(ForensicFailure, 'controller-evidence-is-not-complete-success'):
                    validate_evidence(root, root / 'target.qcow2', 'live')
                top['status'] = 'running'
                top['stages']['live']['guest_probe']['checks'][0]['status'] = 'FAIL'
                self.save_metadata(root, top)
                with self.assertRaisesRegex(ForensicFailure, 'guest-covered-checks-do-not-match-successes'):
                    validate_evidence(root, root / 'target.qcow2', 'live')

        def test_debug_boot_or_network_metadata_refused(self):
            with tempfile.TemporaryDirectory(prefix='cv-forensic-unit-') as directory:
                root = Path(directory); top = self.metadata(root)
                for field in ('kernel_debug_options_added', 'guest_network_devices'):
                    top[field] = True; self.save_metadata(root, top)
                    with self.assertRaisesRegex(ForensicFailure, 'controller-did-not-attest-normal-offline-boot'):
                        validate_evidence(root, root / 'target.qcow2', 'live')
                    top[field] = False

        def test_hash_bound_delivered_gui_and_rechecks_reject_changes(self):
            with tempfile.TemporaryDirectory(prefix='cv-forensic-unit-') as directory:
                root = Path(directory); self.metadata(root)
                proof = validate_evidence(root, root / 'target.qcow2', 'live')
                path = root / 'fixture-delivery' / GUI_HELPER
                path.write_bytes(b'changed public synthetic helper')
                with self.assertRaisesRegex(ForensicFailure, 'delivered-helper-bytes-do-not-match-controller'):
                    validate_evidence(root, root / 'target.qcow2', 'live')
                with self.assertRaisesRegex(ForensicFailure, 'delivered-helper-evidence-changed-during-scan'):
                    recheck_json(proof)

        def test_boundary_is_exclusive_readonly_and_detects_later_mutation(self):
            with tempfile.TemporaryDirectory(prefix='cv-forensic-unit-') as directory:
                path = Path(directory) / 'boundary.json'; value = {'status': 'original-public-boundary'}
                proof = seal_boundary(path, value)
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o400)
                value['status'] = 'changed-controller-memory'
                self.assertEqual(read_json(path)[0]['status'], 'original-public-boundary')
                with self.assertRaises(FileExistsError): seal_boundary(path, value)
                recheck_json({'source_json': [proof]})
                path.chmod(0o600); path.write_text(json.dumps(value))
                with self.assertRaisesRegex(ForensicFailure, 'source-json-evidence-changed-during-scan'):
                    recheck_json({'source_json': [proof]})

        def test_disk_inode_replacement_hardlink_and_symlink_rejected(self):
            with tempfile.TemporaryDirectory(prefix='cv-forensic-unit-') as directory:
                path = Path(directory) / 'target.qcow2'; path.write_bytes(b'public synthetic image'); path.chmod(0o600)
                descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
                try:
                    before = identity(os.fstat(descriptor))
                    other = Path(directory) / 'new.qcow2'; other.write_bytes(path.read_bytes()); other.chmod(0o600)
                    os.replace(other, path)
                    with self.assertRaises(ForensicFailure): same_file(path, descriptor, before, mode=0o600)
                finally: os.close(descriptor)
                link = Path(directory) / 'linked'; os.link(path, link)
                with self.assertRaises(ForensicFailure): regular(path.stat(), mode=0o600)
                symlink = Path(directory) / 'redirected'; symlink.symlink_to(path)
                with self.assertRaisesRegex(ForensicFailure, 'symlinked-evidence-path'): code_proof(symlink)

        def test_recorded_unreaped_pid_and_active_own_qemu_reference_rejected(self):
            with tempfile.TemporaryDirectory(prefix='cv-forensic-unit-') as directory:
                proc = Path(directory); process = proc / '100001'; process.mkdir()
                (process / 'stat').write_text('100001 (qemu-system) ' + ' '.join(['S'] + ['0'] * 18 + ['42']))
                (process / 'comm').write_text('qemu-system-x86\n')
                disk = proc / 'target.qcow2'
                (process / 'cmdline').write_bytes(b'/usr/bin/qemu-system-x86_64\0')
                proof = {'owned_qemu': [{'pid': 100001, 'start_ticks': '42'}]}
                with self.assertRaisesRegex(ForensicFailure, 'recorded-qemu-has-not-been-reaped'):
                    stopped_qemu(proof, disk, proc)
                proof['owned_qemu'][0]['start_ticks'] = '41'
                stopped_qemu(proof, disk, proc)  # A reused PID with different birth is not our child.
                (process / 'cmdline').write_bytes(b'/usr/bin/qemu-system-x86_64\0file=' + os.fsencode(disk) + b'\0')
                with self.assertRaisesRegex(ForensicFailure, 'owned-test-image-is-still-used-by-qemu'):
                    stopped_qemu(proof, disk, proc)

        def header(self):
            value = bytearray(104)
            value[:4] = b'QFI\xfb'
            value[4:8] = (3).to_bytes(4, 'big')
            value[20:24] = (16).to_bytes(4, 'big')
            value[24:32] = VIRTUAL_SIZE.to_bytes(8, 'big')
            value[100:104] = (104).to_bytes(4, 'big')
            return value

        def test_valid_header_and_negative_references(self):
            self.assertEqual(validate_header(self.header())['virtual_bytes'], VIRTUAL_SIZE)
            for first, last, value in ((8,16,1),(16,20,1),(32,36,1),(60,64,1),
                                       (72,80,1),(72,80,2),(72,80,4),(72,80,16),(100,104,103)):
                header = self.header(); header[first:last] = value.to_bytes(last-first, 'big')
                with self.assertRaises(ForensicFailure): validate_header(header)
            with self.assertRaises(ForensicFailure): validate_header(self.header()[:100])

        def test_nested_external_corrupt_and_snapshot_info_rejected(self):
            base = {'filename':'/proc/self/fd/3', 'format':'qcow2','virtual-size':VIRTUAL_SIZE,
                    'format-specific':{'type':'qcow2','data':{'compat':'1.1','corrupt':False,'data-file-raw':False}}}
            self.assertEqual(validate_image_info([base], '/proc/self/fd/3')['format'], 'qcow2')
            for field, value in (('data-file','outside.raw'),('corrupt',True),('encrypt',{})):
                info = json.loads(json.dumps(base)); info['format-specific']['data'][field] = value
                with self.assertRaises(ForensicFailure): validate_image_info([info], '/proc/self/fd/3')
            for field, value in (('backing-filename','outside.qcow2'),('encrypted',True),('dirty-flag',True),('snapshots',[{}])):
                info = json.loads(json.dumps(base)); info[field] = value
                with self.assertRaises(ForensicFailure): validate_image_info([info], '/proc/self/fd/3')
            with self.assertRaises(ForensicFailure): validate_image_info([base,base], '/proc/self/fd/3')

        def test_boundary_self_overlap_and_carry_are_counted_once(self):
            payload = b'xxxABCDE--ABABA---ABCDE'
            scan = scan_stream(io.BytesIO(payload), [b'ABCDE',b'ABA'], time.monotonic()+10, chunk_size=4)
            expected=[]
            for needle in (b'ABCDE',b'ABA'):
                start=0
                while (index:=payload.find(needle,start)) >= 0:
                    expected.append((needle.decode(),index)); start=index+1
            self.assertEqual(sorted((hit['marker'],hit['offset']) for hit in scan['hits']),sorted(expected))
            self.assertEqual(scan['hit_count'],len(expected))
            self.assertEqual(scan['scanned_bytes'],len(payload))
            self.assertEqual(scan['raw_sha256'],hashlib.sha256(payload).hexdigest())

        def test_hit_limit_keeps_full_scan_and_digest(self):
            payload=b'ABABA'*100
            scan=scan_stream(io.BytesIO(payload),[b'ABA'],time.monotonic()+10,chunk_size=3,hit_limit=2)
            self.assertTrue(scan['hits_truncated']); self.assertEqual(len(scan['hits']),2)
            self.assertEqual(scan['scanned_bytes'],len(payload))
            self.assertEqual(scan['raw_sha256'],hashlib.sha256(payload).hexdigest())

        def test_existing_raw_is_preserved_and_new_raw_is_exclusive(self):
            with tempfile.TemporaryDirectory(prefix='cv-forensic-unit-') as directory:
                path=Path(directory)/'synthetic.raw'; path.write_bytes(b'unchanged synthetic sentinel')
                with self.assertRaises(FileExistsError): reserve_raw(path,64)
                self.assertEqual(path.read_bytes(),b'unchanged synthetic sentinel')
                new=Path(directory)/'new.raw'; descriptor=reserve_raw(new,64)
                try:
                    self.assertEqual(os.fstat(descriptor).st_size,64)
                    self.assertEqual(stat.S_IMODE(os.fstat(descriptor).st_mode),0o600)
                finally: os.close(descriptor)

        def test_generic_prefixes_do_not_validate_as_unique_markers(self):
            self.assertIsNone(MARKER.fullmatch('CORE_VAULT_FORENSIC_TEST_'))
            self.assertIsNone(WALLET.fullmatch('cv-forensic-ci-gpg-'))
            self.assertIsNotNone(MARKER.fullmatch('CORE_VAULT_FORENSIC_TEST_'+'a'*32))

        def test_failed_or_coerced_controller_report_is_rejected_before_files(self):
            for report in ({'schema':2,'status':'failed'}, {'schema':True,'status':'passed-covered-checks'},
                           {'schema':2,'status':'running'}):
                with patch.dict(globals(), {'read_json':lambda path:(report,{})}):
                    with self.assertRaisesRegex(ForensicFailure, '^controller-evidence-is-not-complete-success$'):
                        validate_evidence(Path('/synthetic-evidence-root'),Path('/synthetic-evidence-root/target.qcow2'))

    suite=unittest.defaultTestLoader.loadTestsFromTestCase(Tests)
    return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    modes=parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--evidence-root',type=Path)
    modes.add_argument('--self-test',action='store_true')
    parser.add_argument('--phase', choices=('live', 'installed'),
                        help='Require genuine completed phase; Live must precede all installation stages.')
    args=parser.parse_args()
    if args.self_test and args.phase:
        parser.error('--phase requires --evidence-root')
    return self_test() if args.self_test else forensic(args.evidence_root, args.phase)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ForensicFailure,OSError,ValueError,KeyError,subprocess.SubprocessError) as error:
        print(json.dumps({'status':'FAIL_PREFLIGHT','failure':error.args[0] if isinstance(error,ForensicFailure)
                          else type(error).__name__}),flush=True)
        raise SystemExit(1)
