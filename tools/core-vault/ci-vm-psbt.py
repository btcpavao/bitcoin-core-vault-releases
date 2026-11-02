#!/usr/bin/python3
"""Test-only recovered-wallet signing in a disposable Vault guest's RAM.

This never changes the production mainnet launcher, uses no real coins, and
never broadcasts. The secondary official GUI binary uses the verified guest
X11 session and starts minimized, solely as an isolated signing fixture.
No backend output, keys, descriptors, PSBTs or passphrases are reported.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import resource
import shutil
import signal
import socket
import stat
import subprocess
import tempfile
import threading
import time

CORE = Path('/usr/local/bin/bitcoin-qt')
CLI = Path('/usr/local/bin/bitcoin-cli')
CORE_SHA256 = 'd43632a3e54dfb181ba045db2a5b1ec2396a1acdda010e3b6d07b2e21c69c183'
PLATFORM = 'xcb'
# Per-format operation allowance for slow TCG. The caller's whole-probe
# watchdog also covers initial attestation and the separate bounded cleanup.
PROOF_SECONDS = 360
READY_SECONDS = 120
PHASES = frozenset({'attestation-start', 'attestation-passed', 'archive-decryption-start',
    'snapshot-verified', 'secondary-core-starting', 'secondary-rpc-ready',
    'control-restore-start', 'control-restored', 'control-signing-start',
    'control-signed-and-finalized', 'fresh-restore-start', 'fresh-restored',
    'fresh-signing-start', 'fresh-signed-and-finalized', 'cleanup-start',
    'cleanup-complete', 'proof-complete'})
RPC_METHODS = frozenset({'getnetworkinfo', 'getblockchaininfo', 'listwallets', 'restorewallet',
    'getwalletinfo', 'getnewaddress', 'getaddressinfo', 'createpsbt', 'decodepsbt',
    'decoderawtransaction', 'walletprocesspsbt', 'finalizepsbt', 'walletpassphrase',
    'walletlock', 'stop'})
# Only these fixed tags may be persisted by the caller as an error reason.
PUBLIC_FAILURE_LABELS = frozenset({
    'archive-format-receipt-mismatch', 'archive-path-receipt-mismatch',
    'cli-differs-from-installed-payload', 'control-address-not-owned', 'duplicate-psbt-key',
    'encrypted-archive-sha256-mismatch', 'encrypted-recovered-wallet-was-not-locked',
    'finalized-transaction-lacks-fresh-p2wpkh-signature',
    'fresh-recovered-wallet-does-not-own-synthetic-utxo-address', 'invalid-psbt-length',
    'invalid-psbt-magic', 'invalid-psbt-map', 'invalid-public-proof-phase',
    'invalid-unsigned-psbt-or-script', 'noncanonical-or-oversized-psbt-length', 'not-regular-file',
    'official-core-binary-not-executable', 'official-core-identity-changed',
    'original-encrypted-archive-changed', 'oversized-regtest-rpc-output',
    'recovered-wallet-cannot-sign-synthetic-utxo-psbt', 'regtest-7z-recovery-failed',
    'regtest-chain-or-initial-wallets-incorrect', 'regtest-child-identity-changed',
    'regtest-child-not-running-or-identity-changed', 'regtest-cleanup-path-not-private-ram',
    'regtest-core-dumps-not-disabled', 'regtest-core-exited-before-rpc', 'regtest-core-is-not-offline',
    'regtest-core-rpc-not-ready', 'regtest-fixture-is-outside-private-ram',
    'regtest-fixture-remains-in-production-wallet-inventory', 'regtest-guest-has-network-device',
    'regtest-pid-file-mismatch', 'regtest-port-conflicts-with-production',
    'regtest-proof-deadline-expired', 'regtest-proof-requires-vault-uid', 'regtest-readiness-failed',
    'regtest-recovered-snapshot-mismatch', 'regtest-restored-gpg-profile-mismatch',
    'regtest-rpc-timeout', 'regtest-signing-proof-not-completed', 'restore-mutated-original-snapshot',
    'restored-wallet-encryption-state-mismatch', 'restored-wallet-has-no-private-keys',
    'signed-psbt-not-finalizable', 'signed-public-key-does-not-match-synthetic-utxo',
    'signed-synthetic-input-or-key-mismatch', 'supplied-synthetic-witness-utxo-not-validated',
    'synthetic-utxo-is-not-p2wpkh', 'truncated-psbt-length', 'truncated-psbt-value',
    'unexpected-private-ram-root', 'unexpected-test-rpc-method', 'unexpected-test-wallet-name',
    'unsafe-binary-owner-or-mode', 'unsafe-regtest-cookie', 'unsafe-regtest-ram-parent',
    'unsafe-rpc-stdin-value', 'unsigned-psbt-has-preexisting-data-or-wrong-map-count',
    'unsigned-psbt-has-preexisting-input-data', 'unexpected-guest-x11-display',
    'unexpected-guest-x11-authority', 'unsafe-guest-x11-authority', 'unsafe-guest-x11-socket',
    'guest-x11-authority-not-in-ram',
    'unsafe-guest-x11-runtime-alias',
    'startup-diagnostics-not-pre-wallet', 'startup-capture-not-cleared', 'startup-drainer-not-reaped'
}) | frozenset('regtest-rpc-' + method + '-failed' for method in RPC_METHODS)


class SigningProofError(RuntimeError):
    """Fixed, public failure labels; never include native process output."""


def _require(condition, label):
    if not condition:
        raise SigningProofError(label)


def _phase(backup_format, label, started, observations):
    """Only fixed public phases/timing can reach test output, never native data."""
    _require(backup_format in ('7z', 'gpg') and label in PHASES, 'invalid-public-proof-phase')
    observation = {'phase': label, 'elapsed_seconds': round(time.monotonic() - started, 2)}
    observations.append(observation)
    try:
        print('[PSBT] ' + json.dumps(dict(backup_format=backup_format, **observation), sort_keys=True), flush=True)
    except OSError:
        # Loss of the controller's output pipe must never bypass child cleanup.
        # Keep the public timing record for the caller's eventual JSON report.
        pass


def _hash(path, deadline=None):
    with path.open('rb') as stream:
        digest = hashlib.sha256()
        while block := stream.read(1024 * 1024):
            if deadline is not None:
                _remaining(deadline)
            digest.update(block)
        return digest.hexdigest()


def _regular(path, owner=None):
    info = path.lstat()
    _require(stat.S_ISREG(info.st_mode) and not path.is_symlink(), 'not-regular-file')
    if owner is not None:
        _require(info.st_uid == owner and not info.st_mode & 0o022, 'unsafe-binary-owner-or-mode')
    return info


def _archive_identity(path):
    info = _regular(path)
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns,
            _hash(path))


def _remaining(deadline, maximum=30):
    remaining = deadline - time.monotonic()
    _require(remaining > 0, 'regtest-proof-deadline-expired')
    return min(maximum, remaining)


class _DeadlineProgress:
    def __init__(self, deadline):
        self.deadline = deadline

    def check(self):
        _remaining(self.deadline)

    def close(self):
        pass


def _rpc_command(directory, cookie, port, method, wallet=None):
    _require(method in RPC_METHODS,
             'unexpected-test-rpc-method')
    arguments = [str(CLI), '-datadir=' + str(directory),
                 '-rpccookiefile=' + str(cookie), '-rpcconnect=127.0.0.1',
                 '-rpcport=' + str(port)]
    if wallet is not None:
        _require(wallet in ('snapshot-control', 'fresh-recovery'), 'unexpected-test-wallet-name')
        arguments.append('-rpcwallet=' + wallet)
    # All parameters, including walletpassphrase, travel only over stdin.
    return [*arguments, '-stdin', method]


def _compact(value):
    _require(type(value) is int and 0 <= value <= 1024 * 1024, 'invalid-psbt-length')
    if value < 253:
        return bytes([value])
    if value <= 65535:
        return b'\xfd' + value.to_bytes(2, 'little')
    return b'\xfe' + value.to_bytes(4, 'little')


def _read_compact(data, offset):
    _require(offset < len(data), 'truncated-psbt-length')
    marker = data[offset]
    offset += 1
    if marker < 253:
        return marker, offset
    width = {253: 2, 254: 4, 255: 8}[marker]
    _require(offset + width <= len(data), 'truncated-psbt-length')
    value = int.from_bytes(data[offset:offset + width], 'little')
    _require(value >= {253: 253, 254: 65536, 255: 4294967296}[marker]
             and value <= 1024 * 1024, 'noncanonical-or-oversized-psbt-length')
    return value, offset + width


def _map(data, offset):
    entries = {}
    while True:
        length, offset = _read_compact(data, offset)
        if length == 0:
            return entries, offset
        _require(len(entries) < 64 and offset + length <= len(data), 'invalid-psbt-map')
        key = data[offset:offset + length]
        offset += length
        _require(key not in entries, 'duplicate-psbt-key')
        length, offset = _read_compact(data, offset)
        _require(offset + length <= len(data), 'truncated-psbt-value')
        entries[key] = data[offset:offset + length]
        offset += length


def _supplied_witness_utxo(unsigned_psbt, script_hex):
    """Add exactly one public, synthetic P2WPKH witnessUTXO (BIP174).

    Core creates the unsigned one-input/one-output transaction. Reject any
    existing input data/signature; the two signers receive this exact PSBT.
    """
    try:
        data = base64.b64decode(unsigned_psbt, validate=True)
        script = bytes.fromhex(script_hex)
    except (ValueError, TypeError):
        raise SigningProofError('invalid-unsigned-psbt-or-script') from None
    _require(len(data) <= 1024 * 1024 and data.startswith(b'psbt\xff'), 'invalid-psbt-magic')
    _require(len(script) == 22 and script[:2] == b'\x00\x14', 'synthetic-utxo-is-not-p2wpkh')
    global_map, global_end = _map(data, 5)
    input_map, input_end = _map(data, global_end)
    output_map, end = _map(data, input_end)
    _require(set(global_map) == {b'\x00'} and not input_map and not output_map and end == len(data),
             'unsigned-psbt-has-preexisting-data-or-wrong-map-count')
    value = (200000000).to_bytes(8, 'little') + _compact(len(script)) + script
    item = _compact(1) + b'\x01' + _compact(len(value)) + value + b'\x00'
    return base64.b64encode(data[:global_end] + item + data[input_end:]).decode('ascii')


def _rpc(directory, cookie, port, deadline, environment, method, *parameters, wallet=None):
    values = [str(value) for value in parameters]
    _require(all(not any(c in value for c in '\r\n\0') for value in values), 'unsafe-rpc-stdin-value')
    try:
        result = subprocess.run(_rpc_command(directory, cookie, port, method, wallet),
            input=''.join(value + '\n' for value in values), text=True,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=environment,
            timeout=_remaining(deadline), check=False)
    except subprocess.TimeoutExpired:
        raise SigningProofError('regtest-rpc-timeout') from None
    _require(result.returncode == 0, 'regtest-rpc-' + method + '-failed')
    _require(len(result.stdout) <= 4 * 1024 * 1024, 'oversized-regtest-rpc-output')
    text = result.stdout.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _birth(pid):
    return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19]


def _owned(process, birth, arguments):
    if process.poll() is not None:
        return False
    try:
        actual = Path(f'/proc/{process.pid}/cmdline').read_bytes().split(b'\0')[:-1]
        return (_birth(process.pid) == birth and os.getpgid(process.pid) == process.pid
                and actual == [os.fsencode(value) for value in arguments]
                and Path(f'/proc/{process.pid}/exe').resolve(strict=True) == CORE)
    except (FileNotFoundError, ProcessLookupError):
        return False


def _stop(process, birth, arguments, rpc):
    """Only stop/reap the child we started; never signal a reaped/stale PGID."""
    if process.poll() is None:
        _require(_owned(process, birth, arguments), 'regtest-child-identity-changed')
        try:
            rpc('stop')
        except SigningProofError:
            pass
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            _require(_owned(process, birth, arguments), 'regtest-child-identity-changed')
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _require(_owned(process, birth, arguments), 'regtest-child-identity-changed')
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
    else:
        process.wait(timeout=1)


def _attest(runtime):
    _require(os.getuid() == os.geteuid() == 1000, 'regtest-proof-requires-vault-uid')
    _require(resource.getrlimit(resource.RLIMIT_CORE) == (0, 0), 'regtest-core-dumps-not-disabled')
    _require({p.name for p in Path('/sys/class/net').iterdir()} == {'lo'}, 'regtest-guest-has-network-device')
    _require(runtime.ROOT == Path('/run/core-vault'), 'unexpected-private-ram-root')
    runtime.check_storage()
    runtime.check_core_mounts()
    for binary in (CORE, CLI):
        _regular(binary, owner=0)
        _require(os.access(binary, os.X_OK), 'official-core-binary-not-executable')
    _require(_hash(CORE) == CORE_SHA256, 'official-core-identity-changed')
    manifest = json.loads(Path('/etc/core-vault/installer-payload.json').read_text())['files']
    _require(manifest.get('usr/local/bin/bitcoin-cli') == _hash(CLI), 'cli-differs-from-installed-payload')


def _authority_classification(value):
    if value is None or value == '':
        return 'unset'
    return {'/home/vault/.Xauthority': 'knownhome',
            '/run/lightdm/vault/xauthority': 'knownrun',
            '/var/run/lightdm/vault/xauthority': 'knownvarrun'}.get(value, 'other')


def _verified_var_run_alias():
    """Verify only Debian's exact root-controlled /var/run -> /run alias."""
    try:
        alias = Path('/var/run').lstat()
        target = os.readlink('/var/run')
        directories = [Path('/var').lstat(), Path('/run').lstat()]
    except OSError:
        raise SigningProofError('unsafe-guest-x11-runtime-alias') from None
    _require(stat.S_ISLNK(alias.st_mode) and alias.st_uid == 0
             and target in ('/run', '../run')
             and all(stat.S_ISDIR(info.st_mode) and info.st_uid == 0
                     and not info.st_mode & 0o022 for info in directories),
             'unsafe-guest-x11-runtime-alias')


