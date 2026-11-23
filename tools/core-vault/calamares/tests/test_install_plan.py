"""Destructive-intent boundary tests using JSON and temporary regular files only.

No test opens, formats, mounts or unmounts a block device, or executes a boot job.
"""
from copy import deepcopy
from pathlib import Path
import importlib.util, json, sys, tempfile, unittest
from unittest.mock import patch
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'runtime/usr/lib/core-node-installer').is_dir() or (p/'config/includes.chroot/usr/lib/core-vault-installer').is_dir())
LIB=ROOT/('runtime/usr/lib/core-node-installer' if (ROOT/'runtime').is_dir() else 'config/includes.chroot/usr/lib/core-vault-installer')
sys.path.insert(0,str(LIB))
import install_plan as P
import boot_finalize as B
MiB=P.MIB;GiB=P.GIB

def oldpart(n,first,size,fs,label=''):
    return dict(path='/dev/sda'+str(n),first=first,size=size,fs=fs,partuuid=f'00000000-0000-0000-0000-{n:012d}',label=label,
        parttype=P.ESP_TYPE if n==1 else '0fc63daf-8483-4772-8e79-3d69d8477de4',fsuuid='1234-ABCD' if n==1 else f'fs-{n}')

def planned(p,mount='',format=False,new=False,fs=None):
    return dict(path=p['path'],device='/dev/sda',first=p['first'],size=p['size'],fs=p['fs'] if fs is None else fs,label=p['label'],
        uuid=p['partuuid'],mount=mount,format=format,new=new,efi=(mount=='/boot/efi'))

def job(kind,p):return dict(type=kind,device='/dev/sda',partition_device='/dev/sda',first=p['first'],size=p['size'],path=p['path'])

def fixture(product='node'):
    before=[oldpart(1,MiB,512*MiB,'vfat'),oldpart(2,513*MiB,60*GiB,'ntfs','Existing system'),
        oldpart(3,513*MiB+60*GiB,64*GiB,'exfat','Explicit target'),
        oldpart(4,513*MiB+124*GiB,32*GiB,'','BitcoinCoreVaultReserved')]
    identity=dict(name='/dev/sda',size=200*GiB,major_minor='8:0',serial='FIXTURE_ONLY',wwn='w-fixture',model='Fixture',sysfs='/fixtures/sda',logical_size=512,
        pttype='gpt',ptuuid='aaaaaaaa-0000-0000-0000-000000000001',partitions=deepcopy(before))
    parts=[planned(before[0],'/boot/efi'),planned(before[1]),planned(before[2],'/',True,True,'ext4'),planned(before[3])]
    disk=dict(path='/dev/sda',logical_size=512,table_before='gpt',table_after='gpt',partitions=parts,jobs=[job('DeletePartitionJob',before[2]),job('CreatePartitionJob',parts[2])])
    plan=dict(schema=1,product=product,mode='advanced',firmware='efi',target='/dev/sda',boot_target='/dev/sda',expected=deepcopy(identity),disks=[disk])
    return plan,identity

def created_layout(product='node'):
    plan,identity=fixture(product)
    identity['partitions']=identity['partitions'][:2]
    plan['expected']=deepcopy(identity);disk=plan['disks'][0];disk['partitions']=disk['partitions'][:3]
    root=disk['partitions'][2];root['size']=32*GiB if product=='node' else 16*GiB
    other='vault' if product=='node' else 'node'
    reserve=planned(oldpart(4,root['first']+root['size'],32*GiB,'',P.RESERVED_LABEL[other]),new=True)
    reserve['uuid']='';disk['partitions'].append(reserve)
    disk['jobs']=[job('CreatePartitionJob',root),job('CreatePartitionJob',reserve)]
    return plan,identity

