#!/usr/bin/python3
"""Genuine backup/recovery/Finish dialogs in an owned disposable QEMU guest.

The controller copies this file and ci-vm-guest-probe.py onto its own VAULT_CI
USB before starting QEMU. Host run_gui_checks uses only that controller's QMP
input/screen methods. --guest-check runs from the normal Vault Terminal, UID1000,
and verifies only public synthetic fixture data. It never overlays production
code, mounts a device, powers off the host or reads an active host FAT image.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import shlex
import time

HERE = Path(__file__).resolve().parent
PUBLIC = runpy.run_path(str(HERE / 'ci-vm-guest-probe.py'), run_name='ci_gui_public_constants')
EXPORT_PHRASES = PUBLIC['EXPORT_PHRASES']
WRONG_PHRASE = 'Different synthetic disposable VM phrase!'
RECOVERED_PREFIX = 'ci-gui-recovered-'


def require(condition, label):
    if not condition:
        raise RuntimeError(label)


def normalized(value):
    return re.sub(r'[^a-z0-9]', '', value.lower())


def _screen(vm, label, phrases, timeout=90):
    def matches(value):
        value = normalized(value)
        return all(normalized(phrase) in value for phrase in phrases)
    if not label.startswith(('core-', 'finish-')):
        return vm.wait_screen(label, matches, timeout)
    # Stock Core menus can be too small for default full-frame OCR. Enlarge
    # the captured pixels, preserve the original, and map observed boxes back.
    # This changes recognition only; all expected phrases remain mandatory.
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        screen = vm.words(label)
        if matches(screen[2]):
            return screen
        scaled = _core_scaled_screen(screen)
        if matches(scaled[2]):
            return scaled
        time.sleep(2)
    raise RuntimeError('Guest screen deadline exceeded: ' + label)


def _core_scaled_screen(screen):
    import subprocess
    from PIL import Image
    image, _, _ = screen
    derived = image.with_name(image.stem + '-core-3x-ocr.png')
    with Image.open(image) as capture:
        require(0 < capture.width <= 4096 and 0 < capture.height <= 2160,
                'Core OCR screenshot dimensions are unsupported.')
        capture.resize((capture.width * 3, capture.height * 3),
                       Image.Resampling.LANCZOS).save(derived)
    result = subprocess.run(['tesseract', str(derived), 'stdout', '-l', 'eng', 'tsv'],
                            capture_output=True, text=True, timeout=15, check=True)
    rows = []
    for line in result.stdout.splitlines()[1:]:
        fields = line.split('\t')
        if len(fields) == 12 and fields[11].strip():
            rows.append((fields[11], *(int(fields[index]) / 3 for index in (6, 7, 8, 9))))
    derived.with_suffix('.json').write_text(json.dumps({
        'raw_screenshot': image.name, 'raw_sha256': hashlib.sha256(image.read_bytes()).hexdigest(),
        'method': 'full-frame-Lanczos-3x-TSV', 'scale': 3,
        'coordinates': 'mapped-to-original-screenshot'}) + '\n')
    return image, rows, ' '.join(row[0] for row in rows)


def _point(vm, image, x, y, *, button='left', click=True, settle_click=False):
    from PIL import Image
    with Image.open(image) as capture:
        width, height = capture.size
    require(0 <= x < width and 0 <= y < height, 'GUI target is outside its captured guest screen.')
    vm.call('input-send-event', events=[{'type':'abs','data':{'axis':axis,
        'value':round(value*32767/(size-1))}} for axis,value,size in
        (('x',x,width), ('y',y,height))])
    if click:
        vm.call('input-send-event', events=[{'type':'btn','data':{'button':button,'down':True}}])
        if settle_click:time.sleep(.10)
        vm.call('input-send-event', events=[{'type':'btn','data':{'button':button,'down':False}}])
        # A QMP response acknowledges injection, while the guest tablet still
        # needs to consume release before a subsequent pointer-only movement.
        if settle_click:time.sleep(.25)


def _phrase_boxes(rows, phrase):
    tokens = [normalized(part) for part in phrase.split() if normalized(part)]
    rows = [row for row in rows if normalized(row[0])]
    matches = []
    for start in range(len(rows)):
        group = rows[start:start+len(tokens)]
        if len(group) != len(tokens) or [normalized(r[0]) for r in group] != tokens:
            continue
        if max(r[2] for r in group)-min(r[2] for r in group) >= max(r[4] for r in group)+6:
            continue
        left, top = min(r[1] for r in group), min(r[2] for r in group)
        right, bottom = max(r[1]+r[3] for r in group), max(r[2]+r[4] for r in group)
        matches.append((left,top,right-left,bottom-top))
    return matches


def _click_phrase(vm, phrase, screen, *, first=False, largest=False):
    image, rows, _ = screen
    found = _phrase_boxes(rows, phrase)
    require(found, 'Native GUI control was not recognized: '+phrase)
    if first:
        found = [min(found, key=lambda r:r[1])]
    elif largest:
        maximum = max(r[3] for r in found)
        found = [r for r in found if r[3] == maximum]
    require(len(found) == 1, 'Native GUI control is ambiguous: '+phrase)
    x,y,w,h = found[0]
    _point(vm,image,x+w/2,y+h/2)


def _result_public_filename(image, rows, filename):
    """Recognize an exact public basename; never reinterpret an extension."""
    import subprocess
    from PIL import Image
    # A spaced path may have its leading slash misread (e.g. /home as Jnome)
    # while the exact final basename is a separate correctly recognized token.
    # This selector attests the public basename only; the guest read-back check
    # separately validates the RAM destination, complete bytes and wallet digest.
    primary = [row for row in rows if Path(row[0].rstrip(',.;:')).name == filename]
    require(len(primary) <= 1,'Native ResultDialog has duplicate public basename tokens.')
    if primary:return True
    starts = [row for row in rows if row[0].startswith('/')]
    if not starts:return False
    require(len(starts) == 1,'Native ResultDialog has ambiguous public path rows.')
    start = starts[0]
    center = start[2]+start[4]/2
    line = [row for row in rows if row[1] >= start[1] and abs(row[2]+row[4]/2-center) <= 4]
    with Image.open(image) as capture:
        width,height = capture.size
        left,top = min(row[1] for row in line)-4,min(row[2] for row in line)-4
        right,bottom = max(row[1]+row[3] for row in line)+4,max(row[2]+row[4] for row in line)+4
        require(0 <= left < right <= width and 35 < top < bottom < height-130 and bottom-top <= 64,
                'Native public result-path crop is outside its client body.')
        primary = [row for row in line if Path(row[0].rstrip(',.;:')).name == filename]
        require(len(primary) <= 1,'Native ResultDialog has duplicate public basename tokens.')
        if primary:return True
        # Full-frame OCR read the actual .7z as .72. A separately labeled
        # bounded raw-pixel crop must recognize the exact basename; no aliases.
        derived = image.with_name(image.stem+'-public-result-path-4x-psm7.png')
        crop = capture.convert('RGB').crop((left,top,right,bottom))
        crop.resize((crop.width*4,crop.height*4),Image.Resampling.LANCZOS).save(derived)
    derived.with_suffix('.json').write_text(json.dumps({'raw_screenshot':image.name,
        'purpose':'ResultDialog-public-path-row-only','crop':[left,top,right,bottom],
        'match_scope':'exact-basename-only','directory_verified_by_ocr':False,
        'method':'4x-Lanczos-PSM7','scale':4},separators=(',',':'))+'\n')
    result = subprocess.run(['tesseract',str(derived),'stdout','-l','eng','--psm','7'],
                            capture_output=True,text=True,timeout=10,check=True)
    observed = result.stdout.strip()
    return observed.startswith('/') and '\n' not in observed and Path(observed).name == filename


def _result_ok_box(screen, *, heading, body, filename=None):
    """Recognize only the production ResultDialog's observed OK button."""
    import subprocess
    from PIL import Image
    titles = {'Encrypted backup ready':'Encrypted Backup',
              'Backup could not be completed':'Encrypted Backup',
              'File recovered to RAM':'GPG Recovery',
              'GPG recovery could not be completed':'GPG Recovery'}
    if heading not in titles or not body:return None
    image,rows,_ = screen
    with Image.open(image) as capture:
        pixels = capture.convert('RGB');width,height = pixels.size
    caption = 'Bitcoin Core Vault '+titles[heading]
    title_boxes = [box for box in _phrase_boxes(rows,caption) if 0 <= box[1] < 35]
    headings = [box for box in _phrase_boxes(rows,heading)
                if 35 <= box[1] and box[1]+box[3] < height-150 and box[3] >= 16]
    if not title_boxes or not headings:return None
    require(len(title_boxes) == len(headings) == 1,'Native ResultDialog title or heading is ambiguous.')
    client_rows = [row for row in rows if headings[0][1]+headings[0][3] < row[2] and
                   row[2]+row[4] < height-130]
    if not all(_phrase_boxes(client_rows,phrase) for phrase in body):return None
    if filename is not None and not _result_public_filename(image,client_rows,filename):return None
    # message_dialog.py fixes these normal/hover button fills. Restrict to the
    # lower client, outside its top icon and the 40px taskbar. Its white glyph
    # can split off a tiny blue island; filter button size before uniqueness.
    colours = ((33,105,168),(40,124,190))
    remaining = {(x,y) for y in range(max(0,height-130),height-45) for x in range(width)
                 if any(all(abs(a-b) <= 3 for a,b in zip(pixels.getpixel((x,y)),colour))
                        for colour in colours)}
    buttons = []
    while remaining:
        pending = [remaining.pop()];component = set(pending)
        while pending:
            x,y = pending.pop()
            for adjacent in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
                if adjacent in remaining:
                    remaining.remove(adjacent);component.add(adjacent);pending.append(adjacent)
        xs,ys = zip(*component)
        left,top,right,bottom = min(xs),min(ys),max(xs)+1,max(ys)+1
        if (80 <= right-left <= 260 and 24 <= bottom-top <= 70 and
                len(component) >= (right-left)*(bottom-top)*.8):
            buttons.append((left,top,right,bottom))
    if not buttons:return None
    require(len(buttons) == 1,'Native ResultDialog has ambiguous blue buttons; no acknowledgement will be sent.')
    left,top,right,bottom = buttons[0]
    primary = [box for box in _phrase_boxes(rows,'OK') if left <= box[0] and top <= box[1] and
               box[0]+box[2] <= right and box[1]+box[3] <= bottom]
    require(len(primary) <= 1,'Native ResultDialog has duplicate OK captions.')
    if primary:return primary[0]
    bounds = (left+2,top+2,right-2,bottom-2)
    derived = image.with_name(image.stem+'-result-ok-interior-4x-psm7.png')
    crop = pixels.crop(bounds)
    crop.resize((crop.width*4,crop.height*4),Image.Resampling.LANCZOS).save(derived)
    derived.with_suffix('.json').write_text(json.dumps({'raw_screenshot':image.name,
        'purpose':'source-ResultDialog-OK-only','expected_heading':heading,'expected_body':body,
        'public_filename':filename,'raw_button_bounds':buttons[0],'crop':bounds,
        'method':'4x-Lanczos-PSM7','scale':4},separators=(',',':'))+'\n')
    result = subprocess.run(['tesseract',str(derived),'stdout','-l','eng','--psm','7','tsv'],
                            capture_output=True,text=True,timeout=10,check=True)
    words = []
    for line in result.stdout.splitlines()[1:]:
        fields = line.split('\t')
        if len(fields) == 12 and normalized(fields[11]):
            words.append((fields[11],*(int(fields[index]) for index in (6,7,8,9))))
    if len(words) != 1 or normalized(words[0][0]) != 'ok':return None
    _,x,y,w,h = words[0]
    box = (bounds[0]+x/4,bounds[1]+y/4,w/4,h/4)
    require(left <= box[0] and top <= box[1] and box[0]+box[2] <= right and box[1]+box[3] <= bottom,
            'Recognized ResultDialog OK caption lies outside its observed button.')
    return box


def _click_result_ok(vm, screen, *, heading, body, filename=None):
    box = _result_ok_box(screen,heading=heading,body=body,filename=filename)
    require(box is not None,'Production ResultDialog OK was not uniquely recognized; no acknowledgement was sent.')
    x,y,w,h = box
    _point(vm,screen[0],x+w/2,y+h/2)



def _click_home_card(vm, title, screen):
    from PIL import Image
    image, rows, _ = screen
    with Image.open(image) as capture:
        width,height = capture.size
    headers = _phrase_boxes(rows,'Bitcoin Core Vault')
    require(len(headers) == 1, 'Native Home heading was not uniquely recognized.')
    header_bottom = headers[0][1]+headers[0][3]
    # Home's subtitle immediately follows its heading. Its word "files" can
    # have the same OCR glyph height as the Files card; exclude that band.
    found = [box for box in _phrase_boxes(rows,title) if box[1] > header_bottom+60 and
             box[0] >= 0 and box[0]+box[2] <= width and box[1]+box[3] < height-50]
    require(found, 'Native Home card was not recognized: '+title)
    # Card titles are larger than their description copy. The Home heading is
    # explicitly excluded, including its Bitcoin Core prefix.
    largest = max(box[3] for box in found)
    found = [box for box in found if box[3] == largest]
    require(len(found) == 1, 'Native Home card is ambiguous: '+title)
    x,y,w,h = found[0]
    _point(vm,image,x+w/2,y+h/2)


def _home_recognized(screen):
    """Recognize the source's centered heading and two rows of native cards.

    One uncertain card spelling must not make a fully visible Home unrecognizable.
    This is still geometry-bound; a Terminal prompt or printed list is insufficient.
    """
    from PIL import Image
    image,rows,_ = screen
    with Image.open(image) as capture:
        width,height = capture.size
    headings = _phrase_boxes(rows,'Bitcoin Core Vault')
    if len(headings) != 1:
        return False
    x,y,w,h = headings[0]
    if h < 16 or w < 180 or abs(x+w/2-width/2) > width*.15:
        return False
    bands = []
    for titles in (('Bitcoin Core','KeePassXC','Arqiver','Brasero','Print & Labels'),
                   ('Files','Editor','Terminal','Wallet Backup','Vault Guide')):
        centers = []
        for title in titles:
            found = [box for box in _phrase_boxes(rows,title) if box[1] > y+h+60
                     and box[0] >= 0 and box[0]+box[2] <= width and box[1]+box[3] < height-50]
            if not found:
                continue
            largest = max(box[3] for box in found)
            found = [box for box in found if box[3] == largest]
            if len(found) == 1:
                left,top,bw,bh = found[0]
                centers.append((left+bw/2,top+bh/2))
        if len(centers) < 3 or max(cy for _,cy in centers)-min(cy for _,cy in centers) > 30:
            return False
        ordered = sorted(cx for cx,_ in centers)
        if min(b-a for a,b in zip(ordered,ordered[1:])) < 70:
            return False
        bands.append(centers)
    return min(cy for _,cy in bands[1])-max(cy for _,cy in bands[0]) >= 80


def _edit_below(vm, label, screen, value):
    image, rows, _ = screen
    found = _phrase_boxes(rows,label)
    require(len(found) == 1, 'Native input label is missing or ambiguous: '+label)
    x,y,w,h = found[0]
    # Qt's observed layout is label, ten-pixel spacing, then a 44-pixel edit.
    # The containing dialog and every label are verified before this target.
    _point(vm,image,x+100,y+h+32,settle_click=True)
    vm.key('ctrl','a')
    vm.text(value)


def _home(vm, label='gui-home'):
    image, rows, text = vm.words(label+'-before')
    if _home_recognized((image,rows,text)):
        return image,rows,text
    from PIL import Image
    with Image.open(image) as capture:
        height = capture.height
    # Verified Vault taskbar Home control is a full 40x40 slot at the far left.
    _point(vm,image,20,height-20,settle_click=True)
    _point(vm,image,5,5,click=False)
    until = time.monotonic()+60
    cleared_hint = False
    while time.monotonic() < until:
        screen = vm.words(label)
        if _home_recognized(screen):
            return screen
        # A delayed custom card hint can cover the Home heading after a modal
        # closes. Use its native empty-background click handler; keep the complete
        # heading/card recognition mandatory.
        if not cleared_hint:
            cards = [box for box in _phrase_boxes(screen[1],'Wallet Backup')
                     if height / 3 < box[1] < height - 140 and box[3] >= 12]
            if len(cards) == 1:
                x,y,w,h = cards[0]
                # The source Home background-click handler unconditionally
                # hides the custom hint; leaveEvent only hides its own card.
                # This upper corner is outside the observed card and taskbar.
                with Image.open(screen[0]) as capture:
                    corner = capture.convert('RGB').crop((25,0,40,12))
                    require(all(max(pixel) <= 20 for pixel in corner.getdata()),
                            'Home hint dismissal corner is not empty background.')
                _point(vm,screen[0],32,5,settle_click=True)
                cleared_hint = True
        time.sleep(2)
    raise RuntimeError('Native Home heading and card geometry were not recognized: '+label)



