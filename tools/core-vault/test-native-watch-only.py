#!/usr/bin/python3
"""Core 32.1 native watch-only export/restore and PSBT regression.

Disposable synthetic wallets in RAM, isolated network namespace via bwrap.
Run with --core-bin pointing to the verified upstream bin directory.
This application test does not certify the final ISO storage policy or GUI.
"""
import argparse, json, os, socket, subprocess, tempfile, time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--core-bin', required=True, type=Path)
    parser.add_argument('--isolated', action='store_true')
    args = parser.parse_args()
    if not args.isolated:
        subprocess.run(['bwrap', '--unshare-all', '--die-with-parent',
                        '--ro-bind', '/', '/', '--proc', '/proc', '--dev', '/dev',
                        '--tmpfs', '/tmp', '--tmpfs', '/run', '--tmpfs', '/home',
                        '--tmpfs', '/dev/shm', '--tmpfs', '/opt',
                        '--ro-bind', str(Path(__file__).resolve()), '/opt/test-native.py',
                        '--ro-bind', str(args.core_bin.resolve().parent), '/opt/bitcoin',
                        '/usr/bin/python3', '/opt/test-native.py',
                        '--core-bin', '/opt/bitcoin/bin', '--isolated'],
                       check=True, timeout=180)
        return
    os.umask(0o077)
    with tempfile.TemporaryDirectory(prefix='native-watch-', dir='/dev/shm') as temp:
        root = Path(temp)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
        proc = subprocess.Popen([str(args.core_bin/'bitcoind'), '-datadir='+temp,
            '-regtest', '-networkactive=0', '-listen=0', '-server',
            '-rpcport='+str(port), '-debuglogfile=0', '-printtoconsole=0', '-dbcache=32'],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        def rpc(method, *params, wallet=None):
            cmd = [str(args.core_bin/'bitcoin-cli'), '-datadir='+temp, '-regtest',
                   '-rpcport='+str(port), '-stdin']
            if wallet is not None: cmd.append('-rpcwallet='+wallet)
            cmd.append(method)
            data = ''.join((p if isinstance(p, str) else json.dumps(p))+'\n' for p in params)
            result = subprocess.run(cmd, input=data, capture_output=True, text=True, timeout=45)
            if result.returncode: raise RuntimeError(method+': '+result.stderr)
            try: return json.loads(result.stdout)
            except ValueError: return result.stdout.strip()
        try:
            for _ in range(150):
                if proc.poll() is not None: raise RuntimeError(proc.stderr.read().decode())
                try:
                    assert rpc('getnetworkinfo')['version'] == 320100
                    break
                except RuntimeError: time.sleep(.1)
            else: raise RuntimeError('Core did not become ready')
            secret = 'disposable test wallet passphrase'
            rpc('createwallet', 'signer', False, False, secret)
            addresses = {}
            for kind in ('legacy', 'p2sh-segwit', 'bech32', 'bech32m'):
                addresses[kind] = rpc('getnewaddress', 'retained-label-'+kind, kind, wallet='signer')
                rpc('getrawchangeaddress', kind, wallet='signer')
            rpc('generatetoaddress', 101, addresses['bech32'])
            assert rpc('getwalletinfo', wallet='signer')['unlocked_until'] == 0
            export = root/'watch-only.dat'
            rpc('exportwatchonlywallet', str(export), wallet='signer')
            assert export.read_bytes().startswith(b'SQLite format 3\x00')
            rpc('restorewallet', 'watch', str(export))
            info = rpc('getwalletinfo', wallet='watch')
            assert info['private_keys_enabled'] is False and info['descriptors'] is True
            assert info['txcount'] > 0
            for kind, address in addresses.items():
                assert address in rpc('getaddressesbylabel', 'retained-label-'+kind, wallet='watch')
                assert rpc('getaddressinfo', address, wallet='watch')['solvable']
            for kind in addresses:
                assert rpc('getnewaddress', '', kind, wallet='watch') == rpc('getnewaddress', '', kind, wallet='signer')
                assert rpc('getrawchangeaddress', kind, wallet='watch') == rpc('getrawchangeaddress', kind, wallet='signer')
            try:
                rpc('listdescriptors', True, wallet='watch')
            except RuntimeError as exc:
                assert "Can't get private descriptor string for watch-only wallets" in str(exc)
            else: raise AssertionError('Watch-only wallet exposed private descriptors')
            public = json.dumps(rpc('listdescriptors', False, wallet='watch'))
            assert 'tprv' not in public and 'xprv' not in public and secret not in public
            print('PASS: locked signer exports native database; restore preserves public derivations, labels and history', flush=True)
            rpc('createwallet', 'recipient')
            recipient = rpc('getnewaddress', wallet='recipient')
            funded = rpc('walletcreatefundedpsbt', [], {recipient:1}, 0,
                         {'includeWatching':True, 'fee_rate':2}, True, wallet='watch')
            unsigned = funded['psbt']
            assert rpc('walletprocesspsbt', unsigned, wallet='watch')['complete'] is False
            rpc('walletpassphrase', secret, 30, wallet='signer')
            try: signed = rpc('walletprocesspsbt', unsigned, wallet='signer')
            finally: rpc('walletlock', wallet='signer')
            assert signed['complete'] is True
            final = rpc('finalizepsbt', signed['psbt'])
            assert final['complete'] is True
            assert rpc('testmempoolaccept', [final['hex']])[0]['allowed'] is True
            txid = rpc('sendrawtransaction', final['hex'])
            assert txid in rpc('getrawmempool')
            assert rpc('getnetworkinfo')['connections'] == 0
            print('PASS: watch-only cannot sign; restored public wallet prepares PSBT; signer signs and Core accepts', flush=True)
            rpc('stop'); proc.wait(timeout=20)
        finally:
            if proc.poll() is None:
                proc.terminate()
                try: proc.wait(timeout=10)
                except subprocess.TimeoutExpired: proc.kill(); proc.wait()


if __name__ == '__main__': main()
