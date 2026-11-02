#!/usr/bin/python3
"""Owned, headless candidate VM evidence; no host disks, network or desktop input.

Normal firmware boot and a normal Vault Terminal deliver the synthetic probe.
Optional installation uses only the new owned virtual disk and native wizard.
Uncovered GUI/recovery cases remain explicit pending items.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import stat
import subprocess
import sys
import time
import uuid

HERE = Path(__file__).resolve().parent
FORENSIC_SHA256 = 'e1cf3e233b4934946847fd064bfbfcf59d7b90b413484ba3c2fa7822b69d9bb9'
RESET_SHA256 = '74c230e62e502bf0483965892c3b67e9b78ebd81aff79f816dfbe5e3fccd437f'
RESET_PROBE_SHA256 = 'ae0e3a57a40b958c08af7d00863e45eca585e9adb3bf63b6be3837264e5b24c9'
RESET_RUNNER_SHA256 = 'f18e3b96fbd817167bfd23b9874e60d2c541fe2d2fc70d64951ed82fc402b771'
VIRTUAL_DISK_BYTES = 24 * 1024**3


def require(ok, message):
    if not ok: raise RuntimeError(message)


def plain(path):
    path = Path(os.path.abspath(path))
    require(',' not in str(path), 'Commas in QEMU paths are unsupported.')
    for p in (path, *path.parents):
        require(not p.is_symlink(), 'Symlinked fixture or ISO path refused.')
    return path


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def run(args, **kw):
    return subprocess.run(args, check=True, timeout=kw.pop('timeout', 30), **kw)


def grub_menu_ocr(image, primary_text):
    """Recognize only the frozen dual-entry GRUB menu; retain the raw PNG.

    The selected inverse-video row is ignored by whole-screen Tesseract.
    Derive two enlarged OCR inputs from its actual bright-row geometry.
    """
    from PIL import Image, ImageOps, ImageStat
    if 'gnu grub' not in primary_text.lower():return None
    with Image.open(image) as source:gray = source.convert('L')
    width, height = gray.size
    first, last = round(width*.035), round(width*.965)
    bright = []
    for y in range(round(height*.05),round(height*.30)):
        values = list(gray.crop((first,y,last,y+1)).getdata())
        if sum(value>=225 for value in values)/len(values)>.75:bright.append(y)
    if not bright:return None
    runs = []
    for y in bright:
        if not runs or y!=runs[-1][-1]+1:runs.append([y])
        else:runs[-1].append(y)
    runs = [group for group in runs if 12<=len(group)<=24]
    if len(runs)!=1:return None
    top, row_height = runs[0][0],len(runs[0])
    middle = top+row_height//2
    whites = [x for x in range(width) if gray.getpixel((x,middle))>=225]
    if not whites or max(whites)-min(whites)<width*.85:return None
    cell = row_height//2
    left, right = min(whites)+cell,max(whites)-cell
    records = []
    for label,box in [('live',(left,top-1,right,top+row_height-1)),
                      ('install',(left,top+row_height-1,right,top+2*row_height+2))]:
        crop = gray.crop(box)
        if ImageStat.Stat(crop).mean[0]<128:crop = ImageOps.invert(crop)
        derived = image.with_name(image.stem+'-grub-'+label+'-ocr-input.png')
        crop.resize((crop.width*4,crop.height*4),Image.Resampling.LANCZOS).save(derived)
        result = run(['tesseract',str(derived),'stdout','-l','eng','--psm','7'],capture_output=True,text=True)
        records.append({'entry':label,'text':result.stdout.strip(),'ocr_input':derived.name,'box':list(box)})
    def one_glyph(actual, expected):
        if actual==expected:return True
        if len(actual)==len(expected):return sum(a!=b for a,b in zip(actual,expected))==1
        if abs(len(actual)-len(expected))!=1:return False
        longer,shorter = (actual,expected) if len(actual)>len(expected) else (expected,actual)
        return any(longer[:i]+longer[i+1:]==shorter for i in range(len(longer)))
    def matches(text, expected):
        actual = re.findall(r'[a-z]+',text.lower())
        return len(actual)==len(expected) and all(
            one_glyph(a,b) if b in ('bitcoin','vault') else a==b for a,b in zip(actual,expected))
    if not (matches(records[0]['text'],['start','bitcoin','core','vault','live','ram'])
            and matches(records[1]['text'],['install','bitcoin','core','vault'])):return None
    return {'method':'verified-GNU-GRUB-header-and-two-row-Lanczos4x-psm7',
            'raw_screenshot':image.name,'entries':records,'allowed_one_glyph_words':['bitcoin','vault']}


def installer_button_words(screen,label):
    """OCR observed native white button pixels; retain raw and derived evidence."""
    from PIL import Image
    image,rows,text=screen
    with Image.open(image) as capture:
        gray=capture.convert('L');width,height=gray.size
        low,high=(round(height*.3),round(height*.85)) if label=='installer-final-confirmation' else (round(height*.65),round(height*.9))
        bright=[y for y in range(low,high) if sum(value>=235 for value in gray.crop((0,y,width,y+1)).getdata())>=80]
        groups=[]
        for y in bright:
            if not groups or y!=groups[-1][-1]+1:groups.append([y])
            else:groups[-1].append(y)
        rectangles=[]
        for group in groups:
            if not 20<=len(group)<=65:continue
            top,bottom=group[0],group[-1]+1
            columns=[x for x in range(width) if sum(gray.getpixel((x,y))>=235 for y in range(top,bottom))>=(bottom-top)*.5]
            runs=[]
            for x in columns:
                if not runs or x!=runs[-1][-1]+1:runs.append([x])
                else:runs[-1].append(x)
            for run in runs:
                if 80<=len(run)<=800:rectangles.append((run[0],top,run[-1]+1,bottom))
        for index,(left,top,right,bottom) in enumerate(rectangles):
            bounds=(left+2,top+2,right-2,bottom-2);crop=capture.crop(bounds)
            derived=image.with_name(image.stem+'-native-button-'+str(index)+'-4x.png')
            crop.resize((crop.width*4,crop.height*4),Image.Resampling.LANCZOS).save(derived)
            result=subprocess.run(['tesseract',str(derived),'stdout','-l','eng','--psm','7','tsv'],capture_output=True,text=True,timeout=15,check=True)
            observed=[]
            for line in result.stdout.splitlines()[1:]:
                fields=line.split('\t')
                if len(fields)==12 and fields[11].strip():
                    x,y,w,h=(int(fields[i])/4 for i in (6,7,8,9));observed.append((fields[11],bounds[0]+x,bounds[1]+y,w,h))
            if observed:
                rows=[row for row in rows if not (left<=row[1]+row[3]/2<right and top<=row[2]+row[4]/2<bottom)]+observed
            derived.with_suffix('.json').write_text(json.dumps({'raw_screenshot':image.name,'raw_sha256':digest(image),'button_bounds':[left,top,right,bottom],'crop':bounds,'scale':4,'method':'observed-white-button-Lanczos-PSM7','coordinates':'original-screen'})+'\n')
    return image,rows,' '.join(row[0] for row in rows)


def installer_screen_words(image,label):
    """Read small installer captions from the actual full frame at 3x scale."""
    from PIL import Image
    derived=image.with_name(image.stem+'-full-3x.png')
    with Image.open(image) as im:im.resize((im.width*3,im.height*3),Image.Resampling.LANCZOS).save(derived)
    result=subprocess.run(['tesseract',str(derived),'stdout','-l','eng','tsv'],capture_output=True,text=True,timeout=20,check=True)
    rows=[]
    for line in result.stdout.splitlines()[1:]:
        fields=line.split('\t')
        if len(fields)==12 and fields[11].strip():rows.append((fields[11],*(int(fields[i])/3 for i in (6,7,8,9))))
    derived.with_suffix('.json').write_text(json.dumps({'raw_screenshot':image.name,'raw_sha256':digest(image),'scale':3,'method':'full-frame-Lanczos','coordinates':'original-screen'})+'\n')
    return installer_button_words((image,rows,' '.join(row[0] for row in rows)),label)


class VM:
    def __init__(self, root, args):
        self.root, self.args = root, args
        self.pidfd = None
        self.never_quit = False
        self.log = (root/'qemu.log').open('xb')
        try:
            self.p = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=self.log,
                                      stderr=self.log, start_new_session=True)
        except BaseException:
            self.log.close()
            raise
        try:
            # /proc may expose the freshly spawned child's transient argv.
            # Wait only for the exact launched argv, before connecting or acting.
            until = time.monotonic()+1
            identity = self.identity()
            while identity[0] != self.args and self.p.poll() is None and time.monotonic() < until:
                time.sleep(.02)
                identity = self.identity()
            require(identity[0] == self.args, 'Own QEMU initial argv identity does not match.')
            self.birth = identity[1]
        except BaseException:
            if self.p.returncode is None:self.p.kill()
            self.p.wait(timeout=15);self.log.close()
            raise
        self.sock = None
        self.reader = None
        self.counter = 0

    def identity(self):
        p = Path('/proc')/str(self.p.pid)
        require(p.stat().st_uid == os.getuid(), 'Own QEMU UID changed.')
        argv = [v.decode() for v in (p/'cmdline').read_bytes().split(b'\0') if v]
        ticks = (p/'stat').read_text().split(') ', 1)[1].split()[19]
        return argv, ticks

    def guard(self):
        require(self.p.poll() is None, 'Own QEMU stopped; inspect qemu.log.')
        require(self.identity() == (self.args, self.birth), 'Own QEMU PID/argv identity changed.')

    def retain_pidfd(self):
        require(hasattr(os, 'pidfd_open') and hasattr(signal, 'pidfd_send_signal') and self.pidfd is None,
                'Owned reset VM requires a retained pidfd.')
        self.guard()
        descriptor = os.pidfd_open(self.p.pid, 0)
        try:self.guard()
        except BaseException:
            os.close(descriptor);raise
        self.pidfd = descriptor

    def abrupt_stop(self):
        require(self.pidfd is not None, 'Abrupt stop requires the original owned pidfd.')
        self.guard()
        signal.pidfd_send_signal(self.pidfd, signal.SIGKILL, None, 0)
        require(self.p.wait(timeout=15) == -signal.SIGKILL, 'Owned abrupt VM did not reap with SIGKILL.')

    def connect(self):
        until = time.monotonic()+30
        while time.monotonic() < until:
            self.guard()
            if (self.root/'qmp.sock').exists(): break
            time.sleep(.2)
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(30)
        self.sock.connect(str(self.root/'qmp.sock'))
        self.reader = self.sock.makefile('rb')
        self.receive()
        self.call('qmp_capabilities')

    def receive(self):
        data = self.reader.readline(1024*1024)
        require(data and len(data) < 1024*1024, 'Invalid or oversized QMP response.')
        return json.loads(data)

    def call(self, command, **arguments):
        self.guard()
        self.sock.sendall((json.dumps({'execute': command, 'arguments': arguments})+'\n').encode())
        while True:
            response = self.receive()
            if 'event' in response: continue
            require('error' not in response, 'Own QMP command failed: '+command)
            return response.get('return')

    def key(self, *keys):
        def events(down, values):
            return [{'type':'key','data':{'down':down,'key':{'type':'qcode','data':k}}} for k in values]
        self.call('input-send-event', events=events(True, keys))
        self.call('input-send-event', events=events(False, reversed(keys)))
        time.sleep(.03)

    def text(self, value):
        normal = dict(zip(' -=[];\'`,./\\\n', ['spc','minus','equal','bracket_left','bracket_right','semicolon','apostrophe','grave_accent','comma','dot','slash','backslash','ret']))
        shifted = dict(zip('!@#$%^&*()_+{}:"<>?|~', ['1','2','3','4','5','6','7','8','9','0','minus','equal','bracket_left','bracket_right','semicolon','apostrophe','comma','dot','slash','backslash','grave_accent']))
        for ch in value:
            if ch.isascii() and ch.isalnum(): self.key(*(['shift'] if ch.isupper() else []), ch.lower())
            elif ch in normal: self.key(normal[ch])
            elif ch in shifted: self.key('shift', shifted[ch])
            else: raise RuntimeError('Only ASCII fixture commands may be typed.')

    def capture(self, label):
        from PIL import Image
        self.counter += 1
        ppm = self.root/f'{self.counter:04d}-{label}.ppm'
        png = ppm.with_suffix('.png')
        self.call('screendump', filename=str(ppm))
        with Image.open(ppm) as im: im.save(png)
        ppm.unlink()
        return png

    def words(self, label):
        image = self.capture(label)
        if label.startswith('installer-') and not label.endswith('-boot-menu'):
            return installer_screen_words(image,label)
        p = run(['tesseract',str(image),'stdout','-l','eng','tsv'], capture_output=True, text=True)
        rows = []
        for line in p.stdout.splitlines()[1:]:
            f = line.split('\t')
            if len(f) == 12 and f[11].strip():
                rows.append((f[11], int(f[6]), int(f[7]), int(f[8]), int(f[9])))
        return image, rows, ' '.join(r[0] for r in rows)

    def wait_screen(self, label, predicate, timeout):
        started = time.monotonic()
        until = started+timeout
        heartbeat = started+30
        while time.monotonic() < until:
            image, rows, text = self.words(label)
            if predicate(text): return image, rows, text
            if time.monotonic() >= heartbeat:
                print(json.dumps({'observation':label,'elapsed_seconds':round(time.monotonic()-started)}),flush=True)
                heartbeat = time.monotonic()+30
            time.sleep(5)
        raise RuntimeError('Guest screen deadline exceeded: '+label)

    def wait_boot_menu(self, phase, firmware):
        until = time.monotonic()+120
        while time.monotonic()<until:
            image,rows,text = self.words(phase+'-boot-menu')
            if (('Live' in text and 'Vault' in text and 'Install' in text)
                    or (phase=='live' and home_screen(text))):return image,rows,text
            if firmware=='uefi':
                record = grub_menu_ocr(image,text)
                if record is not None:
                    self.boot_menu_ocr = record
                    return image,rows,text
            time.sleep(5)
        raise RuntimeError('Guest firmware menu recognition deadline exceeded (120 seconds).')

    def click_phrase(self, phrase, rows, image):
        def clean(value):return re.sub(r'^[^A-Za-z0-9]+|[^A-Za-z0-9]+$', '', value).lower()
        expected = [clean(word) for word in phrase.split()]
        matches = []
        for first in range(len(rows)-len(expected)+1):
            candidate = rows[first:first+len(expected)]
            if [clean(row[0]) for row in candidate] == expected:
                # Native button text is a single line. Do not combine words
                # from separate controls or a paragraph elsewhere on screen.
                if max(row[2] for row in candidate)-min(row[2] for row in candidate) <= max(row[4] for row in candidate):
                    matches.append(candidate)
        require(len(matches)==1, 'Expected one native GUI phrase: '+phrase)
        candidate = matches[0]
        x, y = min(r[1] for r in candidate), min(r[2] for r in candidate)
        right, bottom = max(r[1]+r[3] for r in candidate), max(r[2]+r[4] for r in candidate)
        self.click_word(phrase, [(phrase,x,y,right-x,bottom-y)], image)

    def click_word(self, word, rows, image):
        from PIL import Image
        found = [r for r in rows if r[0].strip().lower() == word.lower()]
        require(len(found) == 1, 'Expected one native GUI control: '+word)
        _, x, y, w, h = found[0]
        with Image.open(image) as im: width, height = im.size
        self.call('input-send-event',events=[{'type':'abs','data':{'axis':axis,'value':round(v*32767/(size-1))}} for axis,v,size in [('x',x+w/2,width),('y',y+h/2,height)]])
        self.call('input-send-event',events=[{'type':'btn','data':{'button':'left','down':True}}])
        self.call('input-send-event',events=[{'type':'btn','data':{'button':'left','down':False}}])
        if self.root.name == 'installer' and not word.lower().startswith('restart'):
            # Keep the native pointer from obscuring the next button caption.
            time.sleep(.2)
            self.call('input-send-event',events=[{'type':'abs','data':{'axis':axis,'value':round(5*32767/(size-1))}} for axis,size in [('x',width),('y',height)]])
            time.sleep(.1)

    def close(self):
        try:
            if self.p.returncode is None:
                if self.never_quit:
                    self.abrupt_stop()
                    return
                try:
                    self.call('quit')
                    self.p.wait(timeout=15)
                except Exception:
                    if self.p.returncode is None:
                        self.p.kill()
                    self.p.wait(timeout=15)
        finally:
            # Preserve the retained capability if a guarded abrupt stop failed
            # while the process remains alive. Never replace it with a PID kill.
            if not (self.p.returncode is None and self.never_quit):
                if self.pidfd is not None:
                    os.close(self.pidfd);self.pidfd = None
                if self.reader:self.reader.close()
                if self.sock:self.sock.close()
                self.log.close()



def home_screen(text):
    return all(word in text for word in ('Wallet', 'Backup', 'Terminal'))


def qemu_command(args, phase, directory, disk, usb, iso, variables):
    command = [str(Path(shutil.which('qemu-system-x86_64')).absolute()),
        '-name', 'Vault synthetic candidate ' + args.firmware + ' ' + phase,
        '-machine', 'q35,accel=' + args.accel + ',dump-guest-core=off', '-m', '4096', '-smp', '2',
        '-nic', 'none', '-display', 'none', '-vga', 'std', '-device', 'qemu-xhci,id=usb',
        '-device', 'usb-tablet', '-qmp', f'unix:{directory}/qmp.sock,server=on,wait=off',
        '-monitor', 'none', '-serial', f'file:{directory}/serial.log', '-no-reboot',
        '-drive', f'file={disk},if=none,id=target,format=qcow2',
        '-device', 'virtio-blk-pci,drive=target,serial=CV_RAM_TEST_INTERNAL',
        '-drive', f'file={usb},if=none,id=fixture,format=raw',
        '-device', 'usb-storage,bus=usb.0,drive=fixture,removable=on,serial=CV_RAM_TEST_USB']
    if phase != 'installed':
        command += ['-drive', f'file={iso},if=ide,index=2,media=cdrom,readonly=on', '-boot', 'order=d']
    else:
        command += ['-boot', 'order=c']
    if variables is not None:
        command += ['-drive', 'if=pflash,format=raw,unit=0,readonly=on,file=/usr/share/OVMF/OVMF_CODE_4M.fd',
                    '-drive', f'if=pflash,format=raw,unit=1,file={variables}']
    return command


def existing_probe_terminal(image, rows):
    """Find only the existing probe terminal below a covering Core window.

    Whole-screen OCR omits the dark taskbar in the actual candidate. Preserve
    the raw screen and derive a bounded enlarged input for its last 40 pixels.
    This changes focus only; it never creates a terminal or types a command.
    """
    from PIL import Image
    top = [row[0] for row in rows if row[2] < 70]
    if 'Bitcoin Core' not in ' '.join(top) or not {'File', 'Settings', 'Help'} <= set(top):
        return None
    with Image.open(image) as source:
        width, height = source.size
        if width < 640 or height < 300:return None
        crop = source.crop((0,height-40,width,height)).convert('L')
        derived = image.with_name(image.stem+'-terminal-taskbar-ocr-input.png')
        crop.resize((width*3,120),Image.Resampling.LANCZOS).save(derived)
    result = run(['tesseract',str(derived),'stdout','-l','eng','--psm','6','tsv'],
                 capture_output=True,text=True)
    words = []
    for line in result.stdout.splitlines()[1:]:
        fields = line.split('\t')
        if len(fields)==12 and fields[11].strip():
            words.append((fields[11],int(fields[6]),int(fields[7]),int(fields[8]),int(fields[9])))
    matches = []
    expected = ['Terminal','-','vault@core-vault:','~']
    for first in range(len(words)-len(expected)+1):
        candidate = words[first:first+len(expected)]
        if [word[0] for word in candidate] != expected:continue
        if max(word[2] for word in candidate)-min(word[2] for word in candidate)>max(word[4] for word in candidate):continue
        x,y = min(word[1] for word in candidate),min(word[2] for word in candidate)
        right,bottom = max(word[1]+word[3] for word in candidate),max(word[2]+word[4] for word in candidate)
        matches.append((' '.join(word[0] for word in candidate),x/3,height-40+y/3,(right-x)/3,(bottom-y)/3))
    if len(matches)!=1:return None
    return {'caption':matches[0], 'derived_screenshot':derived.name}


def wait_probe_completion(vm, stage, phase, pattern):
    started = time.monotonic()
    until, heartbeat = started+1320,started+30
    while time.monotonic()<until:
        image,rows,text = vm.words(phase+'-guest-probe')
        if pattern.search(text):return image,text
        terminal = existing_probe_terminal(image,rows)
        if terminal is not None:
            caption = terminal['caption']
            vm.click_word(caption[0],[caption],image)
            stage.setdefault('probe_terminal_activations',[]).append({
                'elapsed_seconds':round(time.monotonic()-started),
                'raw_screenshot':image.name,'derived_screenshot':terminal['derived_screenshot'],
                'caption':caption[0], 'action':'Activate the already-open probe terminal taskbar tab.'})
        if time.monotonic()>=heartbeat:
            print(json.dumps({'observation':phase+'-guest-probe','elapsed_seconds':round(time.monotonic()-started)}),flush=True)
            heartbeat = time.monotonic()+30
        time.sleep(5)
    raise RuntimeError('Guest screen deadline exceeded: '+phase+'-guest-probe')


def guest_probe(vm, stage, args, phase):
    image, rows, _ = vm.wait_screen(phase + '-home', home_screen, args.boot_timeout)
    stage['normal_home_boot'] = 'passed'
    stage['home_screenshot'] = image.name
    vm.click_word('Terminal', rows, image)
    vm.wait_screen(phase + '-terminal', lambda s: 'vault@' in s.replace(' ', '') or 'core-vault:' in s, 60)
    # Run the exact copied probe as UID1000 in the native Home Terminal. Echoed
    # printf formats cannot satisfy the digit-bearing completion predicate.
    stdout_name = args.firmware + '-' + phase + '-guest-stdout.log'
    banner = 'VAULT CI ' + phase.upper() + ' DONE EXIT'
    command = ('for p in /media/vault/*/ci-vm-guest-probe.py; do [ -f "$p" ] || continue; '
        'python3 "$p" --user-workflow --phase ' + phase + ' --firmware ' + args.firmware +
        ' >"${p%/*}/' + stdout_name + '" 2>&1; r=$?; sync; '
        "printf '\\n" + banner + " %s\\n' \"$r\"; break; done\n")
    vm.text(command)
    pattern = re.compile(re.escape(banner) + r'\s+([0-9]+)\b')
    image,text = wait_probe_completion(vm,stage,phase,pattern)
    require(pattern.search(text).group(1) == '0', 'Synthetic ' + phase + ' guest probe reported failure.')
    stage['guest_completion_screenshot'] = image.name


def copy_guest_evidence(usb, directory, firmware, phase, stage, helper_hashes):
    stdout_name = firmware + '-' + phase + '-guest-stdout.log'
    try:
        subprocess.run(['mcopy', '-i', str(usb), '::' + stdout_name, str(directory/stdout_name)],
                       capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        stage['guest_stdout_copy'] = 'unavailable'
    name = firmware + '-' + phase + '-result.json'
    result = subprocess.run(['mcopy', '-i', str(usb), '::' + name, str(directory/name)],
                            capture_output=True, timeout=30)
    require(result.returncode == 0, 'Guest evidence JSON was not produced: ' + phase)
    guest = json.loads((directory/name).read_text())
    require(isinstance(guest, dict) and guest.get('status') == 'passed-covered-checks'
            and guest.get('phase') == phase and guest.get('firmware') == firmware
            and guest.get('execution_uid') == 1000 and bool(guest.get('covered'))
            and guest.get('target_serial') == 'CV_RAM_TEST_INTERNAL'
            and guest.get('fixture_serial') == 'CV_RAM_TEST_USB'
            and guest.get('helper_sha256') == helper_hashes,
            'Guest result did not attest successful covered checks: ' + phase)
    signing = guest.get('psbt_signing', {})
    require(signing.get('status')=='passed' and len(signing.get('proofs',[]))==2
            and {proof.get('backup_format') for proof in signing['proofs']}=={'7z','gpg'}
            and all(proof.get('chain')=='main' and proof.get('fresh_recovery_signed') is True
                    and proof.get('blockchain_funding_proven') is False and proof.get('broadcast') is False
                    for proof in signing['proofs']), 'Recovered-wallet synthetic PSBT evidence is incomplete: '+phase)
    stage['guest_probe'] = guest


def selected_test_disk(text):
    compact = text.replace(' ', '')
    return ('/dev/vda' in compact and re.search(r'24(?:\.0+)?(?:GiB|GB)', compact) is not None
            and not re.search(r'/dev/(?:sd[a-z]+|hd[a-z]+|nvme\d+n\d+|vd[b-z]+)', compact))


def install_via_gui(vm, stage, args):
    image, rows, text = vm.wait_screen('installer-keyboard', lambda s:
        'choose your keyboard layout' in s.lower() and 'continue' in s.lower(), args.boot_timeout)
    require('english' in text.lower() and 'us' in text.lower(), 'Expected default English US keyboard was not visible.')
    stage['keyboard_screenshot'] = image.name
    vm.click_word('Continue', rows, image)
    image, rows, text = vm.wait_screen('installer-disk', lambda s:
        'choose where to install bitcoin core vault' in s.lower() and 'installation drive' in s.lower() and 'continue' in s.lower(), 120)
    require(selected_test_disk(text), 'Installer selection is not the sole 24GiB /dev/vda fixture.')
    stage['disk_selection_screenshot'] = image.name
    stage['installation_target'] = {'path': '/dev/vda', 'serial': 'CV_RAM_TEST_INTERNAL', 'virtual_bytes': 24*1024**3}
    vm.click_word('Continue', rows, image)
    image, rows, text = vm.wait_screen('installer-review', lambda s:
        'ready to install' in s.lower() and 'understand' in s.lower() and 'erase drive and install' in s.lower(), 120)
    require('/dev/vda' in text.lower().replace(' ', '') and
            not re.search(r'/dev/(?:sd[a-z]+|hd[a-z]+|nvme\d+n\d+|vd[b-z]+)', text.lower().replace(' ', '')),
            'Installer review changed away from the designated test disk.')
    stage['review_screenshot'] = image.name
    vm.click_word('understand', rows, image)
    image, rows, _ = vm.words('installer-consent')
    stage['consent_screenshot'] = image.name
    vm.click_phrase('Erase drive and install', rows, image)
    image, rows, text = vm.wait_screen('installer-final-confirmation', lambda s:
        'continue with installation' in s.lower() and 'install now' in s.lower()
        and 'undo' in s.lower(), 60)
    stage['final_confirmation_screenshot'] = image.name
    vm.click_phrase('Install Now', rows, image)
    image, _, text = vm.wait_screen('installer-executing', lambda s:
        'installing bitcoin core vault' in s.lower() or 'installation failed' in s.lower(), 120)
    require('installation failed' not in text.lower(), 'Calamares reported installation failure.')
    stage['execution_screenshot'] = image.name
    image, rows, text = vm.wait_screen('installer-finished', lambda s:
        ('bitcoin core vault is ready' in s.lower() and 'installation completed successfully' in s.lower()
         and 'restart into bitcoin core vault' in s.lower()) or 'installation failed' in s.lower(), args.install_timeout)
    require('installation failed' not in text.lower(), 'Calamares reported installation failure.')
    stage['finished_screenshot'] = image.name
    vm.click_phrase('Restart into Bitcoin Core Vault', rows, image)
    deadline = time.monotonic()+300
    while vm.p.poll() is None:
        require(time.monotonic() < deadline, 'Installer Restart did not stop the no-reboot QEMU instance.')
        time.sleep(1)
    require(vm.p.returncode == 0, 'Own QEMU did not exit normally after installer Restart.')
    stage['genuine_installer_restart'] = 'passed'


def run_phase(args, root, phase, disk, usb, iso, variables, report):
    directory = root/phase
    directory.mkdir(mode=0o700)
    stage = report['stages'][phase] = {'status': 'running', 'evidence_directory': phase}
    command = qemu_command(args, phase, directory, disk, usb, iso, variables)
    vm = None
    failure = None
    try:
        if getattr(args, 'reset', False):args.reset_files.before_start()
        print(json.dumps({'phase': phase, 'status': 'starting', 'firmware': args.firmware}), flush=True)
        vm = VM(directory, command);vm.connect()
        if getattr(args, 'reset', False):stage['qemu_owned_file_fds'] = args.reset_files.active(vm)
        stage['qemu'] = {'pid': vm.p.pid, 'start_ticks': vm.birth, 'argv': command}
        stage['attached_blocks'] = vm.call('query-block')
        if phase in ('live', 'installer'):
            _, _, first = vm.wait_boot_menu(phase,args.firmware)
            if hasattr(vm,'boot_menu_ocr'):stage['boot_menu_ocr'] = vm.boot_menu_ocr
            if not (phase == 'live' and home_screen(first)):
                vm.key('home')
                if phase == 'installer':vm.key('down')
                vm.key('ret')
        if phase == 'installer':install_via_gui(vm, stage, args)
        else:
            guest_probe(vm, stage, args, phase)
            if getattr(args, 'reset', False):
                nonce = args.reset_nonces[phase]['normal']
                stage['reset_normal_arm'] = reset_guest(vm, report, phase, 'normal', nonce, 'arm-existing')
            if args.gui:
                helper = HERE/'ci-vm-gui-actions.py'
                require(digest(helper)==report['gui_helper_sha256'], 'Native GUI helper changed after fixture preparation.')
                spec = importlib.util.spec_from_file_location('vault_ci_gui_actions', helper)
                module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
                gui = module.run_gui_checks(vm, stage, phase=phase, firmware=args.firmware, finish=True)
                require(isinstance(gui,dict) and gui.get('status')=='passed-covered-checks'
                        and gui.get('phase')==phase and gui.get('poweroff_observed') is True
                        and bool(gui.get('checks')) and all(check.get('status')=='PASS'
                            and check.get('phase')==phase for check in gui['checks']),
                        'Native GUI helper did not attest covered checks.')
                # A successful final dialog alone is insufficient: this exact
                # owned QEMU must exit normally after the genuine Finish action.
                vm.p.wait(timeout=300)
                require(vm.p.returncode==0, 'Own QEMU did not shut down normally after genuine Finish.')
                stage['genuine_gui'] = gui
                stage['genuine_finish_shutdown'] = 'passed'
    except BaseException as error:
        failure = error
        stage['status'] = 'failed';stage['error'] = str(error) or type(error).__name__
    finally:
        try:
            if vm:vm.close()
        except Exception as error:
            failure = failure or error
            stage['status'] = 'failed';stage.setdefault('error', 'Own QEMU cleanup did not complete.')
        try:
            require(digest(iso) == args.sha256, 'Candidate ISO changed during VM evidence collection.')
            stage['iso_sha256_after_vm'] = args.sha256
            require(vm is None or vm.p.returncode is not None, 'USB readback refused while own QEMU remains active.')
            if getattr(args, 'reset', False):args.reset_files.stopped([stage['qemu']] if vm else [])
            if phase != 'installer':copy_guest_evidence(usb, directory, args.firmware, phase, stage, report['helper_sha256'])
            if getattr(args, 'reset', False) and failure is None and phase != 'installer':
                require(stage.get('genuine_finish_shutdown') == 'passed', 'Reset READY needs genuine Finish.')
                ready_directory = directory/'reset-normal-ready';ready_directory.mkdir(mode=0o700)
                stage['reset_normal_ready'] = reset_ready(usb, ready_directory, report, phase, 'normal',
                                                          stage['reset_normal_arm']['nonce'])
                stage['reset_normal_runner_ack'] = reset_runner_ack(usb, ready_directory, report, phase,
                                                                   'normal', 'arm-existing')
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
            failure = failure or error
            stage['status'] = 'failed';stage.setdefault('error', str(error))
        if failure is None:stage['status'] = 'passed-covered-checks'
        (directory/'phase-result.json').write_text(json.dumps(stage, indent=2)+'\n')
        (root/'vm-result.json').write_text(json.dumps(report, indent=2)+'\n')
    if failure is not None:raise failure
    return stage


def forensic_helper():
    helper = plain(HERE / 'ci-vm-forensic.py')
    require(helper.is_file() and digest(helper) == FORENSIC_SHA256,
            'Frozen forensic helper is missing or changed.')
    return helper


def frozen_module(name, expected):
    path = plain(HERE / name)
    require(path.is_file() and digest(path) == expected, 'Frozen reset dependency changed: ' + name)
    spec = importlib.util.spec_from_file_location('vault_ci_' + name.replace('-', '_'), path)
    module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    require(digest(path) == expected, 'Frozen reset dependency changed while loading.')
    return module


class ResetFiles:
    """Hold owned image inodes; mutable hashes are checked only while stopped."""
    def __init__(self, root, disk, usb, iso, variables):
        self.root, self.files, self.boundary = root, {}, None
        self.root_identity = (root.stat().st_dev, root.stat().st_ino, root.stat().st_uid)
        self.forensic = frozen_module('ci-vm-forensic.py', FORENSIC_SHA256)
        try:
            entries = [('disk', disk, True), ('usb', usb, True), ('iso', iso, False)]
            if variables is not None:
                entries += [('vars', variables, True), ('firmware', Path('/usr/share/OVMF/OVMF_CODE_4M.fd'), False)]
            for name, value, mutable in entries:
                path = plain(value)
                fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
                self.files[name] = {'path': path, 'fd': fd, 'mutable': mutable}
                info = os.fstat(fd)
                require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and not info.st_mode & 0o022
                        and (not mutable or info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o600),
                        'Reset file is not an owned standalone regular image.')
                item = self.files[name]
                item['stable'] = self.stable(info)
                item['size'] = info.st_size
                if not mutable:
                    item['readonly'] = (info.st_size, info.st_mtime_ns, info.st_ctime_ns, self.hash_fd(fd))
            self.check()
            self.stopped([])
        except BaseException:
            self.close();raise

    @staticmethod
    def stable(info):
        return (info.st_dev, info.st_ino, info.st_uid, info.st_mode, info.st_nlink)

    @staticmethod
    def hash_fd(fd):
        before = os.fstat(fd)
        sha = hashlib.sha256();position = 0
        while block := os.pread(fd, 16 * 1024**2, position):
            sha.update(block);position += len(block)
        after = os.fstat(fd)
        require((before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
                (after.st_size, after.st_mtime_ns, after.st_ctime_ns), 'Reset file changed during hashing.')
        return sha.hexdigest()

    def metadata(self):
        return {name:(info.st_size, info.st_mtime_ns, info.st_ctime_ns) for name, item in self.files.items()
                if item['mutable'] for info in [os.fstat(item['fd'])]}

    def check(self):
        root = self.root.lstat()
        require((root.st_dev, root.st_ino, root.st_uid) == self.root_identity and
                stat.S_ISDIR(root.st_mode) and stat.S_IMODE(root.st_mode) == 0o700,
                'Reset evidence root identity changed.')
        for name, item in self.files.items():
            path, fd = item['path'], item['fd']
            require(not path.is_symlink() and self.stable(path.lstat()) == item['stable']
                    and self.stable(os.fstat(fd)) == item['stable'], 'Reset image inode or ownership changed.')
            info = os.fstat(fd)
            if name in ('usb', 'vars'):
                require(info.st_size == item['size'], 'Reset fixture size changed.')
            if not item['mutable']:
                require((info.st_size, info.st_mtime_ns, info.st_ctime_ns, self.hash_fd(fd)) == item['readonly'],
                        'Readonly reset ISO or firmware changed.')

    def stopped(self, records):
        self.check()
        before = self.metadata()
        for item in self.files.values():
            if item['mutable']:
                self.forensic.stopped_qemu({'owned_qemu': records}, item['path'])
        self.forensic.validate_header(os.pread(self.files['disk']['fd'], 104, 0))
        self.boundary = {name: self.hash_fd(item['fd']) for name, item in self.files.items() if item['mutable']}
        self.check()
        require(self.metadata() == before, 'Stopped reset images changed during boundary capture.')
        return dict(self.boundary)

    def before_start(self):
        require(self.boundary is not None, 'No stopped reset file boundary exists.')
        self.check()
        before = self.metadata()
        for name, item in self.files.items():
            if item['mutable']:
                self.forensic.stopped_qemu({'owned_qemu': []}, item['path'])
                require(self.hash_fd(item['fd']) == self.boundary[name], 'Reset file changed between stopped boots.')
        self.check()
        require(self.metadata() == before, 'Reset images changed immediately before new boot.')

    def active(self, vm, *, proc_root=Path('/proc')):
        """Attest only this identity-checked QEMU's actual open image inodes."""
        vm.guard();self.check()
        process = proc_root/str(vm.p.pid)
        require(process.stat().st_uid == os.getuid(), 'Active reset QEMU UID changed.')
        identities = set()
        for descriptor in (process/'fd').iterdir():
            try:identities.add(self.stable(descriptor.stat()))
            except FileNotFoundError:continue  # Unrelated QEMU FD may close during inventory.
        expected = {name:item['stable'] for name,item in self.files.items() if item['mutable']}
        require(all(identity in identities for identity in expected.values()),
                'Own QEMU did not open the retained disk/USB/OVMF variable inodes.')
        self.check();vm.guard()
        return {name:dict(zip(('device','inode','uid','mode','links'), identity)) for name,identity in expected.items()}

    def close(self):
        for item in self.files.values():os.close(item['fd'])
        self.files.clear()


