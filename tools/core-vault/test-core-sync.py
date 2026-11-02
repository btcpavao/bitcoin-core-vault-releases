#!/usr/bin/python3
"""Actual official Core tests in private Xvfb, disposable HOME and datadirs.
Screenshots and generic logs are test evidence. No production wallet is opened.
These tests do not establish OS network isolation or installed Vault behavior.
"""
from pathlib import Path
import argparse
import ctypes as C
import hashlib
import importlib.machinery
import importlib.util
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT/'config/includes.chroot/usr/local/bin/bitcoin-qt'
HELPER = ROOT/'config/includes.chroot/usr/local/bin/core-vault-hide-sync'
ASSETS = ROOT/'config/includes.chroot/usr/share/core-vault'
FLAGS = ['-networkactive=0', '-maxconnections=0', '-connect=0', '-listen=0',
         '-listenonion=0', '-dns=0', '-dnsseed=0', '-fixedseeds=0', '-discover=0',
         '-natpmp=0', '-walletbroadcast=0', '-server=0', '-prune=550', '-splash=0', '-lang=en']


def stop(process):
    if process is None or process.poll() is not None: return
    process.terminate()
    try: process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        process.kill(); process.wait(timeout=5)


def load_helper():
    loader = importlib.machinery.SourceFileLoader('vault_hide_test', str(HELPER))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec); loader.exec_module(module)
    return module