def _session_x11(runtime=None):
    """Use only the actual local Vault display and its known auth file."""
    supplied = os.environ.get('XAUTHORITY')
    try:
        print('[PSBT X11] ' + json.dumps({'authority_class': _authority_classification(supplied),
            'display_class': 'knownlocal' if os.environ.get('DISPLAY') == ':0' else 'other'},
            sort_keys=True), flush=True)
    except OSError:
        pass
    _require(os.environ.get('DISPLAY') == ':0', 'unexpected-guest-x11-display')
    known = (Path('/run/lightdm/vault/xauthority'), Path('/home/vault/.Xauthority'))
    def eligible(path, info):
        return (stat.S_ISREG(info.st_mode) and not path.is_symlink()
                and not path.parent.is_symlink() and info.st_uid in (0, 1000)
                and not info.st_mode & 0o022 and os.access(path, os.R_OK))
    if supplied:
        if supplied == '/var/run/lightdm/vault/xauthority':
            _verified_var_run_alias()
            authority = known[0]
        else:
            authority = Path(supplied)
        _require(authority in known, 'unexpected-guest-x11-authority')
        _require(eligible(authority, authority.lstat()), 'unsafe-guest-x11-authority')
    else:
        # Ordinary Vault terminals may leave XAUTHORITY unset. Never accept an
        # arbitrary path or weaken validation; use only an eligible known file.
        authority = None
        for candidate in known:
            try:
                info = candidate.lstat()
            except FileNotFoundError:
                continue
            if eligible(candidate, info):
                authority = candidate
                break
        _require(authority is not None, 'unsafe-guest-x11-authority')
    if runtime is not None:
        _require(runtime.mount_at(authority)['fstype'] == 'tmpfs', 'guest-x11-authority-not-in-ram')
    connection = Path('/tmp/.X11-unix/X0')
    info = connection.lstat()
    _require(stat.S_ISSOCK(info.st_mode) and not connection.is_symlink() and not connection.parent.is_symlink()
             and info.st_uid in (0, 1000), 'unsafe-guest-x11-socket')
    return {'DISPLAY': ':0', 'XAUTHORITY': str(authority)}


