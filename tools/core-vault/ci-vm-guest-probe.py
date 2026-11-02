#!/usr/bin/python3
"""Synthetic acceptance inside an explicitly designated, disposable QEMU guest.

Run with --user-workflow from the normal Vault terminal. The virtual USB must
already be mounted by the desktop; this probe never mounts a device, changes
production files, overlays runtime code, or powers off the guest. The optional
root wrapper requires --diagnostic-root-wrapper and only invokes runuser.

Core runs with the installed production launcher and its offline mainnet
configuration. A separate offline mainnet test node signs a supplied synthetic
witnessUTXO PSBT with freshly restored fixture wallets; this proves no funding,
blockchain confirmation, mempool acceptance or broadcast. Genuine GUI dialogs,
actual Finish destruction, cold reset and disk scans are separate checks.
All wallets, passphrases and exported data here are fixtures.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pwd
import re
import resource
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import Mock
import uuid

TARGET_SERIAL = 'CV_RAM_TEST_INTERNAL'
USB_SERIAL = 'CV_RAM_TEST_USB'
TIMEOUT_SECONDS = 1200
# Public, disposable test phrases. Never use these for a real wallet or backup.
WALLET_PHRASE = 'Synthetic disposable VM wallet passphrase 2026!'
EXPORT_PHRASES = {
    '7z': 'Synthetic disposable VM 7z passphrase 2026!',
    'gpg': 'Synthetic disposable VM GPG passphrase 2026!',
}
REPORT = {}
PREFLIGHT = {}
WORKFLOW_CLOCK = None
SIGNING_HELPER = None
DIAGNOSTIC_RUNTIME = None
sys.dont_write_bytecode = True


class ProbeFailure(Exception):
    """A fixed test label, without backend output or secret values."""


class ProbeDeadline(BaseException):
    """Bypass production UI error handling when the global deadline expires."""


def require(condition, label):
    if not condition:
        raise ProbeFailure(label)


def checked_path(value):
    path = Path(os.path.abspath(value))
    require(not any(ord(c) < 32 or ord(c) == 127 for c in str(path)), 'unsafe-path')
    for component in (path, *path.parents):
        require(not component.is_symlink(), 'symlinked-path')
    return path


def rows(tree):
    for row in tree:
        yield row
        yield from rows(row.get('children', []))


def command_json(arguments):
    result = subprocess.run(arguments, capture_output=True, text=True, timeout=15)
    require(result.returncode == 0, 'attestation-command-failed')
    return json.loads(result.stdout)


def public_usb_metadata(blocks):
    """Bounded sysfs identity fields, only called after the QEMU DMI guard."""
    observations = []
    for row in blocks[:64]:
        if row.get('type') != 'disk':
            continue
        name = Path(str(row.get('path', ''))).name
        if not re.fullmatch(r'(?:sd[a-z]+|vd[a-z]+|nvme\d+n\d+)', name):
            continue
        try:
            bus_path = (Path('/sys/class/block') / name).resolve(strict=True)
            if not bus_path.is_relative_to('/sys/devices') or not any(re.fullmatch(r'usb\d+', part) for part in bus_path.parts):
                continue
            entry = {'path': str(row['path'])[:256], 'sysfs_bus_path': str(bus_path)[:512]}
            for ancestor in (bus_path, *bus_path.parents):
                if not ancestor.is_relative_to('/sys/devices'):
                    break
                if (ancestor / 'idVendor').is_file() and (ancestor / 'idProduct').is_file():
                    entry['usb_ancestor'] = str(ancestor)[:512]
                    for field in ('serial', 'idVendor', 'idProduct'):
                        metadata = ancestor / field
                        if metadata.is_file():
                            with metadata.open(errors='replace') as stream:
                                entry[field] = stream.read(256).strip()
                    break
            observations.append(entry)
        except OSError:
            observations.append({'path': str(row.get('path', ''))[:256], 'sysfs_metadata': 'unavailable'})
    return observations


def machine_guard(phase, firmware):
    require(Path('/sys/class/dmi/id/sys_vendor').read_text().strip() == 'QEMU', 'not-designated-qemu')
    # No block inventory or USB sysfs reads occur on a non-QEMU machine.
    PREFLIGHT.update(uid=os.getuid(), euid=os.geteuid(), sys_vendor='QEMU',
                     efi=Path('/sys/firmware/efi').is_dir(),
                     network_interfaces=sorted(p.name[:64] for p in Path('/sys/class/net').iterdir())[:64])
    require(PREFLIGHT['efi'] == (firmware == 'uefi'), 'firmware-does-not-match')
    installed = Path('/etc/core-vault/installation.json').is_file()
    PREFLIGHT['installed_marker'] = installed
    require(installed == (phase == 'installed'), 'boot-phase-does-not-match')
    require({p.name for p in Path('/sys/class/net').iterdir()} == {'lo'}, 'guest-has-network-device')
    data = command_json(['/usr/bin/lsblk', '-J', '--tree=PATH', '-o', 'PATH,TYPE,SERIAL,MAJ:MIN,MOUNTPOINTS'])
    blocks = list(rows(data['blockdevices']))
    PREFLIGHT['block_devices'] = [{key: (None if row.get(key) is None else str(row[key])[:256])
                                  for key in ('path', 'type', 'serial', 'maj:min')} for row in blocks[:64]]
    PREFLIGHT['block_inventory_truncated'] = len(blocks) > 64
    PREFLIGHT['usb_sysfs'] = public_usb_metadata(blocks)
    targets = [r for r in rows(data['blockdevices']) if r.get('serial') == TARGET_SERIAL and r.get('type') == 'disk']
    fixtures = [r for r in rows(data['blockdevices']) if r.get('serial') == USB_SERIAL and r.get('type') == 'disk']
    require(len(targets) == len(fixtures) == 1, 'designated-disk-serials-missing-or-ambiguous')
    require(targets[0]['maj:min'] != fixtures[0]['maj:min'], 'fixture-is-internal-target')
    account = pwd.getpwnam('vault')
    require((account.pw_uid, account.pw_gid, account.pw_dir) == (1000, 1000, '/home/vault'), 'unexpected-vault-account')
    return targets[0], fixtures[0]


def fixture_mount(fixture, requested):
    require(PREFLIGHT.get('sys_vendor') == 'QEMU', 'fixture-metadata-requires-designated-qemu')
    identities = {r['maj:min'] for r in rows([fixture])}
    mounts = command_json(['/usr/bin/findmnt', '-J', '-l', '-o', 'TARGET,SOURCE,FSTYPE,MAJ:MIN,OPTIONS'])
    observation = {'fixture_identities': sorted(str(value)[:64] for value in identities)[:64],
                   'findmnt_top_keys': (sorted(str(key)[:64] for key in mounts)[:32]
                                         if isinstance(mounts, dict) else []),
                   'fixture_child_count': len(fixture.get('children', []))}
    PREFLIGHT['fixture_mount'] = observation
    require(isinstance(mounts, dict) and isinstance(mounts.get('filesystems'), list), 'invalid-fixture-mount-metadata')
    mount_rows = mounts['filesystems']
    observation['findmnt_row_count'] = len(mount_rows)
    observation['first_row_keys'] = (sorted(str(key)[:64] for key in mount_rows[0])[:32]
                                     if mount_rows and isinstance(mount_rows[0], dict) else [])
    require(all(isinstance(row, dict) for row in mount_rows), 'invalid-fixture-mount-row')
    # Aliases are observations only. Selection below still uses exactly
    # findmnt's canonical "maj:min" key, with no identity normalization.
    aliases = {'target': ('target', 'TARGET'), 'source': ('source', 'SOURCE'),
               'fstype': ('fstype', 'FSTYPE'), 'options': ('options', 'OPTIONS'),
               'maj:min': ('maj:min', 'maj_min', 'maj-min', 'majmin', 'MAJ:MIN')}
    def public_mount(row):
        values = {}
        for field, names in aliases.items():
            value = next((row[name] for name in names if name in row), None)
            values[field] = None if value is None else str(value)[:512]
        values['identity_key_names'] = [name for name in aliases['maj:min'] if name in row]
        return values
    alias_matches = [row for row in mount_rows if any(row.get(name) in identities for name in aliases['maj:min'])]
    observation['observed_alias_match_count'] = len(alias_matches)
    observation['observed_matching_mounts'] = [public_mount(row) for row in alias_matches[:64]]
    # PATH-only lsblk output may be flat. Record its observed disk/partition
    # family for diagnosis; these identities NEVER enter the selection set.
    fixture_path = str(fixture.get('path', ''))
    partition_suffix = r'p\d+' if fixture_path[-1:].isdigit() else r'\d+'
    family_pattern = re.compile(re.escape(fixture_path) + '(?:' + partition_suffix + ')?')
    family = [row for row in PREFLIGHT.get('block_devices', [])
              if isinstance(row.get('path'), str) and family_pattern.fullmatch(row['path'])]
    family_identities = {row.get('maj:min') for row in family if row.get('maj:min') is not None}
    family_mounts = [row for row in mount_rows
                     if any(row.get(name) in family_identities for name in aliases['maj:min'])]
    observation['diagnostic_block_family_identities'] = sorted(family_identities)[:64]
    observation['diagnostic_block_family_mount_count'] = len(family_mounts)
    observation['diagnostic_block_family_mounts'] = [public_mount(row) for row in family_mounts[:64]]
    candidates = [r for r in mounts['filesystems'] if r.get('maj:min') in identities]
    observation['canonical_candidate_count'] = len(candidates)
    if requested is not None:
        media = checked_path(requested)
        candidates = [r for r in candidates if r.get('target') == str(media)]
    observation['selected_candidate_count'] = len(candidates)
    observation['selected_matching_mounts'] = [public_mount(row) for row in candidates[:64]]
    require(len(candidates) == 1, 'fixture-is-not-mounted-uniquely')
    mount = candidates[0]
    media = checked_path(mount['target'])
    require(media.is_dir() and media != Path('/'), 'unsafe-fixture-mountpoint')
    require(not any(media.is_relative_to(p) for p in (Path('/run/core-vault'), Path('/home/vault'))), 'fixture-mount-is-inside-private-ram')
    require(mount['fstype'] == 'vfat', 'fixture-is-not-fat32')
    require('rw' in mount['options'].split(','), 'fixture-is-read-only')
    require(os.access(media, os.R_OK | os.W_OK | os.X_OK), 'fixture-is-not-writable')
    return media, {k: mount[k] for k in ('target', 'source', 'fstype', 'maj:min')}


def output_path(media, supplied, firmware, phase):
    path = checked_path(supplied or media / f'{firmware}-{phase}-result.json')
    require(path.parent == media and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*\.json', path.name), 'result-must-be-directly-on-fixture')
    require(not os.path.lexists(path), 'result-already-exists')
    return path


def passed(label, **facts):
    REPORT['checks'].append(dict(check=label, status='PASS', **facts))
    print('[PASS] ' + label, flush=True)


def stage_progress(label):
    """Bounded fixed-label timings; never include wallet names or phrases."""
    global WORKFLOW_CLOCK
    require(re.fullmatch(
        r'(?:workflow-(?:start|complete)|helpers-attested|policy-(?:start|complete)|'
        r'core-(?:launch-start|ready)|format-(?:7z|gpg)-(?:wallet-create-start|wallet-created|'
        r'plain-start|plain-complete|core-encrypted-start|core-encrypted-complete|negative-checks-start|complete)|'
        r'signing-(?:start|complete|(?:7z|gpg)-(?:start|complete))|'
        r'finish-(?:start|complete|wrong-passphrase-start|wrong-passphrase-session-kept|verified-start|core-stopped))', label),
        'invalid-public-stage-label')
    now = time.monotonic()
    if WORKFLOW_CLOCK is None:
        WORKFLOW_CLOCK = [now, now]
    progress = REPORT.setdefault('stage_progress', [])
    if len(progress) >= 64:
        REPORT['stage_progress_truncated'] = True
        return
    entry = {'stage': label, 'elapsed_seconds': round(now - WORKFLOW_CLOCK[0], 3),
             'since_previous_seconds': round(now - WORKFLOW_CLOCK[1], 3)}
    WORKFLOW_CLOCK[1] = now
    progress.append(entry)
    print('VAULT_CI_STAGE=' + json.dumps(entry, separators=(',', ':')), flush=True)


def file_hash(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def signing_helper(media):
    global SIGNING_HELPER
    require(checked_path(__file__).parent == media, 'probe-is-not-on-verified-fixture')
    path = checked_path(media / 'ci-helper-sha256.json')
    require(path.is_file() and path.stat().st_size <= 16384, 'test-helper-manifest-missing-or-oversized')
    manifest = json.loads(path.read_text())
    require(isinstance(manifest, dict) and set(manifest) == {'schema', 'helpers'} and
            type(manifest['schema']) is int and manifest['schema'] == 1, 'invalid-test-helper-manifest')
    hashes = manifest['helpers']
    names = {'ci-vm-guest-probe.py', 'ci-vm-psbt.py'}
    require(isinstance(hashes, dict) and set(hashes) == names and
            all(isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) for value in hashes.values()),
            'invalid-test-helper-hash-set')
    for name in sorted(names):
        actual = checked_path(media / name)
        require(actual.is_file() and file_hash(actual) == hashes[name], 'copied-test-helper-hash-mismatch')
    REPORT['helper_sha256'] = hashes
    passed('copied-test-helper-hashes-match-controller-manifest')
    helper_path = checked_path(media / 'ci-vm-psbt.py')
    spec = importlib.util.spec_from_file_location('core_vault_ci_psbt', helper_path)
    require(spec is not None and spec.loader is not None, 'test-signing-helper-cannot-load')
    helper = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = helper
    spec.loader.exec_module(helper)
    require(Path(helper.__file__) == helper_path, 'unexpected-test-signing-helper-module')
    SIGNING_HELPER = helper
    return helper


def safe_failure_label(error):
    if isinstance(error, (ProbeFailure, ProbeDeadline)):
        return error.args[0]
    helper = SIGNING_HELPER
    labels = getattr(helper, 'PUBLIC_FAILURE_LABELS', None) if helper is not None else None
    if (helper is not None and type(error) is getattr(helper, 'SigningProofError', None) and
            isinstance(labels, frozenset) and 1 <= len(labels) <= 160 and
            all(isinstance(label, str) and re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', label) for label in labels) and
            len(error.args) == 1 and isinstance(error.args[0], str) and error.args[0] in labels):
        return error.args[0]
    return type(error).__name__


def sanitize_observer_log(payload):
    known = {
        'SYNC HIDE: bounded observation; no global input.': 'bounded-observation-started',
        'SYNC HIDE: native Return addressed once to verified Core window.': 'native-action-addressed',
        'SYNC HIDE: native panel disappearance verified; helper finished.': 'panel-disappearance-verified',
        'SYNC HIDE: one action sent; disappearance unconfirmed; no retry.': 'action-sent-unconfirmed',
        'SYNC HIDE: startup observation expired; no input sent.': 'observation-expired',
    }
    error_types = {'OSError', 'RuntimeError', 'ValueError', 'SubprocessError', 'TimeoutExpired', 'CalledProcessError',
                   'FileNotFoundError', 'PermissionError', 'ProcessLookupError', 'BrokenPipeError',
                   'NotADirectoryError', 'IsADirectoryError', 'InterruptedError', 'BlockingIOError',
                   'ChildProcessError', 'TimeoutError', 'ConnectionError', 'ConnectionResetError',
                   'ConnectionAbortedError', 'ConnectionRefusedError', 'UnicodeError', 'UnicodeDecodeError',
                   'UnicodeEncodeError', 'UnicodeTranslateError'}
    events, unknown, count = [], 0, 0
    for line in payload.decode('utf-8', errors='replace').splitlines():
        event = {'event': known[line]} if line in known else None
        unavailable = re.fullmatch(r'SYNC HIDE: unavailable \(([A-Za-z]{1,40})\); helper finished\.', line)
        if unavailable and unavailable[1] in error_types:
            event = {'event': 'unavailable', 'error_type': unavailable[1]}
        if event is None:
            unknown += 1
        else:
            count += 1
            if len(events) < 32:
                events.append(event)
    return {'events': events, 'known_event_count': count, 'unknown_line_count': unknown,
            'events_truncated': count > len(events)}


def startup_observer_diagnostics(runtime):
    """Optional enum-only diagnostics; missing/unsafe logs never change outcome."""
    diagnostic = {'status': 'not-collected', 'source': 'fixed-private-ram-startup-observer-log'}
    REPORT['startup_observer_diagnostics'] = diagnostic
    descriptor = None
    try:
        require(PREFLIGHT.get('sys_vendor') == 'QEMU' and os.getuid() == os.geteuid() == 1000 and
                runtime.ROOT == Path('/run/core-vault'), 'observer-diagnostic-scope-unverified')
        path = checked_path('/run/core-vault/state/core-runtime/core-vault-hide-sync.log')
        for parent in (runtime.ROOT / 'state', runtime.ROOT / 'state/core-runtime'):
            info = parent.lstat()
            require(stat.S_ISDIR(info.st_mode) and info.st_uid == 1000 and
                    stat.S_IMODE(info.st_mode) == 0o700, 'observer-parent-is-not-private')
        info = path.lstat()
        require(stat.S_ISREG(info.st_mode) and info.st_uid == 1000 and info.st_nlink == 1 and
                not stat.S_IMODE(info.st_mode) & 0o022 and info.st_size <= 8192, 'observer-log-metadata-is-not-safe')
        private, visible = runtime.mount_at(runtime.ROOT, exact=True), runtime.mount_at(path)
        require(private.get('target') == '/run/core-vault' and private.get('fstype') == 'tmpfs' and
                'noswap' in str(private.get('options', '')).split(',') and
                visible.get('fstype') == 'tmpfs' and visible.get('maj:min') == private.get('maj:min'),
                'observer-log-is-not-on-private-noswap-ram')
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        signature = lambda value: (value.st_dev, value.st_ino, value.st_uid, value.st_mode,
                                   value.st_nlink, value.st_size, value.st_mtime_ns)
        require(signature(os.fstat(descriptor)) == signature(info), 'observer-log-changed-before-read')
        payload = os.read(descriptor, 8193)
        require(len(payload) == info.st_size and len(payload) <= 8192 and
                signature(os.fstat(descriptor)) == signature(info) and signature(path.lstat()) == signature(info),
                'observer-log-changed-during-read')
        diagnostic.update(status='sanitized', observed_bytes=len(payload), **sanitize_observer_log(payload))
    except FileNotFoundError:
        diagnostic['status'] = 'absent'
    except PermissionError:
        diagnostic['status'] = 'unreadable'
    except ProbeFailure:
        diagnostic['status'] = 'unsafe-or-changing-metadata'
    except Exception:
        diagnostic['status'] = 'metadata-unavailable'
    finally:
        if descriptor is not None:
            os.close(descriptor)


def production_modules():
    sys.path.insert(0, '/usr/lib/core-vault')
    sys.path.insert(1, '/usr/lib/core-vault-backup')
    import runtime
    import export
    import gpg_backend
    for module, expected in ((runtime, '/usr/lib/core-vault/runtime.py'),
                             (export, '/usr/lib/core-vault/export.py'),
                             (gpg_backend, '/usr/lib/core-vault-backup/gpg_backend.py')):
        require(Path(module.__file__) == Path(expected), 'unexpected-runtime-module')
    manifest = json.loads(Path('/etc/core-vault/installer-payload.json').read_text())['files']
    required = ('usr/lib/core-vault/runtime.py', 'usr/lib/core-vault/export.py',
                'usr/lib/core-vault-backup/backup.py', 'usr/lib/core-vault-backup/gpg_backend.py',
                'usr/local/bin/core-vault-bitcoin', 'usr/local/bin/core-vault-finish',
                'usr/local/bin/bitcoin-qt', 'usr/local/bin/bitcoin-cli')
    hashes = {}
    for relative in required:
        path = checked_path('/' + relative)
        require(path.is_file(), 'production-runtime-file-missing')
        hashes[relative] = file_hash(path)
        require(manifest.get(relative) == hashes[relative], 'runtime-differs-from-iso-payload')
    REPORT['runtime_sha256'] = hashes
    return runtime, export, gpg_backend


def storage_mount_observation(runtime, name, exact, observations, mounts):
    """Gather every public mount fact before policy assertions can fail."""
    try:
        mount = runtime.mount_at(Path(name), exact=exact)
        require(isinstance(mount, dict), 'invalid-storage-mount-metadata')
        mounts[name] = mount
        observations[name] = {key: (None if mount.get(key) is None else str(mount[key])[:4096])
                              for key in ('target', 'fstype', 'options', 'maj:min', 'fsroot')}
    except Exception as error:
        observations[name] = {'observation_error': type(error).__name__}


def live_overlay_attestation(runtime, observations, mounts):
    """Accept only Debian live-boot's observed tmpfs-backed root overlay."""
    root = mounts.get('/', {})
    options = str(root.get('options', '')).split(',')
    values = {name: [value.split('=', 1)[1] for value in options if value.startswith(name + '=')]
              for name in ('upperdir', 'workdir', 'lowerdir')}
    proof = REPORT['live_overlay'] = {'status': 'pending', 'observed_root_options': {
        name: [value[:4096] for value in items[:8]] for name, items in values.items()}}
    for name, exact in (('/run/live/overlay', True), ('/run/live/overlay/rw', False),
                        ('/run/live/overlay/work', False)):
        storage_mount_observation(runtime, name, exact, observations, mounts)
    observed_lowers = values['lowerdir'][0].split(':') if len(values['lowerdir']) == 1 else []
    known_lowers = bool(observed_lowers) and len(observed_lowers) <= 8 and all(
        re.fullmatch(r'/run/live/rootfs/[A-Za-z0-9_-][A-Za-z0-9_.-]*/?', name) for name in observed_lowers)
    # Debian may spell the directory with one trailing slash. Normalize only
    # that already-validated form; never accept repeated slashes or traversal.
    lowers = [name[:-1] if name.endswith('/') else name for name in observed_lowers] if known_lowers else []
    if known_lowers:
        for name in lowers:
            storage_mount_observation(runtime, name, True, observations, mounts)
    proof['observed_lower_paths'] = [name[:512] for name in observed_lowers[:8]]
    proof['canonical_lower_paths'] = lowers
    # All requested mount facts are already in REPORT before any assertions.
    require(root.get('target') == '/' and root.get('fstype') == 'overlay' and
            root.get('fsroot') == '/' and 'rw' in options, 'live-root-is-not-known-overlay')
    require(values['upperdir'] == ['/run/live/overlay/rw'] and
            values['workdir'] == ['/run/live/overlay/work'] and known_lowers,
            'live-overlay-provenance-paths-are-not-known')
    base = mounts.get('/run/live/overlay', {})
    require(base.get('target') == '/run/live/overlay' and base.get('fstype') == 'tmpfs' and
            base.get('fsroot') == '/' and 'rw' in str(base.get('options', '')).split(',') and
            isinstance(base.get('maj:min'), str), 'live-overlay-backing-is-not-tmpfs')
    for name in ('/run/live/overlay/rw', '/run/live/overlay/work'):
        path = checked_path(name)
        mount = mounts.get(name, {})
        require(path.is_dir() and mount.get('target') == '/run/live/overlay' and
                mount.get('fstype') == 'tmpfs' and mount.get('maj:min') == base['maj:min'] and
                mount.get('fsroot') == '/', 'live-overlay-writable-branch-is-not-known-tmpfs')
    for name in lowers:
        path = checked_path(name)
        mount = mounts.get(name, {})
        require(path.is_dir() and mount.get('target') == name and mount.get('fstype') == 'squashfs' and
                'ro' in str(mount.get('options', '')).split(',') and
                'rw' not in str(mount.get('options', '')).split(','), 'live-overlay-lower-is-not-readonly-squashfs')
    proof.update(status='passed', writable_branches_tmpfs=True, lower_branches_readonly_squashfs=True,
                 active_swap=False, scope='Root overlay writes use verified tmpfs upper/work branches; '
                                          'this does not claim memory sanitization or an offline whole-disk scan.')
    return root


