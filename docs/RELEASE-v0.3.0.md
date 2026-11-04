# Bitcoin Core Vault v0.3.0 (Bitcoin Core 32.1)

Public release candidate dated 2026-11-02, Debian 13 amd64, Bitcoin Core
32.1, KeePassXC 2.8.0, Calamares 3.3.14-1+corevault4 and backup
module 0.7.3. This is a dedicated RAM-only private-session signer and is
not affiliated with the Bitcoin Core project or Debian.

## Files, hashes and downloads

Release: https://github.com/btcpavao/bitcoin-core-vault-releases/releases/tag/v0.3.0

ISO: `bitcoin-core-vault-v0.3.0-core32.1-amd64.iso`

Size: **795148288 bytes**.

SHA-256: `26a1cb255db3cd48b5427a87c6692cb2cfce94bb249207acac90ea7e4f4bb047`.

Other assets: `SHA256SUMS`, `SOURCE-COMMIT.txt`,
`bitcoin-core-vault-v0.3.0-source.tar.gz`, `ACCEPTANCE.json`.

## Verify the maintainer signature

The release checksum list is signed by **btcpavao**, using an Ed25519 OpenPGP key.

Primary key fingerprint:

```text
787A 2AAF B0D1 19CA 0522 B2A5 B9C9 9AF8 5788 96D0
```

Download the [public key](https://github.com/btcpavao/bitcoin-core-vault-releases/releases/download/v0.3.0/btcpavao-pgp.asc) and [detached signature](https://github.com/btcpavao/bitcoin-core-vault-releases/releases/download/v0.3.0/SHA256SUMS.asc), alongside `SHA256SUMS` and the release files. The fingerprint is also published at [btcpavao.com/pgp.txt](https://btcpavao.com/pgp.txt).

Inspect the downloaded public key and compare its full fingerprint with the one you trust before importing it:

```bash
gpg --show-keys --fingerprint btcpavao-pgp.asc
```

From the directory containing the downloaded files:

```bash
gpg --import btcpavao-pgp.asc &&
gpg --verify SHA256SUMS.asc SHA256SUMS &&
sha256sum -c SHA256SUMS
```

On macOS, use `shasum -a 256 -c SHA256SUMS` for the last command. The signature must validate for the full fingerprint above, and each release file must report `OK`.

The signature authenticates the published checksum list. Independently established source reproducibility has not been demonstrated.

## What changed

- Bitcoin Core 32.1 with native watch-only export/restore.
- Standalone Debian-based Live RAM and installed RAM-home environment.
- Wallet Backup: one valid Bitcoin Core SQLite `wallet.dat` is encrypted
  directly with standard AES-256 CFB+MDC GPG; the final layer decrypts
  immediately to `wallet.dat`. No TAR step for an individual wallet.
- Backups of multiple files or folders retain standard TAR under GPG.
- Each independent passphrase creates a separate GPG layer; multiple layers
  carry portable inner filenames.
- Built-in Decrypt Backup supports older OCB and GPG/TAR archives.
- Repaired Decrypt Backup and Print & Labels icons, and opens Private Workspace
  automatically after saving a verified backup there.
- Upgraded KeePassXC to 2.8.0 and retained Debian GNU/Linux credit.
- Repaired Calamares drive detection, which previously showed an empty
  selector on ThinkPad T530 and in virtual SATA/VirtIO fixtures.

## Root cause and safety correction

A local ISO remaster wrongly rewrote the numeric owners and groups of 24
system paths to root:root. In particular
`usr/lib/dbus-1.0/dbus-daemon-launch-helper` must be setuid-root and belong
to the `messagebus` group (numeric GID 991 in this image). Its incorrect
group made DBus activation of KDE Partition Manager fail with
`org.kde.kpmcore.helperinterface: Permission denied`; Calamares detected no
usable devices. Restored owner/group/mode values from the known-good
2026-10-29 release. Added an automatic 24-path numeric UID/GID/mode
SquashFS gate to the build source to prevent regressions.

## Recorded acceptance for this exact ISO

- ISO SHA-256 checked; 484 installer payload entries verified.
- Calamares source/package gate and ISO inspection pass (40 ELF files).
- Critical SquashFS ownership check passes for 24 paths.
- BIOS USB boot, virtual 24 GiB SATA selection and virtual 24 GiB VirtIO
  selection tested: internal disk listed and Continue enabled; no partitioning
  was initiated in these VM selector tests.
- User physically tested T530 and confirmed installation succeeded.
- GPG component unit, integration and multi-layer tests passed. User
  separately confirmed recovery on Mac in an earlier build. The exact final
  image has unchanged backup 0.7.3 payload, but a full formal independent
  macOS recovery test on this SHA is not recorded.

## Scope and limitations

The VM disk selection tests intentionally did not erase disks. They do not
establish full installed-mode reboot and every hardware variant. No external
security audit, independently certified signing identity, comprehensive threat model validation,
clean-host end-to-end bit-reproducible build or independent ISO attestation
is claimed. Do not depend on any single untested backup or a sole copy of a
passphrase. The Linux and GnuPG environment can fail and every critical
restore path must be tested with disposable wallets first.

The public source snapshot records the inputs and scripts used for the image;
a final ISO remaster was required to repair package-file ownership. See
`BUILD-PROVENANCE-v0.3.0.md` and the source archive. This publication should
not be represented as a bit-for-bit reproducible build.