def _terminal_prompt(screen):
    """Read one actual shell prompt in the client body, excluding task tabs."""
    from PIL import Image
    image,rows,_ = screen
    with Image.open(image) as capture:
        width,height = capture.size
        pixels = capture.convert('RGB')
    def cursor_only(row):
        _,left,top,w,h = row
        if not (0 < w <= 20 and 10 <= h <= 32 and 0 <= left < width-w and 40 <= top < height-h):
            return False
        crop = pixels.crop((left,top,left+w,top+h))
        # VTE's solid white block cursor is sometimes OCR'd as "ff". Ignore
        # only that uniformly filled captured rectangle, never text glyphs.
        return sum(min(pixel) >= 230 for pixel in crop.getdata()) >= w*h*.95
    lines = []
    for row in sorted((row for row in rows if 40 <= row[2] and row[2]+row[4] < height-70 and not cursor_only(row)),
                      key=lambda row:(row[2]+row[4]/2,row[1])):
        center = row[2]+row[4]/2
        line = next((line for line in lines if abs(center-line['center']) <= 4),None)
        if line is None:
            line = {'center':center,'rows':[]};lines.append(line)
        line['rows'].append(row)
    lines.sort(key=lambda line:line['center'])
    candidates = []
    for index,line in enumerate(lines):
        line['rows'].sort(key=lambda row:row[1])
        value = ' '.join(row[0] for row in line['rows'])
        match = re.match(r'^vault\s*@\s*core-vault\s*:\s*[^$]{0,160}\$\s*(.*)$',value,re.I)
        if match and line['rows'][0][1] < width*.1:
            candidates.append((index,line,match.group(1)))
    require(len(candidates) <= 1, 'Native Terminal body prompt is ambiguous; no command will be entered.')
    if not candidates:
        return None
    index,line,echo = candidates[0]
    # A long public command may wrap. Only adjacent client-body lines belong
    # to its visible echo; no other prompt or output is accepted as readiness.
    previous = line['center']
    for following in lines[index+1:index+4]:
        if following['center']-previous > 30:
            break
        echo += ' '+' '.join(row[0] for row in following['rows'])
        previous = following['center']
    first = line['rows'][0]
    prompt_right = first[1]+first[3]
    for row in line['rows']:
        if '$' in row[0]:
            prompt_right = row[1]+row[3];break
    return {'echo':echo,'focus':(min(width-20,prompt_right+12),line['center'])}


def _terminal_client_prompt_ocr(screen):
    """Re-read an absent prompt from the observed native Terminal client.

    Full-frame OCR omitted the genuinely empty prompt after one font zoom in
    the actual BIOS capture. This separately labeled crop retains the exact
    prompt parser and its raw-pixel caret guard; it never repairs OCR words.
    """
    import subprocess
    from PIL import Image
    image,rows,_ = screen
    # A recognized nonempty or ambiguous primary prompt must never gain this
    # fallback. In particular, an unexecuted command remains an echo negative.
    if _terminal_prompt(screen) is not None:return None
    with Image.open(image) as capture:
        width,height = capture.size
        require(800 <= width <= 4096 and 400 <= height <= 2160,
                'Native Terminal client OCR capture is outside the tested bounds.')
        title_rows = [row for row in rows if 0 <= row[2] and row[2]+row[4] <= 23
                      and 0 <= row[1] and row[1]+row[3] <= width]
        titles = _phrase_boxes(title_rows,'Terminal')
        require(len(titles) <= 1,'Native Terminal title is ambiguous; no prompt OCR will be used.')
        title = ' '.join(row[0] for row in sorted(title_rows,key=lambda row:row[1]))
        if not titles:return None
        if not re.search(r'\bvault\s*@\s*core-vault\s*:',title):
            # Full-frame OCR can truncate the small native title after font
            # zoom. Re-read its actual pixels without relaxing account checks.
            title_bounds = (titles[0][0],0,width-40,23)
            title_crop = capture.crop(title_bounds)
            title_image = image.with_name(image.stem+'-terminal-title-3x-psm7.png')
            title_crop.resize((title_crop.width*3,title_crop.height*3),Image.Resampling.LANCZOS).save(title_image)
            observed = subprocess.run(['tesseract',str(title_image),'stdout','-l','eng','--psm','7'],
                                      capture_output=True,text=True,timeout=10,check=True).stdout
            title_image.with_suffix('.json').write_text(json.dumps({
                'raw_screenshot':image.name,'raw_sha256':hashlib.sha256(image.read_bytes()).hexdigest(),
                'crop':title_bounds,'scale':3,'method':'native-title-Lanczos-PSM7'})+'\n')
            if not re.search(r'\bTerminal\b',observed) or not re.search(r'\bvault\s*@\s*core-vault\s*:',observed):return None
        # Xfce's captured maximized title/menubar end at y=44. Exclude its
        # right scrollbar and the bottom range already excluded by the parser.
        bounds = (0,44,width-16,height-70)
        require(0 <= bounds[0] < bounds[2] <= width and
                40 <= bounds[1] < bounds[3] < height-40,
                'Native Terminal prompt OCR crop is outside its client body.')
        derived = image.with_name(image.stem+'-terminal-client-prompt-4x-psm6.png')
        crop = capture.convert('RGB').crop(bounds)
        crop.resize((crop.width*4,crop.height*4),Image.Resampling.LANCZOS).save(derived)
    derived.with_suffix('.json').write_text(json.dumps({'raw_screenshot':image.name,
        'purpose':'native-Terminal-public-client-prompt-only','crop':bounds,
        'method':'4x-Lanczos-PSM6','scale':4,'raw_coordinate_mapping':'nearest-pixel-edges',
        'primary_prompt_absent':True},separators=(',',':'))+'\n')
    result = subprocess.run(['tesseract',str(derived),'stdout','-l','eng','--psm','6','tsv'],
                            capture_output=True,text=True,timeout=10,check=True)
    mapped = []
    for line in result.stdout.splitlines()[1:]:
        values = line.split('\t')
        if len(values) != 12 or not values[11].strip():continue
        left,top,w,h = (int(values[index]) for index in (6,7,8,9))
        require(0 <= left < left+w <= crop.width*4 and 0 <= top < top+h <= crop.height*4,
                'Native Terminal prompt OCR row is outside its labeled crop.')
        x,y = bounds[0]+round(left/4),bounds[1]+round(top/4)
        right,bottom = bounds[0]+round((left+w)/4),bounds[1]+round((top+h)/4)
        require(bounds[0] <= x < right <= bounds[2] and bounds[1] <= y < bottom <= bounds[3],
                'Native Terminal prompt OCR mapped row is outside its raw client.')
        mapped.append((values[11],x,y,right-x,bottom-y))
    client = (image,mapped,' '.join(row[0] for row in mapped))
    if _terminal_prompt(client) is None:return None
    # Retain the original chrome/footer observations for callers. Replace only
    # the source-bound client rows with the separately attested OCR rows.
    outside = [row for row in rows if not (bounds[1] <= row[2] and row[2]+row[4] <= bounds[3])]
    combined = sorted(outside+mapped,key=lambda row:(row[2],row[1]))
    return image,combined,' '.join(row[0] for row in combined)


def _terminal_screen(vm, label, *, timeout=60):
    until = time.monotonic()+timeout
    while time.monotonic() < until:
        screen = vm.words(label)
        prompt = _terminal_prompt(screen)
        if prompt is None:
            fallback = _terminal_client_prompt_ocr(screen)
            if fallback is not None:
                screen = fallback
                prompt = _terminal_prompt(screen)
        if prompt is not None and not normalized(prompt['echo']):
            return screen
        time.sleep(.5)
    raise RuntimeError('Native Terminal did not show a unique empty client-body prompt: '+label)


def _shell_failure(text):
    value = normalized(text)
    return any(message in value for message in ('commandnotfound','nosuchfileordirectory',
               'cantopenfile','tracebackmostrecentcalllast'))


def _terminal_wrap_observed(screen):
    """Observe a right-edge command line and adjacent left-edge continuation.

    This only permits one native font zoom before the final pre-execution
    attempt. It never repairs OCR text or accepts a command echo.
    """
    from PIL import Image
    image,rows,_ = screen
    with Image.open(image) as capture:
        width,height = capture.size
    prompt = _terminal_prompt(screen)
    if prompt is None or not prompt['echo'] or width < 800 or height < 400:
        return False
    center = prompt['focus'][1]
    body = [row for row in rows if 0 <= row[1] and row[1]+row[3] <= width and
            40 <= row[2] and row[2]+row[4] < height-70]
    right_edge = any(abs(row[2]+row[4]/2-center) <= 4 and
                     row[1]+row[3] >= width*.95 for row in body)
    continuation = any(4 < row[2]+row[4]/2-center <= 30 and
                       row[1] <= width*.05 for row in body)
    return right_edge and continuation


def _enter_terminal_command(vm, command, screen, *, label):
    """Verify complete public command echo before exactly one Return."""
    public_helper = (r'python3 /media/vault/VAULT_CI/ci-vm-gui-actions\.py --guest-check '
                     r'(?:initial|exports|unchanged|context-intent|context|no-plaintext|recovery|restore|restore-cleanup|session)'
                     r' --phase (?:live|installed) --firmware (?:bios|uefi)')
    require(command == '/usr/local/bin/core-vault-finish' or re.fullmatch(public_helper,command),
            'Terminal entry accepts only fixed public fixture or production Finish commands.')
    require('\n' not in command and '\r' not in command, 'A command must not execute during typing.')
    for attempt in range(2):
        prompt = _terminal_prompt(screen)
        require(prompt is not None, 'Verified Terminal client-body prompt is unavailable.')
        _point(vm,screen[0],*prompt['focus'],settle_click=True)
        from PIL import Image
        with Image.open(screen[0]) as capture:
            width,height = capture.size
        # Keep VTE focused, but park the pointer without clicking away from its
        # prompt/caret pixels. An overlapping mouse I-beam corrupts their OCR.
        _point(vm,screen[0],width/2,height/2,click=False)
        time.sleep(.25)  # The observed VTE client receives focus before Readline input.
        vm.key('ctrl','e');vm.key('ctrl','u')
        _terminal_screen(vm,label+'-cleared-'+str(attempt),timeout=10)
        # Bash ignores trailing separators. Keep the block caret apart from the
        # final word so its pixels cannot be merged into that word by OCR.
        vm.text(command+'  ')  # No newline: a missing character remains unexecuted.
        for observation in range(2):
            screen = vm.words(label+'-command-echo-'+str(attempt)+'-'+str(observation))
            observed = _terminal_prompt(screen)
            if observed is not None and normalized(observed['echo']) == normalized(command):
                vm.key('ret')
                return screen[0].name
            # Small terminal glyphs can merge m into n in full-frame OCR.
            # Re-read actual enlarged pixels; never alias or repair a command.
            # This path checks complete echo only and cannot establish readiness.
            enlarged = _core_scaled_screen(screen)
            observed = _terminal_prompt(enlarged)
            if observed is not None and normalized(observed['echo']) == normalized(command):
                vm.key('ret')
                return screen[0].name
            time.sleep(.4)  # Re-observe a blinking cursor without retyping or executing.
        if attempt == 0 and _terminal_wrap_observed(screen):
            # Xfce Terminal's source-backed Ctrl+- action shrinks its font.
            # The unexecuted command is cleared and the fresh empty prompt
            # verified by the next, final iteration before any retyping.
            vm.key('ctrl','minus')
            time.sleep(.25)
            screen = vm.words(label+'-zoomed-before-final-attempt')
    raise RuntimeError('Complete public command echo was not verified; no Return was sent.')


def _terminal_check(vm, kind, phase, firmware, media, *, timeout=180):
    home = _home(vm,'check-'+kind+'-home')
    _click_home_card(vm,'Terminal',home)
    ready = _terminal_screen(vm,'check-'+kind+'-terminal')
    command = ('python3 '+shlex.quote(media+'/ci-vm-gui-actions.py')+
               ' --guest-check '+kind+' --phase '+phase+' --firmware '+firmware)
    _enter_terminal_command(vm,command,ready,label='check-'+kind)
    marker = 'GUI_CHECK_PASS_'+kind
    screen = vm.wait_screen('check-'+kind+'-result',
        lambda value: normalized(marker) in normalized(value) or
                      'guicheckfail' in normalized(value) or _shell_failure(value), timeout)
    require(not _shell_failure(screen[2]), 'Native Terminal could not execute the public fixture helper: '+kind)
    require(normalized(marker) in normalized(screen[2]), 'Synthetic guest GUI assertion failed: '+kind)
    vm.key('alt','f4')
    return screen[0].name


def _wallet_picker_anchor(screen):
    """Require the painted native heading and instruction inside the client."""
    from PIL import Image
    image,rows,_ = screen
    with Image.open(image) as capture:
        width,height = capture.size
    headings = [box for box in _phrase_boxes(rows,'Select wallet to back up')
                if 20 <= box[1] and box[1]+box[3] < height-90]
    if not headings:
        return None
    require(len(headings) == 1, 'Native wallet-picker heading is ambiguous; no wallet will be selected.')
    heading = headings[0]
    instructions = [box for box in _phrase_boxes(rows,'Select items from the list below')
                    if heading[1]+heading[3] < box[1] and box[1]+box[3] < height-90]
    if not instructions:
        return None
    require(len(instructions) == 1, 'Native wallet-picker instruction is ambiguous; no wallet will be selected.')
    instruction = instructions[0]
    bottom = height-100
    buttons = [box for title in ('Cancel','OK') for box in _phrase_boxes(rows,title)
               if box[1] > instruction[1]+instruction[3]+40 and box[1] < height-50]
    if buttons:bottom = min(box[1] for box in buttons)-12
    return {'width':width,'height':height,'top':instruction[1]+instruction[3]+4,'bottom':bottom}


def _wallet_list_ocr(screen, anchor):
    """Clearly labeled bounded raw-pixel OCR; preserve the original screenshot."""
    import math
    import subprocess
    from PIL import Image
    image,_,_ = screen
    width,top,bottom = anchor['width'],anchor['top'],anchor['bottom']
    require(0 < width <= 4096 and 0 <= top < bottom <= anchor['height'] and bottom-top <= 2160,
            'Native wallet-list OCR crop is out of bounds.')
    derived = image.with_name(image.stem+'-list-ocr-y'+str(top)+'-'+str(bottom)+'-4x-psm6.png')
    with Image.open(image) as capture:
        crop = capture.crop((0,top,width,bottom))
        crop.resize((width*4,(bottom-top)*4),Image.Resampling.LANCZOS).save(derived)
    derived.with_suffix('.json').write_text(json.dumps({'raw_screenshot':image.name,
        'purpose':'synthetic-wallet-list-only','crop':[0,top,width,bottom],
        'method':'4x-Lanczos-PSM6','scale':4},separators=(',',':'))+'\n')
    result = subprocess.run(['tesseract',str(derived),'stdout','-l','eng','--psm','6','tsv'],
                            capture_output=True,text=True,timeout=10,check=True)
    rows = []
    for line in result.stdout.splitlines()[1:]:
        values = line.split('\t')
        if len(values) == 12 and values[11].strip():
            left,y,w,h = (int(values[index]) for index in (6,7,8,9))
            rows.append((values[11],math.floor(left/4),top+math.floor(y/4),math.ceil(w/4),math.ceil(h/4)))
    return rows


def _wallet_rows_ocr(screen, anchor):
    """Read observed synthetic row pixels at 2x; keep exact format matching."""
    import math
    import subprocess
    from PIL import Image
    image,rows,_ = screen
    candidates = [row for row in rows if normalized('cv-forensic-ci-') in normalized(row[0])
                  and 0 <= row[1] and row[1]+row[3] <= anchor['width']
                  and anchor['top'] <= row[2] and row[2]+row[4] < anchor['bottom']]
    observed=[]
    with Image.open(image) as capture:
        for index,(_,x,y,w,h) in enumerate(candidates):
            bounds=(max(0,math.floor(x)-3),max(anchor['top'],math.floor(y)-4),
                    min(anchor['width'],math.ceil(x+w)+3),min(anchor['bottom'],math.ceil(y+h)+4))
            crop=capture.crop(bounds)
            derived=image.with_name(image.stem+'-observed-wallet-row-'+str(index)+'-2x.png')
            crop.resize((crop.width*2,crop.height*2),Image.Resampling.LANCZOS).save(derived)
            result=subprocess.run(['tesseract',str(derived),'stdout','-l','eng','--psm','7','tsv'],
                                  capture_output=True,text=True,timeout=10,check=True)
            for line in result.stdout.splitlines()[1:]:
                fields=line.split('\t')
                if len(fields)==12 and fields[11].strip():
                    left,top,width,height=(int(fields[i])/2 for i in (6,7,8,9))
                    observed.append((fields[11],bounds[0]+left,bounds[1]+top,width,height))
            derived.with_suffix('.json').write_text(json.dumps({'raw_screenshot':image.name,
                'raw_sha256':hashlib.sha256(image.read_bytes()).hexdigest(),'crop':bounds,
                'scale':2,'method':'observed-wallet-row-Lanczos-PSM7'})+'\n')
    return observed


