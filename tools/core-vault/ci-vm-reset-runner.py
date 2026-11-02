#!/usr/bin/python3
"""QA-only fixed-slot transport for the frozen disposable-VM reset probe.

Usage: python3 /media/vault/VAULT_CI/ci-vm-reset-runner.py live-normal-arm
Only the eight live/installed normal/abrupt arm/probe slots are accepted. The
host prepares and SHA-attests each bounded public request before a fresh VM;
probe requests are prepared only after the preceding owned VM is reaped.

This transport does not change the frozen probe, production files, VM state,
or the original two-helper manifest. It never receives a secret, arbitrary
path, shell command, Python source, or executable argument from a request.
Only a validated helper completion marker and short real-exit banner escape
the anonymous output buffer. Host stop/reap/continuity and actual reset
acceptance remain independent, mandatory evidence.
"""
from __future__ import annotations

from contextlib import ExitStack, redirect_stderr, redirect_stdout
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import stat
import sys
import uuid

sys.dont_write_bytecode = True
MEDIA = Path('/media/vault/VAULT_CI')
RUNNER = 'ci-vm-reset-runner.py'
HELPER = 'ci-vm-reset-probe.py'
PROBE = 'ci-vm-guest-probe.py'
HELPER_SHA = '74c230e62e502bf0483965892c3b67e9b78ebd81aff79f816dfbe5e3fccd437f'
PROBE_SHA = 'ae0e3a57a40b958c08af7d00863e45eca585e9adb3bf63b6be3837264e5b24c9'
HELPER_BYTES = 39006
PROBE_BYTES = 51565
GUEST_UID = 1000
MODES = {0o600, 0o644, 0o700, 0o755}
HEX = re.compile(r'[0-9a-f]{64}')
NONCE = re.compile(r'[0-9a-f]{32}')
BOOT = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')
JSON_LIMIT = 8192
CODE_LIMIT = 128 * 1024
OUTPUT_LIMIT = 128 * 1024
SLOTS = {phase + '-' + case + '-' + action: (phase, case, action)
         for phase in ('live', 'installed') for case in ('normal', 'abrupt') for action in ('arm', 'probe')}
ARM_KEYS = {'schema', 'slot', 'phase', 'firmware', 'case', 'nonce', 'helper_sha256', 'probe_sha256'}
ACK_KEYS = {'schema', 'slot', 'phase', 'firmware', 'case', 'nonce', 'request_sha256',
            'runner_sha256', 'helper_sha256', 'probe_sha256', 'status', 'helper_exit_code'}


class RunnerFailure(RuntimeError):
    """A fixed public enum; never native output, user text, or exception text."""


def require(condition, label):
    if not condition:
        raise RunnerFailure(label)


def identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def no_links(path):
    require(path.is_absolute(), 'non-absolute-fixed-path')
    for part in (path, *path.parents):
        info = part.lstat()
        require(not stat.S_ISLNK(info.st_mode) and (part == path or stat.S_ISDIR(info.st_mode)),
                'redirected-fixed-path')


def safe_file(info, limit):
    mode = stat.S_IMODE(info.st_mode)
    require(stat.S_ISREG(info.st_mode) and info.st_uid == info.st_gid == GUEST_UID and info.st_nlink == 1
            and mode in MODES and not mode & 0o022 and 0 < info.st_size <= limit, 'unsafe-public-file')


def public_bytes(path, limit, expected_sha=None, expected_size=None):
    """A stable no-follow owned FD; the returned buffer is the verified input."""
    no_links(path)
    before = path.lstat()
    safe_file(before, limit)
    require(expected_size is None or before.st_size == expected_size, 'pinned-code-size-mismatch')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    try:
        safe_file(os.fstat(fd), limit)
        require(identity(os.fstat(fd)) == identity(before), 'public-file-open-race')
        parts, total = [], 0
        while True:
            block = os.read(fd, min(65536, limit + 1 - total))
            if not block:
                break
            parts.append(block); total += len(block)
            require(total <= limit, 'public-file-too-large')
        payload = b''.join(parts)
        require(len(payload) == before.st_size and identity(os.fstat(fd)) == identity(before)
                and identity(path.lstat()) == identity(before), 'public-file-read-race')
    finally:
        os.close(fd)
    sha = hashlib.sha256(payload).hexdigest()
    require(expected_sha is None or sha == expected_sha, 'pinned-public-sha256-mismatch')
    return payload, sha


