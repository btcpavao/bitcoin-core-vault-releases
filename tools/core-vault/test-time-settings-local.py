#!/usr/bin/python3
"""Focused offline time regression tests. All privileged effects are stubbed."""
from contextlib import contextmanager, ExitStack
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'config/includes.chroot/usr/lib/core-vault/settings'))
import vault_time as clock
import vault_device_state as state
import vault_time_ui as ui
from PySide6.QtWidgets import QApplication
APP = QApplication.instance() or QApplication(['vault-time-regression'])
APP.setQuitOnLastWindowClosed(False)

class RootPath(type(Path())):
    def lstat(self):
        values = list(super().lstat()); values[4] = 0
        return os.stat_result(values)

class FixedDate(datetime):
    current = datetime(2026, 11, 24, 8, 12, 57, tzinfo=timezone.utc)
    @classmethod
    def now(cls, tz=None):
        return cls.current.astimezone(tz) if tz is not None else cls.current.replace(tzinfo=None)

@contextmanager
def runtime_fixture(installed):
    with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
        root = RootPath(directory)
        runtime = root/'run-time'; runtime.mkdir(mode=0o755)
        local = root/'localtime'; local.write_bytes(clock.zone_file('Etc/UTC').read_bytes()); local.chmod(0o644)
        namefile = root/'timezone'; namefile.write_text('Etc/UTC\n'); namefile.chmod(0o644)
        def command(argv, **kwargs):
            if argv[:2] == ['/usr/bin/findmnt', '-n']:
                return Mock(stdout='tmpfs\n', returncode=0)
            if argv[:2] == ['/usr/bin/mount', '--bind']:
                return Mock(stdout='', returncode=0)
            raise AssertionError('Unexpected external command: '+repr(argv))
        stack.enter_context(patch.object(clock, 'STATE', runtime))
        stack.enter_context(patch.object(clock, 'LOCALTIME', local))
        stack.enter_context(patch.object(clock, 'TIMEZONE', namefile))
        stack.enter_context(patch.object(clock.os, 'geteuid', return_value=0))
        stack.enter_context(patch.object(clock.subprocess, 'run', side_effect=command))
        stack.enter_context(patch.object(clock.time, 'tzset'))
        system = stack.enter_context(patch.object(clock.time, 'clock_settime'))
        rtc = stack.enter_context(patch.object(clock, '_set_installed_clock', return_value=None))
        stack.enter_context(patch.object(state, 'installed_mode', return_value=installed))
        save = stack.enter_context(patch.object(state, 'save_component'))
        yield runtime, system, rtc, save

@contextmanager
def live_link_fixture(boot_live=True, upper_fstype='tmpfs', etc_fstype='overlay'):
    utc_raw = clock.zone_file('Etc/UTC').read_bytes()
    zagreb_raw = clock.zone_file('Europe/Zagreb').read_bytes()
    with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
        root = RootPath(directory)
        etc = root/'etc'
        zones = root/'zoneinfo'
        live = root/'run/live'
        upper = live/'overlay/rw'
        runtime = root/'run/time'
        for folder in (etc, zones, zones/'Etc', zones/'Europe', live,
                       live/'overlay', upper, runtime):
            folder.mkdir(parents=True, exist_ok=True)
            folder.chmod(0o755)
        utc = zones/'Etc/UTC'; utc.write_bytes(utc_raw); utc.chmod(0o644)
        zagreb = zones/'Europe/Zagreb'; zagreb.write_bytes(zagreb_raw); zagreb.chmod(0o644)
        local = etc/'localtime'; local.symlink_to(utc)
        namefile = etc/'timezone'; namefile.write_text('Etc/UTC\n'); namefile.chmod(0o644)
        cmdline = root/'cmdline'
        cmdline.write_text('boot=live components quiet\n' if boot_live else 'root=UUID=installed quiet\n')
        def command(argv, **kwargs):
            if argv == ['/usr/bin/findmnt', '--json', '-o', 'FSTYPE,OPTIONS', '-T', str(etc)]:
                return Mock(stdout=json.dumps({'filesystems':[{
                    'fstype':etc_fstype,
                    'options':'rw,lowerdir=/run/live/rootfs/filesystem.squashfs,upperdir='+str(upper)
                }]}), returncode=0)
            if argv == ['/usr/bin/findmnt', '-n', '-o', 'FSTYPE', '-T', str(upper)]:
                return Mock(stdout=upper_fstype+'\n', returncode=0)
            if argv == ['/usr/bin/findmnt', '-n', '-o', 'FSTYPE', '-T', str(runtime)]:
                return Mock(stdout='tmpfs\n', returncode=0)
            if (argv[:2] == ['/usr/bin/mount', '--bind']
                    and argv[2:] in [[str(runtime/'localtime'),str(local)],
                                     [str(runtime/'zone'),str(namefile)]]):
                return Mock(stdout='', returncode=0)
            raise AssertionError('Unexpected external command: '+repr(argv))
        for name, value in [('STATE',runtime), ('LOCALTIME',local), ('TIMEZONE',namefile),
                            ('ZONE_ROOT',zones), ('CMDLINE',cmdline), ('LIVE_ROOT',live),
                            ('Path',RootPath)]:
            stack.enter_context(patch.object(clock, name, value))
        stack.enter_context(patch.object(clock.os, 'geteuid', return_value=0))
        run = stack.enter_context(patch.object(clock.subprocess, 'run', side_effect=command))
        stack.enter_context(patch.object(clock.time, 'tzset'))
        system = stack.enter_context(patch.object(clock.time, 'clock_settime'))
        rtc = stack.enter_context(patch.object(clock, '_set_installed_clock'))
        stack.enter_context(patch.object(state, 'installed_mode', return_value=not boot_live))
        save = stack.enter_context(patch.object(state, 'save_component'))
        yield {'root':root, 'local':local, 'utc':utc, 'utc_raw':utc_raw,
               'runtime':runtime, 'system':system, 'rtc':rtc, 'save':save, 'run':run}


