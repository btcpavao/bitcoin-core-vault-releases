"""Pure/source tests only. Never invoke partitioning or target configuration."""
import ast,copy,importlib.util,json,os,re,subprocess,tempfile,unittest
from pathlib import Path
import yaml
ROOT=Path(__file__).resolve().parents[4]
INC=ROOT/'config/includes.chroot'

def load(name,path):
    sp=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m);return m
D=load('vault_disk_tests',INC/'usr/lib/core-vault-installer/disk_safety.py')
T=load('vault_target_tests',INC/'usr/lib/core-vault-installer/target.py')

def disk():
    return {'name':'/dev/vda','type':'disk','tran':'virtio','ro':False,'rm':False,
        'size':24*1024**3,'serial':'CV_TEST_BIOS','wwn':None,'model':'VirtIO',
        'maj:min':'252:0','mountpoints':[None],'children':[]}

class DiskTests(unittest.TestCase):
    def check(self,node=None,**kw):
        return D.validate_tree(node or disk(),kw.get('sysfs','/sys/devices/pci/virtio/block/vda'),
            kw.get('holders',set()),kw.get('swaps',set()))
    def test_virtual_disk(self): self.assertEqual(self.check()['serial'],'CV_TEST_BIOS')
    def test_internal_sata(self):
        n=disk();n.update(name='/dev/sda',tran='sata');self.assertEqual(self.check(n)['name'],'/dev/sda')
    def test_nvme(self):
        n=disk();n.update(name='/dev/nvme0n1',tran='nvme');self.check(n)
    def test_usb(self):
        n=disk();n['tran']='usb'
        with self.assertRaises(D.UnsafeDisk):self.check(n)
    def test_usb_sysfs(self):
        with self.assertRaises(D.UnsafeDisk):self.check(sysfs='/sys/pci/usb1/1-2/block/vda')
    def test_readonly(self):
        n=disk();n['ro']=True
        with self.assertRaises(D.UnsafeDisk):self.check(n)
    def test_removable(self):
        n=disk();n['rm']=1
        with self.assertRaises(D.UnsafeDisk):self.check(n)
    def test_small(self):
        n=disk();n['size']=4*1024**3
        with self.assertRaises(D.UnsafeDisk):self.check(n)
    def test_no_identity(self):
        n=disk();n['serial']=''
        with self.assertRaises(D.UnsafeDisk):self.check(n)
    def test_whitespace_identity(self):
        n=disk();n['serial']='   '
        with self.assertRaises(D.UnsafeDisk):self.check(n)
    def test_partition(self):
        n=disk();n.update(name='/dev/vda1',type='part')
        with self.assertRaises(D.UnsafeDisk):self.check(n)
    def test_host_root(self):
        n=disk();n['mountpoints']=['/']
        with self.assertRaises(D.UnsafeDisk):self.check(n)
    def test_live_medium_mounted(self):
        n=disk();n['children']=[{'name':'/dev/vda1','type':'part','mountpoints':['/run/live/medium']}]
        with self.assertRaises(D.UnsafeDisk):self.check(n)
    def test_active_swap(self):
        with self.assertRaises(D.UnsafeDisk):self.check(swaps={'/dev/vda'})
    def test_holder(self):
        with self.assertRaises(D.UnsafeDisk):self.check(holders={'/dev/vda'})
    def test_mapped_child(self):
        n=disk();n['children']=[{'name':'/dev/dm-0','type':'crypt','mountpoints':[]}]
        with self.assertRaises(D.UnsafeDisk):self.check(n)
    def test_network(self):
        n=disk();n['tran']='iscsi'
        with self.assertRaises(D.UnsafeDisk):self.check(n)
    def test_changed_identity(self):
        n=disk();n['serial']='OTHER';self.assertNotEqual(self.check(n),self.check())
    def test_regular_file(self):
        with tempfile.NamedTemporaryFile() as f:
            with self.assertRaises((D.UnsafeDisk,OSError)):D.probe(f.name)

