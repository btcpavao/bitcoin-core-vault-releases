#!/usr/bin/python3
"""Selected-disk BIOS/EFI ownership, bounded metadata and peer boot entries.

Filesystem signatures are cleared only inside fresh, reviewed reservation spans.
EFI and GRUB writes use the mounted, confirmed target. Other disks are inspected
read-only with lsblk/mtype/debugfs; their files are not mounted.
Never import this module to perform writes: finalize() is an explicit entry point.
"""
from __future__ import annotations
import hashlib, json, os, re, shutil, stat, subprocess, sys
from pathlib import Path
from install_plan import (ESP_TYPE, MIN_ROOT, PlanError, require, span, fs,
                          validate_after, verify_reservation, validate_record)
import disk_safety
ENV={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LC_ALL':'C','LANG':'C'}
PRODUCTS={'node':'BitcoinCoreNode','vault':'BitcoinCoreVault'}
META='EFI/BitcoinCore'
BIOS_META='var/lib/bitcoin-core-installer'
MAX_RECORD=65536
MAX_EFI=32*1024**2
T2_ESP_CONFLICT=('This Apple T2 Mac needs its own EFI fallback to boot without NVRAM changes. '
    'The selected EFI partition contains a bootloader belonging to another system or one whose ownership cannot be verified. '
    'In Advanced partitioning, create or select a separate FAT32 EFI system partition on this disk and mount it at /boot/efi. '
    'Keep the existing EFI partition unchanged.')
LSBLK='NAME,KNAME,TYPE,TRAN,RO,RM,SIZE,MOUNTPOINTS,SERIAL,WWN,MODEL,MAJ:MIN,LOG-SEC,PTTYPE,PTUUID,FSTYPE,PARTUUID,PARTLABEL,PARTTYPE,UUID'


def bounded_json(data):
    require(isinstance(data,(bytes,str)) and len(data)<=MAX_RECORD, 'Installation metadata exceeds the size limit.')
    def unique(pairs):
        result={}
        for key,value in pairs:
            require(key not in result,'Duplicate installation metadata key.')
            result[key]=value
        return result
    value=json.loads(data,object_pairs_hook=unique)
    require(isinstance(value,dict) and type(value.get('schema')) is int and value.get('schema') in (1,2), 'Unsupported installation metadata schema.')
    return value


def direct_filesystem(device):
    require(re.fullmatch(r'/dev/[A-Za-z0-9]+',device),'Invalid partition path.')
    result=subprocess.run(['/usr/sbin/blkid','--probe','--output','export',device],
        capture_output=True,text=True,timeout=5,env=ENV)
    require(result.returncode in (0,2),'A partition signature could not be read reliably.')
    fields=dict(line.split('=',1) for line in result.stdout.splitlines() if '=' in line)
    return fields.get('TYPE','').lower(),fields.get('UUID','')


def disk_layout(device):
    """Inspect the mounted target after jobs; this is NOT an eligibility bypass."""
    require(re.fullmatch(r'/dev/(?:sd[a-z]+|hd[a-z]+|nvme\d+n\d+|vd[a-z]+)',device), 'Invalid disk path.')
    st=os.stat(device);require(stat.S_ISBLK(st.st_mode),'Target is not a block device.')
    data=subprocess.check_output(['/usr/bin/lsblk','--json','--bytes','--paths','--output',LSBLK,device],timeout=10,env=ENV)
    nodes=json.loads(data)['blockdevices'];require(len(nodes)==1,'Ambiguous disk identity.')
    node=nodes[0];require(node['name']==device and node['type']=='disk','Not the selected physical disk.')
    result={
        'name':device,'size':int(node['size']),'major_minor':node.get('maj:min',''),
        'serial':(node.get('serial') or '').strip(),'wwn':(node.get('wwn') or '').strip(),
        'model':(node.get('model') or '').strip(),
        'sysfs':str((Path('/sys/class/block')/Path(device).name).resolve(strict=True)),
        'logical_size':int(node.get('log-sec') or 512),'pttype':node.get('pttype') or '',
        'ptuuid':node.get('ptuuid') or '', 'partitions':[]}
    require(result['major_minor']==f'{os.major(st.st_rdev)}:{os.minor(st.st_rdev)}','Disk changed while inspecting it.')
    # Share the initial probe's partition geometry. MBR extended partitions have
    # an lsblk/sysfs size of only the EBR sector on some kernels; sfdisk is the
    # authoritative source for their containing span. Mounted-target inspection
    # never calls (or bypasses) the earlier disk eligibility decision.
    result['partitions']=disk_safety.partition_layout(device,node)
    for part in result['partitions']:
        if part.get('extended'):
            part['fs']='';part['fsuuid']=''
        else:
            part['fs'],part['fsuuid']=direct_filesystem(part['path'])
    return result


def read_bounded(command, limit=MAX_RECORD):
    """Bound a read-only helper's output before processing untrusted bytes."""
    require(type(limit) is int and 0 < limit <= MAX_EFI,'Invalid bounded read size.')
    process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,env=ENV)
    try:
        result=subprocess.run(['/usr/bin/head','-c',str(limit+1)],stdin=process.stdout,
            capture_output=True,check=True,timeout=5,env=ENV)
        process.stdout.close()
        if len(result.stdout)>limit:return None
        if process.wait(timeout=2)!=0:return None
        return result.stdout
    except (OSError,ValueError,RecursionError,subprocess.SubprocessError):return None
    finally:
        if process.poll() is None:process.kill()
        process.wait(timeout=2)


