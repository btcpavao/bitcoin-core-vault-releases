#!/usr/bin/python3
"""Test actual Home background clicks in the private Xephyr preview only.
Creates two disposable X11 windows. No real apps, wallets or archives are opened.
"""
from __future__ import annotations
import argparse
import ctypes as C
import json
import os
from pathlib import Path
import runpy
import subprocess
import time

ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument('--project', type=Path, required=True)
args = ap.parse_args()
runtime = Path(os.environ.get('XDG_RUNTIME_DIR', ''))
if os.environ.get('CORE_VAULT_NESTED_PREVIEW') != '1' or not str(runtime).startswith('/tmp/core-vault-preview.'):
    raise SystemExit('Only run through the isolated preview-desktop.sh script.')
report = json.loads((runtime / 'core-vault-desktop-geometry.json').read_text())
if report.get('window_behavior') != 'background-click-v1.2':
    raise SystemExit('Preview is not running the patched Home.')
helper = args.project.resolve() / 'config/includes.chroot/usr/local/bin/core-vault-show-home'
X11 = runpy.run_path(str(helper), run_name='vault_x11_test_helper')['X11']
x = X11()
lib = x.lib
for name, params, result in (
    ('XCreateSimpleWindow', [C.c_void_p, C.c_ulong, C.c_int, C.c_int, C.c_uint, C.c_uint, C.c_uint, C.c_ulong, C.c_ulong], C.c_ulong),
    ('XChangeProperty', [C.c_void_p, C.c_ulong, C.c_ulong, C.c_ulong, C.c_int, C.c_int, C.POINTER(C.c_ubyte), C.c_int], C.c_int),
    ('XStoreName', [C.c_void_p, C.c_ulong, C.c_char_p], C.c_int),
    ('XMapWindow', [C.c_void_p, C.c_ulong], C.c_int),
    ('XMoveWindow', [C.c_void_p, C.c_ulong, C.c_int, C.c_int], C.c_int),
    ('XDestroyWindow', [C.c_void_p, C.c_ulong], C.c_int),
):
    fn = getattr(lib, name)
    fn.argtypes, fn.restype = params, result
xt = C.CDLL('libXtst.so.6')
xt.XTestFakeMotionEvent.argtypes = [C.c_void_p, C.c_int, C.c_int, C.c_int, C.c_ulong]
xt.XTestFakeButtonEvent.argtypes = [C.c_void_p, C.c_uint, C.c_int, C.c_ulong]

def wait_for(test, message):
    end = time.monotonic() + 6
    while time.monotonic() < end:
        lib.XSync(x.display, 0)
        if test():
            return
        time.sleep(0.05)
    raise RuntimeError(message)

def click(px, py):
    xt.XTestFakeMotionEvent(x.display, x.screen, px, py, 0)
    xt.XTestFakeButtonEvent(x.display, 1, 1, 0)
    xt.XTestFakeButtonEvent(x.display, 1, 0, 0)
    lib.XSync(x.display, 0)

class ClientMessageData(C.Union):
    _fields_ = [('b', C.c_char * 20), ('s', C.c_short * 10), ('l', C.c_long * 5)]

class ClientMessage(C.Structure):
    _fields_ = [('type', C.c_int), ('serial', C.c_ulong), ('send_event', C.c_int),
                ('display', C.c_void_p), ('window', C.c_ulong),
                ('message_type', C.c_ulong), ('format', C.c_int), ('data', ClientMessageData)]

class XEvent(C.Union):
    _fields_ = [('xclient', ClientMessage), ('pad', C.c_long * 24)]

lib.XSendEvent.argtypes = [C.c_void_p, C.c_ulong, C.c_int, C.c_long, C.POINTER(XEvent)]
lib.XSendEvent.restype = C.c_int

def restore_test_window(win):
    # The desktop now initially maximizes apps. Restore only these synthetic
    # fixtures so this test can still send a real click to the Home margin.
    event = XEvent()
    event.xclient.type, event.xclient.window = 33, win
    event.xclient.display = x.display
    event.xclient.message_type = x.atom('_NET_WM_STATE')
    event.xclient.format = 32
    event.xclient.data.l[:] = [0, x.atom('_NET_WM_STATE_MAXIMIZED_HORZ'),
                               x.atom('_NET_WM_STATE_MAXIMIZED_VERT'), 1, 0]
    lib.XSendEvent(x.display, x.root, 0, (1 << 19) | (1 << 20), C.byref(event))
    lib.XSync(x.display, 0)
    wait_for(lambda: not any(x.atom(name) in x.prop(win, '_NET_WM_STATE')
                            for name in ('_NET_WM_STATE_MAXIMIZED_HORZ',
                                         '_NET_WM_STATE_MAXIMIZED_VERT')),
             'Synthetic window did not restore from its initial maximization.')

windows = []
home = int(report['window_id'], 16)
hx, hy, width, height = report['desktop_geometry']
try:
    # Right-hand side, leaving the 24-pixel Home margin exposed on the left.
    for n in range(2):
        win = int(lib.XCreateSimpleWindow(x.display, x.root,
                    hx + width - 340, hy + 70 + 190*n, 300, 140, 1, 0x444444, 0x222222))
        windows.append(win)
        values = (C.c_ulong * 1)(x.atom('_NET_WM_WINDOW_TYPE_NORMAL'))
        lib.XChangeProperty(x.display, win, x.atom('_NET_WM_WINDOW_TYPE'), x.atom('ATOM'),
                            32, 0, C.cast(values, C.POINTER(C.c_ubyte)), 1)
        lib.XStoreName(x.display, win, f'Vault background test {n+1}'.encode())
        lib.XMapWindow(x.display, win)
    lib.XSync(x.display, 0)
    wait_for(lambda: all(w in x.prop(x.root, '_NET_CLIENT_LIST') and
                        x.prop(w, 'WM_STATE')[:1] == [1] for w in windows), 'Test windows did not map.')
    for n, win in enumerate(windows):
        restore_test_window(win)
        lib.XMoveWindow(x.display, win, hx + width - 340, hy + 70 + 190*n)
    lib.XSync(x.display, 0)
    time.sleep(0.25)
    click(hx + width - 200, hy + 120)
    time.sleep(0.15)
    if any(x.minimized(w) for w in windows):
        raise RuntimeError('Click inside an application incorrectly minimized it.')
    # REAL input to the Home margin. This must reach its Qt event filter and
    # invoke the installed helper, not a substitute test implementation.
    click(hx + 8, hy + height // 2)
    wait_for(lambda: all(x.minimized(w) for w in windows),
             'Background click did not minimize the two test windows.')
    if x.minimized(home):
        raise RuntimeError('Home was minimized.')
    clients = x.prop(x.root, '_NET_CLIENT_LIST')
    panels = [w for w in clients if x.atom('_NET_WM_WINDOW_TYPE_DOCK') in x.prop(w, '_NET_WM_WINDOW_TYPE')]
    if len(panels) != 1 or any(x.minimized(w) for w in panels):
        raise RuntimeError('Taskbar visibility changed during the click test.')
    theme = subprocess.check_output(['xprop', '-root', '_OB_THEME'], text=True, timeout=3)
    if 'CoreVault' not in theme:
        raise RuntimeError('Openbox did not load the CoreVault theme: ' + theme.strip())
    print('VAULT BACKGROUND CLICK X11 TEST PASSED')
    print('Real click: two application windows minimized; Home and bottom panel stayed visible.')
    print('Openbox theme: CoreVault')
finally:
    for win in windows:
        lib.XDestroyWindow(x.display, win)
    lib.XSync(x.display, 0)
    x.close()
