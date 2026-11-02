#!/bin/sh
set -eu
umask 022
cd "$(dirname "$0")"
stage=$(mktemp -d)
chmod 0755 "$stage"
trap 'rm -rf "$stage"' EXIT HUP INT TERM
install -d "$stage/DEBIAN" "$stage/usr/bin" "$stage/usr/lib/core-vault-backup" \
  "$stage/usr/share/applications" "$stage/usr/share/doc/core-vault-backup"
cat > "$stage/DEBIAN/control" <<'EOF'
Package: core-vault-backup
Version: 0.7.3
Architecture: all
Maintainer: Core Vault Local Build <local-build@localhost>
Section: utils
Priority: optional
Depends: python3 (>= 3.11), python3-pyside6.qtwidgets, gpg (>= 2.4), tar, zenity, thunar, util-linux
Description: Local Core Vault encrypted-backup desktop integration
 Uses stock GnuPG AES-256 CFB+MDC and standard TAR for verified layered backups.
 Provides Qt passphrase dialogs and RAM-only recovery. Locally authored;
 not maintained or audited by Debian or the Bitcoin Core project.
EOF
install -m 644 src/backup.py src/setup.py src/self-test.py src/password_dialog.py src/message_dialog.py src/gui-test.py src/gpg_backend.py src/gpg-self-test.py src/recovery_dialog.py src/layered_backend.py "$stage/usr/lib/core-vault-backup/"
for pair in 'core-vault-backup backup.py' 'core-vault-backup-setup setup.py' 'core-vault-backup-self-test self-test.py' 'core-vault-backup-gui-test gui-test.py' 'core-vault-gpg-self-test gpg-self-test.py'; do
  set -- $pair
  printf '#!/bin/sh\nexec /usr/bin/python3 /usr/lib/core-vault-backup/%s "$@"\n' "$2" > "$stage/usr/bin/$1"
  chmod 755 "$stage/usr/bin/$1"
done
cat > "$stage/usr/share/applications/core-vault-backup.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Create Encrypted Backup
Comment=Create and verify a layered GPG backup
Exec=/usr/bin/core-vault-backup create %F
Icon=document-encrypt
Terminal=false
Categories=Utility;Security;
EOF
cat > "$stage/usr/share/applications/core-vault-decrypt-gpg.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Decrypt Encrypted Backup
Comment=Decrypt and authenticate a GPG file into the RAM-only Private Workspace
Exec=/usr/bin/core-vault-backup decrypt %f
Icon=document-decrypt
Terminal=false
NoDisplay=true
MimeType=application/pgp-encrypted;application/x-gpg;
Categories=Utility;Security;
EOF
[ ! -f README.md ] || install -m 644 README.md "$stage/usr/share/doc/core-vault-backup/README.md"
[ ! -f LICENSE ] || install -m 644 LICENSE "$stage/usr/share/doc/core-vault-backup/copyright"
printf 'No configuration files or user data are removed by this package.\n' > "$stage/usr/share/doc/core-vault-backup/LOCAL-PACKAGE"
export SOURCE_DATE_EPOCH=1790841600
find "$stage" -print0 | xargs -0 touch -h -d "@$SOURCE_DATE_EPOCH"
dpkg-deb --threads-max=1 --root-owner-group --build "$stage" ./core-vault-backup_0.7.3_all.deb
