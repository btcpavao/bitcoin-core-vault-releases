#!/usr/bin/python3
"""Read-only disk eligibility/identity check. Does not partition or unmount."""
from __future__ import annotations
import json, os, re, stat, subprocess, sys
from pathlib import Path

MIN_BYTES = 16 * 1024**3
class UnsafeDisk(ValueError): pass

def walk(node):
    yield node
    for child in node.get('children', []): yield from walk(child)

def flag(value):
    return value is True or str(value).lower() in ('1','true','yes')

def external_bus(syspath):
    # An external NVMe controller can report the same transport as an internal
    # one. The PCI port or one of its bridges can carry the removable marker.
    for parent in Path(syspath).parents:
        subsystem = parent / 'subsystem'
        if not subsystem.is_symlink():
            continue
        bus = subsystem.resolve(strict=True).name
        if bus in ('usb', 'firewire', 'thunderbolt'):
            return True
        if bus == 'pci':
            for attribute, external in (('removable', 'removable'), ('untrusted', '1')):
                try:
                    if (parent / attribute).read_text().strip() == external:
                        return True
                except FileNotFoundError:
                    continue
    return False


def validate_tree(node, syspath, holders, active_swaps):
    name = node.get('name', '')
    if not re.fullmatch(r'/dev/(?:sd[a-z]+|hd[a-z]+|nvme\d+n\d+|vd[a-z]+)', name):
        raise UnsafeDisk('Only whole internal SATA/NVMe or virtual test disks are supported.')
    if node.get('type') != 'disk': raise UnsafeDisk('Not a whole disk.')
    if flag(node.get('ro')) or flag(node.get('rm')): raise UnsafeDisk('Read-only or removable device.')
    transport = (node.get('tran') or '').lower()
    if (transport in ('usb', 'sbp', 'mmc', 'firewire', 'iscsi', 'fc', 'tcp', 'rdma')
            or re.search(r'/usb\d*(?:/|$)', syspath) or external_bus(syspath)):
        raise UnsafeDisk('External/removable/network storage is not an installation target.')
    if int(node.get('size',0)) < MIN_BYTES: raise UnsafeDisk('Disk must be at least 16 GiB.')
    if not ((node.get('serial') or '').strip() or (node.get('wwn') or '').strip()):
        raise UnsafeDisk('No stable serial/WWN was reported; refusing an ambiguous disk.')
    for child in walk(node):
        if child.get('type') not in ('disk','part'):
            raise UnsafeDisk('Active LVM, RAID or mapped storage is not supported.')
        if any(p for p in (child.get('mountpoints') or [])):
            raise UnsafeDisk('Disk or a partition is mounted. No automatic unmount is performed.')
        if child.get('name') in active_swaps:
            raise UnsafeDisk('Disk has active swap.')
        if child.get('name') in holders:
            raise UnsafeDisk('Disk/partition is held by another block device.')
    return {
        'name': name, 'size': int(node['size']),
        'major_minor': node.get('maj:min',''),
        'serial': (node.get('serial') or '').strip(),
        'wwn': (node.get('wwn') or '').strip(),
        'model': (node.get('model') or '').strip(), 'sysfs': syspath,
    }

