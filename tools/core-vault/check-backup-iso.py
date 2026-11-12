#!/usr/bin/python3
"""Read-only encrypted-backup ISO/SquashFS content check; never mounts it."""
from pathlib import Path
import argparse,hashlib,json,re,runpy,subprocess,tempfile

def check(squash):
    def get(path):
        return subprocess.check_output(['unsquashfs','-cat',str(squash),path],stderr=subprocess.PIPE,timeout=90)
    record=json.loads(get('etc/core-vault/backup-build.json'))
    if record.get('schema')!=3 or record.get('packages',{}).get('core-vault-backup')!='0.7.4':
        raise RuntimeError('Unexpected backup module build record')
    required={'usr/bin/core-vault-backup','usr/lib/core-vault-backup/backup.py',
              'usr/lib/core-vault-backup/destinations.py',
              'usr/bin/tar','usr/lib/core-vault-backup/layered_backend.py',
              'etc/core-vault-backup.require-private-workspace',
              'usr/lib/core-vault-backup/password_dialog.py','usr/lib/core-vault-backup/gui-test.py',
              'usr/bin/core-vault-backup-gui-test','usr/lib/core-vault-backup/message_dialog.py'}
    required.update({'usr/bin/gpg','usr/bin/core-vault-gpg-self-test',
                     'usr/lib/core-vault-backup/gpg_backend.py',
                     'usr/lib/core-vault-backup/gpg-self-test.py',
                     'usr/lib/core-vault-backup/recovery_dialog.py',
                     'usr/share/applications/core-vault-decrypt-gpg.desktop'})
    if (record.get('formats')!=['gpg-tar'] or record.get('gpg_profile')!='aes256-cfb-mdc-v1'
            or record.get('gpg_round_trip')!='passed' or 'gpg' not in record.get('packages',{})):
        raise RuntimeError('Missing supported GPG profile or real round-trip record')
    if not required.issubset(record.get('files',{})) or record.get('build_round_trip')!='passed' or record.get('paired_dialog_qt_test')!='passed':
        raise RuntimeError('Missing backup runtime or build round-trip record')
    for name,digest in record['files'].items():
        if not re.fullmatch(r'[0-9a-f]{64}',digest) or hashlib.sha256(get(name)).hexdigest()!=digest:
            raise RuntimeError('ISO backup payload mismatch: '+name)
    status=get('var/lib/dpkg/status').decode()
    for package,version in record['packages'].items():
        para=next((p for p in status.split('\n\n') if re.search(r'^Package: '+re.escape(package)+r'$',p,re.M)),None)
        if not para or 'Status: install ok installed' not in para.splitlines() or 'Version: '+version not in para.splitlines():
            raise RuntimeError('ISO package identity differs: '+package)
    for para in status.split('\n\n'):
        if any('Package: '+name in para.splitlines() for name in ('veracrypt','arqiver','7zip')) and 'Status: install ok installed' in para.splitlines():
            raise RuntimeError('Retired container package is still installed')
    manifest=json.loads(get('etc/core-vault/installer-payload.json'))
    if not required.issubset(manifest.get('files',{})):
        raise RuntimeError('Installer manifest omits backup runtime')
    for name in required:
        if hashlib.sha256(get(name)).hexdigest()!=manifest['files'][name]:
            raise RuntimeError('Installer backup hash mismatch: '+name)
    wrapper=get('usr/local/bin/core-vault-bitcoin').decode()
    inner=get('usr/local/libexec/core-vault-core-session').decode()
    if ('exec /usr/local/bin/core-vault-media-view -- /usr/bin/bwrap' not in wrapper or '--ro-bind / /' not in wrapper or
        'VAULT_CORE_NATIVE_HIDE_V2' not in inner or 'core-vault-hide-sync --pid' not in inner or any(x in wrapper+inner for x in
        ('core-vault-core-cover','core-vault-core-startup-guard','xdotool key','xdotool type','AT_SPI_BUS_ADDRESS'))):
        raise RuntimeError('ISO lacks the bounded, addressed native Core Hide launcher')
    helper=get('usr/local/bin/core-vault-hide-sync')
    if helper != (Path(__file__).resolve().parents[2]/'config/includes.chroot/usr/local/bin/core-vault-hide-sync').read_bytes():
        raise RuntimeError('ISO Core Hide helper differs from tested source')
    for package in ('bubblewrap','tesseract-ocr','tesseract-ocr-eng'):
        para=next((p for p in status.split('\n\n') if re.search(r'^Package: '+re.escape(package)+r'$',p,re.M)),None)
        if not para or 'Status: install ok installed' not in para.splitlines():
            raise RuntimeError('ISO native Hide dependency missing: '+package)
    for name in ('usr/bin/tesseract','usr/share/tesseract-ocr/5/tessdata/eng.traineddata','usr/local/bin/core-vault-hide-sync'):
        if name not in manifest['files'] or hashlib.sha256(get(name)).hexdigest()!=manifest['files'][name]:
            raise RuntimeError('Installed native Hide payload hash mismatch: '+name)
    if hashlib.sha256(get('usr/local/bin/bitcoin-qt')).hexdigest()!='d43632a3e54dfb181ba045db2a5b1ec2396a1acdda010e3b6d07b2e21c69c183':
        raise RuntimeError('Original Bitcoin Core 32.1 binary identity changed')
    home=get('usr/local/bin/core-vault-home').decode()
    if 'VAULT_OPTICAL_ICONS_V1' not in home or 'VAULT_POWER_ICON_BUTTONS_V1' not in home:
        raise RuntimeError('ISO lacks normalized icons or power icon buttons')
    css_name = 'etc/skel/.config/gtk-4.0/gtk.css'
    css = get(css_name)
    if css != (Path(__file__).resolve().parents[2] / 'config/includes.chroot' / css_name).read_bytes():
        raise RuntimeError('ISO native GTK4 menu CSS differs from visually tested source')
    if manifest['files'].get(css_name) != hashlib.sha256(css).hexdigest():
        raise RuntimeError('Installer omits the native GTK4 menu CSS')
    openbox_name = 'usr/share/core-vault/openbox.xml'
    openbox = get(openbox_name)
    if openbox != (Path(__file__).resolve().parents[2] / 'config/includes.chroot' / openbox_name).read_bytes():
        raise RuntimeError('ISO Openbox configuration differs from the tested window policy')
    if manifest['files'].get(openbox_name) != hashlib.sha256(openbox).hexdigest():
        raise RuntimeError('Installer omits the tested Openbox window policy')
    # VAULT_POWER_THEME_ICONS_V2_ISO_CHECK: same exact SVG source artwork and licenses in Live/installed payload.
    power=runpy.run_path(str(Path(__file__).with_name('check-power-theme.py')))
    power['verify_payload'](home,lambda relative:get('usr/share/core-vault/'+relative),manifest)
    svg=next((p for p in status.split('\n\n') if p.startswith('Package: qt6-svg-plugins\n')),None)
    if not svg or 'Status: install ok installed' not in svg.splitlines():
        raise RuntimeError('ISO lacks the Qt 6 SVG icon engine')
    if record.get('dark_result_qt_test') != 'passed':
        raise RuntimeError('Dark result dialog test is not recorded')
    if "'title': 'Decrypt Backup'" not in home or "['/usr/bin/core-vault-backup', 'decrypt']" not in home:
        raise RuntimeError('ISO lacks the direct recovery tile')
    listing=subprocess.check_output(['unsquashfs','-ll',str(squash)],text=True,stderr=subprocess.PIPE,timeout=90)
    for forbidden in ('squashfs-root/usr/bin/veracrypt','squashfs-root/etc/sudoers.d/92-core-vault-veracrypt',
                      'squashfs-root/etc/modules-load.d/core-vault-veracrypt.conf',
                      'squashfs-root/usr/share/core-vault/recovery/veracrypt/'):
        if forbidden in listing:raise RuntimeError('Retired payload remains in ISO: '+forbidden)

    if 'ClearClipboard=false' not in get('etc/skel/.config/keepassxc/keepassxc.ini').decode():
        raise RuntimeError('Fresh ISO KeePassXC clipboard default is incorrect')
    if record.get('multilayer_round_trip') != 'passed':
        raise RuntimeError('Multi-layer round-trip gate is not recorded')
    print('VAULT ENCRYPTED BACKUP ISO CONTENT CHECK PASSED')
    print('GUI/boot and cross-platform recovery are not proven by this content check.')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('iso',nargs='?',type=Path);p.add_argument('--squashfs',type=Path)
    a=p.parse_args()
    if bool(a.iso)==bool(a.squashfs):p.error('Choose an ISO or --squashfs FILE')
    if a.squashfs:check(a.squashfs.resolve(strict=True))
    else:
        with tempfile.TemporaryDirectory(prefix='vault-backup-iso-') as td:
            squash=Path(td)/'root.squashfs'
            subprocess.run(['xorriso','-osirrox','on','-indev',str(a.iso.resolve(strict=True)),
                            '-extract','/live/filesystem.squashfs',str(squash)],check=True,
                           stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=300)
            check(squash)
