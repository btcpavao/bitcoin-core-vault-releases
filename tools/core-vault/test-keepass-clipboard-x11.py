#!/usr/bin/python3
"""Stock KeePassXC clipboard test; private Xvfb/D-Bus and disposable profile only."""
import argparse
import configparser
import json
import os
from pathlib import Path
import struct
import signal
import resource
import subprocess
import tempfile
import time

def bus_test(project, output, config):
    # Coordinates verified against stock Debian KeePassXC 2.7.10, 800x600,
    # on the private 1280x800 Xvfb display; never the user's desktop.
    from PySide6.QtWidgets import QApplication, QLineEdit
    app=QApplication(['synthetic-clipboard-reader'])
    version=subprocess.check_output(['/usr/bin/keepassxc','--version'],text=True).strip()
    assert '2.7.10' in version,'Revalidate coordinates for this KeePassXC version'
    results={'version':version,'scope':'Stock host app with image profile; VM acceptance pending'}
    process=None
    def wait(seconds):
        end=time.monotonic()+seconds
        while time.monotonic()<end:app.processEvents();time.sleep(.05)
    def click(x,y):
        subprocess.run(['xdotool','mousemove',str(x),str(y),'click','1'],check=True)
        wait(.4)
    def settings(launch):
        click(637,54);click(58,275)
        shot=app.primaryScreen().grabWindow(0)
        shot.save(str(output/('security-'+str(launch)+'.png')))
        pic=shot.toImage()
        marker=pic.pixelColor(20,280)
        assert marker.green()>marker.red()+10,'Security page was not displayed'
        dark=sum(pic.pixelColor(x,y).lightness()<100 for x in range(140,152) for y in range(167,178))
        assert (dark>5)==(launch==2),'Unexpected actual Settings checkbox state'
        results['launch-'+str(launch)+'-checkbox-enabled']=dark>5
    try:
        for launch in range(3):
            print('Launch',launch,flush=True)
            process=subprocess.Popen(['/usr/bin/keepassxc','--config',str(config)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            wait(4);assert process.poll() is None
            windows=subprocess.check_output(['xdotool','search','--onlyvisible','--pid',str(process.pid)],text=True).split()
            assert len(windows)==1,'Expected one isolated main window'
            subprocess.run(['xdotool','windowmove',windows[0],'0','0','windowsize',windows[0],'800','600'],check=True)
            wait(.4)
            settings(launch);click(750,551)
            click(595,54);click(713,136)
            secret=app.clipboard().text();assert secret,'Generator did not copy'
            if launch<2:
                wait(31)
                field=QLineEdit();field.paste()
                assert field.text()==secret,'Clipboard cleared before 31 seconds'
                field.clear();results['launch-'+str(launch)+'-paste-after-31s']=True
                print('Paste after 31 seconds PASSED',flush=True)
            else:
                wait(12);assert not app.clipboard().text(),'Enabled timeout did not clear'
                results['enabled-timeout-cleared']=True
            secret=None
            click(690,543)
            if launch==1:
                click(637,54);click(58,275);click(145,172);click(750,551)
                assert 'ClearClipboard=true' in config.read_text()
            process.terminate();process.wait(timeout=5);process=None
            assert 'ClearClipboard='+('true' if launch>=1 else 'false') in config.read_text()
        (output/'result.json').write_text(json.dumps(results,indent=2)+'\n')
        print(json.dumps(results),flush=True)
        print('VAULT KEEPASSXC CLIPBOARD DEFAULT AND USER PREFERENCE TEST PASSED',flush=True)
    finally:
        if process is not None and process.poll() is None:
            process.terminate();process.wait(timeout=5)
        app.clipboard().clear()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--project',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--bus',type=Path)
    args=parser.parse_args()
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    project=args.project.resolve(strict=True)
    if args.bus:
        bus_test(project,args.output,args.bus);return
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=False)
    with tempfile.TemporaryDirectory(prefix='vault-clipboard-',dir='/dev/shm') as directory:
        tmp=Path(directory)
        for name in ('home','config','runtime','cache','data','tmp'):
            (tmp/name).mkdir(mode=0o700)
        config=tmp/'config/keepassxc.ini'
        defaults=(project/'config/includes.chroot/etc/skel/.config/keepassxc/keepassxc.ini').read_text()
        assert 'ClearClipboard=false' in defaults
        # Test-only: allow isolated test process alongside an existing host app.
        # Production image/launcher settings and the host profile are untouched.
        config.write_text(defaults.replace('[General]','[General]\nSingleInstance=false'))
        fields=[b'',b'',b'MIT-MAGIC-COOKIE-1',os.urandom(16)]
        auth=tmp/'Xauthority'
        auth.write_bytes(struct.pack('>H',65535)+b''.join(struct.pack('>H',len(f))+f for f in fields));auth.chmod(0o600)
        env=os.environ.copy()
        for name in ('DISPLAY','DBUS_SESSION_BUS_ADDRESS','SESSION_MANAGER'):env.pop(name,None)
        env.update(HOME=str(tmp/'home'),TMPDIR=str(tmp/'tmp'),XDG_CONFIG_HOME=str(tmp/'config'),
            XDG_RUNTIME_DIR=str(tmp/'runtime'),XDG_CACHE_HOME=str(tmp/'cache'),XDG_DATA_HOME=str(tmp/'data'),XDG_DATA_DIRS=str(tmp/'data'),GSETTINGS_SCHEMA_DIR='/usr/share/glib-2.0/schemas',
            XAUTHORITY=str(auth),QT_QPA_PLATFORMTHEME='',GTK_USE_PORTAL='0',QT_NO_XDG_DESKTOP_PORTAL='1',QT_LINUX_ACCESSIBILITY_ALWAYS_ON='1',QT_ACCESSIBILITY='1',NO_AT_BRIDGE='1')
        read,write=os.pipe()
        with (output/'xvfb.log').open('w') as log:
            server=subprocess.Popen(['Xvfb','-displayfd',str(write),'-screen','0','1280x800x24',
                '-nolisten','tcp','-auth',str(auth)],env=env,pass_fds=(write,),stdout=log,stderr=log)
        os.close(write);display=os.read(read,100).decode().strip();os.close(read)
        assert display.isdigit()
        env['DISPLAY']=':'+display
        try:
            with (output/'preview.log').open('w') as log:
                done=subprocess.Popen(['dbus-run-session','--','/usr/bin/python3',__file__,
                    '--project',str(project),'--output',str(output),'--bus',str(config)],
                    env=env,stdout=log,stderr=log,start_new_session=True)
                try:done.wait(timeout=150)
                finally:
                    try:os.killpg(done.pid,signal.SIGTERM)
                    except ProcessLookupError:pass
                    time.sleep(.3)
                    try:os.killpg(done.pid,signal.SIGKILL)
                    except ProcessLookupError:pass
                    done.wait(timeout=5)
            print((output/'preview.log').read_text())
            raise SystemExit(done.returncode)
        finally:
            server.terminate();server.wait(timeout=5)

if __name__=='__main__':main()
