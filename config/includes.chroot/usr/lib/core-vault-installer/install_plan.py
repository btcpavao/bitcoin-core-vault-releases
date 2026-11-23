#!/usr/bin/python3
"""Pure, fail-closed validation of the native installer's planned disk operations.

This module never opens, mounts, formats or writes a block device. disk_safety.py
supplies an independently re-probed identity immediately before partition jobs.
"""
from __future__ import annotations
import json, re

MIB = 1024**2
GIB = 1024**3
MIN_ROOT = {'node': 32*GIB, 'vault': 16*GIB}
RESERVED_LABEL = {'node': 'BitcoinCoreNodeReserved', 'vault': 'BitcoinCoreVaultReserved'}
ESP_TYPE = 'c12a7328-f81f-11d2-ba4b-00a0c93ec93b'
JOBS = {'CreatePartitionTableJob', 'CreatePartitionJob', 'DeletePartitionJob',
        'FormatPartitionJob', 'SetPartFlagsJob', 'ChangeFilesystemLabelJob'}

class PlanError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise PlanError(message)


def integer(value, name):
    require(type(value) is int and 0 <= value < 2**63, 'Invalid '+name+'.')
    return value


def span(p):
    first, size = integer(p.get('first'), 'partition start'), integer(p.get('size'), 'partition size')
    require(size > 0, 'Empty partition in the installation plan.')
    return first, first+size


def fs(p):
    value = str(p.get('fs', '')).lower()
    return {'vfat':'fat32','unknown':'','unformatted':''}.get(value,value)


def overlaps(a, b):
    return a[0] < b[1] and b[0] < a[1]