def _wallet_picker_row(screen, backup_format, *, ocr_fallback=False):
    """One exact row below verified painted anchors; never use a task tab."""
    anchor = _wallet_picker_anchor(screen)
    if anchor is None:
        return None
    prefix = normalized('cv-forensic-ci-'+backup_format+'-')
    def matching(rows):
        return [row for row in rows if prefix in normalized(row[0]) and
                0 <= row[1] and row[1]+row[3] <= anchor['width'] and
                anchor['top'] <= row[2] and row[2]+row[4] < anchor['bottom']]
    found = matching(screen[1])
    require(len(found) <= 1, 'Synthetic wallet row was not uniquely recognized: '+backup_format)
    if not found and ocr_fallback:
        found = matching(_wallet_list_ocr(screen,anchor))
        if not found:found = matching(_wallet_rows_ocr(screen,anchor))
    if not found:
        return None
    require(len(found) == 1, 'Synthetic wallet row was not uniquely recognized: '+backup_format)
    return found[0][1:]


def _select_wallet(vm, backup_format, phase):
    home = _home(vm,'backup-'+backup_format+'-home')
    _click_home_card(vm,'Wallet Backup',home)
    until = time.monotonic()+60
    while time.monotonic() < until:
        screen = vm.words('backup-'+backup_format+'-wallet-list')
        row = _wallet_picker_row(screen,backup_format,ocr_fallback=True)
        if row is not None:
            break
        time.sleep(.5)
    else:
        raise RuntimeError('Native wallet picker did not paint its body heading, instruction and unique target row: '+backup_format)
    image,_,_ = screen
    from PIL import Image
    anchor = _wallet_picker_anchor(screen)
    with Image.open(image) as capture:
        park_x,park_y = capture.width/2,capture.height/2
        require(anchor is not None and anchor['top']+20 < park_y < anchor['bottom']-20,
                'Wallet picker has no observed center inside its client list.')
        patch = capture.convert('RGB').crop((int(park_x)-8,int(park_y)-8,int(park_x)+8,int(park_y)+8))
        require(all(min(patch.getpixel((px,py))) >= 245 for py in range(patch.height) for px in range(patch.width)),
                'Wallet-picker pointer parking is not visibly blank; no selection was sent.')
    x,y,w,h = row
    _point(vm,image,x+w/2,y+h/2,settle_click=True)
    # A short row box can put the pointer over a label when the next dialog
    # maps (actual "as" became "4s"). Park without a second click, only after
    # the selected-row click has released and before its one Return.
    _point(vm,image,park_x,park_y,click=False)
    vm.key('ret')
    return _screen(vm,'backup-'+backup_format+'-request',
                   ('Protect your backup','Backup format','Save backup as','New passphrase','Confirm passphrase'),60)


def _fill_backup_request(vm, screen, backup_format, destination, phrase, *, label):
    require(backup_format in ('gpg','7z'),'Unknown native backup format.')
    if backup_format == 'gpg':
        _click_phrase(vm,'GPG Encrypted File',screen,first=True)
    # Every caller opens a fresh PassphraseDialog, whose source checks 7z by
    # default. Attest its selected note instead of clicking a redundant label
    # that OCR can merge to "7zArchive". Unexpected GPG state is a failure.
    elif _backup_format_selected(screen,'gpg'):
        raise RuntimeError('Fresh 7z request unexpectedly has GPG selected; no backup input was sent.')
    until = time.monotonic()+30
    while time.monotonic() < until:
        screen = vm.words(label+'-format')
        if backup_format == '7z' and _backup_format_selected(screen,'gpg'):
            raise RuntimeError('Fresh 7z request unexpectedly has GPG selected; no backup input was sent.')
        if _backup_format_selected(screen,backup_format):break
        time.sleep(.5)
    else:raise RuntimeError('Native backup dialog did not show its selected format note: '+backup_format)
    screen = _replace_public_destination(vm,screen,destination,label=label)
    _edit_below(vm,'New passphrase',screen,phrase)
    vm.key('ret')
    vm.text(phrase)
    return vm.words(label+'-filled')


def _backup_format_selected(screen, backup_format):
    """The source changes this note only after the corresponding radio toggles."""
    image,rows,_ = screen
    from PIL import Image
    with Image.open(image) as capture:height = capture.height
    heading = _phrase_boxes(rows,'Protect your backup')
    labels = [_phrase_boxes(rows,text) for text in ('Save backup as','New passphrase','Confirm passphrase')]
    if len(heading) != 1 or any(len(boxes) != 1 for boxes in labels):return False
    save,new,confirm = (boxes[0] for boxes in labels)
    if not (20 <= heading[0][1] < save[1] < new[1] < confirm[1] < height-90):return False
    caption = 'Encrypt one file using GPG' if backup_format == 'gpg' else 'Supports files and folders'
    notes = [box for box in _phrase_boxes(rows,caption)
             if heading[0][1]+heading[0][3] < box[1] and box[1]+box[3] < save[1]]
    require(len(notes) <= 1, 'Native selected-format note is ambiguous.')
    return len(notes) == 1


def _destination_region(screen):
    """Bound only the public QLineEdit between its labels and Choose button."""
    from PIL import Image
    image,rows,_ = screen
    with Image.open(image) as capture:width,height = capture.size
    labels = [_phrase_boxes(rows,text) for text in ('Save backup as','New passphrase','Choose')]
    require(all(len(boxes) == 1 for boxes in labels),'Native public destination anchors are missing or ambiguous.')
    save,new,choose = (boxes[0] for boxes in labels)
    # Source: 10px label spacing, 44px edit, 10px text padding; the Choose
    # button is adjacent. Exclude edit borders, that button and secret fields.
    left,top,right,bottom = save[0]+12,save[1]+save[3]+14,choose[0]-48,save[1]+save[3]+50
    require(0 <= left < right < width and 0 <= top < bottom < new[1] < height-90 and
            top < choose[1]+choose[3]/2 < bottom and right-left > 300,
            'Native public destination viewport is out of bounds.')
    return {'bounds':(left,top,right,bottom),'size':(width,height),'save':save,'new':new}


def _destination_crop(screen, region):
    from PIL import Image
    image,rows,_ = screen
    require(_phrase_boxes(rows,'Save backup as') == [region['save']] and
            _phrase_boxes(rows,'New passphrase') == [region['new']],
            'Native public destination labels changed before verification.')
    with Image.open(image) as capture:
        require(capture.size == region['size'],'Native public destination capture dimensions changed.')
        return capture.convert('RGB').crop(region['bounds'])


def _destination_empty(screen, region):
    """Raw pixels prove cleared public text; only a narrow white caret remains."""
    crop = _destination_crop(screen,region)
    pixels = crop.load()
    background = sum(all(abs(channel-32) <= 6 for channel in pixels[x,y])
                     for y in range(crop.height) for x in range(crop.width))
    if background < crop.width*crop.height*.98:return False
    ink = [(x,y) for y in range(crop.height) for x in range(crop.width)
           if max(pixels[x,y]) > 80]
    if not ink:return True
    xs,ys = zip(*ink)
    return (max(xs)-min(xs) < 3 and max(xs) < 5 and max(ys)-min(ys) < 28 and
            all(min(pixels[x,y]) >= 230 for x,y in ink))


def _destination_observed_dim_caret(screen, region):
    """Recognize the recorded QA caret solely to allow one focus change.

    This is not an empty-text proof: that still requires the unchanged pixel
    guard after defocusing. No visible glyph is discarded or repaired.
    """
    crop = _destination_crop(screen,region)
    pixels = crop.load()
    background = sum(all(abs(channel-32) <= 6 for channel in pixels[x,y])
                     for y in range(crop.height) for x in range(crop.width))
    if background < crop.width*crop.height*.98:return False
    ink = {(x,y,pixels[x,y]) for y in range(crop.height) for x in range(crop.width)
           if max(pixels[x,y]) > 80}
    return ink == {(0,y,(223,223,223)) for y in range(11,26)}


def _destination_ocr(screen, region):
    """Labeled OCR of public path pixels only, never either passphrase edit."""
    import subprocess
    from PIL import Image
    image,_,_ = screen
    crop = _destination_crop(screen,region)
    derived = image.with_name(image.stem+'-public-destination-4x-psm7.png')
    crop.resize((crop.width*4,crop.height*4),Image.Resampling.LANCZOS).save(derived)
    derived.with_suffix('.json').write_text(json.dumps({'raw_screenshot':image.name,
        'purpose':'public-destination-only','crop':region['bounds'],
        'method':'4x-Lanczos-PSM7','scale':4},separators=(',',':'))+'\n')
    result = subprocess.run(['tesseract',str(derived),'stdout','-l','eng','--psm','7'],
                            capture_output=True,text=True,timeout=10,check=True)
    return result.stdout.strip()


def _destination_visual_exact(screen, region, destination):
    """Exact public path, with one measured DejaVu uppercase-I recognition.

    The production dialog fixes DejaVu Sans 10. Its capital I is a short
    straight stem aligned with the other capitals; lowercase l is taller.
    OCR commonly calls that capital I "l". No text is rewritten or supplied
    to OCR, and any other path/value mismatch remains a rejection.
    """
    observed = _destination_ocr(screen,region)
    if observed == destination:return True
    if observed != destination.replace('/VAULT_CI/','/VAULT_Cl/'):return False
    import subprocess
    from PIL import Image
    image,_,_ = screen
    derived = image.with_name(image.stem+'-public-destination-4x-psm7.png')
    result = subprocess.run(['tesseract',str(derived),'stdout','-l','eng','--psm','7','makebox'],
                            capture_output=True,text=True,timeout=10,check=True)
    boxes = []
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) != 6 or len(fields[0]) != 1:return False
        boxes.append((fields[0],*(int(value) for value in fields[1:5])))
    characters = ''.join(box[0] for box in boxes)
    if characters != observed:return False
    offset = characters.find('VAULT_Cl/')
    if offset < 0:return False
    with Image.open(derived) as capture:
        pixels = capture.convert('RGB')
        def ink(box):
            _,left,low,right,high = box
            if not (0 <= left < right <= pixels.width and 0 <= low < high <= pixels.height):return set()
            return {(x,y) for y in range(pixels.height-high,pixels.height-low) for x in range(left,right)
                    if min(pixels.getpixel((x,y))) >= 160}
        references = [ink(boxes[offset+index]) for index in (1,2,3,4)]
        if any(not points for points in references):return False
        caps = [(min(y for _,y in points),max(y for _,y in points)) for points in references]
        if max(top for top,_ in caps)-min(top for top,_ in caps) > 2 or \
                max(bottom for _,bottom in caps)-min(bottom for _,bottom in caps) > 2:return False
        # LSTM character boxes may overlap the C or include the I in the
        # following slash box. Inspect that bounded pair, and demand exactly
        # one straight cap-height stem; the C arc and slash cannot qualify.
        letter,slash = boxes[offset+7],boxes[offset+8]
        remaining = ink(('?',min(letter[1],slash[1]),min(letter[2],slash[2]),
                         max(letter[3],slash[3]),max(letter[4],slash[4])))
        components = []
        while remaining:
            pending = [remaining.pop()];component = set(pending)
            while pending:
                x,y = pending.pop()
                for adjacent in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
                    if adjacent in remaining:
                        remaining.remove(adjacent);component.add(adjacent);pending.append(adjacent)
            components.append(component)
        if not components:return False
        stems = []
        for points in components:
            xs,ys = zip(*points)
            left,top,right,bottom = min(xs),min(ys),max(xs),max(ys)
            if (right-left+1 <= 8 and bottom-top+1 >= 28 and
                min(value[0] for value in caps)-2 <= top <= max(value[0] for value in caps)+2 and
                min(value[1] for value in caps)-2 <= bottom <= max(value[1] for value in caps)+2 and
                len(points) >= (right-left+1)*(bottom-top+1)*.85):
                stems.append((left,top,right,bottom))
        if len(stems) != 1:return False
        left,top,right,bottom = stems[0]
        matched = True
    notice = json.loads(derived.with_suffix('.json').read_text())
    notice['visual_recognition'] = {'scope':'one-public-VAULT_CI-uppercase-I-glyph',
        'font':'production-DejaVu-Sans-10','method':'raw-stem-cap-height-and-shape',
        'derived_stem_bounds':[left,top,right+1,bottom+1],'derived_cap_limits':caps,
        'raw_stem_bounds':[region['bounds'][0]+left/4,region['bounds'][1]+top/4,
                           region['bounds'][0]+(right+1)/4,region['bounds'][1]+(bottom+1)/4],
        'matched':matched,'input_value_substituted':False}
    derived.with_suffix('.json').write_text(json.dumps(notice,separators=(',',':'))+'\n')
    return matched


def _public_edit_key(vm, *keys):
    require(keys in (('ctrl','a'),('backspace',)),'Unexpected key in public destination replacement.')
    for down,values in ((True,keys),(False,reversed(keys))):
        vm.call('input-send-event',events=[{'type':'key','data':{'down':down,
            'key':{'type':'qcode','data':key}}} for key in values])
        time.sleep(.10 if down else .15)


def _replace_public_destination(vm, screen, destination, *, label):
    require(re.fullmatch(r'/media/vault/VAULT_CI/(?:ci-(?:gui|context)-(?:live|installed)\.(?:gpg|7z)'
                         r'|ci-gui-(?:live|installed)-cancel\.gpg)',destination),
            'Destination replacement accepts only fixed public fixture paths.')
    region = _destination_region(screen)
    left,top,right,bottom = region['bounds']
    _point(vm,screen[0],left+88,(top+bottom)/2,settle_click=True)
    width,height = region['size']
    _point(vm,screen[0],width/2,height/2,click=False)
    _public_edit_key(vm,'ctrl','a')
    _public_edit_key(vm,'backspace')
    until = time.monotonic()+10
    while time.monotonic() < until:
        cleared = vm.words(label+'-destination-cleared')
        if _destination_empty(cleared,region):break
        time.sleep(.5)
    else:
        require(_destination_observed_dim_caret(cleared,region),
                'Native public destination was not visibly empty; no replacement was typed.')
        # Source: leaving an empty destination calls normalize_destination,
        # which returns without changing it. Tab focuses Choose; its disabled
        # auto-default behavior never invokes the chooser or creates a backup.
        vm.key('tab')
        until = time.monotonic()+10
        while time.monotonic() < until:
            unfocused = vm.words(label+'-destination-unfocused-empty')
            crop = _destination_crop(unfocused,region)
            if (_destination_empty(unfocused,region) and
                    not any(max(pixel) > 80 for pixel in crop.getdata())):
                break
            time.sleep(.5)
        else:raise RuntimeError('Native public destination did not prove fully empty after defocusing; no replacement was typed.')
        _point(vm,unfocused[0],left+88,(top+bottom)/2,settle_click=True)
        _point(vm,unfocused[0],width/2,height/2,click=False)
    vm.text(destination)  # No Return; the backup is never submitted here.
    vm.key('tab')  # Source editingFinished normalizes the chosen suffix.
    until = time.monotonic()+15
    while time.monotonic() < until:
        screen = vm.words(label+'-destination')
        if _destination_visual_exact(screen,region,destination):return screen
        time.sleep(.5)
    raise RuntimeError('Native backup destination did not show the exact full fixture path; no backup was submitted.')


def _backup_request(vm, backup_format, destination, phrase, phase):
    return _fill_backup_request(vm,_select_wallet(vm,backup_format,phase),
                                backup_format,destination,phrase,label='backup-'+backup_format)


def _file_row(screen, filename):
    """Require one exact filename in the captured file-content viewport."""
    from PIL import Image
    image,rows,_ = screen
    with Image.open(image) as capture:
        height = capture.height
    headers = [box for box in _phrase_boxes(rows,'Name') if 40 <= box[1] < 200]
    require(len(headers) == 1, 'Native file-list Name column was not uniquely recognized.')
    left,top,_,header_height = headers[0]
    found = [row for row in rows if normalized(row[0]) == normalized(filename)
             and row[1] >= left and max(100,top+header_height) <= row[2]
             and row[2]+row[4] <= height-70]
    require(len(found) == 1, 'Native file view did not uniquely show the designated fixture file.')
    return found[0][1:]


def _files_media_location(vm, label, media, *, timeout=60):
    """Verify the fixture path in Thunar's address field, separately from body OCR.

    The stock font paints capital I and lowercase l identically. Permit that
    single observed glyph ambiguity only in the known VAULT_CI fixture label;
    native file actions still require their unique exact fixture filenames.
    """
    from PIL import Image
    import subprocess
    require(media == '/media/vault/VAULT_CI', 'Unexpected disposable fixture mount.')
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        screen = vm.words(label)
        image, rows, text = screen
        if all(normalized(word) in normalized(text) for word in ('File','Edit','View')):
            with Image.open(image) as capture:
                require(capture.size == (1280,800), 'Unexpected Thunar capture geometry.')
                crop = capture.crop((185,50,1230,80)).resize((3135,90),Image.Resampling.LANCZOS)
            derived = image.with_name(image.stem+'-fixture-location-ocr.png')
            crop.save(derived)
            result = subprocess.run(['tesseract',str(derived),'stdout','-l','eng','--psm','7'],
                                    check=True,capture_output=True,text=True)
            observed = result.stdout.strip().rstrip('/')
            if observed in (media, '/media/vault/VAULT_Cl'):
                image.with_name(image.stem+'-fixture-location-proof.json').write_text(json.dumps({
                    'raw_screenshot':image.name,'derived_screenshot':derived.name,
                    'expected_path':media,'observed_path':observed,
                    'crop':[185,50,1230,80],'scale':3,
                    'allowed_ambiguity':'Capital I / lowercase l in fixed VAULT_CI label only.'},indent=2)+'\n')
                return screen
        time.sleep(.5)
    raise RuntimeError('Native Thunar fixture address was not verified: '+label)


