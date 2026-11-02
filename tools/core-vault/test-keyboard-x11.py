#!/usr/bin/python3
"""Native keyboard-only entry and power-cancel flow; no fixture focus on Home."""
import argparse,json,os,runpy,subprocess,sys,time
from pathlib import Path
assert os.environ.get('CORE_VAULT_ISOLATED_GUI_TEST')=='1' and os.environ.get('QT_QPA_PLATFORM')=='xcb'
p=argparse.ArgumentParser();p.add_argument('--project',required=True,type=Path);p.add_argument('--output',required=True,type=Path);p.add_argument('--size',required=True);a=p.parse_args();source=a.project/'config/includes.chroot/usr/local/bin/core-vault-home';assets=a.project/'config/includes.chroot/usr/share/core-vault';sys.argv=[str(source),'--preview','--assets',str(assets)];m=runpy.run_path(str(source),run_name='keyboard_home')
from PySide6.QtCore import QTimer,QEventLoop,QSize
from PySide6.QtGui import QFont,QIcon
from PySide6.QtWidgets import QApplication,QMessageBox
app=QApplication(['vault-keyboard-test']);app.setStyle('Fusion');app.setFont(QFont('DejaVu Sans',10));QIcon.setThemeName('Adwaita');QIcon.setFallbackThemeName('hicolor')
def wait(ms):
 loop=QEventLoop();QTimer.singleShot(ms,loop.quit);loop.exec();app.processEvents()
def xdo(*args):
 r=subprocess.run(['xdotool',*map(str,args)],text=True,capture_output=True,timeout=3)
 if r.returncode:raise RuntimeError(r.stderr)
 return r.stdout.strip()
