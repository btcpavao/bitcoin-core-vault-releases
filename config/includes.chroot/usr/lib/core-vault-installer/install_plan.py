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
BIOS_GRUB_TYPE = '21686148-6449-6e6f-744e-656564454649'
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
    require(isinstance(plan, dict) and type(plan.get('schema')) is int and plan.get('schema') == 1,
            'Unsupported installation plan.')
    product, mode = plan.get('product'), plan.get('mode')
    require(product in MIN_ROOT and mode in ('erase', 'advanced', 'erase-layout'),
            'Unsupported installation method.')
    target = plan.get('target')
    require(target == current.get('name') and target == plan.get('boot_target'),
            'The installation and bootloader must use the same selected internal disk.')
    expected = plan.get('expected')
    require(isinstance(expected, dict) and expected == current,
            'The selected disk or its partition layout changed. Return to Disk and scan again.')
    disks = plan.get('disks')
    require(isinstance(disks, list) and 1 <= len(disks) <= 64
            and all(isinstance(d, dict) for d in disks), 'Invalid disk plan.')
    selected = [d for d in disks if d.get('path') == target]
    require(len(selected) == 1, 'The selected disk is missing or duplicated.')
    for d in disks:
        require(isinstance(d.get('jobs'), list) and isinstance(d.get('partitions'), list)
                and all(isinstance(p, dict) for p in d['partitions']), 'Incomplete disk plan.')
        if d.get('path') != target:
            require(not d['jobs'] and not any(p.get('mount') or p.get('format') or p.get('new')
                                             for p in d['partitions']),
                    'The plan changes another physical disk. Keep every operation on the selected disk.')
    disk = selected[0]
    parts, jobs = disk['partitions'], disk['jobs']
    sector = integer(current.get('logical_size'), 'logical sector size')
    require(sector in (512, 1024, 2048, 4096) and disk.get('logical_size') == sector,
            'The selected disk sector size changed or is unsupported.')
    require(1 <= len(parts) <= 128 and len(jobs) <= 512, 'Invalid partition operation count.')
    table = disk.get('table_after')
    require(table in ('gpt', 'dos'), 'Use a GPT or MBR partition table.')
    require(disk.get('table_before') == (current.get('pttype') or 'none'),
            'The original partition table type changed.')
    firmware = plan.get('firmware')
    require(firmware in ('efi', 'bios'), 'Unknown firmware mode.')
    before = current.get('partitions', [])
    require(isinstance(before, list), 'The original partition table could not be verified.')
    original = {span(p): p for p in before}
    original_paths = {p['path']: span(p) for p in before}
    require(len(original) == len(before) == len(original_paths), 'Ambiguous original partition boundaries.')
    original_data = {area: p for area, p in original.items() if not p.get('extended', False)}
    original_extended = {area: p for area, p in original.items() if p.get('extended', False)}
    suffix = 'p' if str(target)[-1:].isdigit() else ''
    part_pattern = re.escape(target+suffix) + r'[1-9][0-9]*'

    def reference(value):
        path = value.get('path')
        require(isinstance(path, str) and (not path or re.fullmatch(part_pattern, path)),
                'A partition path points outside the selected physical disk.')
        require(value.get('device') == target, 'A partition or job belongs to another physical disk.')
        if mode == 'advanced' and path in original_paths:
            require(span(value) == original_paths[path],
                    'A partition path refers to a different preserved partition.')
        return path

    def contained(inner, outer):
        return outer[0] <= inner[0] and inner[1] <= outer[1]

    def free_area(p):
        area = span(p)
        require(not any(overlaps(area, old) for old in original_data),
                'A new partition may use only genuinely unallocated space.')
        for outer in original_extended:
            if overlaps(area, outer):
                require(p.get('logical') is True and contained(area, outer),
                        'Only a logical partition may use free space inside an existing extended partition.')

    planned_spans = [span(p) for p in parts]
    require(len(set(planned_spans)) == len(planned_spans), 'Duplicate planned partition boundaries.')
    containers = [(p, span(p)) for p in parts if p.get('extended', False)]
    require(not containers or (table == 'dos' and len(containers) == 1),
            'An extended partition is supported only on an MBR disk.')
    for i, p in enumerate(parts):
        start, end = planned_spans[i]
        path = reference(p)
        require(type(p.get('format')) is bool and type(p.get('new')) is bool, 'Invalid format state.')
        for flag in ('extended', 'logical', 'bios_grub'):
            require(type(p.get(flag, False)) is bool, 'Invalid partition role.')
        old = original.get((start, end))
        if not p['new']:
            require(old is not None and path == old.get('path')
                    and str(p.get('uuid', '')).lower() == str(old.get('partuuid', '')).lower(),
                    'An existing partition path or identity differs from the original disk.')
            require(p.get('extended', False) == old.get('extended', False)
                    and p.get('logical', False) == old.get('logical', False),
                    'An existing primary, logical or extended partition role would change.')
        require(start >= (MIB if p['new'] else sector) and end <= current['size']
                and start % sector == 0 and (end-start) % sector == 0,
                'A planned partition is outside the selected disk or is not sector aligned.')
        require(p.get('mount') in ('', '/', '/boot', '/boot/efi'), 'Unsupported mount assignment.')
        if p.get('extended', False):
            require(not p['new'] and not p['format'] and not p['mount'] and not p.get('logical')
                    and old is not None and not p.get('bios_grub'),
                    'The existing extended partition container must be preserved unchanged.')
        if p.get('logical', False):
            require(table == 'dos' and len(containers) == 1
                    and contained((start, end), containers[0][1]) and start > containers[0][1][0],
                    'A logical partition must stay inside the existing extended partition.')
            if p['new']:
                logical_ends = [area[1] for area, prev in original_data.items() if prev.get('logical')]
                require(not logical_ends or start >= max(logical_ends) + sector,
                        'Create new logical partitions after the existing logical partitions to preserve their identities.')
        for j, other in enumerate(parts[i+1:], i+1):
            if not overlaps((start, end), planned_spans[j]):
                continue
            container_overlap = (
                p.get('extended', False) and other.get('logical', False)
                and contained(planned_spans[j], (start, end))) or (
                other.get('extended', False) and p.get('logical', False)
                and contained((start, end), planned_spans[j]))
            require(container_overlap, 'Planned partitions overlap.')
    if table == 'dos':
        require(sum(not p.get('logical', False) for p in parts) <= 4,
                'An MBR disk has only four primary partition slots.')
        require(current['size'] // sector <= 2**32,
                'This disk is too large for an MBR layout. Use GPT, including in Legacy BIOS mode.')
    else:
        require(not any(p.get('logical') or p.get('extended') for p in parts),
                'GPT does not contain logical or extended partitions.')

    roots = [p for p in parts if p.get('mount') == '/']
    require(len(roots) == 1, 'Choose exactly one root partition for this installation.')
    root = roots[0]
    require(root.get('format') is True and fs(root) == 'ext4'
            and not root.get('extended') and not root.get('bios_grub'),
            'The selected root must be explicitly formatted as ext4.')
    require(integer(root.get('size'), 'root size') >= MIN_ROOT[product], 'The selected root partition is too small.')
    root_span = span(root)
    boot = [p for p in parts if p.get('mount') == '/boot']
    require(not boot or (product == 'node' and mode == 'erase' and len(boot) == 1),
            'A separate /boot is supported only by the automatic whole-disk Node layout.')
    if boot:
        require(boot[0].get('new') is True and boot[0].get('format') is True
                and fs(boot[0]) == 'ext4' and integer(boot[0].get('size'), 'boot size') == GIB,
                'Automatic Node /boot must be a new, explicitly formatted 1 GiB ext4 partition.')
    for job in jobs:
        require(isinstance(job, dict) and job.get('type') in JOBS,
                'An unsupported partition operation is queued. Resizing and moving existing partitions are not supported.')
        require(job.get('device') == target, 'A queued job targets another physical disk.')
        if job['type'] != 'CreatePartitionTableJob':
            reference(job)
            require(job.get('partition_device') == target, 'A job partition belongs to another physical disk.')
    require(jobs, 'No root installation operation is planned.')
    esps = [p for p in parts if p.get('mount') == '/boot/efi']
    esp, bios_grub = None, None
    if firmware == 'efi':
        require(table == 'gpt', 'UEFI Advanced installation uses GPT. An existing MBR disk is not converted automatically.')
        require(len(esps) == 1, 'Choose one EFI system partition on the same disk as the root partition.')
        esp = esps[0]
        require(fs(esp) == 'fat32' and esp['size'] >= 128*MIB and esp.get('efi') is True
                and not esp.get('bios_grub') and not esp.get('extended'),
                'EFI must be FAT32 and at least 128 MiB.')
    else:
        require(not esps, 'Unexpected EFI mount assignment in BIOS mode.')
        bios_parts = [p for p in parts if p.get('bios_grub', False)]
        if table == 'gpt':
            require(len(bios_parts) == 1,
                    'Legacy BIOS on GPT needs one unformatted BIOS boot partition (bios_grub), at least 1 MiB. Create it in unallocated space.')
            bios_grub = bios_parts[0]
            require(fs(bios_grub) == '' and not bios_grub['format'] and not bios_grub['mount']
                    and bios_grub['size'] >= MIB and not bios_grub.get('efi'),
                    'The BIOS boot partition must be unformatted, unmounted and at least 1 MiB.')
            old = original.get(span(bios_grub))
            if old and mode == 'advanced':
                require(old.get('parttype', '').lower() == BIOS_GRUB_TYPE
                        and old.get('bios_grub', False) and not bios_grub['new'],
                        'A preserved data partition cannot be repurposed as BIOS boot space.')
        else:
            require(not bios_parts, 'An MBR layout does not use a GPT BIOS boot partition.')
            require(min(span(p)[0] for p in parts) >= MIB,
                    'Legacy BIOS on this MBR disk needs a 1 MiB gap before the first partition for GRUB. Existing partitions will not be moved; use another disk or an explicitly erased GPT layout.')

    companion = 'vault' if product == 'node' else 'node'
    reserved = [p for p in parts if p is not root and p is not esp and p is not bios_grub
                and p.get('label') == RESERVED_LABEL[companion] and p.get('new')]
    require(len(reserved) <= 1, 'Only one companion reservation is supported per installation.')
    for p in reserved:
        require(fs(p) == '' and not p['format'] and not p['mount'] and not p.get('extended')
                and not p.get('bios_grub') and p['size'] >= MIN_ROOT[companion],
                'A companion reservation must be new, unformatted, unmounted and large enough.')
    result = dict(product=product, mode=mode, disk=target, root=root, esp=esp,
                  bios_grub=bios_grub, reserved=reserved)
    if mode in ('erase', 'erase-layout'):
        require(any(j['type'] == 'CreatePartitionTableJob' for j in jobs),
                'A whole-disk installation must create the reviewed partition table.')
        require(all(p['new'] for p in parts), 'A whole-disk replacement must explicitly create every planned partition.')
        allowed = [root] + esps + ([bios_grub] if bios_grub else []) + reserved + boot
        require(all(any(p is allowed_part for allowed_part in allowed) for p in parts),
                'The whole-disk layout contains an unreviewed partition role.')
        return result

    require(disk.get('table_before') in ('gpt', 'dos', 'unknown', 'none'),
            'This existing partition table is unsupported. It will not be changed automatically.')
    if any(j['type'] == 'CreatePartitionTableJob' for j in jobs):
        require(not before and disk.get('table_before') in ('unknown', 'none'),
                'Advanced cannot replace an existing partition table without explicit whole-disk erase.')
    else:
        require(table == disk.get('table_before'), 'Advanced must preserve the existing partition table type.')
    for p in parts:
        area, old = span(p), original.get(span(p))
        if p is root:
            if not old:
                free_area(p)
            continue
        if p is esp:
            if old:
                require(not p['new'] and not p['format'] and fs(old) == 'fat32'
                        and old.get('parttype', '').lower() == ESP_TYPE,
                        'The existing EFI system partition must be reused without formatting.')
            else:
                require(p['new'] and p['format'], 'A new EFI partition must be explicitly formatted.')
                free_area(p)
            continue
        if p is bios_grub:
            if old:
                require(not p['new'] and not p['format'] and fs(old) == ''
                        and old.get('parttype', '').lower() == BIOS_GRUB_TYPE,
                        'Reuse the existing BIOS boot partition without formatting.')
            else:
                require(p['new'], 'A new BIOS boot partition is missing from the plan.')
                free_area(p)
            continue
        if p['new']:
            require(any(p is reserve for reserve in reserved),
                    'Only root, required boot space and an unformatted companion reservation may be created.')
            free_area(p)
        else:
            require(old is not None and not p['format'] and not p['mount'] and fs(p) == fs(old)
                    and p.get('bios_grub', False) == old.get('bios_grub', False),
                    'An existing data or other-system partition would be changed.')
            require(not old.get('partuuid') or p.get('uuid', '').lower() == old['partuuid'].lower(),
                    'An existing preserved partition identity would change.')
    for area in original:
        require(area in planned_spans, 'An existing partition would be deleted or resized.')
    new_areas = {span(p) for p in parts if p['new']}
    for job in jobs:
        kind = job['type']
        if kind == 'CreatePartitionTableJob':
            continue
        area = span(job)
        if kind == 'DeletePartitionJob':
            require(False, 'Advanced formats the selected root in place. Deleting an existing partition is not permitted.')
        elif kind == 'FormatPartitionJob':
            require(area == root_span and area in original and job['path'] == original[area]['path'],
                    'Only the explicitly selected existing root may receive a separate format job.')
        elif kind == 'CreatePartitionJob':
            require(area in new_areas, 'A partition creation is missing from the reviewed plan.')
        elif kind in ('SetPartFlagsJob', 'ChangeFilesystemLabelJob'):
            require(area == root_span or area in new_areas,
                    'Flags or labels on a preserved partition would be changed.')
    return result