class Signal:
    def __init__(self): self.listeners=[]
    def connect(self, fn): self.listeners.append(fn)
    def emit(self, *args):
        for fn in self.listeners: fn(*args)

class InlineJob:
    def __init__(self, operation, parent=None):
        self.operation=operation
        self.success=Signal();self.failure=Signal();self.finished=Signal()
    def start(self):
        try: self.success.emit(self.operation())
        except (ValueError, RuntimeError) as error: self.failure.emit(str(error))
        finally:self.finished.emit()
    def deleteLater(self): pass

@contextmanager
def dialog_fixture():
    with patch.object(ui, 'installed_mode', return_value=False), \
            patch.object(ui, 'snapshot', return_value={'timezone':'Etc/UTC','automatic':False}), \
            patch.object(ui, 'datetime', FixedDate):
        dialog=ui.VaultDateTimeDialog()
        try: yield dialog
        finally: dialog.reject();dialog.deleteLater();APP.processEvents()

class TimeSettingsRegression(unittest.TestCase):
    def test_timezone_only_request_and_winter_summer_offsets(self):
        self.assertEqual(clock.validate_request({'timezone':'Europe/Zagreb','local_time':None}),
                         ('Europe/Zagreb',None))
        for month,expected in [(11,7),(7,6)]:
            _, epoch=clock.validate_request({'timezone':'Europe/Zagreb',
                'local_time':f'2026-{month:02d}-24 08:12:57'})
            self.assertEqual(datetime.fromtimestamp(epoch,timezone.utc).hour, expected)

    def test_invalid_or_ambiguous_manual_input_rejected(self):
        for request in [
            {'timezone':'../etc/passwd','local_time':None},
            {'timezone':'Etc/UTC','local_time':False},
            {'timezone':'Etc/UTC','local_time':None,'automatic':True},
            {'timezone':'Europe/Zagreb','local_time':'2026-10-25 02:30:00'},
            {'timezone':'Europe/Zagreb','local_time':'2026-03-29 02:30:00'}]:
            with self.subTest(request=request),self.assertRaises(clock.TimeError):
                clock.validate_request(request)

    def test_installed_timezone_only_never_sets_clock_or_rtc(self):
        with runtime_fixture(True) as (runtime,system,rtc,save):
            result=clock.apply_settings({'timezone':'Europe/Zagreb','local_time':None})
            system.assert_not_called();rtc.assert_not_called()
            save.assert_called_once_with('timezone','Europe/Zagreb')
            self.assertEqual((runtime/'zone').read_text(),'Europe/Zagreb\n')
            self.assertEqual((runtime/'localtime').read_bytes(),clock.zone_file('Europe/Zagreb').read_bytes())
            self.assertFalse(result['clock_changed'])

    def test_live_manual_clock_never_persists_or_writes_rtc(self):
        request={'timezone':'Europe/Zagreb','local_time':'2026-11-24 14:00:00'}
        with runtime_fixture(False) as (_,system,rtc,save):
            result=clock.apply_settings(request)
            system.assert_called_once_with(clock.time.CLOCK_REALTIME,clock.validate_request(request)[1])
            rtc.assert_not_called();save.assert_not_called()
            self.assertFalse(result['persistent']);self.assertFalse(result['rtc_saved'])

    def test_installed_manual_clock_saves_only_zone_and_updates_rtc(self):
        request={'timezone':'Europe/Zagreb','local_time':'2026-11-24 14:00:00'}
        with runtime_fixture(True) as (_,system,rtc,save):
            result=clock.apply_settings(request)
            system.assert_not_called()
            rtc.assert_called_once_with(clock.validate_request(request)[1])
            save.assert_called_once_with('timezone','Europe/Zagreb')
            self.assertTrue(result['rtc_saved'])

    def test_boot_timezone_restore_never_touches_clocks_or_saved_store(self):
        with runtime_fixture(True) as (_,system,rtc,save):
            clock.apply_timezone_only('Europe/Zagreb')
            system.assert_not_called();rtc.assert_not_called();save.assert_not_called()

    def test_rtc_partial_success_is_reported_after_saving_zone(self):
        with runtime_fixture(True) as (_,_,rtc,save):
            rtc.return_value='The running clock was updated, but this device has no readable hardware clock.'
            with self.assertRaisesRegex(clock.TimeError,'time zone was saved.*no readable hardware clock'):
                clock.apply_settings({'timezone':'Europe/Zagreb','local_time':'2026-11-24 14:00:00'})
            save.assert_called_once_with('timezone','Europe/Zagreb')

    def test_installed_clock_commands_are_utc_and_readback_is_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            adj=Path(directory)/'adjtime';adj.write_text('0.0 0 0.0\n0\nUTC\n')
            with patch.object(clock,'ADJTIME',adj), \
                    patch.object(clock.subprocess,'run') as run, \
                    patch.object(clock,'_hardware_epoch',return_value=1795525200), \
                    patch.object(clock.time,'time',return_value=1795525201):
                self.assertIsNone(clock._set_installed_clock(1795525200))
                self.assertEqual([c.args[0] for c in run.call_args_list],[
                    ['/usr/bin/timedatectl','--no-ask-password','set-local-rtc','0'],
                    ['/usr/bin/timedatectl','--no-ask-password','set-time','@1795525200']])
            with patch.object(clock,'ADJTIME',adj), \
                    patch.object(clock.subprocess,'run'), \
                    patch.object(clock,'_hardware_epoch',return_value=1795500000), \
                    patch.object(clock.time,'time',return_value=1795525201):
                self.assertIn('hardware clock did not keep',clock._set_installed_clock(1795525200))

    def test_hardware_clock_read_uses_boot_rtc_and_missing_clock_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name,value,boot in [('rtc0',123,0),('rtc1',1795525200,1)]:
                d=root/name;d.mkdir();(d/'since_epoch').write_text(str(value));(d/'hctosys').write_text(str(boot))
            with patch.object(clock,'RTC_ROOT',root):
                self.assertEqual(clock._hardware_epoch(),1795525200)
            with patch.object(clock,'RTC_ROOT',root/'missing'),self.assertRaisesRegex(clock.TimeError,'no readable hardware clock'):
                clock._hardware_epoch()

    def test_timezone_name_symlink_rejected_before_writing_or_mounting(self):
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'target';target.write_text('unchanged')
            link=Path(directory)/'timezone';link.symlink_to(target)
            with patch.object(clock,'TIMEZONE',link),patch.object(clock.subprocess,'run') as run:
                with self.assertRaises(clock.TimeError):clock._prepare_zone_name('Europe/Zagreb')
                run.assert_not_called()
            self.assertEqual(target.read_text(),'unchanged')

    def test_ui_previews_selected_zone_and_timezone_only_request_has_no_timestamp(self):
        with dialog_fixture() as dialog:
            self.assertIn('08:12:57',dialog.live.text())
            dialog.timezone.setCurrentText('Europe/Zagreb')
            self.assertIn('09:12:57',dialog.live.text())
            self.assertEqual(dialog.zone_status.text(),'Europe/Zagreb · UTC+01:00')
            self.assertEqual(dialog.request_values(),{'timezone':'Europe/Zagreb','local_time':None})
            self.assertFalse(dialog.manual.isEnabled())
            dialog.change_clock.setChecked(True)
            self.assertEqual(dialog.request_values()['local_time'],'2026-11-24 09:12:57')

    def test_ui_keeps_precise_helper_partial_failure_message(self):
        message='The time zone was saved. The running clock was updated, but this device has no readable hardware clock.'
        with dialog_fixture() as dialog,patch.object(ui,'Job',InlineJob), \
                patch.object(ui.subprocess,'run',return_value=subprocess.CompletedProcess([],1,json.dumps({'ok':False,'error':message}),'')):
            dialog.timezone.setCurrentText('Europe/Zagreb')
            dialog.change_clock.setChecked(True)
            dialog.save()
            self.assertEqual(dialog.feedback.text(),message)
            self.assertIsNone(dialog.job)
            self.assertTrue(dialog.apply.isEnabled())

