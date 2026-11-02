#!/usr/bin/python3
"""Actual taskbar mouse controls on an owned private Xvfb desktop.

Synthetic Qt apps only. No real profiles, wallets, host desktop or global input.
"""
import argparse
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import signal
import struct
import subprocess
import tempfile
import time

ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument('--project', required=True, type=Path)
ap.add_argument('--output', required=True, type=Path)
ap.add_argument('--before-inspector', type=Path)
a = ap.parse_args()
if os.getuid() == 0:
    raise SystemExit('Run as an ordinary user.')
root = a.project.resolve(strict=True)
assets = root/'config/includes.chroot/usr/share/core-vault'
out = a.output.resolve()
out.mkdir(parents=True, exist_ok=False)
for command in ('Xvfb','openbox','xprop','xwininfo','xwd','convert'):
    if shutil.which(command) is None:
        raise SystemExit('Missing private fixture dependency: '+command)
processes, widgets, app, x, scope = [], [], None, None, None
report = {}

def run(*args):
    return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT, timeout=5)

def wait(test, message):
    deadline = time.monotonic()+10
    while time.monotonic() < deadline:
        if app:
            app.processEvents()
        if test():
            return
        time.sleep(.04)
    raise RuntimeError(message)

def spawn(argv,name,env):
    p = subprocess.Popen(argv,env=env,stdout=(out/(name+'.log')).open('w'),stderr=subprocess.STDOUT)
    processes.append(p)
    return p

def read_panel():
    try:
        return json.loads((tmp/'runtime/core-vault-taskbar-geometry.json').read_text())
    except (FileNotFoundError,json.JSONDecodeError):
        return {}

def center(rect):
    px,py,w,h = rect
    return px+w//2,py+h//2

def click(rect,button=1):
    px,py = center(rect)
    xt.XTestFakeMotionEvent(x.display,x.screen,px,py,0)
    xt.XTestFakeButtonEvent(x.display,button,1,0)
    xt.XTestFakeButtonEvent(x.display,button,0,0)
    x.lib.XSync(x.display,0)

def task_rect(w):
    return read_panel()['tasks'][hex(w)]['rect']

def screenshot(name):
    app.processEvents()
    time.sleep(.35)
    app.processEvents()
    raw = subprocess.check_output(['xwd','-root','-silent'],timeout=5)
    subprocess.run(['convert','xwd:-',str(out/(name+'.png'))],input=raw,check=True,timeout=5)

def context(w):
    menu = tmp/'runtime/core-vault-taskbar-menu.json'
    menu.unlink(missing_ok=True)
    click(task_rect(w),3)
    wait(menu.exists,'Right click did not open the task context menu.')
    values = json.loads(menu.read_text())
    assert list(values)==['Minimize','Close']
    return values

