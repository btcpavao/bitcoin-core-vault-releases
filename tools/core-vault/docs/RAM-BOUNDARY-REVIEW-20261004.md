# RAM boundary review and candidate ISO test — 2026-10-04

> Historical engineering report. This file records test conditions and incomplete acceptance of an October 2026 candidate. It is not a claim that a later published Vault ISO passed these same tests. For the current release, consult the current release notes, signed artifacts, build provenance and acceptance records.

## Candidate status and correction

A candidate ISO was built and a clean BIOS/UEFI installation and boot without the ISO succeeded. The tested ISO had SHA-256:

651fc0a648a0dcaccaa11ecf6036878d59e015f9c761d5bc0785bae66101d063

Final testing then found two defects: an empty Finish was blocked by the systemd inaccessible directory at /run/user/1000/systemd/inaccessible/dir, and preparation left .local owned by root with mode 0700. The source was corrected, but a new final ISO build and acceptance were still required at the time of this report.

Bitcoin Core was given its own runtime directory at /run/core-vault/state/core-runtime. The shared desktop runtime is read-only to Core and is excluded from its writable wallet inventory. The startup code corrects .local ownership and tests the relevant storage and process paths. Unknown unreadable directories inside real writable RAM roots continue to fail closed. The four affected runtime files have corresponding identical template copies.

The earlier ISO failed the expected stale-payload gate; passing a source-level test did not make that older image acceptable. The candidate overlay used in some of the tests was temporary and did not modify the installed VM source.

## Security architecture under test

The Debian/Calamares installation used a minimal Openbox/tint2 desktop with Thunar. System applications and immutable files remained on the installed disk. The private account home was bind-mounted from protected tmpfs before LightDM startup. Wallets were created directly in RAM, rather than written to disk and subsequently deleted.

An unprivileged bubblewrap namespace restricted Bitcoin Core writes to checked private RAM locations. The OS, external media, device filesystem and /dev/shm were read-only to Core. Child mounts under the allowed writable roots were rejected to avoid recursively importing an unintended filesystem. There was no unconfined fallback. Local RPC, a single Core process and offline network options were preserved.

Mount checks used the effective kernel mount ID, not only a flattened mount table: a shadowed mount entry must not be mistaken for a writable destination, while a real descendant bind must be rejected. Native Core backups and signed PSBT files were directed to RAM. Wallet Backup used Bitcoin Core's official backupwallet RPC, produced encrypted 7z archives on selected removable media and verified recovery in RAM. Newly attached input files were copied into Private Workspace before opening them in Core.

Loaded wallet names and physical paths, including absolute and relative paths, were inventoried. Normal Finish required verified encrypted exports for every recognized wallet. Core was stopped cleanly; inventory and logical SQLite data were checked again, the clipboard was cleared, and a narrow shutdown helper finished the session. An explicit emergency option could abandon an unbacked-up RAM session. Shutdown was not described as a physical overwriting of RAM.

Controls included no-swap mounts; disabled hibernate/suspend/resume; volatile home, logs, temporary files and printer spool; disabled core dumps; and restricted power paths. Files or terminals could still intentionally write to selected external media. This confinement was not a claim that all applications were incapable of exporting plaintext.

## Observed candidate results

