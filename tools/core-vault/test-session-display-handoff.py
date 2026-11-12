#!/usr/bin/python3
"""Check Vault's display handoff on a private, input-free X server."""
import ctypes as ct
from pathlib import Path
import subprocess
import sys


HERE = Path(__file__).resolve()
DISPLAY_SETUP = (HERE.parents[2] / 'config/includes.chroot/usr/share'
                 / 'core-signer/lightdm-display-setup.sh')


class SaverInfo(ct.Structure):
    # XScreenSaverInfo from X11/extensions/scrnsaver.h
    _fields_ = [('window', ct.c_ulong), ('state', ct.c_int), ('kind', ct.c_int),
                ('til_or_since', ct.c_ulong), ('idle', ct.c_ulong),
                ('event_mask', ct.c_ulong)]


def check_display(helper):
    x11 = ct.CDLL('libX11.so.6')
    x11.XOpenDisplay.argtypes = [ct.c_char_p]
    x11.XOpenDisplay.restype = ct.c_void_p
    x11.XDefaultRootWindow.argtypes = [ct.c_void_p]
    x11.XDefaultRootWindow.restype = ct.c_ulong
    x11.XCloseDisplay.argtypes = [ct.c_void_p]
    xss = ct.CDLL('libXss.so.1')
    xss.XScreenSaverQueryInfo.argtypes = [ct.c_void_p, ct.c_ulong, ct.POINTER(SaverInfo)]
    display = x11.XOpenDisplay(None)
    if not display:
        raise RuntimeError('Cannot open the isolated test display')
    try:
        root = x11.XDefaultRootWindow(display)

        def saver_state():
            info = SaverInfo()
            if not xss.XScreenSaverQueryInfo(display, root, ct.byref(info)):
                raise RuntimeError('XScreenSaverQueryInfo failed')
            return info.state

        for timeout in ('on', 'off'):
            subprocess.run(['xset', 's', 'on', 's', 'activate'], check=True)
            subprocess.run(['xset', 's', timeout], check=True)
            if saver_state() != 1:  # ScreenSaverOn
                raise AssertionError('Test setup did not produce an active saver')
            subprocess.run(['/bin/sh', helper], check=True)
            if saver_state() not in (0, 3):  # ScreenSaverOff or ScreenSaverDisabled
                raise AssertionError(f'Display still blank after handoff with saver timeout {timeout}')
    finally:
        x11.XCloseDisplay(display)


if __name__ == '__main__':
    # xvfb-run allocates its own display and cookie. Never change the caller's display.
    subprocess.run([
        'xvfb-run', '--auto-servernum', '--server-args=-screen 0 800x600x24 -extension DPMS',
        sys.executable, '-c',
        "from runpy import run_path; import sys; run_path(sys.argv[1])['check_display'](sys.argv[2])",
        str(HERE), str(DISPLAY_SETUP),
    ], check=True, timeout=30)
    print('Vault display handoff cleared the active saver without keyboard or pointer input.')