def unique_json(payload):
    def unique(pairs):
        output = {}
        for key, value in pairs:
            require(key not in output, 'duplicate-json-key')
            output[key] = value
        return output
    require(0 < len(payload) <= JSON_LIMIT, 'public-json-too-large')
    value = json.loads(payload, object_pairs_hook=unique)
    require(isinstance(value, dict), 'public-json-is-not-object')
    return value


def valid_boot(value):
    return isinstance(value, str) and BOOT.fullmatch(value) is not None and uuid.UUID(value).int != 0


def validate_request(value, slot):
    require(slot in SLOTS, 'invalid-slot')
    phase, case, action = SLOTS[slot]
    require(set(value) == ARM_KEYS | ({'ready_sha256'} if action == 'probe' else set()), 'invalid-request-key-set')
    require(type(value['schema']) is int and value['schema'] == 1 and value['slot'] == slot and
            value['phase'] == phase and value['case'] == case and value['firmware'] in ('bios', 'uefi'),
            'request-slot-identity-mismatch')
    require(isinstance(value['nonce'], str) and NONCE.fullmatch(value['nonce']) and
            uuid.UUID(hex=value['nonce']).int != 0, 'invalid-public-nonce')
    require(value['helper_sha256'] == HELPER_SHA and value['probe_sha256'] == PROBE_SHA, 'request-code-pins-mismatch')
    if action == 'probe':
        require(isinstance(value['ready_sha256'], str) and HEX.fullmatch(value['ready_sha256']), 'invalid-ready-sha256')
    return phase, case, action


def derived_argv(value):
    _, case, action = validate_request(value, value['slot'])
    mode = 'probe' if action == 'probe' else ('arm-existing' if case == 'normal' else 'arm-fresh')
    result = [str(MEDIA / HELPER), '--mode', mode, '--phase', value['phase'], '--firmware', value['firmware'],
              '--case', value['case'], '--nonce', value['nonce'], '--helper-sha256', HELPER_SHA, '--probe-sha256', PROBE_SHA]
    if action == 'probe':
        result += ['--ready-sha256', value['ready_sha256']]
    return result


def compiled_helper(payload):
    """Execute only the already verified buffer, with its fixed USB identity."""
    require(len(payload) == HELPER_BYTES and hashlib.sha256(payload).hexdigest() == HELPER_SHA, 'helper-buffer-not-pinned')
    name = 'core_vault_ci_reset_slot_helper'
    spec = importlib.util.spec_from_loader(name, loader=None, origin=str(MEDIA / HELPER))
    require(spec is not None, 'helper-module-unavailable')
    module = importlib.util.module_from_spec(spec)
    module.__file__ = str(MEDIA / HELPER)
    sys.modules[name] = module
    exec(compile(payload, str(MEDIA / HELPER), 'exec'), module.__dict__)
    require(callable(module.main), 'helper-main-unavailable')
    return module


class Discard(io.TextIOBase):
    def write(self, value):
        return len(value)

    def flush(self):
        pass


