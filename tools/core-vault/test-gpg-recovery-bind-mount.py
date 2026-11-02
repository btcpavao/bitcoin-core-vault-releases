#!/usr/bin/python3
"""Regression for GPG recovery across Vault's real RAM HOME bind mount.

Runs only inside an ordinary disposable Vault guest. The caller supplies the
reviewed fixed backup.py as a public fixture; no installed files are changed.
Dialogs are substituted explicitly. This is not native GUI or ISO acceptance.
"""
from pathlib import Path
import errno, hashlib, importlib.util, json, sys, uuid

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

def main():
    assert sys.argv[1:] == ['--guest']
    sys.path.insert(0, '/usr/lib/core-vault-backup')
    sys.path.insert(0, '/usr/lib/core-vault')
    import runtime as policy
    import recovery_dialog, gpg_backend
    policy.check_storage()
    original = load('bind_original_backup', '/usr/lib/core-vault-backup/backup.py')
    fixed = load('bind_fixed_backup', '/media/vault/VAULT_CI/ci-fixed-backup.py')
    workspace = original.verified_workspace()
    root = policy.ROOT / 'export'
    nonce = uuid.uuid4().hex
    prefix = 'ci-bind-recovery-' + nonce
    source = root / (prefix + '.txt')
    encrypted = root / (prefix + '.gpg')
    destination = workspace / (prefix + '.dat')
    bad_destination = workspace / (prefix + '-wrong.dat')
    cancel_destination = workspace / (prefix + '-cancel.dat')
    phrase = 'public regression only alpha bravo charlie delta echo foxtrot'
    expected = b'PUBLIC SYNTHETIC BIND MOUNT RECOVERY TEST\n' * 200
    result = {'scope': 'real mount/stock GPG regression, dialogs substituted',
              'source_sha256': hashlib.sha256(Path('/media/vault/VAULT_CI/ci-fixed-backup.py').read_bytes()).hexdigest(),
              'checks': []}
    class Progress:
        def check(self): pass
        def close(self): pass
        def update(self, *args): pass
    for module in (original, fixed):
        module.Progress = Progress
        module.message = lambda *args, **kwargs: None
    original_request = recovery_dialog.get_recovery_request
    try:
        source.write_bytes(expected)
        source.chmod(0o600)
        gpg_backend.encrypt_file(source, encrypted, phrase, ram_root=root)
        encrypted_hash = hashlib.sha256(encrypted.read_bytes()).hexdigest()
        recovery_dialog.get_recovery_request = lambda *a, **k: (destination, phrase)
        try:
            original.decrypt_gpg_ui([str(encrypted)])
        except OSError as error:
            assert error.errno == errno.EXDEV, error.errno
            assert not destination.exists()
            result['checks'].append({'check': 'baseline-cross-bind-publication-fails-with-EXDEV', 'status': 'PASS'})
        else:
            raise RuntimeError('Baseline did not reproduce the expected mount publication failure')
        fixed.decrypt_gpg_ui([str(encrypted)])
        assert destination.read_bytes() == expected
        result['checks'].append({'check': 'fixed-authenticated-recovery-publishes-exact-bytes-in-RAM', 'status': 'PASS'})
        try:
            fixed.decrypt_gpg_ui([str(encrypted)])
        except fixed.BackupError:
            assert destination.read_bytes() == expected
            result['checks'].append({'check': 'existing-output-refused-and-preserved', 'status': 'PASS'})
        else:
            raise RuntimeError('Existing output was accepted')
        recovery_dialog.get_recovery_request = lambda *a, **k: (bad_destination, 'wrong public regression phrase')
        try:
            fixed.decrypt_gpg_ui([str(encrypted)])
        except fixed.BackupError:
            assert not bad_destination.exists()
            result['checks'].append({'check': 'wrong-passphrase-publishes-nothing', 'status': 'PASS'})
        else:
            raise RuntimeError('Wrong phrase was accepted')
        recovery_dialog.get_recovery_request = lambda *a, **k: None
        try:
            fixed.decrypt_gpg_ui([str(encrypted)])
        except fixed.Cancelled:
            assert not cancel_destination.exists()
            result['checks'].append({'check': 'cancel-publishes-nothing', 'status': 'PASS'})
        else:
            raise RuntimeError('Cancelled request continued')
        assert hashlib.sha256(encrypted.read_bytes()).hexdigest() == encrypted_hash
        result['checks'].append({'check': 'original-encrypted-input-unchanged', 'status': 'PASS'})
        result['status'] = 'passed'
    finally:
        recovery_dialog.get_recovery_request = original_request
        for file in (source, encrypted, destination, bad_destination, cancel_destination):
            file.unlink(missing_ok=True)
    Path('/media/vault/VAULT_CI/bind-recovery-result.json').write_text(json.dumps(result, indent=2) + '\n')
    print('BIND RECOVERY REGRESSION DONE EXIT 0', flush=True)

if __name__ == '__main__':
    main()
