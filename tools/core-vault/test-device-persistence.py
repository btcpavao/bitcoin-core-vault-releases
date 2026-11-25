#!/usr/bin/python3
"""Bounded persistence regression tests; no host settings or disk commands run.

Run in an unprivileged user namespace so fixture ownership is genuinely uid 0:
  unshare --user --map-root-user python3 -B tools/core-vault/test-device-persistence.py
All configuration paths are temporary fixtures. Root/mount identity and the RAM
restore's ownership operations are modeled where noted. Clock and hardware
commands are forbidden. A real installed/live VM remains a separate check.
"""
from concurrent.futures import ThreadPoolExecutor
import importlib
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2] / 'config/includes.chroot'
sys.path.insert(0, str(ROOT / 'usr/lib/core-vault/settings'))
import vault_device_state as state
import vault_input as inputs

LAYOUT = {'model': 'pc105', 'layout': 'hr', 'variant': '', 'options': ''}
POINTER = {'schema': 1, 'devices': {'QA mouse': 0.35}}
INPUT = {'schema': 1, 'keyboard': {'repeat': True, 'delay_ms': 600, 'rate_hz': 30, 'numlock': False},
         'devices': {'QA mouse': {'left_handed': True, 'natural_scroll': True}}}


class DevicePersistenceTests(unittest.TestCase):
    def setUp(self):
        if os.geteuid() != 0:
            self.fail('Run these isolated fixtures with unshare --user --map-root-user.')
        self.temp = tempfile.TemporaryDirectory(prefix='vault-device-state-test-')
        self.root = Path(self.temp.name)
        self.marker = self.root / 'etc/core-vault/installation.json'
        self.cmdline = self.root / 'proc/cmdline'
        self.mountinfo = self.root / 'proc/mountinfo'
        self.store = self.root / 'var/lib/core-vault-device-settings'
        for directory in (self.marker.parent, self.cmdline.parent, self.store.parent):
            directory.mkdir(parents=True)
        for directory in self.root.rglob('*'):
            if directory.is_dir():
                directory.chmod(0o755)
        self.marker.write_text(json.dumps({'schema': 1, 'stage': 'installed-checks-passed',
            'storage': 'persistent-os-with-ram-only-private-home-v1'}))
        self.marker.chmod(0o644)
        self.cmdline.write_text('root=UUID=test-root ro quiet noresume')
        self.mountinfo.write_text('1 0 8:2 / / rw - ext4 /dev/vda2 rw\n')
        self.patches = []
        for name, value in [('MARKER', self.marker), ('CMDLINE', self.cmdline),
                            ('MOUNTINFO', self.mountinfo), ('STATE_DIR', self.store)]:
            self.start(patch.object(state, name, value))
        # Fixture root models /; ancestors outside it are not part of the model.
        original = state._root_directory
        def fixture_parents(path):
            for parent in reversed(Path(path).parents):
                if parent == self.root or self.root in parent.parents:
                    original(parent)
        self.start(patch.object(state, '_protected_parents', side_effect=fixture_parents))
        self.commands = self.start(patch.object(state.subprocess, 'run',
            side_effect=AssertionError('A real host process must never run in these tests.')))

    def start(self, item):
        result = item.start()
        self.patches.append(item)
        return result

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def saved(self):
        return json.loads((self.store / state.STATE_FILE).read_text())['preferences']

    def test_installed_identity_and_live_veto(self):
        self.assertTrue(state.installed_mode())
        self.cmdline.write_text('boot=live root=UUID=test-root')
        self.assertFalse(state.installed_mode())
        self.cmdline.write_text('root=UUID=test-root')
        self.mountinfo.write_text('1 0 0:1 / / rw - overlay overlay rw\n')
        self.assertFalse(state.installed_mode())

    def test_marker_must_be_completed_regular_and_protected(self):
        self.marker.chmod(0o666)
        self.assertFalse(state.installed_mode())
        self.marker.chmod(0o644)
        self.marker.write_text(json.dumps({'schema': 1, 'stage': 'target-configured',
            'storage': 'persistent-os-with-ram-only-private-home-v1'}))
        self.assertFalse(state.installed_mode())
        target = self.marker.with_suffix('.real')
        self.marker.rename(target); self.marker.symlink_to(target)
        self.assertFalse(state.installed_mode())

    def test_live_saves_never_call_privilege_helper_or_write_store(self):
        self.cmdline.write_text('boot=live')
        self.assertFalse(state.persist_component('layout', LAYOUT))
        with self.assertRaises(state.DeviceStateError):
            state.save_component('layout', LAYOUT)
        self.assertFalse(self.store.exists())
        self.commands.assert_not_called()

    def test_only_allowlisted_typed_values_can_be_stored(self):
        bad = [('wallet', '/home/vault/.bitcoin/wallets/test/wallet.dat'),
               ('timezone', '../etc/shadow'), ('timezone', {'timestamp': 123}),
               ('layout', {**LAYOUT, 'command': 'touch /tmp/private'}),
               ('input', {**INPUT, 'password': 'never-store'}),
               ('pointer', {'schema': 1, 'devices': {'QA mouse': float('nan')}}),
               (['timezone'], 'Europe/Zagreb')]
        for component, value in bad:
            with self.subTest(component=component), self.assertRaises((ValueError, TypeError)):
                state.save_component(component, value)
        self.assertFalse(self.store.exists())

    def test_locked_updates_preserve_other_components_and_private_modes(self):
        with ThreadPoolExecutor(max_workers=3) as workers:
            results = [workers.submit(state.save_component, name, value)
                       for name, value in [('layout', LAYOUT), ('pointer', POINTER),
                                           ('timezone', 'Europe/Zagreb')]]
            for result in results:
                self.assertTrue(result.result(timeout=10))
        self.assertEqual(self.saved(), {'layout': LAYOUT, 'pointer': POINTER, 'timezone': 'Europe/Zagreb'})
        self.assertEqual(self.store.stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.store / state.STATE_FILE).stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.store / state.STATE_FILE).stat().st_uid, 0)

    def test_state_and_lock_symlinks_never_replace_their_target(self):
        self.store.mkdir(mode=0o700)
        target = self.root / 'sentinel'
        target.write_text('preserve-this-file')
        for name in (state.STATE_FILE, '.lock'):
            with self.subTest(name=name):
                path = self.store / name
                path.unlink(missing_ok=True); path.symlink_to(target)
                with self.assertRaises((ValueError, OSError)):
                    state.save_component('timezone', 'Europe/Zagreb')
                self.assertEqual(target.read_text(), 'preserve-this-file')
                path.unlink()
        self.assertFalse((self.store / state.STATE_FILE).exists())

    def test_corrupt_existing_state_is_not_silently_replaced(self):
        state.save_component('timezone', 'Europe/Zagreb')
        path = self.store / state.STATE_FILE
        raw = '{"schema":1,"preferences":{"wallet":"private"}}'
        path.write_text(raw); path.chmod(0o600)
        with self.assertRaises(ValueError):
            state.save_component('layout', LAYOUT)
        self.assertEqual(path.read_text(), raw)

    def test_boot_restore_only_maps_typed_device_files_and_timezone(self):
        for name, value in [('layout', LAYOUT), ('input', INPUT), ('pointer', POINTER),
                            ('timezone', 'Europe/Zagreb')]:
            state.save_component(name, value)
        time_api = SimpleNamespace(apply_timezone_only=unittest.mock.Mock(),
                                   zone_file=importlib.import_module('vault_time').zone_file)
        with patch.object(state.pwd, 'getpwnam', return_value=SimpleNamespace(
                pw_uid=1000, pw_gid=1000, pw_dir='/home/vault')), \
             patch.object(state, '_restore_ram_file') as restore, \
             patch.dict(sys.modules, {'vault_time': time_api}):
            self.assertTrue(state.restore_at_boot())
        self.assertEqual(restore.call_args_list, [
            unittest.mock.call('.config/bitcoin-core-vault/keyboard-layout.json', LAYOUT),
            unittest.mock.call('.config/bitcoin-core-vault/input.json', INPUT),
            unittest.mock.call('.config/bitcoin-core-vault/pointer.json', POINTER)])
        time_api.apply_timezone_only.assert_called_once_with('Europe/Zagreb')
        self.commands.assert_not_called()

    def test_live_boot_does_not_restore_installed_preferences(self):
        state.save_component('timezone', 'Europe/Zagreb')
        self.cmdline.write_text('boot=live')
        with patch.object(state, '_restore_ram_file') as restore:
            self.assertFalse(state.restore_at_boot())
            restore.assert_not_called()

    def test_ram_restore_rejects_redirected_directory_and_disk_fallback(self):
        home = self.root / 'ram-home'
        home.mkdir(mode=0o700)
        outside = self.root / 'outside'
        outside.mkdir(); sentinel = outside / 'wallet.dat'; sentinel.write_text('private')
        (home / '.config').symlink_to(outside, target_is_directory=True)
        real_fstat = os.fstat
        def ram_owner(fd):
            info = real_fstat(fd)
            return SimpleNamespace(st_uid=1000, st_mode=info.st_mode, st_nlink=info.st_nlink)
        with patch.object(state, 'RAM_HOME', home), patch.object(state.os, 'fstat', side_effect=ram_owner), \
             patch.object(state, '_filesystem_type', return_value='tmpfs'):
            with self.assertRaises(OSError):
                state._restore_ram_file('.config/bitcoin-core-vault/input.json', INPUT)
        self.assertEqual(sentinel.read_text(), 'private')
        with patch.object(state, 'RAM_HOME', home), \
             patch.object(state, '_filesystem_type', return_value='ext4'):
            with self.assertRaises(state.DeviceStateError):
                state._restore_ram_file('.config/bitcoin-core-vault/input.json', INPUT)
        self.assertEqual(list(outside.iterdir()), [sentinel])

    def test_request_rejects_duplicate_keys_unknown_fields_and_oversize(self):
        bad = [b'{"schema":1,"schema":1,"component":"timezone","value":"UTC"}',
               b'{"schema":1,"component":"timezone","value":"UTC","path":"/etc/shadow"}',
               b'x' * (state.LIMIT + 1)]
        for raw in bad:
            with self.subTest(size=len(raw)), self.assertRaises(ValueError):
                state.read_request(io.BytesIO(raw))

    def test_component_size_limits_match_ram_loaders(self):
        names = [('é' * 198) + str(i).zfill(2) for i in range(32)]
        large_pointer = {'schema': 1, 'devices': {name: 0.25 for name in names}}
        large_input = {'schema': 1, 'keyboard': INPUT['keyboard'],
                       'devices': {name: {'left_handed': True} for name in names}}
        for name, value in [('pointer', large_pointer), ('input', large_input)]:
            with self.subTest(name=name), self.assertRaises(state.DeviceStateError):
                state.save_component(name, value)
        self.assertFalse(self.store.exists())
        self.assertEqual(state.validate_component('pointer', POINTER), POINTER)
        self.assertEqual(state.validate_component('input', INPUT), INPUT)

    def test_zone_names_match_the_boot_restore_validator(self):
        for name in ['localtime', 'posixrules', 'right/Europe/Zagreb',
                     'posix/Europe/Zagreb', '../Europe/Zagreb', '/etc/localtime']:
            with self.subTest(name=name), self.assertRaises(ValueError):
                state.save_component('timezone', name)
        self.assertFalse(self.store.exists())
        for name in ['Europe/Zagreb', 'Etc/UTC']:
            self.assertEqual(state.validate_component('timezone', name), name)

    def test_save_failure_does_not_claim_rolled_back_display_is_applied(self):
        with patch.object(state.subprocess, 'run', return_value=SimpleNamespace(
                returncode=1, stdout='', stderr='unavailable')):
            with self.assertRaises(state.DeviceStateError) as caught:
                state.persist_component('display', None)
        self.assertNotIn('applied', str(caught.exception).lower())
        self.assertIn('could not be saved', str(caught.exception))

    def test_display_clear_removes_only_display_component(self):
        # Display None is the explicit rollback-to-no-saved-display operation.
        state.save_component('timezone', 'Europe/Zagreb')
        state.save_component('layout', LAYOUT)
        state.save_component('display', None)
        self.assertEqual(self.saved(), {'timezone': 'Europe/Zagreb', 'layout': LAYOUT})


if __name__ == '__main__':
    unittest.main(verbosity=2)
