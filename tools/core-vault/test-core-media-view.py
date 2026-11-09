#!/usr/bin/python3
"""Regression for the read-only Core hotplug bridge.

Default checks do not mount anything. --disposable-vm additionally creates a
private mount namespace inside QEMU/KVM, then verifies an actual child tmpfs
hotplug through bindfs and a pre-existing read-only bubblewrap namespace.
Only synthetic files in a fresh temporary directory are used.
"""
import argparse
import errno
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / 'config/includes.chroot/usr/local/bin/core-vault-media-view'


def load_helper():
    loader = importlib.machinery.SourceFileLoader('core_media_view', str(HELPER))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def policy_tests(module):
    command = ['/usr/bin/bwrap', '--ro-bind', '/', '/',
               '--bind', '/home/vault', '/home/vault',
               '--sync-fd', '3', '/usr/local/libexec/core-vault-core-session']
    views = [(Path('/run/user/1000/fresh-view/0'), None),
             (Path('/run/user/1000/fresh-view/1'), None)]
    actual = module.command_with_views(command, views)
    assert actual[:-7] == command[:-1]
    assert actual[-7:] == ['--ro-bind', str(views[0][0]), '/media/vault',
                           '--ro-bind', str(views[1][0]), '/run/media/vault',
                           command[-1]]
    assert module.command_with_views(command, []) == command
    for bad in ([], ['/bin/sh'], command[1:], command[:-1] + ['/bin/sh']):
        try:
            module.command_with_views(bad, views)
        except RuntimeError:
            pass
        else:
            raise AssertionError('Unconfined command accepted')
    path = Path('/test-view')
    for target, fstype, options, flags, expected in (
            ('/test-view', 'fuse.bindfs', 'ro,nodev,nosuid,noexec', os.ST_RDONLY, True),
            ('/test-view', 'fuse.bindfs', 'rw,nodev,nosuid', 0, False),
            ('/test-view', 'fuse.bindfs', 'ro', 0, False),
            ('/test-view', 'tmpfs', 'ro', os.ST_RDONLY, False),
            ('/parent', 'fuse.bindfs', 'ro', os.ST_RDONLY, False)):
        with mock.patch.object(module, 'mount_record', return_value={
                'target': target, 'fstype': fstype, 'options': options}), \
                mock.patch.object(module.os, 'statvfs', return_value=mock.Mock(f_flag=flags)):
            assert module.is_read_only_view(path) is expected
    print('[PASS] Only verified read-only media mounts are inserted; no-view fallback preserves confinement')


PROBE = r"""
import errno, json, os, sys
print(json.dumps({'ready': True}), flush=True)
for line in sys.stdin:
    request=json.loads(line)
    try:
        if request.get('write'):
            with open(request['path'], 'w') as stream:
                stream.write('This write must be rejected.')
            response={'written': True}
        else:
            with open(request['path']) as stream:
                response={'data': stream.read()}
    except OSError as error:
        response={'errno': error.errno}
    print(json.dumps(response), flush=True)
"""


def integration(module):
    views = []
    child = None
    mounted = False
    with tempfile.TemporaryDirectory(prefix='vault-synthetic-media-') as temporary:
        base = Path(temporary)
        source = base / 'media'
        source.mkdir()
        (source / 'existing').write_text('synthetic existing file')
        hotplug = source / 'hotplug'
        hotplug.mkdir()
        try:
            views.append(module.start_view(source, base / 'view'))
            child = subprocess.Popen(
                ['/usr/bin/bwrap', '--ro-bind', '/', '/',
                 '--ro-bind', str(views[0][0]), str(source),
                 '/usr/bin/python3', '-u', '-c', PROBE],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
            assert json.loads(child.stdout.readline()) == {'ready': True}

            def probe(path, write=False):
                child.stdin.write(json.dumps({'path': str(path), 'write': write}) + '\n')
                child.stdin.flush()
                return json.loads(child.stdout.readline())

            assert probe(source / 'existing') == {'data': 'synthetic existing file'}
            assert probe(hotplug / 'new') == {'errno': errno.ENOENT}
            # Attach a new synthetic filesystem after Core's namespace exists.
            subprocess.run(['/usr/bin/mount', '-t', 'tmpfs', '-o',
                            'size=1m,nosuid,nodev,noexec', 'tmpfs', str(hotplug)], check=True)
            mounted = True
            (hotplug / 'new').write_text('synthetic newly attached media')
            assert probe(hotplug / 'new') == {'data': 'synthetic newly attached media'}
            assert probe(hotplug / 'denied', write=True) == {'errno': errno.EROFS}
            assert not (hotplug / 'denied').exists()
            subprocess.run(['/usr/bin/umount', str(hotplug)], check=True)
            mounted = False
            assert probe(hotplug / 'new') == {'errno': errno.ENOENT}
            print('[PASS] Existing Core namespace reads hotplugged media, rejects writes, and observes removal')
        finally:
            if child is not None:
                child.terminate()
                child.wait(timeout=10)
            if mounted:
                subprocess.run(['/usr/bin/umount', str(hotplug)], check=True)
            module.stop_views(views)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--disposable-vm', action='store_true')
    parser.add_argument('--integration-child', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    module = load_helper()
    policy_tests(module)
    if args.disposable_vm or args.integration_child:
        virtualization = subprocess.check_output(
            ['/usr/bin/systemd-detect-virt', '--vm'], text=True).strip()
        if os.getuid() != 0 or virtualization not in ('qemu', 'kvm'):
            raise RuntimeError('Actual mount regression is restricted to a disposable QEMU/KVM guest.')
    if args.integration_child:
        if os.environ.get('CORE_VAULT_TEST_PRIVATE_MOUNTS') != '1':
            raise RuntimeError('A private test mount namespace is required.')
        integration(module)
    elif args.disposable_vm:
        environment = os.environ.copy()
        environment['CORE_VAULT_TEST_PRIVATE_MOUNTS'] = '1'
        subprocess.run(['/usr/bin/unshare', '--mount', '--propagation', 'private',
                        sys.executable, str(Path(__file__).resolve()), '--integration-child'],
                       env=environment, check=True, timeout=90)


if __name__ == '__main__':
    main()