class _StartupCapture:
    """Drain stdout continuously; retain only a bounded pre-wallet RAM tail."""
    def __init__(self, stream):
        self.stream, self.lock = stream, threading.Lock()
        self.enabled, self.tail, self.total = True, bytearray(), 0
        self.thread = threading.Thread(target=self._drain, daemon=True)
        self.thread.start()

    def _record(self, block):
        with self.lock:
            if self.enabled:
                self.total += len(block)
                self.tail.extend(block)
                del self.tail[:-4096]

    def _drain(self):
        try:
            while block := os.read(self.stream.fileno(), 4096):
                self._record(block)
        except OSError:
            pass

    def snapshot(self):
        with self.lock:
            return bytes(self.tail), self.total, self.enabled

    def discard(self):
        with self.lock:
            self.enabled = False
            self.tail.clear()
            self.total = 0

    def close(self):
        self.discard()
        self.thread.join(timeout=2)
        self.stream.close()
        self.thread.join(timeout=2)
        _require(not self.thread.is_alive(), 'startup-drainer-not-reaped')


def _startup_diagnostics(work, capture, label, wallet_operations_started):
    """Classify startup errors with fixed public hints; never publish raw text."""
    _require(not wallet_operations_started, 'startup-diagnostics-not-pre-wallet')
    _require(label in PUBLIC_FAILURE_LABELS, 'invalid-public-proof-phase')
    tail, total, enabled = capture.snapshot()
    _require(enabled, 'startup-diagnostics-not-pre-wallet')
    hint = 'unclassified-startup'
    for needle, fixed in ((b'maxmempool must be at least', 'invalid-mempool-limit'),
            (b'error parsing command line', 'invalid-command-line'),
            (b'could not read setting', 'settings-error'),
            (b'error reading settings', 'settings-error'),
            (b'failed to write settings', 'settings-error'),
            (b'cannot obtain a lock', 'datadir-lock-error'),
            (b'could not connect to display', 'x11-connection-error'),
            (b'qt platform plugin', 'qt-platform-error'),
            (b'this plugin does not support', 'qt-platform-capability-warning')):
        if needle in tail.lower():
            hint = fixed
            break
    diagnostic = {'failure_label': label, 'phase': 'pre-wallet-secondary-core-startup',
                  'observed_startup_hint': hint, 'retained_startup_bytes': len(tail),
                  'startup_output_bytes': total,
                  'cookie_present': (work / 'rpc.cookie').is_file(),
                  'pid_file_present': (work / 'core.pid').is_file()}
    try:
        print('[PSBT STARTUP] ' + json.dumps(diagnostic, sort_keys=True), flush=True)
    except OSError:
        pass