class PlanTests(unittest.TestCase):
    def test_explicit_partition_format_preserves_three_other_partitions(self):
        p,d=fixture();v=P.validate_plan(p,d);self.assertEqual(v['root']['path'],'/dev/sda3');self.assertFalse(v['esp']['format'])
    def test_existing_ext4_is_formatted_without_delete_recreate(self):
        p,d=fixture();d['partitions'][2]['fs']='ext4';p['expected']=deepcopy(d);p['disks'][0]['partitions'][2]['new']=False
        p['disks'][0]['jobs']=[job('FormatPartitionJob',p['disks'][0]['partitions'][2])];P.validate_plan(p,d)
    def test_both_reciprocal_reservations(self):
        for product in ('node','vault'):
            with self.subTest(product=product):
                p,d=created_layout(product);v=P.validate_plan(p,d);self.assertEqual(len(v['reserved']),1)
    def test_new_esp_in_same_unallocated_span(self):
        p,d=created_layout();d['partitions']=[];p['expected']=deepcopy(d);disk=p['disks'][0]
        disk['partitions']=[disk['partitions'][0],*disk['partitions'][2:]]
        esp=disk['partitions'][0];esp.update(new=True,format=True)
        disk['jobs'].insert(0,job('CreatePartitionJob',esp));disk['jobs'].append(job('SetPartFlagsJob',esp));P.validate_plan(p,d)
    def test_4kn_uses_byte_boundaries(self):
        p,d=created_layout();d['logical_size']=4096;p['expected']=deepcopy(d);p['disks'][0]['logical_size']=4096;P.validate_plan(p,d)
    def test_changed_identity_or_layout(self):
        for key,value in [('serial','OTHER'),('size',201*GiB),('ptuuid','OTHER')]:
            with self.subTest(key=key):
                p,d=fixture();d[key]=value
                with self.assertRaises(P.PlanError):P.validate_plan(p,d)
        p,d=fixture();d['partitions'][1]['partuuid']='changed'
        with self.assertRaises(P.PlanError):P.validate_plan(p,d)
    def test_unknown_resize_move_jobs_fail_closed(self):
        for kind in ('ResizePartitionJob','ResizeVolumeGroupJob','CreateVolumeGroupJob','UnknownJob'):
            p,d=fixture();p['disks'][0]['jobs'].append(job(kind,p['disks'][0]['partitions'][1]))
            with self.assertRaises(P.PlanError):P.validate_plan(p,d)
    def test_preserved_partition_cannot_be_deleted_formatted_or_relabelled(self):
        for kind in ('DeletePartitionJob','FormatPartitionJob','SetPartFlagsJob','ChangeFilesystemLabelJob'):
            p,d=fixture();p['disks'][0]['jobs'].append(job(kind,p['disks'][0]['partitions'][1]))
            with self.assertRaises(P.PlanError):P.validate_plan(p,d)
    def test_other_physical_disk_cannot_receive_jobs_or_mount_assignments(self):
        p,d=fixture();other=deepcopy(p['disks'][0]);other['path']='/dev/sdb';p['disks'].append(other)
        with self.assertRaises(P.PlanError):P.validate_plan(p,d)
        other['jobs']=[]
        with self.assertRaises(P.PlanError):P.validate_plan(p,d)
        for part in other['partitions']:part.update(new=False,format=False,mount='')
        P.validate_plan(p,d)
    def test_bootloader_cannot_target_other_disk(self):
        p,d=fixture();p['boot_target']='/dev/sdb'
        with self.assertRaises(P.PlanError):P.validate_plan(p,d)
    def test_no_existing_esp_format(self):
        p,d=fixture();p['disks'][0]['partitions'][0]['format']=True
        with self.assertRaises(P.PlanError):P.validate_plan(p,d)
    def test_esp_requires_correct_original_partition_type(self):
        p,d=fixture();d['partitions'][0]['parttype']='data';p['expected']=deepcopy(d)
        with self.assertRaises(P.PlanError):P.validate_plan(p,d)
    def test_no_automatic_shrink_or_new_root_overlap(self):
        p,d=fixture();p['disks'][0]['partitions'][1]['size']-=GiB
        with self.assertRaises(P.PlanError):P.validate_plan(p,d)
        p,d=fixture();p['disks'][0]['partitions'][2]['first']-=GiB
        with self.assertRaises(P.PlanError):P.validate_plan(p,d)
    def test_no_faked_unallocated_space(self):
        p,d=created_layout();new=p['disks'][0]['partitions'][2];new['first']=513*MiB+GiB
        with self.assertRaises(P.PlanError):P.validate_plan(p,d)
    def test_reserved_size_product_filesystem_are_checked(self):
        for field,value in [('label','BitcoinCoreNodeReserved'),('size',GiB),('fs','ext4'),('format',True)]:
            p,d=created_layout();p['disks'][0]['partitions'][3][field]=value
            with self.assertRaises(P.PlanError):P.validate_plan(p,d)
    def test_job_and_partition_paths_are_bound_to_selected_device(self):
        for target in ('root_path','job_path','job_device','partition_device'):
            p,d=fixture()
            if target=='root_path':p['disks'][0]['partitions'][2]['path']='/dev/sdb3'
            elif target=='job_path':p['disks'][0]['jobs'][0]['path']='/dev/sdb3'
            elif target=='job_device':p['disks'][0]['jobs'][0]['device']='/dev/sdb'
            else:p['disks'][0]['jobs'][0]['partition_device']='/dev/sdb'
            with self.assertRaises(P.PlanError):P.validate_plan(p,d)
    def test_path_cannot_alias_a_preserved_partition_on_the_same_disk(self):
        p,d=fixture();p['disks'][0]['jobs'][0]['path']='/dev/sda2'
        with self.assertRaises(P.PlanError):P.validate_plan(p,d)
    def test_new_gpt_on_an_empty_disk_has_a_new_guid_after_jobs(self):
        p,d=created_layout();d['partitions']=[];d['ptuuid']='';d['pttype']='';p['expected']=deepcopy(d)
        disk=p['disks'][0];disk['table_before']='none';disk['partitions']=[disk['partitions'][0],*disk['partitions'][2:]]
        esp=disk['partitions'][0];esp.update(new=True,format=True)
        disk['jobs']=[dict(type='CreatePartitionTableJob',device='/dev/sda'),job('CreatePartitionJob',esp),*disk['jobs']]
        after=deepcopy(d);after['pttype']='gpt';after['ptuuid']='NEW-GPT'
        for i,v in enumerate(disk['partitions'],1):
            after['partitions'].append(oldpart(i,v['first'],v['size'],v['fs'],v['label']))
        P.validate_after(p,after)
    def test_legacy_bios_advanced_is_explicitly_rejected(self):
        p,d=fixture();p['firmware']='bios'
        with self.assertRaisesRegex(P.PlanError,'UEFI'):P.validate_plan(p,d)
    def test_existing_whole_disk_bios_mode_still_accepts_standard_jobs(self):
        p,d=fixture();p.update(mode='erase',firmware='bios');disk=p['disks'][0]
        root=disk['partitions'][2];disk['partitions']=[root];disk['jobs']=[dict(type='CreatePartitionTableJob',device='/dev/sda'),job('CreatePartitionJob',root),job('SetPartFlagsJob',root)]
        P.validate_plan(p,d)
    def test_whole_disk_uefi_erase_requires_explicit_table_job(self):
        p,d=created_layout();p['mode']='erase-layout'
        for part in p['disks'][0]['partitions']:part['new']=True
        with self.assertRaises(P.PlanError):P.validate_plan(p,d)
        p['disks'][0]['jobs'].insert(0,dict(type='CreatePartitionTableJob',device='/dev/sda'));P.validate_plan(p,d)
    def test_whole_disk_reservations_are_validated_before_writes(self):
        for field,value in [('size',MiB),('new',False),('format',True),('fs','ext4')]:
            p,d=created_layout();p['mode']='erase-layout'
            for part in p['disks'][0]['partitions']:part['new']=True
            p['disks'][0]['jobs'].insert(0,dict(type='CreatePartitionTableJob',device='/dev/sda'))
            p['disks'][0]['partitions'][3][field]=value
            with self.assertRaises(P.PlanError):P.validate_plan(p,d)
    def test_no_root_consent_no_plan(self):
        p,d=fixture();p['disks'][0]['partitions'][2]['format']=False
        with self.assertRaises(P.PlanError):P.validate_plan(p,d)
    def test_post_partition_check_preserves_esp_and_other_uuid(self):
        p,d=fixture();after=deepcopy(d);after['partitions'][2].update(fs='ext4',fsuuid='new-root')
        P.validate_after(p,after)
        after['partitions'][0]['fsuuid']='EFI-FORMATTED'
        with self.assertRaises(P.PlanError):P.validate_after(p,after)