def validate_plan(plan, current):
    require(isinstance(plan, dict) and type(plan.get('schema')) is int and plan.get('schema') == 1, 'Unsupported installation plan.')
    product, mode = plan.get('product'), plan.get('mode')
    require(product in MIN_ROOT and mode in ('erase', 'advanced', 'erase-layout'), 'Unsupported installation method.')
    target = plan.get('target')
    require(target == current.get('name') and target == plan.get('boot_target'),
            'The installation and bootloader must use the same selected internal disk.')
    expected = plan.get('expected')
    require(isinstance(expected, dict) and expected == current,
            'The selected disk or its partition layout changed. Return to Disk and scan again.')
    disks = plan.get('disks')
    require(isinstance(disks, list) and 1 <= len(disks) <= 64, 'Invalid disk plan.')
    selected = [d for d in disks if d.get('path') == target]
    require(len(selected) == 1, 'The selected disk is missing or duplicated.')
    for d in disks:
        require(isinstance(d.get('jobs'), list) and isinstance(d.get('partitions'), list), 'Incomplete disk plan.')
        if d.get('path') != target:
            require(not d['jobs'] and not any(p.get('mount') or p.get('format') or p.get('new') for p in d['partitions']),
                    'The plan changes another physical disk. Keep every operation on the selected disk.')
    disk = selected[0]
    parts, jobs = disk['partitions'], disk['jobs']
    require(disk.get('logical_size') == current.get('logical_size'), 'The selected disk sector size changed.')
    require(1 <= len(parts) <= 128 and len(jobs) <= 512, 'Invalid partition operation count.')
    roots = [p for p in parts if p.get('mount') == '/']
    require(len(roots) == 1, 'Choose exactly one root partition for this installation.')
    root = roots[0]
    require(root.get('format') is True and fs(root) == 'ext4', 'The selected root must be explicitly formatted as ext4.')
    require(integer(root.get('size'), 'root size') >= MIN_ROOT[product], 'The selected root partition is too small.')
    root_span = span(root)
    before = current.get('partitions', [])
    require(isinstance(before, list), 'The original partition table could not be verified.')
    original = {span(p): p for p in before}
    original_paths = {p['path']: span(p) for p in before}
    suffix = 'p' if str(target)[-1:].isdigit() else ''
    part_pattern = re.escape(target+suffix) + r'[1-9][0-9]*'
    def reference(value):
        path = value.get('path')
        require(isinstance(path,str) and (not path or re.fullmatch(part_pattern,path)),
                'A partition path points outside the selected physical disk.')
        require(value.get('device') == target, 'A partition or job belongs to another physical disk.')
        if mode == 'advanced' and path in original_paths:
            require(span(value) == original_paths[path], 'A partition path refers to a different preserved partition.')
        return path
    require(len(original) == len(before), 'Ambiguous original partition boundaries.')
    planned_spans = [span(p) for p in parts]
    for i, p in enumerate(parts):
        start, end = planned_spans[i]
        path = reference(p)
        if not p.get('new'):
            old = original.get((start,end))
            require(old is not None and path == old.get('path')
                    and str(p.get('uuid','')).lower() == str(old.get('partuuid','')).lower(),
                    'An existing partition path or identity differs from the original disk.')
        require(start >= MIB and end <= current['size'], 'A planned partition is outside the selected disk.')
        require(not any(overlaps((start,end), other) for other in planned_spans[i+1:]), 'Planned partitions overlap.')
        require(p.get('mount') in ('', '/', '/boot/efi'), 'Only root and EFI mount assignments are supported.')
        require(type(p.get('format')) is bool and type(p.get('new')) is bool, 'Invalid format state.')
    for job in jobs:
        require(isinstance(job, dict) and job.get('type') in JOBS,
                'An unsupported partition operation is queued. Resizing and moving existing partitions are not supported.')
        require(job.get('device') == target, 'A queued job targets another physical disk.')
        if job['type'] != 'CreatePartitionTableJob':
            reference(job)
            require(job.get('partition_device') == target, 'A job partition belongs to another physical disk.')
    require(jobs, 'No root installation operation is planned.')
    firmware = plan.get('firmware')
    require(firmware in ('efi', 'bios'), 'Unknown firmware mode.')
    esp = [p for p in parts if p.get('mount') == '/boot/efi']
    if firmware == 'efi':
        require(len(esp) == 1, 'Choose one EFI system partition on the same disk as the root partition.')
        esp = esp[0]
        require(fs(esp) in ('fat32', 'vfat') and esp['size'] >= 128*MIB and esp.get('efi') is True,
                'EFI must be FAT32 and at least 128 MiB.')
    else:
        require(mode == 'erase', 'Advanced partitioning and reservations require booting this installer in UEFI mode.')
        require(not esp, 'Unexpected EFI assignment in BIOS mode.')
        esp = None
    # Whole-disk erase remains an explicit, separately reviewed operation.
    if mode in ('erase', 'erase-layout'):
        require(any(j['type'] == 'CreatePartitionTableJob' for j in jobs),
                'A whole-disk installation must create the reviewed partition table.')
        if mode == 'erase-layout':
            require(firmware == 'efi', 'Reserved layouts require UEFI mode.')
        companion = 'vault' if product == 'node' else 'node'
        reserved = [p for p in parts if p is not root and p is not esp and p.get('label') == RESERVED_LABEL[companion]]
        require(len(reserved) <= 1, 'Only one companion reservation is supported per installation.')
        for p in reserved:
            require(p.get('new') is True and fs(p) == '' and not p['format'] and not p['mount']
                    and p['size'] >= MIN_ROOT[companion],
                    'A companion reservation must be new, unformatted, unmounted and large enough.')
        require(all(p['new'] for p in parts), 'A whole-disk replacement must explicitly create every planned partition.')
        return dict(product=product, mode=mode, disk=target, root=root, esp=esp, reserved=reserved)
    require(firmware == 'efi', 'Advanced partitioning requires UEFI mode.')
    require(disk.get('table_after') == 'gpt', 'Advanced partitioning requires a GPT disk.')
    require(disk.get('table_before') in ('gpt', 'unknown', 'none'), 'Existing non-GPT layouts are not modified in Advanced.')
    if any(j['type'] == 'CreatePartitionTableJob' for j in jobs):
        require(not before, 'Advanced cannot replace an existing partition table without explicit whole-disk erase.')
    companion = 'vault' if product == 'node' else 'node'
    reserved = []
    for p in parts:
        area = span(p)
        old = original.get(area)
        if p is root:
            if not old:
                require(not any(overlaps(area, area0) for area0 in original),
                        'A new root may use only genuinely unallocated space.')
            continue
        if p is esp:
            if old:
                require(not p['new'] and not p['format'] and fs(old) in ('fat32','vfat')
                        and old.get('parttype', '').lower() == ESP_TYPE,
                        'The existing EFI system partition must be reused without formatting.')
            else:
                require(p['new'] and p['format'] and not any(overlaps(area, a) for a in original),
                        'A new EFI partition must be created only in unallocated space.')
            continue
        if p['new']:
            require(p.get('label') == RESERVED_LABEL[companion] and fs(p) in ('unformatted','unknown','')
                    and not p['format'] and not p['mount'] and p['size'] >= MIN_ROOT[companion],
                    'Only an unformatted companion reservation may be created in addition to root and EFI.')
            require(not any(overlaps(area, a) for a in original), 'Reserved space must be genuinely unallocated.')
            reserved.append(p)
        else:
            require(old is not None and not p['format'] and not p['mount'] and fs(p) == fs(old),
                    'An existing data or other-system partition would be changed.')
            require(not old.get('partuuid') or p.get('uuid','').lower() == old['partuuid'].lower(),
                    'An existing preserved partition identity would change.')
    require(len(reserved) <= 1, 'Only one companion reservation is supported per installation.')
    for area in original:
        require(area in planned_spans, 'An existing partition would be deleted or resized.')
    new_areas = {span(p) for p in parts if p['new']}
    for job in jobs:
        kind = job['type']
        if kind == 'CreatePartitionTableJob':
            continue
        area = span(job)
        if kind == 'DeletePartitionJob':
            require(area == root_span and area in original and job['path'] == original[area]['path'],
                    'Only the explicitly selected root may be replaced; other partitions are preserved.')
        elif kind == 'FormatPartitionJob':
            require(area == root_span and area in original and job['path'] == original[area]['path'],
                    'Only the explicitly selected existing root may receive a separate format job.')
        elif kind == 'CreatePartitionJob':
            require(area in new_areas, 'A partition creation is missing from the reviewed plan.')
        elif kind in ('SetPartFlagsJob','ChangeFilesystemLabelJob'):
            require(area == root_span or area in new_areas,
                    'Flags or labels on a preserved partition would be changed.')
    return dict(product=product, mode=mode, disk=target, root=root, esp=esp, reserved=reserved)