editor_state=a.output/(a.size+'-foreign-editor.json');editor_state.unlink(missing_ok=True);editor=subprocess.Popen(['/usr/bin/python3',str(Path(__file__).with_name('keyboard-foreign-editor.py')),str(editor_state)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
try:
 for _ in range(40):
  if editor_state.exists():break
  wait(50)
 assert editor_state.exists();editor_id=json.loads(editor_state.read_text())['window'];xdo('windowactivate',editor_id);wait(100);xdo('type','--clearmodifiers','START');wait(100)
 w=m['VaultHome']();w.show();wait(300);home_id=int(w.winId());m['args'].preview=False
 real_run=subprocess.run
 def guarded_run(command,*args,**kwargs):
  if command and any('systemctl' in str(x) or 'sudo' in str(x) for x in command):raise AssertionError('Power backend dispatch attempted')
  return real_run(command,*args,**kwargs)
 m['subprocess'].run=guarded_run
 results={'resolution':a.size,'entry':'native F12, then native Tab/ShiftTab and Space','home_fixture_focus_calls':0,'power_backend_calls':0,'states':[],'dialogs':[]}
 def showing():return subprocess.run(['xprop','-root','_NET_SHOWING_DESKTOP'],capture_output=True,text=True).stdout.strip().endswith('= 1')
 def state(name):
  f=app.focusWidget();results['states'].append({'step':name,'x_input_focus':int(xdo('getwindowfocus')),'home_active':w.isActiveWindow(),'qt_focus':f.accessibleName() if f else None,'qt_has_focus':f.hasFocus() if f else False,'showing_desktop':showing()})
 def screenshot(name):
  filename=a.size+'-'+name+'.png';assert app.primaryScreen().grabWindow(0).save(str(a.output/filename));return filename
 assert int(xdo('getwindowfocus'))==editor_id and not w.isActiveWindow();xdo('type','--clearmodifiers','KEEP');wait(100);assert json.loads(editor_state.read_text())['text']=='STARTKEEP';state('Home startup preserves foreign input');screenshot('startup-foreign-input')
 xdo('key','F12');wait(180);assert showing() and int(xdo('getwindowfocus'))==home_id;state('natural F12 entry')
 xdo('key','F12');wait(180);assert not showing() and int(xdo('getwindowfocus'))==editor_id;xdo('type','--clearmodifiers','BACK');wait(100);assert json.loads(editor_state.read_text())['text']=='STARTKEEPBACK';state('F12 toggle back preserves editor input');screenshot('f12-toggle-back')
 xdo('key','F12');wait(150);xdo('key','Tab');wait(100);assert app.focusWidget() is w.restart_button and w.restart_button.hasFocus();state('F12 Tab reaches Restart');screenshot('restart-keyboard-focus')
 errors=[]
 def cancel_question(key,title):
  def cancel():
   box=app.activeModalWidget()
   try:
    assert isinstance(box,m['PowerQuestion']) and box.isActiveWindow();assert int(xdo('getwindowfocus'))==int(box.winId()), 'Modal lacks native X input focus';assert box.windowTitle()==title;assert box.standardButton(box.defaultButton())==QMessageBox.No
    capture=screenshot(title.lower().replace(' ','-')+'-'+key.lower());results['dialogs'].append({'title':title,'key':key,'default':'No','native_x_focus':int(xdo('getwindowfocus')),'dialog_xid':int(box.winId()),'screenshot':capture})
    xdo('key',key)
   except Exception as exc:
    errors.append(str(exc))
    if isinstance(box,QMessageBox):box.done(int(QMessageBox.No))
  QTimer.singleShot(180,cancel);xdo('key','space');wait(500);assert not errors,errors;assert app.activeModalWidget() is None
 for button,key,title in ((w.restart_button,'Return','Restart Bitcoin Core Vault'),(w.shutdown_button,'Escape','Shut down Bitcoin Core Vault'),(w.restart_button,'Escape','Restart Bitcoin Core Vault'),(w.shutdown_button,'Return','Shut down Bitcoin Core Vault')):
  current=app.focusWidget()
  if current is not button:xdo('key','Tab' if button is w.shutdown_button else 'shift+Tab');wait(100)
  assert app.focusWidget() is button and button.hasFocus();cancel_question(key,title);wait(200)
  state(title+' cancelled via '+key)
  assert int(xdo('getwindowfocus'))==home_id and app.focusWidget() is button and button.hasFocus(), 'Keyboard flow did not return to power button'
  screenshot('after-'+('restart' if button is w.restart_button else 'shutdown')+'-'+key.lower())
 # Explicit foreign activation while a modal is open must never trigger a return to background Home.
 def foreign_during_modal():
  box=app.activeModalWidget()
  try:
   assert isinstance(box,m['PowerQuestion']), 'PowerQuestion missing for foreign case';xdo('key','F12');wait(200);state('F12 while modal open');results['dialogs'].append({'case':'F12 during modal','showing_desktop':showing(),'screenshot':screenshot('f12-during-modal')})
   xdo('windowactivate',editor_id);wait(250);state('foreign activation while modal open');assert int(xdo('getwindowfocus'))==editor_id, 'Foreign editor was not given X input focus';assert not box.isActiveWindow(), 'Home power dialog remained active after foreign activation';screenshot('foreign-focus-during-modal');box.done(int(QMessageBox.No))
  except Exception as exc:
   errors.append(repr(exc));(a.output/(a.size+'-failure-states.json')).write_text(json.dumps(results,indent=2)+'\n')
   if isinstance(box,QMessageBox):box.done(int(QMessageBox.No))
 QTimer.singleShot(180,foreign_during_modal);xdo('key','space');wait(600);assert not errors,errors;assert int(xdo('getwindowfocus'))==editor_id and not w.isActiveWindow();xdo('type','--clearmodifiers','FOREIGN');wait(100);assert json.loads(editor_state.read_text())['text']=='STARTKEEPBACKFOREIGN';state('Foreign focused programmatic No does not steal focus');screenshot('foreign-focus-preserved')
 (a.output/(a.size+'-result.json')).write_text(json.dumps(results,indent=2)+'\n');print('PASS '+a.size+': native F12 entry/toggle, Tab/ShiftTab, both power buttons via Space, both No/Enter and Esc return focus, foreign cancellation guard, startup input preserved, no backend',flush=True);w.reaper.stop();w.deleteLater();app.processEvents()
finally:
 editor.terminate()
 try:editor.wait(timeout=2)
 except subprocess.TimeoutExpired:editor.kill();editor.wait(timeout=2)