def invoke_helper(module, value):
    """Suppress Python/native diagnostics; retain bounded anonymous stdout only."""
    # Every successful allocation is registered immediately. ExitStack still
    # runs all remaining cleanup if setup, a flush, or a restore callback fails.
    with ExitStack() as cleanup:
        def own(fd):
            cleanup.callback(os.close, fd)
            return fd
        saved_stdout, saved_stderr = own(os.dup(1)), own(os.dup(2))
        capture = own(os.memfd_create('vault-reset-public-output', os.MFD_CLOEXEC))
        quiet = own(os.open('/dev/null', os.O_WRONLY | os.O_CLOEXEC))
        # Flush preexisting wrappers before changing the process descriptors.
        sys.stdout.flush(); sys.stderr.flush()
        cleanup.callback(os.dup2, saved_stderr, 2)
        cleanup.callback(os.dup2, saved_stdout, 1)
        os.dup2(capture, 1); os.dup2(quiet, 2)
        stream_fd = own(os.dup(capture))
        stream = cleanup.enter_context(os.fdopen(stream_fd, 'w', encoding='utf-8', buffering=1, closefd=False))
        saved_argv = sys.argv
        cleanup.callback(setattr, sys, 'argv', saved_argv)
        sys.argv = derived_argv(value)
        with redirect_stdout(stream), redirect_stderr(Discard()):
            result = module.main()
        stream.flush()
        require(type(result) is int and result == 0, 'helper-did-not-exit-zero')
        size = os.fstat(capture).st_size
        require(0 < size <= OUTPUT_LIMIT, 'helper-output-missing-or-oversized')
        os.lseek(capture, 0, os.SEEK_SET)
        payload = os.read(capture, OUTPUT_LIMIT + 1)
        require(len(payload) == size, 'helper-output-readback-incomplete')
        return payload.decode('utf-8')


def protected_marker(output, value):
    _, case, action = validate_request(value, value['slot'])
    wanted = 'VAULT_RESET_USBREADY=' if action == 'arm' else 'VAULT_RESET_PROBE_PASS='
    prefixes = ('VAULT_RESET_USBREADY=', 'VAULT_RESET_PROBE_PASS=')
    candidates = [line for line in output.splitlines() if line.startswith(prefixes)]
    require(len(candidates) == 1 and candidates[0].startswith(wanted), 'helper-completion-marker-missing-or-conflicting')
    marker = unique_json(candidates[0][len(wanted):].encode())
    sha_key = 'ready_sha256' if action == 'arm' else 'probe_sha256'
    require(set(marker) == {'case', 'nonce', sha_key} and marker['case'] == case and
            marker['nonce'] == value['nonce'] and isinstance(marker[sha_key], str) and HEX.fullmatch(marker[sha_key]),
            'helper-completion-marker-identity-mismatch')
    return wanted, marker, sha_key


def verified_marker_file(value, marker, sha_key):
    _, _, action = validate_request(value, value['slot'])
    stem = 'ci-reset-' + value['phase'] + '-' + value['case'] + '-' + value['nonce']
    output = MEDIA / (stem + ('-ready.json' if action == 'arm' else '-probe.json'))
    payload, _ = public_bytes(output, 128 * 1024, expected_sha=marker[sha_key])
    # Full helper evidence is validated separately by the host. Here only
    # metadata is interpreted; no private snapshot or log is ever read.
    def unique(pairs):
        result = {}
        for key, item in pairs:
            require(key not in result, 'duplicate-helper-evidence-key')
            result[key] = item
        return result
    proof = json.loads(payload, object_pairs_hook=unique)
    require(isinstance(proof, dict) and type(proof.get('schema')) is int and proof['schema'] == 1 and
            proof.get('status') == ('USBREADY' if action == 'arm' else 'passed-reset-observations') and
            all(proof.get(key) == value[key] for key in ('phase', 'firmware', 'case', 'nonce', 'helper_sha256')) and
            proof.get('guest_probe_sha256') == PROBE_SHA and valid_boot(proof.get('source_boot_id')),
            'helper-evidence-identity-mismatch')
    if action == 'probe':
        require(proof.get('ready_sha256') == value['ready_sha256'] and valid_boot(proof.get('current_boot_id'))
                and proof['current_boot_id'] != proof['source_boot_id'], 'helper-evidence-ready-or-boot-mismatch')