def reset_args(report, phase, case, nonce):
    from types import SimpleNamespace
    require(phase in ('live', 'installed') and case in ('normal', 'abrupt') and re.fullmatch(r'[0-9a-f]{32}', nonce)
            and nonce != '0'*32 and report['firmware'] in ('bios', 'uefi'),
            'Reset fixture identity is invalid.')
    return SimpleNamespace(phase=phase, case=case, nonce=nonce, firmware=report['firmware'],
                           helper_sha256=RESET_SHA256, probe_sha256=report['guest_probe_sha256'])


def reset_runner_helper():
    path = plain(HERE/'ci-vm-reset-runner.py')
    require(re.fullmatch(r'[0-9a-f]{64}', RESET_RUNNER_SHA256) and path.is_file()
            and digest(path) == RESET_RUNNER_SHA256, 'Frozen short reset runner changed or is missing.')
    return path


def reset_slot(phase, case, mode):
    require(phase in ('live','installed') and case in ('normal','abrupt') and
            ((mode == 'arm-existing' and case == 'normal') or (mode == 'arm-fresh' and case == 'abrupt') or mode == 'probe'),
            'Reset slot mode/case combination is invalid.')
    return phase+'-'+case+'-'+('probe' if mode == 'probe' else 'arm')


def reset_request(report, phase, case, nonce, mode, ready_sha=None):
    values = reset_args(report, phase, case, nonce)
    slot = reset_slot(phase, case, mode)
    require(values.probe_sha256 == RESET_PROBE_SHA256 and
            ((mode == 'probe' and isinstance(ready_sha,str) and re.fullmatch(r'[0-9a-f]{64}',ready_sha)) or
             (mode != 'probe' and ready_sha is None)), 'Reset request source or READY binding is invalid.')
    value = {'schema':1,'slot':slot,'phase':phase,'firmware':values.firmware,'case':case,'nonce':nonce,
             'helper_sha256':RESET_SHA256,'probe_sha256':RESET_PROBE_SHA256}
    if mode == 'probe':value['ready_sha256'] = ready_sha
    frozen_module('ci-vm-reset-runner.py',RESET_RUNNER_SHA256).validate_request(value,slot)
    return value