def policy_attestation(runtime, phase=None):
    # The native GUI helper's public call omits phase; infer it from the same
    # immutable installed marker used by machine_guard, preserving that API.
    installed = Path('/etc/core-vault/installation.json').is_file()
    if phase is None:
        phase = 'installed' if installed else 'live'
    require(phase in ('live', 'installed') and installed == (phase == 'installed'), 'storage-phase-does-not-match')
    require(os.getuid() == os.geteuid() == 1000, 'workflow-is-not-unprivileged-vault')
    expected = {'HOME': '/home/vault', 'TMPDIR': '/run/core-vault/tmp',
                'XDG_CONFIG_HOME': '/home/vault/.config', 'XDG_CACHE_HOME': '/home/vault/.cache',
                'XDG_DATA_HOME': '/home/vault/.local/share', 'XDG_STATE_HOME': '/home/vault/.local/state'}
    require(all(os.environ.get(k) == v for k, v in expected.items()), 'session-environment-is-not-private')
    require(resource.getrlimit(resource.RLIMIT_CORE) == (0, 0), 'inherited-core-dump-limit-is-not-zero')
    observations, mounts = {}, {}
    REPORT['storage'], REPORT['storage_phase'] = observations, phase
    primary = ('/run/core-vault', '/home/vault', '/tmp', '/var/tmp')
    auxiliary = ('/var/log', '/var/spool/cups', '/var/cache/cups')
    for name in ('/', *primary, *auxiliary):
        storage_mount_observation(runtime, name, name == '/' or name in primary or phase == 'installed',
                                  observations, mounts)
    runtime.check_storage()
    runtime.check_core_mounts()
    require(len(Path('/proc/swaps').read_text().splitlines()) == 1, 'swap-is-active')
    root = live_overlay_attestation(runtime, observations, mounts) if phase == 'live' else None
    for name in primary:
        mount = mounts.get(name, {})
        require(mount.get('target') == name and mount.get('fstype') == 'tmpfs' and
                'noswap' in str(mount.get('options', '')).split(','), 'private-or-temporary-directory-is-not-exact-noswap-tmpfs')
    for name in auxiliary:
        mount = mounts.get(name, {})
        if phase == 'installed' or mount.get('fstype') != 'overlay':
            require(mount.get('target') == name and mount.get('fstype') == 'tmpfs' and
                    'noswap' in str(mount.get('options', '')).split(','), 'auxiliary-directory-is-not-exact-noswap-tmpfs')
        else:
            require(mount.get('target') == '/' and mount.get('maj:min') == root['maj:min'] and
                    mount.get('fsroot') == '/' and mount.get('options') == root['options'],
                    'live-auxiliary-directory-is-not-verified-root-overlay')
    passed('actual-unprivileged-storage-swap-and-phase-aware-ram-policy', phase=phase)


