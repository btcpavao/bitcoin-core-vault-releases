"""Vault raw-partition policy regressions using in-memory disk metadata only.

No test opens a block device. sfdisk/lsblk/sysfs readback is simulated, and every
reservation-preparation test stubs probes and subprocesses before entering the
production function. Unexpected external process creation fails the test.
"""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import json
import sys
import unittest
from unittest.mock import call, patch

ROOT = next(p for p in Path(__file__).resolve().parents
            if (p / 'config/includes.chroot/usr/lib/core-vault-installer').is_dir())
LIB = ROOT / 'config/includes.chroot/usr/lib/core-vault-installer'
sys.path.insert(0, str(LIB))
import install_plan as P
import boot_finalize as B
import disk_safety as D

MIB, GIB = P.MIB, P.GIB
DATA_TYPE = '0fc63daf-8483-4772-8e79-3d69d8477de4'
DISK_GUID = 'aaaaaaaa-0000-0000-0000-000000000001'


def partition(number, first, size, filesystem, label, mount='', bios=False):
    return dict(path='/dev/sda' + str(number), device='/dev/sda',
                first=first, size=size, fs=filesystem, label=label, uuid='',
                mount=mount, format=bool(filesystem), new=True, efi=False,
                extended=False, logical=False, bios_grub=bios)


def created_bios_layout(reserve=True):
    """Reviewed Vault erase/create-layout from a prior MBR disk to GPT."""
    identity = dict(
        name='/dev/sda', size=320_000_000_000, major_minor='8:0',
        serial='FIXTURE_ONLY', wwn='fixture-only', model='In-memory fixture',
        sysfs='/fixtures/sda', logical_size=512, pttype='dos', ptuuid='12345678',
        partitions=[dict(
            path='/dev/sda1', first=MIB, size=320_000_000_000 - 2*MIB,
            fs='ext4', fsuuid='old-root', label='', partuuid='12345678-01',
            parttype='83', extended=False, logical=False, bios_grub=False)],
    )
    parts = [
        partition(1, MIB, 2*MIB, '', 'BIOS boot', bios=True),
        partition(2, 3*MIB, 32*GIB, 'ext4', 'BitcoinCoreVault', mount='/'),
    ]
    if reserve:
        parts.append(partition(
            3, 3*MIB + 32*GIB, 200*GIB, '', P.RESERVED_LABEL['node']))
    jobs = [dict(type='CreatePartitionTableJob', device='/dev/sda')]
    jobs += [dict(type='CreatePartitionJob', device='/dev/sda',
                  partition_device='/dev/sda', path=p['path'],
                  first=p['first'], size=p['size']) for p in parts]
    jobs.append(dict(type='SetPartFlagsJob', device='/dev/sda',
                     partition_device='/dev/sda', path='/dev/sda1',
                     first=MIB, size=2*MIB))
    plan = dict(
        schema=1, product='vault', mode='erase-layout', firmware='bios',
        target='/dev/sda', boot_target='/dev/sda', expected=deepcopy(identity),
        disks=[dict(path='/dev/sda', logical_size=512, table_before='dos',
                    table_after='gpt', partitions=parts, jobs=jobs)],
    )
    return plan