def deliver_reset_request(args, root, usb, report, phase, case, nonce, mode, *, ready_sha=None,
                          initial=False, stopped_records=()):
    """Write only public requests, with no QEMU using the fixture image."""
    reset_runner_helper()
    value = reset_request(report, phase, case, nonce, mode, ready_sha)
    slot = value['slot'];filename = 'ci-reset-request-'+slot+'.json'
    require(slot not in report.get('reset_requests',{}), 'A reset request slot must be created only once.')
    if initial:
        require(mode != 'probe' and not report['stages'] and getattr(args,'reset_files',None) is None,
                'Initial reset requests must precede every VM.')
        frozen_module('ci-vm-forensic.py',FORENSIC_SHA256).stopped_qemu({'owned_qemu':[]},usb)
    else:
        require(mode == 'probe' and bool(stopped_records), 'A dynamic READY request needs stopped source QEMU proof.')
        args.reset_files.stopped(list(stopped_records))
    directory = root/'fixture-delivery';path = directory/filename
    payload = (json.dumps(value,sort_keys=True,indent=2)+'\n').encode()
    descriptor = os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o600)
    try:
        with os.fdopen(descriptor,'wb',closefd=False) as stream:stream.write(payload);stream.flush();os.fsync(descriptor)
    finally:os.close(descriptor)
    run(['mcopy','-i',str(usb),str(path),'::'+filename],capture_output=True)
    copied = directory/('readback-'+filename)
    require(not copied.exists(), 'Existing request readback must not be overwritten.')
    run(['mcopy','-i',str(usb),'::'+filename,str(copied)],capture_output=True);copied.chmod(0o600)
    copied_value, proof = scan_json(copied)
    require(copied_value == value and proof['sha256'] == hashlib.sha256(payload).hexdigest(), 'Reset request readback mismatch.')
    record = {'slot':slot,'mode':mode,'value':value,'sha256':proof['sha256'],'filename':filename,
              'source':str(path.relative_to(root)),'readback':str(copied.relative_to(root)),
              'delivery_boundary':'before-any-VM' if initial else 'after-owned-source-QEMU-reaped'}
    report.setdefault('reset_requests',{})[slot] = record
    if not initial:args.reset_files.stopped(list(stopped_records))  # Bind this authorized public FAT write before next boot.
    return record


def reset_runner_ack(usb, directory, report, phase, case, mode):
    slot = reset_slot(phase, case, mode);request = report['reset_requests'][slot]
    data, sha = reset_usb_file(usb,request['filename'],directory,limit=8192)
    require(sha == request['sha256'] and json.loads(data) == request['value'], 'Executed reset request changed.')
    data, ack_sha = reset_usb_file(usb,'ci-reset-runner-'+slot+'-result.json',directory,limit=8192)
    ack = frozen_module('ci-vm-reset-runner.py',RESET_RUNNER_SHA256).unique_json(data)
    expected = {'schema':1,'slot':slot,'phase':phase,'firmware':report['firmware'],'case':case,
                'nonce':request['value']['nonce'],'request_sha256':request['sha256'],
                'runner_sha256':RESET_RUNNER_SHA256,'helper_sha256':RESET_SHA256,'probe_sha256':RESET_PROBE_SHA256,
                'status':'passed-runner-execution','helper_exit_code':0}
    require(ack == expected and type(ack.get('schema')) is int and type(ack.get('helper_exit_code')) is int,
            'Actual short runner execution/source/request acknowledgement failed.')
    return {'status':'passed-runner-execution','slot':slot,'request_sha256':sha,'ack_sha256':ack_sha,
            'runner_sha256':RESET_RUNNER_SHA256}


def reset_control_key(vm, key):
    """Settle only the two Readline controls used by the reset fixture."""
    require(key in ('e', 'u'), 'Only fixed reset Readline controls may be held.')
    def events(down, keys):
        return [{'type':'key','data':{'down':down,'key':{'type':'qcode','data':value}}} for value in keys]
    try:
        vm.call('input-send-event', events=events(True, ('ctrl', key)))
        time.sleep(.10)
    finally:
        vm.call('input-send-event', events=events(False, (key, 'ctrl')))
    time.sleep(.15)


def reset_empty_prompt(vm, gui, label):
    """Retain a newly painted empty prompt and confirm stable body geometry."""
    first = gui._terminal_screen(vm, label, timeout=10)
    until = time.monotonic()+10
    previous = gui._terminal_prompt(first)
    require(previous is not None and not gui.normalized(previous['echo']), 'Fresh reset prompt is not empty.')
    from PIL import Image
    with Image.open(first[0]) as capture: dimensions = capture.size
    while time.monotonic() < until:
        time.sleep(.25)
        fresh = vm.words(label+'-stable')
        prompt = gui._terminal_prompt(fresh)
        with Image.open(fresh[0]) as capture: current = capture.size
        if (prompt is not None and not gui.normalized(prompt['echo']) and current == dimensions
                and abs(prompt['focus'][0]-previous['focus'][0]) <= 3
                and abs(prompt['focus'][1]-previous['focus'][1]) <= 3):
            return fresh
        require(prompt is None or not gui.normalized(prompt['echo']), 'Reset prompt changed before typing.')
        if prompt is not None:
            previous = prompt; dimensions = current
    raise RuntimeError('Fresh empty reset prompt did not settle; no command was typed.')


def reset_viewport_right(capture, rows, top, bottom):
    """Attest a narrow neutral right scrollbar beside an untouched black client."""
    width,height = capture.size
    if (width,height) != (1280,800): return None
    pixels = capture.convert('RGB')
    # The stock title/menu ends at y43. A two-pixel OCR margin can include
    # that last menu row; it is not part of the client scrollbar attestation.
    body_top = max(44,top)
    candidates = []
    for right in range(width-24,width-7):
        if all(max(pixels.getpixel((x,y))) <= 8 for x in range(right-3,right)
               for y in range(body_top,height-41)) and all(
               min(pixels.getpixel((x,y))) >= 96 and
               max(pixels.getpixel((x,y)))-min(pixels.getpixel((x,y))) <= 32
               for x in range(right,width) for y in range(body_top,height-41)):
            candidates.append(right)
    if len(candidates) != 1: return None
    right = candidates[0]
    # Never crop an observed command token or an altered client edge.
    if any(top <= row[2]+row[4]/2 < bottom and row[1]+row[3] > right for row in rows): return None
    return right


