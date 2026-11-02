#!/usr/bin/python3
"""Source consistency checks; does not access or change the running desktop."""
import ast
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
INC = ROOT / 'config/includes.chroot'
home = INC / 'usr/local/bin/core-vault-home'
text = home.read_text()
tree = ast.parse(text)
cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'VaultHome')
methods = [n.name for n in cls.body if isinstance(n, ast.FunctionDef)]
for name in ('_home_control_at', '_belongs_to_home', 'show_home_from_background_click', 'eventFilter'):
    if methods.count(name) != 1:
        raise RuntimeError('Missing or duplicate Home method: ' + name)
if 'QApplication.instance().installEventFilter(self)' not in text:
    raise RuntimeError('The Home event filter is not registered.')
if 'VAULT_BACKGROUND_CLICK_V12' not in text or 'core-vault-show-home' not in text:
    raise RuntimeError('Missing background-click integration.')
for rel in ('usr/local/bin/core-vault-home', 'usr/local/bin/core-vault-show-home',
            'usr/local/bin/core-vault-taskbar', 'usr/share/core-vault/icons/debian-white.svg', 'usr/share/core-vault/icons/debian-white.png',
            'usr/share/core-vault/openbox.xml', 'usr/share/themes/CoreVault/openbox-3/themerc'):
    a, b = INC / rel, ROOT / 'tools/core-vault/runtime-template' / rel
    if a.read_bytes() != b.read_bytes():
        raise RuntimeError('Active/runtime template mismatch: ' + rel)
helper = (INC / 'usr/local/bin/core-vault-show-home').read_text()
compile(helper, 'core-vault-show-home', 'exec')
for token in ('_NET_CLIENT_LIST_STACKING', 'XIconifyWindow', 'DESKTOP', 'DOCK'):
    if token not in helper:
        raise RuntimeError('Missing window-selection protection: ' + token)
panel = (INC / 'usr/local/bin/core-vault-taskbar').read_text()
compile(panel, 'core-vault-taskbar', 'exec')
for token in ('WA_X11NetWmWindowTypeDock', '_NET_WM_STRUT_PARTIAL', '_NET_CLOSE_WINDOW',
              'Qt.MiddleButton', 'Minimize', 'Close', 'debian-white.png',
              'VAULT_TASKBAR_VISIBILITY_V2', 'VAULT_TASKBAR_NATURAL_WIDTH_V2', 'self.hide()',
              'XDeleteProperty', 'text-align: center;'):
    if token not in panel:
        raise RuntimeError('Missing taskbar integration: ' + token)
if 'XKillClient' in panel or 'os.kill(' in panel or 'xdotool' in panel:
    raise RuntimeError('Taskbar must use addressed window-manager requests.')
xml = ET.parse(INC / 'usr/share/core-vault/openbox.xml')
ns = {'o': 'http://openbox.org/3.4/rc'}
if xml.findtext('o:theme/o:name', namespaces=ns) != 'CoreVault':
    raise RuntimeError('Openbox is not configured to use CoreVault.')
applications = xml.findall('o:applications/o:application', ns)
maximize_rules = [n for n in applications if n.find('o:maximized', ns) is not None]
if [(n.attrib, n.findtext('o:maximized', namespaces=ns)) for n in maximize_rules] != [
        ({'class': '*', 'type': 'normal'}, 'yes'),
        ({'class': '*', 'type': 'dialog'}, 'yes')]:
    raise RuntimeError('Expected initial maximization only for normal apps and dialogs.')
if any(n.find('o:size', ns) is not None or n.find('o:fullscreen', ns) is not None
       for n in maximize_rules):
    raise RuntimeError('Initial maximization must preserve size hints and the panel work area.')
if xml.findtext("o:applications/o:application[@type='desktop']/o:focus", namespaces=ns) != 'no':
    raise RuntimeError('Home desktop focus policy changed.')
theme = (INC / 'usr/share/themes/CoreVault/openbox-3/themerc').read_text()
for token in ('window.active.title.bg.color: #111111',
              'window.active.label.text.color: #ffffff',
              'window.inactive.title.bg.color: #171717'):
    if token not in theme:
        raise RuntimeError('Missing dark theme value: ' + token)
print('VAULT WINDOW BEHAVIOR + DARK CHROME + INITIAL MAXIMIZE SOURCE CHECK PASSED')
