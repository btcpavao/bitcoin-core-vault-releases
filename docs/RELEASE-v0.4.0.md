# Bitcoin Core Vault v0.4.0

Debian 13 amd64 with the unmodified Bitcoin Core 32.1 application,
KeePassXC 2.8.0 and encrypted-backup module 0.7.3.

Release: https://github.com/btcpavao/bitcoin-core-vault-releases/releases/tag/v0.4.0

## Changes

- Native Core watch-only export and other Core save dialogs start in
  **Private Workspace**, using the standard XDG Documents location.
- Qt Places sidebars start at 320 logical pixels and grow for longer media
  labels; Thunar uses a 320-pixel minimum and GTK Places uses 300 pixels.
  A user's wider setting is preserved.
- Mounted USB volumes appear in Qt Places and refresh during the session.
  The permanent **USB Media** entry opens the removable-media folder.
- An already-running Core can read newly attached USB media through
  read-only FUSE mirrors. Both the mirrors and Core's mount bindings reject
  external writes. Watch-only exports still go to RAM; use Files to copy the
  public export to a transfer drive.
- Debian packages are refreshed from the stable Trixie and security archives.
  Core 32.1 and KeePassXC 2.8.0 remain the current verified upstream versions.
- Added a read-only optical-device diagnostic and USB inspection tools.
- Aligned Vault Guide chapter icons, navigation and reading layout with the
  current Node Guide. Updated instructions and illustrations for direct
  wallet-file encryption, grouped TAR backups, watch-only export and USB use.
- Fresh builds now restore Debian's intended Polkit rule-directory ownership
  after live-build copies the local files. The exact-image ownership gate
  retains the required daemon group and checks Debian's stricter 0750 mode.

## Optical-device report

A reported external DVD writer was not listed in Brasero in a live session.
The previous ISO already included USB storage/UAS and optical kernel drivers,
the GVfs/UDisks discovery services, optical-device access rules and Brasero's
DVD burning backends. No missing driver or permission rule was established
from the available report.

This release does not claim a verified fix for that specific physical writer.
Run `core-vault-optical-diagnostics` as the desktop user with the writer
connected to distinguish kernel detection, user access and desktop discovery.
It does not open, eject, mount or write media. See
[the optical diagnosis guide](../tools/core-vault/docs/OPTICAL-MEDIA.md).

## Downloads and verification

The release assets include the ISO, matching source archive,
`SOURCE-COMMIT.txt`, `ACCEPTANCE.json` and `SHA256SUMS`. The acceptance file
records the checks performed against the exact published ISO and their scope.
Check the checksum list from the directory containing the downloaded assets:

```sh
sha256sum -c SHA256SUMS
```

If `SHA256SUMS.asc` is included, verify it before checking the hashes:

```sh
gpg --import btcpavao-pgp.asc
gpg --verify SHA256SUMS.asc SHA256SUMS
```

The expected maintainer fingerprint is
`787A2AAFB0D119CA0522B2A5B9C99AF8578896D0`; compare it with a copy you already
trust. A signature authenticates the checksum list, not independent
reproducibility or hardware compatibility.

## Build and test scope

The source archive and `SOURCE-COMMIT.txt` identify the reviewed build inputs.
The image is built with the canonical live-build entry point in a disposable
Debian 13 guest. See `ACCEPTANCE.json` for the final package versions, boot and
synthetic wallet/media test results. Virtual USB optical discovery is distinct
from physically writing a DVD. A byte-identical independent rebuild and
an independent security audit are not claimed.