_GUID = re.compile(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}')
_MBR_DISK = re.compile(r'[0-9a-fA-F]{8}')
_MBR_PART = re.compile(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{2,8}')
_RECORD_FIELDS = {
    'reserved': {'schema','product','serial','wwn','disk_guid','partuuid','first','size'},
    'installed': {'schema','product','serial','wwn','disk_guid','root_partuuid','root_fsuuid','esp_partuuid','esp_fsuuid','boot_id'},
    'fallback': {'schema','product','esp_partuuid','sha256'},
}
_BIOS_RECORD_FIELDS = {
    'reserved': {'schema','firmware','table_type','product','serial','wwn','disk_guid','partuuid','first','size'},
    'installed': {'schema','firmware','table_type','product','serial','wwn','disk_guid','root_partuuid','root_fsuuid','boot_id'},
}

def validate_record(record, kind):
    require(isinstance(record, dict) and type(record.get('schema')) is int, 'Invalid boot metadata.')
    bios = record['schema'] == 2
    fields = _BIOS_RECORD_FIELDS if bios else _RECORD_FIELDS
    require(kind in fields and set(record) == fields[kind], 'Unexpected boot metadata fields.')
    require(record['schema'] in (1, 2) and isinstance(record['product'], str)
            and record['product'] in MIN_ROOT, 'Unsupported boot metadata schema or product.')
    if bios:
        require(record['firmware'] == 'bios' and record['table_type'] in ('gpt', 'dos'),
                'Unsupported BIOS metadata layout.')
    numbers = {'schema', 'first', 'size'}
    for key, value in record.items():
        if key in numbers:
            integer(value, 'metadata '+key)
        else:
            require(isinstance(value, str) and len(value) <= 512 and '\x00' not in value,
                    'Invalid boot metadata field: '+key)
    mbr = bios and record['table_type'] == 'dos'
    for key in ('disk_guid', 'partuuid', 'root_partuuid', 'esp_partuuid'):
        if key in record:
            pattern = (_MBR_DISK if key == 'disk_guid' else _MBR_PART) if mbr else _GUID
            require(pattern.fullmatch(record[key]), 'Invalid disk or partition identifier in boot metadata.')
    if kind == 'reserved':
        require(record['first'] >= MIB and record['size'] >= MIN_ROOT[record['product']],
                'Invalid reserved partition span.')
    elif kind == 'installed':
        require(_GUID.fullmatch(record['root_fsuuid']), 'Invalid root filesystem identifier in boot metadata.')
        if not bios:
            require(re.fullmatch(r'[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}', record['esp_fsuuid']),
                    'Invalid EFI filesystem identifier in boot metadata.')
        require(record['boot_id'] == 'BitcoinCore'+record['product'].title(), 'Unexpected product boot identifier.')
    else:
        require(re.fullmatch(r'[0-9a-f]{64}', record['sha256']), 'Invalid fallback ownership digest.')
    return record


def verify_reservation(record, product, identity, partition):
    """Validate stored ownership metadata, never a human-readable label alone."""
    validate_record(record, 'reserved')
    require(record.get('product') == product and product in MIN_ROOT, 'Reservation belongs to the other product.')
    require(record.get('serial') == identity.get('serial') and record.get('wwn') == identity.get('wwn'),
            'Reservation disk identity does not match.')
    table_type = record.get('table_type', 'gpt')
    require(table_type == identity.get('pttype'), 'Reservation partition table type does not match.')
    require(record.get('disk_guid') and record['disk_guid'].lower() == identity.get('ptuuid', '').lower(),
            'Reservation disk identity does not match.')
    require(record.get('partuuid') and record['partuuid'].lower() == partition.get('partuuid', '').lower(),
            'Reservation partition identity does not match.')
    require(record.get('first') == partition.get('first') and record.get('size') == partition.get('size'),
            'Reservation boundaries changed.')
    require(not fs(partition) and not partition.get('extended') and not partition.get('bios_grub')
            and partition['size'] >= MIN_ROOT[product], 'Reserved partition is no longer an unformatted data partition.')
    return True


def validate_after(plan, current):
    """Read-only post-partition identity check before boot metadata updates."""
    intent = validate_plan(plan, plan.get('expected', {}))
    expected = plan['expected']
    for key in ('name', 'size', 'major_minor', 'serial', 'wwn', 'model', 'sysfs', 'logical_size'):
        require(current.get(key) == expected.get(key), 'Target disk identity changed after partitioning: '+key)
    disk = next(d for d in plan['disks'] if d['path'] == plan['target'])
    require(current.get('pttype') == disk['table_after'], 'Installed partition table type differs from the reviewed plan.')
    planned = {span(p): p for p in disk['partitions']}
    actual = {span(p): p for p in current['partitions']}
    require(len(actual) == len(current['partitions']) and planned.keys() == actual.keys(),
            'Installed partition boundaries differ from the reviewed plan.')
    reviewed_new_table = any(j['type'] == 'CreatePartitionTableJob' for j in disk['jobs'])
    if plan['mode'] == 'advanced' and not reviewed_new_table:
        require(current.get('ptuuid') == expected.get('ptuuid'), 'The preserved disk identity changed.')
    original = {span(p): p for p in expected['partitions']}
    for area, p in planned.items():
        now = actual[area]
        require(fs(now) == fs(p), 'Installed filesystem differs from the reviewed plan.')
        for role in ('extended', 'logical', 'bios_grub'):
            observed, reviewed = now.get(role, False), p.get(role, False)
            require(observed == reviewed,
                    f'Installed partition role differs from the reviewed plan: '
                    f'{now.get("path", "(unknown)")} {role} is {observed!r}, expected {reviewed!r} '
                    f'(partition type {now.get("parttype", "(unknown)")}).')
        if disk['table_after'] == 'gpt' and p['new'] and p.get('label'):
            require(now.get('label') == p['label'], 'A new GPT partition label differs from the reviewed plan.')
        if not p['new']:
            old = original[area]
            require(now['path'] == old['path'] and now.get('partuuid') == old.get('partuuid'),
                    'An existing partition path or identity changed.')
            if p.get('mount') != '/':
                for key in ('fsuuid', 'parttype', 'label'):
                    require(now.get(key) == old.get(key), 'A preserved partition identity or label changed.')
        require(now.get('partuuid'), 'An installed partition identity is missing.')
    intent['root'] = actual[span(intent['root'])]
    if intent['esp']:
        intent['esp'] = actual[span(intent['esp'])]
        require(intent['esp'].get('parttype', '').lower() == ESP_TYPE, 'Installed EFI partition type is wrong.')
    if intent['bios_grub']:
        intent['bios_grub'] = actual[span(intent['bios_grub'])]
        require(intent['bios_grub'].get('parttype', '').lower() == BIOS_GRUB_TYPE,
                'Installed BIOS boot partition type is wrong.')
    intent['reserved'] = [actual[span(p)] for p in intent['reserved']]
    return intent
