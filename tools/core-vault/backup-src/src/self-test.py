#!/usr/bin/python3
"""Real nested GnuPG/TAR tests. Disposable synthetic inputs, private tmpfs only."""
from pathlib import Path
import hashlib
import io
import os
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import layered_backend as layers
import gpg_backend as gpg
import backup

RAM_ROOT = Path('/dev/shm')


class LayerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='vault-layer-test-', dir=RAM_ROOT)
        self.root = Path(self.tmp.name)
        self.inputs = self.root / 'inputs'
        self.inputs.mkdir(mode=0o700)
        self.workspace = self.root / 'workspace'
        self.workspace.mkdir(mode=0o700)
        self.source = self.inputs / 'čitanje.txt'
        self.source.write_bytes(b'synthetic data only\0' + os.urandom(1024))
        self.secrets = ['synthetic secret alpha', 'different synthetic beta', ' treći synthetic ž ']

    def tearDown(self):
        self.tmp.cleanup()

    def create(self, count=1, items=None):
        secrets = ['independent synthetic layer ' + str(i) + ' ž ' for i in range(count)]
        path = self.root / 'backup.gpg'
        layers.create_layers(items or [self.source], path, secrets, ram_root=self.root)
        return path, secrets

    def recover(self, path, secrets, **kw):
        return layers.recover_files(path, self.workspace / 'recovered', secrets,
                                   ram_root=self.root, workspace=self.workspace, **kw)

    def assert_clean(self):
        self.assertFalse(list(self.root.glob('layers-*')))
        self.assertFalse(list(self.root.glob('.vault-gpg-*')))
        self.assertFalse(list(self.workspace.glob('.recover-*')))

    def test_one_layer(self):
        self.roundtrip(1)

    def test_two_layers(self):
        self.roundtrip(2)

    def test_three_layers(self):
        self.roundtrip(3)

    def test_six_layers(self):
        self.roundtrip(6)

    def test_ten_layers_any_order(self):
        self.roundtrip(10)

    def roundtrip(self, count):
        folder = self.inputs / 'folder'
        folder.mkdir()
        (folder / 'original.gpg').write_bytes(b'An original GPG filename is not a layer')
        empty = folder / 'empty'
        empty.mkdir()
        original = self.source.read_bytes()
        path, secrets = self.create(count, [self.source, folder])
        self.assertNotIn(self.source.name.encode(), path.read_bytes())
        out = self.recover(path, secrets[::2] + secrets[1::2])
        self.assertEqual((out / self.source.name).read_bytes(), original)
        self.assertEqual((out / 'folder/original.gpg').read_bytes(), (folder / 'original.gpg').read_bytes())
        self.assertTrue((out / 'folder/empty').is_dir())
        self.assertEqual(self.source.read_bytes(), original)
        self.assert_clean()

    def test_original_real_gpg_stops_at_tar(self):
        inner = self.inputs / 'original.gpg'
        gpg.encrypt_file(self.source, inner, 'original file secret', ram_root=self.root)
        path, secrets = self.create(2, [inner])
        out = self.recover(path, secrets)
        self.assertEqual((out / 'original.gpg').read_bytes(), inner.read_bytes())

    def test_original_tar_is_preserved(self):
        inner = self.inputs / 'original.tar'
        layers.package([self.source], inner, limit=layers.MAX_BYTES, budget=layers.Budget())
        path, secrets = self.create(items=[inner])
        out = self.recover(path, secrets)
        self.assertEqual((out / 'original.tar').read_bytes(), inner.read_bytes())

    def test_wrong_missing_duplicate_and_retry(self):
        path, secrets = self.create(3)
        for supplied in (['wrong'], secrets[:1]):
            with self.assertRaises(layers.MorePassphrases):
                self.recover(path, supplied)
            self.assertFalse((self.workspace / 'recovered').exists())
            self.assert_clean()
        with self.assertRaises(layers.LayerError):
            self.recover(path, secrets + [secrets[0]])
        out = self.recover(path, list(reversed(secrets)))
        self.assertTrue((out / self.source.name).is_file())

    def test_unicode_secret_and_filename(self):
        path = self.root / 'unicode.gpg'
        layers.create_layers([self.source], path, self.secrets, ram_root=self.root)
        out = self.recover(path, list(reversed(self.secrets)))
        self.assertEqual((out / self.source.name).read_bytes(), self.source.read_bytes())

    def test_damage_and_truncation_no_publication(self):
        path, secrets = self.create()
        data = path.read_bytes()
        for payload in (data[:-1], data[:30], data[:len(data)//2] + bytes([data[len(data)//2] ^ 1]) + data[len(data)//2+1:]):
            path.write_bytes(payload)
            with self.assertRaises(layers.LayerError):
                self.recover(path, secrets)
            self.assertFalse((self.workspace / 'recovered').exists())
            self.assert_clean()

    def test_ordinary_gpg_requires_explicit_mode(self):
        path = self.root / 'ordinary.gpg'
        gpg.encrypt_file(self.source, path, self.secrets[0], ram_root=self.root)
        with self.assertRaises(layers.MorePassphrases):
            self.recover(path, self.secrets[:1])
        out = self.recover(path, self.secrets[:1], ordinary=True)
        self.assertEqual((out / 'recovered-file').read_bytes(), self.source.read_bytes())

    def test_plaintext_is_not_accepted(self):
        with self.assertRaises(layers.MorePassphrases):
            self.recover(self.source, self.secrets)
        self.assert_clean()

    def test_malicious_tar_paths_links_duplicates_and_sparse(self):
        for name, kind in [('../escape', tarfile.REGTYPE), ('/absolute', tarfile.REGTYPE),
                           ('a/../../escape', tarfile.REGTYPE), ('a\\escape', tarfile.REGTYPE),
                           ('link', tarfile.SYMTYPE), ('hardlink', tarfile.LNKTYPE),
                           ('device', tarfile.CHRTYPE), ('pipe', tarfile.FIFOTYPE),
                           ('sparse', tarfile.GNUTYPE_SPARSE)]:
            path = self.root / 'malicious.tar'
            with tarfile.open(path, 'w') as tar:
                entry = tarfile.TarInfo(name); entry.type = kind;entry.linkname = '../escape'
                tar.addfile(entry, io.BytesIO(b''))
            with self.subTest(name=name), self.assertRaises(layers.LayerError):
                layers.inspect_tar(path, limit=layers.MAX_BYTES, budget=layers.Budget())
        path = self.root / 'duplicate.tar'
        with tarfile.open(path, 'w') as tar:
            for _ in range(2):
                tar.addfile(tarfile.TarInfo('duplicate'))
        with self.assertRaises(layers.LayerError):
            layers.inspect_tar(path, limit=layers.MAX_BYTES, budget=layers.Budget())

    def test_tar_trailing_data_rejected(self):
        path=self.root/'payload.tar'
        layers.package([self.source],path,limit=layers.MAX_BYTES,budget=layers.Budget())
        with path.open('ab') as out:out.write(b'X'*512)
        with self.assertRaises(layers.LayerError):
            layers.inspect_tar(path,limit=layers.MAX_BYTES,budget=layers.Budget())

    def test_unsafe_source_and_destination(self):
        link=self.inputs/'link';link.symlink_to(self.source)
        with self.assertRaises((layers.LayerError,gpg.GPGError)):
            self.create(items=[link])
        path,secrets=self.create()
        with self.assertRaises(layers.LayerError):
            layers.recover_files(path,self.root/'escape',secrets,ram_root=self.root,workspace=self.workspace)
        out=self.recover(path,secrets)
        with self.assertRaises(layers.LayerError):
            self.recover(path,secrets)
        self.assertTrue(out.is_dir())

    def test_budget_and_cancel_cleanup(self):
        class Cancelled(Exception):pass
        class Stop:
            def check(self):raise Cancelled()
        with self.assertRaises(Cancelled):
            layers.create_layers([self.source],self.root/'cancel.gpg',self.secrets,ram_root=self.root,progress=Stop())
        with patch.object(layers,'MAX_BYTES',1024):
            with self.assertRaises(layers.LayerError):
                self.create()
        self.assertFalse((self.root/'cancel.gpg').exists())
        self.assertFalse((self.root/'backup.gpg').exists())
        self.assert_clean()

    def test_gpg_output_limit(self):
        cipher=self.root/'large.gpg';plain=self.root/'too-large'
        gpg.encrypt_file(self.source,cipher,self.secrets[0],ram_root=self.root)
        with self.assertRaises(gpg.GPGError):
            gpg.decrypt_file(cipher,plain,self.secrets[0],ram_root=self.root,max_output_bytes=16)
        self.assertFalse(plain.exists())

    def test_deterministic_tar(self):
        a,b=self.root/'a.tar',self.root/'b.tar'
        for path in (a,b):
            layers.package([self.source],path,limit=layers.MAX_BYTES,budget=layers.Budget())
        self.assertEqual(a.read_bytes(),b.read_bytes())

    def test_standard_gnupg_tar_independent_recovery(self):
        path,secrets=self.create(3)
        # These stock commands do not call the application's decryption/extraction.
        with tempfile.TemporaryDirectory(dir=self.root) as directory:
            work=Path(directory);current=path
            for number,secret in enumerate(reversed(secrets)):
                read,write=os.pipe()
                try:
                    os.write(write,secret.encode()+b'\n');os.close(write);write=None
                    output=work/str(number)
                    env=dict(PATH='/usr/bin:/bin',HOME=str(work),GNUPGHOME=str(work),TMPDIR=str(work),LANG='C.UTF-8')
                    run=subprocess.run(['/usr/bin/gpg','--no-options','--homedir',str(work),
                        '--batch','--no-tty','--no-autostart','--pinentry-mode','loopback',
                        '--no-symkey-cache','--passphrase-fd',str(read),'--output',str(output),
                        '--decrypt',str(current)],pass_fds=(read,),env=env,
                        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30)
                    self.assertEqual(run.returncode,0)
                    current=output
                finally:
                    os.close(read)
                    if write is not None:os.close(write)
            recovered=work/'stock-tar';recovered.mkdir()
            subprocess.run(['/usr/bin/tar','--extract','--file',str(current),
                '--directory',str(recovered),'--no-same-owner','--no-same-permissions'],check=True,
                stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=15)
            self.assertEqual((recovered/self.source.name).read_bytes(),self.source.read_bytes())


if __name__ == '__main__':
    import argparse, sys
    parser=argparse.ArgumentParser()
    parser.add_argument('--ram-root',type=Path,default=RAM_ROOT)
    args=parser.parse_args()
    RAM_ROOT=args.ram_root
    backup.harden()
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(LayerTests))
    if result.wasSuccessful():
        print('VAULT MULTILAYER GPG TAR SELF-TEST PASSED')
    sys.exit(0 if result.wasSuccessful() else 1)
