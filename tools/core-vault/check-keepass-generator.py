#!/usr/bin/python3
"""Gate the stock KeePassXC generator integration and RAM-only defaults."""
import ast
import configparser
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
INC = ROOT / 'config/includes.chroot'
for name in ('core-vault-keepassxc', 'core-vault-open-passphrase'):
    source = INC / 'usr/local/bin' / name
    mirror = ROOT / 'tools/core-vault/runtime-template/usr/local/bin' / name
    assert source.is_file() and not source.is_symlink()
    assert mirror.read_bytes() == source.read_bytes(), name + ' mirror differs'
    assert source.stat().st_mode & 0o111, name + ' must be executable'
wrapper = (INC / 'usr/local/bin/core-vault-keepassxc').read_text()
subprocess.run(['/bin/sh', '-n', str(INC / 'usr/local/bin/core-vault-keepassxc')], check=True)
hook = (ROOT / 'config/hooks/live/0948-core-vault-private-session.hook.chroot').read_text()
for text, start, end in ((wrapper, "<<'CONFIG'\n", '\nCONFIG'),
                         (hook, "<<'KEEPASS'\n", '\nKEEPASS')):
    ini = configparser.ConfigParser(interpolation=None)
    ini.read_string(text.split(start, 1)[1].split(end, 1)[0])
    assert ini.getint('PasswordGenerator', 'Type') == 1
    assert ini.getint('PasswordGenerator', 'WordCount') == 6
    assert ini.get('PasswordGenerator', 'WordList') == 'eff_large.wordlist'
    assert not ini.getboolean('General', 'CheckForUpdates')
    assert not ini.getboolean('General', 'RememberLastDatabases')
    assert not ini.getboolean('General', 'RememberLastKeyFiles')
assert 'export QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1' in wrapper
assert '"$XDG_RUNTIME_DIR/core-vault-open-passphrase.log"' in wrapper
assert 'exec /usr/bin/keepassxc "$@"' in wrapper
observer = (INC / 'usr/local/bin/core-vault-open-passphrase').read_text()
ast.parse(observer)
for token in ('GetNameOwner', 'GetConnectionUnixProcessID', 'GetConnectionUnixUser',
              'pid != expected_pid', 'birth != expected_birth', "Path('/usr/bin/keepassxc')",
              'Atspi.StateType.MODAL', 'Atspi.StateType.CHECKED',
              'Atspi.Role.TOOL_BAR', "button.get_name() == 'Password Generator'",
              'Atspi.Role.MENU_BAR', "node.get_name() == 'Tools'", "actions.get_action_name(i) == 'Press'",
              'generator_showing(frame)', "node.get_name() == 'Generated password'",
              'attempted = True', "return 'generator action unconfirmed'",
              'os.O_NOFOLLOW', 'fcntl.LOCK_NB', 'signal.alarm(12)'):
    assert token in observer, token
for token in ('XTest', 'XSendEvent', 'xdotool', 'grabWindow', 'get_text(', 'set_text(', 'clipboard'):
    assert token not in observer.split('import fcntl', 1)[1], token
packages = (ROOT / 'config/package-lists/core-vault.list.chroot').read_text().splitlines()
for name in ('libusb-1.0-0', 'at-spi2-core', 'gir1.2-atspi-2.0', 'python3-gi'):
    assert name in packages, name
print('VAULT KEEPASSXC SIX-WORD PASSPHRASE STARTUP SOURCE CHECK PASSED')
