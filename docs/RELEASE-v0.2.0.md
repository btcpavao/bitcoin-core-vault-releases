# Bitcoin Core Vault v0.2.0

[Published on 15 October 2026](https://github.com/btcpavao/bitcoin-core-vault/releases/tag/v0.2.0). Covered exact-image BIOS/UEFI acceptance passed.

The release tag binds verification and documentation commit `f4ff30553d334925e240e20d9ac27f4be6039031`.
See [the publication record](RELEASE-v0.2.0-PUBLICATION.json) for uploaded asset checksums and CI results.

This release adds a single-file GPG encrypted-backup option alongside the
existing 7z workflow. Backup package 0.6.1 fixes authenticated GPG recovery
into the RAM-only Private Workspace across its HOME bind mount. The Vault
Guide explains Core wallet encryption, whole-file encryption, optional layers,
independent recovery secrets and inheritance tradeoffs.

The image contains Debian 13 amd64 and unmodified Bitcoin Core 31.1. Live
and installed sessions keep the Vault account home and private data in RAM.

## Exact build

- Product source: `d11f31b002386287ee7de6fbe1ec10476c9343b6`.
- ISO: `bitcoin-core-vault-v0.2.0-amd64.iso`.
- Size: 749,731,840 bytes.
- SHA-256: `ef6b210772d096e37a3ec6de5fb586b5d1af75e33f33e8ed6ab8425b15b2ae56`.
- Build date: 14 October 2026.
- Verify final files using `sha256sum -c SHA256SUMS`.

## Validation

Source/package gates, ISO content gates and the RAM bind-mount regression
passed. The exact image passed native BIOS/UEFI Live, installation and installed
acceptance: both backup formats, GPG recovery and native Core restore, recovered
wallet synthetic PSBT signing, genuine Finish shutdown, full virtual-disk
exact-marker scans with zero matches, and clean/abrupt cold-boot checks.
See [the acceptance record](GPG-061-ACCEPTANCE.md),
[the machine-readable summary](gpg-061-final-acceptance.json) and the accompanying
test-results archive with exact controllers and original screenshots.

Synthetic wallets were created through Core RPC; native wallet creation was not
exercised. No funded transaction or broadcast was tested. Physical USB behavior,
Windows/macOS recovery, physical memory sanitization and whole-ISO bit-for-bit
reproducibility are not established by these tests.

## Corresponding sources

The new assets contain the exact project source, Debian source delta,
additional static-source set and authenticated curl 8.14.1-2+deb13u7 sources.
The unchanged baseline source companions remain available in
[v0.1.0](https://github.com/btcpavao/bitcoin-core-vault/releases/tag/v0.1.0):

- `bitcoin-core-vault-debian-sources.part01.tar`
- `bitcoin-core-vault-debian-sources.part02.tar`
- `bitcoin-core-vault-debian-sources.part03.tar`
- `bitcoin-core-vault-bootloader-sources.tar`
- `core-31.1-static-qt-6.8.3-sources.tar.gz`
- `bitcoin-core-vault-v0.1.0-modified-sources.tar.xz`
- `bitcoin-core-vault-v0.1.0-notices.tar.gz`

The package/source comparison records 765 packages and identifies the backup
package and curl updates. Source-version coverage is distinct from a
bit-reproducibility assertion. See the accompanying source manifests and
`THIRD_PARTY_NOTICES.md` for provenance and licenses.

## Operating notes

Export files that must survive before ending a private session. Installation
erases the selected internal disk. Core private-key encryption and external
backup encryption are independent; retain all passphrases needed for recovery.
The GPG format uses the documented GnuPG OCB profile, so recovery software
must support that profile.
