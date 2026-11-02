# GPG-only candidate validation — 16 October 2026

This record applies to the working tree in `core-signer-os-gpg-candidate`, based on `66b36c6`, with locally built backup package 0.7.0. It does not certify an ISO built from an earlier revision. No changes have been published to GitHub and no physical USB drive has been written.

## GPG 0.6.1 image checked on 14 October 2026

The published v0.2.0 image passed the covered BIOS and UEFI Live, native
installation and installed-session checks. See the
[exact-image acceptance record](GPG-061-ACCEPTANCE.md) and
[machine-readable evidence](gpg-061-final-acceptance.json) for checksum, native
backup/recovery, synthetic PSBT signing, Finish, full virtual-disk marker scans,
clean/abrupt cold boots, controller provenance and explicit coverage limits.
The following sections retain the historical v0.1.0 record.


## Confirmed results

- All 12 source/package gate commands in `docs/validation/gpg-only-20261016/source-checks.log` passed, including their nested runtime, installer, permanent-delete, media and desktop checks.
- Backup unit suite: 55 tests passed, covering the retained GPG authentication checks, fd-based passphrases, cancellation, safe publication, wallet snapshot consistency, receipts, policy and UI routes.
- Real multilayer/TAR suite: 19 tests passed, including 1, 2, 3, 6 and 10 independent layers; arbitrary secret order; missing/wrong secrets; corruption/truncation; nested original GPG and TAR files; ordinary GPG mode; hostile TAR entries; resource bounds; cancellation and independent stock GPG/TAR recovery.
- Stock GPG profile roundtrip, tamper/truncation/wrong-passphrase and plaintext-packet rejection self-test passed.
- Offscreen Qt suite: 8 tests passed for dynamic rows, validation, visibility, cancellation, Enter/focus behavior, accessible labels, recovery mode, plain-text error presentation and constrained-height layout.
- Private-session suite: 22 tests passed. Its mount, RPC, clipboard and shutdown controls are synthetic, not a real machine shutdown or ISO boot.
- Core file-dialog source gate and 9 isolated native Qt dialog scenarios passed.
- Actual unmodified Bitcoin Core 31.1 regtest passed: loaded/unloaded/closed wallet snapshots, encrypted wallet recovery, expected addresses and labels, and signing of a funded PSBT which Core accepted. Core binary SHA-256: `fcd4c1a3193e0cb4eec9d980c835d822ad726627b0c01281b13f5c3c1f593fcb`.
- Actual Core-backed Files/Thunar backup harness passed: live exclusive locks, required RPC, mixed selected files, wrong secret rejection, wallet restore, unloaded and closed wallets, unchanged original settings and failure cleanup.

Core tests run in disposable bubblewrap/Xvfb environments, with synthetic regtest wallets. No real funds or user wallet profiles are used. A byte-identical, owned copy of stock GPG is bound into the test namespace to accommodate its uid mapping; production executable ownership checks remain enforced.

- Actual stock KeePassXC clipboard acceptance passed in an isolated Xvfb session: Security checkbox initially unchecked, synthetic generated passphrase pasted after 31 seconds on two launches, user enabled the option through Settings, third launch preserved it and the clipboard cleared. Screenshots and results are retained beside the test logs. This verifies the host application with the image profile; Live/installed VM checks remain pending.

## Reproduce on Debian 13

Use `umask 022`. Source-mode checks reject writable trusted inputs. From the project root:

```sh
python3 tools/core-vault/check-backup.py --project .
python3 -m unittest discover -s tools/core-vault/backup-src/tests -v
python3 tools/core-vault/backup-src/src/self-test.py
python3 tools/core-vault/backup-src/src/gpg-self-test.py
QT_QPA_PLATFORM=offscreen python3 tools/core-vault/backup-src/src/gui-test.py
python3 tools/core-vault/test-private-session.py
python3 tools/core-vault/test-core-wallet-export.py --core-root config/includes.chroot --regtest
python3 tools/core-vault/test-thunar-wallet-backup.py --core-root config/includes.chroot
```

The optional `test-keepass-clipboard-x11.py --project . --output /tmp/vault-clipboard-new-run` harness needs `xdotool`, Xvfb, stock KeePassXC 2.7.10 and PySide6. It creates a separate display, bus, profile and synthetic generated secrets. Its coordinates are version-specific and are checked against the visible Security page; no existing host profile is read. The output directory must be new.

The host used GnuPG 2.4.7, KeePassXC 2.7.10, Python 3.13 and packaged PySide6. Passing host/offscreen tests does not establish the live image's mount or desktop behavior.

## Outstanding release acceptance

The first user-run build on 16 October stopped in hook 0900: the installer and Vault power rules still had checkout mode 0644 when the first complete policy validation ran. Hook 0900 now sets root ownership and mode 0440 for all three shipped rules before validation, rejecting missing files and symlinks. The rules themselves were not changed. Shell syntax, the Live source gate and diff checks passed; validation inside a newly built image remains pending a rerun.

The new ISO has not been built. Remote Desktop Commander blocks the `sudo` command required by `build-live-iso.sh`; that restriction was not bypassed. The user must run the existing build entry point locally:

```sh
cd /home/pavao/core-signer-os-gpg-candidate
umask 022
bash tools/core-vault/build-live-iso.sh
```