def prove_restored_signing(runtime, export, gpg, archive, receipt, external_phrase,
                           core_phrase, backup_format):
    """Return only public proof facts after all QA wallets and the node are gone.

    A control restore signs a supplied synthetic-witnessUTXO PSBT; a second
    fresh restore of the exact same exported snapshot signs that same unsigned
    PSBT. It has no real/confirmed funding and is never broadcast or submitted
    to testmempoolaccept. Both restores stay on mainnet for descriptor parity.
    Pass core_phrase=None for an unencrypted Core wallet.
    """
    started, observations = time.monotonic(), []
    def phase(label):
        _phase(backup_format, label, started, observations)
    phase('attestation-start')
    _attest(runtime)
    x11 = _session_x11(runtime)
    phase('attestation-passed')
    _require(backup_format in ('7z', 'gpg') and export.receipt_format(receipt) == backup_format,
             'archive-format-receipt-mismatch')
    export.validate_password(external_phrase)
    if core_phrase is not None:
        export.validate_password(core_phrase)
    archive = Path(os.path.abspath(archive))
    _require(archive == Path(receipt['archive']), 'archive-path-receipt-mismatch')
    original = _archive_identity(archive)
    _require(original[-1] == receipt['archive_sha256'], 'encrypted-archive-sha256-mismatch')
    before_inventory = runtime.wallet_files()
    parent = runtime.ROOT / 'export'
    parent_info = parent.lstat()
    _require(parent.is_dir() and not parent.is_symlink() and parent_info.st_uid == 1000
             and stat.S_IMODE(parent_info.st_mode) == 0o700, 'unsafe-regtest-ram-parent')
    deadline = time.monotonic() + PROOF_SECONDS
    progress = _DeadlineProgress(deadline)
    work = Path(tempfile.mkdtemp(prefix='ci-vm-psbt-', dir=parent))
    process = None
    birth = None
    arguments = None
    result = None
    startup_capture = None
    wallet_operations_started = False
    try:
        _require(runtime.mount_at(work)['maj:min'] == runtime.mount_at(runtime.ROOT, True)['maj:min'],
                 'regtest-fixture-is-outside-private-ram')
        raw = work / 'wallet.dat'
        phase('archive-decryption-start')
        if backup_format == 'gpg':
            _require(gpg.decrypt_file(archive, raw, external_phrase, ram_root=parent,
                                     progress=progress) == 'AES256-OCB',
                     'regtest-restored-gpg-profile-mismatch')
        else:
            export.archive_listing(archive, external_phrase)
            progress.check()
            code, prompts = export.run7z(['x', '-t7z', '-y', '-o' + str(work), str(archive), 'wallet.dat'],
                                         external_phrase, progress=progress)
            _require(code == 0 and prompts > 0, 'regtest-7z-recovery-failed')
        _regular(raw, owner=1000)
        _require(_hash(raw, deadline) == receipt['wallet_backup_sha256']
                 and runtime.wallet_digest(raw) == receipt['wallet_digest'], 'regtest-recovered-snapshot-mismatch')
        progress.check()
        snapshot_hash = _hash(raw, deadline)
        phase('snapshot-verified')
        paths = {name: work / name for name in ('node', 'wallets', 'home', 'tmp', 'runtime',
                                                'config', 'cache', 'data', 'state')}
        for path in paths.values():
            path.mkdir(mode=0o700)
        node, cookie = paths['node'], work / 'rpc.cookie'
        # Bind a currently free loopback-only port. A later collision fails
        # readiness/cookie/PID checks; it cannot connect to production RPC8332.
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1', 0))
            port = reservation.getsockname()[1]
        _require(port != 8332, 'regtest-port-conflicts-with-production')
        environment = {'PATH': '/usr/local/bin:/usr/bin:/bin', 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8',
            'HOME': str(paths['home']), 'TMPDIR': str(paths['tmp']), 'TMP': str(paths['tmp']),
            'TEMP': str(paths['tmp']), 'XDG_RUNTIME_DIR': str(paths['runtime']),
            'XDG_CONFIG_HOME': str(paths['config']), 'XDG_CACHE_HOME': str(paths['cache']),
            'XDG_DATA_HOME': str(paths['data']), 'XDG_STATE_HOME': str(paths['state']),
            'QT_QPA_PLATFORM': PLATFORM, **x11}
        (node / 'settings.json').write_text('{"listen": false}\n')
        arguments = [str(CORE), '-chain=main', '-datadir=' + str(node),
            '-walletdir=' + str(paths['wallets']), '-settings=' + str(node / 'settings.json'),
            '-rpccookiefile=' + str(cookie), '-pid=' + str(work / 'core.pid'),
            '-server=1', '-rpcport=' + str(port), '-rpcbind=127.0.0.1', '-rpcallowip=127.0.0.1',
            '-connect=0', '-listen=0', '-listenonion=0', '-discover=0', '-dnsseed=0',
            '-fixedseeds=0', '-natpmp=0', '-maxconnections=0', '-networkactive=0',
            '-dbcache=32', '-maxmempool=5', '-prune=550', '-splash=0', '-min',
            '-nodebuglogfile', '-printtoconsole=1']
        phase('secondary-core-starting')
        process = subprocess.Popen(arguments, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, env=environment, cwd=work, start_new_session=True)
        birth = _birth(process.pid)
        startup_capture = _StartupCapture(process.stdout)
        def rpc(method, *parameters, wallet=None):
            _require(_owned(process, birth, arguments), 'regtest-child-not-running-or-identity-changed')
            return _rpc(node, cookie, port, deadline, environment, method, *parameters, wallet=wallet)
        ready = min(deadline, time.monotonic() + READY_SECONDS)
        try:
            while True:
                _require(_owned(process, birth, arguments), 'regtest-core-exited-before-rpc')
                try:
                    info = _rpc(node, cookie, port, ready, environment, 'getnetworkinfo')
                    break
                except SigningProofError as exc:
                    _require(str(exc) == 'regtest-rpc-getnetworkinfo-failed', 'regtest-readiness-failed')
                    _require(time.monotonic() < ready, 'regtest-core-rpc-not-ready')
                    time.sleep(.2)
        except SigningProofError as exc:
            _startup_diagnostics(work, startup_capture, exc.args[0], wallet_operations_started)
            raise
        _require(info.get('networkactive') is False and info.get('connections') == 0,
                 'regtest-core-is-not-offline')
        _require(rpc('getblockchaininfo').get('chain') == 'main' and rpc('listwallets') == [],
                 'regtest-chain-or-initial-wallets-incorrect')
        _require(cookie.is_file() and not cookie.is_symlink() and cookie.stat().st_uid == 1000
                 and not stat.S_IMODE(cookie.stat().st_mode) & 0o077, 'unsafe-regtest-cookie')
        _require((work / 'core.pid').read_text().strip() == str(process.pid), 'regtest-pid-file-mismatch')
        phase('secondary-rpc-ready')
        # Atomically stop storage and clear startup bytes BEFORE the first
        # private wallet RPC. The pipe is drained/discarded until owned shutdown.
        startup_capture.discard()
        _require(startup_capture.snapshot() == (b'', 0, False), 'startup-capture-not-cleared')
        control, recovered = 'snapshot-control', 'fresh-recovery'
        phase('control-restore-start')
        wallet_operations_started = True
        for name in (control,):
            rpc('restorewallet', name, raw, 'false')
        phase('control-restored')
        wallet_info = rpc('getwalletinfo', wallet=control)
        _require(wallet_info.get('private_keys_enabled') is True, 'restored-wallet-has-no-private-keys')
        _require((wallet_info.get('unlocked_until') == 0) if core_phrase is not None
                 else ('unlocked_until' not in wallet_info), 'restored-wallet-encryption-state-mismatch')
        address = rpc('getnewaddress', '', 'bech32', wallet=control)
        address_info = rpc('getaddressinfo', address, wallet=control)
        _require(address_info.get('ismine') is True, 'control-address-not-owned')
        if core_phrase is not None:
            rpc('walletpassphrase', core_phrase, '120', wallet=control)
        recipient = rpc('getnewaddress', '', 'bech32', wallet=control)
        dummy_txid = hashlib.sha256(b'CORE_VAULT_PUBLIC_SYNTHETIC_UTXO_NOT_REAL_COINS').hexdigest()
        unsigned = rpc('createpsbt', json.dumps([{'txid': dummy_txid, 'vout': 0}]),
                       json.dumps([{recipient: 1.99998}]))
        decoded = rpc('decodepsbt', unsigned)
        _require(len(decoded['tx']['vin']) == len(decoded['tx']['vout']) == 1
                 and decoded['inputs'] == [{}], 'unsigned-psbt-has-preexisting-input-data')
        psbt = _supplied_witness_utxo(unsigned, address_info['scriptPubKey'])
        populated = rpc('decodepsbt', psbt)
        _require(len(populated['inputs']) == 1
                 and set(populated['inputs'][0]) == {'witness_utxo'}
                 and populated['inputs'][0]['witness_utxo']['amount'] == 2,
                 'supplied-synthetic-witness-utxo-not-validated')
        def sign_and_finalize(name):
            signed = rpc('walletprocesspsbt', psbt, wallet=name)
            _require(signed.get('complete') is True, 'recovered-wallet-cannot-sign-synthetic-utxo-psbt')
            final = rpc('finalizepsbt', signed['psbt'])
            _require(final.get('complete') is True and isinstance(final.get('hex'), str), 'signed-psbt-not-finalizable')
            transaction = rpc('decoderawtransaction', final['hex'])
            witness = transaction['vin'][0].get('txinwitness')
            _require(len(transaction['vin']) == 1 and isinstance(witness, list) and len(witness) == 2
                     and len(bytes.fromhex(witness[0])) >= 9 and len(bytes.fromhex(witness[1])) == 33,
                     'finalized-transaction-lacks-fresh-p2wpkh-signature')
            _require(transaction['vin'][0]['txid'] == dummy_txid
                     and transaction['vin'][0]['vout'] == 0
                     and witness[1] == address_info['pubkey'], 'signed-synthetic-input-or-key-mismatch')
            public_key_hash = hashlib.new('ripemd160', hashlib.sha256(bytes.fromhex(witness[1])).digest()).digest()
            _require(b'\x00\x14' + public_key_hash == bytes.fromhex(address_info['scriptPubKey']),
                     'signed-public-key-does-not-match-synthetic-utxo')
            return hashlib.sha256(bytes.fromhex(final['hex'])).hexdigest()
        phase('control-signing-start')
        control_transaction = sign_and_finalize(control)
        phase('control-signed-and-finalized')
        if core_phrase is not None:
            rpc('walletlock', wallet=control)
        _require(_hash(raw) == snapshot_hash, 'restore-mutated-original-snapshot')
        phase('fresh-restore-start')
        rpc('restorewallet', recovered, raw, 'false')
        phase('fresh-restored')
        _require(rpc('getaddressinfo', address, wallet=recovered).get('ismine') is True,
                 'fresh-recovered-wallet-does-not-own-synthetic-utxo-address')
        if core_phrase is not None:
            _require(rpc('getwalletinfo', wallet=recovered).get('unlocked_until') == 0,
                     'encrypted-recovered-wallet-was-not-locked')
            rpc('walletpassphrase', core_phrase, '120', wallet=recovered)
        phase('fresh-signing-start')
        recovered_transaction = sign_and_finalize(recovered)
        phase('fresh-signed-and-finalized')
        if core_phrase is not None:
            rpc('walletlock', wallet=recovered)
        _require(_hash(raw) == snapshot_hash, 'restore-mutated-original-snapshot')
        result = {'backup_format': backup_format, 'test_only': True, 'test_platform': PLATFORM,
            'chain': 'main', 'official_core_sha256': CORE_SHA256,
            'archive_sha256': original[-1], 'snapshot_sha256': snapshot_hash,
            'same_unsigned_psbt_sha256': hashlib.sha256(psbt.encode('ascii')).hexdigest(),
            'control_transaction_sha256': control_transaction,
            'fresh_recovery_transaction_sha256': recovered_transaction,
            'exact_decrypted_snapshot': True, 'supplied_synthetic_witness_utxo': True,
            'preexisting_signatures': False, 'blockchain_funding_proven': False,
            'control_signed': True, 'fresh_recovery_signed': True,
            'both_finalized_with_fresh_witness': True, 'mempool_tested': False, 'broadcast': False,
            'independent_signature_verification': False,
            'core_wallet_encrypted': core_phrase is not None}
    finally:
        phase('cleanup-start')
        if process is not None:
            # Cleanup has its own bounded allowance even if the proof expired.
            def stop_rpc(method):
                return _rpc(node, cookie, port, time.monotonic() + 5, environment, method)
            _stop(process, birth, arguments, stop_rpc)
        if startup_capture is not None:
            startup_capture.close()
        elif process is not None and process.stdout is not None:
            process.stdout.close()
        runtime.check_storage()
        runtime.check_core_mounts()
        _require(not work.is_symlink() and work.parent == parent and work.stat().st_uid == 1000
                 and runtime.mount_at(work)['maj:min'] == runtime.mount_at(runtime.ROOT, True)['maj:min'],
                 'regtest-cleanup-path-not-private-ram')
        shutil.rmtree(work)
        _require(not work.exists() and runtime.wallet_files() == before_inventory,
                 'regtest-fixture-remains-in-production-wallet-inventory')
        _require(_archive_identity(archive) == original, 'original-encrypted-archive-changed')
        phase('cleanup-complete')
    _require(result is not None, 'regtest-signing-proof-not-completed')
    result.update(owned_node_reaped=True, qa_wallets_removed=True, production_inventory_unchanged=True,
                  original_archive_unchanged=True)
    phase('proof-complete')
    result['phase_timings'] = observations
    return result


