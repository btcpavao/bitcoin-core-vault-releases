import ast,copy,hashlib,importlib.util,json,os,shutil,subprocess,tempfile,unittest
from pathlib import Path
B=Path(__file__).resolve().parents[1]
# In the applied project tools/ layout, payload paths live in ../../config.
PAYLOAD=B/'payload/config/includes.chroot'
if not PAYLOAD.exists(): PAYLOAD=B.parents[1]/'config/includes.chroot'

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
D=load('disk_safety',PAYLOAD/'usr/lib/core-offline-installer/disk_safety.py')
T=load('target',PAYLOAD/'usr/lib/core-offline-installer/target.py')

def disk(): return {'name':'/dev/vda','type':'disk','tran':'virtio','ro':False,'rm':False,
                   'size':24*1024**3,'serial':'CO_TEST_BIOS','wwn':None,'model':'VirtIO',
                   'maj:min':'252:0','mountpoints':[None], 'children':[]}
class DiskTests(unittest.TestCase):
    def valid(self,n,**kw): return D.validate_tree(n,kw.get('sysfs','/sys/devices/pci/virtio0/block/vda'),kw.get('holders',set()),kw.get('swaps',set()))
    def test_valid_internal(self): self.assertEqual(self.valid(disk())['serial'],'CO_TEST_BIOS')
    def test_usb(self):
        n=disk();n['tran']='usb'
        with self.assertRaises(D.UnsafeDisk): self.valid(n)
    def test_usb_sysfs_even_missing_transport(self):
        with self.assertRaises(D.UnsafeDisk): self.valid(disk(),sysfs='/sys/devices/pci/usb1/1-1/block/vda')
    def test_read_only(self):
        n=disk();n['ro']=True
        with self.assertRaises(D.UnsafeDisk): self.valid(n)
    def test_removable(self):
        n=disk();n['rm']='1'
        with self.assertRaises(D.UnsafeDisk): self.valid(n)
    def test_small(self):
        n=disk();n['size']=8*1024**3
        with self.assertRaises(D.UnsafeDisk): self.valid(n)
    def test_no_stable_id(self):
        n=disk();n['serial']=''
        with self.assertRaises(D.UnsafeDisk): self.valid(n)
    def test_partition_rejected(self):
        n=disk();n['name']='/dev/vda1';n['type']='part'
        with self.assertRaises(D.UnsafeDisk): self.valid(n)
    def test_root_disk_mounted(self):
        n=disk();n['mountpoints']=['/']
        with self.assertRaises(D.UnsafeDisk): self.valid(n)
    def test_child_mounted(self):
        n=disk();n['children']=[{'name':'/dev/vda1','type':'part','mountpoints':['/media/signer/test']}]
        with self.assertRaises(D.UnsafeDisk): self.valid(n)
    def test_active_swap(self):
        with self.assertRaises(D.UnsafeDisk): self.valid(disk(),swaps={'/dev/vda'})
    def test_holders(self):
        with self.assertRaises(D.UnsafeDisk): self.valid(disk(),holders={'/dev/vda'})
    def test_mapped_child(self):
        n=disk();n['children']=[{'name':'/dev/dm-0','type':'crypt','mountpoints':[]}]
        with self.assertRaises(D.UnsafeDisk): self.valid(n)
    def test_iscsi(self):
        n=disk();n['tran']='iscsi'
        with self.assertRaises(D.UnsafeDisk): self.valid(n)
    def test_identity_changes(self):
        a=disk();b=disk();b['serial']='DIFFERENT'
        self.assertNotEqual(self.valid(a),self.valid(b))
    def test_file_not_block_device(self):
        with tempfile.NamedTemporaryFile() as f:
            with self.assertRaises((D.UnsafeDisk,OSError)): D.probe(f.name)
class TargetTests(unittest.TestCase):
    def test_refuse_host_root(self):
        with self.assertRaises(T.TargetError): T.validate_target('/')
    def test_refuse_unmounted_directory(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(T.TargetError): T.validate_target(d)
    def test_swap_removed(self):
        s=T.add_fstab('UUID=a / ext4 defaults 0 1\nUUID=b none swap sw 0 0\n')
        self.assertNotIn(' none swap ',s);self.assertIn('tmpfs /home/signer',s)
    def test_fstab_idempotent(self):
        s=T.add_fstab('UUID=a / ext4 defaults 0 1\n')
        # Mount records must not duplicate even if human comments are retained.
        self.assertEqual(T.add_fstab(s).count('tmpfs /home/signer'),1)
        self.assertEqual(T.add_fstab(s).count('tmpfs /var/log'),1)
class BundleTests(unittest.TestCase):
    def test_sequence_only_two_config_pages(self):
        import yaml
        c=yaml.safe_load((PAYLOAD/'etc/calamares/settings.conf').read_text())
        self.assertEqual(c['sequence'][0]['show'],['keyboard','partition','summary'])
        self.assertTrue(c['prompt-install'])
        self.assertEqual(c['sequence'][1]['exec'][0],'partition')
    def test_yaml_valid(self):
        import yaml
        for p in (PAYLOAD/'etc/calamares').rglob('*.conf'): yaml.safe_load(p.read_text())
    def test_python_syntax(self):
        for p in (PAYLOAD/'usr/lib/core-offline-installer').rglob('*.py'): ast.parse(p.read_text())
        ast.parse((PAYLOAD/'usr/local/sbin/core-offline-installer').read_text())
    def test_shell_syntax(self):
        for p in B.rglob('*'):
            if not p.is_file() or '__pycache__' in p.parts: continue
            b=p.read_bytes()
            if b.startswith(b'#!/bin/sh'): subprocess.run(['/bin/sh','-n',str(p)],check=True)
            if b.startswith(b'#!/bin/bash'): subprocess.run(['/bin/bash','-n',str(p)],check=True)
    def test_narrow_installer_sudoers_syntax(self):
        exe=shutil.which('visudo')
        if not exe: self.skipTest('visudo unavailable')
        subprocess.run([exe,'-cf',str(PAYLOAD/'etc/sudoers.d/80-core-offline-installer')],check=True,capture_output=True)
    def test_no_wallet_paths_in_installer(self):
        s=(PAYLOAD/'etc/calamares/modules/unpackfs.conf').read_text()
        self.assertIn('/run/live/medium/live/filesystem.squashfs',s)
        self.assertNotIn('source: /\n',s)
    def test_normal_entry_preserves_session(self):
        s=(PAYLOAD/'usr/local/bin/core-offline-entry').read_text()
        self.assertIn('*) exec /usr/local/bin/core-signer-session ;;',s)
        self.assertIn('core-offline.install=1',s)
    def test_root_entry_checks_live_flag(self):
        s=(PAYLOAD/'usr/local/sbin/core-offline-installer').read_text()
        self.assertIn("'boot=live' not in cmdline",s)
        self.assertIn("'core-offline.install=1' not in cmdline",s)
        self.assertIn('SUDO_UID',s)
if __name__=='__main__': unittest.main(verbosity=2)
