#!/usr/bin/python3
"""Check the explicit Home keyboard entry and narrowly guarded modal return."""
from pathlib import Path
import argparse,ast,xml.etree.ElementTree as ET

def check_home_keyboard(home,config,guide):
    tree=ast.parse(home)
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='VaultHome')
    assert 'VAULT_POWER_KEYBOARD_FLOW_V1' in home
    assert 'self.setAttribute(Qt.WA_ShowWithoutActivating, True)' in home
    assert 'self.setAttribute(Qt.WA_X11NetWmWindowTypeDesktop, True)' in home
    flow=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='power_question')
    text=ast.unparse(flow)
    for token in ('home_was_active = self.isActiveWindow()', 'answer == QMessageBox.No and home_was_active', 'dialog.cancel_from_active_dialog', 'button.setFocus(Qt.OtherFocusReason)', 'self.activateWindow()'):
        assert token in text,token
    for name in ('__init__','fit_screen','reap','show_home_from_background_click'):
        body=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name==name)
        assert 'self.activateWindow()' not in ast.unparse(body),'Background/startup must never steal focus'
    document=ET.fromstring(config);ns={'o':'http://openbox.org/3.4/rc'}
    f12=document.findall("o:keyboard/o:keybind[@key='F12']",ns)
    assert len(f12)==1 and [a.attrib.get('name') for a in f12[0]]==['ToggleShowDesktop']
    home_rule=document.find("o:applications/o:application[@title='Bitcoin Core Vault'][@type='desktop']",ns)
    assert home_rule is not None and home_rule.find('o:focus',ns).text=='no'
    for token in ('Home & keyboard','F12','Shift+Tab','Space','Esc'):
        assert token in guide,token

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--project',type=Path,default=Path(__file__).resolve().parents[2]);root=ap.parse_args().project.resolve()
    active=root/'config/includes.chroot';template=root/'tools/core-vault/runtime-template'
    rels=['usr/local/bin/core-vault-home','usr/share/core-vault/openbox.xml','usr/local/bin/core-vault-guide']
    guide_modules=['usr/lib/core-vault/guide_content.py','usr/lib/core-vault/guide_visuals.py']
    for rel in rels + guide_modules:
        assert (active/rel).read_bytes()==(template/rel).read_bytes(),'Keyboard runtime/template mismatch: '+rel
    for base in (active,template):
        home, config, guide = [(base/rel).read_text() for rel in rels]
        # The updated Guide keeps keyboard instructions in imported modules,
        # not in the thin launcher; inspect all packaged Guide source files.
        guide += '\n' + '\n'.join((base/rel).read_text() for rel in guide_modules)
        check_home_keyboard(home,config,guide)
    print('VAULT HOME KEYBOARD ENTRY + GUARDED CANCEL SOURCE CHECK PASSED')

if __name__=='__main__':main()