def security_check():
    result = subprocess.run(['/usr/local/bin/core-vault-security-check'], capture_output=True, text=True, timeout=30)
    require(result.returncode == 0, 'production-security-check-failed')
    passed('actual-production-security-check')


def start_core(runtime):
    require(not runtime.wallet_files() and not runtime.read_receipts(), 'session-has-existing-wallets-or-receipts')
    try:
        info = runtime.rpc('getnetworkinfo')
    except RuntimeError:
        subprocess.Popen(['/usr/local/bin/core-vault-bitcoin'], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        deadline = time.monotonic() + 60
        while True:
            try:
                info = runtime.rpc('getnetworkinfo')
                break
            except RuntimeError:
                require(time.monotonic() < deadline, 'production-core-rpc-not-ready')
                time.sleep(.25)
    require(info.get('networkactive') is False and info.get('connections') == 0, 'core-is-not-offline')
    require(runtime.rpc('getblockchaininfo').get('chain') == 'main', 'production-core-chain-is-not-mainnet')
    require(runtime.rpc('listwallets') == [], 'core-has-existing-loaded-wallets')
    passed('actual-production-core-launcher-offline-mainnet')


def core_password_command(runtime, wallet, method, phrase):
    args = ['/usr/local/bin/bitcoin-cli', '-datadir=' + str(runtime.CORE), '-rpcport=8332',
            '-rpcwallet=' + wallet, '-stdin', method]
    result = subprocess.run(args, input=phrase + '\n', text=True, capture_output=True, timeout=30)
    require(result.returncode == 0, 'synthetic-core-wallet-encryption-failed')


def expected_rejection(operation, label, error_type=RuntimeError):
    try:
        operation()
    except ProbeFailure:
        raise
    except error_type:
        passed(label)
    else:
        raise ProbeFailure(label + '-was-accepted')


def public_descriptors(runtime, wallet):
    values = runtime.rpc('listdescriptors', 'false', wallet=wallet)['descriptors']
    require(bool(values) and {False, True}.issubset({v.get('internal', False) for v in values}), 'wallet-public-descriptors-missing')
    return sorted((v.get('internal', False), v['desc']) for v in values)


def recover_and_prove(runtime, export, gpg, wallet, archive, receipt, phrase, address, label, encrypted, backup_format):
    restored = wallet + '-restored-' + uuid.uuid4().hex
    restored_directory = runtime.WALLETS / restored
    require(not os.path.lexists(restored_directory), 'restored-wallet-path-already-exists')
    with tempfile.TemporaryDirectory(prefix='ci-vm-restore-', dir=runtime.ROOT / 'export') as temporary:
        raw = Path(temporary) / 'wallet.dat'
        if backup_format == 'gpg':
            require(gpg.decrypt_file(archive, raw, phrase, ram_root=runtime.ROOT / 'export') == 'AES256-OCB', 'restored-gpg-profile-mismatch')
        else:
            code, prompts = export.run7z(['x', '-t7z', '-y', '-o' + temporary, str(archive), 'wallet.dat'], phrase)
            require(code == 0 and prompts > 0, 'actual-usb-7z-recovery-failed')
        require(raw.is_file() and not raw.is_symlink(), 'recovered-wallet-is-not-regular')
        require(runtime.file_digest(raw) == receipt['wallet_backup_sha256'] and
                runtime.wallet_digest(raw) == receipt['wallet_digest'], 'recovered-wallet-byte-or-logical-digest-mismatch')
        try:
            runtime.rpc('restorewallet', restored, raw, 'false')
            require(runtime.rpc('getaddressinfo', address, wallet=restored).get('ismine') is True, 'restored-address-is-not-owned')
            require(address in runtime.rpc('getaddressesbylabel', label, wallet=restored), 'restored-address-label-missing')
            require(public_descriptors(runtime, restored) == public_descriptors(runtime, wallet), 'restored-public-descriptors-differ')
            info = runtime.rpc('getwalletinfo', wallet=restored)
            require(info.get('private_keys_enabled') is True, 'restored-wallet-has-no-private-keys')
            require((info.get('unlocked_until') == 0) if encrypted else ('unlocked_until' not in info), 'restored-core-encryption-state-differs')
        finally:
            if restored in runtime.rpc('listwallets'):
                runtime.rpc('unloadwallet', restored, 'false')
            if restored_directory.exists():
                runtime.check_storage()
                runtime.check_core_mounts()
                require(not restored_directory.is_symlink() and restored_directory.is_dir() and
                        restored_directory.resolve(strict=True) == runtime.WALLETS.resolve(strict=True) / restored and
                        restored_directory.stat().st_uid == 1000 and
                        runtime.mount_at(restored_directory)['maj:min'] == runtime.mount_at(runtime.ROOT, True)['maj:min'],
                        'restored-wallet-cleanup-is-not-private-ram')
                shutil.rmtree(restored_directory)
    passed('actual-usb-' + backup_format + '-restore-' + ('core-encrypted' if encrypted else 'core-unencrypted'),
           exact_snapshot_sha256=True, logical_wallet_digest=True, address_ownership=True,
           address_label=True, public_descriptors=True, core_encryption_state=True)


def format_workflow(runtime, export, gpg, media, backup_format, nonce):
    wallet = 'cv-forensic-ci-' + backup_format + '-' + nonce
    marker = 'CORE_VAULT_FORENSIC_TEST_' + uuid.uuid4().hex
    stage_progress('format-' + backup_format + '-wallet-create-start')
    runtime.rpc('createwallet', wallet)
    address = runtime.rpc('getnewaddress', marker, wallet=wallet)
    phrase = EXPORT_PHRASES[backup_format]
    path = runtime.wallet_files()[wallet]
    stage_progress('format-' + backup_format + '-wallet-created')
    for encrypted in (False, True):
        state_label = 'core-encrypted' if encrypted else 'plain'
        stage_progress('format-' + backup_format + '-' + state_label + '-start')
        if encrypted:
            old = runtime.read_receipts()[wallet]
            core_password_command(runtime, wallet, 'encryptwallet', WALLET_PHRASE)
            require(runtime.current_wallet_digest(wallet, path) != old['wallet_digest'], 'core-encryption-did-not-invalidate-old-receipt')
            passed('core-encryption-invalidates-previous-' + backup_format + '-receipt')
        name = wallet + ('-encrypted' if encrypted else '-plain') + '.' + backup_format
        archive = export.export_wallet(wallet, media / name, phrase, backup_format=backup_format)
        receipt = runtime.read_receipts()[wallet]
        require(export.receipt_format(receipt) == backup_format, 'receipt-format-mismatch')
        require(runtime.current_wallet_digest(wallet, path) == receipt['wallet_digest'], 'current-wallet-does-not-match-receipt')
        export.verify_export(receipt, phrase)
        expected_rejection(lambda: export.verify_export(receipt, 'Different synthetic disposable VM phrase!'),
                           'actual-' + backup_format + '-wrong-passphrase-rejected-' + str(encrypted).lower())
        recover_and_prove(runtime, export, gpg, wallet, archive, receipt, phrase, address, marker, encrypted, backup_format)
        stage_progress('format-' + backup_format + '-' + state_label + '-complete')
    stage_progress('format-' + backup_format + '-negative-checks-start')
    altered_receipt = dict(receipt, wallet_backup_sha256='0' * 64)
    expected_rejection(lambda: export.verify_export(altered_receipt, phrase), 'actual-' + backup_format + '-wrong-snapshot-digest-rejected')
    if backup_format == 'gpg':
        with tempfile.TemporaryDirectory(prefix='ci-vm-gpg-reject-', dir=runtime.ROOT / 'export') as temporary:
            stage = Path(temporary)
            data = archive.read_bytes()
            for suffix, changed in (('truncated', data[:-1]), ('altered', data[:len(data)//2] + bytes([data[len(data)//2] ^ 1]) + data[len(data)//2+1:])):
                bad, output = stage / (suffix + '.gpg'), stage / (suffix + '-plaintext')
                bad.write_bytes(changed)
                expected_rejection(lambda: gpg.decrypt_file(bad, output, phrase, ram_root=runtime.ROOT / 'export'),
                                   'actual-gpg-' + suffix + '-authentication-rejected', gpg.GPGError)
                require(not output.exists(), 'failed-gpg-published-plaintext')
    REPORT['exports'].append({'format': backup_format, 'wallet': wallet, 'marker': marker,
                              'archive': archive.name, 'archive_sha256': receipt['archive_sha256'],
                              'wallet_backup_sha256': receipt['wallet_backup_sha256'],
                              'wallet_digest': receipt['wallet_digest']})
    stage_progress('format-' + backup_format + '-complete')


def signing_proofs(runtime, export, gpg, helper):
    proofs = REPORT['psbt_signing']['proofs']
    true_fields = ('test_only', 'exact_decrypted_snapshot', 'supplied_synthetic_witness_utxo',
                   'control_signed', 'fresh_recovery_signed', 'both_finalized_with_fresh_witness',
                   'core_wallet_encrypted', 'owned_node_reaped', 'qa_wallets_removed',
                   'production_inventory_unchanged', 'original_archive_unchanged')
    false_fields = ('preexisting_signatures', 'blockchain_funding_proven', 'mempool_tested',
                    'broadcast', 'independent_signature_verification')
    hash_fields = ('official_core_sha256', 'archive_sha256', 'snapshot_sha256',
                   'same_unsigned_psbt_sha256', 'control_transaction_sha256',
                   'fresh_recovery_transaction_sha256')
    known = set(true_fields + false_fields + hash_fields + ('backup_format', 'test_platform', 'chain', 'phase_timings'))
    for record in REPORT['exports']:
        wallet, backup_format = record['wallet'], record['format']
        stage_progress('signing-' + backup_format + '-start')
        inventory, receipts = runtime.wallet_files(), runtime.read_receipts()
        require(wallet in inventory and wallet in receipts, 'signing-original-wallet-or-receipt-missing')
        receipt = receipts[wallet]
        require(runtime.current_wallet_digest(wallet, inventory[wallet]) == receipt['wallet_digest'],
                'signing-original-wallet-differs-from-current-receipt')
        proof = helper.prove_restored_signing(runtime, export, gpg, Path(receipt['archive']), receipt,
                                             EXPORT_PHRASES[backup_format], WALLET_PHRASE, backup_format)
        require(isinstance(proof, dict) and set(proof) == known and
                proof['backup_format'] == backup_format and proof['chain'] == 'main' and
                helper.PLATFORM in ('minimal:enable_fonts', 'xcb') and proof['test_platform'] == helper.PLATFORM and
                all(proof[key] is True for key in true_fields) and
                all(proof[key] is False for key in false_fields) and
                all(isinstance(proof[key], str) and re.fullmatch(r'[0-9a-f]{64}', proof[key]) for key in hash_fields),
                'signing-proof-did-not-attest-required-synthetic-scope')
        require(proof['official_core_sha256'] == REPORT['runtime_sha256']['usr/local/bin/bitcoin-qt'] and
                proof['archive_sha256'] == receipt['archive_sha256'] and
                proof['snapshot_sha256'] == receipt['wallet_backup_sha256'], 'signing-proof-source-hash-mismatch')
        timings = proof['phase_timings']
        require(isinstance(timings, list) and 1 <= len(timings) <= 32 and
                all(isinstance(item, dict) and set(item) == {'phase', 'elapsed_seconds'} and
                    item['phase'] in helper.PHASES and type(item['elapsed_seconds']) in (int, float) and
                    0 <= item['elapsed_seconds'] <= TIMEOUT_SECONDS for item in timings) and
                all(first['elapsed_seconds'] <= second['elapsed_seconds'] for first, second in zip(timings, timings[1:])),
                'signing-proof-public-timings-are-invalid')
        runtime.check_storage()
        runtime.check_core_mounts()
        require(runtime.wallet_files() == inventory and runtime.read_receipts() == receipts and
                runtime.current_wallet_digest(wallet, inventory[wallet]) == receipt['wallet_digest'],
                'signing-proof-changed-production-wallets-or-receipts')
        proofs.append(proof)
        stage_progress('signing-' + backup_format + '-complete')
        passed('actual-restored-' + backup_format + '-wallet-signs-supplied-synthetic-utxo-psbt',
               actual_core_signing=True, fresh_recovery=True, synthetic_witness_utxo=True,
               funding_proven=False, mempool_tested=False, broadcast=False,
               independent_signature_verification=False, production_receipts_unchanged=True)
    require(len(proofs) == 2 and {proof['backup_format'] for proof in proofs} == {'7z', 'gpg'},
            'both-restored-backup-formats-have-not-signed')
    REPORT['psbt_signing']['status'] = 'passed'
    REPORT['pending'].remove('recovered-wallet PSBT signing with supplied synthetic witness UTXO')


def finish_controlflow(runtime, export, gpg):
    """Run unchanged production functions; mock UI and the final power request."""
    source = Path('/usr/local/bin/core-vault-finish')
    tree = ast.parse(source.read_text())
    names = ('core_running', 'stop_core', 'main')
    functions = [next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name) for name in names]
    from PySide6.QtGui import QClipboard
    clipboard = Mock()
    clipboard.supportsSelection.return_value = True
    dialog = Mock(return_value=Mock())
    dialog.return_value.exec.return_value = 1
    dialog.Question, dialog.Yes, dialog.No = 0, 1, 2
    requests = []
    missing = Mock(return_value=False)
    wrong = [True]
    verification_events = []

    def tracked_verify(receipt, password):
        backup_format = export.receipt_format(receipt)
        try:
            result = export.verify_export(receipt, password)
        except RuntimeError as error:
            verification_events.append((backup_format, 'gpg-authentication-rejected'
                                        if isinstance(error.__cause__, gpg.GPGError) else 'other-error'))
            raise
        else:
            verification_events.append((backup_format, 'verified'))
            return result

    def prompt(*arguments):
        text = arguments[2]
        records = runtime.read_receipts()
        matching = [r for r in records.values() if text.endswith(str(r['archive']))]
        require(len(matching) == 1, 'finish-prompt-does-not-match-receipt')
        backup_format = export.receipt_format(matching[0])
        return ('Different synthetic disposable VM phrase!' if wrong[0] and backup_format == 'gpg'
                else EXPORT_PHRASES[backup_format]), True

    def power_request(arguments, **options):
        require(arguments == ['/usr/bin/sudo', '-n', '/usr/local/sbin/core-vault-end-session', 'poweroff'] and
                options == {'check': True, 'timeout': 15}, 'unexpected-finish-command')
        requests.append('poweroff-request-intercepted')
        return subprocess.CompletedProcess(arguments, 0)

    def no_launch(*arguments, **options):
        raise ProbeFailure('unexpected-finish-relaunch')

    namespace = dict(os=os, Path=Path, time=time, CORE=runtime.CORE, rpc=runtime.rpc,
                     check_storage=runtime.check_storage, wallet_files=runtime.wallet_files,
                     check_loaded_wallet_coverage=runtime.check_loaded_wallet_coverage,
                     read_receipts=runtime.read_receipts, current_wallet_digest=runtime.current_wallet_digest,
                     wallet_digest=runtime.wallet_digest, verify_export=tracked_verify,
                     receipt_format=export.receipt_format, missing_backup=missing,
                     QInputDialog=SimpleNamespace(getText=prompt), QLineEdit=SimpleNamespace(Password=1),
                     QMessageBox=dialog, QClipboard=QClipboard, args=SimpleNamespace(restart=False),
                     app=SimpleNamespace(clipboard=lambda: clipboard, processEvents=lambda: None),
                     subprocess=SimpleNamespace(run=power_request, Popen=no_launch))
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(source), 'exec'), namespace)
    stage_progress('finish-wrong-passphrase-start')
    namespace['main']()
    require(not requests and missing.call_count == 1 and namespace['core_running']() and
            ('gpg', 'gpg-authentication-rejected') in verification_events and
            all(result != 'other-error' for _, result in verification_events),
            'wrong-passphrase-did-not-retain-session')
    passed('production-finish-rejects-wrong-gpg-passphrase', dialog_mocked=True, actual_decryption=True)
    stage_progress('finish-wrong-passphrase-session-kept')
    wrong[0] = False
    missing.reset_mock()
    verification_events.clear()
    stage_progress('finish-verified-start')
    namespace['main']()
    require(requests == ['poweroff-request-intercepted'] and not missing.called and not namespace['core_running']() and
            sorted(verification_events) == [('7z', 'verified'), ('gpg', 'verified')],
            'verified-finish-did-not-stop-core-and-reach-power-request')
    passed('production-finish-verifies-both-formats-and-final-wallet-flush', dialog_mocked=True,
           actual_decryption=True, actual_core_shutdown=True, final_power_request_intercepted=True)
    stage_progress('finish-core-stopped')


def user_workflow(media, phase, firmware, mount):
    global REPORT, WORKFLOW_CLOCK, DIAGNOSTIC_RUNTIME
    WORKFLOW_CLOCK = None
    REPORT = dict(schema=1, status='RUNNING', phase=phase, firmware=firmware,
                  target_serial=TARGET_SERIAL, fixture_serial=USB_SERIAL, fixture_mount=mount,
                  execution_uid=os.getuid(), checks=[], exports=[], stage_progress=[], timeout_seconds=TIMEOUT_SECONDS,
                  psbt_signing={'status': 'pending', 'proofs': [],
                                'scope': 'Separate offline mainnet Core signs supplied synthetic witnessUTXO PSBTs; '
                                         'no real funding, confirmation, mempool, broadcast or independent signature validation.'},
                  pending=['genuine GUI dialog acceptance', 'actual Finish session destruction',
                           'cold reboot and power-loss RAM reset', 'offline whole-disk marker scan',
                           'recovered-wallet PSBT signing with supplied synthetic witness UTXO'])
    stage_progress('workflow-start')
    helper = signing_helper(media)
    stage_progress('helpers-attested')
    runtime, export, gpg = production_modules()
    DIAGNOSTIC_RUNTIME = runtime
    stage_progress('policy-start')
    policy_attestation(runtime, phase)
    stage_progress('policy-complete')
    os.umask(0o077)
    security_check()
    stage_progress('core-launch-start')
    start_core(runtime)
    stage_progress('core-ready')
    startup_observer_diagnostics(runtime)
    security_check()
    nonce = uuid.uuid4().hex
    for backup_format in ('7z', 'gpg'):
        format_workflow(runtime, export, gpg, media, backup_format, nonce)
    require(len(runtime.wallet_files()) == len(runtime.read_receipts()) == 2, 'unexpected-post-probe-wallet-inventory')
    stage_progress('signing-start')
    signing_proofs(runtime, export, gpg, helper)
    stage_progress('signing-complete')
    stage_progress('finish-start')
    finish_controlflow(runtime, export, gpg)
    stage_progress('finish-complete')
    runtime.check_storage()
    stage_progress('workflow-complete')
    REPORT['status'] = 'passed-covered-checks'
    REPORT['covered'] = [item['check'] for item in REPORT['checks']]
    REPORT['scope'] = ('Production runtime in the actual Live/installed guest; new synthetic wallets; actual USB backup, '
                       'authentication and restore; production Finish verification with mocked dialogs and intercepted power request. '
                       'A separate offline mainnet Core node signs synthetic witnessUTXO PSBTs from restored archives. '
                       'No funding, confirmation, mempool acceptance, broadcast, runtime overlay, device mount or actual session destruction.')
    return REPORT


def diagnostic_environment():
    auth = Path('/run/lightdm/vault/xauthority')
    if not auth.is_file():
        auth = Path('/home/vault/.Xauthority')
    return dict(os.environ, HOME='/home/vault', XDG_RUNTIME_DIR='/run/user/1000',
                XDG_CONFIG_HOME='/home/vault/.config', XDG_CACHE_HOME='/home/vault/.cache',
                XDG_DATA_HOME='/home/vault/.local/share', XDG_STATE_HOME='/home/vault/.local/state',
                TMPDIR='/run/core-vault/tmp', TMP='/run/core-vault/tmp', TEMP='/run/core-vault/tmp',
                HISTFILE='/dev/null', PYTHONDONTWRITEBYTECODE='1', DISPLAY=':0', XAUTHORITY=str(auth))


def write_result(path, result):
    payload = (json.dumps(result, indent=2) + '\n').encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    print('VAULT_CI_VM_RESULT=' + json.dumps(result, separators=(',', ':')), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', required=True, choices=('live', 'installed'))
    parser.add_argument('--firmware', required=True, choices=('bios', 'uefi'))
    parser.add_argument('--media', type=Path)
    parser.add_argument('--output', type=Path)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--user-workflow', action='store_true')
    modes.add_argument('--diagnostic-root-wrapper', action='store_true')
    args = parser.parse_args()
    target, fixture = machine_guard(args.phase, args.firmware)
    media, mount = fixture_mount(fixture, args.media)
    output = output_path(media, args.output, args.firmware, args.phase)
    if args.diagnostic_root_wrapper:
        require(os.getuid() == os.geteuid() == 0, 'diagnostic-wrapper-requires-explicit-guest-root')
        command = ['/usr/sbin/runuser', '-u', 'vault', '--', '/usr/bin/python3',
                   str(checked_path(__file__)), '--user-workflow', '--phase', args.phase,
                   '--firmware', args.firmware, '--media', str(media), '--output', str(output)]
        return subprocess.run(command, env=diagnostic_environment(), timeout=TIMEOUT_SECONDS + 30).returncode
    require(os.getuid() == os.geteuid() == 1000, 'use-normal-vault-terminal')
    def alarm(signum, frame):
        raise ProbeDeadline('guest-probe-deadline-exceeded')
    signal.signal(signal.SIGALRM, alarm)
    signal.alarm(TIMEOUT_SECONDS)
    try:
        result = user_workflow(media, args.phase, args.firmware, mount)
    except BaseException as error:
        if DIAGNOSTIC_RUNTIME is not None:
            try:
                startup_observer_diagnostics(DIAGNOSTIC_RUNTIME)
            except BaseException:
                REPORT['startup_observer_diagnostics'] = {'status': 'diagnostic-interrupted',
                    'source': 'fixed-private-ram-startup-observer-log'}
        result = dict(REPORT)
        result.update(schema=1, status='FAIL', phase=args.phase, firmware=args.firmware,
                      failure=safe_failure_label(error),
                      scope='Probe failed; private session and synthetic originals were not intentionally discarded.')
        write_result(output, result)
        return 1
    finally:
        signal.alarm(0)
    write_result(output, result)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ProbeFailure, OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        observation = {'status': 'FAIL_BEFORE_WORKFLOW', 'failure_type': type(error).__name__,
                       'preflight': PREFLIGHT}
        if isinstance(error, ProbeFailure):
            observation['failure'] = error.args[0]
        print(json.dumps(observation), flush=True)
        raise SystemExit(1)