def reset_row_echo(screen, gui, *, timeout=3):
    """Read only an observed public prompt row, with no supplied OCR text."""
    from PIL import Image
    image, rows, text = screen
    prompt = gui._terminal_prompt(screen)
    if prompt is None or not gui.normalized(prompt['echo']):
        return None
    before = image.lstat()
    require(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid() and before.st_nlink == 1
            and not before.st_mode & 0o022, 'Unsafe original reset command capture.')
    raw_sha = digest(image)
    with Image.open(image) as capture:
        width,height = capture.size
        center = prompt['focus'][1]
        line_rows = [row for row in rows if abs(row[2]+row[4]/2-center) <= 4]
        if not line_rows: return None
        top = int(min(row[2] for row in line_rows))-2
        bottom = int(max(row[2]+row[4] for row in line_rows))+12
        if not (width >= 800 and height >= 400 and 40 <= top < bottom < height-70):
            return None
        # A row crop must not hide an adjacent continuation or another visible
        # command/output row that the full-frame parser included in the echo.
        if any(4 < row[2]+row[4]/2-center <= 30 and 40 <= row[2]
               and row[2]+row[4] < height-70 for row in rows):
            return None
        right = reset_viewport_right(capture,rows,top,bottom)
        if right is None: return None
        crop = capture.crop((0,top,right,bottom))
        crop = crop.resize((right*3,(bottom-top)*3),Image.Resampling.LANCZOS)
        header = capture.crop((20,0,width-80,20))
        header = header.resize((header.width*3,header.height*3),Image.Resampling.LANCZOS)
    deadline = time.monotonic()+timeout
    title_input = image.with_name(image.stem+'-reset-terminal-title-ocr-input.png')
    fd = os.open(title_input,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o600)
    try:
        with os.fdopen(fd,'wb',closefd=False) as stream: header.save(stream,format='PNG')
    finally: os.close(fd)
    try:
        title = run(['tesseract',str(title_input),'stdout','-l','eng','--psm','7'],
                    capture_output=True,text=True,timeout=max(.01,deadline-time.monotonic())).stdout.strip()
    except subprocess.TimeoutExpired: return None
    if not re.fullmatch(r'Terminal\s*-\s*vault\s*@\s*core-vault\s*:\s*~',title,re.I): return None
    derived = image.with_name(image.stem+'-reset-command-row-ocr-input.png')
    fd = os.open(derived,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o600)
    try:
        with os.fdopen(fd,'wb',closefd=False) as stream: crop.save(stream,format='PNG')
    finally: os.close(fd)
    try:
        remaining = deadline-time.monotonic()
        if remaining <= 0: return None
        output = run(['tesseract',str(derived),'stdout','-l','eng','--psm','7','tsv'],
                     capture_output=True,text=True,timeout=remaining).stdout
    except subprocess.TimeoutExpired:
        return None
    require(len(output.encode()) <= 65536, 'Oversized reset row OCR result.')
    mapped = []
    for line in output.splitlines()[1:]:
        fields = line.split('\t')
        if len(fields) != 12 or not fields[11].strip(): continue
        left,y,w,h = map(int,fields[6:10])
        require(0 <= left < right*3 and 0 <= y < (bottom-top)*3 and w > 0 and h > 0
                and left+w <= right*3 and y+h <= (bottom-top)*3, 'Invalid reset row OCR coordinates.')
        mapped.append((fields[11],left/3,top+y/3,w/3,h/3))
    after = image.lstat()
    identity = lambda value:(value.st_dev,value.st_ino,value.st_mode,value.st_uid,value.st_nlink,
                             value.st_size,value.st_mtime_ns,value.st_ctime_ns)
    require(identity(before) == identity(after) and digest(image) == raw_sha, 'Original reset capture changed.')
    observed = gui._terminal_prompt((image,mapped,' '.join(row[0] for row in mapped)))
    if observed is None: return None
    return observed, {'method':'observed-public-prompt-row-3x-Lanczos-PSM7',
                      'raw_screenshot':image.name,'raw_sha256':raw_sha,'derived_screenshot':derived.name,
                      'crop':[0,top,right,bottom],'scale':3,'viewport_right':right,
                      'scrollbar_rect':[right,max(44,top),width,height-41],'title_ocr_input':title_input.name,
                      'terminal_title_verified':True}


def reset_echo_matches(prompt, gui, command):
    # Cursor OCR punctuation must not vanish through normalized equality. The
    # fixed short command contains only this public alphabet; no repair occurs.
    return (prompt is not None and re.fullmatch(r'[A-Za-z0-9 /_.-]*',prompt['echo']) is not None
            and gui.normalized(prompt['echo']) == gui.normalized(command))


def reset_exact_echo(vm, gui, command, label):
    """Passively await the entire public command, never repairing its value."""
    until = time.monotonic()+10
    screen = None
    while time.monotonic() < until:
        screen = vm.words(label)
        prompt = gui._terminal_prompt(screen)
        if reset_echo_matches(prompt,gui,command):
            return screen, {'method':'original-full-frame-OCR','raw_screenshot':screen[0].name}
        remaining = until-time.monotonic()
        if remaining <= 0: break
        alternate = reset_row_echo(screen,gui,timeout=min(3,remaining))
        if alternate is not None:
            prompt,proof = alternate
            if reset_echo_matches(prompt,gui,command):
                return screen,proof
        time.sleep(.4)
    return screen,None


def reset_guest(vm, report, phase, case, nonce, mode, *, ready_sha=None):
    """Type a fixed public reset command with full echo before one Return."""
    require(mode in ('arm-existing', 'arm-fresh', 'probe') and report.get('reset_helper_sha256') == RESET_SHA256,
            'Reset mode or source identity is invalid.')
    values = reset_args(report, phase, case, nonce)
    reset_runner_helper()
    slot = reset_slot(phase, case, mode)
    value = reset_request(report, phase, case, nonce, mode, ready_sha)
    require(report.get('reset_runner_sha256') == RESET_RUNNER_SHA256 and
            report.get('reset_requests',{}).get(slot,{}).get('value') == value,
            'Short reset command is not bound to its delivered public request.')
    gui = frozen_module('ci-vm-gui-actions.py', report['gui_helper_sha256'])
    screen = gui._home(vm, 'reset-' + mode + '-home')
    gui._click_home_card(vm, 'Terminal', screen)
    screen = gui._terminal_screen(vm, 'reset-' + mode + '-terminal')
    command = 'python3 /media/vault/VAULT_CI/ci-vm-reset-runner.py '+slot
    banner = 'VAULT CI RESET ' + case.upper() + ' ' + ('PROBE' if mode == 'probe' else 'ARM') + ' DONE EXIT'
    for attempt in range(2):
        prompt = gui._terminal_prompt(screen)
        require(prompt is not None, 'Reset Terminal body prompt is unavailable.')
        gui._point(vm, screen[0], *prompt['focus'], settle_click=True)
        from PIL import Image
        with Image.open(screen[0]) as capture:width, height = capture.size
        gui._point(vm, screen[0], width / 2, height / 2, click=False)
        time.sleep(.25)
        reset_control_key(vm,'e');reset_control_key(vm,'u')
        screen = reset_empty_prompt(vm,gui,'reset-' + mode + '-cleared')
        vm.text(command + '  ')
        screen, echo_proof = reset_exact_echo(vm,gui,command,'reset-' + mode + '-echo')
        if echo_proof is not None:
            vm.key('ret');break
    else:raise RuntimeError('Complete public reset command was not verified; no Return sent.')
    pattern = re.compile(re.escape(banner) + r'\s+([0-9]+)\b')
    image, text = wait_probe_completion(vm, {}, 'reset-' + mode, pattern)
    require(pattern.search(text).group(1) == '0', 'Guest reset helper failed: ' + mode)
    expected = 'VAULT_RESET_PROBE_PASS' if mode == 'probe' else 'VAULT_RESET_USBREADY'
    require(gui.normalized(expected) in gui.normalized(text), 'Guest reset completion lacked its protected result marker.')
    if case == 'normal':vm.key('alt', 'f4')  # Close only this completed public Terminal, before any fresh Core arm.
    return {'mode': mode, 'phase': phase, 'case': case, 'nonce': nonce,
            'helper_sha256': RESET_SHA256, 'runner_sha256':RESET_RUNNER_SHA256,
            'request_sha256':report['reset_requests'][slot]['sha256'], 'slot':slot,
            'screenshot': image.name, 'entry_echo_proof':echo_proof,'status': 'completed-exit-zero'}


