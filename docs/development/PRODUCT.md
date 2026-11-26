# Vault product baseline

Read [CURRENT.md](CURRENT.md) for the selected development baseline and [SHARED-WORKFLOW.md](SHARED-WORKFLOW.md) for change and release rules. This inventory describes implemented behavior; it is not a backlog or a new acceptance report.

## Identity and evidence

Reviewed on **2026-11-26** against clean source revision [`58f873fa727054f262b2f99bf742aff251cc5672`](https://github.com/btcpavao/bitcoin-core-vault-releases/tree/58f873fa727054f262b2f99bf742aff251cc5672), the frozen publication source for **Vault v0.9.0**. The accepted ISO is `bitcoin-core-vault-v0.9.0-amd64.iso`, 1,133,379,584 bytes, SHA-256 `615067c09f573a4476c7039adc90e58f75a46bdf20a028fd3c58f3e300c832fe`.

The source freeze occurred after the accepted local `desktop-tuning-v2-20261124` image was assembled. It is a source-to-image mapping, not evidence that building this commit reproduces those bytes. The release records one review-metadata difference in `usr/share/core-vault/shred-policy.json`; the accepted ISO was not changed. Read the [release record](../RELEASE-v0.9.0.md), [build guide](../REBUILD.md) and the release's `BUILD-PROVENANCE.json` / `source-runtime-verification.json` before interpreting a failed equality check.

| Evidence | What it establishes |
| --- | --- |
| Current source inspection | The implementation and module boundaries described here |
| Final-image records | Archive/source checks and focused desktop VM checks at 1280×800 and 1024×768, bound to the v0.9.0 ISO |
| Earlier candidate records | Installer and settings results only for their recorded images; unchanged component hashes explain reuse of evidence |
| Maintainer acceptance, 2026-11-25 | Pavao accepted the exact candidate following T530 testing; it is not an exhaustive hardware matrix |
| Reproducibility | A complete independent byte-identical v0.9.0 rebuild has **not** been demonstrated; v0.8.0 results remain specific to v0.8.0 |

No runtime tests, installation, new ISO build or new hardware acceptance are implied by this documentation review.

## Product and session model

Vault is the offline Bitcoin Core signer on Debian 13 Trixie for amd64. Bitcoin Core 32.1 uses upstream binaries; the project supplies the session, launchers, confinement, desktop, backup tools, installer integration and guides. Node prepares transactions, tracks the blockchain and broadcasts signed transactions on a separate online system.

The current desktop uses X11/Openbox and project PySide6 applications. Do not infer an XFCE desktop session merely because Thunar and other XFCE components are installed. Vault has no blockchain synchronization workflow or online software-update category. Its network restrictions, loopback helper RPC and RAM boundary are distinct from Node.

| Data or setting | Live RAM | Installed Vault |
| --- | --- | --- |
| Debian and program binaries | Loaded from the boot image | Persist on the installed OS disk |
| `/home/vault`, wallets, Core settings/cookie/logs, password databases and ordinary application state | RAM | RAM |
| Private Workspace, decrypted staging, temporary export receipts | RAM | RAM |
| Validated display, keyboard layout/repeat, mouse/pointer and time-zone preferences | Current session only | Small allowlisted device record persists and is restored into the new RAM session |
| Time-zone-only Apply | Changes the displayed zone; leaves both clocks running | Same behavior; chosen zone is also saved |
| Explicit manual date/time correction | Changes the running clock only | Changes the running clock and attempts UTC hardware-clock update with readback; partial failure is reported |
| Files deliberately saved on external media | Remain on that media | Remain on that media |

The private home is backed by `/run/core-vault/home` and bound at `/home/vault`; it is not restored from an old persistent home. Private-session preparation verifies protected tmpfs and inactive swap before normal use. Swap, persistent dumps and suspend/hibernate are disabled by the image policy. Volatility is not a claim of physical RAM sanitization or erasure of earlier disk contents.

Installed device preferences are the explicit exception to volatile user state. `vault_device_state.py` accepts only `layout`, `input`, `pointer`, `display` and `timezone` in `/var/lib/core-vault-device-settings/preferences.json`. The privileged store uses protected ownership, bounded JSON, validation and atomic replacement. Installed detection requires a matching installation marker, an ext4 root and absence of `boot=live`. Live sessions do not invoke its persistence helper. Boot preparation restores only those fields, never wallets, arbitrary paths, passwords, a home archive or a saved clock timestamp.

Sources: [device-state implementation](../../config/includes.chroot/usr/lib/core-vault/settings/vault_device_state.py), [time implementation](../../config/includes.chroot/usr/lib/core-vault/settings/vault_time.py), [boot preparation](../../config/includes.chroot/usr/local/libexec/core-vault-prepare), [current settings specification](../../tools/core-vault/docs/SETTINGS.md).

## Implemented user functions

| Surface | Current behavior and boundary |
| --- | --- |
| Home | Ten launchers in fixed order: Bitcoin Core, Wallet Backup, Decrypt Backup, KeePassXC, Editor, Brasero, Print & Labels, Files, Terminal, Vault Guide. [UI.md](UI.md) records layout and interactions. |
| Bottom-right controls | Settings, Restart, Shutdown; clock above them opens Date & Time. Vault has no peer-status row. |
| Settings | Display Settings; Keyboard and Mouse; Date & Time; Backup and Restore. Device settings can be exported/imported separately. No network, online updater, login-account or Node chainstate category. |
| Display Settings | Built-in, mirror, extend and external-only presets; detected resolution/rate, primary display, arrangement, rotation and interface scale. Apply requires confirmation within 15 seconds; rollback is supervised independently. Imported layouts are reviewed before application. |
| Keyboard and Mouse | Supported X11 layout, repeat, Num Lock, handedness, scrolling and pointer-speed controls. Settings are bounded and applied to supported devices; reconnect watching is session-owned. |
| Bitcoin Core | Create/encrypt/restore wallets, receive addresses, inspect and sign PSBTs. The wrapper keeps Core offline and its private writes in validated RAM. Core's optional wallet passphrase is independent of backup encryption. |
| Wallet Backup | Consistent wallet snapshot, whole-file GPG encryption, verification and new-file publication. It handles loaded wallets through Core's `backupwallet` and supported closed SQLite wallets through the snapshot path. |
| Decrypt Backup | Authenticate/decrypt into a new recovery folder, defaulting to Private Workspace; an explicitly selected writable USB destination is supported and retains plaintext after shutdown. Restore the recovered wallet through Core. |
| Files | Thunar and mounted removable media; encrypted-backup/recovery actions and deletion helpers. Ordinary deletion and the Secure Delete helper are separate operations. Secure Delete is not an SSD/flash sanitization guarantee. |
| KeePassXC | Stock passphrase generator starts with six words; copied passphrases clear after ten seconds by default. User changes remain ordinary RAM application state. A deliberately exported database remains on its selected medium. |
| Editor, Terminal | Local notes and advanced tools inside the session; deliberately written external files remain external. |
| Brasero | Optical-media application and read-only diagnostics are present. General support for every external writer has not been established. |
| Print & Labels | Local printing and label/instruction preparation; it does not automatically insert wallet secrets. Print spools/cache are volatile. |
| Vault Guide | Bundled offline practical guide, with content and visual modules versioned with the image. It is user documentation, not proof that every described workflow passed on every hardware model. |

## Backups and recovery contract

New backups use standard symmetric **AES-256 CFB + MDC OpenPGP**, not a proprietary container and not new OCB output. The backend supplies explicit RFC 4880, cipher and S2K settings. Legacy AES-256 OCB and earlier GPG/TAR backups have read compatibility in the recovery path.

| Input | Current final plaintext payload after all GPG layers are opened |
| --- | --- |
| Exactly one valid supported Bitcoin Core SQLite `wallet.dat` | The verified wallet file directly, without TAR |
| Multiple files, folders or other selected files | A validated standard TAR package |
| Explicit ordinary single-layer GPG recovery | One authenticated recovered file; the tool deliberately does not recursively infer its meaning |

One GPG layer is the default. The UI supports up to 16 independent layers; a package is bounded to 10,000 TAR entries and 256 MiB, reduced according to available RAM. Repeated external passphrases are rejected. A single selected file named `wallet.dat` must pass the direct-wallet validation; an invalid one is rejected rather than silently treated as generic TAR input. These are implementation limits, not a recommendation to use every layer.

Sensitive snapshots, packages and decrypted provisional layers remain in checked RAM. Encryption checks each layer and full recovery against the original payload; publication refuses to replace an existing destination. Creation verification does not substitute for a later restore-and-sign drill. The backup destination may be RAM or explicitly selected writable media. Only external copies survive session loss. Recovery to USB has different consequences from recovery to RAM, including possible partial plaintext if the device is removed during copying.

Current sources: [`gpg_backend.py`](../../tools/core-vault/backup-src/src/gpg_backend.py), [`layered_backend.py`](../../tools/core-vault/backup-src/src/layered_backend.py), [`backup.py`](../../tools/core-vault/backup-src/src/backup.py), [`destinations.py`](../../tools/core-vault/backup-src/src/destinations.py). Older notes describing 7z as the default or TAR for every wallet are historical, not the current creation contract.

## Watch-only transfer and signing

Core's **File → Export watch-only wallet** is the current export interface. There is no separate Vault watch-only JSON exporter. Supported native exports are staged and checked before writing to a selected mounted drive. Exporting a private wallet by renaming it is not an allowed public-export path.

When a watch-only wallet contains address-book or transaction records, Vault asks before writing to USB. Cancel leaves the destination untouched and Core displays **Export Error**; it must not display success. A confirmed successful write produces **Export Successful**. File dialogs expose removable media with the widened Places sidebar. A mounted drive can also receive the signed PSBT through the native signing window's **Save…** action.

The intended workflow is Vault public export → Node watch-only restore → Node unsigned PSBT → Vault review/sign/save → Node broadcast. Signing keys and private wallet backups stay on the Vault side. See [WATCH-ONLY.md](../WATCH-ONLY.md) and the source modules listed in [MODULES.md](MODULES.md).

## Boot and installation

The boot menu retains **Start Bitcoin Core Vault (Live RAM)** and **Install Bitcoin Core Vault**. Installer choices are **Install to disk** and **Advanced partitioning**, within the Keyboard → Disk → Review flow. Advanced can format an explicitly selected root partition or create a layout in genuinely unallocated space and reserve unformatted space for Node. It does not automatically shrink/move filesystems or treat filesystem free space as unallocated disk space.

The v0.9.0 implementation supports the documented Legacy BIOS and UEFI paths. It has explicit disk/partition identity checks, reviewed destructive actions, root/EFI/BIOS-boot handling, and product-specific boot ownership. The exact constraints and matrix belong to [ADVANCED-INSTALLATION.md](../ADVANCED-INSTALLATION.md), not a simplified parallel installer specification.

The image includes standard Debian and T2 kernel inputs. Matching Apple manufacturer/model identifiers select the T2 path automatically before Linux starts and for installed boot. This is implementation support, not physical validation of every T2 machine or peripheral. Apple Silicon, 32-bit-only EFI and Secure Boot are outside the image's stated scope. Existing filesystem shrink and general LVM/RAID migration are not features of this installer.

## Finish, restart and shutdown

Both power actions use `core-vault-finish`: two confirmations, then a cancellable 300-second countdown. Cancel, Esc or closing the countdown keeps the session available; the explicit immediate-action button skips the remaining delay. Core stops cleanly before clipboard clearing and privileged teardown. A Core stop failure cancels the normal finish path.

Finish **does not** ask for backup passphrases, inspect wallets or verify backup receipts. It cannot establish that backups are current. Do not restore the earlier receipt-gated shutdown behavior when editing nearby code. See [the current implementation](../../config/includes.chroot/usr/local/bin/core-vault-finish) and `test-finish-session.py`.

## Known boundaries to retain in future work

- Keep the published ISO, matching source, documentation-only changes and a future candidate distinct in [CURRENT.md](CURRENT.md).
- A new source build and a byte-identical rebuild are different results. Do not weaken an existing check to conceal the documented v0.9.0 metadata exception.
- A shared visual component does not authorize copying Node's networking, updater, persistent wallet storage or login behavior into Vault.
- Device configuration persistence is allowlisted; it does not make the private home persistent.
- Historical checks and general maintainer acceptance must retain their original artifact and hardware scope. New hardware reports must identify the exact image and scenario.
