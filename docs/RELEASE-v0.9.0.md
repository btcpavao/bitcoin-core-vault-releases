# Bitcoin Core Vault v0.9.0

Vault v0.9.0 adds advanced installation on Legacy BIOS and UEFI, automatic kernel selection for supported Apple T2 model identifiers, persistent installed-device preferences and the desktop clock/taskbar behavior used by Node. It keeps the private Vault account and workspace in RAM.

The public filename is `bitcoin-core-vault-v0.9.0-amd64.iso`. It contains exactly the bytes of the local `desktop-tuning-v2-20261124` candidate accepted by Pavao; publication does not rebuild or modify that image.

| Identity | Value |
| --- | --- |
| ISO size | 1,133,379,584 bytes |
| ISO SHA-256 | `615067c09f573a4476c7039adc90e58f75a46bdf20a028fd3c58f3e300c832fe` |
| Architecture | amd64, 64-bit Intel/AMD |
| Bitcoin Core | Unmodified upstream 32.1 binaries |
| Calamares | `3.3.14-1+corevault10localrolesfix1` |
| Source revision | Release `SOURCE-COMMIT.txt`, authenticated by `SHA256SUMS.asc` |

## Installation

- **Install to disk** and **Advanced partitioning** work in the supported Legacy BIOS and UEFI paths. Advanced can use an explicitly selected root partition or create a layout in genuinely unallocated space, with an optional unformatted reservation for Node.
- The reviewed plan identifies the selected disk and partition actions before execution. Existing filesystems are not automatically shrunk or moved.
- The installer includes the partition-preview lifecycle fix, required Qt QML packages and the corrected native partition-role/flag handling that resolves the reported reservation preparation failure. Launcher diagnostics preserve the actual installer failure status.
- Automatic T2 model detection chooses the included T2 kernel before Linux starts and again for installed boot. The user does not choose a T2 profile in the installer. Other machines retain the standard Debian kernel.

See [advanced installation and hardware scope](ADVANCED-INSTALLATION.md) for disk eligibility, EFI ownership, BIOS layouts, model identifiers and Mac firmware preparation. Apple Silicon, 32-bit-only EFI and Secure Boot are outside this image. The added T2 inputs are not a claim that every T2 peripheral or installation scenario has been physically validated.

## Settings and desktop

Installed Vault saves validated display, keyboard, mouse and time-zone preferences and restores them at startup. A Live RAM session applies those preferences only for the current session. Wallets, password databases, ordinary application state and private workspace files remain volatile in both modes.

Date & Time displays the selected zone correctly. Applying a zone changes the zone without resetting the clock from a stale manual editor. Manual date/time correction is explicit; installed mode includes UTC hardware-clock write/readback. The Settings gear uses the existing elementary-xfce artwork with its notice retained.

The desktop date and time appear above Settings, Restart and Shutdown. Clicking the clock opens the existing Date & Time dialog. Open-window names collapse into icons when they no longer fit the taskbar; hover shows the full title, and closing enough windows restores the names. The final taskbar fix hides a removed window button before deferred deletion, preventing an old compact icon from remaining over the restored labels.

## Recorded validation and its limits

The final ISO's archive was read back and checked against the frozen source: 24 overlay file hashes, 23 immutable payload entries, ownership/modes, device nodes, the unchanged native v10 binaries, internal filesystem checksum and BIOS/UEFI boot catalog. The on-disk release candidate was rehashed before VM testing. Publication also compared all 70 recorded source inputs, including 60 installed custom files, with the accepted image; `source-runtime-verification.json` records that separate source-to-image check.

The exact final ISO passed focused live QEMU checks at **1280 × 800 and 1024 × 768**: clock/icon rendering and normal time progression, taskbar compaction, full-title hover, activation/minimization, label restoration after closing a window, and clear separation between the visible taskbar and Home's clock/power controls. The guest taskbar hash was checked. The previous stale-button failure was reproduced on desktop v1, fixed and retested on v2.

The live Europe/Zagreb Apply and immediate update in the same Home process were demonstrated on desktop v1. Final v2 retains the identical Home/clock/timezone files; its only runtime change from desktop v1 is the taskbar removal fix. Earlier settings-fix-v2 evidence separately records a Legacy BIOS installation with a Node reservation, normal installed boot and time-zone persistence. Its 21 settings overlay files and native installer remain identical in this final image. These earlier results are not presented as new complete installation tests of the final ISO.

On **25 November 2026**, Pavao confirmed that Vault was working correctly and approved this exact candidate for release, following the T530 testing in the development record. That maintainer acceptance does not specify every firmware mode or peripheral. No new physical T2 test, complete UEFI matrix or independent security audit is asserted here. The release's `BUILD-PROVENANCE.json` records the artifact and validation boundaries.

## Source and reproducibility

The release contains the matching project source snapshot and retained Calamares source companion, input/provenance records, package inventory and checksums. The ISO was assembled locally by repacking an existing Vault base with reviewed inputs. **An independent byte-identical rebuild of the complete v0.9.0 image has not been demonstrated.** The previous v0.8.0 matching-build result remains attached to v0.8.0.

The T2 kernel binary is exactly pinned and was authenticated through signed repository metadata. Its upstream build used a mutable patch-branch `HEAD`; an exact historical patch commit and a matching T2 source-to-binary rebuild are not invented. The Calamares companion provides the actual retained patched source and original incremental-build evidence; a new clean binary equality result is not claimed.

[Inspect the release and source-build entry point](REBUILD.md) · [Native source companion](NATIVE-REBUILD.md) · [Component notices](../THIRD_PARTY_NOTICES.md)

## Verify before use

Download the ISO, `SHA256SUMS`, `SHA256SUMS.asc` and `btcpavao-pgp.asc` from the [v0.9.0 release](https://github.com/btcpavao/bitcoin-core-vault-releases/releases/tag/v0.9.0). Confirm the maintainer fingerprint independently:

```text
787A 2AAF B0D1 19CA 0522 B2A5 B9C9 9AF8 5788 96D0
```

Follow the [signature and checksum commands](REBUILD.md#1-authenticate-the-release-files). The signature covers the manifest's final asset names, including the source companions. An unsigned or incomplete draft is not the finished signed release.