def disk_readback(plan, type_overrides=None, stale_signatures=False):
    """Exercise the real read-only layout decoder with bounded fake inputs."""
    overrides = type_overrides or {}
    identity = deepcopy(plan['expected'])
    identity.update(pttype='gpt', ptuuid=DISK_GUID)
    node = dict(name='/dev/sda', type='disk', size=identity['size'],
                pttype='gpt', ptuuid=DISK_GUID, children=[])
    node['log-sec'] = 512
    entries, starts = [], {}
    for number, p in enumerate(plan['disks'][0]['partitions'], 1):
        guid = f'bbbbbbbb-0000-0000-0000-{number:012d}'
        ptype = overrides.get(p['path'],
                              P.BIOS_GRUB_TYPE if p['bios_grub'] else DATA_TYPE)
        filesystem = 'ext4' if stale_signatures and not p['fs'] else p['fs']
        node['children'].append(dict(
            name=p['path'], type='part', size=p['size'], fstype=filesystem,
            partuuid=guid, partlabel=p['label'], parttype=ptype,
            uuid='fixture-fs-' + str(number) if filesystem else '',
        ))
        entries.append(dict(
            node=p['path'], start=p['first']//512, size=p['size']//512,
            type=ptype, uuid=guid,
        ))
        starts['/sys/class/block/' + Path(p['path']).name + '/start'] = str(p['first']//512)
    table = dict(partitiontable=dict(
        device='/dev/sda', label='gpt', unit='sectors', sectorsize=512,
        id=DISK_GUID, partitions=entries,
    ))

    def read_start(path, *args, **kwargs):
        return starts[str(path)]

    with patch.object(D.subprocess, 'run',
                      return_value=SimpleNamespace(stdout=json.dumps(table))) as command, \
         patch.object(Path, 'read_text', autospec=True, side_effect=read_start):
        identity['partitions'] = D.partition_layout('/dev/sda', node)
    if command.call_args.args[0] != ['/usr/sbin/sfdisk', '--json', '/dev/sda']:
        raise AssertionError('Unexpected geometry command')
    return identity


class RawPartitionRoleTests(unittest.TestCase):
    def setUp(self):
        self.process = patch.object(
            B.subprocess, 'Popen',
            side_effect=AssertionError('Tests must not launch external processes'))
        self.process.start()
        self.addCleanup(self.process.stop)

    def assert_preparation_rejected(self, plan, after, message):
        with patch.object(B, 'confirmed_plan', return_value=plan), \
             patch.object(D, 'probe', return_value=after), \
             patch.object(B, 'direct_filesystem') as signature, \
             patch.object(B.subprocess, 'run') as command:
            with self.assertRaisesRegex(P.PlanError, message):
                B.prepare_reservations()
            signature.assert_not_called()
            command.assert_not_called()

    def test_correct_bios_gpt_layout_with_node_reservation(self):
        plan = created_bios_layout()
        P.validate_plan(plan, plan['expected'])
        after = disk_readback(plan)
        intent = P.validate_after(plan, after)
        self.assertEqual(intent['bios_grub']['path'], '/dev/sda1')
        self.assertEqual(intent['root']['path'], '/dev/sda2')
        self.assertEqual([p['path'] for p in intent['reserved']], ['/dev/sda3'])
        self.assertTrue(after['partitions'][0]['bios_grub'])
        self.assertFalse(after['partitions'][2]['bios_grub'])

    def test_missing_bios_guid_reports_exact_role_before_any_signature_work(self):
        plan = created_bios_layout()
        after = disk_readback(plan, {'/dev/sda1': DATA_TYPE})
        self.assert_preparation_rejected(
            plan, after, r'Installed partition role differs.*sda1.*bios_grub.*False.*True')

    def test_reservation_cannot_acquire_bios_boot_role(self):
        plan = created_bios_layout()
        after = disk_readback(plan, {'/dev/sda3': P.BIOS_GRUB_TYPE})
        self.assert_preparation_rejected(
            plan, after, r'Installed partition role differs.*sda3.*bios_grub.*True.*False')

    def test_other_partition_roles_remain_checked(self):
        for role in ('extended', 'logical'):
            with self.subTest(role=role):
                plan = created_bios_layout()
                after = disk_readback(plan)
                after['partitions'][2][role] = True
                self.assert_preparation_rejected(
                    plan, after, r'Installed partition role differs.*sda3.*' + role)

    def test_preparation_clears_only_fresh_reviewed_raw_spans(self):
        plan = created_bios_layout()
        after = disk_readback(plan, stale_signatures=True)
        with patch.object(B, 'confirmed_plan', return_value=plan), \
             patch.object(D, 'probe', return_value=after), \
             patch.object(B, 'direct_filesystem',
                          side_effect=[('ext4', 'old-reserve'), ('', ''),
                                       ('ext4', 'old-boot'), ('', '')]) as signature, \
             patch.object(B.subprocess, 'run') as command:
            B.prepare_reservations()
        self.assertEqual(signature.call_args_list, [
            call('/dev/sda3'), call('/dev/sda3'),
            call('/dev/sda1'), call('/dev/sda1')])
        self.assertEqual([c.args[0] for c in command.call_args_list], [
            ['/usr/sbin/wipefs', '--all', '--force', '--', '/dev/sda3'],
            ['/usr/sbin/wipefs', '--all', '--force', '--', '/dev/sda1']])
        self.assertEqual(after['partitions'][0]['fs'], 'ext4')
        self.assertEqual(after['partitions'][2]['fs'], 'ext4')

    def test_bios_layout_without_reservation_prepares_only_bios_slot(self):
        plan = created_bios_layout(reserve=False)
        after = disk_readback(plan)
        with patch.object(B, 'confirmed_plan', return_value=plan), \
             patch.object(D, 'probe', return_value=after), \
             patch.object(B, 'direct_filesystem', return_value=('', '')) as signature, \
             patch.object(B.subprocess, 'run') as command:
            B.prepare_reservations()
        self.assertEqual(signature.call_args_list, [call('/dev/sda1'), call('/dev/sda1')])
        command.assert_not_called()

    def test_wrong_disk_span_filesystem_and_unreviewed_partition_stop_before_writes(self):
        for mutation in ('disk', 'span', 'root-fs', 'partuuid', 'label', 'extra'):
            with self.subTest(mutation=mutation):
                plan = created_bios_layout()
                after = disk_readback(plan)
                if mutation == 'disk':
                    after['serial'] = 'CHANGED'
                elif mutation == 'span':
                    after['partitions'][2]['first'] += MIB
                elif mutation == 'root-fs':
                    after['partitions'][1]['fs'] = 'ntfs'
                elif mutation == 'partuuid':
                    after['partitions'][2]['partuuid'] = ''
                elif mutation == 'label':
                    after['partitions'][2]['label'] = 'Unreviewed reserve'
                else:
                    extra = deepcopy(after['partitions'][2])
                    extra.update(path='/dev/sda4', first=250*GIB, size=GIB)
                    after['partitions'].append(extra)
                self.assert_preparation_rejected(plan, after, '.')

    def test_existing_bios_slot_is_preserved_and_never_cleared(self):
        plan = created_bios_layout()
        after = disk_readback(plan)
        previous = deepcopy(after)
        previous['partitions'] = previous['partitions'][:2]
        plan.update(mode='advanced', expected=previous)
        disk = plan['disks'][0]
        disk['table_before'] = 'gpt'
        for part, old in zip(disk['partitions'][:2], previous['partitions']):
            part.update(new=False, uuid=old['partuuid'])
        root, reserve = disk['partitions'][1:]
        disk['jobs'] = [
            dict(type=kind, device='/dev/sda', partition_device='/dev/sda',
                 path=p['path'], first=p['first'], size=p['size'])
            for kind, p in (('FormatPartitionJob', root),
                            ('CreatePartitionJob', reserve))]
        with patch.object(B, 'confirmed_plan', return_value=plan), \
             patch.object(D, 'probe', return_value=after), \
             patch.object(B, 'direct_filesystem', return_value=('', '')) as signature, \
             patch.object(B.subprocess, 'run') as command:
            B.prepare_reservations()
        self.assertEqual(signature.call_args_list, [call('/dev/sda3'), call('/dev/sda3')])
        command.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