| Check | Result and scope |
| --- | --- |
| Private-session tests | PASS 22/22 in the later correction run; an earlier source review passed 19/19 |
| Installer tests | PASS 49/49 |
| Source, package, startup and UI gates | PASS |
| Official Bitcoin Core launcher, private runtime writable, OS/device/media read-only, one instance | PASS |
| Fresh BIOS/UEFI install and boot without ISO | PASS |
| Empty Finish on the originally built ISO | FAIL: known runtime-directory defect |
| Corrected BIOS candidate overlay: wallet inventory, create, encryption, backup, virtual USB export, integrity, incorrect password and restore | PASS |
| Restored address, label, public receive/change descriptors and locked encrypted wallet | PASS |
| Incorrect GUI passphrase preserves session; verified Finish shuts down VM | PASS with candidate correction |
| Cold boot after normal Finish: empty wallet directory, receipts and markers | PASS |
| KeePassXC GUI start | PASS smoke test; a full KDBX/clipboard acceptance was not claimed |
| Abrupt QMP interruption with Core and KeePassXC active | Executed |
| Offline disk scan after normal Finish | PASS: zero matches for four supplied synthetic markers in 25,769,803,776 scanned bytes |
| Offline disk scan after abrupt interruption | PASS: zero matches for two supplied synthetic markers in 25,769,803,776 scanned bytes |
| Boot after abrupt interruption | PASS on candidate overlay; no wallet/receipt/marker files |
| Newly rebuilt final ISO without candidate overlay | PENDING at the time of this report |

The raw disk SHA-256 after a normal shutdown was:

a79c8f8c44da14941e8235ec5bfae2bc21dd23a52d45d939fc938d97878b8018

The raw disk SHA-256 after an abrupt interruption was:

7315d6c1da6b3def9a97ec94003bb6292299839c534383523f888929ab8000b5

These marker scans checked only the supplied synthetic values, including deleted blocks. They do not certify arbitrary data destruction or protection from a compromised OS, malicious firmware or live memory acquisition.

Evidence recorded for this work was under /home/pavao/vault-test-results/ram-session-20261004/final-acceptance-1612, with launcher-fixed.log, installer-fixed.log, fixed-normal-finish-serial.log, fixed-normal-finish-scan.log, fixed-cold-boot-and-powerloss-serial.log and fixed-powerloss-scan.log. The local path identifies where tests were recorded; the files were not automatically published as part of this document.

## Earlier source and application review

The earlier source review used synthetic wallets and passwords, never real signing keys. Its evidence directory was /home/pavao/vault-test-results/ram-session-20261004/continuation-20261004.

- Private-session regression suite: PASS 19/19, including hidden and active submounts, kernel mount IDs and fail-closed metadata.
- Installer: PASS 49/49, including the protected /media mount, idempotence and preserving child filesystems.
- The production launcher started official Core, created and encrypted a wallet, wrote a native RAM backup, rejected simulated OS/USB/device destinations, held its single-instance lock and released it after stopping.
- Regtest and backup/recovery tests completed the disposable funding and PSBT signing workflow, opened a path-like wallet, verified the encrypted 7z archive, rejected a wrong password and restored from that actual exported archive.
- Source preflight: PASS 14/14. Calamares package and staged-package gates passed without recompiling unchanged inputs.
- The Home UI passed tests at 800x600, 1024x768, 1280x800 and 1920x1080. A missing SVG plugin and obsolete test strings were corrected in the test environment; the visual production Home code was unchanged.
- The stale original ISO was rejected as intended: Stale private session payload in ISO: usr/lib/core-vault/runtime.py.
- The boundary launcher SHA-256 was d19fa171bd77da114b530607c4f8cbb83f549e9830ebb341f892a49e4004637c, and its inner helper SHA-256 was a6a69253db36a5bc232e1ae272e7df6fba264757844bad7b157c046c24769331. Syntax checks passed for 29 modified Python files and seven shell files.

This review did not exercise the final installed boot sequence, actual removable devices or all window-manager actions. The Regtest application fixture simulated destination media classification. Earlier failures remain relevant test history and should not be silently interpreted as success.

The earlier candidate ISO was 752,877,568 bytes with SHA-256:

1449745bada4402a099f8490c40ef0247c87091e2da940114e83db9385f3601f

After that image, the source received wallet-state, backup, RPC string-parsing, emergency Finish and Qt clipboard handling fixes. A test of one clipboard correction used changed code in a volatile VM overlay, not a rebuilt installed ISO. A separate 24 GiB raw image marker test reported PASS_NO_SUPPLIED_MARKERS with SHA-256:

8fdc3d68d7ea42e03bcd295cef5933a66467a758f827c2ad2e1074a1b39336f2

That result covers only the specific marker and tested image. The official Bitcoin Core 31.1 binary was not modified; its bitcoin-qt SHA-256 was:

fcd4c1a3193e0cb4eec9d980c835d822ad726627b0c01281b13f5c3c1f593fcb

The Calamares package in this source review was 3.3.14-1+corevault3, and the backup package was 0.5.0.

## Outstanding acceptance at the time

A new build needed clean BIOS and UEFI installations on disposable disks, boot without ISO, security checks, actual wallet encryption and backup, encrypted USB export, incorrect-backup rejection and recovery. It also needed KeePassXC and clipboard checks, normal Finish, cold boot, forced crash and power loss, followed by an offline scan of the entire stopped virtual disk for the designated test values.

The existing local rebuild entrypoint was:

    cd /home/pavao/core-signer-os
    bash tools/core-vault/build-live-iso.sh

The remote command environment blocked sudo. That restriction was not bypassed: privileged rebuilds had to run on the local build machine. At the time, the candidate was explicitly **not** accepted as a final security-reviewed ISO.

## File inventory of the October 4 change

```text
config/hooks/live/0948-core-vault-private-session.hook.chroot
config/hooks/live/0950-core-vault-installer-check.hook.chroot
config/hooks/live/0960-core-vault-sync-accessibility.hook.chroot
config/includes.chroot/usr/lib/core-vault-installer/target.py
config/includes.chroot/usr/lib/core-vault/export.py
config/includes.chroot/usr/lib/core-vault/runtime.py
config/includes.chroot/usr/local/bin/core-vault-bitcoin
config/includes.chroot/usr/local/bin/core-vault-finish
config/includes.chroot/usr/local/bin/core-vault-guide
config/includes.chroot/usr/local/bin/core-vault-install-check
config/includes.chroot/usr/local/bin/core-vault-security-check
config/includes.chroot/usr/local/bin/core-vault-storage-check
config/includes.chroot/usr/local/bin/core-vault-wallet-backup
config/includes.chroot/usr/local/libexec/core-vault-core-session
config/includes.chroot/usr/share/core-vault/shred-policy.json
config/package-lists/core-vault.list.chroot
tools/core-vault/calamares/tests/test_installer.py
tools/core-vault/check-backup-iso.py
tools/core-vault/check-core-startup-v4.py
tools/core-vault/check-installer-iso.py
tools/core-vault/check-private-session.py
tools/core-vault/check-ui-polish-v4.py
tools/core-vault/docs/RAM-BOUNDARY-REVIEW-20261004.md
tools/core-vault/docs/RAM-PRIVATE-SESSION.md
tools/core-vault/manifests/core-vault.list.chroot
tools/core-vault/runtime-template/usr/lib/core-vault-installer/target.py
tools/core-vault/runtime-template/usr/lib/core-vault/export.py
tools/core-vault/runtime-template/usr/lib/core-vault/runtime.py
tools/core-vault/runtime-template/usr/local/bin/core-vault-bitcoin
tools/core-vault/runtime-template/usr/local/bin/core-vault-finish
tools/core-vault/runtime-template/usr/local/bin/core-vault-guide
tools/core-vault/runtime-template/usr/local/bin/core-vault-install-check
tools/core-vault/runtime-template/usr/local/bin/core-vault-security-check
tools/core-vault/runtime-template/usr/local/bin/core-vault-storage-check
tools/core-vault/runtime-template/usr/local/bin/core-vault-wallet-backup
tools/core-vault/runtime-template/usr/local/libexec/core-vault-core-session
tools/core-vault/runtime-template/usr/share/core-vault/shred-policy.json
tools/core-vault/test-core-launcher.py
tools/core-vault/test-core-startup.py
tools/core-vault/test-core-wallet-export.py
tools/core-vault/test-private-session.py
tools/core-vault/test-ui-polish-v4-qt.py
```