def read_record(command, kind):
    data=read_bounded(command)
    if data is None:return None
    try:return validate_record(bounded_json(data),kind)
    except (ValueError,RecursionError,KeyError,TypeError):return None


def t2_model():
    """Use the same exact DMI detection as Live boot and target configuration."""
    if '/usr/lib/core-vault' not in sys.path:
        sys.path.insert(0,'/usr/lib/core-vault')
    from t2_hardware import detect_t2
    return detect_t2()


def esp_fallback_exists(esp):
    """Inspect FAT directories read-only, distinguishing absence from read errors."""
    require(re.fullmatch(r'/dev/[A-Za-z0-9]+',esp),'Invalid EFI device path.')
    directory='::/'
    for index, component in enumerate(('EFI','BOOT','BOOTX64.EFI')):
        listing=read_bounded(['/usr/bin/mdir','-a','-b','-f','-i',esp,directory])
        require(listing is not None,
                'The selected EFI partition could not be inspected safely. Select a separate FAT32 EFI system partition.')
        matches=[entry for entry in listing.splitlines()
                 if entry.rstrip(b'/').rsplit(b'/',1)[-1].lower()==component.lower().encode('ascii')]
        if not matches:return False
        require(len(matches)==1,'Ambiguous path on the selected EFI partition.')
        if index<2:
            require(matches[0].endswith(b'/'),'Invalid EFI directory on the selected partition.')
            directory+=component+'/'
        else:
            require(not matches[0].endswith(b'/'),'The existing EFI fallback is not a file.')
    return True


def validate_t2_efi_plan(plan, current, intent):
    """Run after validate_plan, before partition writes or confirmation recording.

    Apple firmware discovers the fallback path on each ESP. A foreign fallback
    must be preserved, so a T2 installation then needs a separate selected ESP.
    This preflight reads the old FAT filesystem without mounting it.
    """
    if plan.get('product')!='vault' or plan.get('firmware')!='efi' or not t2_model():return
    esp=intent['esp']
    if esp['new']:return
    originals=[p for p in current['partitions'] if p['path']==esp['path'] and span(p)==span(esp)]
    require(len(originals)==1,'The selected EFI partition identity changed.')
    original=originals[0]
    if not esp_fallback_exists(original['path']):return
    owner=read_record(['/usr/bin/mtype','-i',original['path'],'::/'+META+'/fallback-owner.json'],'fallback')
    require(owner and owner.get('product')=='vault' and owner.get('esp_partuuid')==original['partuuid'],T2_ESP_CONFLICT)
    image=read_bounded(['/usr/bin/mtype','-i',original['path'],'::/EFI/BOOT/BOOTX64.EFI'],MAX_EFI)
    require(image is not None and 1024<len(image)<MAX_EFI and image[:2]==b'MZ'
            and hashlib.sha256(image).hexdigest()==owner['sha256'],T2_ESP_CONFLICT)