def fsync_ack(path, value):
    require(set(value) == ACK_KEYS, 'invalid-runner-ack-key-set')
    payload = (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()
    require(0 < len(payload) <= JSON_LIMIT, 'runner-ack-oversized')
    no_links(path.parent)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        with os.fdopen(fd, 'wb', closefd=False) as stream:
            stream.write(payload); stream.flush(); os.fsync(fd)
    finally:
        os.close(fd)
    parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        os.fsync(parent)
    finally:
        os.close(parent)
    public_bytes(path, JSON_LIMIT, expected_sha=hashlib.sha256(payload).hexdigest())


def guest_guard():
    require(os.getuid() == os.geteuid() == GUEST_UID and os.environ.get('HOME') == '/home/vault', 'not-normal-vault-account')
    require(Path('/sys/class/dmi/id/sys_vendor').read_text().strip() == 'QEMU', 'not-designated-qemu')
    require(Path(os.path.abspath(__file__)) == MEDIA / RUNNER, 'runner-not-on-fixed-usb-path')


def run_slot(slot):
    guest_guard()
    require(slot in SLOTS, 'invalid-slot')
    os.umask(0o077)
    _, runner_sha = public_bytes(MEDIA / RUNNER, CODE_LIMIT)
    request_bytes, request_sha = public_bytes(MEDIA / ('ci-reset-request-' + slot + '.json'), JSON_LIMIT)
    value = unique_json(request_bytes)
    validate_request(value, slot)
    helper_bytes, _ = public_bytes(MEDIA / HELPER, CODE_LIMIT, expected_sha=HELPER_SHA, expected_size=HELPER_BYTES)
    public_bytes(MEDIA / PROBE, CODE_LIMIT, expected_sha=PROBE_SHA, expected_size=PROBE_BYTES)
    ack_path = MEDIA / ('ci-reset-runner-' + slot + '-result.json')
    try:
        ack_path.lstat()
    except FileNotFoundError:
        pass
    else:
        raise RunnerFailure('runner-ack-already-exists')
    output = invoke_helper(compiled_helper(helper_bytes), value)
    prefix, marker, sha_key = protected_marker(output, value)
    verified_marker_file(value, marker, sha_key)
    ack = {key: value[key] for key in ('schema', 'slot', 'phase', 'firmware', 'case', 'nonce', 'helper_sha256', 'probe_sha256')}
    ack.update(request_sha256=request_sha, runner_sha256=runner_sha,
               status='passed-runner-execution', helper_exit_code=0)
    fsync_ack(ack_path, ack)
    # Only authenticated public completion data are forwarded. Everything
    # else, including native stderr, is discarded from anonymous RAM buffers.
    print(prefix + json.dumps(marker, separators=(',', ':')), flush=True)


def banner(slot, code):
    _, case, action = SLOTS[slot]
    return 'VAULT CI RESET ' + case.upper() + ' ' + action.upper() + ' DONE EXIT ' + str(code)


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    slot = arguments[0] if arguments and arguments[0] in SLOTS else None
    try:
        require(len(arguments) == 1 and slot is not None, 'invalid-cli')
        run_slot(slot)
    except BaseException as error:
        # Frozen helper exceptions, SystemExit and alarm expiry all mean
        # unsuccessful execution; native/error messages are never forwarded.
        label = error.args[0] if isinstance(error, RunnerFailure) else 'helper-or-transport-failed'
        print('VAULT_RESET_RUNNER_FAIL=' + json.dumps({'failure': label}, separators=(',', ':')), flush=True)
        if slot is not None:
            print(banner(slot, 1), flush=True)
        return 1
    print(banner(slot, 0), flush=True)
    return 0


def self_test():
    """Local source-only regressions; never execute a guest arm/probe mode."""
    import copy
    import tempfile
    import unittest
    from unittest.mock import Mock, patch

    def request(slot='live-normal-arm'):
        phase, case, action = SLOTS[slot]
        result = {'schema': 1, 'slot': slot, 'phase': phase, 'firmware': 'bios', 'case': case,
                  'nonce': 'a' * 32, 'helper_sha256': HELPER_SHA, 'probe_sha256': PROBE_SHA}
        if action == 'probe': result['ready_sha256'] = 'b' * 64
        return result

    class Tests(unittest.TestCase):
        def test_all_slots_are_fixed_and_derive_only_safe_argv(self):
            self.assertEqual(len(SLOTS), 8)
            for slot in SLOTS:
                value = request(slot); phase, case, action = validate_request(value, slot)
                argv = derived_argv(value)
                self.assertEqual(argv[0], str(MEDIA / HELPER))
                self.assertEqual(argv[2], 'probe' if action == 'probe' else ('arm-existing' if case == 'normal' else 'arm-fresh'))
                self.assertEqual('--ready-sha256' in argv, action == 'probe')
                self.assertEqual(banner(slot, 0), 'VAULT CI RESET ' + case.upper() + ' ' + action.upper() + ' DONE EXIT 0')

        def test_request_identity_schema_nonce_and_pins_fail_closed(self):
            mutations = [lambda v: v.update(schema=True), lambda v: v.update(slot='installed-normal-arm'),
                         lambda v: v.update(phase='installed'), lambda v: v.update(case='abrupt'),
                         lambda v: v.update(firmware='unknown'), lambda v: v.update(nonce='0' * 32),
                         lambda v: v.update(nonce='A' * 32), lambda v: v.update(nonce='../escape'),
                         lambda v: v.update(helper_sha256='f' * 64), lambda v: v.update(probe_sha256='f' * 64),
                         lambda v: v.update(ready_sha256='b' * 64), lambda v: v.update(path='/arbitrary'),
                         lambda v: v.update(code='print(42)'), lambda v: v.pop('nonce')]
            for mutate in mutations:
                value = request(); mutate(value)
                with self.assertRaises(RunnerFailure): validate_request(value, 'live-normal-arm')
            value = request('live-normal-probe'); value.pop('ready_sha256')
            with self.assertRaises(RunnerFailure): validate_request(value, 'live-normal-probe')
            value = request('live-normal-probe'); value['ready_sha256'] = '--anything'
            with self.assertRaises(RunnerFailure): validate_request(value, 'live-normal-probe')

        def test_json_duplicate_unknown_large_and_nonobject(self):
            for payload in (b'{"schema":1,"schema":1}', b'[]', b'{}' + b' ' * JSON_LIMIT):
                with self.assertRaises(RunnerFailure): unique_json(payload)
            self.assertEqual(unique_json(b'{"public":true}'), {'public': True})

        def test_fd_owner_modes_links_special_files_and_hashes(self):
            with tempfile.TemporaryDirectory() as directory, patch(__name__ + '.GUEST_UID', os.getuid()):
                root = Path(directory); path = root / 'request.json'; path.write_bytes(b'public')
                sha = hashlib.sha256(b'public').hexdigest()
                for mode in MODES:
                    path.chmod(mode); self.assertEqual(public_bytes(path, 16, sha), (b'public', sha))
                for mode in (0o666, 0o777, 0o400, 0o664):
                    path.chmod(mode)
                    with self.assertRaises(RunnerFailure): public_bytes(path, 16)
                path.chmod(0o600)
                with self.assertRaises(RunnerFailure): public_bytes(path, 16, 'f' * 64)
                with self.assertRaises(RunnerFailure): public_bytes(path, 16, expected_size=5)
                with self.assertRaises(RunnerFailure): public_bytes(path, 5)
                other = root / 'hard'; os.link(path, other)
                with self.assertRaises(RunnerFailure): public_bytes(path, 16)
                other.unlink(); path.unlink(); path.symlink_to('missing')
                with self.assertRaises(RunnerFailure): public_bytes(path, 16)
                path.unlink(); os.mkfifo(path)
                with self.assertRaises(RunnerFailure): public_bytes(path, 16)
                owned = root / 'owned'; owned.write_bytes(b'public'); owned.chmod(0o600)
                with patch(__name__ + '.GUEST_UID', os.getuid() + 1):
                    with self.assertRaises(RunnerFailure): safe_file(owned.stat(), 16)

        def test_actual_frozen_helper_buffer_and_code_mutations(self):
            # Module definition only: no main(), guest checks or VM mode run.
            original = Path(__file__).with_name(HELPER).read_bytes()
            module = compiled_helper(original)
            self.assertTrue(callable(module.main))
            self.assertEqual(Path(module.__file__), MEDIA / HELPER)
            for payload in (original[:-1], original + b'\n', b'x' + original[1:]):
                with self.assertRaises(RunnerFailure): compiled_helper(payload)

        def test_marker_readback_evidence_identity_and_boot_gates(self):
            with tempfile.TemporaryDirectory() as directory, patch(__name__ + '.GUEST_UID', os.getuid()), \
                    patch(__name__ + '.MEDIA', Path(directory)):
                for slot in ('live-normal-arm', 'installed-abrupt-probe'):
                    value = request(slot)
                    action = SLOTS[slot][2]
                    proof = {'schema': 1, 'status': 'USBREADY' if action == 'arm' else 'passed-reset-observations',
                             **{key: value[key] for key in ('phase', 'firmware', 'case', 'nonce', 'helper_sha256')},
                             'guest_probe_sha256': PROBE_SHA, 'source_boot_id': '12345678-1234-4321-abcd-123456789abc'}
                    if action == 'probe':
                        proof.update(ready_sha256=value['ready_sha256'], current_boot_id='87654321-4321-1234-dcba-cba987654321')
                    stem = 'ci-reset-' + value['phase'] + '-' + value['case'] + '-' + value['nonce']
                    path = MEDIA / (stem + ('-ready.json' if action == 'arm' else '-probe.json'))
                    def write(candidate):
                        data = (json.dumps(candidate) + '\n').encode(); path.write_bytes(data); path.chmod(0o600)
                        return {'case': value['case'], 'nonce': value['nonce'],
                                ('ready_sha256' if action == 'arm' else 'probe_sha256'): hashlib.sha256(data).hexdigest()}
                    key = 'ready_sha256' if action == 'arm' else 'probe_sha256'
                    verified_marker_file(value, write(proof), key)
                    bad = copy.deepcopy(proof); bad['source_boot_id'] = '00000000-0000-0000-0000-000000000000'
                    with self.assertRaises(RunnerFailure): verified_marker_file(value, write(bad), key)
                    bad = copy.deepcopy(proof); bad['phase'] = 'wrong'
                    with self.assertRaises(RunnerFailure): verified_marker_file(value, write(bad), key)
                    if action == 'probe':
                        for field, changed in (('current_boot_id', proof['source_boot_id']), ('ready_sha256', 'f' * 64)):
                            bad = copy.deepcopy(proof); bad[field] = changed
                            with self.assertRaises(RunnerFailure): verified_marker_file(value, write(bad), key)

        def test_marker_is_unique_exact_and_bound_to_case_nonce(self):
            value = request(); body = {'case': 'normal', 'nonce': value['nonce'], 'ready_sha256': 'c' * 64}
            good = 'VAULT_RESET_USBREADY=' + json.dumps(body)
            self.assertEqual(protected_marker('discarded native output\n' + good + '\n', value)[1], body)
            failures = ['', good + '\n' + good, good.replace('normal', 'abrupt'),
                        good.replace('a' * 32, 'b' * 32), good.replace('c' * 64, 'short'),
                        'VAULT_RESET_PROBE_PASS=' + json.dumps(body),
                        'VAULT_RESET_USBREADY=' + json.dumps(dict(body, arbitrary='data'))]
            for output in failures:
                with self.assertRaises(RunnerFailure): protected_marker(output, value)

        def test_helper_output_is_anonymous_and_not_forwarded_on_error(self):
            value = request()
            def good():
                self.assertEqual(sys.argv, derived_argv(value))
                print('public buffered output', flush=True)
                print('discard private diagnostic', file=sys.stderr)
                os.write(2, b'discard native diagnostic\n')
                return 0
            self.assertEqual(invoke_helper(SimpleNamespace(main=good), value), 'public buffered output\n')
            for result in (1, True, None):
                with self.assertRaises(RunnerFailure): invoke_helper(SimpleNamespace(main=lambda: result), value)
            def failure():
                print('private diagnostic never forwarded', flush=True)
                raise RuntimeError('private exception text never forwarded')
            with self.assertRaises(RuntimeError): invoke_helper(SimpleNamespace(main=failure), value)

        def test_partial_setup_closes_all_fds_without_invoking_helper(self):
            value = request(); fake = SimpleNamespace(main=Mock(return_value=0))
            def fds():
                return set(os.listdir('/proc/self/fd'))
            real_dup, real_dup2, real_open = os.dup, os.dup2, os.open
            for which in ('dup-first', 'dup-second', 'dup-stream', 'memfd', 'dev-null', 'fdopen', 'redirect-first', 'redirect-second'):
                count = [0]
                def dup(fd):
                    count[0] += 1
                    fail_at = {'dup-first': 1, 'dup-second': 2, 'dup-stream': 3}.get(which)
                    if count[0] == fail_at:
                        raise PermissionError('public-test')
                    return real_dup(fd)
                redirects = [0]
                def dup2(fd, target):
                    redirects[0] += 1
                    fail_at = {'redirect-first': 1, 'redirect-second': 2}.get(which)
                    if redirects[0] == fail_at:
                        raise PermissionError('public-test')
                    return real_dup2(fd, target)
                def open_file(path, flags):
                    if which == 'dev-null' and path == '/dev/null':
                        raise PermissionError('public-test')
                    return real_open(path, flags)
                before = fds()
                with patch(__name__ + '.os.dup', side_effect=dup), patch(__name__ + '.os.dup2', side_effect=dup2), \
                        patch(__name__ + '.os.open', side_effect=open_file):
                    if which == 'memfd':
                        with patch(__name__ + '.os.memfd_create', side_effect=PermissionError):
                            with self.assertRaises(PermissionError): invoke_helper(fake, value)
                    elif which == 'fdopen':
                        with patch(__name__ + '.os.fdopen', side_effect=PermissionError):
                            with self.assertRaises(PermissionError): invoke_helper(fake, value)
                    else:
                        with self.assertRaises(PermissionError): invoke_helper(fake, value)
                self.assertEqual(fds(), before, which)
                fake.main.assert_not_called()

        def test_ack_exclusive_fsync_and_only_public_fields(self):
            with tempfile.TemporaryDirectory() as directory, patch(__name__ + '.GUEST_UID', os.getuid()):
                value = request(); ack = {key: value[key] for key in ARM_KEYS}
                ack.update(request_sha256='b' * 64, runner_sha256='c' * 64,
                           status='passed-runner-execution', helper_exit_code=0)
                path = Path(directory) / 'ack.json'; fsync_ack(path, ack)
                self.assertEqual(unique_json(public_bytes(path, JSON_LIMIT)[0]), ack)
                with self.assertRaises(FileExistsError): fsync_ack(path, ack)
                with self.assertRaises(RunnerFailure): fsync_ack(Path(directory) / 'bad.json', dict(ack, secret='no'))

        def test_failure_banner_has_true_nonzero_status_without_raw_output(self):
            capture = io.StringIO()
            with patch(__name__ + '.run_slot', side_effect=RuntimeError('private data')), redirect_stdout(capture):
                self.assertEqual(main(['live-normal-arm']), 1)
            self.assertNotIn('private data', capture.getvalue())
            self.assertIn('VAULT CI RESET NORMAL ARM DONE EXIT 1', capture.getvalue())
            with patch(__name__ + '.run_slot') as run, redirect_stdout(io.StringIO()):
                self.assertEqual(main(['live-normal-arm', 'arbitrary']), 1); run.assert_not_called()

    from types import SimpleNamespace
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Tests))
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
