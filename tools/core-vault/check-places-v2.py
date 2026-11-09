#!/usr/bin/python3
"""Verify Places policy using temporary homes and synthetic GIO/Xfconf metadata.

The historic filename is retained for build compatibility. No real desktop,
device, wallet, media mount, or running file manager is accessed.
"""
from pathlib import Path
import copy
import hashlib
import tempfile


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


class Xfconf:
    def __init__(self, values=None, fail_device_once=False):
        self.values = copy.deepcopy(values or {})
        self.fail_device_once = fail_device_once
        self.calls = []

    def __call__(self, args):
        self.calls.append(args[:])
        if args == ['-l']:
            return '\n'.join(self.values) + '\n'
        prop = args[args.index('-p') + 1]
        if len(args) == 2:
            values = self.values[prop]
            return f'Value is an array with {len(values)} items:\n\n' + '\n'.join(values) + '\n'
        if '--reset' in args:
            self.values.pop(prop, None)
            return ''
        if self.fail_device_once and prop == '/hidden-devices':
            self.fail_device_once = False
            raise RuntimeError('Synthetic settings service failure')
        self.values[prop] = [args[i + 1] for i, arg in enumerate(args) if arg == '--set']
        return ''


class WidthXfconf:
    def __init__(self, width=None):
        self.width, self.writes = width, 0

    def __call__(self, args):
        prop = '/last-separator-position'
        if args == ['-l']:
            return prop + '\n' if self.width is not None else ''
        require(args[:2] == ['-p', prop], 'Wrong sidebar property')
        if len(args) == 2:
            return str(self.width) + '\n'
        require('--set' in args, 'Expected sidebar width write')
        if self.width is None:
            require('--create' in args and args[args.index('--type') + 1] == 'int',
                    'New sidebar width must have integer type')
        self.width = int(args[args.index('--set') + 1])
        self.writes += 1
        return ''


class GioConstants:
    VOLUME_IDENTIFIER_KIND_UUID = 'uuid'
    VOLUME_IDENTIFIER_KIND_UNIX_DEVICE = 'unix-device'


class Root:
    def __init__(self, path):
        self.path = path

    def get_path(self):
        return self.path


class Mount:
    def __init__(self, root, name, uuid=None, volume=None):
        self.root, self.name, self.uuid, self.volume = root, name, uuid, volume

    def get_root(self):
        return Root(self.root)

    def get_name(self):
        return self.name

    def get_uuid(self):
        return self.uuid

    def get_volume(self):
        return self.volume


class Volume:
    def __init__(self, name, unix, uuid=None, identifier_uuid=None, mount=None):
        self.name, self.unix, self.uuid = name, unix, uuid
        self.identifier_uuid, self.mount = identifier_uuid, mount

    def get_name(self):
        return self.name

    def get_uuid(self):
        return self.uuid

    def get_mount(self):
        return self.mount

    def get_identifier(self, key):
        return self.identifier_uuid if key == 'uuid' else self.unix


class Monitor:
    def __init__(self, volumes, mounts):
        self.volumes, self.mounts = volumes, mounts

    def get_volumes(self):
        return self.volumes

    def get_mounts(self):
        return self.mounts


def fixture(base):
    home = base / 'home/vault'
    runtime = base / 'run/user/1000'
    config = home / '.config'
    home.mkdir(parents=True)
    runtime.mkdir(parents=True)
    return home, runtime, config


