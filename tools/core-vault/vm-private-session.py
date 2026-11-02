#!/usr/bin/python3
"""Disposable VM controller. Never sends input to the host desktop or another VM."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import time

BASE = Path('/home/pavao/vault-test-results/ram-session-20261004')


def directory(name):
    if name not in ('vm-bios', 'vm-uefi', 'vm-800'):
        raise RuntimeError('Only designated disposable test directories are allowed.')
    path = BASE / name
    if path.is_symlink():
        raise RuntimeError('Test directory cannot be a link.')
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)
    return path


def guard(path):
    record = json.loads((path / 'current.json').read_text())
    proc = Path('/proc') / str(record['pid'])
    args = [x.decode() for x in (proc / 'cmdline').read_bytes().split(b'\0') if x]
    if args != record['args'] or (proc / 'stat').read_text().split(') ', 1)[1].split()[19] != record['start_ticks']:
        raise RuntimeError('Own QEMU PID/argv identity changed.')
    if record['args'][0] != '/usr/bin/qemu-system-x86_64' or str(path / 'qmp.sock') not in ' '.join(args):
        raise RuntimeError('Private QMP scope mismatch.')
    return record


class QMP:
    def __init__(self, path):
        self.path = path
        guard(path)
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(15)
        self.sock.connect(str(path / 'qmp.sock'))
        self.stream = self.sock.makefile('rb')
        self.stream.readline()
        self.call('qmp_capabilities')

    def call(self, command, **arguments):
        record = guard(self.path)
        with (self.path / 'actions.jsonl').open('a') as log:
            log.write(json.dumps({'time': time.time(), 'own_pid': record['pid'], 'command': command, 'arguments': arguments}) + '\n')
        self.sock.sendall((json.dumps({'execute': command, 'arguments': arguments}) + '\n').encode())
        while True:
            result = json.loads(self.stream.readline())
            if 'event' in result:
                continue
            if 'error' in result:
                raise RuntimeError(result['error'])
            return result.get('return')

    def key(self, keys):
        self.call('input-send-event', events=[{'type': 'key', 'data': {'down': True, 'key': {'type': 'qcode', 'data': key}}} for key in keys])
        time.sleep(.03)
        self.call('input-send-event', events=[{'type': 'key', 'data': {'down': False, 'key': {'type': 'qcode', 'data': key}}} for key in reversed(keys)])
        time.sleep(.04)

    def text(self, value):
        plain = dict(zip(' -=[];\'`,./\\\n', ['spc', 'minus', 'equal', 'bracket_left', 'bracket_right', 'semicolon', 'apostrophe', 'grave_accent', 'comma', 'dot', 'slash', 'backslash', 'ret']))
        shifted = dict(zip('!@#$%^&*()_+{}:"<>?|~', ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0', 'minus', 'equal', 'bracket_left', 'bracket_right', 'semicolon', 'apostrophe', 'comma', 'dot', 'slash', 'backslash', 'grave_accent']))
        for ch in value:
            if ch.isascii() and ch.isalnum():
                self.key((['shift'] if ch.isupper() else []) + [ch.lower()])
            elif ch in plain:
                self.key([plain[ch]])
            elif ch in shifted:
                self.key(['shift', shifted[ch]])
            else:
                raise RuntimeError('Use ASCII QMP typing only.')

    def close(self):
        self.stream.close()
        self.sock.close()


def launch(path, phase, iso, media):
    if phase not in ('install', 'installed'):
        raise RuntimeError('Invalid disposable phase.')
    if (path / 'current.json').exists():
        try:
            guard(path)
        except FileNotFoundError:
            pass
        else:
            raise RuntimeError('Own test VM is still running.')
    disk = path / 'standalone-24GiB.qcow2'
    if not disk.exists():
        if phase != 'install':
            raise RuntimeError('No installed test disk.')
        subprocess.run(['qemu-img', 'create', '-f', 'qcow2', str(disk), '24G'], check=True)
    info = json.loads(subprocess.check_output(['qemu-img', 'info', '--output=json', str(disk)]))
    if disk.is_symlink() or info['format'] != 'qcow2' or info['virtual-size'] != 24 * 1024**3 or any(key in info for key in ('backing-filename', 'data-file')):
        raise RuntimeError('Only standalone disposable qcow2 images are allowed.')
    sock = path / 'qmp.sock'
    if sock.exists():
        if not sock.is_socket():
            raise RuntimeError('Unexpected QMP path.')
        sock.unlink()
    args = ['/usr/bin/qemu-system-x86_64', '-name', 'Core Vault RAM TEST ' + path.name,
            '-machine', 'q35,accel=kvm', '-m', '2048', '-smp', '2', '-nic', 'none',
            '-display', 'none', '-vga', 'std', '-global', 'VGA.edid=on',
            '-global', 'VGA.xres=' + ('800' if path.name == 'vm-800' else '1280'),
            '-global', 'VGA.yres=' + ('600' if path.name == 'vm-800' else '800'),
            '-qmp', f'unix:{sock},server=on,wait=off', '-monitor', 'none',
            '-serial', f'file:{path}/{phase}-serial.log', '-device', 'qemu-xhci', '-device', 'usb-tablet',
            '-drive', f'file={disk},if=none,id=target,format=qcow2',
            '-device', 'virtio-blk-pci,drive=target,serial=CV_RAM_TEST_INTERNAL']
    if path.name == 'vm-uefi':
        import shutil
        variables = path / 'test-vars.fd'
        if not variables.exists():
            shutil.copyfile('/usr/share/OVMF/OVMF_VARS_4M.fd', variables)
        args += ['-drive', 'if=pflash,format=raw,unit=0,readonly=on,file=/usr/share/OVMF/OVMF_CODE_4M.fd',
                 '-drive', f'if=pflash,format=raw,unit=1,file={variables}']
    state = None
    if phase == 'install':
        iso = iso.resolve(strict=True)
        if iso.parent != BASE or iso.is_symlink() or iso.stat().st_mode & 0o222:
            raise RuntimeError('Only the frozen read-only ISO in this evidence directory is allowed.')
        with iso.open('rb') as stream:
            sha = hashlib.file_digest(stream, 'sha256').hexdigest()
        state = {'path': str(iso), 'sha256': sha, 'bytes': iso.stat().st_size}
        args += ['-drive', f'file={iso},if=ide,index=2,media=cdrom,readonly=on', '-boot', 'order=d', '-no-reboot']
    else:
        args += ['-boot', 'order=c']
    if media:
        media = media.resolve(strict=True)
        if media.parent != BASE or media.is_symlink():
            raise RuntimeError('Only the separate disposable USB fixture is allowed.')
        args += ['-drive', f'file={media},format=raw,if=none,id=usbfixture',
                 '-device', 'usb-storage,drive=usbfixture,serial=CV_RAM_TEST_USB']
    nonce = str(time.time_ns())
    with (path / (phase + '-' + nonce + '-qemu.log')).open('xb') as log:
        process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
    ticks = (Path('/proc') / str(process.pid) / 'stat').read_text().split(') ', 1)[1].split()[19]
    record = {'pid': process.pid, 'args': args, 'start_ticks': ticks, 'phase': phase, 'iso': state, 'disk': str(disk)}
    (path / (phase + '-' + nonce + '-manifest.json')).write_text(json.dumps(record, indent=2))
    (path / 'current.json').write_text(json.dumps(record, indent=2))
    for attempt in range(50):
        if sock.exists():
            sock.chmod(0o600)
            break
        if process.poll() is not None:
            raise RuntimeError('Own QEMU did not start.')
        time.sleep(.1)
    client = QMP(path)
    try:
        blocks = client.call('query-block')
        (path / (phase + '-' + nonce + '-blocks.json')).write_text(json.dumps(blocks, indent=2))
        if phase == 'installed' and any(row.get('inserted', {}).get('file', '').endswith('.iso') for row in blocks):
            raise RuntimeError('Installed boot has an unexpected ISO.')
    finally:
        client.close()
    print(json.dumps(record))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('vm-bios', 'vm-uefi', 'vm-800'))
    parser.add_argument('action', choices=('launch', 'key', 'type', 'click', 'capture', 'status', 'quit'))
    parser.add_argument('values', nargs='*')
    parser.add_argument('--phase', default='install')
    parser.add_argument('--iso', type=Path)
    parser.add_argument('--media', type=Path)
    args = parser.parse_args()
    path = directory(args.mode)
    if args.action == 'launch':
        launch(path, args.phase, args.iso, args.media)
        return
    client = QMP(path)
    try:
        if args.action == 'key':
            client.key(args.values)
        elif args.action == 'type':
            client.text(args.values[0])
        elif args.action == 'click':
            x, y, width, height = map(int, args.values)
            client.call('input-send-event', events=[{'type': 'abs', 'data': {'axis': axis, 'value': round(value * 32767 / (size - 1))}} for axis, value, size in (('x', x, width), ('y', y, height))])
            client.call('input-send-event', events=[{'type': 'btn', 'data': {'button': 'left', 'down': True}}])
            time.sleep(.12)
            client.call('input-send-event', events=[{'type': 'btn', 'data': {'button': 'left', 'down': False}}])
            time.sleep(.2)
        elif args.action == 'capture':
            from PIL import Image
            name = args.values[0]
            if not name.replace('-', '').replace('_', '').isalnum():
                raise RuntimeError('Invalid capture name.')
            ppm, png = path / (name + '.ppm'), path / (name + '.png')
            if ppm.exists() or png.exists():
                raise RuntimeError('Evidence cannot be overwritten.')
            client.call('screendump', filename=str(ppm))
            Image.open(ppm).save(png)
            print(png)
        elif args.action == 'status':
            print(json.dumps(client.call('query-status')))
        elif args.action == 'quit':
            client.call('quit')
    finally:
        client.close()


if __name__ == '__main__':
    main()