def worker(args):
    helper = load_helper(); x = helper.X11(); recog = helper.Recognizer(args.ocr_prefix)
    def atom(name): return x.x.XInternAtom(x.display, name.encode('ascii'), 1)
    reports = []; evidence = args.output_dir; evidence.mkdir(parents=True, exist_ok=True)
    def screenshot(name, wid):
        (evidence/name).write_bytes(recog.capture(wid))
    def record(report):
        reports.append(report)
        (evidence/'core-tests.json').write_text(json.dumps({'core_sha256':hashlib.sha256(CORE.read_bytes()).hexdigest(),
            'tests':reports,'scope':'Private Xvfb; offline Core arguments; no production HOME/datadir'},indent=2)+'\n')
    def focus(env):
        return subprocess.check_output(['xdotool', 'getwindowfocus'], env=env, text=True).strip()
    def wait_panel(proc, shown=True, timeout=12):
        deadline = time.monotonic() + timeout
        wid = None; words = []
        while time.monotonic() < deadline:
            if proc.poll() is not None: raise RuntimeError('Core exited unexpectedly')
            wid = x.window(proc.pid)
            if wid is not None:
                wait_taskbar(True)
                words = recog.words(wid)
                if (recog.panel(words) if shown else recog.hidden(words)): return wid, words
            time.sleep(.15)
        if wid is not None:
            screenshot('unrecognized-panel-state.png', wid)
            text = ' '.join(word for word, _ in words)
            (evidence/'unrecognized-panel-state.json').write_text(json.dumps({
                'expected_shown':shown, 'word_count':len(words),
                'hide_count':sum(word == 'hide' for word, _ in words),
                'matched_phrases':{phrase:phrase in text for phrase in helper.PANEL_PHRASES},
                'workarea':x.property(x.root, '_NET_WORKAREA'),
                'maximized':all(atom('_NET_WM_STATE_MAXIMIZED_'+axis) in
                    (x.property(wid, '_NET_WM_STATE') or ()) for axis in ('HORZ', 'VERT')),
            }, indent=2)+'\n')
        raise RuntimeError('Expected actual panel state not observed')
    def check_maximized(wid):
        state = x.property(wid, '_NET_WM_STATE') or ()
        if not all(atom('_NET_WM_STATE_MAXIMIZED_'+axis) in state for axis in ('HORZ', 'VERT')):
            raise RuntimeError('Actual Core did not initially maximize')
        attrs = x.attributes(wid)
        extents = x.property(wid, '_NET_FRAME_EXTENTS') or (0, 0, 0, 0)
        if (attrs.width+extents[0]+extents[1], attrs.height+extents[2]+extents[3]) != (1280, 760):
            raise RuntimeError('Actual Core did not fill the 40px panel work area')
    def observer(proc, env, name, timeout=20):
        path = evidence/(name+'.log'); log = path.open('w')
        command = ['/usr/bin/python3', str(HELPER), '--pid', str(proc.pid),
                   '--test-exe', str(CORE), '--timeout', str(timeout)]
        if args.ocr_prefix: command += ['--ocr-prefix', str(args.ocr_prefix)]
        process = subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT)
        return process, log, path
    with tempfile.TemporaryDirectory(prefix='vault-core-actual-') as td:
        private = Path(td)
        env = dict(os.environ)
        for name in ('QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH', 'QT_QPA_PLATFORM',
                     'AT_SPI_BUS_ADDRESS', 'LD_PRELOAD', 'LD_LIBRARY_PATH'):
            env.pop(name, None)
        env.update(LANG='C.UTF-8', LC_ALL='C.UTF-8')
        theme = Path(env['HOME'])/'.themes/CoreVault/openbox-3'
        theme.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT/'config/includes.chroot/usr/share/themes/CoreVault/openbox-3/themerc',
                        theme/'themerc')
        wm = subprocess.Popen(['openbox', '--sm-disable', '--config-file', str(ASSETS/'openbox.xml')],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        panel = None
        panel_geometry = Path(env['XDG_RUNTIME_DIR'])/'core-vault-taskbar-geometry.json'
        def wait_taskbar(visible, timeout=10):
            expected = (0, 0, 1280, 760 if visible else 800)
            deadline = time.monotonic()+timeout
            while time.monotonic() < deadline:
                if panel.poll() is not None:
                    raise RuntimeError('Production taskbar exited unexpectedly')
                try:
                    report = json.loads(panel_geometry.read_text())
                except (FileNotFoundError, json.JSONDecodeError):
                    time.sleep(.05)
                    continue
                wid = int(report['window_id'], 16)
                attrs = x.attributes(wid)
                strut = x.property(wid, '_NET_WM_STRUT_PARTIAL') or ()
                if (report['pid'] == panel.pid and attrs is not None
                        and attrs.map_state == (2 if visible else 0)
                        and (x.property(x.root, '_NET_WORKAREA') or ())[:4] == expected
                        and (len(strut) == 12 and strut[3] == 40 if visible else not strut)
                        and (visible or not x.property(wid, '_NET_WM_STRUT'))):
                    return
                time.sleep(.05)
            raise RuntimeError('Expected taskbar visibility and work area unavailable')
        try:
            time.sleep(.5)
            panel = subprocess.Popen(['/usr/bin/python3',
                str(ROOT/'config/includes.chroot/usr/local/bin/core-vault-taskbar'),
                '--preview', '--assets', str(ASSETS)], env=env,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            wait_taskbar(False)
            record({'test':'idle taskbar hidden', 'result':'PASS',
                    'panel_unmapped':True, 'struts_absent':True,
                    'workarea':[0, 0, 1280, 800]})
            # Start the real observer immediately with EVERY new Core PID,
            # including clean closes/reopens of the same synthetic datadir.
            # Timing ends at generic observer events, never persisted OCR text.
            case = private/'startup-latency'; case.mkdir(mode=0o700)
            home = case/'home'; home.mkdir(mode=0o700)
            runtime = case/'runtime'; runtime.mkdir(mode=0o700)
            data = case/'data'; data.mkdir(mode=0o700)
            env.update(HOME=str(home), XDG_CONFIG_HOME=str(home/'.config'),
                XDG_CACHE_HOME=str(home/'.cache'), XDG_DATA_HOME=str(home/'.local/share'),
                XDG_STATE_HOME=str(home/'.local/state'), XDG_RUNTIME_DIR=str(runtime))
            seen_pids = set()
            for run in range(args.startup_runs):
                core = obs = None; log = None
                with (evidence/('startup-core-%d.log'%run)).open('w') as output:
                    try:
                        started = time.monotonic()
                        core = subprocess.Popen([str(CORE), '-datadir='+str(data), *FLAGS],
                            env=env, stdout=output, stderr=subprocess.STDOUT)
                        if core.pid in seen_pids: raise RuntimeError('Startup test reused a Core PID')
                        seen_pids.add(core.pid)
                        obs, log, obs_path = observer(core, env, 'startup-%d-helper'%run)
                        observed = {'mapped_s':None, 'native_hide_s':None, 'hidden_verified_s':None}
                        while obs.poll() is None:
                            if time.monotonic()-started > 24: raise RuntimeError('Startup observer exceeded hard scope')
                            if core.poll() is not None: raise RuntimeError('Fresh Core exited during startup test')
                            if observed['mapped_s'] is None and x.window(core.pid) is not None:
                                observed['mapped_s'] = round(time.monotonic()-started, 3)
                                wait_taskbar(True)
                            messages = obs_path.read_text()
                            for name, message in [('native_hide_s', 'Return addressed once'),
                                                  ('hidden_verified_s', 'disappearance verified')]:
                                if observed[name] is None and message in messages:
                                    observed[name] = round(time.monotonic()-started, 3)
                            time.sleep(.01)
                        log.close(); log = None
                        if obs.returncode != 0:
                            raise RuntimeError('Fresh startup Hide failed: '+obs_path.read_text())
                        # Cover events flushed just before helper exit.
                        messages = obs_path.read_text()
                        for name, message in [('native_hide_s', 'Return addressed once'),
                                              ('hidden_verified_s', 'disappearance verified')]:
                            if observed[name] is None and message in messages:
                                observed[name] = round(time.monotonic()-started, 3)
                        wid, _ = wait_panel(core, False, 3)
                        check_maximized(wid)
                        record({'test':'cold Core startup' if run == 0 else 'fresh PID reopen '+str(run),
                            'result':'PASS', 'fresh_core_pid':core.pid, 'same_synthetic_datadir':True,
                            'initially_maximized':True, **observed})
                        print('PASS fresh Core PID startup %d: %s'%(run+1, json.dumps(observed)), flush=True)
                    finally:
                        stop(obs); stop(core)
                        if log: log.close()
                        wait_taskbar(False)
            for run in range(args.runs + 1):
                case = private/('launch-'+str(run)); case.mkdir(mode=0o700)
                home = case/'home'; home.mkdir(mode=0o700)
                runtime = case/'runtime'; runtime.mkdir(mode=0o700)
                data = case/'data'; data.mkdir(mode=0o700)
                env.update(HOME=str(home), XDG_CONFIG_HOME=str(home/'.config'),
                    XDG_CACHE_HOME=str(home/'.cache'), XDG_DATA_HOME=str(home/'.local/share'),
                    XDG_STATE_HOME=str(home/'.local/state'), XDG_RUNTIME_DIR=str(runtime))
                core = foreign = obs = None; log = None
                with (evidence/('core-'+str(run)+'.log')).open('w') as output:
                    try:
                        wallet_args = []
                        if run == args.runs:
                            wallet_tool = args.wallet_tool
                            subprocess.run([str(wallet_tool), '-datadir='+str(data), '-wallet=Vault title test', 'create'],
                                env=env,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10)
                            wallet_args = ['-wallet=Vault title test']
                        core = subprocess.Popen([str(CORE), '-datadir='+str(data), *FLAGS, *wallet_args], env=env,
                            stdout=output, stderr=subprocess.STDOUT)
                        wid, words = wait_panel(core)
                        check_maximized(wid)
                        if wallet_args and x.property(wid,'_NET_WM_NAME') != b'Bitcoin Core - Vault title test':
                            raise RuntimeError('Named empty test wallet title was not observed')
                        screenshot('launch-%d-before.png'%run, wid)
                        original_focus = None
                        if run == args.runs - 1:
                            foreign_source = case/'foreign.py'; value = case/'foreign-value.txt'
                            foreign_source.write_text("from PySide6.QtWidgets import QApplication,QWidget,QVBoxLayout,QLineEdit\nfrom PySide6.QtCore import QTimer\nfrom pathlib import Path\nimport sys\na=QApplication([]);w=QWidget();w.setWindowTitle('VAULT TEST PASSPHRASE');l=QVBoxLayout(w);e=QLineEdit();e.setEchoMode(QLineEdit.Password);l.addWidget(e);w.resize(280,100);w.move(900,50);w.show();w.activateWindow();e.setFocus();e.setText('before-')\ndef restore():\n w.showNormal();w.resize(280,100);w.move(900,50);w.activateWindow();e.setFocus()\nQTimer.singleShot(350,restore)\ndef save(): Path(sys.argv[1]).write_text(e.text())\nt=QTimer();t.timeout.connect(save);t.start(100);a.exec()\n")
                            foreign = subprocess.Popen(['/usr/bin/python3', str(foreign_source), str(value)],
                                env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                            time.sleep(1)
                            subprocess.run(['xdotool', 'type', '--clearmodifiers', 'TEST'], env=env, check=True)
                            original_focus = focus(env)
                        obs, log, obs_path = observer(core, env, 'launch-%d-helper'%run)
                        result = obs.wait(timeout=24); log.close(); log = None
                        if result != 0: raise RuntimeError('Helper did not verify native Hide: '+obs_path.read_text())
                        after_wid, after_words = wait_panel(core, False, 3)
                        if after_wid != wid: raise RuntimeError('Core main window identity changed')
                        screenshot('launch-%d-after.png'%run, wid)
                        if original_focus is not None:
                            if focus(env) != original_focus: raise RuntimeError('Foreign input focus changed')
                            subprocess.run(['xdotool', 'type', '--clearmodifiers', '--', '-AFTER'], env=env, check=True)
                            time.sleep(.3)
                            if value.read_text() != 'before-TEST-AFTER': raise RuntimeError('Foreign input changed')
                            screenshot('launch-%d-foreign-focus.png'%run, x.root)
                            stop(foreign); foreign = None
                        # Only this private test display receives deliberate mouse
                        # input to Core's recognized native synchronization label.
                        targets = [rect for text, rect in after_words if text == 'behind']
                        if len(targets) != 1: raise RuntimeError('Native reopen target not recognized')
                        left, top, width, height = targets[0]
                        subprocess.run(['xdotool', 'mousemove', '--window', str(wid),
                            str(left+width//2), str(top+height//2), 'click', '1'], env=env, check=True)
                        wait_panel(core, True, 4)
                        time.sleep(1)
                        wait_panel(core, True, 3)
                        if obs.poll() is None: raise RuntimeError('Observer remained alive after one action')
                        screenshot('launch-%d-reopened.png'%run, wid)
                        record({'test':'named empty wallet launch' if wallet_args else 'actual launch '+str(run+1), 'result':'PASS',
                            'visible_to_hidden':True, 'manual_reopen_preserved':True,
                            'initially_maximized':True, 'workarea':[0, 0, 1280, 760],
                            'foreign_focus_and_input':original_focus is not None})
                        print('PASS actual Core launch %d: visible → native Hide → hidden; reopen preserved'%(run+1), flush=True)
                    finally:
                        stop(obs); stop(foreign); stop(core)
                        if log: log.close()
                        wait_taskbar(False)
            # Early process death ends the observer before its startup TTL.
            case=private/'early-close';case.mkdir(); home=case/'home';home.mkdir();data=case/'data';data.mkdir()
            env.update(HOME=str(home),XDG_CONFIG_HOME=str(home/'.config'))
            core=subprocess.Popen([str(CORE),'-datadir='+str(data),*FLAGS],env=env,
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            obs,log,path=observer(core,env,'early-close')
            try:
                time.sleep(.15); stop(core)
                result=obs.wait(timeout=5)
                log.close(); log=None
                if 'addressed once' in path.read_text(): raise RuntimeError('Early-close test unexpectedly sent input')
                record({'test':'close during startup','result':'PASS','no_action':True})
                print('PASS early close: helper exited without input',flush=True)
            finally:
                stop(obs);stop(core)
                if log:log.close()
            # Establish a real Settings popup, then a separate Options dialog.
            case=private/'dialog';case.mkdir();home=case/'home';home.mkdir();data=case/'data';data.mkdir()
            env.update(HOME=str(home),XDG_CONFIG_HOME=str(home/'.config'))
            core=subprocess.Popen([str(CORE),'-datadir='+str(data),*FLAGS],env=env,
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            obs=None;log=None
            try:
                wid,_=wait_panel(core)
                subprocess.run(['xdotool','windowactivate','--sync',str(wid),
                    'mousemove','--window',str(wid),'65','10','click','1'],env=env,check=True)
                time.sleep(.3)
                subprocess.run(['xdotool','key','End','Return'],env=env,check=True)
                time.sleep(.6)
                screenshot('core-dialog-blocker.png',x.root)
                if x.window(core.pid) is not None: raise RuntimeError('Real Core Settings popup was not established')
                initial_focus=focus(env)
                obs,log,path=observer(core,env,'core-dialog-blocker',3)
                obs.wait(timeout=6);log.close();log=None
                if 'addressed once' in path.read_text() or focus(env)!=initial_focus:
                    raise RuntimeError('Core dialog blocker allowed an action or changed focus')
                screenshot('core-dialog-blocker-after.png',x.root)
                record({'test':'real Core Settings popup','result':'PASS','no_action':True})
                print('PASS real Core Settings popup: no action, focus unchanged',flush=True)
                # Coordinates are derived from the screenshot of this private
                # Core menu (Options is its visible last row), never host UI.
                subprocess.run(['xdotool','mousemove','--window',str(wid),
                    '100','96','click','1'],env=env,check=True)
                time.sleep(.6)
                clients=x.property(x.root,'_NET_CLIENT_LIST')
                dialogs=[w for w in clients if x.property(w,'_NET_WM_PID')==(core.pid,)
                    and x.property(w,'_NET_WM_NAME')==b'Options']
                if len(dialogs)!=1 or x.window(core.pid) is not None:
                    raise RuntimeError('Real Core Options dialog was not established')
                screenshot('core-options-dialog-before.png',x.root)
                initial_focus=focus(env)
                obs,log,path=observer(core,env,'core-options-dialog',3)
                obs.wait(timeout=6);log.close();log=None
                if 'addressed once' in path.read_text() or focus(env)!=initial_focus:
                    raise RuntimeError('Options dialog allowed an action or changed focus')
                screenshot('core-options-dialog-after.png',x.root)
                record({'test':'real Core Options dialog','result':'PASS','no_action':True})
                print('PASS real Core Options dialog: no action, focus unchanged',flush=True)
            finally:
                stop(obs);stop(core)
                if log:log.close()
            # A stalled OCR engine must be reaped within the bounded request,
            # and the next observation must use a fresh engine and screenshot.
            case=private/'ocr-timeout';case.mkdir();home=case/'home';home.mkdir();data=case/'data';data.mkdir()
            env.update(HOME=str(home),XDG_CONFIG_HOME=str(home/'.config'))
            core=subprocess.Popen([str(CORE),'-datadir='+str(data),*FLAGS],env=env,
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            try:
                wid,_=wait_panel(core)
                recog.start_worker(); stalled=recog.worker
                os.kill(stalled.pid,signal.SIGSTOP)
                started=time.monotonic()
                try: recog.words(wid,timeout=.1)
                except subprocess.TimeoutExpired: pass
                else: raise RuntimeError('Stalled OCR engine bypassed its deadline')
                elapsed=time.monotonic()-started
                if stalled.poll() is None or elapsed>1:
                    raise RuntimeError('Stalled OCR engine was not promptly reaped')
                if not recog.panel(recog.words(wid)):
                    raise RuntimeError('Fresh OCR observation did not recover after timeout')
                record({'test':'stalled OCR engine cleanup and fresh observation','result':'PASS',
                    'timeout_cleanup_s':round(elapsed,3),'no_action':True})
                print('PASS OCR timeout: engine reaped, fresh panel recognition recovered; no input',flush=True)
            finally: stop(core)
        finally:
            stop(panel)
            stop(wm)
    (evidence/'core-tests.json').write_text(json.dumps({'core_sha256':hashlib.sha256(CORE.read_bytes()).hexdigest(),
        'tests':reports,'scope':'Private Xvfb; offline Core arguments; no production HOME/datadir'},indent=2)+'\n')
    print('VAULT ACTUAL CORE NATIVE HIDE TESTS PASSED',flush=True)
    return 0


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker',action='store_true');parser.add_argument('--runs',type=int,default=3)
    parser.add_argument('--startup-runs',type=int,default=6)
    parser.add_argument('--output-dir',type=Path,required=True);parser.add_argument('--ocr-prefix',type=Path)
    parser.add_argument('--wallet-tool', type=Path, required=True, help='Verified bitcoin-wallet from the same Core release')
    args=parser.parse_args()
    args.wallet_tool=args.wallet_tool.resolve(strict=True)
    args.output_dir=args.output_dir.resolve()
    if args.ocr_prefix:args.ocr_prefix=args.ocr_prefix.resolve()
    if not 1<=args.runs<=5:parser.error('runs must be between 1 and 5')
    if not 0<=args.startup_runs<=20:parser.error('startup-runs must be between 0 and 20')
    if args.worker:return worker(args)
    for tool in ('xvfb-run','xauth','openbox','xdotool'):
        if not shutil.which(tool):raise RuntimeError('Missing private GUI test dependency: '+tool)
    with tempfile.TemporaryDirectory(prefix='vault-core-x-session-',ignore_cleanup_errors=True) as td:
        p=Path(td);home=p/'home';home.mkdir(mode=0o700);runtime=p/'run';runtime.mkdir(mode=0o700)
        env=dict(os.environ,HOME=str(home),XDG_CONFIG_HOME=str(home/'.config'),XDG_RUNTIME_DIR=str(runtime))
        env.pop('DISPLAY',None);env.pop('DBUS_SESSION_BUS_ADDRESS',None)
        command=['xvfb-run','-a','-s','-screen 0 1280x800x24 -nolisten tcp',
            'dbus-run-session','--','/usr/bin/python3',str(Path(__file__).resolve()),'--worker','--runs',str(args.runs),
            '--startup-runs',str(args.startup_runs),
            '--output-dir',str(args.output_dir), '--wallet-tool',str(args.wallet_tool)]
        if args.ocr_prefix:command+=['--ocr-prefix',str(args.ocr_prefix)]
        return subprocess.call(command,env=env)


if __name__=='__main__':
    try:raise SystemExit(main())
    except (OSError,RuntimeError,subprocess.SubprocessError) as exc:
        print('CORE TEST STOPPED:',exc,file=sys.stderr);raise SystemExit(1)