_GUID = re.compile(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}')
_RECORD_FIELDS = {
    'reserved': {'schema','product','serial','wwn','disk_guid','partuuid','first','size'},
    'installed': {'schema','product','serial','wwn','disk_guid','root_partuuid','root_fsuuid','esp_partuuid','esp_fsuuid','boot_id'},
    'fallback': {'schema','product','esp_partuuid','sha256'},
}

def validate_record(record, kind):
    require(kind in _RECORD_FIELDS and isinstance(record,dict) and set(record)==_RECORD_FIELDS[kind],
            'Unexpected EFI metadata fields.')
    require(type(record['schema']) is int and record['schema']==1 and isinstance(record['product'],str) and record['product'] in MIN_ROOT,
            'Unsupported EFI metadata schema or product.')
    numbers={'schema','first','size'}
    for key,value in record.items():
        if key in numbers:
            integer(value,'metadata '+key)
        else:
            require(isinstance(value,str) and len(value)<=512 and '\x00' not in value,
                    'Invalid EFI metadata field: '+key)
    for key in ('disk_guid','partuuid','root_partuuid','esp_partuuid'):
        if key in record:require(_GUID.fullmatch(record[key]),'Invalid GPT identifier in EFI metadata.')
    if kind=='reserved':
        require(record['first']>=MIB and record['size']>=MIN_ROOT[record['product']], 'Invalid reserved partition span.')
    elif kind=='installed':
        require(_GUID.fullmatch(record['root_fsuuid']) and re.fullmatch(r'[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}',record['esp_fsuuid']),
                'Invalid filesystem identifier in EFI metadata.')
        require(record['boot_id']=='BitcoinCore'+record['product'].title(),'Unexpected EFI vendor directory.')
    else:
        require(re.fullmatch(r'[0-9a-f]{64}',record['sha256']),'Invalid fallback ownership digest.')
    return record


def verify_reservation(record, product, identity, partition):
    """Validate stored ownership metadata, never a human-readable label alone."""
    validate_record(record,'reserved')
    require(record.get('product') == product and product in MIN_ROOT, 'Reservation belongs to the other product.')
    require(record.get('serial') == identity.get('serial') and record.get('wwn') == identity.get('wwn'),
            'Reservation disk identity does not match.')
    require(record.get('disk_guid') and record['disk_guid'].lower() == identity.get('ptuuid','').lower(),
            'Reservation GPT disk identity does not match.')
    require(record.get('partuuid') and record['partuuid'].lower() == partition.get('partuuid','').lower(),
            'Reservation partition identity does not match.')
    require(record.get('first') == partition.get('first') and record.get('size') == partition.get('size'),
            'Reservation boundaries changed.')
    require(not fs(partition) and partition['size'] >= MIN_ROOT[product], 'Reserved partition is no longer unformatted.')
    return True


def validate_after(plan, current):
    """Read-only post-partition check before EFI metadata/loader updates."""
    intent = validate_plan(plan, plan.get('expected', {}))
    expected = plan['expected']
    for key in ('name','size','major_minor','serial','wwn','model','sysfs','logical_size'):
        require(current.get(key)==expected.get(key), 'Target disk identity changed after partitioning: '+key)
    disk=next(d for d in plan['disks'] if d['path']==plan['target'])
    planned={span(p):p for p in disk['partitions']}
    actual={span(p):p for p in current['partitions']}
    require(len(actual)==len(current['partitions']) and planned.keys()==actual.keys(),
            'Installed partition boundaries differ from the reviewed plan.')
    reviewed_new_table=any(j['type']=='CreatePartitionTableJob' for j in disk['jobs'])
    if plan['mode']=='advanced' and not reviewed_new_table:
        require(current.get('ptuuid')==expected.get('ptuuid'), 'The preserved GPT disk identity changed.')
    original={span(p):p for p in expected['partitions']}
    for area,p in planned.items():
        now=actual[area]
        require(fs(now)==fs(p), 'Installed filesystem differs from the reviewed plan.')
        if not p['new'] and p.get('mount')!='/':
            old=original[area]
            for key in ('partuuid','fsuuid','parttype','label'):
                require(now.get(key)==old.get(key), 'A preserved partition identity or label changed.')
        require(now.get('partuuid') or plan['firmware']=='bios', 'A GPT partition identity is missing.')
    intent['root']=actual[span(intent['root'])]
    if intent['esp']:
        intent['esp']=actual[span(intent['esp'])]
        require(intent['esp'].get('parttype','').lower()==ESP_TYPE, 'Installed EFI partition type is wrong.')
    intent['reserved']=[actual[span(p)] for p in intent['reserved']]
    return intent