class TargetTests(unittest.TestCase):
    def test_refuse_running_root(self):
        with self.assertRaises(T.TargetError):T.validate_target('/')
    def test_refuse_relative_path(self):
        with self.assertRaises(T.TargetError):T.validate_target('tmp/target')
    def test_refuse_missing_target(self):
        with self.assertRaises(T.TargetError):T.validate_target(None)
    def test_refuse_unmounted_directory(self):
        with tempfile.TemporaryDirectory() as p:
            with self.assertRaises(T.TargetError):T.validate_target(p)
    def test_fstab_escape(self):
        s=T.add_fstab('UUID=x / ext4 defaults 0 1\n')
        self.assertIn('noswap',s)
        self.assertNotIn('/home/vault',s)
        self.assertNotIn('Private Workspace tmpfs',s)
    def test_no_swap(self):
        s=T.add_fstab('UUID=x / ext4 defaults 0 1\nUUID=y none swap sw 0 0\n')
        self.assertNotIn(' none swap ',s)
    def test_idempotent(self):
        s=T.add_fstab('UUID=x / ext4 defaults 0 1\n');self.assertEqual(T.add_fstab(s),s)
    def test_removable_mountpoint_metadata_uses_ram(self):
        source='UUID=root / ext4 defaults 0 1\nUUID=old /media ext4 defaults 0 2\n'
        rows=[line.split() for line in T.add_fstab(source).splitlines() if line and not line.startswith('#')]
        media=[row for row in rows if row[1]=='/media']
        self.assertEqual(len(media),1)
        self.assertEqual(media[0][:3],['tmpfs','/media','tmpfs'])
        self.assertTrue({'noswap','nosuid','nodev','noexec','mode=0755'}.issubset(media[0][3].split(',')))
        self.assertIn('UUID=root / ext4 defaults 0 1',T.add_fstab(source))
    def test_explicit_external_media_mount_is_preserved(self):
        source='UUID=root / ext4 defaults 0 1\nUUID=usb /media/vault/backup ext4 noauto,nosuid,nodev,noexec 0 0\n'
        self.assertIn('UUID=usb /media/vault/backup ext4 noauto,nosuid,nodev,noexec 0 0',T.add_fstab(source))
    def test_fstab_six_fields(self):
        s=T.add_fstab('UUID=x / ext4 defaults 0 1\n')
        for l in s.splitlines():
            if l and not l.startswith('#'):self.assertEqual(len(l.split()),6)
    def test_reject_volatile_home(self):
        with self.assertRaises(T.TargetError):T.add_fstab('tmpfs /home/vault tmpfs defaults 0 0\n')
    def test_reject_malformed(self):
        with self.assertRaises(T.TargetError):T.add_fstab('tmpfs /home/vault/Private Workspace tmpfs\n')
    def test_efi_preserved(self):
        rec='UUID=x /boot/efi vfat umask=0077 0 2\n';self.assertIn(rec,T.add_fstab(rec))
    def test_path_escape(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'escape').symlink_to('/etc')
            with self.assertRaises(T.TargetError):T.safe(root,'escape/hosts')
    def test_path_inside_target(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);self.assertEqual(T.safe(root,'etc/hosts'),root/'etc/hosts')

class SourceTests(unittest.TestCase):
    def test_two_choices_review(self):
        s=yaml.safe_load((INC/'etc/calamares/settings.conf').read_text());self.assertEqual(s['sequence'][0]['show'],['keyboard','partition','summary'])
    def test_immutable_source(self):
        s=yaml.safe_load((INC/'etc/calamares/modules/unpackfs.conf').read_text());self.assertEqual(s['unpack'][0]['source'],'/run/live/medium/live/filesystem.squashfs')
    def test_no_fde(self):
        s=yaml.safe_load((INC/'etc/calamares/modules/partition.conf').read_text());self.assertFalse(s['enableLuksAutomatedPartitioning']);self.assertEqual(s['userSwapChoices'],['none'])
    def test_guard_before_writes(self):
        s=(ROOT/'tools/core-vault/calamares/base_patch.py').read_text();self.assertIn('new CoreOfflineDiskGuard',s);self.assertIn('device filtering',s)
    def test_guard_validates_identity(self):
        s=(ROOT/'tools/core-vault/calamares/CoreOfflineGuard.h').read_text();self.assertIn('current != m_expected.value(n)',s);self.assertIn('m_nodes.size() != 1',s)
    def test_ack_reset(self):
        s=(ROOT/'tools/core-vault/calamares/patch_calamares_source.py').read_text();self.assertIn('consent->setChecked(false)',s);self.assertIn('return consent && consent->isChecked()',s)
    def test_no_renamed_service_fiction(self):
        s=(INC/'usr/lib/core-vault-installer/target.py').read_text();self.assertNotIn('core-vault-offline.service',s);self.assertIn('core-signer-offline.service',s)
    def test_installer_requires_live(self):
        s=(INC/'usr/local/sbin/core-vault-installer').read_text();self.assertIn('"boot=live" not in cmdline',s);self.assertIn('"core-vault.install=1" not in cmdline',s)
    def test_storage_refuses_fallback(self):
        s=(INC/'usr/local/bin/core-vault-storage-check').read_text();self.assertIn('check_storage()',s)
        runtime=(INC/'usr/lib/core-vault/runtime.py').read_text();self.assertIn("ram['fstype'] != 'tmpfs'",runtime);self.assertIn("home['fsroot'] != '/home'",runtime)
    def test_boot_routing_before_desktop(self):
        s=(INC/'usr/local/bin/core-vault-session').read_text();self.assertLess(s.index('core-vault.install=1'),s.index('core-vault-home'))
    def test_safe_vm(self):
        s=(ROOT/'tools/core-vault/vm-installer-test.sh').read_text();self.assertIn('-nic none',s);self.assertIn('qemu-img create -f qcow2',s);self.assertNotIn('file=/dev/',s);self.assertIn('-no-reboot',s)
    def test_no_host_packages_in_builder(self):
        s=(ROOT/'tools/core-vault/prepare-installer.sh').read_text();self.assertLess(s.index('chroot "$BUILDER"'),s.index('apt-get install'))
    def test_yaml_parses(self):
        for p in (INC/'etc/calamares').rglob('*.conf'):yaml.safe_load(p.read_text())
    def test_python_parses(self):
        for p in (INC/'usr/lib/core-vault-installer').rglob('*.py'):ast.parse(p.read_text())
    def test_installer_sudo_rule(self):
        subprocess.run(['/usr/sbin/visudo','-cf',str(INC/'etc/sudoers.d/80-core-vault-installer')],check=True,capture_output=True)

if __name__=='__main__':unittest.main(verbosity=2)