def bios_peer_location(identity, root_partition):
    """Resolve a peer's optional separate /boot from its own bounded fstab.

    Only an unambiguous same-disk ext4 UUID reference is accepted. Nothing is
    mounted, and no arbitrary file path from the existing system is executed.
    """
    data=read_bounded(['/usr/sbin/debugfs','-R','cat /etc/fstab',root_partition['path']])
    require(data is not None,'The peer filesystem table could not be read.')
    entries=[]
    for line in data.decode('utf-8',errors='strict').splitlines():
        columns=line.split('#',1)[0].split()
        if len(columns)>=2 and columns[1]=='/boot':entries.append(columns)
    if not entries:return dict(uuid=root_partition['fsuuid'],path='/boot/grub/grub.cfg')
    require(len(entries)==1 and len(entries[0])>=4 and entries[0][2]=='ext4'
            and entries[0][0].startswith('UUID='),'Unsupported peer /boot reference.')
    uuid=entries[0][0][5:]
    require(re.fullmatch(r'[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}',uuid),
            'Unsafe peer /boot UUID.')
    boots=[p for p in identity['partitions'] if p.get('fsuuid')==uuid and fs(p)=='ext4' and not p.get('extended')]
    require(len(boots)==1 and boots[0]['path']!=root_partition['path'],'Peer /boot is not an unambiguous separate same-disk partition.')
    return dict(uuid=uuid,path='/grub/grub.cfg')


def read_esp_record(esp, filename):
    """Read an existing schema-1 EFI record without mounting the FAT filesystem."""
    require(filename in ('installed-node.json','installed-vault.json','reserved-node.json','reserved-vault.json'),
            'Unsupported EFI metadata path.')
    require(re.fullmatch(r'/dev/[A-Za-z0-9]+',esp),'Invalid EFI device path.')
    record=read_record(['/usr/bin/mtype','-i',esp,'::/'+META+'/'+filename],
        'reserved' if filename.startswith('reserved-') else 'installed')
    return record if record and record['schema']==1 else None


def read_bios_record(root_device, filename):
    """debugfs defaults to read-only: no mount and no journal replay occur."""
    require(filename in ('installed-node.json','installed-vault.json','reserved-node.json','reserved-vault.json'),
            'Unsupported BIOS metadata path.')
    require(re.fullmatch(r'/dev/[A-Za-z0-9]+',root_device),'Invalid BIOS root device path.')
    record=read_record(['/usr/sbin/debugfs','-R','cat /'+BIOS_META+'/'+filename,root_device],
        'reserved' if filename.startswith('reserved-') else 'installed')
    return record if record and record['schema']==2 and record.get('firmware')=='bios' else None


def installed_bios_peer(record, product, identity, root_partition):
    validate_record(record,'installed')
    require(record['schema']==2 and record.get('firmware')=='bios' and record['product']==product,
            'Unverified BIOS peer product.')
    require(record.get('table_type')==identity['pttype'], 'Peer partition table differs.')
    require(record.get('serial')==identity['serial'] and record.get('wwn')==identity['wwn']
            and record.get('disk_guid','').lower()==identity['ptuuid'].lower(),'Peer disk identity differs.')
    require(record.get('boot_id')==PRODUCTS[product],'Unexpected peer boot identity.')
    require(record.get('root_partuuid','').lower()==root_partition.get('partuuid','').lower()
            and fs(root_partition)=='ext4' and record.get('root_fsuuid')==root_partition.get('fsuuid'),
            'Peer metadata is not on its recorded root partition.')
    return dict(product=product,firmware='bios',**bios_peer_location(identity,root_partition))


