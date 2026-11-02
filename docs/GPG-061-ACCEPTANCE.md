# GPG 0.6.1 exact-image acceptance

Status: passed for the covered checks; [v0.2.0 was published on 15 October 2026](https://github.com/btcpavao/bitcoin-core-vault/releases/tag/v0.2.0).

The image built on 14 October 2026 is 749,731,840 bytes with SHA-256
`ef6b210772d096e37a3ec6de5fb586b5d1af75e33f33e8ed6ab8425b15b2ae56`.
Its product source is `d11f31b002386287ee7de6fbe1ec10476c9343b6`; later
controller and documentation changes do not change that image. The
[machine-readable report](gpg-061-final-acceptance.json) binds the results to
this checksum and the exact controllers used.

## Covered execution

| Check | BIOS | UEFI |
| --- | --- | --- |
| Live boot and actual RAM/offline policy | PASS | PASS |
| Native whole-disk installation and installer restart | PASS | PASS |
| Installed boot and actual RAM/offline policy | PASS | PASS |
| GPG and 7z native backup dialogs, read-back and receipts in both modes | PASS | PASS |
| Native Files GPG creation and double-click recovery to RAM in both modes | PASS | PASS |
| Native Core restore, labelled address, ownership and locked-state attestation | PASS | PASS |
| Recovered GPG and 7z wallets sign synthetic witness-UTXO PSBTs | PASS | PASS |
| Wrong passphrase, damaged GPG, wrong snapshot and no-overwrite checks | PASS | PASS |
| Wrong Finish passphrase retains session; correct Finish shuts down guest | PASS | PASS |
| Complete 24 GiB virtual-disk exact-marker scans after Live and installed Finish | PASS: zero matches | PASS: zero matches |
| Clean and abrupt-stop cold-boot checks in Live and installed modes | PASS | PASS |

QEMU/KVM used 4 GiB RAM, two virtual CPUs, an owned 24 GiB virtual internal
disk and a separate synthetic USB fixture. No network adapter or host disk was
attached. Normal firmware menus, native installer confirmations and the product's
Finish flow were used. Runtime probes ran as the unprivileged Vault account.

The GUI GPG recovery check compares the recovered RAM file to the authenticated
snapshot before using Core's native Restore Wallet dialog. Core's receiving
address and label are observed, then checked using read-only RPC. The restored
GUI test wallet is closed through Core and its owned RAM files are removed while
the original test wallets remain. Separate recovered-wallet PSBT probes cover
both backup formats; they use synthetic supplied UTXOs and never broadcast.

## Evidence and controller corrections

The release test-results archive contains final VM reports, phase records,
original screenshots, derived OCR images, raw-image hashes, controller sources
and logs, disk-scan records and reset proofs. Failed attempts and exact resume
drivers are retained rather than relabelled as successful.

Small native captions, pointer overlap and a lingering Home hint caused
controller recognition failures. Fixes enlarge actual captured pixels, park
the pointer, dismiss the observed hint through its native background handler
and use native dialog shortcuts after recognizing the expected dialog. A bounded
2x reread of observed wallet-row pixels resolves a 7z caption OCR failure while
retaining the exact format prefix and uniqueness requirement. Required
words, owned-file checks and installation-target checks remain enforced.
The same incomplete-title OCR failure occurred in both installed phases; their
failed screenshots were byte-identical. Reading the actual enlarged native title
preserves the exact account and empty-prompt checks. Full command echo
is separately re-read from enlarged actual pixels when small glyphs are
misrecognized; Return still requires the entire exact permitted public command.
The forensic reader uses the verified current preboot helper readback; prior
helper bytes remain archived. Installer evidence file permissions were tightened
from inherited host defaults to 0600 without changing their bytes or hashes.

Completed Live phase, disk-scan and reset evidence was preserved byte-for-byte
when incomplete installation resumed. Completed installer evidence was also
preserved when failed installed-session tests repeated. Those repeats used
freshly formatted owned synthetic USB fixtures, with the previous image archived
locally and its hash recorded. Exact helper and request bytes were read back and
verified before boot. The installed operating system was not changed.

Each extension records source and preserved-evidence hashes. Per-phase controller
snapshots and resume drivers are retained; consolidated current helpers are
separate from the exact controllers that produced each run. No production file
was overlaid or replaced in the guest.

The consolidated GUI selector self-test, installer screenshot regression and
Terminal-title regression passed separately. Those local checks do not substitute
for native VM execution. All 98 backup unit tests passed in a clean export of the
exact product commit, with tracked executable modes and a persistent temporary
directory. An earlier direct host run failed because its fake GPG script was
group-writable and the disk-negative fixture used the host RAM-backed /tmp;
both logs and the corrected environment record are retained. The exact product
[source CI also passed](https://github.com/btcpavao/bitcoin-core-vault/actions/runs/38572164208).
Build-time source/package gates, image content gates and
the real RAM bind-mount regression are separate supporting evidence.

## Coverage limits

Native Core wallet creation was not exercised: synthetic fixture wallets were
created through Core RPC. Physical-device USB behavior, real funded transactions,
Windows/macOS recovery, physical DRAM sanitization and whole-ISO bit-for-bit
reproducibility are not established. Zero exact-marker matches establish only
absence of those supplied synthetic markers from the scanned virtual disk.

The earlier failing 0.6.0 image and controller attempts remain historical records;
the passing result applies only to the 0.6.1 image checksum above.