def partition_layout(device, node):
    """Read partition geometry without mounting, including full MBR containers.

    The kernel exposes an extended partition as a tiny block device, not its
    full container. sfdisk supplies the table geometry; sysfs independently
    confirms starts and ordinary partition sizes before that layout is used.
    """
    children = [child for child in walk(node) if child is not node]
    if any(child.get('type') != 'part' for child in children):
        raise UnsafeDisk('Mapped storage is not a supported target.')
    by_path = {child['name']: child for child in children}
    if len(by_path) != len(children):
        raise UnsafeDisk('Duplicate partition identity.')
    table_type = node.get('pttype') or ''
    if table_type not in ('gpt', 'dos'):
        if children:
            raise UnsafeDisk('Only GPT and MBR partition tables are supported.')
        return []
    proc = subprocess.run(['/usr/sbin/sfdisk', '--json', device], check=True,
        capture_output=True, text=True, timeout=10,
        env={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LC_ALL':'C'})
    if len(proc.stdout) > 1024*1024:
        raise UnsafeDisk('Partition table metadata exceeds the size limit.')
    table = json.loads(proc.stdout).get('partitiontable', {})
    sector = int(node.get('log-sec') or 512)
    if (table.get('device') != device or table.get('label') != table_type
            or table.get('unit') != 'sectors' or int(table.get('sectorsize', sector)) != sector):
        raise UnsafeDisk('Partition table geometry changed during inspection.')
    table_id = str(table.get('id', '')).lower().removeprefix('0x')
    if table_id != str(node.get('ptuuid') or '').lower().removeprefix('0x'):
        raise UnsafeDisk('Partition table identity changed during inspection.')
    entries = table.get('partitions', [])
    if not isinstance(entries, list) or len(entries) != len(by_path) or len(entries) > 128:
        raise UnsafeDisk('The kernel and on-disk partition lists differ.')
    parts, seen = [], set()
    prefix = device + ('p' if device[-1:].isdigit() else '')
    for entry in entries:
        path = entry.get('node')
        if path not in by_path or path in seen or not re.fullmatch(re.escape(prefix)+r'[1-9][0-9]*', path):
            raise UnsafeDisk('An on-disk partition has an ambiguous device path.')
        seen.add(path)
        child = by_path[path]
        number = int(path[len(prefix):])
        ptype = str(entry.get('type', '')).lower()
        extended = table_type == 'dos' and int(ptype.removeprefix('0x') or '0', 16) in (0x05, 0x0f, 0x85)
        logical = table_type == 'dos' and number >= 5
        first, size = int(entry['start'])*sector, int(entry['size'])*sector
        sys_start = Path('/sys/class/block')/Path(path).name/'start'
        if (first != int(sys_start.read_text().strip())*512 or size <= 0
                or first < sector or first+size > int(node['size'])
                or (not extended and size != int(child['size']))):
            raise UnsafeDisk('Partition boundaries changed during inspection.')
        parttype = (child.get('parttype') or ptype).lower()
        if table_type == 'gpt':
            if parttype != ptype:
                raise UnsafeDisk('A GPT partition type changed during inspection.')
            partuuid = str(child.get('partuuid') or '').lower()
            if partuuid != str(entry.get('uuid') or '').lower():
                raise UnsafeDisk('A GPT partition identity changed during inspection.')
        else:
            if int(parttype.removeprefix('0x') or '0', 16) != int(ptype.removeprefix('0x') or '0', 16):
                raise UnsafeDisk('An MBR partition type changed during inspection.')
            partuuid = str(child.get('partuuid') or '').lower()
            if partuuid != table_id+'-'+format(number, '02x'):
                raise UnsafeDisk('An MBR partition identity changed during inspection.')
        parts.append(dict(path=path, first=first, size=size,
            fs='' if extended else (child.get('fstype') or '').lower(),
            partuuid=partuuid, label=child.get('partlabel') or '',
            parttype=parttype, fsuuid='' if extended else child.get('uuid') or '',
            extended=extended, logical=logical,
            bios_grub=table_type == 'gpt' and ptype == '21686148-6449-6e6f-744e-656564454649'))
    return sorted(parts, key=lambda p:(p['first'], p['path']))


def probe(device):
    if not re.fullmatch(r'/dev/[A-Za-z0-9]+', device): raise UnsafeDisk('Invalid device path.')
    st = os.stat(device)
    if not stat.S_ISBLK(st.st_mode): raise UnsafeDisk('Not a block device.')
    p=subprocess.run(['/usr/bin/lsblk','--json','--bytes','--paths','--output',
       'NAME,KNAME,TYPE,TRAN,RO,RM,SIZE,MOUNTPOINTS,SERIAL,WWN,MODEL,MAJ:MIN,LOG-SEC,PTTYPE,PTUUID,FSTYPE,PARTUUID,PARTLABEL,PARTTYPE,UUID',device],
       check=True, capture_output=True, text=True, timeout=10,
       env={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LC_ALL':'C'})
    nodes=json.loads(p.stdout)['blockdevices']
    if len(nodes)!=1: raise UnsafeDisk('Ambiguous lsblk result.')
    node=nodes[0]
    syspath=str((Path('/sys/class/block')/Path(device).name).resolve(strict=True))
    holders=set()
    for n in walk(node):
        k=Path(n['name']).name
        h=Path('/sys/class/block')/k/'holders'
        if not h.is_dir(): raise UnsafeDisk('Cannot inspect device holders.')
        if any(h.iterdir()): holders.add(n['name'])
    swaps={line.split()[0] for line in Path('/proc/swaps').read_text().splitlines()[1:] if line.split()}
    result=validate_tree(node,syspath,holders,swaps)
    # Bind the initial device identity to the complete on-disk partition layout.
    # sysfs starts are expressed in 512-byte sectors, including on 4Kn disks.
    result['logical_size']=int(node.get('log-sec') or 512)
    result['pttype']=node.get('pttype') or ''
    result['ptuuid']=node.get('ptuuid') or ''
    result['partitions']=partition_layout(device,node)

    if result['major_minor'] != f'{os.major(st.st_rdev)}:{os.minor(st.st_rdev)}':
        raise UnsafeDisk('Device identity changed during inspection.')
    return result

def main(argv):
    if argv[1:]==['prepare-reservations']:
        from boot_finalize import prepare_reservations
        prepare_reservations()
        print(json.dumps({'ok':True}))
        return 0
    if len(argv)==4 and argv[1]=='reservations':
        from boot_finalize import verified_reservations
        print(json.dumps(verified_reservations(argv[2],argv[3])))
        return 0
    if len(argv)==3 and argv[1]=='probe':
        print(json.dumps(probe(argv[2]),sort_keys=True,separators=(',',':')))
        return 0
    if argv[1:] not in (['validate-plan'], ['validate-plan','--record']):
        raise UnsafeDisk('Usage: disk_safety.py probe /dev/DISK | validate-plan [--record]')
    from install_plan import validate_plan
    raw=sys.stdin.buffer.read(1024*1024+1)
    if len(raw)>1024*1024:raise UnsafeDisk('Installation plan is too large.')
    plan=json.loads(raw)
    firmware='efi' if Path('/sys/firmware/efi').is_dir() else 'bios'
    if plan.get('firmware')!=firmware:raise UnsafeDisk('The installation plan does not match the current firmware mode.')
    current=probe(plan.get('target',''))
    intent=validate_plan(plan,current)
    from boot_finalize import validate_t2_efi_plan
    validate_t2_efi_plan(plan,current,intent)
    if argv[1:]==['validate-plan','--record']:
        directory=Path('/run/core-installer')
        directory.mkdir(mode=0o700,exist_ok=True)
        st=directory.lstat()
        if not stat.S_ISDIR(st.st_mode) or st.st_uid!=0 or st.st_mode&0o077:
            raise UnsafeDisk('Unsafe installer runtime directory.')
        target=directory/'confirmed-plan.json'
        fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'w') as f:json.dump(plan,f,sort_keys=True,separators=(',',':'))
    print(json.dumps({'ok':True}))
    return 0

if __name__=='__main__':
    try:
        sys.exit(main(sys.argv))
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as e:
        print(f'Installer: {e}',file=sys.stderr);sys.exit(1)