def legacy_node_peer(identity, root_partition):
    """Recognize pre-metadata Node installs; this is not hardware-bound history.

    Old BIOS Node wrote only an explicit installed marker. Read that marker and
    match its fstab to the actual root before offering a fixed GRUB config path.
    No replacement metadata is written and no old filesystem is mounted.
    """
    require(fs(root_partition)=='ext4' and not root_partition.get('extended'),
            'Legacy Node requires an ordinary ext4 root.')
    device=root_partition['path']
    require(re.fullmatch(r'/dev/[A-Za-z0-9]+',device),'Invalid legacy Node device.')
    def read(name,limit=MAX_RECORD):
        return read_bounded(['/usr/sbin/debugfs','-R','cat '+name,device],limit)
    marker=read('/etc/bitcoin-core-node/installed',128)
    require(marker==b'Bitcoin Core Node development installation\n','No legacy Node installation marker.')
    # Read the canonical regular file; /etc/os-release may be a symlink and
    # debugfs cat does not provide normal mounted-filesystem path semantics.
    release=read('/usr/lib/os-release',8192)
    require(release is not None,'Legacy Node OS identity is unreadable.')
    release=release.decode('utf-8',errors='strict')
    require(re.search(r'^ID=(?:debian|"debian")$',release,re.M)
            and re.search(r'^VERSION_ID=(?:13|"13")$',release,re.M),
            'Legacy Node requires the expected Debian 13 identity.')
    data=read('/etc/fstab')
    require(data is not None,'Legacy Node filesystem table is unreadable.')
    roots=[]
    for line in data.decode('utf-8',errors='strict').splitlines():
        fields=line.split('#',1)[0].split()
        if len(fields)>=2 and fields[1]=='/':roots.append(fields)
    require(len(roots)==1 and len(roots[0])>=4 and roots[0][2]=='ext4'
            and roots[0][0]=='UUID='+root_partition.get('fsuuid',''),
            'Legacy Node root UUID does not match the inspected partition.')
    require(re.fullmatch(r'[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}',root_partition.get('fsuuid','')),
            'Invalid legacy Node root UUID.')
    return dict(product='node',firmware='bios',discovery='legacy-installed-marker',
                **bios_peer_location(identity,root_partition))


def verified_reservations(device, product):
    require(product in PRODUCTS,'Unknown reservation product.')
    identity=disk_safety.probe(device)
    output=[]
    records=[]
    owner='vault' if product=='node' else 'node'
    for part in identity['partitions']:
        if part['parttype'].lower()==ESP_TYPE and fs(part)=='fat32':
            record=read_esp_record(part['path'],'reserved-'+product+'.json')
            if record:records.append(record)
        elif fs(part)=='ext4':
            installed=read_bios_record(part['path'],'installed-'+owner+'.json')
            if not installed:continue
            try:installed_bios_peer(installed,owner,identity,part)
            except (ValueError,KeyError,TypeError):continue
            record=read_bios_record(part['path'],'reserved-'+product+'.json')
            if record:records.append(record)
    for record in records:
        for part in identity['partitions']:
            if part.get('extended'):continue
            try:verify_reservation(record,product,identity,part)
            except (ValueError,KeyError,TypeError):continue
            output.append(dict(path=part['path'],first=part['first'],size=part['size'],partuuid=part['partuuid']))
    # Contradicting records never select a partition automatically.
    unique={p['partuuid']:p for p in output}
    return list(unique.values()) if len(unique)==1 else []


def installed_peer(record, product, identity, esp, firmware='efi'):
    validate_record(record,'installed')
    require(record['product']==product,'Unverified peer product.')
    require(record.get('serial')==identity['serial'] and record.get('wwn')==identity['wwn']
            and record.get('disk_guid')==identity['ptuuid'],'Peer disk identity differs.')
    require(record.get('esp_partuuid')==esp['partuuid'] and record.get('esp_fsuuid')==esp['fsuuid'],'Peer EFI identity differs.')
    require(record.get('boot_id')==PRODUCTS[product],'Unexpected peer boot path.')
    roots=[p for p in identity['partitions'] if p['partuuid']==record.get('root_partuuid')]
    require(len(roots)==1 and fs(roots[0])=='ext4' and roots[0]['fsuuid']==record.get('root_fsuuid'),'Peer root identity differs.')
    require(re.fullmatch(r'[0-9A-Fa-f-]{4,64}',esp['fsuuid']),'Unsafe EFI filesystem UUID.')
    if firmware=='bios':
        return dict(product=product,firmware='bios',**bios_peer_location(identity,roots[0]))
    return dict(product=product,uuid=esp['fsuuid'],path='/EFI/'+PRODUCTS[product]+'/grubx64.efi')