def _self_test():
    """Narrow negative/helper tests; these do not stand in for actual Core proof."""
    import unittest
    import contextlib
    import io
    from unittest.mock import Mock, patch
    class Tests(unittest.TestCase):
        def test_exact_trusted_var_run_alias_maps_to_guarded_run_file(self):
            def info(path):
                if path == Path('/var/run'):
                    return Mock(st_mode=stat.S_IFLNK | 0o777, st_uid=0)
                if path in (Path('/var'), Path('/run')):
                    return Mock(st_mode=stat.S_IFDIR | 0o755, st_uid=0)
                if path == Path('/tmp/.X11-unix/X0'):
                    return Mock(st_mode=stat.S_IFSOCK | 0o777, st_uid=0)
                return Mock(st_mode=stat.S_IFREG | 0o600, st_uid=1000)
            policy = Mock()
            policy.mount_at.return_value = {'fstype': 'tmpfs'}
            with patch.dict(os.environ, {'DISPLAY': ':0', 'XAUTHORITY': '/var/run/lightdm/vault/xauthority'}), \
                    patch.object(Path, 'lstat', info), patch.object(Path, 'is_symlink', return_value=False), \
                    patch('os.access', return_value=True):
                for target in ('/run', '../run'):
                    with patch('os.readlink', return_value=target):
                        self.assertEqual(_session_x11(policy)['XAUTHORITY'], '/run/lightdm/vault/xauthority')
                for target in ('/tmp/user-run', '../../run', '/run/another-directory'):
                    with patch('os.readlink', return_value=target):
                        with self.assertRaisesRegex(SigningProofError, '^unsafe-guest-x11-runtime-alias$'):
                            _session_x11(policy)
                with patch('os.readlink', return_value='/run'), \
                        patch.object(Path, 'lstat', return_value=Mock(st_mode=stat.S_IFLNK | 0o777, st_uid=1000)):
                    with self.assertRaisesRegex(SigningProofError, '^unsafe-guest-x11-runtime-alias$'):
                        _session_x11(policy)
                os.environ['XAUTHORITY'] = '/var/run//lightdm/vault/xauthority'
                with self.assertRaisesRegex(SigningProofError, '^unexpected-guest-x11-authority$'):
                    _session_x11(policy)
        def test_authority_diagnostic_is_only_public_enum(self):
            output = io.StringIO()
            with patch.dict(os.environ, {'DISPLAY': ':0', 'XAUTHORITY': '/tmp/PRIVATE-NATIVE-SECRET'}), \
                    contextlib.redirect_stdout(output):
                with self.assertRaises(SigningProofError):
                    _session_x11()
            self.assertIn('"authority_class": "other"', output.getvalue())
            self.assertNotIn('PRIVATE', output.getvalue())
            self.assertEqual(_authority_classification(None), 'unset')
            self.assertEqual(_authority_classification(''), 'unset')
            self.assertEqual(_authority_classification('/var/run/lightdm/vault/xauthority'), 'knownvarrun')
        def test_only_actual_local_x11_session_is_accepted(self):
            for display, auth in ((':99', '/run/lightdm/vault/xauthority'),
                                  ('remote-host:0', '/run/lightdm/vault/xauthority'),
                                  (':0', '/tmp/arbitrary-authority')):
                with patch.dict(os.environ, {'DISPLAY': display, 'XAUTHORITY': auth}):
                    with self.assertRaises(SigningProofError):
                        _session_x11()
            def info(path):
                if path == Path('/tmp/.X11-unix/X0'):
                    return Mock(st_mode=stat.S_IFSOCK | 0o777, st_uid=0)
                return Mock(st_mode=stat.S_IFREG | 0o600, st_uid=1000)
            with patch.dict(os.environ, {'DISPLAY': ':0', 'XAUTHORITY': '/run/lightdm/vault/xauthority'}), \
                    patch.object(Path, 'lstat', info), patch.object(Path, 'is_symlink', return_value=False), \
                    patch('os.access', return_value=True):
                self.assertEqual(_session_x11(), {'DISPLAY': ':0', 'XAUTHORITY': '/run/lightdm/vault/xauthority'})
        def test_unset_or_empty_authority_uses_only_verified_known_file(self):
            lightdm, home = Path('/run/lightdm/vault/xauthority'), Path('/home/vault/.Xauthority')
            def info(path):
                if path == lightdm:
                    raise FileNotFoundError
                if path == Path('/tmp/.X11-unix/X0'):
                    return Mock(st_mode=stat.S_IFSOCK | 0o777, st_uid=0)
                return Mock(st_mode=stat.S_IFREG | 0o600, st_uid=1000)
            for supplied in (None, ''):
                environment = {'DISPLAY': ':0'}
                if supplied is not None:
                    environment['XAUTHORITY'] = supplied
                policy = Mock()
                policy.mount_at.return_value = {'fstype': 'tmpfs'}
                with patch.dict(os.environ, environment, clear=True), \
                        patch.object(Path, 'lstat', info), patch.object(Path, 'is_symlink', return_value=False), \
                        patch('os.access', return_value=True):
                    self.assertEqual(_session_x11(policy), {'DISPLAY': ':0', 'XAUTHORITY': str(home)})
                    policy.mount_at.assert_called_once_with(home)
                    policy.mount_at.return_value = {'fstype': 'ext4'}
                    with self.assertRaisesRegex(SigningProofError, '^guest-x11-authority-not-in-ram$'):
                        _session_x11(policy)
        def test_authority_fallback_does_not_accept_redirected_or_unknown_file(self):
            lightdm, home = Path('/run/lightdm/vault/xauthority'), Path('/home/vault/.Xauthority')
            def info(path):
                if path == Path('/tmp/.X11-unix/X0'):
                    return Mock(st_mode=stat.S_IFSOCK | 0o777, st_uid=0)
                if path == lightdm:
                    return Mock(st_mode=stat.S_IFLNK | 0o777, st_uid=1000)
                return Mock(st_mode=stat.S_IFREG | 0o600, st_uid=1000)
            with patch.dict(os.environ, {'DISPLAY': ':0'}, clear=True), \
                    patch.object(Path, 'lstat', info), patch.object(Path, 'is_symlink', return_value=False), \
                    patch('os.access', return_value=True):
                self.assertEqual(_session_x11()['XAUTHORITY'], str(home))
                os.environ['XAUTHORITY'] = str(lightdm)
                with self.assertRaisesRegex(SigningProofError, '^unsafe-guest-x11-authority$'):
                    _session_x11()
                os.environ['XAUTHORITY'] = ' '
                with self.assertRaisesRegex(SigningProofError, '^unexpected-guest-x11-authority$'):
                    _session_x11()
            with patch.dict(os.environ, {'DISPLAY': ':0'}, clear=True), \
                    patch.object(Path, 'lstat', side_effect=FileNotFoundError):
                with self.assertRaisesRegex(SigningProofError, '^unsafe-guest-x11-authority$'):
                    _session_x11()
        def test_startup_capture_is_bounded_classified_and_cleared(self):
            reader, writer = os.pipe()
            capture = _StartupCapture(os.fdopen(reader, 'rb', buffering=0))
            try:
                payload = b'X' * 10000 + b'PRIVATE-FIXTURE-PHRASE qt platform plugin'
                os.write(writer, payload)
                until = time.monotonic() + 2
                while capture.snapshot()[1] < len(payload) and time.monotonic() < until:
                    time.sleep(.001)
                self.assertEqual(capture.snapshot()[1], len(payload))
                self.assertLessEqual(len(capture.snapshot()[0]), 4096)
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    _startup_diagnostics(Path('/nonexistent-fixture'), capture,
                                         'regtest-core-rpc-not-ready', False)
                    with self.assertRaises(SigningProofError):
                        _startup_diagnostics(Path('/nonexistent-fixture'), capture,
                                             'regtest-core-rpc-not-ready', True)
                self.assertIn('qt-platform-error', output.getvalue())
                self.assertNotIn('PRIVATE-FIXTURE-PHRASE', output.getvalue())
                self.assertNotIn('tail_utf8', output.getvalue())
                capture.discard()
                capture._record(b'PRIVATE-WALLET-OUTPUT-AFTER-RESTORE')
                self.assertEqual(capture.snapshot(), (b'', 0, False))
            finally:
                os.close(writer)
                capture.close()
        def test_fixed_public_failure_labels_cover_static_guards(self):
            import ast
            tree = ast.parse(Path(__file__).read_text())
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                        and node.func.id == '_require' and len(node.args) > 1
                        and isinstance(node.args[1], ast.Constant)):
                    self.assertIn(node.args[1].value, PUBLIC_FAILURE_LABELS)
            self.assertNotIn('arbitrary-secret-native-text', PUBLIC_FAILURE_LABELS)
        def test_breadcrumbs_only_allow_fixed_public_fields(self):
            observations, output = [], io.StringIO()
            with contextlib.redirect_stdout(output):
                with patch('time.monotonic', return_value=12.345):
                    _phase('gpg', 'snapshot-verified', 10, observations)
                with self.assertRaises(SigningProofError):
                    _phase('gpg', 'PRIVATE-NATIVE-OUTPUT', 10, observations)
                with self.assertRaises(SigningProofError):
                    _phase('SECRET-PHRASE', 'snapshot-verified', 10, observations)
            self.assertEqual(observations, [{'phase': 'snapshot-verified', 'elapsed_seconds': 2.35}])
            self.assertNotIn('PRIVATE', output.getvalue())
            self.assertNotIn('SECRET', output.getvalue())
            with patch('builtins.print', side_effect=BrokenPipeError):
                _phase('gpg', 'cleanup-start', time.monotonic(), observations)
            self.assertEqual(observations[-1]['phase'], 'cleanup-start')
        def test_passphrase_never_in_command(self):
            phrase = 'Public synthetic dummy test phrase!'
            command = _rpc_command(Path('/ram/node'), Path('/ram/cookie'), 49152, 'walletpassphrase', 'fresh-recovery')
            self.assertNotIn(phrase, command)
            self.assertEqual(command[-2:], ['-stdin', 'walletpassphrase'])
            self.assertNotIn('8332', ' '.join(command))
        def test_broadcast_and_unexpected_wallet_rejected(self):
            with self.assertRaises(SigningProofError):
                _rpc_command(Path('/ram/node'), Path('/ram/cookie'), 49152, 'sendrawtransaction')
            with self.assertRaises(SigningProofError):
                _rpc_command(Path('/ram/node'), Path('/ram/cookie'), 49152, 'walletpassphrase', 'production-wallet')
            for method in ('generatetoaddress', 'testmempoolaccept', 'walletcreatefundedpsbt'):
                with self.assertRaises(SigningProofError):
                    _rpc_command(Path('/ram/node'), Path('/ram/cookie'), 49152, method)
        def test_synthetic_witness_utxo_exact_map(self):
            empty = b'psbt\xff\x01\x00\x01X\x00\x00\x00'
            script = '0014' + 'ab' * 20
            encoded = _supplied_witness_utxo(base64.b64encode(empty).decode('ascii'), script)
            data = base64.b64decode(encoded)
            global_map, position = _map(data, 5)
            input_map, position = _map(data, position)
            output_map, end = _map(data, position)
            self.assertEqual(global_map, {b'\x00': b'X'})
            self.assertEqual(input_map, {b'\x01': (200000000).to_bytes(8, 'little') + b'\x16' + bytes.fromhex(script)})
            self.assertEqual(output_map, {})
            self.assertEqual(end, len(data))
        def test_existing_signature_trailing_maps_and_bad_script_rejected(self):
            global_map = b'psbt\xff\x01\x00\x01X\x00'
            for data, script in ((global_map + b'\x01\x02\x01S\x00\x00', '0014' + 'ab' * 20),
                                 (global_map + b'\x00\x00\x00', '0014' + 'ab' * 20),
                                 (global_map + b'\x00\x00', '0020' + 'ab' * 32),
                                 (global_map[:-1], '0014' + 'ab' * 20)):
                with self.assertRaises(SigningProofError):
                    _supplied_witness_utxo(base64.b64encode(data).decode('ascii'), script)
            with self.assertRaises(SigningProofError):
                _read_compact(b'\xfd\x01\x00', 0)
        def test_deadline_and_parameter_injection_rejected(self):
            with self.assertRaises(SigningProofError):
                _remaining(time.monotonic() - 1)
            with patch('subprocess.run') as run:
                with self.assertRaises(SigningProofError):
                    _rpc(Path('/ram/node'), Path('/ram/cookie'), 49152, time.monotonic() + 2,
                         {}, 'walletpassphrase', 'phrase\nextra', wallet='fresh-recovery')
                run.assert_not_called()
        def test_stderr_and_failed_rpc_not_exposed(self):
            with patch('subprocess.run', return_value=Mock(returncode=1, stdout='SECRET')) as run:
                with self.assertRaisesRegex(SigningProofError, '^regtest-rpc-walletpassphrase-failed$'):
                    _rpc(Path('/ram/node'), Path('/ram/cookie'), 49152, time.monotonic() + 2,
                         {}, 'walletpassphrase', 'Public synthetic phrase', wallet='fresh-recovery')
                self.assertEqual(run.call_args.kwargs['stderr'], subprocess.DEVNULL)
                self.assertNotIn('Public synthetic phrase', run.call_args.args[0])
        def test_reaped_child_never_signalled(self):
            process = Mock()
            process.poll.return_value = 0
            with patch('os.killpg') as kill:
                _stop(process, '1', [], Mock())
                kill.assert_not_called()
                process.wait.assert_called_once()
        def test_changed_child_identity_never_signalled(self):
            process = Mock()
            process.poll.return_value = None
            with patch.dict(globals(), {'_owned': lambda *args: False}), patch('os.killpg') as kill:
                with self.assertRaises(SigningProofError):
                    _stop(process, '1', [], Mock())
                kill.assert_not_called()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(Tests)
    if not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful():
        raise SystemExit(1)


if __name__ == '__main__':
    import sys
    if sys.argv[1:] != ['--self-test']:
        raise SystemExit('This module is a disposable guest test helper; use --self-test for helper checks.')
    _self_test()