class ReservationPreparationTests(unittest.TestCase):
    def after(self, plan, identity):
        after=deepcopy(identity);after['partitions']=[]
        for i,part in enumerate(plan['disks'][0]['partitions'],1):
            previous=next((v for v in identity['partitions'] if P.span(v)==P.span(part)),None)
            value=deepcopy(previous) if previous else oldpart(i,part['first'],part['size'],part['fs'],part['label'])
            if part['new']:value['fs']=part['fs']
            after['partitions'].append(value)
        return after
    def test_only_fresh_reviewed_reservation_is_cleared(self):
        plan,identity=created_layout();after=self.after(plan,identity);after['partitions'][3]['fs']='ext4'
        with patch.object(B,'confirmed_plan',return_value=plan), patch.object(B.disk_safety,'probe',return_value=after), \
             patch.object(B,'direct_filesystem',side_effect=[('ext4','old'),('','')]), patch.object(B.subprocess,'run') as run:
            B.prepare_reservations()
            self.assertEqual(run.call_count,1)
            self.assertEqual(run.call_args.args[0],['/usr/sbin/wipefs','--all','--force','--','/dev/sda4'])
    def test_existing_empty_slot_is_never_cleared(self):
        plan,identity=fixture()
        with patch.object(B,'confirmed_plan',return_value=plan), patch.object(B.subprocess,'run') as run:
            B.prepare_reservations();run.assert_not_called()
    def test_changed_disk_or_other_partition_stops_before_wipe(self):
        for mutation in ('serial','preserved_uuid','boundary'):
            plan,identity=created_layout();after=self.after(plan,identity)
            if mutation=='serial':after['serial']='OTHER'
            elif mutation=='preserved_uuid':after['partitions'][1]['partuuid']='OTHER'
            else:after['partitions'][3]['first']+=MiB
            with patch.object(B,'confirmed_plan',return_value=plan), patch.object(B.disk_safety,'probe',return_value=after), patch.object(B.subprocess,'run') as run:
                with self.assertRaises(P.PlanError):B.prepare_reservations()
                run.assert_not_called()
    def test_mounted_or_live_target_stops_before_wipe(self):
        plan,identity=created_layout()
        with patch.object(B,'confirmed_plan',return_value=plan), patch.object(B.disk_safety,'probe',side_effect=B.disk_safety.UnsafeDisk('Mounted')), patch.object(B.subprocess,'run') as run:
            with self.assertRaises(ValueError):B.prepare_reservations()
            run.assert_not_called()