def discover_peers(product, own_identity, firmware='efi', own_root_uuid=''):
    other='vault' if product=='node' else 'node'; output=[]
    rows=json.loads(subprocess.check_output(['/usr/bin/lsblk','--json','--bytes','--paths','--nodeps','--output','NAME,TYPE'],timeout=5,env=ENV))['blockdevices']
    for row in rows:
        if row.get('type')!='disk':continue
        try:identity=own_identity if row['name']==own_identity['name'] else disk_safety.probe(row['name'])
        except (OSError,ValueError,subprocess.SubprocessError):continue
        for part in identity['partitions']:
            if part['parttype'].lower()==ESP_TYPE and fs(part)=='fat32':
                record=read_esp_record(part['path'],'installed-'+other+'.json')
                if not record:continue
                try:output.append(installed_peer(record,other,identity,part,firmware))
                except (ValueError,KeyError,TypeError):continue
            elif firmware=='bios' and fs(part)=='ext4' and part.get('fsuuid')!=own_root_uuid:
                record=read_bios_record(part['path'],'installed-'+other+'.json')
                if record:
                    try:output.append(installed_bios_peer(record,other,identity,part))
                    except (ValueError,KeyError,TypeError):pass
                    continue
                if other=='node':
                    # Compatibility only: old BIOS Node has no serial/WWN record.
                    # A matching marker and fstab may add a menu entry, never
                    # confer reservation ownership or select the default OS.
                    try:output.append(legacy_node_peer(identity,part))
                    except (ValueError,KeyError,TypeError):continue
    return list({(p['product'],p['uuid']):p for p in output}.values())


def grub_peer_script(peers):
    """Data is restricted to fixed product paths and validated FAT UUIDs."""
    text='#!/bin/sh\nexec tail -n +3 "$0"\n# Bitcoin Core: chainload only explicit EFI paths. No OS filesystem probing.\n'
    if peers:text+='insmod part_gpt\ninsmod fat\ninsmod search_fs_uuid\n'
    for peer in peers:
        require(peer.get('product') in PRODUCTS and re.fullmatch(r'[0-9A-Fa-f-]{4,64}',peer.get('uuid','')),'Unsafe boot entry.')
        name='Bitcoin Core '+peer['product'].title();path='/EFI/'+PRODUCTS[peer['product']]+'/grubx64.efi'
        text+=f"if search --no-floppy --fs-uuid --set=core_peer {peer['uuid']}; then\n"
        text+=f"  if [ -f ($core_peer){path} ]; then\n"
        text+=f"    menuentry '{name}' --class gnu-linux --id core-{peer['product']}-{peer['uuid']} {{\n"
        text+="      insmod part_gpt\n      insmod fat\n      insmod chain\n"
        text+=f"      search --no-floppy --fs-uuid --set=root {peer['uuid']}\n      chainloader {path}\n    }}\n  fi\nfi\n"
    return text


def grub_bios_peer_script(peers):
    """Load only a validated peer root's GRUB configuration, never its MBR."""
    text='#!/bin/sh\nexec tail -n +3 "$0"\n# Bitcoin Core: validated BIOS peer locations; no OS filesystem mounts.\n'
    if peers:text+='insmod part_gpt\ninsmod part_msdos\ninsmod ext2\ninsmod search_fs_uuid\n'
    for peer in peers:
        require(peer.get('product') in PRODUCTS and re.fullmatch(r'[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}',peer.get('uuid','')),
                'Unsafe BIOS boot entry.')
        if peer.get('discovery')=='legacy-installed-marker':
            text+='# Legacy Node compatibility: installed marker and root/boot UUIDs, without historical disk metadata.\n'
        name='Bitcoin Core '+peer['product'].title();uuid=peer['uuid'];path=peer.get('path','/boot/grub/grub.cfg')
        require(path in ('/boot/grub/grub.cfg','/grub/grub.cfg'),'Unsafe BIOS configuration path.')
        text+=f"if search --no-floppy --fs-uuid --set=core_peer {uuid}; then\n"
        text+=f"  if [ -f ($core_peer){path} ]; then\n"
        text+=f"    menuentry '{name}' --class gnu-linux --id core-{peer['product']}-{uuid} {{\n"
        text+="      insmod part_gpt\n      insmod part_msdos\n      insmod ext2\n      insmod configfile\n"
        text+=f"      search --no-floppy --fs-uuid --set=root {uuid}\n"
        text+=f"      configfile ($root){path}\n    }}\n  fi\nfi\n"
    return text


def safe(root, name):
    path=root/name
    require(path.resolve(strict=False).is_relative_to(root),'Path escapes the installation target.')
    return path