def _files_list_screen(vm, label, filename, *, timeout=60):
    """Read the actual Name column at legible scale and map its row to the raw UI."""
    from PIL import Image
    import subprocess
    require(re.fullmatch(r'ci-(?:helper-sha256\.json|gui-(?:live|installed)\.gpg)',filename),
            'Unexpected public file selector.')
    until = time.monotonic()+timeout
    while time.monotonic() < until:
        image, rows, text = vm.words(label)
        with Image.open(image) as capture:
            require(capture.size == (1280,800), 'Unexpected Thunar list geometry.')
            crop = capture.crop((175,87,810,729)).resize((1905,1926),Image.Resampling.LANCZOS)
        derived = image.with_name(image.stem+'-name-column-3x.png');crop.save(derived)
        result = subprocess.run(['tesseract',str(derived),'stdout','-l','eng','--psm','6','tsv'],
                                check=True,capture_output=True,text=True)
        mapped=[]
        for line in result.stdout.splitlines()[1:]:
            fields=line.split('\t')
            if len(fields)==12 and fields[11].strip():
                x,y,w,h=map(int,fields[6:10])
                require(0 <= x < 1905 and 0 <= y < 1926 and x+w <= 1905 and y+h <= 1926,
                        'Name column OCR row lies outside its captured crop.')
                mapped.append((fields[11],175+x/3,87+y/3,w/3,h/3))
        # Replace only rows inside this same captured Name column.
        combined=[row for row in rows if not (175 <= row[1] < 810 and 87 <= row[2] < 729)]+mapped
        matches=[row for row in mapped if normalized(row[0])==normalized(filename)]
        require(len(matches)<=1, 'Ambiguous public fixture filename in native list.')
        screen=(image,combined,' '.join(row[0] for row in combined))
        if matches and len(_phrase_boxes(combined,'Name'))==1:
            _file_row(screen,filename)
            image.with_name(image.stem+'-name-column-proof.json').write_text(json.dumps({
                'raw_screenshot':image.name,'derived_screenshot':derived.name,
                'crop':[175,87,810,729],'scale':3,'filename':filename,
                'selected_raw_coordinates':list(matches[0][1:])},indent=2)+'\n')
            return screen
        time.sleep(.5)
    raise RuntimeError('Native file Name column did not show the exact fixture: '+filename)


def _context_gpg_gui(vm, phase, media):
    home = _home(vm,'context-gpg-home')
    _click_home_card(vm,'Files',home)
    _screen(vm,'context-gpg-files',('File','Edit','View'),60)
    vm.key('ctrl','l');vm.text(media);vm.key('ret')
    _files_media_location(vm,'context-gpg-folder',media)
    # Thunar 4.20.2 explicitly assigns Ctrl+2 to its detailed List View.
    # The column headers distinguish the new view from a stale icon capture.
    vm.key('ctrl','2')
    screen = _files_list_screen(vm,'context-gpg-file-row','ci-helper-sha256.json')
    x,y,w,h = _file_row(screen,'ci-helper-sha256.json')
    _point(vm,screen[0],x+w/2,y+h/2)
    selection = vm.capture('context-gpg-file-selected').name
    _point(vm,screen[0],x+w/2,y+h/2,button='right')
    screen = _screen(vm,'context-gpg-native-menu',('Create Encrypted Backup','Properties'),30)
    menu = screen[0].name
    _click_phrase(vm,'Create Encrypted Backup',screen)
    screen = _screen(vm,'context-gpg-request',
                     ('Create Encrypted Backup','Protect your backup','Backup format',
                      'Save backup as','New passphrase','Confirm passphrase'),60)
    filled = _fill_backup_request(vm,screen,'gpg',media+'/ci-context-'+phase+'.gpg',
                                 EXPORT_PHRASES['gpg'],label='context-gpg')
    vm.key('ret')
    screen = _screen(vm,'context-gpg-created',
                     ('Encrypted backup ready','Encrypted backup created and tested','Original files'),180)
    result = screen[0].name
    _click_result_ok(vm,screen,heading='Encrypted backup ready',
                     body=('Encrypted backup created and tested','Original files'),
                     filename='ci-context-'+phase+'.gpg')
    return {'selection_screenshot':selection,'context_menu_screenshot':menu,
            'request_screenshot':filled[0].name,'result_screenshot':result}


def _created(vm, backup_format, phase):
    vm.key('ret')
    screen = _screen(vm,'backup-'+backup_format+'-verified',('Encrypted backup ready','created','verified'),180)
    _click_result_ok(vm,screen,heading='Encrypted backup ready',body=('created','verified'),
                     filename='ci-gui-'+phase+'.'+backup_format)
    return screen[0].name


def _open_gpg_from_files(vm, phase, media):
    home = _home(vm,'gpg-files-home')
    _click_home_card(vm,'Files',home)
    _screen(vm,'gpg-files-window',('File','Edit','View'),60)
    vm.key('ctrl','l')
    vm.text(media)
    vm.key('ret')
    filename = 'ci-gui-'+phase+'.gpg'
    _files_media_location(vm,'gpg-files-fixture-location',media)
    vm.key('ctrl','2')
    screen = _files_list_screen(vm,'gpg-files-fixture',filename)
    image,rows,_ = screen
    found = [r for r in rows if normalized(r[0]) == normalized(filename)]
    require(len(found) == 1, 'Native Files view did not uniquely show the new GPG backup.')
    _,x,y,w,h = found[0]
    # Actual two clicks on the file item; no direct backend/xdg-open invocation.
    _point(vm,image,x+w/2,y+h/2)
    time.sleep(.12)
    _point(vm,image,x+w/2,y+h/2)
    return _screen(vm,'gpg-native-recovery',('Decrypt GPG Backup','Recover your file','Recovered file name','Passphrase'),60)


def _recovery_request(vm, phase, media, filename, phrase):
    screen = _open_gpg_from_files(vm,phase,media)
    # Source's initial native focus is the passphrase edit; its explicit
    # reverse-tab target is the recovered filename, then Tab returns to secret.
    vm.key('shift','tab')
    vm.key('ctrl','a')
    vm.text(filename)
    vm.key('tab')
    vm.text(phrase)
    return vm.words('gpg-recovery-filled')


def _core_restore_gui(vm, phase):
    """Use the official Core menus and dialogs; never issue restore RPC."""
    name = 'cv-gui-restored-'+phase
    screen = _screen(vm,'core-restore-ready',('Bitcoin Core','File','Settings','Help'),90)
    # Click the observed menu-bar File caption and allow native activation.
    # A transient focus race can consume Alt+F immediately after Core startup.
    boxes = [box for box in _phrase_boxes(screen[1],'File') if box[1] < 40 and box[0] < 150]
    require(len(boxes) == 1, 'Core menu-bar File caption is not unique.')
    x,y,w,h = boxes[0]
    _point(vm,screen[0],x+w/2,y+h/2,settle_click=True)
    screen = _screen(vm,'core-restore-file-menu',('Restore Wallet','Create Wallet','Open Wallet'),30)
    _click_phrase(vm,'Restore Wallet',screen)
    screen = _screen(vm,'core-load-wallet-backup',('Load Wallet Backup','File name','Wallet Data'),60)
    filename = RECOVERED_PREFIX+phase+'.dat'
    # Stock Qt 6.8.3 labels this edit "File &name:" and installs its buddy;
    # Alt+N focuses that native GUI edit regardless of remembered favorites.
    vm.key('alt','n');vm.key('ctrl','a')
    vm.text('/home/vault/Private Workspace/'+filename)
    vm.key('tab')
    screen = _screen(vm,'core-restore-ram-file',('Load Wallet Backup',filename),60)
    # Qt QFileDialog exposes the observed Open button through Alt+O. Its
    # small icon-bearing caption is not reliable in whole-frame OCR.
    vm.key('alt','o')
    screen = _screen(vm,'core-restore-name',('Restore Wallet','Wallet Name'),60)
    # Stock QInputDialog's initial focus is its plain-text wallet-name edit.
    vm.text(name);vm.key('ret')
    screen = _screen(vm,'core-restore-success',('Restore wallet message','Wallet restored successfully'),180)
    success = screen[0].name
    vm.key('ret')  # The attested success message has a single default OK.
    screen = _screen(vm,'core-restored-wallet-selected',
                     ('Bitcoin Core',name,'Overview','Send','Receive','Transactions'),60)
    selected = screen[0].name
    _click_phrase(vm,'Window',screen)
    screen = _screen(vm,'core-restored-window-menu',('Receiving addresses','Sending addresses'),30)
    _click_phrase(vm,'Receiving addresses',screen)
    screen = _screen(vm,'core-restored-receiving-label',
                     ('Receiving addresses',name,'CORE_VAULT_FORENSIC_TEST_'),60)
    label = screen[0].name
    vm.key('esc')  # Dismiss the observed native receiving-address dialog.
    return success,selected,label


def _core_close_restored_gui(vm, phase):
    name = 'cv-gui-restored-'+phase
    _click_home_card(vm,'Bitcoin Core',_home(vm,'core-restored-close-home'))
    screen = _screen(vm,'core-restored-close-ready',('Bitcoin Core',name,'Overview'),60)
    # Click the observed menu-bar File caption and allow native activation.
    # A transient focus race can consume Alt+F immediately after Core startup.
    boxes = [box for box in _phrase_boxes(screen[1],'File') if box[1] < 40 and box[0] < 150]
    require(len(boxes) == 1, 'Core menu-bar File caption is not unique.')
    x,y,w,h = boxes[0]
    _point(vm,screen[0],x+w/2,y+h/2,settle_click=True)
    screen = _screen(vm,'core-restored-close-menu',('Close Wallet','Close All Wallets'),30)
    _click_phrase(vm,'Close Wallet',screen)
    screen = _screen(vm,'core-restored-close-confirm',
                     ('Close wallet','Are you sure you wish to close the wallet',name),30)
    vm.key('alt','y')  # Stock QMessageBox Yes mnemonic on the attested close confirmation.
    def restored_no_longer_selected(text):
        value = normalized(text)
        return all(normalized(word) in value for word in ('Bitcoin Core','File','Settings','Help')) and \
               normalized(name) not in value and 'areyousureyouwishtoclosethewallet' not in value
    # Core may select a loaded original wallet or its no-wallet page. The
    # subsequent guest assertion proves unload independently, without RPC action.
    return vm.wait_screen('core-restored-closed',restored_no_longer_selected,60)[0].name


def _launch_finish(vm, phase):
    # The production entrypoint is launched from the ordinary guest Terminal;
    # its real QInputDialog/QMessageBox and power request are never substituted.
    home = _home(vm,'finish-home')
    _click_home_card(vm,'Terminal',home)
    ready = _terminal_screen(vm,'finish-terminal')
    _enter_terminal_command(vm,'/usr/local/bin/core-vault-finish',ready,label='finish')
    screen = vm.wait_screen('finish-passphrase',lambda text: _shell_failure(text) or
                           all(normalized(phrase) in normalized(text) for phrase in
                               ('Verify encrypted wallet backup','passphrase for')),60)
    require(not _shell_failure(screen[2]), 'Native Terminal could not launch the production Finish dialog.')
    # Enlarge the native format prompt before choosing its public fixture
    # phrase; default OCR can read 7z as 72. Never alias those spellings.
    return _core_scaled_screen(screen)


def _finish_phrase(screen, wrong_gpg=False):
    value = normalized(screen[2])
    if 'gpgbackuppassphrase' in value:
        return WRONG_PHRASE if wrong_gpg else EXPORT_PHRASES['gpg']
    if '7zbackuppassphrase' in value:
        return EXPORT_PHRASES['7z']
    raise RuntimeError('Native Finish did not identify its backup format.')


def run_gui_checks(vm, report, *, phase='live', firmware=None, finish=True,
                   media='/media/vault/VAULT_CI'):
    """Execute native dialogs; raise on gaps instead of manufacturing PASS.

    finish=True requests genuine Finish poweroff and passively waits for this
    owned QEMU to exit. The controller must not call quit before that wait.
    The same function can be called in Live and installed disposable phases.
    """
    require(phase in ('live','installed') and firmware in ('bios','uefi'), 'Invalid GUI fixture phase/firmware.')
    require(media == '/media/vault/VAULT_CI', 'GUI fixture media must be the designated USB mount.')
    report['genuine_backup_dialogs'] = 'running'
    report['genuine_gpg_recovery_dialogs'] = 'pending'
    report['genuine_context_menu_gpg_creation'] = 'pending'
    report['genuine_core_restore_dialogs'] = 'pending'
    report['genuine_finish_dialogs_and_session_destruction'] = 'pending'
    checks = report.setdefault('gui_checks',[])
    def passed(label, screenshot=None, **facts):
        checks.append(dict(check=label,status='PASS',phase=phase,screenshot=screenshot,**facts))
    try:
        screenshot = _terminal_check(vm,'initial',phase,firmware,media)
        passed('actual-gui-fixture-attestation',screenshot)
        for backup_format in ('gpg','7z'):
            path = media+'/ci-gui-'+phase+'.'+backup_format
            _backup_request(vm,backup_format,path,EXPORT_PHRASES[backup_format],phase)
            screenshot = _created(vm,backup_format,phase)
            passed('native-wallet-backup-'+backup_format+'-created-and-verified',screenshot)
        screenshot = _terminal_check(vm,'exports',phase,firmware,media)
        passed('gui-exports-match-receipts-and-authenticate-from-usb',screenshot)
        existing = media+'/ci-gui-'+phase+'.gpg'
        _backup_request(vm,'gpg',existing,EXPORT_PHRASES['gpg'],phase)
        vm.key('ret')
        screen = _screen(vm,'backup-existing-refused',('Protect your backup','already exists','will not be overwritten'),30)
        passed('native-backup-existing-output-disabled',screen[0].name)
        vm.key('esc')
        _backup_request(vm,'gpg',media+'/ci-gui-'+phase+'-cancel.gpg',EXPORT_PHRASES['gpg'],phase)
        vm.key('esc')
        screenshot = _terminal_check(vm,'unchanged',phase,firmware,media)
        passed('native-backup-cancel-and-no-overwrite-preserve-output',screenshot)
        report['genuine_backup_dialogs'] = 'passed'
        _terminal_check(vm,'context-intent',phase,firmware,media)
        context_screens = _context_gpg_gui(vm,phase,media)
        screenshot = _terminal_check(vm,'context',phase,firmware,media)
        passed('native-files-context-menu-gpg-creation-authenticates-exact-public-json',screenshot,
               **context_screens,generic_file=True,wallet_receipt_created=False)
        report['genuine_context_menu_gpg_creation'] = 'passed'
        _recovery_request(vm,phase,media,'ci-gui-'+phase+'-cancel.dat',EXPORT_PHRASES['gpg'])
        vm.key('esc')
        _recovery_request(vm,phase,media,'ci-gui-'+phase+'-wrong.dat',WRONG_PHRASE)
        vm.key('ret')
        screen = _screen(vm,'gpg-recovery-wrong-password',('GPG recovery could not be completed','No recovered file was published'),180)
        passed('native-gpg-recovery-wrong-passphrase-rejected',screen[0].name)
        _click_result_ok(vm,screen,heading='GPG recovery could not be completed',
                         body=('No recovered file was published',))
        screenshot = _terminal_check(vm,'no-plaintext',phase,firmware,media)
        passed('native-recovery-cancel-and-authentication-failure-publish-nothing',screenshot)
        recovered = RECOVERED_PREFIX+phase+'.dat'
        _recovery_request(vm,phase,media,recovered,EXPORT_PHRASES['gpg'])
        vm.key('ret')
        screen = _screen(vm,'gpg-recovery-verified',('File recovered to RAM','Private Workspace'),180)
        passed('native-files-double-click-routes-gpg-and-recovers-to-ram',screen[0].name)
        _click_result_ok(vm,screen,heading='File recovered to RAM',body=('Private Workspace',),
                         filename=recovered)
        _recovery_request(vm,phase,media,recovered,EXPORT_PHRASES['gpg'])
        vm.key('ret')
        screen = _screen(vm,'gpg-recovery-existing-refused',('Recover your file','already exists','will not be overwritten'),30)
        passed('native-recovery-existing-output-disabled',screen[0].name)
        vm.key('esc')
        screenshot = _terminal_check(vm,'recovery',phase,firmware,media)
        passed('gui-recovered-wallet-is-exact-authenticated-snapshot-in-ram',screenshot)
        report['genuine_gpg_recovery_dialogs'] = 'passed'
        # Actual user restoration is entirely the unmodified Core GUI. Guest
        # Terminal checks only observe it and clean up the owned test fixture.
        _click_home_card(vm,'Bitcoin Core',_home(vm,'restore-core-home'))
        _screen(vm,'restore-core-started',('Bitcoin Core','File','Settings','Help'),90)
        success,selected,label = _core_restore_gui(vm,phase)
        passed('native-core-restore-dialog-loads-recovered-ram-wallet',success,
               selected_wallet_screenshot=selected,core_restore_dialog=True,restore_rpc_used=False)
        passed('native-restored-wallet-shows-synthetic-receiving-label',label)
        screenshot = _terminal_check(vm,'restore',phase,firmware,media)
        passed('native-restored-wallet-core-ownership-and-label-attested',screenshot,read_only_rpc=True)
        screenshot = _core_close_restored_gui(vm,phase)
        passed('native-core-close-wallet-unloads-restored-test-wallet',screenshot,unload_rpc_used=False)
        screenshot = _terminal_check(vm,'restore-cleanup',phase,firmware,media)
        passed('owned-restored-test-wallet-ram-cleanup-preserves-originals',screenshot)
        report['genuine_core_restore_dialogs'] = 'passed'
        screen = _launch_finish(vm,phase)
        # Inventory order is not assumed: each actual prompt identifies format.
        for _ in range(3):
            wrong = 'gpgbackuppassphrase' in normalized(screen[2])
            vm.text(_finish_phrase(screen,wrong_gpg=True));vm.key('ret')
            if wrong:
                break
            # A new format distinguishes the next prompt from a stale capture.
            screen = _screen(vm,'finish-next-format',('Verify encrypted wallet backup','GPG backup passphrase'),180)
        else:
            raise RuntimeError('Native Finish never presented the GPG verification prompt.')
        screen = _screen(vm,'finish-wrong-password-session-kept',('Private session still active','Keep session open'),180)
        passed('native-finish-wrong-gpg-passphrase-keeps-session-open',screen[0].name)
        vm.key('ret')  # Production missing_backup explicitly defaults to Keep session open.
        screenshot = _terminal_check(vm,'session',phase,firmware,media)
        passed('wrong-finish-retains-core-wallets-ram-and-usb-backups',screenshot)
        screen = _launch_finish(vm,phase)
        seen = []
        for index in range(2):
            phrase = _finish_phrase(screen)
            current = 'gpg' if 'gpgbackuppassphrase' in normalized(screen[2]) else '7z'
            seen.append(current)
            vm.text(phrase);vm.key('ret')
            if index == 0:
                other = '7z' if current == 'gpg' else 'GPG'
                screen = _screen(vm,'finish-verified-next-format',
                                 ('Verify encrypted wallet backup',other+' backup passphrase'),180)
            else:
                screen = _screen(vm,'finish-verified-summary',
                                 ('Finish Private Session','Encrypted wallet backups: created and verified'),180)
        require(sorted(seen) == ['7z','gpg'], 'Native Finish did not verify both GUI-export formats.')
        require('encryptedwalletbackupscreatedandverified' in normalized(screen[2]), 'Native Finish did not reach the verified summary.')
        passed('native-finish-verifies-both-formats-and-prompts-final-confirmation',screen[0].name)
        if not finish:
            _click_phrase(vm,'No',screen)
            passed('native-finish-final-cancel-keeps-session',vm.capture('finish-final-cancel').name)
            report['genuine_finish_dialogs_and_session_destruction'] = 'dialogs-passed-destruction-not-requested'
            report['gui_status'] = 'dialogs-passed-destruction-not-requested'
            return {'status':report['gui_status'],'checks':checks,'phase':phase,'poweroff_observed':False}
        # Production confirmation has Yes/No and explicitly defaults to No.
        # Shift+Tab selects the adjacent Finish button; Return activates it.
        vm.key('shift','tab');vm.key('ret')
        until = time.monotonic()+120
        while vm.p.poll() is None and time.monotonic() < until:
            time.sleep(.25)
        require(vm.p.poll() == 0, 'Genuine Finish did not successfully power off the owned QEMU.')
        passed('native-verified-finish-powers-off-owned-guest',qemu_exit_code=0,controller_quit_used=False)
        report['genuine_finish_dialogs_and_session_destruction'] = 'passed'
    except BaseException as error:
        report['gui_status'] = 'failed'
        report['gui_error'] = str(error)
        raise
    report['gui_status'] = 'passed-covered-checks'
    return {'status':report['gui_status'],'checks':checks,'phase':phase,'poweroff_observed':True}