try:
    tmp = Path(tempfile.mkdtemp(prefix='core-vault-preview.taskbar.'))
    scope = tmp.name
    for name in ('home','config','cache','data','runtime'):
        (tmp/name).mkdir(mode=0o700)
    theme=tmp/'home/.themes/CoreVault/openbox-3'
    theme.mkdir(parents=True)
    shutil.copyfile(root/'config/includes.chroot/usr/share/themes/CoreVault/openbox-3/themerc',theme/'themerc')
    cookie=tmp/'Xauthority'
    fields=[b'',b'',b'MIT-MAGIC-COOKIE-1',os.urandom(16)]
    cookie.write_bytes(struct.pack('>H',65535)+b''.join(struct.pack('>H',len(f))+f for f in fields))
    cookie.chmod(0o600)
    env=os.environ.copy()
    for key in ('DISPLAY','DBUS_SESSION_BUS_ADDRESS','SESSION_MANAGER'):
        env.pop(key,None)
    env.update(HOME=str(tmp/'home'),XDG_CONFIG_HOME=str(tmp/'config'),XDG_CACHE_HOME=str(tmp/'cache'),
               XDG_DATA_HOME=str(tmp/'data'),XDG_RUNTIME_DIR=str(tmp/'runtime'),XAUTHORITY=str(cookie),
               CORE_VAULT_TASKBAR_TEST_SCOPE=scope)
    r,w=os.pipe()
    server=subprocess.Popen(['Xvfb','-displayfd',str(w),'-screen','0','1280x800x24','-nolisten','tcp','-auth',str(cookie)],
                            env=env,pass_fds=(w,),stdout=(out/'xvfb.log').open('w'),stderr=subprocess.STDOUT)
    processes.append(server)
    os.close(w)
    display=os.read(r,100).decode().strip()
    os.close(r)
    assert display.isdigit()
    env['DISPLAY']=':'+display
    os.environ.update(env)
    spawn(['openbox','--sm-disable','--config-file',str(assets/'openbox.xml')],'openbox',env)
    wait(lambda:'0x' in run('xprop','-root','_NET_SUPPORTING_WM_CHECK'),'WM did not start.')
    panel=spawn(['/usr/bin/python3',str(root/'config/includes.chroot/usr/local/bin/core-vault-taskbar'),
                 '--preview','--assets',str(assets)],'taskbar',env)
    wait(lambda:read_panel().get('visible') is False and '= 0, 0, 1280, 800' in run('xprop','-root','_NET_WORKAREA'),
         'Idle taskbar must be hidden without reserving screen space.')
    spawn(['/usr/bin/python3',str(root/'config/includes.chroot/usr/local/bin/core-vault-home'),
           '--preview','--assets',str(assets)],'home',env)
    wait((tmp/'runtime/core-vault-desktop-geometry.json').exists,'Home did not start.')
    from PySide6.QtWidgets import QApplication,QWidget,QLabel,QVBoxLayout,QDialog
    from PySide6.QtGui import QWindow
    app=QApplication(['synthetic-taskbar-apps'])
    app.setQuitOnLastWindowClosed(False)
    class Synthetic(QWidget):
        def __init__(self,name):
            super().__init__()
            self.closes=0
            self.allow_close=True
            self.setWindowTitle(name)
            row=QVBoxLayout(self)
            row.addWidget(QLabel('SYNTHETIC WINDOW ONLY — NO WALLET OR USER DATA'))
            self.resize(500,400)
        def closeEvent(self,event):
            self.closes+=1
            event.accept() if self.allow_close else event.ignore()
    idle=read_panel()
    report['initial_idle']=idle
    assert not idle['strut']
    assert idle['tasks']=={}
    idle_id=int(idle['window_id'],16)
    assert hex(idle_id) not in run('xprop','-root','_NET_CLIENT_LIST')
    report['idle_desktop_check']=run('/usr/bin/python3',str(root/'tools/core-vault/inspect-desktop.py'))
    screenshot('taskbar-idle-home')
    X11=runpy.run_path(str(root/'config/includes.chroot/usr/local/bin/core-vault-show-home'),run_name='test_x11')['X11']
    x=X11()
    home_geometry=json.loads((tmp/'runtime/core-vault-desktop-geometry.json').read_text())
    home_wrapper=QWindow.fromWinId(int(home_geometry['window_id'],16))
    confirmation=QDialog()
    confirmation.setWindowTitle('Synthetic Home confirmation')
    confirmation.setFixedSize(420,180)
    confirmation.winId()
    confirmation.windowHandle().setTransientParent(home_wrapper)
    confirmation.show()
    confirmation_id=int(confirmation.winId())
    wait(lambda:confirmation_id in x.prop(x.root,'_NET_CLIENT_LIST') and
         x.prop(confirmation_id,'WM_TRANSIENT_FOR')==[int(home_geometry['window_id'],16)],
         'Synthetic Home confirmation did not map with its managed Home parent.')
    wait(lambda:read_panel().get('visible') is False,'A Home-owned confirmation incorrectly showed the taskbar.')
    if a.before_inspector:
        before=subprocess.run(['/usr/bin/python3',str(a.before_inspector)],env=env,
                              stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=5)
        assert before.returncode!=0,'Baseline inspector unexpectedly accepted Home-only confirmation.'
        report['baseline_home_confirmation_mismatch']=before.stdout
    report['home_confirmation_desktop_check']=run('/usr/bin/python3',str(root/'tools/core-vault/inspect-desktop.py'))
    confirmation.close()
    wait(lambda:confirmation_id not in x.prop(x.root,'_NET_CLIENT_LIST'),'Owned Home confirmation did not close.')
    home_wrapper=None
    first,second=Synthetic('Bitcoin Core'),Synthetic('Password Generator – KeePassXC')
    widgets += [first,second]
    first.show(); second.show()
    one,two=int(first.winId()),int(second.winId())
    xt=C.CDLL('libXtst.so.6')
    xt.XTestFakeMotionEvent.argtypes=[C.c_void_p,C.c_int,C.c_int,C.c_int,C.c_ulong]
    xt.XTestFakeButtonEvent.argtypes=[C.c_void_p,C.c_uint,C.c_int,C.c_ulong]
    wait(lambda:all(hex(w) in read_panel().get('tasks',{}) for w in (one,two)),'Synthetic tasks did not appear.')
    wait(lambda:read_panel().get('visible') is True and '= 0, 0, 1280, 760' in run('xprop','-root','_NET_WORKAREA'),
         'First app did not show the bar and reserve 40 pixels.')
    initial=read_panel()
    assert initial['panel']==[0,760,1280,40]
    assert initial['home']==[0,760,40,40],initial['home']
    assert len(initial['tasks'])==2,'Protected Home/DOCK were included as tasks.'
    wid=int(initial['window_id'],16)
    assert x.atom('_NET_WM_WINDOW_TYPE_DOCK') in x.prop(wid,'_NET_WM_WINDOW_TYPE')
    report['panel']=initial
    for task in initial['tasks'].values():
        assert task['text']==task['title'],'An uncongested app title was elided.'
        assert task['rect'][2]==task['natural_width']
    assert 50 < initial['tasks'][hex(one)]['rect'][2] < 160,'Bitcoin Core tab has unnecessary width.'
    assert initial['tasks'][hex(two)]['rect'][2] > initial['tasks'][hex(one)]['rect'][2]
    report['active_desktop_check']=run('/usr/bin/python3',str(root/'tools/core-vault/inspect-desktop.py'))
    screenshot('taskbar-before-home')
    from PySide6.QtGui import QImage
    image=QImage(str(out/'taskbar-before-home.png'))
    white_pixels=[(px,py-760) for py in range(760,800) for px in range(40)
              if min(image.pixelColor(px,py).red(),image.pixelColor(px,py).green(),
                     image.pixelColor(px,py).blue()) > 230]
    white=len(white_pixels)
    assert white > 40,'The white Debian icon did not render in its Home button.'
    report['white_debian_logo_pixels']=white
    bounds=[min(p[0] for p in white_pixels),min(p[1] for p in white_pixels),
            max(p[0] for p in white_pixels),max(p[1] for p in white_pixels)]
    assert (abs((bounds[0]+bounds[2])/2-19.5)<=2 and abs((bounds[1]+bounds[3])/2-19.5)<=2), \
        'The Debian artwork is not centered inside its Home hover square.'
    report['white_debian_logo_bounds']=bounds
    click(initial['home'])
    wait(lambda:all(x.minimized(w) for w in (one,two)),'Home button did not minimize both applications.')
    assert first.closes==second.closes==0
    assert panel.poll() is None
    assert read_panel()['visible'] and read_panel()['strut'][3]==40
    assert '= 0, 0, 1280, 760' in run('xprop','-root','_NET_WORKAREA')
    report['home_button']='PASS: both apps minimized, no close events'
    screenshot('taskbar-home')
    click(task_rect(one))
    wait(lambda:not x.minimized(one),'Left click did not restore selected application.')
    assert x.minimized(two),'Restoring one task affected the other.'
    menu=context(one)
    report['context_menu_rects']=menu
    screenshot('taskbar-context-menu')
    click(menu['Minimize'])
    wait(lambda:x.minimized(one),'Context Minimize did not minimize selected app.')
    assert first.closes==second.closes==0
    report['right_minimize']='PASS'
    click(task_rect(one))
    wait(lambda:not x.minimized(one),'Second restore failed.')
    # First refuse Close to prove the panel sends normal WM_DELETE_WINDOW,
    # preserves application consent, and never kills a process/client.
    first.allow_close=False
    menu=context(one)
    click(menu['Close'])
    wait(lambda:first.closes==1,'Context Close did not reach the application close handler.')
    assert one in x.prop(x.root,'_NET_CLIENT_LIST')
    assert first.isVisible() and panel.poll() is None
    report['application_close_refusal']='PASS: app close handler retained its window'
    first.allow_close=True
    menu=context(one)
    click(menu['Close'])
    wait(lambda:one not in x.prop(x.root,'_NET_CLIENT_LIST'),'Context Close did not close selected app.')
    assert first.closes==2 and second.closes==0
    report['right_close']='PASS: addressed application close handler'
    click(task_rect(two),2)
    wait(lambda:two not in x.prop(x.root,'_NET_CLIENT_LIST'),'Middle click did not close selected app.')
    assert second.closes==1 and panel.poll() is None
    report['middle_close']='PASS: addressed application close handler'
    wait(lambda:not read_panel().get('tasks'),'Closed tasks did not disappear.')
    wait(lambda:read_panel().get('visible') is False and '= 0, 0, 1280, 800' in run('xprop','-root','_NET_WORKAREA'),
         'Closing the last app must hide the bar and release its strut.')
    assert not x.prop(wid,'_NET_WM_STRUT_PARTIAL') and not x.prop(wid,'_NET_WM_STRUT')
    assert wid not in x.prop(x.root,'_NET_CLIENT_LIST')
    report['final_idle_desktop_check']=run('/usr/bin/python3',str(root/'tools/core-vault/inspect-desktop.py'))
    screenshot('taskbar-final-home')
    # The same panel process must reappear for a later application launch.
    third=Synthetic('Editor')
    widgets.append(third)
    third.show()
    three=int(third.winId())
    wait(lambda:hex(three) in read_panel().get('tasks',{}) and read_panel().get('visible') is True,
         'Taskbar did not reappear after a later application launch.')
    assert panel.poll() is None
    third.close()
    wait(lambda:read_panel().get('visible') is False and '= 0, 0, 1280, 800' in run('xprop','-root','_NET_WORKAREA'),
         'Relaunch cycle left a visible bar or stale strut.')
    report['later_launch_cycle']='PASS'
    cycles=[]
    def verify_home_capture(name, idle):
        screenshot(name)
        image=QImage(str(out/(name+'.png')))
        geometry=json.loads((tmp/'runtime/core-vault-desktop-geometry.json').read_text())
        samples=[]
        card_width=geometry['card_sizes'][0][0]
        first_x=(image.width()-(5*card_width+4*14))//2
        # Interior points shared by both 0 px and 40 px bottom reservations.
        # Geometry reports can precede a deferred Qt layout after strut changes.
        for cy in (320,480):
            for column in range(5):
                color=image.pixelColor(first_x+column*(card_width+14)+18,cy)
                samples.append([color.red(),color.green(),color.blue()])
        assert all(value==[21,21,21] for value in samples),'Home cards did not paint in '+name+': '+str(samples)
        footer=sum(1 for py in range(760,800) for px in range(550,730)
                   if max(image.pixelColor(px,py).red(),image.pixelColor(px,py).green(),
                          image.pixelColor(px,py).blue())>80)
        if idle:
            assert footer>10,'Idle Home retains an unnecessary 40-pixel footer margin.'
        return dict(path=str(out/(name+'.png')),sha256=hashlib.sha256((out/(name+'.png')).read_bytes()).hexdigest(),
                    card_pixels=samples,idle_footer_pixels=footer)
    for index in range(5):
        cycle=Synthetic('Cycle '+str(index+1))
        widgets.append(cycle)
        cycle.show()
        cycle_id=int(cycle.winId())
        wait(lambda:hex(cycle_id) in read_panel().get('tasks',{}) and read_panel().get('visible') is True
             and '= 0, 0, 1280, 760' in run('xprop','-root','_NET_WORKAREA'),
             'Cycle app did not show/reserve its taskbar.')
        click(read_panel()['home'])
        wait(lambda:x.minimized(cycle_id),'Cycle Home button did not minimize its app.')
        assert read_panel()['visible'] and read_panel()['strut'][3]==40
        shown=verify_home_capture('cycle-'+str(index+1)+'-home-with-task',False)
        cycle.close()
        wait(lambda:read_panel().get('visible') is False and '= 0, 0, 1280, 800' in run('xprop','-root','_NET_WORKAREA'),
             'Cycle close did not hide/release its taskbar.')
        assert not x.prop(wid,'_NET_WM_STRUT_PARTIAL') and not x.prop(wid,'_NET_WM_STRUT')
        idle=verify_home_capture('cycle-'+str(index+1)+'-idle-home',True)
        cycles.append(dict(index=index+1,shown=shown,idle=idle))
    report['five_dynamic_cycles']=cycles
    report['final_panel']=read_panel()
    report.update(result='PASS',display=env['DISPLAY'],helper_sha256=hashlib.sha256(
                  (root/'config/includes.chroot/usr/local/bin/core-vault-taskbar').read_bytes()).hexdigest())
    (out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    print('VAULT TASKBAR HOME / CONTEXT MINIMIZE / CONTEXT CLOSE / MIDDLE CLOSE X11 TEST PASSED')
finally:
    for widget in widgets:
        widget.allow_close=True
        widget.close()
    if x:
        x.close()
    if scope:
        token=('CORE_VAULT_TASKBAR_TEST_SCOPE='+scope).encode()
        for path in Path('/proc').glob('[0-9]*'):
            try:
                if int(path.name)!=os.getpid() and token in (path/'environ').read_bytes().split(b'\0'):
                    os.kill(int(path.name),signal.SIGTERM)
            except (FileNotFoundError,ProcessLookupError,PermissionError):
                pass
    for process in reversed(processes):
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
    if 'tmp' in globals():
        shutil.rmtree(tmp,ignore_errors=True)