def write_json(path,value):
    kind='reserved' if path.name.startswith('reserved-') else 'installed' if path.name.startswith('installed-') else 'fallback'
    validate_record(value,kind)
    data=(json.dumps(value,sort_keys=True,indent=2)+'\n').encode()
    require(len(data)<=MAX_RECORD,'Generated installation metadata exceeds the limit.')
    require(not path.is_symlink(),'Refusing an installation metadata symlink.')
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.new')
    fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    try:
        with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
        os.replace(temporary,path)
    finally:temporary.unlink(missing_ok=True)


def mounted_source(path):
    value=json.loads(subprocess.check_output(['/usr/bin/findmnt','--json','--mountpoint',str(path),'--output','TARGET,SOURCE,FSTYPE'],timeout=5,env=ENV))['filesystems']
    require(len(value)==1 and value[0]['target']==str(path),'Expected a separate mounted target.')
    return value[0]['source'].split('[')[0],value[0]['fstype']


def confirmed_plan():
    require(os.geteuid()==0 and 'boot=live' in Path('/proc/cmdline').read_text().split(),
            'Reservation jobs require the Live installer root context.')
    record=Path('/run/core-installer/confirmed-plan.json');directory=record.parent.lstat()
    require(stat.S_ISDIR(directory.st_mode) and directory.st_uid==0 and not directory.st_mode&0o077,'Untrusted installer runtime directory.')
    st=record.lstat()
    require(stat.S_ISREG(st.st_mode) and st.st_uid==0 and not st.st_mode&0o077 and st.st_size<=1024*1024,
            'Untrusted installation plan record.')
    return json.loads(record.read_text())


def prepare_reservations():
    """Clear signatures only in fresh reviewed reservations/BIOS areas, before mounts.

    KPM intentionally leaves Unformatted partition contents alone. A previous
    filesystem signature in otherwise unallocated sectors must not turn a new
    reserved slot or BIOS embedding area into an apparent filesystem. Existing
    BIOS embedding areas and all other preserved partitions stay untouched here.
    """
    from copy import deepcopy
    from install_plan import validate_plan
    plan=confirmed_plan();intent=validate_plan(plan,plan['expected'])
    fresh=list(intent['reserved'])
    bios=intent.get('bios_grub')
    if bios and bios.get('new'):fresh.append(bios)
    if not fresh:return
    # Eligibility again rejects every mounted/live/swap/held/removable device.
    current=disk_safety.probe(plan['target']);permitted={span(p) for p in fresh}
    normalized=deepcopy(current)
    for part in normalized['partitions']:
        if span(part) in permitted:part['fs']='';part['fsuuid']=''
    validated=validate_after(plan,normalized)
    prepared=list(validated['reserved'])
    bios=validated.get('bios_grub')
    if bios and span(bios) in permitted:prepared.append(bios)
    for part in prepared:
        require(span(part) in permitted and part['partuuid'],'Fresh raw partition identity is missing.')
        signature,_=direct_filesystem(part['path'])
        if signature:
            subprocess.run(['/usr/sbin/wipefs','--all','--force','--',part['path']],
                check=True,capture_output=True,text=True,timeout=30,env=ENV)
        signature,_=direct_filesystem(part['path'])
        require(not signature,'The reviewed raw partition still contains a filesystem signature.')


def bounded_efi_hash(path):
    st=path.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_size>MAX_EFI:return None
    digest=hashlib.sha256();count=0
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):
            count+=len(chunk)
            if count>MAX_EFI:return None
            digest.update(chunk)
    return digest.hexdigest()


def fallback_is_owned(esp_root, product, esp):
    """Only a same-product, same-ESP record with exact current bytes owns a file."""
    fallback=safe(esp_root,'EFI/BOOT/BOOTX64.EFI')
    owner=safe(esp_root,META+'/fallback-owner.json')
    if not fallback.is_file() or fallback.is_symlink() or fallback.stat().st_size>MAX_EFI:return False
    if not owner.is_file() or owner.is_symlink() or owner.stat().st_size>MAX_RECORD:return False
    try:
        with owner.open('rb') as stream:raw=stream.read(MAX_RECORD+1)
        prior=validate_record(bounded_json(raw),'fallback')
        return (prior.get('product')==product and prior.get('esp_partuuid')==esp['partuuid']
                and prior.get('sha256')==bounded_efi_hash(fallback))
    except (ValueError,RecursionError):return False


