#!/usr/bin/python3
"""Real GPG profile acceptance using new synthetic data in private tmpfs only."""
from pathlib import Path
import argparse
import os
import subprocess
import tempfile
from gpg_backend import GPGError, _path, _private_directory, decrypt_file, encrypt_file


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ram-root',type=Path,default=Path('/dev/shm'))
    args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='vault-gpg-self-test-',dir=args.ram_root) as temporary:
        root=Path(temporary);source=root/'synthetic wallet.dat';cipher=root/'synthetic.gpg';plain=root/'recovered'
        descriptor=_private_directory(_path(root));os.close(descriptor)
        payload=b'Only disposable GPG self-test data\0\n'+os.urandom(128*1024)
        source.write_bytes(payload)
        phrase='  amber basil cedar delta ember forest ž密碼  '
        assert encrypt_file(source,cipher,phrase,ram_root=root)=='AES256-MDC'
        assert decrypt_file(cipher,plain,phrase,ram_root=root)=='AES256-MDC'
        assert plain.read_bytes()==payload;plain.unlink()
        assert not cipher.read_bytes().startswith(b'-----BEGIN')
        def rejected(file,password):
            try:decrypt_file(file,plain,password,ram_root=root)
            except GPGError:pass
            else:raise RuntimeError('GPG accepted an invalid synthetic backup.')
            assert not plain.exists()
        rejected(cipher,'different synthetic passphrase')
        data=cipher.read_bytes()
        altered=bytearray(data);altered[len(altered)//2]^=1
        damaged=root/'altered.gpg';damaged.write_bytes(altered);rejected(damaged,phrase)
        damaged.write_bytes(data[:-1]);rejected(damaged,phrase)
        literal=root/'not-encrypted.gpg'
        with tempfile.TemporaryDirectory(dir=root) as home:
            subprocess.run(['/usr/bin/gpg','--no-options','--homedir',home,'--batch','--no-tty',
                            '--no-autostart','--disable-dirmngr','--output',str(literal),
                            '--store','--',str(source)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                           env=dict(PATH='/usr/bin:/bin',HOME=home,TMPDIR=home,LANG='C.UTF-8'),timeout=15)
        rejected(literal,phrase)
        assert source.read_bytes()==payload
        assert not list(root.glob('.vault-gpg-*'))
    print('VAULT REAL GPG AES256-MDC ROUNDTRIP AND AUTHENTICATION TESTS PASSED')
    return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except (GPGError,OSError,RuntimeError,AssertionError,subprocess.SubprocessError):
        print('VAULT REAL GPG SELF-TEST FAILED')
        raise SystemExit(1)