def reset_usb_file(usb, name, directory, *, limit):
    require(re.fullmatch(r'[A-Za-z0-9_.-]+', name), 'Unsafe public reset evidence filename.')
    path = directory / name
    require(not path.exists(), 'Existing reset evidence must not be overwritten.')
    run(['mcopy', '-i', str(usb), '::' + name, str(path)], capture_output=True)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid() and before.st_nlink == 1
                and not before.st_mode & 0o022 and 0 < before.st_size <= limit, 'Unsafe bounded public reset evidence.')
        payload = os.pread(fd, limit + 1, 0)
        identity = lambda s: (s.st_dev, s.st_ino, s.st_uid, s.st_mode, s.st_nlink, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        require(len(payload) == before.st_size and identity(os.fstat(fd)) == identity(before)
                and identity(path.lstat()) == identity(before),
                'Public reset evidence changed during readback.')
        return payload, hashlib.sha256(payload).hexdigest()
    finally:os.close(fd)


def reset_ready(usb, directory, report, phase, case, nonce):
    module = frozen_module('ci-vm-reset-probe.py', RESET_SHA256)
    values = reset_args(report, phase, case, nonce)
    stem = 'ci-reset-' + phase + '-' + case + '-' + nonce
    payload, sha = reset_usb_file(usb, stem + '-ready.json', directory, limit=module.MAX_JSON)
    value = json.loads(payload);module.validate_ready(value, values)
    require(value['runtime_sha256'] == report['stages'][phase]['guest_probe']['runtime_sha256']
            and (case != 'normal' or value['core_state'] == 'closed'), 'Reset READY runtime or Core state does not match.')
    if case == 'normal':
        exports = report['stages'][phase]['guest_probe']['exports']
        require(set(value['wallets']) == {item['wallet'] for item in exports} and
                {(item['format'],item['name'],item['sha256']) for item in value['archives']} ==
                {(item['format'],item['archive'],item['archive_sha256']) for item in exports},
                'Normal READY is not bound to the original successful probe exports.')
    control = value['usb_control']
    data, actual = reset_usb_file(usb, control['name'], directory, limit=256)
    expected = ('CORE_VAULT_USBREADY_' + phase + '_' + case + '_' + nonce + '\n').encode()
    require(data == expected and actual == control['sha256'] and len(data) == control['bytes'], 'Reset USB control changed.')
    for archive in value['archives']:
        _, actual = reset_usb_file(usb, archive['name'], directory, limit=64 * 1024**2)
        require(actual == archive['sha256'], 'Reset original encrypted archive changed.')
    return {'value': value, 'sha256': sha, 'nonce': nonce, 'case': case,
            'ready_file': str((directory / (stem + '-ready.json')).name)}


def reset_probe_result(usb, directory, report, phase, ready):
    case, nonce = ready['case'], ready['nonce']
    payload, sha = reset_usb_file(usb, 'ci-reset-' + phase + '-' + case + '-' + nonce + '-probe.json',
                                 directory, limit=128 * 1024)
    result = json.loads(payload)
    required_checks = {'old_wallet_inventory_absent', 'old_receipts_absent', 'all_scoped_old_paths_absent',
                       'private_core_directories_empty', 'core_not_started', 'new_boot_id',
                       'usb_ready_control_survived', 'encrypted_usb_archives_unchanged',
                       'production_runtime_unchanged', 'private_storage_policy_passed'}
    fields = {'schema','status','phase','case','nonce','firmware','execution_uid','ready_sha256','helper_sha256',
              'guest_probe_sha256','runtime_sha256','source_boot_id','current_boot_id','fixture_mount','checks','scope'}
    require(isinstance(result, dict) and set(result) == fields and type(result.get('schema')) is int and result['schema'] == 1
            and result.get('status') == 'passed-reset-observations' and result.get('phase') == phase
            and result.get('case') == case and result.get('nonce') == nonce and result.get('firmware') == report['firmware']
            and type(result.get('execution_uid')) is int and result['execution_uid'] == 1000
            and result.get('ready_sha256') == ready['sha256'] and result.get('helper_sha256') == RESET_SHA256
            and result.get('guest_probe_sha256') == report['guest_probe_sha256']
            and result.get('runtime_sha256') == ready['value']['runtime_sha256']
            and result.get('source_boot_id') == ready['value']['source_boot_id']
            and isinstance(result.get('current_boot_id'), str)
            and re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', result['current_boot_id'])
            and result['current_boot_id'] != '00000000-0000-0000-0000-000000000000'
            and result['current_boot_id'] != result['source_boot_id']
            and isinstance(result.get('checks'), dict) and set(result['checks']) == required_checks
            and all(flag is True for flag in result['checks'].values()), 'Reset absence or READY observation failed.')
    return {'status': 'passed-reset-observations', 'result_sha256': sha,
            'source_boot_id': result['source_boot_id'], 'current_boot_id': result['current_boot_id'],
            'ready_sha256': ready['sha256'], 'checks': result['checks']}


def reset_record(vm):
    return {'pid': vm.p.pid, 'start_ticks': vm.birth, 'argv': vm.args,
            **({'opened_image_inodes':vm.reset_image_fds} if hasattr(vm,'reset_image_fds') else {})}


def reset_boot(args, root, phase, label, disk, usb, iso, variables, continuity, previous):
    directory = root / label;directory.mkdir(mode=0o700)
    continuity.before_start()
    command = qemu_command(args, phase, directory, disk, usb, iso, variables)
    require('-snapshot' not in command and '-incoming' not in command and command[command.index('-nic') + 1] == 'none',
            'Reset boot must be fresh and offline without saved RAM state.')
    vm = VM(directory, command)
    try:
        vm.retain_pidfd();vm.connect();vm.reset_image_fds = continuity.active(vm)
        require((vm.p.pid, vm.birth) != (previous['pid'], previous['start_ticks']), 'Reset reused the source QEMU identity.')
        if phase == 'live':
            _, _, first = vm.wait_boot_menu('live', args.firmware)
            if not home_screen(first):vm.key('home');vm.key('ret')
        vm.wait_screen(label + '-home', home_screen, args.boot_timeout)
        require(continuity.active(vm) == vm.reset_image_fds, 'Reset QEMU changed its actual open image identity.')
        return vm, directory
    except BaseException:
        vm.close();raise


def run_reset_cases(args, root, phase, disk, usb, iso, variables, report):
    """New-process boots; no RAM snapshot and no fake Finish for probe cleanup."""
    stage = report['stages'][phase]
    gui = stage.get('genuine_gui', {})
    native = [check for check in gui.get('checks', [])
              if check.get('check') == 'native-verified-finish-powers-off-owned-guest']
    scan = report.get('disk_marker_scans', {}).get(phase, {})
    require(stage.get('status') == 'passed-covered-checks' and stage.get('genuine_finish_shutdown') == 'passed'
            and stage.get('reset_normal_ready') and stage.get('reset_normal_runner_ack',{}).get('status') == 'passed-runner-execution'
            and gui.get('status') == 'passed-covered-checks'
            and gui.get('phase') == phase and gui.get('poweroff_observed') is True and len(native) == 1
            and native[0].get('status') == 'PASS' and native[0].get('phase') == phase
            and native[0].get('qemu_exit_code') == 0 and native[0].get('controller_quit_used') is False
            and scan.get('status') == 'PASS_NO_EXACT_SUPPLIED_MARKERS' and scan.get('phase') == phase
            and scan.get('scanned_bytes') == VIRTUAL_DISK_BYTES and scan.get('hit_count') == 0
            and scan.get('helper_sha256') == FORENSIC_SHA256,
            'Cold reset requires genuine source Finish and a bound normal READY.')
    phase_file = root/phase/'phase-result.json'
    phase_value, phase_proof = scan_json(phase_file)
    require(phase_value == stage, 'Genuine phase source does not match its frozen JSON.')
    continuity = args.reset_files
    source = stage['qemu']
    continuity.stopped([source])
    checks = report.setdefault('reset_checks', {})[phase] = {'status': 'running', 'scope':
        'Synthetic guest RAM state across clean and abrupt new-process boots only; no physical DRAM or disk-forensic claim.'}
    vm = None
    try:
        normal = stage['reset_normal_ready']
        deliver_reset_request(args,root,usb,report,phase,'normal',normal['nonce'],'probe',
                              ready_sha=normal['sha256'],stopped_records=[source])
        vm, directory = reset_boot(args, root, phase, 'reset-' + phase + '-normal', disk, usb, iso, variables,
                                   continuity, source)
        fresh = reset_record(vm)
        checks['boot_identities'] = {'source':source, 'normal':fresh}
        normal_completion = reset_guest(vm, report, phase, 'normal', normal['nonce'], 'probe', ready_sha=normal['sha256'])
        abrupt_nonce = args.reset_nonces[phase]['abrupt']
        vm.never_quit = True
        checks['abrupt_arm'] = {'status':'arming', 'qemu':fresh, 'controller_quit_used':False}
        abrupt_completion = reset_guest(vm, report, phase, 'abrupt', abrupt_nonce, 'arm-fresh')
        checks['abrupt_arm'].update(status='helper-exit-zero-before-stop', completion=abrupt_completion)
        require(continuity.active(vm) == vm.reset_image_fds, 'Abrupt arm no longer uses the retained image inodes.')
        vm.abrupt_stop()
        require(vm.p.returncode == -signal.SIGKILL, 'Abrupt case did not stop with exact SIGKILL.')
        vm.close();vm = None
        continuity.stopped([source, fresh])
        checks['normal'] = reset_probe_result(usb, directory, report, phase, normal)
        checks['normal']['runner_ack'] = reset_runner_ack(usb,directory,report,phase,'normal','probe')
        checks['normal'].update(source_qemu=source, probe_qemu=fresh, source_stop='genuine-Finish-exit-zero',
                                probe_completion=normal_completion, no_core_before_probe=True)
        abrupt = reset_ready(usb, directory, report, phase, 'abrupt', abrupt_nonce)
        abrupt_ack = reset_runner_ack(usb,directory,report,phase,'abrupt','arm-fresh')
        checks['abrupt_arm'] = {'ready_sha256': abrupt['sha256'], 'qemu': fresh, 'completion': abrupt_completion,
                                'pidfd_sigkill': True, 'exit_code': -signal.SIGKILL, 'controller_quit_used': False,
                                'status':'validated-ready-and-reaped','runner_ack':abrupt_ack}
        deliver_reset_request(args,root,usb,report,phase,'abrupt',abrupt_nonce,'probe',
                              ready_sha=abrupt['sha256'],stopped_records=[source,fresh])
        vm, final_directory = reset_boot(args, root, phase, 'reset-' + phase + '-abrupt', disk, usb, iso, variables,
                                         continuity, fresh)
        final = reset_record(vm)
        checks['boot_identities']['abrupt'] = final
        completion = reset_guest(vm, report, phase, 'abrupt', abrupt_nonce, 'probe', ready_sha=abrupt['sha256'])
        vm.close();require(vm.p.returncode == 0, 'Readonly reset probe VM cleanup did not exit normally.');vm = None
        continuity.stopped([source, fresh, final])
        checks['abrupt'] = reset_probe_result(usb, final_directory, report, phase, abrupt)
        checks['abrupt']['runner_ack'] = reset_runner_ack(usb,final_directory,report,phase,'abrupt','probe')
        require(checks['abrupt']['source_boot_id'] == checks['normal']['current_boot_id'],
                'Abrupt READY did not come from the normal cold boot.')
        checks['abrupt'].update(source_qemu=fresh, probe_qemu=final, source_stop='owned-pidfd-SIGKILL-exit-minus-nine',
                                probe_completion=completion, probe_cleanup='controlled-QMP-quit-not-genuine-Finish')
        checks['status'] = 'passed-synthetic-normal-and-abrupt-reset'
    except BaseException as error:
        checks['status'] = 'failed';checks['failure_type'] = type(error).__name__;raise
    finally:
        try:
            if vm:vm.close()
            require(scan_json(phase_file)[1] == phase_proof, 'Original genuine phase proof changed during reset checks.')
        except BaseException as error:
            checks['status'] = 'failed';checks['failure_type'] = type(error).__name__
            raise
        finally:(root / 'vm-result.json').write_text(json.dumps(report, indent=2) + '\n')


def scan_json(path, *, mode=None):
    path = plain(path)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        before = os.fstat(descriptor)
        require(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid() and before.st_nlink == 1
                and not before.st_mode & 0o022 and 0 < before.st_size <= 2 * 1024**2
                and (mode is None or stat.S_IMODE(before.st_mode) == mode), 'Unsafe bounded scan evidence file.')
        payload = os.pread(descriptor, 2 * 1024**2 + 1, 0)
        identity = lambda s: (s.st_dev, s.st_ino, s.st_uid, s.st_mode, s.st_nlink, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        require(len(payload) == before.st_size and identity(os.fstat(descriptor)) == identity(before)
                and identity(path.lstat()) == identity(before), 'Scan evidence file changed during read.')
        value = json.loads(payload)
        require(isinstance(value, dict), 'Scan evidence is not a JSON object.')
        return value, {'sha256': hashlib.sha256(payload).hexdigest(), 'identity': identity(before)}
    finally:
        os.close(descriptor)


def scan_phase(root, phase, report):
    """Synchronous scan only after real Finish; never start/stop QEMU here."""
    require(phase in ('live', 'installed') and report.get('forensic_helper_sha256') == FORENSIC_SHA256,
            'Forensic phase or frozen source identity is invalid.')
    root = plain(root)
    require(root.is_dir() and root.stat().st_uid == os.getuid() and stat.S_IMODE(root.stat().st_mode) == 0o700,
            'Forensic evidence root is not private and owned.')
    stage = report['stages'][phase]
    gui = stage.get('genuine_gui', {})
    require(isinstance(gui, dict), 'No genuine completed GUI phase exists for scanning.')
    checks = gui.get('checks', [])
    require(stage.get('status') == 'passed-covered-checks' and stage.get('genuine_finish_shutdown') == 'passed'
            and isinstance(gui, dict) and gui.get('status') == 'passed-covered-checks'
            and gui.get('phase') == phase and gui.get('poweroff_observed') is True
            and isinstance(checks, list) and checks and all(isinstance(c, dict) and c.get('status') == 'PASS'
                and c.get('phase') == phase for c in checks), 'No genuine completed Finish phase exists for scanning.')
    power = [c for c in checks if c.get('check') == 'native-verified-finish-powers-off-owned-guest']
    require(len(power) == 1 and type(power[0].get('qemu_exit_code')) is int and power[0]['qemu_exit_code'] == 0
            and power[0].get('controller_quit_used') is False, 'Forensic scan requires native exit zero without controller quit.')
    if phase == 'live':
        require(set(report['stages']) == {'live'} and not (root / 'installer').exists()
                and not (root / 'installed').exists(), 'Live forensic scan must precede installer creation.')
    phase_file, top_file = root / phase / 'phase-result.json', root / 'vm-result.json'
    saved_stage, phase_proof = scan_json(phase_file)
    top, top_proof = scan_json(top_file)
    require(saved_stage == stage and top.get('stages', {}).get(phase) == stage,
            'Completed forensic phase JSON does not match the controller.')
    helper = forensic_helper()
    try:
        child = run([sys.executable, str(helper), '--evidence-root', str(root), '--phase', phase],
                    capture_output=True, text=True, timeout=930)
        require(child.returncode == 0, 'Owned forensic scan failed.')
        summary = json.loads(child.stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        raise RuntimeError('Owned forensic scan did not complete successfully: ' + phase) from None
    require(digest(helper) == FORENSIC_SHA256, 'Frozen forensic helper changed during scanning.')
    require(scan_json(phase_file)[1] == phase_proof and scan_json(top_file)[1] == top_proof,
            'Completed phase inputs changed during scanning.')
    require(isinstance(summary, dict) and summary.get('status') == 'PASS_NO_EXACT_SUPPLIED_MARKERS'
            and type(summary.get('scanned_bytes')) is int and summary['scanned_bytes'] == VIRTUAL_DISK_BYTES
            and type(summary.get('hit_count')) is int and summary['hit_count'] == 0,
            'Forensic scan did not prove a complete zero-hit virtual disk scan.')
    require(isinstance(summary.get('result'), str), 'Forensic scan result path is missing.')
    result_path = plain(summary['result'])
    require(result_path.name == 'scan-result.json' and result_path.parent.parent == root
            and re.fullmatch(r'forensic-[0-9a-f]{32}', result_path.parent.name)
            and result_path.parent.stat().st_uid == os.getuid()
            and stat.S_IMODE(result_path.parent.stat().st_mode) == 0o700, 'Forensic result is outside its owned output directory.')
    result, result_proof = scan_json(result_path, mode=0o600)
    evidence = result.get('evidence', {})
    require(result.get('status') == summary['status'] and result.get('requested_phase') == phase
            and type(result.get('scanned_bytes')) is int and result['scanned_bytes'] == VIRTUAL_DISK_BYTES
            and type(result.get('hit_count')) is int and result['hit_count'] == 0
            and isinstance(evidence, dict) and evidence.get('scanned_phases') == [phase]
            and evidence.get('live_before_installation') is (phase == 'live')
            and evidence.get('iso_sha256') == report['iso_sha256']
            and evidence.get('harness_sha256') == report['harness_sha256']
            and evidence.get('helper_sha256') == report['helper_sha256']
            and evidence.get('gui_helper_sha256') == report['gui_helper_sha256']
            and all(result.get(key) is True for key in ('all_owned_qemu_reaped',
                'no_active_own_qemu_referencing_image', 'source_json_unchanged', 'source_and_raw_identities_unchanged')),
            'Forensic result phase, source or stopped-image proof does not match.')
    source = result.get('source_disk', {})
    source_sha = source.get('sha256_before') if isinstance(source, dict) else None
    require(isinstance(source, dict) and source.get('file') == str(root / 'target.qcow2')
            and isinstance(source_sha, str) and re.fullmatch(r'[0-9a-f]{64}', source_sha)
            and result.get('source_qcow_sha256_after') == source_sha
            and isinstance(result.get('raw_sha256'), str) and re.fullmatch(r'[0-9a-f]{64}', result['raw_sha256']),
            'Forensic source disk or complete raw digest is invalid.')
    boundary = result.get('immutable_boundary', {})
    boundary_path = result_path.parent / 'phase-boundary.json'
    boundary_data, boundary_proof = scan_json(boundary_path, mode=0o400)
    require(isinstance(boundary, dict) and boundary.get('file') == str(boundary_path)
            and boundary.get('sha256') == boundary_proof['sha256']
            and boundary_data.get('requested_phase') == phase
            and boundary_data.get('disk_sha256') == source_sha
            and boundary_data.get('status') == 'validated-genuine-finish-boundary', 'Forensic immutable boundary is invalid.')
    record = {'status': summary['status'], 'phase': phase, 'result': str(result_path.relative_to(root)),
              'result_sha256': result_proof['sha256'], 'boundary_sha256': boundary_proof['sha256'],
              'helper_sha256': FORENSIC_SHA256, 'scanned_bytes': VIRTUAL_DISK_BYTES, 'hit_count': 0,
              'scope': 'Exact supplied public phase markers in current guest-visible internal virtual disk bytes only.'}
    # Original phase proofs stay unchanged. The boundary preserves the earlier
    # top report; only this top-level summary is added after the child exits.
    report.setdefault('disk_marker_scans', {})[phase] = record
    top_file.write_text(json.dumps(report, indent=2) + '\n')
    return record


def run_requested_phases(args, root, disk, usb, iso, variables, report):
    run_phase(args, root, 'live', disk, usb, iso, variables, report)
    if args.scan:scan_phase(root, 'live', report)
    if getattr(args, 'reset', False):run_reset_cases(args, root, 'live', disk, usb, iso, variables, report)
    report['normal_live_home_boot'] = 'passed'
    if args.install:
        run_phase(args, root, 'installer', disk, usb, iso, variables, report)
        report['installation'] = 'passed'
        run_phase(args, root, 'installed', disk, usb, iso, variables, report)
        if args.scan:scan_phase(root, 'installed', report)
        if getattr(args, 'reset', False):run_reset_cases(args, root, 'installed', disk, usb, iso, variables, report)
        report['installed_boot_and_runtime_probe'] = 'passed'
    if args.gui:
        report['genuine_backup_dialogs'] = 'passed-requested-phases'
        report['genuine_finish_dialogs_and_session_destruction'] = 'passed-normal-shutdown-requested-phases'
    report['candidate_psbt_signing'] = 'passed-supplied-synthetic-witness-utxo-requested-phases'
    if getattr(args, 'reset', False):
        phases = {'live', 'installed'} if args.install else {'live'}
        require(set(report.get('reset_checks', {})) == phases and all(value.get('status') ==
                'passed-synthetic-normal-and-abrupt-reset' for value in report['reset_checks'].values()),
                'All requested cold-reset phase cases must pass.')
        report['cold_reset_checks'] = 'passed-synthetic-normal-and-abrupt-new-process-boots-requested-phases'
    report['status'] = 'passed-covered-checks'


def scan_self_test():
    """Synthetic metadata and mocked subprocesses only; no QEMU or scans."""
    import tempfile
    from types import SimpleNamespace
    import unittest
    from unittest.mock import patch

    class Tests(unittest.TestCase):
        def fixture(self, root):
            root.chmod(0o700); (root / 'live').mkdir(mode=0o700)
            checks = [{'check': 'native-verified-finish-powers-off-owned-guest', 'status': 'PASS', 'phase': 'live',
                       'qemu_exit_code': 0, 'controller_quit_used': False}]
            stage = {'status': 'passed-covered-checks', 'genuine_finish_shutdown': 'passed',
                     'genuine_gui': {'status': 'passed-covered-checks', 'phase': 'live',
                                     'poweroff_observed': True, 'checks': checks}}
            report = {'status': 'running', 'stages': {'live': stage}, 'forensic_helper_sha256': FORENSIC_SHA256,
                      'iso_sha256': '1' * 64, 'harness_sha256': '2' * 64, 'gui_helper_sha256': '3' * 64,
                      'helper_sha256': {'ci-vm-guest-probe.py': '4' * 64, 'ci-vm-psbt.py': '5' * 64},
                      'cold_reset_and_disk_scan': 'pending'}
            self.save(root, report)
            return report

        def save(self, root, report):
            (root / 'live' / 'phase-result.json').write_text(json.dumps(report['stages']['live']))
            (root / 'vm-result.json').write_text(json.dumps(report))

        def child(self, root, report, *, change=None, returncode=0, mutate_input=False):
            directory = root / ('forensic-' + 'a' * 32); directory.mkdir(mode=0o700)
            boundary = directory / 'phase-boundary.json'
            boundary.write_text(json.dumps({'status': 'validated-genuine-finish-boundary',
                'requested_phase': 'live', 'disk_sha256': '6' * 64})); boundary.chmod(0o400)
            result = {'status': 'PASS_NO_EXACT_SUPPLIED_MARKERS', 'requested_phase': 'live',
                'scanned_bytes': VIRTUAL_DISK_BYTES, 'hit_count': 0,
                'evidence': {'scanned_phases': ['live'], 'live_before_installation': True,
                    **{key: report[key] for key in ('iso_sha256', 'harness_sha256', 'helper_sha256', 'gui_helper_sha256')}},
                'all_owned_qemu_reaped': True, 'no_active_own_qemu_referencing_image': True,
                'source_json_unchanged': True, 'source_and_raw_identities_unchanged': True,
                'source_disk': {'file': str(root / 'target.qcow2'), 'sha256_before': '6' * 64},
                'source_qcow_sha256_after': '6' * 64, 'raw_sha256': '7' * 64,
                'immutable_boundary': {'file': str(boundary), 'sha256': digest(boundary)}}
            if change:change(result)
            path = directory / 'scan-result.json'; path.write_text(json.dumps(result)); path.chmod(0o600)
            summary = {key: result[key] for key in ('status', 'scanned_bytes', 'hit_count')}
            summary['result'] = str(path)
            if mutate_input:(root / 'live' / 'phase-result.json').write_text('{}')
            return SimpleNamespace(returncode=returncode, stdout=json.dumps(summary))

        def test_success_records_only_top_summary_and_keeps_cold_pending(self):
            with tempfile.TemporaryDirectory(prefix='cv-host-scan-unit-') as temporary:
                root = Path(temporary); report = self.fixture(root)
                phase = (root / 'live' / 'phase-result.json').read_bytes()
                def child(args, **kw):
                    self.assertEqual(args[-2:], ['--phase', 'live']); self.assertEqual(kw['timeout'], 930)
                    return self.child(root, report)
                with patch.dict(globals(), {'run': child}):record = scan_phase(root, 'live', report)
                self.assertEqual(record['hit_count'], 0)
                self.assertEqual((root / 'live' / 'phase-result.json').read_bytes(), phase)
                self.assertEqual(report['cold_reset_and_disk_scan'], 'pending')
                self.assertEqual(scan_json(root / 'vm-result.json')[0]['disk_marker_scans']['live'], record)

        def test_failed_finish_or_controller_quit_never_launches_child(self):
            for field, value in (('genuine_finish_shutdown', 'failed'), ('status', 'failed')):
                with tempfile.TemporaryDirectory(prefix='cv-host-scan-unit-') as temporary:
                    root = Path(temporary); report = self.fixture(root); report['stages']['live'][field] = value
                    with patch.dict(globals(), {'run': lambda *a, **k: self.fail('Child launched before Finish')}):
                        with self.assertRaises(RuntimeError):scan_phase(root, 'live', report)
            with tempfile.TemporaryDirectory(prefix='cv-host-scan-unit-') as temporary:
                root = Path(temporary); report = self.fixture(root)
                report['stages']['live']['genuine_gui']['checks'][0]['controller_quit_used'] = True
                with patch.dict(globals(), {'run': lambda *a, **k: self.fail('Controller quit accepted')}):
                    with self.assertRaises(RuntimeError):scan_phase(root, 'live', report)

        def test_changed_source_never_launches_child(self):
            with tempfile.TemporaryDirectory(prefix='cv-host-scan-unit-') as temporary:
                root = Path(temporary); report = self.fixture(root)
                with patch.dict(globals(), {'digest': lambda path: '0' * 64,
                        'run': lambda *a, **k: self.fail('Changed helper launched')}):
                    with self.assertRaisesRegex(RuntimeError, 'Frozen forensic helper'):scan_phase(root, 'live', report)

        def test_failed_partial_hit_wrong_phase_or_source_results_refused(self):
            changes = [lambda r: r.update(status='FAIL_EXACT_MARKER_FOUND'),
                       lambda r: r.update(scanned_bytes=VIRTUAL_DISK_BYTES - 1),
                       lambda r: r.update(hit_count=1), lambda r: r.update(requested_phase='installed'),
                       lambda r: r['evidence'].update(harness_sha256='0' * 64),
                       lambda r: r['source_disk'].update(file='/dev/sda'),
                       lambda r: r.update(source_qcow_sha256_after='0' * 64),
                       lambda r: r['immutable_boundary'].update(sha256='0' * 64)]
            for change in changes:
                with tempfile.TemporaryDirectory(prefix='cv-host-scan-unit-') as temporary:
                    root = Path(temporary); report = self.fixture(root)
                    with patch.dict(globals(), {'run': lambda *a, **k: self.child(root, report, change=change)}):
                        with self.assertRaises(RuntimeError):scan_phase(root, 'live', report)
                    self.assertNotIn('disk_marker_scans', report)

        def test_nonzero_child_and_changed_phase_inputs_refused(self):
            for kwargs in ({'returncode': 1}, {'mutate_input': True}):
                with tempfile.TemporaryDirectory(prefix='cv-host-scan-unit-') as temporary:
                    root = Path(temporary); report = self.fixture(root)
                    with patch.dict(globals(), {'run': lambda *a, **k: self.child(root, report, **kwargs)}):
                        with self.assertRaises(RuntimeError):scan_phase(root, 'live', report)
                    self.assertNotIn('disk_marker_scans', report)

        def test_live_scan_refuses_any_existing_installer_directory(self):
            with tempfile.TemporaryDirectory(prefix='cv-host-scan-unit-') as temporary:
                root = Path(temporary); report = self.fixture(root); (root / 'installer').mkdir()
                with patch.dict(globals(), {'run': lambda *a, **k: self.fail('Late Live scan launched')}):
                    with self.assertRaisesRegex(RuntimeError, 'precede installer'):scan_phase(root, 'live', report)

        def test_scan_requires_gui_before_any_filesystem_or_vm_action(self):
            argv = ['ci-vm-acceptance.py', '--iso', 'unused', '--sha256', '0' * 64,
                    '--output', 'unused', '--firmware', 'bios', '--scan']
            with patch.object(sys, 'argv', argv):
                with self.assertRaisesRegex(RuntimeError, '--scan requires genuine --gui'):main()

        def test_phase_order_and_failure_stop_before_installer(self):
            args = SimpleNamespace(scan=True, install=True, gui=True)
            for failure in (None, 'live', 'scan-live'):
                events = []; report = {'stages': {}, 'cold_reset_and_disk_scan': 'pending'}
                def phase(args, root, name, *unused):
                    events.append(name)
                    if failure == name:raise RuntimeError('synthetic failed Finish')
                    report['stages'][name] = {}
                def scan(root, name, report):
                    events.append('scan-' + name)
                    if name == 'live':self.assertEqual(set(report['stages']), {'live'})
                    if failure == 'scan-' + name:raise RuntimeError('synthetic failed scan')
                with patch.dict(globals(), {'run_phase': phase, 'scan_phase': scan}):
                    if failure:
                        with self.assertRaises(RuntimeError):run_requested_phases(args, Path('/synthetic'), None, None, None, None, report)
                    else:run_requested_phases(args, Path('/synthetic'), None, None, None, None, report)
                self.assertEqual(events, ['live'] if failure == 'live' else ['live', 'scan-live'] if failure else
                                 ['live', 'scan-live', 'installer', 'installed', 'scan-installed'])
                self.assertEqual(report['cold_reset_and_disk_scan'], 'pending')

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(Tests)
    return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1


def reset_self_test():
    """Public metadata, temporary ordinary files and mocks; no VM or signals."""
    import copy
    import tempfile
    import unittest
    from types import SimpleNamespace
    from unittest.mock import Mock, patch

    class Tests(unittest.TestCase):
        def report(self):
            return {'firmware':'bios','guest_probe_sha256':'2'*64,'reset_helper_sha256':RESET_SHA256,
                    'stages':{'live':{'guest_probe':{'runtime_sha256':{str(i):'3'*64 for i in range(8)},
                                                  'exports':[]}}}}

        def ready(self):
            nonce='a'*32;names=['cv-forensic-ci-'+format+'-'+nonce for format in ('7z','gpg')]
            data=('CORE_VAULT_USBREADY_live_normal_'+nonce+'\n').encode()
            value={'schema':1,'status':'USBREADY','case':'normal','nonce':nonce,'phase':'live','firmware':'bios',
                   'source_boot_id':'12345678-1234-4321-abcd-123456789abc','execution_uid':1000,
                   'target_serial':'CV_RAM_TEST_INTERNAL','fixture_serial':'CV_RAM_TEST_USB',
                   'helper_sha256':RESET_SHA256,'guest_probe_sha256':'2'*64,
                   'runtime_sha256':{str(i):'3'*64 for i in range(8)},
                   'usb_control':{'name':'ci-reset-live-normal-'+nonce+'-USBREADY.txt',
                                  'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)},
                   'wallets':names,'archives':[{'format':format,'name':name+'-encrypted.'+format,
                                               'sha256':hashlib.sha256(format.encode()).hexdigest()}
                                               for format,name in zip(('7z','gpg'),names)],
                   'core_state':'closed','armed':{'wallet_inventory_present':True,'receipts_present':True,
                       'recovered_snapshot_authenticated':True,'sentinels_present':True,'core_ram_logs_present':True,
                       'core_state_observed':True,'finish_invoked_by_reset_helper':False},'scope':'Synthetic unit only.'}
            report=self.report()
            report['stages']['live']['guest_probe']['exports']=[{'wallet':name,'format':item['format'],
                'archive':item['name'],'archive_sha256':item['sha256']} for name,item in zip(names,value['archives'])]
            return value,report,data

        def test_reset_requires_both_flags_before_file_or_vm_actions(self):
            for flags in ([],['--gui']):
                with patch.object(sys,'argv',['harness','--iso','unused','--sha256','0'*64,
                                              '--output','unused','--firmware','bios','--reset',*flags]):
                    with self.assertRaisesRegex(RuntimeError,'--reset requires'):main()

        def test_phase_order_reset_after_scan_before_installer_and_all_cases_required(self):
            args=SimpleNamespace(scan=True,gui=True,reset=True,install=True)
            for failed in (None,'reset-live','reset-installed'):
                events=[];report={'stages':{},'cold_reset_and_disk_scan':'pending'}
                def phase(args,root,name,*unused):events.append(name)
                def scan(root,name,report):events.append('scan-'+name)
                def reset(args,root,name,*unused):
                    events.append('reset-'+name)
                    if failed=='reset-'+name:raise RuntimeError('Synthetic reset failure')
                    report.setdefault('reset_checks',{})[name]={'status':'passed-synthetic-normal-and-abrupt-reset'}
                with patch.dict(globals(),{'run_phase':phase,'scan_phase':scan,'run_reset_cases':reset}):
                    if failed:
                        with self.assertRaises(RuntimeError):run_requested_phases(args,Path('/unit'),None,None,None,None,report)
                    else:run_requested_phases(args,Path('/unit'),None,None,None,None,report)
                expected=['live','scan-live','reset-live','installer','installed','scan-installed','reset-installed']
                self.assertEqual(events,expected[:3] if failed=='reset-live' else expected)
                self.assertEqual(report['cold_reset_and_disk_scan'],'pending')
                self.assertEqual('cold_reset_checks' in report,failed is None)

        def test_pidfd_guard_order_and_exact_reap(self):
            vm=VM.__new__(VM);vm.pidfd=None;events=[]
            vm.p=SimpleNamespace(pid=123,wait=lambda **kw:events.append('wait') or -9)
            vm.guard=lambda:events.append('guard')
            with patch.object(os,'pidfd_open',lambda pid,flags:events.append(('open',pid)) or 77),\
                 patch.object(signal,'pidfd_send_signal',lambda fd,sig,*rest:events.append(('signal',fd,sig))):
                vm.retain_pidfd();vm.abrupt_stop()
            self.assertEqual(events,['guard',('open',123),'guard','guard',('signal',77,signal.SIGKILL),'wait'])

        def test_abrupt_failure_keeps_pidfd_and_never_quits_or_pid_kills(self):
            for failure in ('identity','signal','wait','wrong-exit'):
                vm=VM.__new__(VM);vm.pidfd=77;vm.never_quit=True
                vm.p=Mock(returncode=None);vm.reader=vm.sock=None;vm.log=Mock();vm.call=Mock()
                vm.guard=Mock(side_effect=RuntimeError('identity') if failure=='identity' else None)
                vm.p.wait.side_effect=subprocess.TimeoutExpired('owned',15) if failure=='wait' else None
                vm.p.wait.return_value=0 if failure=='wrong-exit' else -9
                with patch.object(signal,'pidfd_send_signal',side_effect=PermissionError('unit') if failure=='signal' else None),\
                     patch.object(os,'close') as close:
                    with self.assertRaises((RuntimeError,PermissionError,subprocess.TimeoutExpired)):vm.close()
                vm.call.assert_not_called();vm.p.kill.assert_not_called();close.assert_not_called()
                self.assertEqual(vm.pidfd,77)

        def files(self,root):
            root.chmod(0o700)
            paths=[]
            for name in ('disk','usb','iso'):
                path=root/name;path.write_bytes(name.encode());path.chmod(0o600);paths.append(path)
            fake=SimpleNamespace(stopped_qemu=lambda *unused:None,validate_header=lambda *unused:None)
            with patch.dict(globals(),{'frozen_module':lambda *unused:fake}):
                return ResetFiles(root,*paths,None),paths

        def test_stopped_image_identity_modes_and_hash_continuity(self):
            for change in ('replacement','symlink','hardlink','mode','content','readonly'):
                with tempfile.TemporaryDirectory(prefix='cv-reset-host-unit-') as temporary:
                    root=Path(temporary);files,paths=self.files(root)
                    try:
                        disk,usb,iso=paths
                        if change in ('replacement','symlink'):
                            disk.rename(root/'old')
                            if change=='replacement':disk.write_bytes(b'disk');disk.chmod(0o600)
                            else:disk.symlink_to(root/'old')
                        elif change=='hardlink':os.link(disk,root/'alias')
                        elif change=='mode':usb.chmod(0o622)
                        elif change=='readonly':iso.write_bytes(b'changed-readonly')
                        else:usb.write_bytes(b'changed')
                        with self.assertRaises(RuntimeError):files.before_start()
                    finally:files.close()

        def test_path_replacement_during_boundary_hash_refused(self):
            with tempfile.TemporaryDirectory(prefix='cv-reset-host-unit-') as temporary:
                root=Path(temporary);files,paths=self.files(root)
                original=files.hash_fd;changed=False
                def hashing(fd):
                    nonlocal changed
                    value=original(fd)
                    if fd==files.files['usb']['fd'] and not changed:
                        paths[0].rename(root/'old');paths[0].write_bytes(b'disk');paths[0].chmod(0o600);changed=True
                    return value
                try:
                    with patch.object(files,'hash_fd',hashing):
                        with self.assertRaisesRegex(RuntimeError,'inode'):files.before_start()
                finally:files.close()

        def test_only_owned_qemu_open_expected_image_inodes_are_accepted(self):
            with tempfile.TemporaryDirectory(prefix='cv-reset-host-unit-') as temporary:
                root=Path(temporary);files,paths=self.files(root)
                process=root/'proc'/'123';(process/'fd').mkdir(parents=True,mode=0o700)
                vm=SimpleNamespace(p=SimpleNamespace(pid=123),guard=Mock())
                try:
                    for number,path in enumerate(paths[:2]):(process/'fd'/str(number)).symlink_to(path)
                    self.assertEqual(set(files.active(vm,proc_root=root/'proc')),{'disk','usb'})
                    self.assertEqual(vm.guard.call_count,2)
                    (process/'fd'/'0').unlink();(process/'fd'/'0').symlink_to(paths[2])
                    with self.assertRaisesRegex(RuntimeError,'did not open'):files.active(vm,proc_root=root/'proc')
                finally:files.close()

        def test_ready_binds_original_exports_controls_runtime_and_complete_arm(self):
            value,report,data=self.ready()
            def read(usb,name,directory,**kw):
                payload=json.dumps(value).encode() if name.endswith('-ready.json') else data if name.endswith('-USBREADY.txt') else name.rsplit('.',1)[1].encode()
                return payload,hashlib.sha256(payload).hexdigest()
            changes=[None,lambda v:v['armed'].update(sentinels_present=False),lambda v:v.update(core_state='running-loaded'),
                     lambda v:v['usb_control'].update(sha256='0'*64),lambda v:v['runtime_sha256'].update({'0':'0'*64}),
                     lambda v:v['archives'][0].update(sha256='0'*64)]
            for change in changes:
                value,report,data=self.ready()
                if change:change(value)
                with patch.dict(globals(),{'reset_usb_file':read}):
                    if change:
                        with self.assertRaises(RuntimeError):reset_ready(None,Path('/unit'),report,'live','normal','a'*32)
                    else:self.assertEqual(reset_ready(None,Path('/unit'),report,'live','normal','a'*32)['value'],value)

        def test_absence_probe_refuses_false_missing_same_boot_or_wrong_identity(self):
            ready,report,_=self.ready();ready={'value':ready,'sha256':'4'*64,'nonce':'a'*32,'case':'normal'}
            value={'schema':1,'status':'passed-reset-observations','phase':'live','case':'normal','nonce':'a'*32,
                'firmware':'bios','execution_uid':1000,'ready_sha256':'4'*64,'helper_sha256':RESET_SHA256,
                'guest_probe_sha256':'2'*64,'runtime_sha256':ready['value']['runtime_sha256'],
                'source_boot_id':ready['value']['source_boot_id'],'current_boot_id':'abcdef01-1234-4321-abcd-123456789abc',
                'fixture_mount':{},'scope':'Unit','checks':dict.fromkeys(('old_wallet_inventory_absent','old_receipts_absent',
                    'all_scoped_old_paths_absent','private_core_directories_empty','core_not_started','new_boot_id',
                    'usb_ready_control_survived','encrypted_usb_archives_unchanged','production_runtime_unchanged',
                    'private_storage_policy_passed'),True)}
            changes=[None,lambda v:v['checks'].update(old_receipts_absent=False),lambda v:v['checks'].pop('core_not_started'),
                lambda v:v.update(current_boot_id=v['source_boot_id']),lambda v:v.update(helper_sha256='0'*64),
                lambda v:v.update(current_boot_id='00000000-0000-0000-0000-000000000000'),
                lambda v:v.update(ready_sha256='0'*64),lambda v:v.update(execution_uid=0)]
            for change in changes:
                result=copy.deepcopy(value)
                if change:change(result)
                with patch.dict(globals(),{'reset_usb_file':lambda *a,**k:(json.dumps(result).encode(),'5'*64)}):
                    if change:
                        with self.assertRaises(RuntimeError):reset_probe_result(None,Path('/unit'),report,'live',ready)
                    else:self.assertEqual(reset_probe_result(None,Path('/unit'),report,'live',ready)['status'],'passed-reset-observations')

        def test_failed_finish_or_scan_never_launches_reset(self):
            for stage in ({}, {'status':'passed-covered-checks','genuine_finish_shutdown':'passed',
                              'reset_normal_ready':{},'genuine_gui':{'controller_quit_used':True}}):
                with patch.dict(globals(),{'reset_boot':lambda *a:self.fail('Unproved cold boot launched')}):
                    with self.assertRaisesRegex(RuntimeError,'genuine source Finish'):
                        run_reset_cases(SimpleNamespace(),Path('/unit'),'live',None,None,None,None,{'stages':{'live':stage}})

        def test_actual_orchestration_requires_reaped_arm_before_readback_and_next_boot(self):
            for fail in (None,'READY','absence','phase-change'):
                with tempfile.TemporaryDirectory(prefix='cv-reset-host-unit-') as temporary:
                    root=Path(temporary);(root/'live').mkdir(mode=0o700);events=[]
                    source={'pid':1,'start_ticks':'1','argv':['owned-source']}
                    native={'check':'native-verified-finish-powers-off-owned-guest','status':'PASS','phase':'live',
                            'qemu_exit_code':0,'controller_quit_used':False}
                    stage={'status':'passed-covered-checks','genuine_finish_shutdown':'passed','qemu':source,
                           'reset_normal_ready':{'nonce':'a'*32,'sha256':'4'*64},
                           'genuine_gui':{'status':'passed-covered-checks','phase':'live','poweroff_observed':True,'checks':[native]}}
                    report={'stages':{'live':stage},'disk_marker_scans':{'live':{'status':'PASS_NO_EXACT_SUPPLIED_MARKERS',
                            'phase':'live','scanned_bytes':VIRTUAL_DISK_BYTES,'hit_count':0,'helper_sha256':FORENSIC_SHA256}}}
                    phase_file=root/'live'/'phase-result.json';phase_file.write_text(json.dumps(stage))
                    continuity=SimpleNamespace(stopped=lambda *a:events.append('stopped'),active=lambda *a:{'disk':'unit'})
                    args=SimpleNamespace(reset_files=continuity,reset_nonces={'live':{'abrupt':'b'*32}})
                    class FakeVM:
                        def __init__(self,label):
                            self.label=label;self.birth='2' if label.endswith('normal') else '3'
                            self.args=[label];self.p=SimpleNamespace(pid=int(self.birth),returncode=None)
                            self.reset_image_fds={'disk':'unit'}
                            self.never_quit=False
                        def abrupt_stop(self):events.append('pidfd-SIGKILL');self.p.returncode=-9
                        def close(self):
                            events.append('close-'+str(self.p.returncode))
                            if self.p.returncode is None:self.p.returncode=0
                    def boot(args,root,phase,label,*unused):
                        events.append(label);directory=root/label;directory.mkdir(mode=0o700)
                        return FakeVM(label),directory
                    def guest(vm,report,phase,case,nonce,mode,**kw):
                        events.append(mode+'-'+case)
                        if fail=='phase-change':phase_file.write_text('{}')
                        return {'status':'completed-exit-zero'}
                    def ready(*unused):
                        events.append('read-READY')
                        if fail=='READY':raise RuntimeError('Synthetic READY failure')
                        return {'sha256':'5'*64,'nonce':'b'*32,'case':'abrupt'}
                    def result(usb,directory,report,phase,ready):
                        events.append('read-'+ready.get('case','normal'))
                        if fail=='absence':raise RuntimeError('Synthetic absence failure')
                        return {'source_boot_id':'first' if ready.get('case')!='abrupt' else 'second',
                                'current_boot_id':'second' if ready.get('case')!='abrupt' else 'third'}
                    stage['reset_normal_runner_ack']={'status':'passed-runner-execution'}
                    phase_file.write_text(json.dumps(stage))
                    def request(*a,**kw):events.append('request-'+a[5]);return {}
                    def ack(*a):events.append('ack-'+a[4]+'-'+a[5]);return {'status':'passed-runner-execution'}
                    with patch.dict(globals(),{'reset_boot':boot,'reset_guest':guest,'reset_ready':ready,'reset_probe_result':result,
                                              'deliver_reset_request':request,'reset_runner_ack':ack}):
                        if fail:
                            with self.assertRaises(RuntimeError):run_reset_cases(args,root,'live',None,None,None,None,report)
                            self.assertEqual(report['reset_checks']['live']['status'],'failed')
                        else:
                            run_reset_cases(args,root,'live',None,None,None,None,report)
                            self.assertEqual(report['reset_checks']['live']['status'],'passed-synthetic-normal-and-abrupt-reset')
                            self.assertEqual(events,['stopped','request-normal','reset-live-normal','probe-normal','arm-fresh-abrupt',
                                'pidfd-SIGKILL','close--9','stopped','read-normal','ack-normal-probe','read-READY',
                                'ack-abrupt-arm-fresh','request-abrupt','reset-live-abrupt','probe-abrupt','close-None',
                                'stopped','read-abrupt','ack-abrupt-probe'])
                    if fail in ('READY','absence'):self.assertNotIn('reset-live-abrupt',events)
                    if fail!='phase-change':self.assertEqual(json.loads(phase_file.read_text()),stage)

        def test_changed_reset_source_is_not_imported(self):
            with patch.dict(globals(),{'digest':lambda *unused:'0'*64}),\
                 patch.object(importlib.util,'spec_from_file_location',side_effect=AssertionError('changed source loaded')):
                with self.assertRaisesRegex(RuntimeError,'Frozen reset dependency'):frozen_module('ci-vm-reset-probe.py',RESET_SHA256)

        def transport_report(self):
            report=self.report();report['guest_probe_sha256']=RESET_PROBE_SHA256
            report['reset_runner_sha256']=RESET_RUNNER_SHA256;report['gui_helper_sha256']='6'*64
            report['stages']={}
            return report

        def test_real_runner_schema_accepts_all_host_slots_and_rejects_substitution(self):
            runner=frozen_module('ci-vm-reset-runner.py',RESET_RUNNER_SHA256);report=self.transport_report()
            for phase in ('live','installed'):
                for case in ('normal','abrupt'):
                    for mode in ('probe','arm-existing' if case=='normal' else 'arm-fresh'):
                        value=reset_request(report,phase,case,'a'*32,mode,'b'*64 if mode=='probe' else None)
                        self.assertEqual(runner.validate_request(value,value['slot'])[:2],(phase,case))
                        self.assertEqual(runner.banner(value['slot'],0),
                            'VAULT CI RESET '+case.upper()+' '+('PROBE' if mode=='probe' else 'ARM')+' DONE EXIT 0')
            for args in (('live','abrupt','a'*32,'arm-existing',None),('live','normal','a'*32,'arm-fresh',None),
                         ('live','normal','0'*32,'arm-existing',None),('live','normal','a'*32,'probe',None),
                         ('live','normal','a'*32,'arm-existing','b'*64)):
                with self.assertRaises(RuntimeError):reset_request(report,*args)
            report['guest_probe_sha256']='0'*64
            with self.assertRaisesRegex(RuntimeError,'source'):reset_request(report,'live','normal','a'*32,'arm-existing')

        def test_request_delivery_requires_stop_readback_then_new_boundary(self):
            for failure in (None,'active','corrupt','duplicate-slot','probe-initial'):
                with tempfile.TemporaryDirectory(prefix='cv-short-reset-unit-') as temporary:
                    root=Path(temporary);(root/'fixture-delivery').mkdir(mode=0o700)
                    report=self.transport_report();events=[];fat={}
                    def stopped(records):
                        events.append('stopped')
                        if failure=='active':raise RuntimeError('Active own QEMU')
                    args=SimpleNamespace(reset_files=SimpleNamespace(stopped=stopped))
                    def copy_file(argv,**kw):
                        events.append('mcopy')
                        if argv[-1].startswith('::'):fat[argv[-1]]=Path(argv[-2]).read_bytes()
                        else:
                            data=fat[argv[-2]]
                            if failure=='corrupt':data=b'{}'
                            Path(argv[-1]).write_bytes(data)
                    if failure=='duplicate-slot':report['reset_requests']={'live-normal-probe':{}}
                    with patch.dict(globals(),{'run':copy_file}):
                        if failure:
                            with self.assertRaises(RuntimeError):deliver_reset_request(args,root,root/'usb',report,
                                'live','normal','a'*32,'probe',ready_sha='b'*64,stopped_records=[{'pid':1}],
                                initial=failure=='probe-initial')
                            if failure in ('active','duplicate-slot','probe-initial'):self.assertNotIn('mcopy',events)
                        else:
                            value=deliver_reset_request(args,root,root/'usb',report,'live','normal','a'*32,'probe',
                                                        ready_sha='b'*64,stopped_records=[{'pid':1}])
                            self.assertEqual(events,['stopped','mcopy','mcopy','stopped'])
                            self.assertEqual(value['value']['ready_sha256'],'b'*64)
                            self.assertEqual(stat.S_IMODE((root/value['source']).stat().st_mode),0o600)

        def test_actual_runner_ack_binds_used_request_code_and_exact_schema(self):
            report=self.transport_report();value=reset_request(report,'live','normal','a'*32,'arm-existing')
            payload=json.dumps(value).encode();request_sha=hashlib.sha256(payload).hexdigest()
            report['reset_requests']={'live-normal-arm':{'value':value,'sha256':request_sha,
                'filename':'ci-reset-request-live-normal-arm.json'}}
            expected={'schema':1,'slot':'live-normal-arm','phase':'live','firmware':'bios','case':'normal','nonce':'a'*32,
                'request_sha256':request_sha,'runner_sha256':RESET_RUNNER_SHA256,'helper_sha256':RESET_SHA256,
                'probe_sha256':RESET_PROBE_SHA256,'status':'passed-runner-execution','helper_exit_code':0}
            for change in (None,'request','runner','nonzero','extra','boolean','duplicate-json'):
                ack=copy.deepcopy(expected)
                if change=='runner':ack['runner_sha256']='0'*64
                if change=='nonzero':ack['helper_exit_code']=1
                if change=='extra':ack['arbitrary_path']='/other'
                if change=='boolean':ack['helper_exit_code']=False
                def read(usb,name,directory,**kw):
                    if name.startswith('ci-reset-request-'):
                        data=b'{}' if change=='request' else payload
                    else:
                        data=json.dumps(ack).encode()
                        if change=='duplicate-json':data=b'{"schema":1,'+data[1:]
                    return data,hashlib.sha256(data).hexdigest()
                with patch.dict(globals(),{'reset_usb_file':read}):
                    if change:
                        with self.assertRaises(RuntimeError):reset_runner_ack(None,Path('/unit'),report,'live','normal','arm-existing')
                    else:self.assertEqual(reset_runner_ack(None,Path('/unit'),report,'live','normal','arm-existing')['request_sha256'],request_sha)

        def test_short_command_enters_once_only_after_full_echo_without_sha_or_shell(self):
            from PIL import Image
            for failure in (None,'fallback','echo','request'):
                with tempfile.TemporaryDirectory(prefix='cv-short-reset-unit-') as temporary:
                    image=Path(temporary)/'public-unit.png';Image.new('RGB',(1280,800)).save(image)
                    screen=(image,[],'');report=self.transport_report()
                    value=reset_request(report,'live','normal','a'*32,'arm-existing')
                    report['reset_requests']={'live-normal-arm':{'value':value,'sha256':'7'*64}}
                    if failure=='request':report['reset_requests']['live-normal-arm']['value']=dict(value,nonce='b'*32)
                    commands=[];keys=[];state={'echo':''};clock=[0];events=[]
                    def typing(text):
                        events.append('text');commands.append(text)
                        state['echo']='ython3' if failure=='echo' else text.replace('normal','normat') if failure=='fallback' else text
                    def call(unused,**kw):
                        events.append('control-'+str(kw['events'][0]['data']['down']))
                        if kw['events'][0]['data']['key']['data']=='u':state['echo']=''
                    vm=SimpleNamespace(text=typing,key=lambda *key:keys.append(key),call=call)
                    def words(*unused):events.append('fresh-capture');return screen
                    vm.words=words
                    prompt=Mock(side_effect=lambda unused:{'echo':state['echo'],'focus':(202,55)})
                    gui=SimpleNamespace(_home=lambda *a:screen,_click_home_card=lambda *a:None,_terminal_screen=lambda *a,**k:screen,
                        _terminal_prompt=prompt,_point=lambda *a,**k:events.append('park' if k.get('click') is False else 'focus'),
                        normalized=lambda text:re.sub('[^a-z0-9]','',text.lower()))
                    real_load=frozen_module
                    def module(name,sha):return gui if name=='ci-vm-gui-actions.py' else real_load(name,sha)
                    def now():clock[0]+=.5;return clock[0]
                    def alternate(*unused,**kw):
                        return ({'echo':commands[-1],'focus':(202,55)},{'method':'bounded-unit-row'}) if failure=='fallback' else None
                    with patch.dict(globals(),{'frozen_module':module,'reset_row_echo':alternate,
                            'wait_probe_completion':lambda *a:
                            (image,'VAULT_RESET_USBREADY=public VAULT CI RESET NORMAL ARM DONE EXIT 0')}),\
                         patch.object(time,'sleep',lambda value:events.append('sleep-'+str(value))),patch.object(time,'monotonic',now):
                        if failure in ('echo','request'):
                            with self.assertRaises(RuntimeError):reset_guest(vm,report,'live','normal','a'*32,'arm-existing')
                            self.assertNotIn(('ret',),keys)
                        else:
                            record=reset_guest(vm,report,'live','normal','a'*32,'arm-existing')
                            self.assertEqual(keys.count(('ret',)),1);self.assertEqual(record['slot'],'live-normal-arm')
                            self.assertEqual(commands,['python3 /media/vault/VAULT_CI/ci-vm-reset-runner.py live-normal-arm  '])
                            self.assertNotIn(RESET_SHA256,commands[0]);self.assertNotIn('printf',commands[0]);self.assertNotIn('\n',commands[0])
                            self.assertEqual(events[:3],['focus','park','sleep-0.25'])
                            self.assertLess(events.index('control-False'),events.index('fresh-capture'))
                            self.assertLess(events.index('fresh-capture'),events.index('text'))
                            if failure=='fallback':self.assertEqual(record['entry_echo_proof']['method'],'bounded-unit-row')
                    if failure=='request':self.assertEqual(commands,[])

        def test_reset_controls_are_held_and_released_in_order_only_for_readline(self):
            events=[]
            vm=SimpleNamespace(call=lambda name,**kw:events.append((name,kw['events'])))
            with patch.object(time,'sleep',lambda value:events.append(('sleep',value))):reset_control_key(vm,'u')
            key=lambda down,value:{'type':'key','data':{'down':down,'key':{'type':'qcode','data':value}}}
            self.assertEqual(events,[('input-send-event',[key(True,'ctrl'),key(True,'u')]),('sleep',.10),
                ('input-send-event',[key(False,'u'),key(False,'ctrl')]),('sleep',.15)])
            events.clear()
            with self.assertRaises(RuntimeError):reset_control_key(vm,'n')
            self.assertEqual(events,[])

        def test_reset_empty_prompt_retains_fresh_stable_capture_before_typing(self):
            from PIL import Image
            with tempfile.TemporaryDirectory(prefix='cv-reset-entry-unit-') as temporary:
                images=[]
                for name in ('initial','moved','stable'):
                    path=Path(temporary)/(name+'.png');Image.new('RGB',(1280,800)).save(path);images.append(path)
                screens=[(image,[],image.stem) for image in images]
                prompts={'initial':{'echo':'','focus':(202,55)},'moved':{'echo':'','focus':(202,60)},
                         'stable':{'echo':'','focus':(202,60)}}
                gui=SimpleNamespace(_terminal_screen=lambda *a,**k:screens[0],
                    _terminal_prompt=lambda screen:prompts[screen[2]],normalized=lambda value:value.strip())
                vm=SimpleNamespace(words=Mock(side_effect=screens[1:]))
                with patch.object(time,'sleep',lambda *a:None):
                    self.assertIs(reset_empty_prompt(vm,gui,'unit'),screens[2])
                prompts['moved']['echo']='late-public-input'
                vm.words=Mock(return_value=screens[1])
                with patch.object(time,'sleep',lambda *a:None):
                    with self.assertRaisesRegex(RuntimeError,'changed before typing'):reset_empty_prompt(vm,gui,'unit')

        def test_passive_reset_echo_waits_without_retyping_and_never_repairs_partial_input(self):
            command='python3 /media/vault/VAULT_CI/ci-vm-reset-runner.py live-normal-arm'
            gui=SimpleNamespace(_terminal_prompt=lambda screen:screen[2],normalized=lambda value:re.sub('[^a-z0-9]','',value.lower()))
            for valid in (True,False,'mixed-cursor'):
                clock=[0];observations=[]
                echo=command if valid is True else command+' [|' if valid=='mixed-cursor' else 'mal-arm '+command[:-7]
                values=[{'echo':'python3','focus':(202,55)},None,{'echo':echo,'focus':(202,55)}]
                def words(label):
                    index=min(len(observations),len(values)-1);observations.append(label)
                    return Path('/public'),[],values[index]
                vm=SimpleNamespace(words=words,text=lambda *a:self.fail('Retyped during passive echo wait'),
                    key=lambda *a:self.fail('Key sent during passive echo wait'))
                def now():clock[0]+=1;return clock[0]
                with patch.dict(globals(),{'reset_row_echo':lambda *a,**k:None}),\
                     patch.object(time,'sleep',lambda *a:None),patch.object(time,'monotonic',now):
                    _,proof=reset_exact_echo(vm,gui,command,'unit')
                self.assertEqual(proof is not None,valid is True);self.assertGreaterEqual(len(observations),3)

        def test_reset_row_fallback_maps_only_actual_body_row_and_refuses_hidden_continuation(self):
            from PIL import Image,ImageDraw
            gui=frozen_module('ci-vm-gui-actions.py',digest(HERE/'ci-vm-gui-actions.py'))
            command='python3 /media/vault/VAULT_CI/ci-vm-reset-runner.py live-normal-arm'
            for invalid in (None,'partial','overwritten','footer','continuation','duplicate','wrong-title'):
                with tempfile.TemporaryDirectory(prefix='cv-reset-entry-unit-') as temporary:
                    image=Path(temporary)/'raw.png';capture=Image.new('RGB',(1280,800))
                    ImageDraw.Draw(capture).rectangle((1265,40,1279,758),fill=(206,206,206));capture.save(image);image.chmod(0o600)
                    echo='python3' if invalid=='partial' else command
                    original=[('vault@core-vault:~$',0,46,190,18),('python3',202,46,68,18)]
                    if invalid=='overwritten':original[0]=('mal-arm core-vault:~$',0,46,190,18)
                    if invalid=='footer':original=[(text,x,770,w,h) for text,x,y,w,h in original]
                    if invalid=='continuation':original.append(('extra',0,70,40,18))
                    if invalid=='duplicate':original.append(('vault@core-vault:~$',0,100,190,18))
                    tsv='level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n'
                    tsv+='5\t1\t1\t1\t1\t1\t0\t6\t570\t54\t95\tvault@core-vault:~$\n'
                    tsv+='5\t1\t1\t1\t1\t2\t606\t6\t'+str(len(echo)*30)+'\t54\t95\t'+echo+'\n'
                    calls=[]
                    def ocr(argv,**kwargs):
                        calls.append((argv,kwargs))
                        return SimpleNamespace(stdout=tsv if argv[-1]=='tsv' else
                            'Files - vault@core-vault: ~' if invalid=='wrong-title' else 'Terminal - vault@core-vault: ~')
                    before=digest(image)
                    with patch.dict(globals(),{'run':ocr}):
                        if invalid=='duplicate':
                            with self.assertRaisesRegex(RuntimeError,'ambiguous'):reset_row_echo((image,original,''),gui)
                            self.assertEqual(calls,[]);continue
                        result=reset_row_echo((image,original,''),gui)
                    self.assertEqual(digest(image),before)
                    if invalid in ('overwritten','footer','continuation','wrong-title'):
                        self.assertIsNone(result);self.assertEqual(len(calls),1 if invalid=='wrong-title' else 0)
                    else:
                        prompt,proof=result
                        self.assertEqual(prompt['echo'],echo);self.assertEqual(prompt['focus'][1],55)
                        self.assertEqual(proof['crop'],[0,44,1265,76]);self.assertEqual(proof['raw_sha256'],before)
                        self.assertEqual(calls[-1][0][-3:],['--psm','7','tsv'])
                        self.assertNotIn(command,calls[-1][0]);self.assertEqual(proof['scale'],3)
                        self.assertEqual(proof['viewport_right'],1265);self.assertTrue(proof['terminal_title_verified'])

        def test_reset_viewport_rejects_missing_malformed_altered_or_clipped_client(self):
            from PIL import Image,ImageDraw
            for invalid in (None,'no-bar','wide-bar','coloured-bar','altered-bar','client-text','clipped-token','dimensions'):
                capture=Image.new('RGB',(1280,800));draw=ImageDraw.Draw(capture)
                if invalid!='no-bar':draw.rectangle((1250 if invalid=='wide-bar' else 1265,40,1279,758),
                    fill=(206,100,50) if invalid=='coloured-bar' else (206,206,206))
                if invalid=='altered-bar':capture.putpixel((1270,400),(0,0,0))
                if invalid=='client-text':capture.putpixel((1264,50),(255,255,255))
                if invalid=='dimensions':capture=capture.resize((1024,768))
                rows=[('public',1248,46,30,18)] if invalid=='clipped-token' else []
                self.assertEqual(reset_viewport_right(capture,rows,44,76),1265 if invalid is None else None)

    suite=unittest.defaultTestLoader.loadTestsFromTestCase(Tests)
    return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1


def main():
    if sys.argv[1:] == ['--scan-self-test']:
        return scan_self_test()
    if sys.argv[1:] == ['--reset-self-test']:
        return reset_self_test()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--iso', required=True, type=Path)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--firmware', required=True, choices=('bios', 'uefi'))
    parser.add_argument('--accel', choices=('tcg', 'kvm'), default='tcg')
    parser.add_argument('--boot-timeout', type=int, default=1200)
    parser.add_argument('--install', action='store_true', help='Install only into the new owned virtual disk, then probe its normal boot.')
    parser.add_argument('--gui', action='store_true', help='Also require native backup/recovery/Finish dialogs and genuine shutdown.')
    parser.add_argument('--scan', action='store_true', help='Require phase-specific offline disk marker scans after genuine Finish; requires --gui.')
    parser.add_argument('--reset', action='store_true', help='Require same-image synthetic clean/abrupt cold boots after genuine Finish and scan; requires --gui --scan.')
    parser.add_argument('--install-timeout', type=int, default=2700)
    args = parser.parse_args()
    require(not args.scan or args.gui, '--scan requires genuine --gui Finish evidence.')
    require(not args.reset or args.gui and args.scan, '--reset requires genuine --gui --scan evidence.')
    if args.reset:
        frozen_module('ci-vm-reset-probe.py', RESET_SHA256)
        reset_runner_helper()
        require(hasattr(os, 'pidfd_open') and hasattr(signal, 'pidfd_send_signal'), 'Reset requires Linux pidfd support.')
    if args.scan:forensic_helper()
    require(os.getuid() != 0, 'Run QEMU evidence as the ordinary test account.')
    require(int(Path('/proc/self/stat').read_text().split('(', 1)[0]) == os.getpid(),
            'The controller requires /proc in its own PID namespace.')
    def interrupted(signum, frame):
        raise KeyboardInterrupt('VM controller interrupted by signal '+str(signum))
    signal.signal(signal.SIGTERM, interrupted)
    require(0 < args.boot_timeout <= 1800 and 0 < args.install_timeout <= 3600, 'Unbounded phase deadline refused.')
    iso, root = plain(args.iso), plain(args.output)
    require(iso.is_file() and re.fullmatch('[0-9a-f]{64}', args.sha256) and digest(iso) == args.sha256, 'Candidate ISO hash mismatch.')
    require(not root.exists(), 'Use a new evidence directory; existing files are never overwritten.')
    os.umask(0o077)  # Every private screenshot and QA record belongs to this account.
    root.mkdir(parents=True, mode=0o700);root.chmod(0o700)
    for program in ('qemu-system-x86_64', 'qemu-img', 'mformat', 'mcopy', 'tesseract'):
        require(shutil.which(program), 'Missing test dependency: '+program)
    probe = HERE/'ci-vm-guest-probe.py'
    require(probe.is_file(), 'The synthetic guest probe is missing.')
    psbt_helper = HERE/'ci-vm-psbt.py'
    require(psbt_helper.is_file() and not psbt_helper.is_symlink(), 'The synthetic PSBT helper is missing.')
    gui_helper = HERE/'ci-vm-gui-actions.py'
    require(not args.gui or (gui_helper.is_file() and not gui_helper.is_symlink()), 'The native GUI helper is missing.')
    disk, usb = root/'target.qcow2', root/'fixture.raw'
    run(['qemu-img', 'create', '-f', 'qcow2', str(disk), '24G'])
    with usb.open('xb') as stream:stream.truncate(512*1024*1024)
    usb.chmod(0o600);disk.chmod(0o600)
    run(['mformat', '-i', str(usb), '-F', '-v', 'VAULT_CI', '::'])
    helper_hashes = {path.name:digest(path) for path in (probe,psbt_helper)}
    reset_helper = HERE/'ci-vm-reset-probe.py'
    runner_helper = HERE/'ci-vm-reset-runner.py'
    helpers = [probe,psbt_helper] + ([gui_helper] if args.gui else []) + ([reset_helper,runner_helper] if args.reset else [])
    delivery = root/'fixture-delivery';delivery.mkdir(mode=0o700)
    for helper in helpers:
        run(['mcopy', '-i', str(usb), str(helper), '::'+helper.name])
        # The ordinary file-backed FAT image is closed/not running here.
        # Attest exact copied helper bytes before any guest process can read it.
        copied = delivery/helper.name
        run(['mcopy', '-i', str(usb), '::'+helper.name, str(copied)])
        require(digest(copied)==digest(helper), 'USB helper copy digest mismatch: '+helper.name)
    helper_manifest = delivery/'ci-helper-sha256.json'
    helper_manifest.write_text(json.dumps({'schema':1,'helpers':helper_hashes},indent=2)+'\n')
    run(['mcopy', '-i', str(usb), str(helper_manifest), '::ci-helper-sha256.json'])
    if args.reset:
        require(digest(reset_helper) == RESET_SHA256 and digest(probe) == RESET_PROBE_SHA256
                and digest(runner_helper) == RESET_RUNNER_SHA256, 'Reset sources changed during USB delivery.')
        reset_manifest = delivery/'ci-reset-helper-sha256.json'
        reset_manifest.write_text(json.dumps({'schema':1,'helpers':{reset_helper.name:RESET_SHA256,
                                                                 runner_helper.name:RESET_RUNNER_SHA256}},indent=2)+'\n')
        run(['mcopy', '-i', str(usb), str(reset_manifest), '::ci-reset-helper-sha256.json'])
    variables = None
    if args.firmware == 'uefi':
        code, original = Path('/usr/share/OVMF/OVMF_CODE_4M.fd'), Path('/usr/share/OVMF/OVMF_VARS_4M.fd')
        require(code.is_file() and original.is_file(), 'OVMF 4M firmware is missing.')
        variables = root/'vars.fd';shutil.copyfile(original, variables);variables.chmod(0o600)
    report = {'schema': 2, 'status': 'running', 'firmware': args.firmware, 'accelerator': args.accel,
        'iso_sha256': args.sha256, 'iso_bytes': iso.stat().st_size,
        'harness_sha256': digest(Path(__file__).resolve()), 'guest_probe_sha256': digest(probe),
        'helper_sha256': helper_hashes,
        'kernel_debug_options_added': False, 'guest_network_devices': False,
        'installation': 'pending', 'installed_boot_and_runtime_probe': 'pending',
        'genuine_backup_dialogs': 'pending', 'genuine_finish_dialogs_and_session_destruction': 'pending',
        'genuine_core_wallet_creation': 'pending',
        'candidate_psbt_signing': 'pending', 'cold_reset_and_disk_scan': 'pending', 'cold_reset_checks': 'pending', 'stages': {},
        'scope': 'Normal firmware/GUI boot, optional genuine Calamares installation and synthetic production-runtime probes; uncovered acceptance remains pending.'}
    if args.gui:report['gui_helper_sha256'] = digest(gui_helper)
    if args.scan:report['forensic_helper_sha256'] = FORENSIC_SHA256
    if args.reset:
        report['reset_helper_sha256'] = RESET_SHA256;report['reset_runner_sha256'] = RESET_RUNNER_SHA256
        args.reset_nonces = {phase:{case:uuid.uuid4().hex for case in ('normal','abrupt')}
                            for phase in (('live','installed') if args.install else ('live',))}
        for phase,cases in args.reset_nonces.items():
            for case,nonce in cases.items():
                deliver_reset_request(args,root,usb,report,phase,case,nonce,
                                      'arm-existing' if case == 'normal' else 'arm-fresh',initial=True)
    args.reset_files = ResetFiles(root, disk, usb, iso, variables) if args.reset else None
    try:
        run_requested_phases(args, root, disk, usb, iso, variables, report)
    except BaseException as error:
        report['status'] = 'failed';report['error'] = str(error) or type(error).__name__
        raise
    finally:
        try:(root/'vm-result.json').write_text(json.dumps(report, indent=2)+'\n')
        finally:
            if args.reset_files:args.reset_files.close()
    print(json.dumps({'status': report['status'], 'firmware': args.firmware, 'evidence': str(root),
                      'pending': [k for k,v in report.items() if v == 'pending']}, indent=2))


if __name__ == '__main__':raise SystemExit(main())