def install_owned_fallback(esp_root, loader, product, esp):
    """Create fallback, or refresh only a byte-verified fallback we already own."""
    fallback=safe(esp_root,'EFI/BOOT/BOOTX64.EFI')
    owner=safe(esp_root,META+'/fallback-owner.json')
    replace=False
    if fallback.exists():
        require(fallback.is_file() and not fallback.is_symlink(),'Invalid existing EFI fallback.')
        replace=fallback_is_owned(esp_root,product,esp)
        if not replace:return fallback
    else:
        require(not fallback.is_symlink(),'Invalid EFI fallback symlink.')
    fallback.parent.mkdir(parents=True,exist_ok=True)
    temporary=fallback.with_name('BOOTX64.EFI.new')
    try:
        with loader.open('rb') as src, temporary.open('xb') as dst:
            shutil.copyfileobj(src,dst);dst.flush();os.fsync(dst.fileno())
        # The existing file is replaceable only after exact owner/hash checks.
        if replace:os.replace(temporary,fallback)
        else:
            # Link is unsupported on FAT; use exclusive creation, preserving any
            # concurrently created fallback rather than overwriting it.
            with temporary.open('rb') as src, fallback.open('xb') as dst:shutil.copyfileobj(src,dst)
    finally:temporary.unlink(missing_ok=True)
    write_json(owner,dict(schema=1,product=product,esp_partuuid=esp['partuuid'],
        sha256=bounded_efi_hash(fallback)))
    return fallback


def finalize_bios(root,product,plan,identity,intent):
    """The native bootloader job has already installed i386-pc to the disk.

    Store identity records only in our mounted root. BIOS boot has one MBR per
    disk; the later installation's GRUB menu can load a verified earlier root.
    A blank reservation is never guessed from a label or unknown future UUID.
    """
    modules=safe(root,'boot/grub/i386-pc')
    require(modules.is_dir() and (modules/'normal.mod').is_file(),
            'The BIOS bootloader modules are missing from the installed root.')
    record=dict(schema=2,firmware='bios',table_type=identity['pttype'],product=product,
        serial=identity['serial'],wwn=identity['wwn'],disk_guid=identity['ptuuid'],
        root_partuuid=intent['root']['partuuid'],root_fsuuid=intent['root']['fsuuid'],boot_id=PRODUCTS[product])
    write_json(safe(root,BIOS_META+'/installed-'+product+'.json'),record)
    other='vault' if product=='node' else 'node'
    for reserved in intent['reserved']:
        require(not fs(reserved) and reserved['size']>=MIN_ROOT[other],'Companion reservation is not unformatted.')
        reservation=dict(schema=2,firmware='bios',table_type=identity['pttype'],product=other,
            serial=identity['serial'],wwn=identity['wwn'],disk_guid=identity['ptuuid'],
            partuuid=reserved['partuuid'],first=reserved['first'],size=reserved['size'])
        write_json(safe(root,BIOS_META+'/reserved-'+other+'.json'),reservation)
    peers=discover_peers(product,identity,'bios',intent['root']['fsuuid'])
    script=safe(root,'etc/grub.d/41_bitcoin_core_peer');script.parent.mkdir(parents=True,exist_ok=True)
    require(not script.is_symlink(),'Unsafe GRUB script path.')
    script.write_text(grub_bios_peer_script(peers));script.chmod(0o755)
    config=safe(root,'etc/default/grub.d/zz-bitcoin-core-boot-menu.cfg');config.parent.mkdir(parents=True,exist_ok=True)
    require(not config.is_symlink(),'Unsafe GRUB configuration path.')
    menu=('GRUB_TIMEOUT_STYLE=menu\nGRUB_TIMEOUT=8\n' if peers else 'GRUB_TIMEOUT_STYLE=hidden\nGRUB_TIMEOUT=0\n')
    config.write_text(menu+'GRUB_DISABLE_OS_PROBER=true\n')
    subprocess.run(['/usr/sbin/chroot',str(root),'/usr/sbin/grub-mkconfig','-o','/boot/grub/grub.cfg'],check=True,timeout=180,env=ENV)


