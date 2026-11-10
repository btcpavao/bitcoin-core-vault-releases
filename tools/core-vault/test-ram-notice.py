#!/usr/bin/python3
"""Targeted detector and Home layout checks with disposable data only."""
import os,sys,runpy,tempfile,unittest,time,json
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
ROOT=Path(__file__).resolve().parents[2]
LIB=ROOT/'tools/core-vault/runtime-template/usr/lib/core-vault'
sys.path.insert(0,str(LIB))
import ram_notice as rn

class Detection(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.root=Path(self.temp.name);self.home=self.root/'home';self.home.mkdir()
  self.ram=self.root/'ram';self.ram.mkdir();self.tmp=self.root/'tmp';self.tmp.mkdir()
  self.roots=((self.home,'home',True),(self.ram,'session',True),(self.tmp,'scratch',False))
 def scan(self,**kwargs):
  return rn.scan_roots(self.roots,uid=os.getuid(),root_check=lambda *_:True,**kwargs)
 def make(self,relative,root=None):
  p=(root or self.home)/relative;p.parent.mkdir(parents=True,exist_ok=True);p.touch();return p
 def test_clean_start_and_empty_directories(self):
  for name in ('Private Workspace','.bitcoin/wallets','Documents','Desktop'): (self.home/name).mkdir(parents=True)
  self.assertEqual(self.scan(),'empty')
 def test_wallet_private_workspace_home_and_nested_hidden_files(self):
  for name in ('.bitcoin/wallets/example/wallet.dat','Private Workspace/imported.gpg','notes.txt','Documents/recovery','Downloads/public.dat','.personal/secret.kdbx','Private Workspace/.hidden'):
   with self.subTest(name=name):
    p=self.make(name);self.assertEqual(self.scan(),'files');p.unlink();self.assertEqual(self.scan(),'empty')
 def test_zero_byte_and_read_only_files_are_not_missed(self):
  p=self.make('Private Workspace/empty.txt');p.chmod(0o000)
  self.assertEqual(self.scan(),'files');p.chmod(0o600)
 def test_automatic_core_and_desktop_metadata_are_excluded(self):
  for name in ('.profile','.bashrc','.Xauthority','.xsession-errors','.config/Bitcoin/Bitcoin-Qt.conf','.cache/thumbnails/thumb.png','.local/state/session.json','.bitcoin/debug.log','.bitcoin/settings.json','.bitcoin/.cookie','.bitcoin/peers.dat','.bitcoin/blocks/index/CURRENT','.bitcoin/chainstate/CURRENT'):
   self.make(name)
  self.assertEqual(self.scan(),'empty')
  self.make('.bitcoin/wallets/test/wallet.dat');self.assertEqual(self.scan(),'files')
 def test_home_restart_does_not_baseline_away_existing_wallet(self):
  self.make('.bitcoin/wallets/existing/wallet.dat');self.assertEqual(self.scan(),'files');self.assertEqual(self.scan(),'files')
 def test_scratch_and_export_data_are_included(self):
  for root,name in ((self.ram,'export/wallet.dat'),(self.ram,'tmp/document.txt'),(self.ram,'extra/secret.kdbx'),(self.tmp,'notes.txt')):
   p=self.make(name,root);self.assertEqual(self.scan(),'files');p.unlink()
 def test_internal_state_and_core_runtime_log_are_excluded(self):
  for name in ('state/exports.json','state/exports.new','state/core-runtime/core-vault-hide-sync.log'):
   self.make(name,self.ram)
  self.assertEqual(self.scan(),'empty')
 def test_external_files_and_symlink_targets_are_not_scanned(self):
  external=self.root/'external';external.mkdir();(external/'wallet.dat').touch()
  (self.home/'usb').symlink_to(external,target_is_directory=True)
  (self.home/'file-link').symlink_to(external/'wallet.dat')
  self.assertEqual(self.scan(),'empty')
 def test_fifo_socket_and_special_objects_do_not_block_or_trigger(self):
  os.mkfifo(self.home/'fifo');self.assertEqual(self.scan(),'empty')
 def test_nested_mount_refused_even_on_same_filesystem(self):
  child=self.home/'nested';child.mkdir();(child/'external.txt').touch()
  original=rn._mount_id
  def identity(fd):
   return original(fd)+1 if os.fstat(fd).st_ino==child.stat().st_ino else original(fd)
  with patch.object(rn,'_mount_id',side_effect=identity):self.assertEqual(self.scan(),'empty')
 def test_budget_or_unavailable_root_is_never_empty(self):
  (self.home/'a').mkdir();self.assertEqual(self.scan(max_entries=0),'unknown')
  self.assertEqual(self.scan(seconds=0),'unknown')
  bad=((self.root/'missing','home',True),)
  self.assertEqual(rn.scan_roots(bad,uid=os.getuid(),root_check=lambda *_:True),'unknown')
 def test_root_validation_refuses_disk_fallback(self):
  self.assertEqual(rn.scan_roots(self.roots,uid=os.getuid(),root_check=lambda *_:False),'unknown')
 def test_no_regular_file_content_is_opened(self):
  self.make('Private Workspace/secret-file.dat')
  original=rn.os.open
  def directory_only(path,flags,*args,**kwargs):
   self.assertTrue(flags & os.O_DIRECTORY);self.assertTrue(flags & os.O_NOFOLLOW)
   return original(path,flags,*args,**kwargs)
  with patch.object(rn.os,'open',side_effect=directory_only):self.assertEqual(self.scan(),'files')
 def test_unknown_hidden_user_folder_and_trash_files_still_count(self):
  for name in ('.private/backup.dat','.local/share/custom-notes/plan','.local/share/Trash/files/notes.txt'):
   p=self.make(name);self.assertEqual(self.scan(),'files');p.unlink()
 def test_names_or_counts_are_not_exposed_and_removing_files_clears(self):
  p=self.make('Private Workspace/very-private-name.txt')
  result=self.scan();self.assertEqual(result,'files');self.assertNotIn(p.name,result)
  p.unlink();self.assertEqual(self.scan(),'empty')

class HomeReminder(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  from PySide6.QtWidgets import QApplication
  cls.app=QApplication.instance() or QApplication([])
  cls.app.setStyle('Fusion')
  with patch.object(sys,'argv',['core-vault-home','--self-test','--assets',str(ROOT/'tools/core-vault/runtime-template/usr/share/core-vault')]):
   cls.g=runpy.run_path(str(ROOT/'tools/core-vault/runtime-template/usr/local/bin/core-vault-home'))
 def make_home(self):
  h=self.g['VaultHome']();h.reaper.stop();h.show();return h
 def settle(self):
  for _ in range(18):self.app.processEvents();time.sleep(.002)
 def cleanup(self,h):
  h.stop_ram_notice();h.hide();h.deleteLater();self.app.processEvents()
 def test_empty_hidden_then_files_visible_without_card_jump(self):
  h=self.make_home()
  try:
   self.settle();h.update_ram_notice('empty');self.settle()
   before=[c.geometry().getRect() for c in h.cards]
   self.assertTrue(h.ram_notice.isHidden())
   h.update_ram_notice('files');self.settle();self.assertTrue(h.ram_notice.isVisible())
   self.assertEqual(before,[c.geometry().getRect() for c in h.cards])
   self.assertEqual(h.ram_notice.text(),rn.NOTICE)
   h.update_ram_notice('unknown');self.settle();self.assertTrue(h.ram_notice.isVisible())
   h.update_ram_notice('empty');self.settle();self.assertTrue(h.ram_notice.isHidden())
  finally:self.cleanup(h)
 def test_centering_and_readability_all_screen_sizes(self):
  from PySide6.QtCore import QPoint
  h=self.make_home()
  try:
   for width,height in ((800,600),(1024,768),(1280,800),(1366,768),(1920,1080)):
    h._test_size=(width,height);h.fit_screen();h.update_ram_notice('files');self.settle()
    top=max(c.mapTo(h,QPoint(0,c.height())).y() for c in h.cards)
    bottom=h.debian_logo.mapTo(h,QPoint()).y();y=h.ram_notice.y();z=y+h.ram_notice.height()
    self.assertLessEqual(abs((y-top)-(bottom-z)),2,(width,y,top,bottom,z))
    self.assertGreaterEqual(y-top,8,(width,y,top,bottom,z))
    self.assertGreaterEqual(bottom-z,8)
    self.assertEqual(h.scroll.verticalScrollBar().maximum(),0,(width,height))
    self.assertFalse(h.notice_position_timer.isActive(),'Geometry timer must settle')
    self.assertLessEqual(h.ram_notice.heightForWidth(h.ram_notice.width()),h.ram_notice.height())
  finally:self.cleanup(h)
 def test_worker_returns_without_blocking_ui(self):
  h=self.make_home()
  try:
   with patch.dict(self.g['RamNoticeWorker'].run.__globals__,session_files=lambda:'files'):
    h.poll_ram_notice();deadline=time.monotonic()+3
    while h.notice_job is not None and time.monotonic()<deadline:self.settle()
   self.assertIsNone(h.notice_job);self.assertTrue(h.ram_notice.isVisible())
  finally:self.cleanup(h)

if __name__=='__main__':unittest.main(verbosity=2)
