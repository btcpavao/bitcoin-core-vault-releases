#!/usr/bin/python3
"""Inspect the live X11 desktop. Reads properties, does not alter windows."""
import json
import os
from pathlib import Path
import re
import runpy
import subprocess
import sys


def run(*argv):
    return subprocess.check_output(argv, text=True, stderr=subprocess.STDOUT, timeout=10)


def geometry(win):
    out = run('xwininfo', '-id', win)
    def field(name):
        match = re.search(r'^\s*' + re.escape(name) + r':\s*(-?\d+)', out, re.M)
        if not match:
            raise RuntimeError('Missing geometry field: ' + name)
        return int(match.group(1))
    return [field('Absolute upper-left X'), field('Absolute upper-left Y'),
            field('Width'), field('Height')]


def main():
    report = Path(os.environ['XDG_RUNTIME_DIR']) / 'core-vault-desktop-geometry.json'
    obj = json.loads(report.read_text())
    if obj.get('version') != 'home-suite-v1':
        raise RuntimeError('Wrong running desktop version; expected home-suite-v1')
    windows = re.findall(r'0x[0-9a-fA-F]+', run('xprop', '-root', '_NET_CLIENT_LIST'))
    panels = []
    homes = []
    for win in windows:
        name = run('xprop', '-id', win, '_NET_WM_NAME', 'WM_NAME')
        if 'Core Vault Taskbar' in name:
            panels.append(win)
        if '"Bitcoin Core Vault"' in name:
            homes.append(win)
    if len(homes) != 1:
        raise RuntimeError(f'Expected one desktop: homes={homes}')
    # Reuse the taskbar's exact current-workspace, transient and skip-taskbar
    # policy so a Home-owned confirmation is never mistaken for an app task.
    helper = Path(__file__).with_name('core-vault-taskbar')
    if not helper.is_file():
        helper = Path(__file__).resolve().parents[2] / 'config/includes.chroot/usr/local/bin/core-vault-taskbar'
    windows_class = runpy.run_path(str(helper), run_name='vault_desktop_window_policy')['Windows']
    x = windows_class()
    try:
        programs = [hex(window) for window in x.task_windows()]
    finally:
        x.close()
    if len(panels) != bool(programs):
        raise RuntimeError(f'Taskbar visibility does not match open apps: panels={panels}, apps={programs}')
    panel = panels[0] if panels else None
    home = homes[0]
    home_props = run('xprop', '-id', home, '_NET_WM_WINDOW_TYPE', '_NET_WM_STATE')
    if '_NET_WM_WINDOW_TYPE_DESKTOP' not in home_props:
        raise RuntimeError('Home is not an EWMH DESKTOP')
    hg, pg = geometry(home), geometry(panel) if panel else None
    if panel:
        panel_props = run('xprop', '-id', panel, '_NET_WM_WINDOW_TYPE', '_NET_WM_STRUT_PARTIAL')
        if '_NET_WM_WINDOW_TYPE_DOCK' not in panel_props:
            raise RuntimeError('Panel is not an EWMH DOCK')
        if pg[0] != hg[0] or pg[2] != hg[2] or pg[1] + pg[3] != hg[1] + hg[3]:
            raise RuntimeError(f'Panel is not flush with the desktop bottom: home={hg}, panel={pg}')
        if pg[3] != 40:
            raise RuntimeError(f'Expected 40-pixel panel, found {pg[3]}')
        match = re.search(r'_NET_WM_STRUT_PARTIAL\([^)]*\)\s*=\s*(.*)', panel_props)
        values = [int(x.strip()) for x in match.group(1).split(',')] if match else []
        if len(values) < 12 or values[2] != 0 or values[3] != 40:
            raise RuntimeError(f'Wrong active panel struts: {values}')
    sizes = {tuple(x) for x in obj['card_sizes']}
    if len(sizes) != 1 or len(obj['card_sizes']) != 10:
        raise RuntimeError('Cards are not ten equal-size widgets')

    expected_titles = ['Bitcoin Core', 'Wallet Backup', 'Decrypt Backup', 'KeePassXC', 'Editor', 'Brasero', 'Print & Labels', 'Files', 'Terminal', 'Vault Guide']
    if obj.get('card_titles') != expected_titles:
        raise RuntimeError(
            f'Unexpected Home cards: {obj.get("card_titles")}'
        )
    workarea = run('xprop', '-root', '_NET_WORKAREA').strip()
    if '=' not in workarea:
        raise RuntimeError('Missing WM work area')
    area = [int(v.strip()) for v in workarea.split('=', 1)[1].split(',')]
    if area[:4] != [hg[0], hg[1], hg[2], hg[3] - (40 if panel else 0)]:
        raise RuntimeError(f'Unexpected single-monitor work area: {area}')
    print('VAULT DESKTOP X11 CHECK PASSED')
    print('Home: DESKTOP, geometry', hg)
    print('Panel: DOCK, geometry' if panel else 'Panel: hidden while Home is alone', pg or '')
    print('Panel reservation: top=0, bottom='+str(40 if panel else 0))
    print('Cards: ten equal widgets, size', next(iter(sizes)))
    print(workarea)
    print('This verifies geometry/type, not offline isolation or wallet security.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, subprocess.SubprocessError, RuntimeError, KeyError, ValueError) as exc:
        print('VAULT DESKTOP CHECK FAILED:', exc, file=sys.stderr)
        sys.exit(1)