def finalize(root,product):
    require(product in PRODUCTS and os.geteuid()==0,'Invalid installation context.')
    root=Path(root)
    require(root.is_absolute() and root!=Path('/') and root.resolve()==root and os.path.ismount(root),'Not a separate installation target.')
    require('boot=live' in Path('/proc/cmdline').read_text().split(),'The boot finalizer only runs from the Live installer.')
    plan=confirmed_plan();require(plan['product']==product,'Installation product mismatch.')
    identity=disk_layout(plan['target']);intent=validate_after(plan,identity)
    source,fstype=mounted_source(root)
    require(source==intent['root']['path'] and fstype=='ext4','Mounted root is not the confirmed partition.')
    if plan['firmware']=='bios':
        finalize_bios(root,product,plan,identity,intent)
        return
    esp=intent['esp'];esp_root=safe(root,'boot/efi');source,fstype=mounted_source(esp_root)
    require(source==esp['path'] and fstype in ('vfat','fat32'),'Mounted EFI is not the confirmed partition.')
    t2=product=='vault' and t2_model()
    existing_fallback=safe(esp_root,'EFI/BOOT/BOOTX64.EFI')
    if t2 and (existing_fallback.exists() or existing_fallback.is_symlink()):
        require(fallback_is_owned(esp_root,product,esp),T2_ESP_CONFLICT)
    loader=safe(esp_root,'EFI/'+PRODUCTS[product]+'/grubx64.efi')
    require(loader.is_file() and not loader.is_symlink() and 1024<loader.stat().st_size<32*1024**2,'The product EFI loader is missing or invalid.')
    with loader.open('rb') as f:require(f.read(2)==b'MZ','The product EFI loader is not a PE image.')
    record=dict(schema=1,product=product,serial=identity['serial'],wwn=identity['wwn'],disk_guid=identity['ptuuid'],
        root_partuuid=intent['root']['partuuid'],root_fsuuid=intent['root']['fsuuid'],
        esp_partuuid=esp['partuuid'],esp_fsuuid=esp['fsuuid'],boot_id=PRODUCTS[product])
    write_json(safe(esp_root,META+'/installed-'+product+'.json'),record)
    other='vault' if product=='node' else 'node'
    for reserved in intent['reserved']:
        require(not fs(reserved) and reserved['size']>=MIN_ROOT[other],'Companion reservation is not unformatted.')
        reservation=dict(schema=1,product=other,serial=identity['serial'],wwn=identity['wwn'],disk_guid=identity['ptuuid'],
            partuuid=reserved['partuuid'],first=reserved['first'],size=reserved['size'])
        write_json(safe(esp_root,META+'/reserved-'+other+'.json'),reservation)
    fallback=install_owned_fallback(esp_root,loader,product,esp)
    if t2:
        require(fallback_is_owned(esp_root,product,esp)
                and bounded_efi_hash(fallback)==bounded_efi_hash(loader),
                'The Apple T2 EFI fallback does not match the installed Vault loader.')
    peers=discover_peers(product,identity)
    # A same-ESP reservation gains a menu entry automatically once the peer is
    # installed. The first system's root/GRUB never needs to be modified later.
    if intent['reserved'] and not any(p['uuid']==esp['fsuuid'] for p in peers):
        peers.append(dict(product=other,uuid=esp['fsuuid']))
    script=safe(root,'etc/grub.d/41_bitcoin_core_peer');script.parent.mkdir(parents=True,exist_ok=True)
    require(not script.is_symlink(),'Unsafe GRUB script path.');script.write_text(grub_peer_script(peers));script.chmod(0o755)
    config=safe(root,'etc/default/grub.d/zz-bitcoin-core-boot-menu.cfg');config.parent.mkdir(parents=True,exist_ok=True)
    require(not config.is_symlink(),'Unsafe GRUB configuration path.')
    menu=('GRUB_TIMEOUT_STYLE=menu\nGRUB_TIMEOUT=8\n' if peers else 'GRUB_TIMEOUT_STYLE=hidden\nGRUB_TIMEOUT=0\n')
    config.write_text(menu+'GRUB_DISABLE_OS_PROBER=true\n')
    subprocess.run(['/usr/sbin/chroot',str(root),'/usr/sbin/grub-mkconfig','-o','/boot/grub/grub.cfg'],check=True,timeout=180,env=ENV)
    # Check existence, not a hardcoded EFI ID shared with another product.
    require(loader.is_file() and fallback.is_file(),'EFI boot files disappeared during finalization.')