def main():
    root = Path(__file__).resolve().parents[2]
    helper = root / 'config/includes.chroot/usr/local/bin/core-vault-file-places'
    template = root / 'tools/core-vault/runtime-template/usr/local/bin/core-vault-file-places'
    source = helper.read_bytes()
    require(source == template.read_bytes(), 'Places runtime/template mismatch')
    module = {'__name__': 'vault_places_source_policy'}
    exec(compile(source, str(helper), 'exec'), module)
    require(module.get('POLICY_VERSION') == 'places-v3', 'Expected Places V3 policy')
    cases = []
    for initial, expected in ((None, 320), (180, 320), (320, 320), (480, 480)):
        xf = WidthXfconf(initial)
        module['ensure_sidebar_width'](xf)
        require(xf.width == expected, 'Thunar minimum or wider sidebar preference lost')
        writes = xf.writes
        module['ensure_sidebar_width'](xf)
        require(xf.writes == writes, 'Thunar width reapply is not idempotent')
    invalid = WidthXfconf('invalid')
    try:
        module['ensure_sidebar_width'](invalid)
    except RuntimeError:
        require(invalid.writes == 0, 'Malformed sidebar preference overwritten')
    else:
        raise RuntimeError('Malformed sidebar width accepted')
    for version in ('gtk-3.0', 'gtk-4.0'):
        relative = Path('etc/skel/.config') / version / 'gtk.css'
        css = (root / 'config/includes.chroot' / relative).read_text()
        require(css == (root / 'tools/core-vault/runtime-template' / relative).read_text(),
                'GTK sidebar CSS runtime/template mismatch')
        require('placessidebar { min-width: 300px; }' in css, 'GTK Places minimum missing')
    cases.append('Thunar 320px minimum, wider choices preserved, GTK3/4 300px Places')

    with tempfile.TemporaryDirectory(prefix='vault-places-policy-') as td:
        base = Path(td)
        home, runtime, config = fixture(base / 'basic')
        private = home / 'Private Workspace'
        text = module['merge_bookmarks']('file:///tmp/notes Notes\n', home, private)
        expected = [f'{(home / ".bitcoin").as_uri()} Bitcoin Core',
                    f'{private.as_uri()} Private Workspace']
        require(text.splitlines() == expected, 'Places order or labels incorrect')
        hidden = module['places_visibility'](
            ['file:///', private.as_uri(), 'file:///run/user/1000/core-vault-places/Vault',
             'file:///old/unrelated'], home, private, config, text)
        require('file:///' not in hidden, 'File System was hidden')
        require(private.as_uri() not in hidden, 'Private Workspace was hidden')
        require((home / '.bitcoin').as_uri() not in hidden, 'Bitcoin Core was hidden')
        require('file:///old/unrelated' in hidden, 'Unrelated prior visibility was lost')
        require('file:///run/user/1000/core-vault-places/Vault' not in hidden,
                'Retired alias visibility was retained')
        require({home.as_uri(), *module['BUILTIN_PLACES'], (home / 'Desktop').as_uri()}
                .issubset(hidden), 'Built-in Places not hidden')
        cases.append('exact two bookmarks, built-in hiding, File System and prior setting preservation')

        mount_text = ('32 22 0:25 / ' + str(private).replace(' ', '\\040') +
                      ' rw,nosuid - tmpfs tmpfs rw\n'
                      '33 22 11:0 / /run/live/medium ro - iso9660 /dev/sr0 ro\n')
        mounts = module['mount_records'](mount_text)
        require(mounts[0]['root'] == str(private), 'Mountinfo spaces not decoded')
        records = [
            {'kind': 'mount', 'root': str(private), 'id': 'Private Workspace', 'name': 'Private Workspace'},
            {'kind': 'volume', 'root': None, 'unix': '/dev/sr0',
             'id': 'optical-uuid', 'name': 'Debian trixie 20261004-0745'},
            {'kind': 'volume', 'root': None, 'unix': '/dev/sdb1',
             'id': 'usb-same-label', 'name': 'Debian trixie 20261004-0745'},
            {'kind': 'volume', 'root': '/media/vault/PSBT', 'unix': '/dev/sdc1',
             'id': 'psbt-usb', 'name': 'PSBT'},
            {'kind': 'volume', 'root': None, 'unix': '/dev/sr1',
             'id': 'other-optical', 'name': 'Personal backup'},
            {'kind': 'mount', 'root': '/', 'id': 'file-system', 'name': 'File System'},
        ]
        require(module['selected_device_ids'](records, mounts, private) ==
                ['Private Workspace', 'optical-uuid'], 'Scoped device hiding incorrect')
        require(module['selected_device_ids'](records, mounts[:1], private) ==
                ['Private Workspace', 'optical-uuid'], 'Inserted Debian optical not hidden after install')
        live_usb = {'kind': 'volume', 'root': None, 'unix': '/dev/sdb1',
                    'id': 'actual-boot-usb', 'name': 'Vault live boot'}
        boot_usb_mount = {'root': '/run/live/medium', 'fstype': 'iso9660', 'source': '/dev/sdb1'}
        require(module['selected_device_ids']([live_usb], [boot_usb_mount], private) ==
                ['actual-boot-usb'], 'Exact actual USB boot medium was not hidden')
        require(module['selected_device_ids']([records[0]], [], private) == [],
                'Unproven disk-backed workspace device was hidden')
        cases.append('tmpfs identity, live boot source, inserted optical, same-label USB negative, other media negative')

        m = Mount(str(private), 'Private Workspace')
        fallback = Mount('/media/x', 'mount-name')
        volumes = [
            Volume('v1', '/dev/sr0', uuid='direct-uuid'),
            Volume('v2', '/dev/sr1', identifier_uuid='identifier-uuid'),
            Volume('v3', '/dev/sdb1'),
        ]
        gio = module['gio_device_records'](Monitor(volumes, [m, fallback]), GioConstants)
        require([v['id'] for v in gio] ==
                ['direct-uuid', 'identifier-uuid', 'v3', 'Private Workspace', 'mount-name'],
                'GIO identity does not match official Thunar fallback order')
        cases.append('synthetic GIO volume UUID, UUID identifier, name and mount UUID/name fallbacks')

        old_alias = runtime / 'core-vault-places/Vault'
        old_alias.parent.mkdir()
        old_alias.symlink_to(home, target_is_directory=True)
        bookmark = config / 'gtk-3.0/bookmarks'
        bookmark.parent.mkdir(parents=True)
        original = f'{old_alias.as_uri()} Vault\nfile:///media/vault/PSBT PSBT\n'.encode()
        bookmark.write_bytes(original)
        bookmark.chmod(0o600)
        core = home / '.bitcoin'
        core.mkdir()
        marker = core / 'synthetic-data-preservation-marker'
        marker.write_bytes(b'Unmodified synthetic bytes.\n')
        marker_before = hashlib.sha256(marker.read_bytes()).hexdigest()
        xf = Xfconf({'/hidden-bookmarks': ['file:///', 'file:///unrelated'],
                     '/hidden-devices': ['previous-hidden-device']})
        selected = lambda _: ['Private Workspace', 'optical-uuid']
        module['configure'](home, runtime, config, run=xf, devices=selected)
        require(bookmark.read_text().splitlines() == expected, 'Actual config bookmarks incorrect')
        require(xf.values['/hidden-devices'] ==
                ['previous-hidden-device', 'Private Workspace', 'optical-uuid'],
                'Existing device setting not preserved')
        require(not old_alias.is_symlink(), 'Old display alias not retired')
        require(marker_before == hashlib.sha256(marker.read_bytes()).hexdigest(),
                'Existing synthetic Core data changed')
        require(bookmark.with_name('bookmarks.before-core-vault-places-v3').read_bytes() ==
                original, 'Original bookmarks backup missing')
        before = (bookmark.read_bytes(), copy.deepcopy(xf.values))
        module['configure'](home, runtime, config, run=xf, devices=selected)
        require(before == (bookmark.read_bytes(), xf.values), 'Configuration not idempotent')
        module['check'](home, runtime, config, run=xf, devices=selected)
        cases.append('V2 migration, alias-only retirement, no data change, backups and idempotence')

        home2, runtime2, config2 = fixture(base / 'rollback')
        b2 = config2 / 'gtk-3.0/bookmarks'
        b2.parent.mkdir(parents=True)
        b2.write_bytes(b'file:///tmp/original Original\n')
        old2 = runtime2 / 'core-vault-places/Vault'
        old2.parent.mkdir()
        old2.symlink_to(home2, target_is_directory=True)
        xf2 = Xfconf({'/hidden-bookmarks': ['file:///original-hidden'],
                      '/hidden-devices': ['original-device']}, fail_device_once=True)
        before2 = copy.deepcopy(xf2.values)
        try:
            module['configure'](home2, runtime2, config2, run=xf2, devices=selected)
        except RuntimeError as exc:
            require('Synthetic settings service failure' in str(exc), 'Unexpected rollback exception')
        else:
            raise RuntimeError('Injected settings failure did not fail')
        require(xf2.values == before2, 'Visibility settings not rolled back')
        require(b2.read_bytes() == b'file:///tmp/original Original\n',
                'Bookmarks not rolled back')
        require(old2.is_symlink() and old2.resolve() == home2.resolve(),
                'Old display alias changed before successful configuration')
        cases.append('settings failure restores both visibility properties, bookmarks and old display alias')

        home3, runtime3, config3 = fixture(base / 'redirect')
        (home3 / 'Private Workspace').symlink_to(home3, target_is_directory=True)
        try:
            module['configure'](home3, runtime3, config3, run=Xfconf(), devices=selected)
        except RuntimeError as exc:
            require('symbolic link' in str(exc), 'Wrong redirected-directory rejection')
        else:
            raise RuntimeError('Redirected workspace unexpectedly accepted')
        cases.append('redirected workspace rejected before bookmarks or visibility mutations')

    print('VAULT PLACES V3 SOURCE CHECK PASSED')
    for case in cases:
        print('PASS: ' + case)


if __name__ == '__main__':
    main()
