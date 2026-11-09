# Bitcoin Core Vault

Bitcoin Core Vault is a dedicated offline environment for creating and restoring
Bitcoin Core wallets, signing PSBTs and exporting encrypted wallet backups. It
uses Debian 13 Trixie on amd64 and the unmodified Bitcoin Core 32.1 application.
Use a separate online Bitcoin Core node to prepare transactions and broadcast
the signed result.

Run Vault as a Live RAM session or install its operating system on an internal
disk. In both modes, the Vault account's home and private working data stay in
RAM. Export the files you want to keep before ending the session.

**Current release: Bitcoin Core Vault v0.4.0**, including Bitcoin Core
32.1 and encrypted-backup module 0.7.3. A single valid Bitcoin Core SQLite
`wallet.dat` is encrypted directly using standard AES-256 CFB+MDC OpenPGP,
without TAR. With two separate passphrases, decryption is
`wallet.dat.gpg.gpg` → `inner.gpg` → `wallet.dat`. TAR is used only for
multiple files or folders. The built-in recovery tool also reads previous
GPG/TAR and AES-256 OCB backup files.

**[Download the v0.4.0 ISO and checksums](https://github.com/btcpavao/bitcoin-core-vault-releases/releases/tag/v0.4.0)**.
See the [exact-image release notes](docs/RELEASE-v0.4.0.md). This project is
independently developed and has not been independently security audited;
building from source has not been shown to be byte-for-byte reproducible.

## Screenshots

Actual Bitcoin Core Vault v0.4.0 interface, captured at 1280 × 800 in a demonstration session. No personal wallets, credentials or funds are shown. Open an image to see it at full size.

### Offline workspace

![image: Offline workspace](docs/screenshots/home.png)

Wallet tools, encrypted backups and recovery in one place.

### Create Encrypted Backup

![image: Create Encrypted Backup](docs/screenshots/backup.png)

The native backup interface with empty passphrase fields. The demonstration wallet is unfunded.

### Vault Guide

![image: Vault Guide](docs/screenshots/guide.png)

Built-in guidance for wallet protection and recovery.

[Capture details](docs/screenshots/CAPTURE.json) · [Website gallery](https://btcpavao.com/en/bitcoin-core/debian-images/#vault)

## Use Vault

The boot configuration provides **Start Bitcoin Core Vault (Live RAM)** and
**Install Bitcoin Core Vault**. The first uses `toram`; the second opens the
Calamares installer.

Home contains ten launchers: Bitcoin Core, Wallet Backup, Decrypt Backup,
KeePassXC, Editor, Brasero, Print & Labels, Files, Terminal and Vault Guide.
Applications and resizable file dialogs open maximized; fixed-size dialogs keep
their native size. Num Lock is enabled at startup. KeePassXC opens its stock
passphrase generator with six words as the initial default.

Keep the signing computer disconnected from networks. Vault disables network
interfaces and radios, and Core runs with peer networking inactive. Helper RPC
uses loopback and cookie authentication. No blockchain synchronization occurs.

Copy imported wallet and PSBT files into RAM before working on them in Core.
Core's filesystem isolation permits writes only to checked RAM locations.
Use **Wallet Backup** for wallet exports and **Files** to transfer signed PSBTs
to external media.

## Watch-only wallet

Use **Bitcoin Core → File → Export watch-only wallet** to save `watch-only.dat`
in Private Workspace (the default export folder), then copy that public file to USB using Files. On an
online computer running Core 32.1 or newer, use **File → Restore Wallet**.
File choosers have wider Places sidebars and show mounted USB volumes. The USB Media shortcut also lets an already-open Core process read newly attached media; Core still saves only to checked RAM locations.
Vault no longer includes a separate watch-only export tool or its JSON format.
Keep the original signing wallet offline. See [the native workflow](docs/WATCH-ONLY.md).

## RAM session and installation

`/home/vault` is backed by `/run/core-vault/home` on a protected RAM filesystem.
Wallets, settings, logs, application state, temporary files and verification
records are volatile. Storage checks run before the desktop and Core start;
swap, persistent crash dumps and suspend/hibernate are disabled by policy.

An installation persists Debian, program binaries and immutable defaults,
while user session files remain volatile. Calamares erases the selected whole
internal disk after review and confirmations. Keep backup media disconnected
while installing. This profile has no dual boot, manual partitioning or full-disk
encryption. Secure Boot is disabled in the build configuration.

Use the Home power controls and **Finish Private Session** when done. Finish
shows two warnings, then a cancellable five-minute countdown before ending RAM.
It does not request passphrases or verify backups. Closing
an application does not end the session; power loss loses unsaved RAM data.
Other files, password databases and signed PSBTs also need to be exported.

The RAM policy does not erase previously written disk data or promise physical
RAM sanitization. See [the current session design](tools/core-vault/docs/RAM-PRIVATE-SESSION.md)
for the implemented storage boundaries and failure behavior.

## Back up and recover a wallet

Choose **Wallet Backup** on Home for a consistent Bitcoin Core snapshot, or
**Files → Create Encrypted Backup** for selected files and folders. Generate
independent random passphrases with KeePassXC, confirm each layer and choose a
new .gpg destination in Private Workspace, another writable folder or external
media. No external drive is required to create a backup. Files saved only in RAM
are lost when the session ends; copy what you need to retain before shutdown or
restart. One layer is enough for a basic encrypted backup;
the interface supports up to 16. Whole-backup readback is checked before publication.

Open the backup through **Decrypt Backup** or Files, and enter its passphrases
in any order. Original names and folder structure are restored into a new folder
in RAM-only Private Workspace. Core's **Restore Wallet** opens the recovered
wallet.dat. If internally encrypted, the wallet still needs its separate Core
passphrase for signing. Verify addresses and signing using disposable test data.

Originals and existing backups are never overwritten or deleted. Only ciphertext
is staged on the destination disk. When needed, TAR archives, decrypted layers and snapshots
stay in verified private RAM. Resource limits are 16 layers, 10,000 entries and
256 MiB per package, further reduced when available RAM is limited.

Direct wallet exports are verified during backup creation. Use Wallet Backup for
each current wallet. Before finishing, save and verify everything you need;
shutdown confirmations do not check whether your backups are current.

## Choose an encryption arrangement

Core private-key encryption is optional and separate from GPG whole-file privacy.
Use extra GPG layers only when independent handling of their secrets justifies
the extra recovery dependencies. Multi-layer encryption is not Bitcoin multisig.
Keep redundant backup copies and redundant secret recovery arrangements in
appropriate separate locations. Geographic separation can delay access under
coercion; it does not guarantee protection from continued coercion.

KeePassXC starts with **Clear clipboard after** unchecked. This deliberately
leaves copied secrets accessible to local applications for longer. Enable
automatic clearing in **Tools → Settings → Security** if preferred. Relaunching
the application preserves that choice within the session; a fresh volatile
profile starts with the image defaults.

[The integrated and portable guide](docs/GPG-BACKUP.md) covers threat models,
inheritance, stock GnuPG/TAR recovery and the distinction from multisig. Recovery
does not require Vault: current GnuPG supporting AES-256 CFB+MDC and Bitcoin Core are sufficient
for direct single-wallet backups. TAR is additionally needed for grouped
backups; old OCB archives require a GnuPG implementation with OCB support.
Test recovery on the actual target operating system before relying on it.

## Build from complete sources

Use a separate Debian 13 amd64 build computer with network access for package
preparation. Calamares is built in a dedicated chroot; its preparation script
requires more than 20 GiB free for that builder.

Host dependencies referenced by the scripts include `live-build`, `debootstrap`,
Python 3 with Pillow and PyYAML, DejaVu fonts, Debian package tools, `sudo`, mount
utilities, `xorriso` and `squashfs-tools`. Runtime dependencies are declared in
`config/package-lists/`; Calamares compiler dependencies are installed in its
builder chroot.

The build also needs verified Core executables, branding assets and reviewed
local backup, Calamares and Thunar packages. Their versions, hashes and
source/package payloads must pass the existing gates. Use `umask 022` when cloning or extracting sources so runtime files are not
writable by other users. Once these inputs are present, run from the project root:

```bash
umask 022
bash tools/core-vault/prepare-installer.sh
bash tools/core-vault/build-live-iso.sh
```

The output is `live-image-amd64.hybrid.iso`. Source/package checks run before
building; ISO content checks run afterward. Content checks do not establish
successful boot, installation or recovery.

## Release verification and status

The [v0.4.0 release](https://github.com/btcpavao/bitcoin-core-vault-releases/releases/tag/v0.4.0)
provides `bitcoin-core-vault-v0.4.0-core32.1-amd64.iso` and `SHA256SUMS`.
The image has exactly **769,654,784 bytes** and SHA-256:

```text
7320f3e3cb1c906d5cfbe701c2e9fb1cce95e0488283ac82ef6415d9498ac864
```

Download `SHA256SUMS.asc` and `btcpavao-pgp.asc` alongside `SHA256SUMS`
and the ISO. The maintainer's Ed25519 primary key fingerprint is:

```text
787A 2AAF B0D1 19CA 0522 B2A5 B9C9 9AF8 5788 96D0
```

Inspect the downloaded key with `gpg --show-keys --fingerprint btcpavao-pgp.asc`
and compare its full fingerprint with a value you trust before importing it.
The public key is also published at [btcpavao.com/pgp.txt](https://btcpavao.com/pgp.txt).
After confirming the fingerprint, run from the download directory:

```bash
gpg --import btcpavao-pgp.asc &&
gpg --verify SHA256SUMS.asc SHA256SUMS &&
sha256sum --ignore-missing --check SHA256SUMS
```

The signature must validate for the full fingerprint above and the ISO must
report `OK`. `--ignore-missing` permits downloading the ISO without the optional
source and evidence bundles. The signature authenticates the checksum list;
it does not establish independent security review or reproducibility.

`ACCEPTANCE.json` records the exact-image test scope: BIOS Live operation,
UEFI Live boot and installation, installed operation, native backup and recovery,
synthetic recovered-wallet signing, Finish controls, restart checks and test-marker
scans on virtual disks. The QA evidence bundle includes release-specific adapters
for the current GPG backup and Finish interfaces, their hashes and preserved failed
attempts. Older probes in the source snapshot target the previous interface;
use the accompanying adapters to inspect this release's recorded tests.

USB optical-reader discovery and Brasero startup were tested with emulated
hardware. **Writing to a physical external DVD burner has not been verified.**
The image includes `core-vault-optical-diagnostics` for collecting read-only
information about a specific drive. See the [release notes](docs/RELEASE-v0.4.0.md)
for the remaining scope and limitations. Previous physical-machine reports apply
to their original releases, not automatically to this ISO.

## Source and licenses

The public release repository contains a standalone snapshot of tracked
Vault sources, build scripts, patches, notices and reviewed package inputs.
The separate private development repository and its historical Git commit
tree are not exposed. The ISO belongs to GitHub Release assets, not Git.
Matching source recipes and component provenance accompany the release;
independent byte-for-byte reproduction has not been proven.

Original Vault integration is licensed under the scoped [MIT license](LICENSE).
Upstream programs, patches, libraries and artwork retain their own licenses.
See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and
[the test record](docs/TESTING.md).
