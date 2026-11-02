#!/usr/bin/python3
"""Exercise stock KeePassXC on owned Xvfb/D-Bus and a disposable empty profile."""
import argparse
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import time


def bus_test(project, output, config):
    import gi
    gi.require_version('Atspi', '2.0')
    from gi.repository import Atspi, Gio, GLib
    Atspi.set_timeout(400, 400)
    desktop = None
    helper = project / 'config/includes.chroot/usr/local/bin/core-vault-open-passphrase'
    results = {}
    process = None

    def wait_for(test, description):
        end = time.monotonic() + 12
        while time.monotonic() < end:
            while GLib.MainContext.default().pending():
                GLib.MainContext.default().iteration(False)
            value = test()
            if value:
                return value
            time.sleep(.05)
        raise AssertionError(description)

    def owned():
        desktop.clear_cache()
        for i in range(desktop.get_child_count()):
            app = desktop.get_child_at_index(i)
            if app.get_process_id() == process.pid:
                return app

    def children(node):
        return [node.get_child_at_index(i) for i in range(node.get_child_count())]

    def nodes(node):
        # Never inspect generated secret fields; this test needs only controls.
        if node.get_role() in (Atspi.Role.TEXT, Atspi.Role.ENTRY, Atspi.Role.PASSWORD_TEXT):
            return
        yield node
        for child in children(node):
            yield from nodes(child)

    def state(node, flag):
        node.clear_cache()
        return node.get_state_set().contains(flag)

    def generator(app):
        frames = [n for n in children(app) if n.get_role() == Atspi.Role.FRAME]
        bars = [n for f in frames for n in children(f) if n.get_role() == Atspi.Role.TOOL_BAR]
        return next(n for b in bars for n in children(b)
                    if n.get_role() == Atspi.Role.CHECK_BOX and n.get_name() == 'Password Generator')

    def observe():
        result = subprocess.run(['/usr/bin/python3', str(helper), '--pid', str(process.pid)], capture_output=True,
                                text=True, timeout=14)
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    try:
        for launch in range(3):
            startup_log = output / ('observer-' + str(launch) + '.log')
            with (output / ('keepass-' + str(launch) + '.log')).open('w') as log:
                # Same observer-before-exec order and retained PID as the
                # Vault wrapper, with an inert private config for this test.
                process = subprocess.Popen(['/bin/sh', '-c',
                    'umask 077; /usr/bin/python3 "$1" --pid "$$" >"$2" 2>&1 & '
                    'exec /usr/bin/keepassxc --config "$3"', 'vault-keepass-test',
                    str(helper), str(startup_log), str(config)], stdout=log, stderr=subprocess.STDOUT)
            start = time.monotonic()
            result = wait_for(lambda: startup_log.read_text().strip() if startup_log.exists() else '',
                              'Startup observer did not finish')
            assert result == 'KeePassXC: generator opened.', result
            desktop = Atspi.get_desktop(0)
            app = wait_for(owned, 'Owned KeePassXC accessibility application missing')
            button = generator(app)
            assert state(button, Atspi.StateType.CHECKED)
            available = list(nodes(app))
            generated = next(n for n in available if n.get_role() == Atspi.Role.FILLER
                             and n.get_name() == 'Generated password')
            assert state(generated, Atspi.StateType.SHOWING), 'Generator page is hidden'
            tab = next(n for n in available if n.get_role() == Atspi.Role.PAGE_TAB
                       and n.get_name() == 'Passphrase')
            # Qt 5 exposes the current tab as FOCUSED rather than SELECTED;
            # its tab-list name also follows the currently selected page.
            assert tab.get_parent().get_name() == 'Passphrase'
            assert state(tab, Atspi.StateType.FOCUSED)
            pane = tab.get_parent().get_parent()
            spin = [n for n in nodes(pane) if n.get_role() == Atspi.Role.SPIN_BUTTON
                    and n.get_name() != 'Password length' and state(n, Atspi.StateType.SHOWING)]
            assert len(spin) == 1, 'Expected exactly one visible Passphrase word-count spin box'
            assert spin[0].get_value_iface().get_current_value() == 6
            assert observe() == 'KeePassXC: generator already open.'
            assert state(button, Atspi.StateType.CHECKED), 'Repeat launch toggled generator closed'
            results['launch-' + str(launch)] = dict(passphrase=True, words=6,
                generator=True, repeat_kept_open=True, open_seconds=round(time.monotonic()-start, 3))
            if launch == 2:
                # An explicitly selected stock About menu action creates a
                # modal dialog without opening any database or real file.
                about = next(n for n in available if n.get_role() == Atspi.Role.MENU_ITEM
                             and n.get_name() == 'About')
                assert about.get_action_iface().do_action(0)
                def modal():
                    return any(n.get_role() in (Atspi.Role.DIALOG, Atspi.Role.ALERT)
                               and state(n, Atspi.StateType.SHOWING)
                               for n in children(app))
                wait_for(modal, 'About did not expose a modal dialog')
                assert observe() == 'KeePassXC: modal window left unchanged.'
                results['modal'] = 'left unchanged'
            process.terminate()
            process.wait(timeout=5)
            process = None
            time.sleep(.1)
        (output / 'result.json').write_text(json.dumps(results, indent=2) + '\n')
        print('VAULT KEEPASSXC REAL GENERATOR STARTUP CHECK PASSED')
        print(json.dumps(results))
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            process.wait(timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--bus', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if os.getuid() == 0:
        raise SystemExit('Run this private preview as an ordinary user.')
    project = args.project.resolve(strict=True)
    if args.bus:
        bus_test(project, args.output, args.bus)
        return
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix='core-vault-preview.keepass.') as td:
        tmp = Path(td)
        for name in ('home', 'config', 'runtime', 'cache', 'data', 'tmp'):
            (tmp / name).mkdir(mode=0o700)
        hook = (project / 'config/hooks/live/0948-core-vault-private-session.hook.chroot').read_text()
        config = tmp / 'config/keepassxc.ini'
        config.write_text(hook.split("<<'KEEPASS'\n", 1)[1].split('\nKEEPASS', 1)[0])
        fields = [b'', b'', b'MIT-MAGIC-COOKIE-1', os.urandom(16)]
        auth = tmp / 'Xauthority'
        auth.write_bytes(struct.pack('>H', 65535) + b''.join(struct.pack('>H', len(f))+f for f in fields))
        auth.chmod(0o600)
        env = os.environ.copy()
        for name in ('DISPLAY', 'DBUS_SESSION_BUS_ADDRESS', 'SESSION_MANAGER'):
            env.pop(name, None)
        env.update(TMPDIR=str(tmp / 'tmp'),HOME=str(tmp / 'home'), XDG_CONFIG_HOME=str(tmp / 'config'),
            XDG_RUNTIME_DIR=str(tmp / 'runtime'), XDG_CACHE_HOME=str(tmp / 'cache'),
            XDG_DATA_HOME=str(tmp / 'data'), XAUTHORITY=str(auth),
            QT_LINUX_ACCESSIBILITY_ALWAYS_ON='1', QT_ACCESSIBILITY='1', NO_AT_BRIDGE='0')
        read_fd, write_fd = os.pipe()
        with (output / 'xvfb.log').open('w') as log:
            server = subprocess.Popen(['Xvfb', '-displayfd', str(write_fd), '-screen', '0',
                '1280x800x24', '-nolisten', 'tcp', '-auth', str(auth)], env=env,
                pass_fds=(write_fd,), stdout=log, stderr=subprocess.STDOUT)
        os.close(write_fd)
        display = os.read(read_fd, 100).decode().strip()
        os.close(read_fd)
        assert display.isdigit(), 'Private Xvfb display allocation failed'
        env['DISPLAY'] = ':' + display
        try:
            with (output / 'preview.log').open('w') as log:
                completed = subprocess.run(['dbus-run-session', '--', '/usr/bin/python3',
                    __file__, '--project', str(project), '--output', str(output), '--bus', str(config)],
                    env=env, stdout=log, stderr=subprocess.STDOUT, timeout=60)
            print((output / 'preview.log').read_text())
            if completed.returncode:
                raise SystemExit(completed.returncode)
        finally:
            server.terminate()
            server.wait(timeout=5)


if __name__ == '__main__':
    main()