def _guest_check(kind, phase, firmware):
    """Attest native restoration with read-only RPC; clean only its RAM fixture."""
    import sys
    sys.path.insert(0,'/usr/lib/core-vault')
    sys.path.insert(1,'/usr/lib/core-vault-backup')
    import runtime
    import export
    target, fixture = PUBLIC['machine_guard'](phase,firmware)
    media, mount = PUBLIC['fixture_mount'](fixture,Path('/media/vault/VAULT_CI'))
    PUBLIC['policy_attestation'].__globals__['REPORT'] = {'checks':[]}
    PUBLIC['policy_attestation'](runtime)
    result_path = media/(firmware+'-'+phase+'-result.json')
    probe = json.loads(result_path.read_text())
    require(probe.get('status') == 'passed-covered-checks', 'GUI fixture has no successful production guest probe.')
    original = {item['format']:item for item in probe['exports']}
    require(set(original) == {'gpg','7z'}, 'GUI fixture needs exactly the two designated wallet formats.')
    wallets = runtime.wallet_files()
    originals = {item['wallet'] for item in original.values()}
    restored_name = 'cv-gui-restored-'+phase
    directory = runtime.WALLETS/restored_name
    expected_wallets = originals | ({restored_name} if kind in ('restore','restore-cleanup') else set())
    require(set(wallets) == expected_wallets and all(
        re.fullmatch(r'cv-forensic-ci-(7z|gpg)-[0-9a-f]{32}',name) for name in originals),
        'GUI checks refuse unrelated or additional wallet files.')
    state_path = media/('gui-'+firmware+'-'+phase+'-state.json')
    recovered = Path('/home/vault/Private Workspace')/(RECOVERED_PREFIX+phase+'.dat')
    if kind == 'initial':
        require(not state_path.exists(), 'GUI evidence state already exists.')
        require(all(not (media/('ci-gui-'+phase+'.'+fmt)).exists() for fmt in ('7z','gpg')) and not recovered.exists(),
                'GUI fixture outputs already exist.')
        state = {'phase':phase,'firmware':firmware,'checks':[]}
    else:
        state = json.loads(state_path.read_text())
        require(state.get('phase') == phase and state.get('firmware') == firmware, 'GUI evidence state has another fixture identity.')
    receipts = runtime.read_receipts()
    require(set(receipts) == originals, 'GUI checks refuse unrelated export receipts.')
    if kind in ('exports','unchanged','context-intent','context','recovery','restore','restore-cleanup','session'):
        for fmt,item in original.items():
            record = receipts[item['wallet']]
            expected = media/('ci-gui-'+phase+'.'+fmt)
            require(record['archive'] == str(expected) and export.receipt_format(record) == fmt and
                    runtime.file_digest(expected) == record['archive_sha256'] and
                    runtime.current_wallet_digest(item['wallet'],wallets[item['wallet']]) == record['wallet_digest'],
                    'GUI export does not match its source wallet and current receipt.')
            export.verify_export(record,EXPORT_PHRASES[fmt])
        hashes = {fmt:receipts[item['wallet']]['archive_sha256'] for fmt,item in original.items()}
        if kind == 'exports':
            state['archive_sha256'] = hashes
        else:
            require(hashes == state['archive_sha256'], 'GUI cancel/overwrite/Finish changed existing encrypted outputs.')
        require(not (media/('ci-gui-'+phase+'-cancel.gpg')).exists(), 'Cancelled creation published an output.')
    if kind in ('context-intent','context'):
        source = media/'ci-helper-sha256.json'
        archive = media/('ci-context-'+phase+'.gpg')
        require(source.is_file() and not source.is_symlink() and source.stat().st_uid == 1000 and
                source.stat().st_size <= 16384, 'Context-menu fixture source is not the designated public JSON.')
        require(json.loads(source.read_bytes()) == {'schema':1,'helpers':probe['helper_sha256']},
                'Context-menu fixture JSON no longer matches the attested helper manifest.')
        if kind == 'context-intent':
            require(not os.path.lexists(archive) and 'context_source_sha256' not in state,
                    'Context-menu fixture output or prior creation intent already exists.')
            state['context_source_sha256'] = runtime.file_digest(source)
            state['context_receipts'] = receipts
        else:
            require('context-intent' in state['checks'] and receipts == state['context_receipts'] and
                    runtime.file_digest(source) == state['context_source_sha256'],
                    'Context-menu creation changed its original public file or wallet receipts.')
            require(archive.is_file() and not archive.is_symlink() and archive.stat().st_uid == 1000,
                    'Context-menu GPG output was not published on the designated USB.')
            import tempfile
            from gpg_backend import decrypt_file
            with tempfile.TemporaryDirectory(prefix='ci-context-check-',dir=runtime.ROOT/'export') as temporary:
                raw = Path(temporary)/'public.json'
                require(runtime.mount_at(Path(temporary))['fstype'] == 'tmpfs' and
                        runtime.mount_at(Path(temporary))['maj:min'] == runtime.mount_at(runtime.ROOT,True)['maj:min'],
                        'Context-menu verification plaintext is outside private RAM.')
                require(decrypt_file(archive,raw,EXPORT_PHRASES['gpg'],ram_root=runtime.ROOT/'export') == 'AES256-OCB',
                        'Context-menu GPG output has the wrong authenticated encryption profile.')
                require(runtime.file_digest(raw) == state['context_source_sha256'] and
                        raw.read_bytes() == source.read_bytes(), 'Context-menu GPG output does not contain the exact public JSON bytes.')
            require(runtime.read_receipts() == state['context_receipts'] and set(runtime.wallet_files()) == originals,
                    'Generic context-menu GPG creation changed wallet inventory or export receipts.')
            state['context_archive_sha256'] = runtime.file_digest(archive)
    if state.get('context_archive_sha256'):
        require(runtime.file_digest(media/('ci-context-'+phase+'.gpg')) == state['context_archive_sha256'] and
                runtime.file_digest(media/'ci-helper-sha256.json') == state['context_source_sha256'],
                'A later GUI operation changed the generic ciphertext or its original public source.')
    if kind == 'no-plaintext':
        require(all(not (recovered.parent/('ci-gui-'+phase+'-'+suffix+'.dat')).exists()
                    for suffix in ('cancel','wrong')), 'Cancelled/failed recovery published plaintext.')
    if kind in ('recovery','restore','restore-cleanup','session'):
        record = receipts[original['gpg']['wallet']]
        require(recovered.is_file() and not recovered.is_symlink() and recovered.stat().st_uid == 1000 and
                runtime.mount_at(recovered)['fstype'] == 'tmpfs' and
                runtime.file_digest(recovered) == record['wallet_backup_sha256'] and
                runtime.wallet_digest(recovered) == record['wallet_digest'],
                'Native GPG recovery did not publish the exact authenticated snapshot in RAM.')
    if kind == 'recovery':
        require(not os.path.lexists(directory), 'Native restoration fixture target already exists.')
        state['restore_intent'] = restored_name
        state['restore_receipts'] = receipts
    if kind == 'restore':
        deadline = time.monotonic()+60
        while True:
            try:
                require(runtime.rpc('getnetworkinfo')['networkactive'] is False, 'Restore Core is not offline.')
                break
            except RuntimeError:
                require(time.monotonic() < deadline, 'Production Core RPC did not become ready for restoration.')
                time.sleep(.25)
        require(state.get('restore_intent') == restored_name and receipts == state.get('restore_receipts'),
                'Native restoration lacks the attested creation intent or changed original receipts.')
        require(runtime.loaded_wallet_name(restored_name,runtime.rpc('listwallets')) == restored_name,
                'Native Core restoration did not load the designated test wallet.')
        runtime.check_storage();runtime.check_core_mounts()
        require(directory.is_dir() and not directory.is_symlink() and directory.stat().st_uid == 1000 and
                directory.resolve(strict=True) == runtime.WALLETS.resolve(strict=True)/restored_name and
                runtime.mount_at(directory)['maj:min'] == runtime.mount_at(runtime.ROOT,True)['maj:min'],
                'Native restoration target is outside owned private RAM.')
        addresses = runtime.rpc('getaddressesbylabel',original['gpg']['marker'],wallet=restored_name)
        require(bool(addresses) and all(runtime.rpc('getaddressinfo',address,wallet=restored_name)['ismine'] for address in addresses),
                'Natively restored wallet lacks the expected owned labelled address.')
        info = runtime.rpc('getwalletinfo',wallet=restored_name)
        require(info['private_keys_enabled'] is True and info.get('unlocked_until') == 0,
                'Natively restored wallet lost its locked private-key state.')
        identity = directory.stat()
        state['native_restored_directory'] = {'device':identity.st_dev,'inode':identity.st_ino}
    if kind == 'restore-cleanup':
        require(state.get('restore_intent') == restored_name and 'restore' in state['checks'] and
                receipts == state.get('restore_receipts'), 'Native restore cleanup lacks prior restoration attestation.')
        until = time.monotonic()+30
        while runtime.loaded_wallet_name(restored_name,runtime.rpc('listwallets')) is not None:
            require(time.monotonic() < until, 'Native Close Wallet did not unload the restored test wallet.')
            time.sleep(.25)
        runtime.check_storage();runtime.check_core_mounts()
        identity = directory.lstat()
        require(directory.is_dir() and not directory.is_symlink() and identity.st_uid == 1000 and
                {'device':identity.st_dev,'inode':identity.st_ino} == state['native_restored_directory'] and
                directory.resolve(strict=True) == runtime.WALLETS.resolve(strict=True)/restored_name and
                runtime.mount_at(directory)['maj:min'] == runtime.mount_at(runtime.ROOT,True)['maj:min'],
                'Native restore cleanup target identity is outside the owned private RAM fixture.')
        import shutil
        shutil.rmtree(directory)
        require(not os.path.lexists(directory) and set(runtime.wallet_files()) == originals and
                runtime.read_receipts() == state['restore_receipts'], 'Native restore cleanup changed original wallet state.')
        runtime.check_loaded_wallet_coverage(runtime.wallet_files())
        for item in original.values():
            require(runtime.current_wallet_digest(item['wallet'],wallets[item['wallet']]) == receipts[item['wallet']]['wallet_digest'],
                    'Native restore cleanup changed an original wallet digest.')
    if kind == 'session':
        require(runtime.rpc('getnetworkinfo')['networkactive'] is False and len(runtime.wallet_files()) == 2,
                'Wrong Finish destroyed the active Core/private session.')
    state['checks'].append(kind)
    state_path.write_text(json.dumps(state,indent=2)+'\n')
    print('GUI_CHECK_PASS_'+kind,flush=True)