class LiveTimezoneLinkRegression(unittest.TestCase):
    def test_live_symlink_is_atomically_replaced_then_bound_without_touching_zoneinfo(self):
        with live_link_fixture() as data:
            replace = os.replace
            def atomic_replace(source, target):
                self.assertEqual(target, data['local'])
                self.assertTrue(target.is_symlink())
                self.assertEqual(Path(source).parent, target.parent)
                self.assertEqual(stat.S_IMODE(os.stat(source).st_mode), 0o644)
                self.assertEqual(data['utc'].read_bytes(), data['utc_raw'])
                replace(source, target)
            with patch.object(clock.os, 'replace', side_effect=atomic_replace) as replaced:
                result = clock.apply_settings({'timezone':'Europe/Zagreb','local_time':None})
                replaced.assert_called_once()
            info = data['local'].lstat()
            self.assertTrue(stat.S_ISREG(info.st_mode))
            self.assertEqual(info.st_uid, 0)  # RootPath models helper ownership.
            self.assertEqual(stat.S_IMODE(info.st_mode), 0o644)
            self.assertEqual(data['utc'].read_bytes(), data['utc_raw'])
            self.assertEqual(data['local'].read_bytes(), data['utc_raw'])  # mount is stubbed.
            self.assertEqual((data['runtime']/'localtime').read_bytes(),
                             clock.zone_file('Europe/Zagreb').read_bytes())
            self.assertEqual((data['runtime']/'zone').read_text(), 'Europe/Zagreb\n')
            self.assertEqual(list(data['local'].parent.glob('.core-vault-localtime-*')), [])
            data['system'].assert_not_called(); data['rtc'].assert_not_called()
            data['save'].assert_not_called()
            self.assertFalse(result['persistent'])
            calls = [c.args[0] for c in data['run'].call_args_list]
            self.assertIn(['/usr/bin/mount','--bind',str(data['runtime']/'localtime'),str(data['local'])],calls)
            self.assertFalse(any(str(data['utc']) in args for args in calls))

    def check_rejected_link(self, data):
        with patch.object(clock.os, 'replace') as replace:
            with self.assertRaises(clock.TimeError):
                clock.apply_settings({'timezone':'Europe/Zagreb','local_time':None})
            replace.assert_not_called()
        self.assertTrue(data['local'].is_symlink())
        self.assertEqual(data['utc'].read_bytes(), data['utc_raw'])
        data['system'].assert_not_called(); data['rtc'].assert_not_called()
        data['save'].assert_not_called()
        self.assertFalse(any(c.args[0][:2] == ['/usr/bin/mount','--bind']
                             for c in data['run'].call_args_list))

    def test_installed_symlink_is_still_rejected(self):
        with live_link_fixture(boot_live=False) as data:
            self.check_rejected_link(data)

    def test_live_overlay_with_disk_upperdir_is_rejected(self):
        with live_link_fixture(upper_fstype='ext4') as data:
            self.check_rejected_link(data)

    def test_separate_disk_etc_mount_is_rejected(self):
        with live_link_fixture(etc_fstype='ext4') as data:
            self.check_rejected_link(data)

    def test_symlink_outside_zoneinfo_is_rejected(self):
        with live_link_fixture() as data:
            outside = data['root']/'outside'; outside.write_bytes(data['utc_raw'])
            outside.chmod(0o644)
            data['local'].unlink(); data['local'].symlink_to(outside)
            self.check_rejected_link(data)
            self.assertEqual(outside.read_bytes(), data['utc_raw'])

    def test_writable_zoneinfo_target_is_rejected(self):
        with live_link_fixture() as data:
            data['utc'].chmod(0o666)
            self.check_rejected_link(data)


if __name__ == '__main__':
    unittest.main(verbosity=2)