Record the new ISO SHA-256 and run `check-backup-iso.py`, `check-live-iso.py`, `check-installer-iso.py` and `check-private-session.py --iso` against that exact image. Do not substitute the prior image's results.

Then use `tools/core-vault/vm-installer-test.sh bios live --usb-test`, `bios install --usb-test`, and `bios installed --usb-test`; repeat for `uefi`. This harness uses ordinary file-backed disposable VM disks and a virtual USB file, with no network or physical disk passthrough.

In both Live and installed modes, record:

1. Default one-layer creation and 3/10-layer creation from Home and Files, using independent synthetic secrets. Check keyboard navigation, scrolling, visibility controls, cancel, duplicate/mismatch validation, clear error messages and no overwrite.
2. Any-order recovery, missing/wrong secret retry, cancellation and corrupted/truncated input, nested original `.gpg` preservation, explicit ordinary GPG behavior, and safe recovery of files only inside the RAM workspace.
3. Core wallet export, recovery, labels/addresses/signing, and Finish verification of the unchanged current wallet with every required secret. Do not use real funds.
4. KeePassXC Settings → Security: clipboard auto-clear initially unchecked; copy a newly generated synthetic passphrase, wait at least 31 seconds, paste successfully; restart KeePassXC and repeat. Enable auto-clear in Settings, restart, and verify that preference persists and clears the clipboard. A fresh Live profile should restore the image default. Never inspect or copy an existing user's password database.
5. No active persistent swap, RAM-only private data and temporary plaintext, original media/storage policy and clean failure cleanup.

No complete Live/installed VM acceptance, physical hardware acceptance, cross-platform recovery claim, or independent security audit is claimed for this candidate.

## Guide visuals and Home order update — 16 October 2026

The subsequent UI revision adds diagrams to all 18 Guide chapters, selectable 1/2/3-layer examples, a backup-versus-multisig comparison and the requested Home order. Body text remains 14 pt. Native Qt checks pass at four viewport sizes, both normal and 2× scaling; Home layout and actual Tab order pass. Source/runtime hash and affected desktop checks pass. See [Guide visual validation](guide-visuals/README.md) for screenshots, logs and exact scope. This UI revision requires a newly built ISO; it is not present in the previously booted VM image.

## 2026-10-16 — Passphrase labels and confirmed shutdown countdown

Implemented in the candidate source and staged backup package. Backup creation
and recovery retain their verification; finish no longer reads wallet receipts,
requests passphrases, or decrypts backups. Single fields have one Passphrase
label, with numbering only while multiple fields exist. Confirm and Show are
short visible labels with contextual accessible names.

Restart and shutdown now share two explicit warnings followed by a monotonic
300-second countdown, refreshed every second. Cancel, Esc and window close leave
the session open. Restart now / Shut down now explicitly skip the remainder.
Core shutdown and clipboard clearing start only after expiry or explicit override.
A per-user lock excludes simultaneous power flows. Core stop failure does not
invoke the privileged teardown helper. The existing narrow helper and sudo rules
are unchanged.

Verified on the build host, without any real power or Core-stop action:

- 13 finish-flow Qt tests: both warning stages, cancellation at each stage,
  countdown expiry and one-second updates, cancellation after timer start,
  Enter safety, explicit override, stop failure, cleanup order and action routing,
  shared lock/retry, absence of secret/backup dependencies.
- 9 backup/recovery Qt tests, including single/multiple/single label transitions
  in both modes, confirmation validation, show/hide and secret clearing.
- 20 private-session tests, including a real synthetic GPG export/reverification.
- Guide: all 18 chapters at 800x600, 1024x768, 1366x768 and 1920x1080;
  no horizontal overflow, readable descriptions and layer selection intact.
- Rebuilt package and source/package coherence checks passed.
- All 11 read-only ISO pre-build checks passed after refreshing the three reviewed UI checksums.
- Preview captures and geometry records: docs/validation/finish-flow-20261016/.
  Countdown, second warning, single recovery field and multi-field creation
  were visually inspected. Guide screenshots/diagrams were regenerated.

Not verified in this change: a newly built ISO, actual VM poweroff/reboot or T530
boot. The current on-disk ISO predates these edits. Build locally with
`bash tools/core-vault/build-live-iso.sh` before VM or USB testing; the remote
commander's sudo restriction prevents the ISO build here. No physical USB was
written, and no repository publication was performed.

## 2026-10-18 — Choose any encrypted-backup destination

Wallet Backup and Files → Create Encrypted Backup now accept RAM, internal and external destinations without media approval. Private Workspace is the initial folder. Home explicitly warns to save required files/wallets externally before shutdown or restart. Existing two-confirmation and five-minute countdown behavior is unchanged.

57 backup tests, 9 dialog tests, 13 Finish tests, 20 private-session tests, the real Core 31.1 backup/restore fixture, Home/Guide geometry checks and ten top-level source gates pass. Evidence and exact scope: [backup-destinations-20261018](validation/backup-destinations-20261018/README.md). These checks use disposable synthetic data. A freshly built ISO still requires VM/T530 acceptance.

## 2026-10-18 — Home warning line break

The backup warning starts on its own line below the RAM-session sentence. Full-size cards and text fit at 800x600 through 1920x1080; see [Home notice checks](validation/home-notice-20261018/README.md). Publication preserves the v0.2.0 release history and its independent CI fixture fixes. The final layout change still requires a new ISO build.