def _selector_self_test():
    """Exercise fail-closed targets locally; never report actual VM acceptance."""
    import ast
    import tempfile
    from PIL import Image
    checks = []
    with tempfile.TemporaryDirectory(prefix='ci-gui-selector-') as temporary:
        image = Path(temporary)/'synthetic-selector.png'
        Image.new('RGB',(1000,800),'black').save(image)
        name = 'ci-helper-sha256.json'
        row = (name,210,170,145,15)
        header = ('Name',200,90,40,15)
        screen = (image,[header,(name,10,5,145,15),(name,10,170,145,15),row,(name,10,745,145,15)],'')
        require(_file_row(screen,name) == row[1:], 'Selector did not exclude chrome and footer duplicates.')
        checks.append('exact-public-file-row-excludes-chrome-and-footer')
        for rows in ([row,(name,210,230,145,15)], [('not-'+name,210,170,170,15)],
                     [('ci-helper-',210,170,80,15),('sha256.json',210,190,85,15)]):
            try:
                _file_row((image,[header,*rows],''),name)
            except RuntimeError:
                pass
            else:
                raise RuntimeError('Ambiguous, wrong or wrapped fixture filename was accepted.')
        checks.append('ambiguous-wrong-and-wrapped-file-targets-rejected')
        menu = [('Create',100,300,45,15),('Encrypted',150,300,70,15),('Backup',225,300,50,15)]
        require(len(_phrase_boxes(menu,'Create Encrypted Backup')) == 1,
                'Native context menu caption was not recognized on one line.')
        require(not _phrase_boxes(menu[:-1]+[('Backup',100,340,50,15)],'Create Encrypted Backup'),
                'A wrapped unrelated context caption was accepted.')
        checks.append('native-context-caption-requires-one-complete-line')
        class IsolatedInputRecorder:
            def __init__(self): self.calls = []
            def call(self, command, **arguments): self.calls.append((command,arguments))
        recorder = IsolatedInputRecorder()
        _point(recorder,image,300,177,button='right')
        require(len(recorder.calls) == 3 and all(command == 'input-send-event' for command,_ in recorder.calls) and
                recorder.calls[1][1]['events'] == [{'type':'btn','data':{'button':'right','down':True}}] and
                recorder.calls[2][1]['events'] == [{'type':'btn','data':{'button':'right','down':False}}],
                'Context action did not use a bounded recorded right-click.')
        before = len(recorder.calls)
        try:
            _point(recorder,image,1000,177,button='right')
        except RuntimeError:
            pass
        else:
            raise RuntimeError('Out-of-frame input target was accepted.')
        require(len(recorder.calls) == before, 'Out-of-frame selector emitted input.')
        checks.append('right-click-is-addressed-and-screen-bounds-precede-input')
        from PIL import ImageDraw, ImageFont
        result_image = Path(temporary)/'source-result-selector.png'
        result_font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',13)
        def result_frame(heading='Encrypted backup ready',caption='OK',*,duplicate=False,footer=False,
                         paint=True,top_widget=False,footer_widget=False,foreign_title=False,
                         output_filename='ci-gui-live.gpg',ocr_filename=None):
            pixels = Image.new('RGB',(1280,800),'#111111')
            draw = ImageDraw.Draw(pixels)
            if paint:
                draw.rectangle((1126,704,1251,735),fill='#2169a8')
                draw.text((1180,713),caption,font=result_font,fill='white')
            if duplicate:
                draw.rectangle((970,704,1095,735),fill='#2169a8')
                draw.text((1024,713),'OK',font=result_font,fill='white')
            if top_widget:draw.rectangle((1126,54,1251,85),fill='#2169a8')
            if footer_widget:draw.rectangle((1126,764,1251,795),fill='#2169a8')
            recovery = heading in ('File recovered to RAM','GPG recovery could not be completed')
            title = 'Bitcoin Core Vault '+('GPG Recovery' if recovery else 'Encrypted Backup')
            if foreign_title:title = 'Bitcoin Core'
            words = []
            for line,top,height,left in ((title,774 if footer else 5,10,24),
                                         (heading,774 if footer else 48,20,97)):
                for word in line.split():
                    words.append((word,left,top,7*len(word),height));left += 7*len(word)+6
            messages = {'Encrypted backup ready':('Encrypted wallet backup created and verified',
                        '/media/vault/VAULT_CI/'+output_filename),
                        'Backup could not be completed':('Backup failed',''),
                        'File recovered to RAM':('File recovered into Private Workspace',
                        '/home/vault/Private Workspace/ci-gui-recovered-live.dat'),
                        'GPG recovery could not be completed':('No recovered file was published','')}
            for line,top in zip(messages.get(heading,('Unknown result','')),(89,105)):
                draw.text((97,top-3),line,font=result_font,fill='#c7c7c7')
                if top == 105 and ocr_filename is not None:line = line.replace(output_filename,ocr_filename)
                left = 97
                for word in line.split():
                    words.append((word,left,top,7*len(word),13));left += 7*len(word)+6
            pixels.save(result_image)
            return result_image,words,' '.join(word[0] for word in words)
        result_options = dict(heading='Encrypted backup ready',body=('created','verified'),filename='ci-gui-live.gpg')
        result_box = _result_ok_box(result_frame(),**result_options)
        require(result_box is not None and result_box[0] > 1126 and result_box[1] > 704,
                'Observed source-blue button interior did not recognize its exact OK caption.')
        result_input = IsolatedInputRecorder()
        _click_result_ok(result_input,result_frame(),**result_options)
        require(len(result_input.calls) == 3,'Result acknowledgement emitted extra clicks or keyboard input.')
        for args in ({'caption':'Cancel'},{'footer':True},{'paint':False},{'heading':'Unknown result'},
                     {'paint':False,'top_widget':True},{'paint':False,'footer_widget':True},{'foreign_title':True}):
            require(_result_ok_box(result_frame(**args),**result_options) is None,
                    'Wrong caption, footer, unknown or unpainted result was accepted.')
        before = len(result_input.calls)
        try:_click_result_ok(result_input,result_frame(duplicate=True),**result_options)
        except RuntimeError:pass
        else:raise RuntimeError('Duplicate source-blue result buttons were accepted.')
        require(len(result_input.calls) == before,'An ambiguous result emitted acknowledgement input.')
        require(_result_ok_box(result_frame(),heading='Encrypted backup ready',body=('created','verified'),
                              filename='ci-context-live.gpg') is None,
                'A result for the wrong public filename was acknowledged.')
        checks.append('source-result-ok-exact-interior-caption-and-mapped-target-reject-stale-foreign-and-duplicate-buttons')
        for heading,body,filename in (
            ('Backup could not be completed',('Backup failed',),None),
            ('File recovered to RAM',('Private Workspace',),'ci-gui-recovered-live.dat'),
            ('GPG recovery could not be completed',('No recovered file was published',),None)):
            require(_result_ok_box(result_frame(heading),heading=heading,body=body,filename=filename) is not None,
                    'An explicit source ResultDialog acknowledgement was rejected: '+heading)
        checks.append('only-four-source-result-headings-with-expected-body-use-the-private-ok-selector')
        seven_result = result_frame(output_filename='ci-gui-live.7z',ocr_filename='ci-gui-live.72')
        require(_result_ok_box(seven_result,heading='Encrypted backup ready',body=('created','verified'),
                              filename='ci-gui-live.7z') is not None,
                'Exact public path-row crop did not recognize the actual .7z basename.')
        for wrong in ('ci-gui-live.72','ci-context-live.7z','ci-gui-live.7z.gpg'):
            frame = result_frame(output_filename=wrong)
            require(_result_ok_box(frame,heading='Encrypted backup ready',body=('created','verified'),
                                  filename='ci-gui-live.7z') is None,
                    'Wrong public basename or extension was accepted from result pixels.')
        valid = result_frame(output_filename='ci-gui-live.7z',ocr_filename='ci-gui-live.72')
        path_row = next(row for row in valid[1] if row[0].startswith('/'))
        for altered in (valid[1]+[(path_row[0],path_row[1],path_row[2]+20,path_row[3],path_row[4])],
                        [(row[0],-10,*row[2:]) if row is path_row else row for row in valid[1]]):
            before = len(result_input.calls)
            try:_click_result_ok(result_input,(valid[0],altered,''),heading='Encrypted backup ready',
                                  body=('created','verified'),filename='ci-gui-live.7z')
            except RuntimeError:pass
            else:raise RuntimeError('Duplicate or out-of-bounds public result paths were accepted.')
            require(len(result_input.calls) == before,'Unsafe public path crop emitted acknowledgement input.')
        checks.append('absent-primary-public-result-path-crop-keeps-exact-basename-extension-and-client-bounds')
        paced = IsolatedInputRecorder()
        original_sleep = time.sleep
        time.sleep = lambda seconds:paced.calls.append(('settle',seconds))
        try:
            _point(paced,image,202,55,settle_click=True)
            _point(paced,image,500,400,click=False)
        finally:
            time.sleep = original_sleep
        require(len(paced.calls) == 6 and
                [event['type'] for event in paced.calls[0][1]['events']] == ['abs','abs'] and
                paced.calls[1][1]['events'] == [{'type':'btn','data':{'button':'left','down':True}}] and
                paced.calls[2] == ('settle',.10) and
                paced.calls[3][1]['events'] == [{'type':'btn','data':{'button':'left','down':False}}] and
                paced.calls[4] == ('settle',.25) and
                [event['type'] for event in paced.calls[5][1]['events']] == ['abs','abs'],
                'Prompt focus moved before button release and its guest-delivery settling period.')
        checks.append('terminal-focus-down-up-and-release-settle-precede-pointer-only-parking')
        heading = [('Bitcoin',360,180,106,22),('Core',479,181,70,21),('Vault',560,180,81,22)]
        home_rows = list(heading)
        for index,title in enumerate(('Bitcoin Core','KeePassXC','Argiver','Brasero','Print & Labels',
                                      'Files','Editor','Terminal','Wallet Backup','Vault Guide')):
            left = 80+170*(index%5)
            top = 340 if index < 5 else 498
            for word in title.split():
                home_rows.append((word,left,top,7*len(word),14));left += 7*len(word)+4
        # This subtitle occurrence must not compete with the actual Files card.
        home_rows.append(('files',650,235,35,14))
        home = (image,home_rows,' '.join(row[0] for row in home_rows))
        require(_home_recognized(home), 'One uncertain Arqiver spelling rejected otherwise complete Home geometry.')
        before = len(recorder.calls)
        _click_home_card(recorder,'Files',home)
        require(len(recorder.calls) == before+3, 'Source subtitle conflicted with the native Files card.')
        checks.append('home-layout-tolerates-one-uncertain-card-and-excludes-subtitle')
        terminal_rows = [(word,x,y,w,13) for word,x,y,w,_ in home_rows]
        require(not _home_recognized((image,terminal_rows,home[2])),
                'Terminal-sized printed titles were accepted as native Home.')
        require(not _home_recognized((image,home_rows+[(word,x,y+400,w,h) for word,x,y,w,h in heading],home[2])),
                'Conflicting Home headings were accepted.')
        checks.append('terminal-sized-text-and-conflicting-home-headings-rejected')
        partially_covered = heading+[row for row in home_rows[len(heading):]
                                     if row[1] < 200 or row[1] > 740]
        require(not _home_recognized((image,partially_covered,home[2])),
                'A modal-covered Home with only outside cards was accepted.')
        checks.append('modal-covered-partial-card-grid-rejected')
        before = len(recorder.calls)
        try:
            _click_home_card(recorder,'Terminal',(image,home_rows+[('Terminal',780,498,56,14)],home[2]))
        except RuntimeError:
            pass
        else:
            raise RuntimeError('Conflicting native card candidates were accepted.')
        require(len(recorder.calls) == before, 'Conflicting card selector emitted input.')
        checks.append('conflicting-card-targets-rejected-before-input')
        home_footer_image = Path(temporary)/'isolated-home-with-terminal-tabs.png'
        Image.new('RGB',(1280,800),'black').save(home_footer_image)
        actual_heading = [('Bitcoin',500,196,106,22),('Core',619,197,70,21),('Vault',700,196,81,22)]
        actual_card = ('Terminal',606,498,67,11)
        footer_cards = [('Terminal',82,774,164,12),('Terminal',317,774,164,12)]
        footer_vm = IsolatedInputRecorder()
        _click_home_card(footer_vm,'Terminal',
                         (home_footer_image,actual_heading+[actual_card,*footer_cards],''))
        target_events = footer_vm.calls[0][1]['events']
        require(len(footer_vm.calls) == 3 and
                target_events[0]['data']['value'] == round((606+67/2)*32767/(1280-1)) and
                target_events[1]['data']['value'] == round((498+11/2)*32767/(800-1)),
                'Taller Terminal task tabs displaced the actual observed Home card target.')
        checks.append('actual-home-terminal-card-target-excludes-both-taller-taskbar-tabs')
        for candidates in (footer_cards,[actual_card,('Terminal',790,498,67,11),*footer_cards],
                           [('Terminal',-10,498,67,11),*footer_cards],
                           [('Terminal',1250,498,67,11),*footer_cards],
                           [('Terminal',606,746,67,11),*footer_cards]):
            refused = IsolatedInputRecorder()
            try:_click_home_card(refused,'Terminal',(home_footer_image,actual_heading+candidates,''))
            except RuntimeError:pass
            else:raise RuntimeError('Footer-only, duplicate-client or out-of-bounds Home title accepted input.')
            require(not refused.calls,'Rejected Home card geometry emitted input.')
        checks.append('footer-only-duplicate-client-and-outbound-home-titles-reject-before-input')
        caption = [('Select',260,200,42,14),('wallet',307,200,42,14),('to',354,200,14,14),
                   ('back',373,200,28,14),('up',406,200,14,14)]
        instruction = [('Select',260,230,42,14),('items',307,230,35,14),('from',347,230,28,14),
                       ('the',380,230,21,14),('list',406,230,28,14),('below.',439,230,42,14)]
        target = ('cv-forensic-ci-gpg-'+'0'*32,260,270,430,14)
        footer = [(word,x,y+574,w,h) for word,x,y,w,h in caption]
        require(_wallet_picker_row((image,footer,''),'gpg') is None,
                'Taskbar-only picker title was accepted as painted client readiness.')
        require(_wallet_picker_row((image,caption+[target],''),'gpg') is None,
                'A painted heading without its source-backed instruction was accepted.')
        require(_wallet_picker_row((image,caption+instruction,''),'gpg') is None,
                'Painted anchors without their target row were accepted.')
        painted = (image,caption+instruction+[target],'')
        require(_wallet_picker_row(painted,'gpg') == target[1:],
                'Unique painted synthetic wallet row was not recognized below its instruction.')
        try:_wallet_picker_row((image,painted[1]+[(target[0],260,295,430,14)],''),'gpg')
        except RuntimeError:pass
        else:raise RuntimeError('Conflicting synthetic picker rows were accepted.')
        require(_wallet_picker_row((image,caption+instruction+[
                    (target[0],260,774,430,14)],''),'gpg') is None,
                'A synthetic-format task-tab label was accepted as a client row.')
        checks.append('picker-requires-painted-heading-instruction-and-unique-body-row-not-footer')
        original_list_ocr = globals()['_wallet_list_ocr']
        fallback_calls = []
        fallback_rows = [('cv-forensic-ci-7z-'+'0'*32,260,290,430,14)]
        def recorded_list_ocr(screen,anchor):
            fallback_calls.append(anchor)
            return fallback_rows
        globals()['_wallet_list_ocr'] = recorded_list_ocr
        try:
            require(_wallet_picker_row((image,footer,''),'7z',ocr_fallback=True) is None and not fallback_calls,
                    'Footer-only picker readiness triggered fallback OCR.')
            require(_wallet_picker_row((image,caption+[target],''),'7z',ocr_fallback=True) is None and not fallback_calls,
                    'Missing instruction triggered fallback OCR.')
            require(_wallet_picker_row(painted,'gpg',ocr_fallback=True) == target[1:] and not fallback_calls,
                    'An exact primary target unnecessarily triggered fallback OCR.')
            require(_wallet_picker_row(painted,'7z',ocr_fallback=True) == fallback_rows[0][1:] and len(fallback_calls) == 1,
                    'Anchored exact fallback target was not returned in raw coordinates.')
            fallback_rows.append((fallback_rows[0][0],260,320,430,14))
            try:_wallet_picker_row(painted,'7z',ocr_fallback=True)
            except RuntimeError:pass
            else:raise RuntimeError('Duplicate fallback wallet rows were accepted.')
        finally:
            globals()['_wallet_list_ocr'] = original_list_ocr
        checks.append('picker-fallback-requires-painted-anchors-and-absent-primary-target')
        checks.append('picker-fallback-preserves-exact-format-and-duplicate-refusal')
        picker_pixels = Image.open(image).convert('RGB')
        ImageDraw.Draw(picker_pixels).rectangle((480,380,520,420),fill='white')
        picker_pixels.save(image)
        class PickerPaintRecorder(IsolatedInputRecorder):
            def __init__(self):super().__init__();self.frames=0;self.selected=False;self.returns=0
            def words(self,label):
                if label.endswith('-home-before'):return home
                self.frames += 1
                return (image,footer,'') if self.frames == 1 else painted
            def key(self,*keys):
                require(keys == ('ret',) and self.frames == 2,
                        'Picker input preceded a fully observed painted target.')
                self.selected=True;self.returns += 1
            def wait_screen(self,*arguments):
                require(self.selected,'Picker request was observed before selecting its painted row.')
                return painted
        picker = PickerPaintRecorder()
        _select_wallet(picker,'gpg','live')
        require(picker.frames == 2 and picker.selected and picker.returns == 1 and len(picker.calls) == 7 and
                picker.calls[-2][1]['events'] == [{'type':'btn','data':{'button':'left','down':False}}] and
                [event['type'] for event in picker.calls[-1][1]['events']] == ['abs','abs'],
                'Picker paint wait emitted an extra or premature row click.')
        checks.append('picker-waits-for-paint-and-released-row-click-then-parks-without-click-before-one-return')
        picker_pixels = Image.open(image).convert('RGB')
        ImageDraw.Draw(picker_pixels).rectangle((480,380,520,420),fill='black')
        picker_pixels.save(image)
        obstructed_picker = PickerPaintRecorder()
        try:_select_wallet(obstructed_picker,'gpg','live')
        except RuntimeError:pass
        else:raise RuntimeError('Nonblank picker parking received a row-selection input.')
        require(not obstructed_picker.selected and obstructed_picker.returns == 0 and len(obstructed_picker.calls) == 3,
                'An unobserved blank parking region emitted a selection or Return.')
        checks.append('picker-rejects-nonblank-client-parking-before-row-selection-or-return')
        destination = '/media/vault/VAULT_CI/ci-gui-live.gpg'
        destination_labels = [('Save',25,170,30,9),('backup',61,169,45,13),('as',112,172,13,7),
            ('New',25,256,27,9),('passphrase',57,255,73,13),('Choose',1164,209,47,10)]
        public_image = Path(temporary)/'public-destination.png'
        from PIL import ImageDraw, ImageFont
        public_font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',13)
        def public_frame(value='',*,caret=False,dim_caret=False):
            pixels = Image.new('RGB',(1280,800),'black')
            draw = ImageDraw.Draw(pixels)
            draw.rectangle((37,196,1115,231),fill='#202020')
            if value:draw.text((37,206),value,font=public_font,fill='white')
            if caret:draw.rectangle((37,206,37,221),fill='white')
            if dim_caret:draw.rectangle((37,207,37,221),fill=(223,223,223))
            pixels.save(public_image)
            return public_image,destination_labels,''
        region = _destination_region(public_frame())
        require(_destination_empty(public_frame(caret=True),region),'Cleared public field and caret were rejected.')
        require(not _destination_empty(public_frame(destination),region),'Nonempty public path was accepted as cleared.')
        Image.new('RGB',(1280,800),'black').save(public_image)
        require(not _destination_empty((public_image,destination_labels,''),region),
                'Unpainted black destination field was accepted as empty.')
        require(region['bounds'][3] < region['new'][1],'Public destination crop overlaps a secret field.')
        checks.append('public-destination-empty-proof-excludes-text-black-frames-and-secret-fields')
        require(not _destination_empty(public_frame(dim_caret=True),region) and
                _destination_observed_dim_caret(public_frame(dim_caret=True),region),
                'Observed gray caret relaxed the unchanged empty proof or failed its narrow transport guard.')
        for value in ('I','l','/media/vault/default.gpg'):
            require(not _destination_observed_dim_caret(public_frame(value,dim_caret=True),region),
                    'Visible public destination text enabled the caret-only focus fallback.')
        for color in ((222,222,222),(224,224,224),(223,222,223)):
            frame = public_frame(dim_caret=True)
            pixels = Image.open(frame[0]).convert('RGB')
            ImageDraw.Draw(pixels).rectangle((37,207,37,221),fill=color);pixels.save(frame[0])
            require(not _destination_observed_dim_caret(frame,region),
                    'An unobserved caret color or ambiguous glyph enabled focus fallback.')
        require(not _destination_observed_dim_caret(public_frame(),region),
                'A normally empty field unnecessarily enabled the dim-caret fallback.')
        checks.append('observed-gray-caret-only-allows-focus-change-without-relaxing-empty-pixel-proof')
        require(_destination_visual_exact(public_frame(destination),region,destination),
                'Raw uppercase-I cap-height recognition rejected the correct public path.')
        for wrong in (destination.replace('VAULT_CI','VAULT_Cl'),destination.replace('VAULT_CI','VAULT_Ci'),
                      destination.replace('VAULT_CI','VAULT_C1'),
                      '/media/vault/'+destination+'Debian/wallet-backup.gpg',
                      destination+'.gpg',destination.replace('ci-gui-live','ci-context-live')):
            require(not _destination_visual_exact(public_frame(wrong),region,destination),
                    'Wrong, ambiguous, concatenated or other public path was accepted.')
        checks.append('public-destination-visual-uppercase-is-distinct-from-lowercase-and-other-paths')
        protect = [('Protect',26,46,89,16),('your',123,50,56,16),('backup',188,46,87,20)]
        confirm = [('Confirm',25,335,49,10),('passphrase',80,335,73,13)]
        gpg_note = [('Encrypt',25,144,49,12),('one',79,146,23,7),('file',107,143,18,10),
                    ('using',131,146,33,10),('GPG.',170,144,26,9)]
        seven_note = [('Supports',422,144,56,12),('files',483,143,26,10),('and',515,143,22,10),
                     ('folders.',543,143,47,10)]
        current = public_frame()
        require(_backup_format_selected((current[0],protect+destination_labels+confirm+gpg_note,''),'gpg') and
                not _backup_format_selected((current[0],protect+destination_labels+confirm+seven_note,''),'gpg') and
                _backup_format_selected((current[0],protect+destination_labels+confirm+seven_note,''),'7z'),
                'Selected-format readiness accepted a stale other-format note.')
        checks.append('format-specific-native-note-must-paint-before-public-entry')
        for phase in ('live','installed'):
            for filename in ('ci-gui-'+phase+'.gpg','ci-gui-'+phase+'.7z',
                             'ci-context-'+phase+'.gpg','ci-gui-'+phase+'-cancel.gpg'):
                fixed_path = '/media/vault/VAULT_CI/'+filename
                require(_destination_visual_exact(public_frame(fixed_path),region,fixed_path),
                        'A fixed public destination was not visually readable: '+filename)
        checks.append('fixed-public-gpg-7z-context-and-cancel-destinations-read-in-live-and-installed-phases')
        class FormatRequestRecorder(IsolatedInputRecorder):
            def __init__(self,wanted,selected='7z'):
                super().__init__();self.wanted=wanted;self.selected=selected;self.entered=False
            def screen(self):
                note = gpg_note if self.selected == 'gpg' else seven_note
                # This merged token is copied from actual native OCR evidence.
                labels = [('7zArchive',47,111,66,10),('GPG',156,112,26,9),
                          ('Encrypted',188,111,64,13),('File',258,111,20,10)]
                rows = protect+labels+destination_labels+confirm+note
                return current[0],rows,' '.join(row[0] for row in rows)
            def call(self,command,**arguments):
                super().call(command,**arguments)
                if arguments['events'][0]['type'] == 'btn' and not arguments['events'][0]['data']['down']:
                    require(self.wanted == 'gpg','Fresh default 7z received a redundant radio click.')
                    self.selected='gpg'
            def words(self,label):return self.screen()
            def key(self,*keys):
                require(keys == ('ret',) and self.entered,'Unexpected input preceded selected-format attestation.')
                self.calls.append(('secret-return-moves-confirm',))
            def text(self,value):
                require(self.entered and value == EXPORT_PHRASES[self.wanted],
                        'Confirm entry preceded format/field readiness.')
                self.calls.append(('masked-confirm-entry',))
        original_replace = globals()['_replace_public_destination']
        original_edit = globals()['_edit_below']
        def attested_replace(vm,screen,destination,*,label):
            require(_backup_format_selected(screen,vm.wanted),'Destination entry preceded selected-format evidence.')
            vm.calls.append(('public-destination-after-format',));return screen
        def attested_secret(vm,label,screen,value):
            require(label == 'New passphrase' and _backup_format_selected(screen,vm.wanted),
                    'Masked passphrase entry preceded selected-format evidence.')
            vm.entered=True;vm.calls.append(('masked-passphrase-after-format',))
        globals()['_replace_public_destination']=attested_replace
        globals()['_edit_below']=attested_secret
        try:
            for format_name in ('7z','gpg'):
                request = FormatRequestRecorder(format_name)
                _fill_backup_request(request,request.screen(),format_name,
                    '/media/vault/VAULT_CI/ci-gui-live.'+format_name,EXPORT_PHRASES[format_name],label='isolated-format')
                qmp = [call for call in request.calls if call[0] == 'input-send-event']
                require(len(qmp) == (3 if format_name == 'gpg' else 0) and request.entered,
                        'Fresh format flow did not use source-backed default or observed GPG selection.')
            unexpected = FormatRequestRecorder('7z',selected='gpg')
            try:_fill_backup_request(unexpected,unexpected.screen(),'7z',
                    '/media/vault/VAULT_CI/ci-gui-live.7z',EXPORT_PHRASES['7z'],label='isolated-unexpected-format')
            except RuntimeError:pass
            else:raise RuntimeError('Fresh 7z flow silently accepted unexpected GPG selection.')
            require(not unexpected.calls and not unexpected.entered,'Unexpected selected format received input.')
        finally:
            globals()['_replace_public_destination']=original_replace
            globals()['_edit_below']=original_edit
        checks.append('fresh-default-7z-and-observed-gpg-selection-integrate-before-entry-unexpected-format-rejects')
        class PublicDestinationRecorder(IsolatedInputRecorder):
            def __init__(self,target=destination):
                super().__init__();self.typed=0;self.cleared_seen=False;self.tabbed=False;self.target=target
            def words(self,label):
                if not self.typed:self.cleared_seen=True;return public_frame(caret=True)
                return public_frame(self.target)
            def text(self,value):
                require(self.cleared_seen and value == self.target,'Public replacement preceded visible clearing.')
                self.typed += 1
                self.calls.append(('typed-public-destination',value))
            def key(self,*keys):
                require(keys == ('tab',) and self.typed == 1,'Destination entry emitted submit or repeated typing.')
                self.tabbed=True;self.calls.append(('key',keys))
        public_vm = PublicDestinationRecorder()
        original_sleep = time.sleep
        time.sleep = lambda seconds:public_vm.calls.append(('settle',seconds))
        try:_replace_public_destination(public_vm,public_frame('/media/vault/Debian/wallet-backup.7z'),
                                        destination,label='isolated-public-replacement')
        finally:time.sleep = original_sleep
        require(public_vm.typed == 1 and public_vm.tabbed and
                public_vm.calls[6][1]['events'][0]['data']['key']['data'] == 'ctrl' and
                public_vm.calls[7] == ('settle',.10) and
                public_vm.calls[8][1]['events'][0]['data']['down'] is False and
                public_vm.calls[9] == ('settle',.15) and
                public_vm.calls[10][1]['events'][0]['data']['key']['data'] == 'backspace' and
                not any(call == ('key',('ret',)) for call in public_vm.calls),
                'Public destination clear/replacement sequence changed or submitted a backup.')
        checks.append('held-public-select-all-backspace-visible-clear-and-exact-value-precede-any-submit')
        # The production GUI test already cancels this fixed unused GPG name.
        # Its public destination must pass the same empty/full-value checks.
        cancel_destination = '/media/vault/VAULT_CI/ci-gui-live-cancel.gpg'
        cancel_vm = PublicDestinationRecorder(cancel_destination)
        time.sleep = lambda seconds:cancel_vm.calls.append(('settle',seconds))
        try:_replace_public_destination(cancel_vm,public_frame('/media/vault/Debian/wallet-backup.7z'),
                                        cancel_destination,label='isolated-native-cancel-destination')
        finally:time.sleep = original_sleep
        require(cancel_vm.typed == 1 and cancel_vm.tabbed,
                'The existing native cancel destination did not pass exact public-entry checks.')
        before = len(cancel_vm.calls)
        try:_replace_public_destination(cancel_vm,public_frame(),
                '/media/vault/VAULT_CI/ci-gui-live-cancel.7z',label='isolated-unapproved-cancel-name')
        except RuntimeError:pass
        else:raise RuntimeError('An unused cancel destination extension was accepted.')
        require(len(cancel_vm.calls) == before,'Rejected public path emitted input.')
        checks.append('existing-fixed-native-cancel-path-uses-same-public-entry-guards')
        class DimCaretDestinationRecorder(PublicDestinationRecorder):
            def __init__(self,*,visible='',sticky=False):
                super().__init__();self.visible=visible;self.sticky=sticky
                self.defocused=False;self.fully_empty_seen=False;self.refocused=False
            def words(self,label):
                self.calls.append(('capture',label))
                if self.typed:return public_frame(self.target)
                if self.defocused and not self.sticky:
                    self.fully_empty_seen=True;return public_frame()
                return public_frame(self.visible,dim_caret=True)
            def key(self,*keys):
                require(keys == ('tab',),'Caret focus fallback emitted a non-Tab key.')
                if not self.typed:
                    require(not self.defocused and not self.fully_empty_seen,
                            'Caret fallback repeated Tab or bypassed its observed failure.')
                    self.defocused=True
                else:self.tabbed=True
                self.calls.append(('key',keys))
            def call(self,command,**arguments):
                if self.defocused and not self.typed:
                    require(self.fully_empty_seen,'Destination refocus preceded fully empty unfocused proof.')
                    if any(event['type'] == 'btn' for event in arguments['events']):self.refocused=True
                super().call(command,**arguments)
            def text(self,value):
                require(self.defocused and self.fully_empty_seen and self.refocused and
                        self.typed == 0 and value == self.target,
                        'Public path typing bypassed defocused proof/refocus or repeated entry.')
                self.typed += 1;self.calls.append(('typed-public-destination',value))
        caret_vm = DimCaretDestinationRecorder()
        original_monotonic = time.monotonic
        fake_clock = [0.0]
        time.monotonic = lambda:fake_clock[0]
        time.sleep = lambda seconds:(fake_clock.__setitem__(0,fake_clock[0]+seconds),
                                   caret_vm.calls.append(('settle',seconds)))
        try:_replace_public_destination(caret_vm,public_frame('/media/vault/Debian/wallet-backup.gpg'),
                                        destination,label='isolated-dim-caret')
        finally:time.sleep=original_sleep;time.monotonic=original_monotonic
        first_tab = caret_vm.calls.index(('key',('tab',)))
        proof_index = caret_vm.calls.index(('capture','isolated-dim-caret-destination-unfocused-empty'))
        typed_index = caret_vm.calls.index(('typed-public-destination',destination))
        refocus = [call for call in caret_vm.calls[proof_index+1:typed_index]
                   if call[0] == 'input-send-event']
        require(caret_vm.typed == 1 and caret_vm.tabbed and first_tab < proof_index < typed_index and
                len(refocus) == 4 and refocus[1][1]['events'][0]['data']['down'] is True and
                refocus[2][1]['events'][0]['data']['down'] is False and
                [event['type'] for event in refocus[3][1]['events']] == ['abs','abs'] and
                not any(call == ('key',('ret',)) for call in caret_vm.calls),
                'Gray-caret transport bypassed full empty proof, settled refocus or one-path/no-submit order.')
        checks.append('dim-caret-defocus-fully-empty-proof-settled-refocus-precede-one-exact-path-entry')
        for visible,sticky in (('/media/vault/default.gpg',False),('',True)):
            rejected = DimCaretDestinationRecorder(visible=visible,sticky=sticky)
            fake_clock = [0.0]
            time.monotonic = lambda:fake_clock[0]
            time.sleep = lambda seconds:fake_clock.__setitem__(0,fake_clock[0]+seconds)
            try:
                try:_replace_public_destination(rejected,public_frame('/media/vault/Debian/wallet-backup.gpg'),
                                                destination,label='isolated-caret-refused')
                except RuntimeError:pass
                else:raise RuntimeError('Text or an unfocused field without empty proof accepted replacement.')
            finally:time.sleep=original_sleep;time.monotonic=original_monotonic
            require(rejected.typed == 0 and not rejected.refocused and
                    sum(call == ('key',('tab',)) for call in rejected.calls) == int(sticky) and
                    not any(call == ('key',('ret',)) for call in rejected.calls),
                    'Rejected gray-caret flow typed, refocused, repeated Tab or submitted.')
        require(public_vm.typed == 1 and
                sum(call == ('key',('tab',)) for call in public_vm.calls) == 1,
                'Previously valid clearing gained a defocus/refocus operation.')
        checks.append('visible-text-or-failed-unfocused-empty-proof-never-refocus-type-or-submit')
        command = 'python3 /media/vault/VAULT_CI/ci-vm-gui-actions.py --guest-check initial --phase live --firmware bios'
        def terminal_frame(buffer='',ambiguous=False):
            rows = [('vault@core-vault:~$',2,48,188,14)]
            left,top = 202,48
            for word in buffer.split():
                w = 6*len(word)
                if left+w > 970:left,top = 2,top+19
                rows.append((word,left,top,w,14));left += w+6
            if ambiguous:rows.append(('vault@core-vault:~$',2,86,188,14))
            return image,rows,' '.join(row[0] for row in rows)
        class TerminalEntryRecorder(IsolatedInputRecorder):
            def __init__(self,always_drop=False):
                super().__init__();self.buffer='';self.typed=0;self.returns=0
                self.always_drop=always_drop;self.echo_seen=False
            def key(self,*keys):
                self.calls.append(('key',keys))
                if keys == ('ctrl','u'):self.buffer='';self.echo_seen=False
                if keys == ('ret',):
                    require(self.echo_seen and self.buffer == command+'  ', 'Return preceded complete verified command echo.')
                    self.returns += 1
            def text(self,value):
                require(value == command+'  ' and '\n' not in value, 'Unexpected or immediately executed command was typed.')
                self.typed += 1;self.buffer=value[1:] if self.typed == 1 or self.always_drop else value
                self.calls.append(('typed-public-command',self.typed))
            def words(self,label):
                if 'command-echo' in label:self.echo_seen=True
                self.calls.append(('captured-echo',self.buffer))
                return terminal_frame(self.buffer)
        terminal = TerminalEntryRecorder()
        _enter_terminal_command(terminal,command,terminal_frame(),label='isolated-drop-first')
        require(terminal.typed == 2 and terminal.returns == 1,
                'A dropped first character was executed or not retried strictly before execution.')
        require(all(command == 'input-send-event' for command,_ in terminal.calls[:4]) and
                terminal.calls[1][1]['events'][0]['type'] == 'btn' and
                terminal.calls[2][1]['events'][0]['type'] == 'btn' and
                [event['type'] for event in terminal.calls[3][1]['events']] == ['abs','abs'] and
                terminal.calls[4] == ('key',('ctrl','e')) and terminal.calls[5] == ('key',('ctrl','u')),
                'Readline entry did not follow focus click, pointer-only parking and clear.')
        parked = terminal.calls[3][1]['events']
        require(parked[1]['data']['value'] > 10000 and
                terminal.calls[1][1]['events'][0]['data']['down'] is True and
                terminal.calls[2][1]['events'][0]['data']['down'] is False,
                'Pointer parking clicked or remained on the prompt echo.')
        checks.append('focus-click-then-pointer-only-parking-precedes-clear-and-command')
        checks.append('dropped-first-character-retyped-before-one-verified-return')
        terminal = TerminalEntryRecorder(always_drop=True)
        try:_enter_terminal_command(terminal,command,terminal_frame(),label='isolated-never-execute')
        except RuntimeError:pass
        else:raise RuntimeError('Unverified command echo was executed.')
        require(terminal.typed == 2 and terminal.returns == 0, 'Bounded echo failures emitted Return.')
        checks.append('bounded-echo-failure-never-executes')
        terminal = TerminalEntryRecorder()
        try:_enter_terminal_command(terminal,command,terminal_frame(ambiguous=True),label='isolated-ambiguous')
        except RuntimeError:pass
        else:raise RuntimeError('Ambiguous shell prompts accepted command entry.')
        require(not terminal.calls, 'An ambiguous body prompt received input.')
        try:_enter_terminal_command(terminal,EXPORT_PHRASES['gpg'],terminal_frame(),label='isolated-secret')
        except RuntimeError:pass
        else:raise RuntimeError('A passphrase was accepted as an echo-diagnostic command.')
        require(not terminal.calls and _shell_failure('bash: ython3: command not found'),
                'Secret/ambiguous entry emitted input or shell failure was missed.')
        checks.append('ambiguous-prompt-and-nonpublic-command-reject-before-input-shell-errors-detected')
        require(shlex.split(command) == shlex.split(command+'  ') and
                shlex.split('/usr/local/bin/core-vault-finish') == shlex.split('/usr/local/bin/core-vault-finish  '),
                'Trailing caret-separation spaces changed public command arguments.')
        caret_image = Path(temporary)/'isolated-caret.png'
        caret_pixels = Image.new('RGB',(1000,800),'black')
        from PIL import ImageDraw
        ImageDraw.Draw(caret_pixels).rectangle((900,45,909,63),fill='white')
        caret_pixels.save(caret_image)
        _,echo_rows,echo_text = terminal_frame(command)
        separated = (caret_image,echo_rows+[('ff',900,45,10,19)],echo_text)
        require(normalized(_terminal_prompt(separated)['echo']) == normalized(command),
                'A separated solid block caret contaminated the complete public echo.')
        merged_rows = [(*row,) for row in echo_rows]
        merged_rows[-1] = ('biosff',*merged_rows[-1][1:])
        require(normalized(_terminal_prompt((image,merged_rows,echo_text))['echo']) != normalized(command),
                'Mixed final-word/caret OCR was silently corrected or ignored.')
        checks.append('trailing-spaces-preserve-argv-isolate-caret-and-retain-mixed-word-negative')
        wrap_image = Path(temporary)/'isolated-observed-terminal-wrap.png'
        Image.new('RGB',(1280,800),'black').save(wrap_image)
        wrap_command = ('python3 /media/vault/VAULT_CI/ci-vm-gui-actions.py '
                        '--guest-check context-intent --phase live --firmware uefi')
        wrap_rows = [('vault@core-vault:~$',2,48,188,14),('python3',202,48,67,15),
                     ('/media/vault/VAULT_CI/ci-vm-gui-actions.py',282,48,418,16),
                     ('--guest-check',714,48,126,15),('context-intent',852,48,137,12),
                     ('--phase',1004,48,66,15),('live',1082,48,38,12),
                     ('--firmware',1134,48,96,12),('ue',1242,51,18,9),
                     ('fi',2,64,49,19),('fl',38,60,16,27)]
        wrapped = (wrap_image,wrap_rows,' '.join(row[0] for row in wrap_rows))
        require(_terminal_wrap_observed(wrapped) and
                normalized(_terminal_prompt(wrapped)['echo']) != normalized(wrap_command),
                'Observed wrap was missed or its mixed caret text was accepted as a complete echo.')
        checks.append('actual-shaped-wrapped-tail-only-enables-transport-and-stays-an-echo-negative')
        for bad_rows in (wrap_rows[:1],wrap_rows[:9],wrap_rows[1:],
                         wrap_rows+[('vault@core-vault:~$',2,105,188,14)],
                         [(*row[:1],row[1] if row[1] < 1000 else row[1]-350,*row[2:])
                          for row in wrap_rows]):
            try:observed = _terminal_wrap_observed((wrap_image,bad_rows,''))
            except RuntimeError:observed = False
            require(not observed,'Unpainted, nonwrapped, ambiguous or non-edge Terminal rows enabled zoom.')
        narrow_image = Path(temporary)/'isolated-narrow-terminal.png'
        Image.new('RGB',(700,800),'black').save(narrow_image)
        require(not _terminal_wrap_observed((narrow_image,wrap_rows,'')) and
                not _terminal_wrap_observed((image,[('Terminal',80,774,70,14)],'')),
                'A narrow viewport or taskbar-only wrong window enabled Terminal zoom.')
        checks.append('terminal-zoom-rejects-wrong-window-narrow-nonwrapped-and-ambiguous-geometry')
        class WrappedTerminalRecorder(IsolatedInputRecorder):
            def __init__(self,*,always_bad=False,geometric_wrap=True,first_exact=False):
                super().__init__();self.buffer='';self.typed=0;self.returns=0
                self.zoomed=False;self.always_bad=always_bad;self.geometric_wrap=geometric_wrap
                self.first_exact=first_exact;self.exact_echo=False;self.empty_seen=False
            def key(self,*keys):
                self.calls.append(('key',keys))
                if keys == ('ctrl','minus'):
                    require(self.typed == 1 and self.returns == 0 and not self.zoomed,
                            'Native Terminal zoom preceded failed first echo or repeated.')
                    self.zoomed=True
                if keys == ('ctrl','u'):
                    self.buffer='';self.empty_seen=False;self.exact_echo=False
                if keys == ('ret',):
                    require(self.exact_echo and self.buffer == wrap_command+'  ' and
                            self.typed == (1 if self.first_exact else 2),
                            'A wrapped command executed before final complete echo verification.')
                    self.returns += 1
            def text(self,value):
                require(value == wrap_command+'  ' and self.empty_seen and self.returns == 0,
                        'Retyping bypassed fresh empty-prompt proof or replayed an executed command.')
                self.buffer=value;self.typed += 1;self.calls.append(('typed-public-command',self.typed))
            def words(self,label):
                self.calls.append(('capture',label))
                if not self.buffer:
                    if 'cleared' in label:self.empty_seen=True
                    return wrap_image,[('vault@core-vault:~$',2,48,188,14)],''
                if self.first_exact or (self.zoomed and not self.always_bad):
                    rows=[('vault@core-vault:~$',2,48,150,12),(wrap_command,166,48,980,12)]
                    if 'command-echo' in label:self.exact_echo=True
                    return wrap_image,rows,wrap_command
                rows=wrap_rows if self.geometric_wrap else wrap_rows[:9]
                return wrap_image,rows,''
        wrapped_vm = WrappedTerminalRecorder()
        time.sleep = lambda seconds:wrapped_vm.calls.append(('settle',seconds))
        try:_enter_terminal_command(wrapped_vm,wrap_command,
                                   (wrap_image,[wrap_rows[0]],''),label='isolated-wrap-zoom')
        finally:time.sleep = original_sleep
        zoom_index = wrapped_vm.calls.index(('key',('ctrl','minus')))
        final_clear = wrapped_vm.calls.index(('capture','isolated-wrap-zoom-cleared-1'))
        final_echo = wrapped_vm.calls.index(('capture','isolated-wrap-zoom-command-echo-1-0'))
        require(wrapped_vm.typed == 2 and wrapped_vm.returns == 1 and
                sum(call == ('key',('ctrl','minus')) for call in wrapped_vm.calls) == 1 and
                zoom_index < final_clear < final_echo < wrapped_vm.calls.index(('key',('ret',))),
                'The conditional zoom added an attempt, skipped fresh empty/echo proof or repeated Return.')
        checks.append('observed-wrap-zooms-once-only-between-first-failure-and-final-empty-exact-echo-return')
        for always_bad,geometric_wrap in ((True,True),(False,False)):
            rejected_vm = WrappedTerminalRecorder(always_bad=always_bad,geometric_wrap=geometric_wrap)
            time.sleep = lambda seconds:rejected_vm.calls.append(('settle',seconds))
            try:
                try:_enter_terminal_command(rejected_vm,wrap_command,
                                            (wrap_image,[wrap_rows[0]],''),label='isolated-wrap-no-execute')
                except RuntimeError:pass
                else:raise RuntimeError('A failed final or nonwrapped echo executed.')
            finally:time.sleep = original_sleep
            require(rejected_vm.typed == 2 and rejected_vm.returns == 0 and
                    sum(call == ('key',('ctrl','minus')) for call in rejected_vm.calls) == int(geometric_wrap),
                    'Final echo failure added an attempt/Return or nonwrapped input triggered zoom.')
        require(not any(call == ('key',('ctrl','minus')) for call in terminal.calls),
                'Original nonwrapped command entry gained a zoom operation.')
        checks.append('failed-final-echo-never-executes-and-nonwrapped-entry-keeps-two-attempt-limit')
        first_vm = WrappedTerminalRecorder(first_exact=True)
        time.sleep = lambda seconds:first_vm.calls.append(('settle',seconds))
        try:_enter_terminal_command(first_vm,wrap_command,
                                   (wrap_image,[wrap_rows[0]],''),label='isolated-first-exact')
        finally:time.sleep = original_sleep
        require(first_vm.typed == 1 and first_vm.returns == 1 and not first_vm.zoomed and
                ('capture','isolated-first-exact-cleared-0') in first_vm.calls and
                ('capture','isolated-first-exact-command-echo-0-0') in first_vm.calls,
                'Successful first-attempt entry gained font zoom, retyping or another Return.')
        checks.append('complete-first-attempt-entry-is-unchanged-without-font-zoom-or-retyping')
        # The actual BIOS empty prompt disappeared from full-frame OCR after
        # the conditional zoom. Exercise the same raster geometry with real
        # crop OCR, then refuse window/grammar/ambiguity and nonempty variants.
        client_image = Path(temporary)/'isolated-zoomed-terminal-client.png'
        client_font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf',13)
        client_title = [('Terminal',24,5,51,10),('vault@core-vault:',91,5,102,10),('~',199,8,7,2)]
        def client_frame(value='vault@core-vault:~$',*,second=None,footer=False,size=(1280,800)):
            pixels = Image.new('RGB',size,'black');draw=ImageDraw.Draw(pixels)
            draw.text((2,44),value,font=client_font,fill='white')
            if second:draw.text((2,84),second,font=client_font,fill='white')
            pixels.save(client_image)
            labels = [('Terminal',80,774,164,12),('vault@core-vault:',148,774,98,12)] if footer else client_title
            return client_image,labels,' '.join(row[0] for row in labels)
        source = client_frame()
        fingerprint = hashlib.sha256(client_image.read_bytes()).hexdigest()
        enlarged = _terminal_client_prompt_ocr(source)
        require(enlarged is not None and _terminal_prompt(enlarged)['echo'] == '' and
                hashlib.sha256(client_image.read_bytes()).hexdigest() == fingerprint,
                'Source-bound enlarged Terminal prompt did not retain an empty exact grammar or raw pixels.')
        metadata = json.loads(client_image.with_name(client_image.stem+'-terminal-client-prompt-4x-psm6.json').read_text())
        require(metadata['raw_screenshot'] == client_image.name and metadata['primary_prompt_absent'] is True and
                metadata['crop'] == [0,44,1264,730], 'Terminal prompt derivative lost its actual raw/client scope.')
        checks.append('absent-primary-terminal-client-crop-reads-exact-empty-prompt-and-preserves-labeled-raw')
        nonempty = _terminal_client_prompt_ocr(client_frame('vault@core-vault:~$ python3 wrong.py'))
        require(nonempty is not None and normalized(_terminal_prompt(nonempty)['echo']) == 'python3wrongpy',
                'Client prompt OCR repaired or concealed a nonempty public command.')
        original_client_ocr = globals()['_terminal_client_prompt_ocr']
        fallback_calls = []
        def forbidden_client_fallback(screen):
            fallback_calls.append(screen);raise RuntimeError('Unexpected fallback for an already recognized prompt.')
        globals()['_terminal_client_prompt_ocr'] = forbidden_client_fallback
        class NonemptyTerminalRecorder:
            def words(self,label):return nonempty
        fake_clock=[0.0];time.monotonic=lambda:fake_clock[0]
        time.sleep=lambda seconds:fake_clock.__setitem__(0,fake_clock[0]+seconds)
        try:
            try:_terminal_screen(NonemptyTerminalRecorder(),'isolated-nonempty-client',timeout=1)
            except RuntimeError as exc:
                require('unique empty client-body prompt' in str(exc),'Nonempty primary used prompt fallback.')
            else:raise RuntimeError('Recognized nonempty Terminal prompt was accepted as ready.')
        finally:
            globals()['_terminal_client_prompt_ocr']=original_client_ocr
            time.monotonic=original_monotonic;time.sleep=original_sleep
        require(not fallback_calls,'A recognized nonempty primary prompt invoked client OCR.')
        require(_terminal_client_prompt_ocr(nonempty) is None,'An existing primary prompt invoked crop OCR.')
        checks.append('nonempty-primary-and-client-command-remain-negative-without-fallback-or-execution')
        for wrong in ('root@core-vault:~$','vault@other-vault:~$','vault@core-vault:~'):
            require(_terminal_client_prompt_ocr(client_frame(wrong)) is None,
                    'Partial or another-user/client prompt passed the unchanged shell grammar.')
        require(_terminal_client_prompt_ocr(client_frame(footer=True)) is None,
                'Taskbar-only Terminal title enabled client prompt OCR.')
        wrong_title = client_frame()
        require(_terminal_client_prompt_ocr((wrong_title[0],[('Bitcoin Core',24,5,102,10)],'')) is None,
                'Another native window enabled Terminal prompt OCR.')
        checks.append('client-prompt-ocr-rejects-partial-foreign-window-and-footer-only-anchors')
        duplicate = client_frame(second='vault@core-vault:~$')
        try:_terminal_client_prompt_ocr(duplicate)
        except RuntimeError:pass
        else:raise RuntimeError('Two crop-recognized shell prompts were accepted.')
        primary_duplicate = client_frame()
        primary_duplicate = (primary_duplicate[0],client_title+
            [('vault@core-vault:~$',2,48,150,14),('vault@core-vault:~$',2,88,150,14)],'')
        try:_terminal_client_prompt_ocr(primary_duplicate)
        except RuntimeError:pass
        else:raise RuntimeError('An ambiguous primary prompt invoked fallback.')
        try:_terminal_client_prompt_ocr(client_frame(size=(700,800)))
        except RuntimeError:pass
        else:raise RuntimeError('An out-of-tested-bounds Terminal client enabled fallback.')
        checks.append('primary-and-crop-prompt-ambiguity-and-outbound-client-refuse-before-input')
        import subprocess
        original_subprocess_run = subprocess.run
        def outside_client_row(*args,**kwargs):
            return subprocess.CompletedProcess(args[0],0,stdout='header\n5\t1\t1\t1\t1\t1\t5055\t0\t100\t52\t99\tvault@core-vault:~$\n')
        subprocess.run=outside_client_row
        try:
            try:_terminal_client_prompt_ocr(client_frame())
            except RuntimeError as exc:require('outside its labeled crop' in str(exc),'Malformed OCR row failed an unrelated guard.')
            else:raise RuntimeError('An out-of-client TSV row enabled prompt fallback.')
        finally:subprocess.run=original_subprocess_run
        checks.append('client-prompt-ocr-refuses-unmapped-out-of-crop-tsv-coordinates')
    tree = ast.parse(Path(__file__).read_text())
    allowed = {'getnetworkinfo','listwallets','getaddressesbylabel','getaddressinfo','getwalletinfo'}
    for node in ast.walk(tree):
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr == 'rpc':
            require(node.args and isinstance(node.args[0],ast.Constant) and node.args[0].value in allowed,
                    'GUI helper added a mutating or unreviewed direct Core RPC action.')
    require(EXPORT_PHRASES == PUBLIC['EXPORT_PHRASES'], 'GUI helper phrases differ from the public synthetic fixture.')
    checks.append('direct-core-rpc-is-observational-and-only-public-fixture-phrases-are-used')
    print(json.dumps({'status':'passed-local-selector-checks','checks':checks,
                      'actual_vm_gui_executed':False,'guest_data_read':False,
                      'real_input_emitted':False},separators=(',',':')))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--guest-check',choices=('initial','exports','unchanged','context-intent','context','no-plaintext','recovery','restore','restore-cleanup','session'))
    action.add_argument('--selector-self-test',action='store_true',help='Local isolated selector and privacy guard checks; no VM GUI acceptance.')
    parser.add_argument('--phase',choices=('live','installed'))
    parser.add_argument('--firmware',choices=('bios','uefi'))
    args = parser.parse_args()
    if args.selector_self_test:
        require(args.phase is None and args.firmware is None, 'Selector checks do not use a guest phase.')
        _selector_self_test()
        return 0
    if args.phase is None or args.firmware is None:
        parser.error('Guest checks require --phase and --firmware.')
    try:
        _guest_check(args.guest_check,args.phase,args.firmware)
    except BaseException as error:
        print('GUI_CHECK_FAIL_'+args.guest_check+'_'+type(error).__name__,flush=True)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