class MetadataTests(unittest.TestCase):
    def record(self):
        p,d=fixture();part=d['partitions'][3]
        return dict(schema=1,product='vault',serial=d['serial'],wwn=d['wwn'],disk_guid=d['ptuuid'],partuuid=part['partuuid'],first=part['first'],size=part['size']),d,part
    def test_reservation_never_trusts_label_alone(self):
        record,d,part=self.record();P.verify_reservation(record,'vault',d,part)
        for key,value in [('serial','OTHER'),('disk_guid','OTHER'),('partuuid','OTHER'),('first',0),('size',0),('product','node')]:
            bad=deepcopy(record);bad[key]=value
            with self.assertRaises(P.PlanError):P.verify_reservation(bad,'vault',d,part)
        with self.assertRaises(P.PlanError):P.verify_reservation({'schema':1,'label':P.RESERVED_LABEL['vault']},'vault',d,part)
    def test_consumed_reservation_cannot_be_autoselected(self):
        r,d,p=self.record();p['fs']='ext4'
        with self.assertRaises(P.PlanError):P.verify_reservation(r,'vault',d,p)
    def test_oversized_or_wrong_schema_metadata_rejected(self):
        for raw in (b' '*(B.MAX_RECORD+1),b'[]',b'{"schema":2}',b'{"schema":true}',b'{"schema":1,"schema":1}'):
            with self.assertRaises((P.PlanError,ValueError)):B.bounded_json(raw)
    def test_metadata_types_and_exact_schema_fail_cleanly(self):
        r,d,p=self.record()
        for key,value in [('disk_guid',1),('serial',[]),('product',{}),('first',True),('schema',True)]:
            bad=deepcopy(r);bad[key]=value
            with self.assertRaises(P.PlanError):P.verify_reservation(bad,'vault',d,p)
        bad=deepcopy(r);bad['unknown']='ignored?'
        with self.assertRaises(P.PlanError):P.verify_reservation(bad,'vault',d,p)
    def test_oversized_fallback_is_preserved_without_reading_it(self):
        with tempfile.TemporaryDirectory() as td:
            esp=Path(td);loader=esp/'loader';loader.write_bytes(b'new');fallback=esp/'EFI/BOOT/BOOTX64.EFI';fallback.parent.mkdir(parents=True)
            with fallback.open('wb') as f:f.truncate(B.MAX_EFI+1)
            with patch.object(B,'bounded_efi_hash',side_effect=AssertionError('Must not hash oversized fallback')):
                B.install_owned_fallback(esp,loader,'node',dict(partuuid='aaaaaaaa-0000-0000-0000-000000000002'))
            self.assertEqual(fallback.stat().st_size,B.MAX_EFI+1)
    def test_grub_script_does_not_inject_untrusted_names_or_paths(self):
        text=B.grub_peer_script([dict(product='vault',uuid='1234-ABCD',path='/ignored')])
        self.assertIn('/EFI/BitcoinCoreVault/grubx64.efi',text);self.assertNotIn('/ignored',text)
        for value in ("';reboot;#",'$(id)','UUID/path'):
            with self.assertRaises(P.PlanError):B.grub_peer_script([dict(product='node',uuid=value)])
    def test_other_owned_fallback_is_preserved_byte_for_byte(self):
        with tempfile.TemporaryDirectory() as td:
            esp=Path(td);loader=esp/'loader';loader.write_bytes(b'node-v1');identity={'partuuid':'aaaaaaaa-0000-0000-0000-000000000002'}
            path=B.install_owned_fallback(esp,loader,'node',identity);original=path.read_bytes();marker=(esp/B.META/'fallback-owner.json').read_bytes()
            loader.write_bytes(b'vault-v1');B.install_owned_fallback(esp,loader,'vault',identity)
            self.assertEqual(path.read_bytes(),original);self.assertEqual((esp/B.META/'fallback-owner.json').read_bytes(),marker)
    def test_same_owned_fallback_can_be_refreshed_only_if_hash_matches(self):
        with tempfile.TemporaryDirectory() as td:
            esp=Path(td);loader=esp/'loader';loader.write_bytes(b'node-v1');identity={'partuuid':'aaaaaaaa-0000-0000-0000-000000000002'}
            path=B.install_owned_fallback(esp,loader,'node',identity);loader.write_bytes(b'node-v2')
            B.install_owned_fallback(esp,loader,'node',identity);self.assertEqual(path.read_bytes(),b'node-v2')
            path.write_bytes(b'other-owner-changed-file');loader.write_bytes(b'node-v3');B.install_owned_fallback(esp,loader,'node',identity)
            self.assertEqual(path.read_bytes(),b'other-owner-changed-file')
    def test_existing_unowned_fallback_is_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            esp=Path(td);loader=esp/'loader';loader.write_bytes(b'new');fallback=esp/'EFI/BOOT/BOOTX64.EFI';fallback.parent.mkdir(parents=True);fallback.write_bytes(b'WINDOWS')
            B.install_owned_fallback(esp,loader,'node',dict(partuuid='aaaaaaaa-0000-0000-0000-000000000002'));self.assertEqual(fallback.read_bytes(),b'WINDOWS')

if __name__=='__main__':unittest.main(verbosity=2)
