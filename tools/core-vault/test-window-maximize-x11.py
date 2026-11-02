#!/usr/bin/python3
"""Real Openbox initial-state regression on an owned private Xvfb server.

No existing desktop, application profile, wallet or real file is used.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import signal
import struct
import subprocess
import tempfile
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--project', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--config', type=Path)
parser.add_argument('--background-test', type=Path)
args = parser.parse_args()
if os.getuid() == 0:
    raise SystemExit('Run this private preview as an ordinary user.')
root = args.project.resolve(strict=True)
assets = root / 'config/includes.chroot/usr/share/core-vault'
config = (args.config or assets / 'openbox.xml').resolve(strict=True)
output = args.output.resolve()
output.mkdir(parents=True, exist_ok=False)
for command in ('Xvfb', 'openbox', 'xprop', 'xwininfo', 'xwd', 'convert',
                'dbus-run-session', 'zenity'):
    if shutil.which(command) is None:
        raise SystemExit('Missing private preview dependency: ' + command)

app = None
processes = []
scope = None
report = {}

def run(*argv):
    return subprocess.check_output(argv, text=True, stderr=subprocess.STDOUT, timeout=5)

def wait_for(test, message):
    end = time.monotonic() + 12
    while time.monotonic() < end:
        if app is not None:
            app.processEvents()
        if test():
            return
        time.sleep(.05)
    raise RuntimeError(message)

def prop(window, name):
    return run('xprop', '-id', hex(window), name).strip()

def snapshot(window):
    geometry = run('xwininfo', '-id', hex(window))
    def number(name):
        return int(re.search(r'^\s*' + re.escape(name) + r':\s*(-?\d+)', geometry, re.M)[1])
    client = [number(n) for n in ('Absolute upper-left X', 'Absolute upper-left Y', 'Width', 'Height')]
    values = prop(window, '_NET_FRAME_EXTENTS').split('=', 1)
    extents = [int(n.strip()) for n in values[1].split(',')] if len(values) == 2 else [0, 0, 0, 0]
    frame = [client[0]-extents[0], client[1]-extents[2],
             client[2]+extents[0]+extents[1], client[3]+extents[2]+extents[3]]
    return dict(window=hex(window), client=client, frame=frame,
                state=prop(window, '_NET_WM_STATE'),
                window_type=prop(window, '_NET_WM_WINDOW_TYPE'),
                normal_hints=prop(window, 'WM_NORMAL_HINTS'))

def maximized(window):
    state = prop(window, '_NET_WM_STATE')
    return all('_NET_WM_STATE_MAXIMIZED_' + axis in state for axis in ('HORZ', 'VERT'))

def check_max(name, window, workarea):
    wait_for(lambda: maximized(window), name + ' did not initially maximize')
    wait_for(lambda: snapshot(window)['frame'] == workarea, name + ' did not fill the panel work area')
    report[name] = snapshot(window)
    expected_type = 'NORMAL' if name == 'normal-app' else 'DIALOG'
    assert '_NET_WM_WINDOW_TYPE_' + expected_type in report[name]['window_type']
    capture(name)

def capture(name):
    if app is not None:
        app.processEvents()
    raw = subprocess.check_output(['xwd', '-root', '-silent'], timeout=5)
    subprocess.run(['convert', 'xwd:-', str(output / (name + '.png'))], input=raw, check=True, timeout=5)

def spawn(argv, name, env):
    process = subprocess.Popen(argv, env=env, stdout=(output / (name+'.log')).open('w'), stderr=subprocess.STDOUT)
    processes.append(process)
    return process

try:
    temporary = tempfile.mkdtemp(prefix='core-vault-preview.maximize.')
    tmp = Path(temporary)
    scope = tmp.name
    for name in ('home', 'config', 'cache', 'data', 'runtime', 'fixture'):
        (tmp / name).mkdir(mode=0o700)
    (tmp / 'fixture/synthetic.txt').write_text('SYNTHETIC WINDOW TEST ONLY\n')
    theme = tmp / 'home/.themes/CoreVault/openbox-3'
    theme.mkdir(parents=True)
    shutil.copyfile(root / 'config/includes.chroot/usr/share/themes/CoreVault/openbox-3/themerc', theme / 'themerc')
    cookie = tmp / 'Xauthority'
    fields = [b'', b'', b'MIT-MAGIC-COOKIE-1', os.urandom(16)]
    cookie.write_bytes(struct.pack('>H', 65535) + b''.join(struct.pack('>H', len(f)) + f for f in fields))
    cookie.chmod(0o600)
    env = os.environ.copy()
    for key in ('DISPLAY', 'DBUS_SESSION_BUS_ADDRESS', 'SESSION_MANAGER'):
        env.pop(key, None)
    env.update(HOME=str(tmp/'home'), XDG_CONFIG_HOME=str(tmp/'config'),
               XDG_CACHE_HOME=str(tmp/'cache'), XDG_DATA_HOME=str(tmp/'data'),
               XDG_RUNTIME_DIR=str(tmp/'runtime'), XAUTHORITY=str(cookie),
               CORE_VAULT_MAXIMIZE_TEST_SCOPE=scope, GTK_USE_PORTAL='0')
    read_fd, write_fd = os.pipe()
    server = subprocess.Popen(['Xvfb', '-displayfd', str(write_fd), '-screen', '0', '1280x800x24',
                               '-nolisten', 'tcp', '-auth', str(cookie)], env=env, pass_fds=(write_fd,),
                              stdout=(output/'xvfb.log').open('w'), stderr=subprocess.STDOUT)
    processes.append(server)
    os.close(write_fd)
    display = os.read(read_fd, 100).decode().strip()
    os.close(read_fd)
    assert display.isdigit(), 'Private Xvfb did not allocate a display'
    env['DISPLAY'] = ':' + display
    os.environ.update(env)
    spawn(['openbox', '--sm-disable', '--config-file', str(config)], 'openbox', env)
    wait_for(lambda: '0x' in run('xprop', '-root', '_NET_SUPPORTING_WM_CHECK'), 'Openbox did not start')
    spawn(['/usr/bin/python3', str(root/'config/includes.chroot/usr/local/bin/core-vault-taskbar'),
           '--preview', '--assets', str(assets)], 'taskbar', env)
    wait_for(lambda: '= 0, 0, 1280, 800' in run('xprop', '-root', '_NET_WORKAREA'), 'Idle panel incorrectly reserves work area')
    workarea = [0, 0, 1280, 760]
    spawn(['/usr/bin/python3', str(root/'config/includes.chroot/usr/local/bin/core-vault-home'),
           '--preview', '--assets', str(assets)], 'home', env)
    geometry_file = tmp/'runtime/core-vault-desktop-geometry.json'
    wait_for(geometry_file.exists, 'Home geometry report missing')
    home_id = int(json.loads(geometry_file.read_text())['window_id'], 16)
    from PySide6.QtWidgets import QApplication, QWidget, QDialog, QFileDialog, QMessageBox
    app = QApplication(['vault-maximize-regression'])
    app.setStyle('Fusion')
    normal = QWidget()
    normal.setWindowTitle('Synthetic normal app')
    normal.resize(640, 420)
    normal.show()
    check_max('normal-app', int(normal.winId()), workarea)
    normal.showNormal()
    wait_for(lambda: not maximized(int(normal.winId())), 'Manual Restore failed')
    report['normal-restored'] = snapshot(int(normal.winId()))
    normal.close()
    dialog = QDialog()
    dialog.setWindowTitle('Synthetic resizable Qt dialog')
    dialog.resize(600, 350)
    dialog.show()
    check_max('qt-dialog', int(dialog.winId()), workarea)
    dialog.close()
    chooser = QFileDialog(None, 'Synthetic Qt Save chooser', str(tmp/'fixture'))
    chooser.setOption(QFileDialog.DontUseNativeDialog)
    chooser.setAcceptMode(QFileDialog.AcceptSave)
    chooser.show()
    check_max('qt-save', int(chooser.winId()), workarea)
    chooser.close()
    fixed = QDialog()
    fixed.setWindowTitle('Synthetic fixed dialog')
    fixed.setFixedSize(420, 180)
    fixed.show()
    wait_for(lambda: 'WM_STATE_NORMAL' in prop(int(fixed.winId()), 'WM_STATE')
             or 'Normal' in prop(int(fixed.winId()), 'WM_STATE'), 'Fixed dialog not mapped')
    app.processEvents()
    time.sleep(.2)
    # Openbox may retain requested MAXIMIZED atoms even when fixed hints
    # prevent resizing; the actual application bounds are the contract.
    report['fixed-dialog'] = snapshot(int(fixed.winId()))
    assert report['fixed-dialog']['client'][2:] == [420, 180]
    capture('fixed-dialog')
    fixed.close()
    message = QMessageBox(QMessageBox.Information, 'Synthetic fixed alert', 'No real data are used.')
    message.show()
    wait_for(lambda: 'Normal' in prop(int(message.winId()), 'WM_STATE'), 'Fixed alert not mapped')
    app.processEvents()
    time.sleep(.2)
    report['fixed-alert'] = snapshot(int(message.winId()))
    assert report['fixed-alert']['client'][2] < 640 and report['fixed-alert']['client'][3] < 400, 'Fixed alert expanded beyond its compact app layout'
    capture('fixed-alert')
    message.close()
    os.chdir(tmp/'fixture')
    title = 'Synthetic native GTK Save chooser'
    spawn(['dbus-run-session', '--', 'zenity', '--file-selection', '--save',
           '--title='+title, '--filename='+str(tmp/'fixture/export.gpg')], 'gtk-save', env)
    def gtk_window():
        clients = re.findall(r'0x[0-9a-fA-F]+', run('xprop', '-root', '_NET_CLIENT_LIST'))
        return next((int(w, 16) for w in clients if title in prop(int(w, 16), '_NET_WM_NAME')), None)
    wait_for(gtk_window, 'Native GTK Save chooser did not map')
    gtk_id = gtk_window()
    check_max('gtk-save', gtk_id, workarea)
    report['home'] = snapshot(home_id)
    assert '_NET_WM_WINDOW_TYPE_DESKTOP' in report['home']['window_type']
    assert not maximized(home_id)
    clients = re.findall(r'0x[0-9a-fA-F]+', run('xprop', '-root', '_NET_CLIENT_LIST'))
    panels = [int(w,16) for w in clients if '_NET_WM_WINDOW_TYPE_DOCK' in prop(int(w,16), '_NET_WM_WINDOW_TYPE')]
    assert len(panels) == 1
    report['panel'] = snapshot(panels[0])
    assert report['panel']['client'] == [0, 760, 1280, 40]
    assert not maximized(panels[0])
    # Close the owned GTK fixture, then run the original real Home-click test
    # with its two addressed/restored synthetic windows under this same WM.
    token = ('CORE_VAULT_MAXIMIZE_TEST_SCOPE='+scope).encode()
    for path in Path('/proc').glob('[0-9]*'):
        try:
            if (path/'comm').read_text().strip() == 'zenity' and token in (path/'environ').read_bytes().split(b'\0'):
                os.kill(int(path.name), signal.SIGTERM)
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            pass
    wait_for(lambda: hex(gtk_id) not in run('xprop', '-root', '_NET_CLIENT_LIST'), 'GTK fixture did not close')
    background = (args.background_test or root/'tools/core-vault/test-window-behavior-x11.py').resolve(strict=True)
    nested = dict(env, CORE_VAULT_NESTED_PREVIEW='1')
    result = subprocess.run(['/usr/bin/python3', str(background), '--project', str(root)],
                            env=nested, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, timeout=30)
    (output/'background-click.log').write_text(result.stdout)
    if result.returncode:
        raise RuntimeError('Existing Home background-click regression failed: '+result.stdout)
    report['background_click'] = 'PASS'
    report.update(result='PASS', workarea=workarea, display=env['DISPLAY'],
                  candidate_config_sha256=__import__('hashlib').sha256(config.read_bytes()).hexdigest())
    (output/'result.json').write_text(json.dumps(report, indent=2)+'\n')
    print('VAULT INITIAL MAXIMIZE X11 TEST PASSED')
    print('Normal app, Qt dialog, Qt Save and native GTK Save fill 1280x760; fixed dialogs, Home and 40px panel preserved.')
finally:
    if scope is not None:
        token = ('CORE_VAULT_MAXIMIZE_TEST_SCOPE='+scope).encode()
        for path in Path('/proc').glob('[0-9]*'):
            try:
                if int(path.name) != os.getpid() and token in (path/'environ').read_bytes().split(b'\0'):
                    os.kill(int(path.name), signal.SIGTERM)
            except (FileNotFoundError, ProcessLookupError, PermissionError):
                pass
    for process in reversed(processes):
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()

    if 'tmp' in globals():
        shutil.rmtree(tmp, ignore_errors=True)
