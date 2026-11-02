# Bitcoin Core Vault — Calamares V1 integration candidate

This archive contains build-source changes, not a prebuilt ISO or Calamares binary.
No installer is executed by apply.py or prepare-installer.sh. The first destructive
operation is performed only inside the installer after the selected-drive review,
acknowledgement and final confirmation. Start with disposable virtual disks only.

## Basis and scope

Based on `bitcoin-core-vault-installer-input-20260930-143606-037001.zip` supplied
by Pavao. Uses the actual current `project/` files and its saved Calamares source
patch. Does not fetch or overwrite the user's GitHub repository. Source changes
are restricted to the `vault-v1` branch; Signer/main is not changed.

Preserves the 10-card Home, hover help, background-click behavior, CoreVault window
theme, Places V2 (Bitcoin Core then Vault), print/recovery text, Bitcoin binaries,
Core launcher, VeraCrypt package verification, and existing application config.
The current session is extended only with an installer route and storage gate.

## Installer UI

Keyboard -> Disk -> Review -> Installing -> Finished.

Only keyboard layout/variant and one whole internal disk are selectable. Review
contains an acknowledgement reset on every entry, and the final button says
“Erase drive and install”. A separate upstream confirmation remains enabled.
USB/removable, mounted, read-only, undersized (<16 GiB), ambiguously identified,
and active mapped/RAID/LVM targets are rejected. BIOS drives >2 TiB are rejected;
boot the installation medium in UEFI for those drives. No dual boot, manual
partitioning, FDE, swap, network, timezone, username or password wizard.

The real Calamares partition, mount, unpackfs, keyboard, fstab, initramfs and
bootloader jobs remain in use. The pre-write disk identity guard is retained;
blank/whitespace identity handling is tightened, not relaxed. This reduces risk,
but cannot eliminate physical hot-swap/TOCTOU risks. Do not attach wallet backup
media while installing.

Black background, Bitcoin Core Vault header, three-stage indicator, Powered by
Debian footer. Previous large fixed margins are reduced for smaller screens;
long reviews scroll rather than enlarging a fullscreen window beyond the screen.
Actual UI layout and C++ compilation still need the local package/VM tests below.

## Persistent target

The immutable SquashFS on the installation medium is copied, not the mutable Live
session. The target creates/validates account `vault`, UID/GID 1000, locked login
passwords and LightDM autologin. Normal home files, including `.bitcoin`, persist
on ext4. No boot passphrase is added.

Private Workspace has its own mandatory tmpfs mount with literal fstab escape
`/home/vault/Private\040Workspace`, uid/gid 1000, mode 0700, nosuid,nodev,noexec.
Its underlying disk directory is root-owned, mode 000. A startup check is required
before installed LightDM and again before the Vault session; missing/wrong mounts
cannot silently become an ordinary writable persistent workspace. Swap remains
disabled. This is not a guarantee of physical RAM sanitization, and does not stop
applications from storing copies elsewhere or users from explicitly exporting.
Logs and /tmp are volatile. The live environment retains its existing RAM model.

Uses the REAL inherited core-signer-offline.service and core-signer-no-swap.service,
not nonexistent renamed variants. Core binaries and selected application/runtime
files are hashed at image build and checked after target copy. Exact existing
poweroff and VeraCrypt sudo permissions are preserved and tested without executing
the privileged operations. Calamares, its config, runtime launcher and installer
sudo rule are removed from the installed target; dependencies are not blanket
removed. Live-boot/config packages may remain inert without boot=live.

Secure Boot is not enabled or claimed. BIOS and UEFI must be tested independently.
An installed-checks-passed marker means target-time checks completed, NOT that a
physical reboot or recovery operation has already been validated.

## Apply (normal user, build computer)

Save the ZIP in Downloads and extract it. Then:

    python3 ~/Downloads/vault-calamares-v1/apply.py --project ~/core-signer-os

The patcher checks expected source hashes against the uploaded snapshot, validates
a merged temporary source tree, saves old source files with their paths in
`~/core-signer-os-backups/calamares-v1-...`, then installs the changes. On a failed
post-write check it restores previous bytes/modes. Unexpected local changes stop
application rather than being silently overwritten. It does not change host
accounts, system services, disk contents or the host's running desktop.

## Build custom Calamares (build computer)

Host prerequisites:

    sudo apt update
    sudo apt install --no-install-recommends debootstrap python3-yaml
    cd ~/core-signer-os
    bash tools/core-vault/prepare-installer.sh

This script requests sudo to create a separate Debian 13 builder chroot under
`build-assets/core-vault-calamares-v1/root`. Allow >=20 GiB free, and an Internet
connection on the BUILD computer. Compiler dependencies are installed in this
chroot, not in the Vault ISO or on the host. It uses Debian authenticated APT
sources, pins source version 3.3.14-1, checks all C++ patch anchors and builds local
version 3.3.14-1+corevault2. Source snapshots, package lists, buildinfo, logs and the
resulting package hash are retained. This is not a sandbox for malicious source
code or a claim of reproducible builds.

An earlier Signer Calamares binary is not relabelled/reused. An exact matching
successful Vault build is reusable; input digest mismatches require rebuilding.
If a package build fails, send the LAST error from its log rather than disabling
checks or changing package versions. The builder can be rerun after an ordinary
compile failure; stale mounts or an incomplete debootstrap require inspection.

Expected completion:

    VAULT CALAMARES PACKAGE CHECK PASSED
    VAULT CALAMARES PACKAGE BUILD PASSED

## Build Live + Install ISO

    bash tools/core-vault/build-installer-iso.sh

The existing live build retains its checks and gains installer package/source/ISO
checks. The boot menu has two choices:

    Start Bitcoin Core Vault (Live RAM)
    Install Bitcoin Core Vault

Live keeps toram. Install does not use toram, keeps the boot medium connected, and
runs an installer-only X session without Vault Home or removable-media automount.
The output name remains `live-image-amd64.hybrid.iso`; save earlier accepted ISO
artifacts in release before rebuilding if they are needed for comparison.

## First BIOS test — no physical disk attached

    bash tools/core-vault/vm-installer-test.sh bios install

Creates only `build-vm/vault-installer-v1/bios/target.qcow2` (24 GiB sparse). No
host block devices, shared folders or networking are attached. Select the Install
entry, choose a keyboard, select the displayed virtual disk, acknowledge erase,
and install. “Restart into Bitcoin Core Vault” exits QEMU intentionally because
-no-reboot is used to force an explicit next boot without the ISO.

Then:

    bash tools/core-vault/vm-installer-test.sh bios installed

In the installed guest Terminal (not the host):

    core-vault-install-check
    core-vault-desktop-check

Use Editor/Files to create `/home/vault/persistent-test.txt` and a separate
`/home/vault/Private Workspace/temporary-test.txt`. Shut down cleanly. Start
`bios installed` again. The first file must remain; the second must be absent.
Repeat once. Test the real applications (only disposable wallets/containers),
Places, printing UI, keyboard, minimization and poweroff. Verify no Calamares entry
or installer privilege remains. Home plaintext is not protected by FDE in V1.

## UEFI test — separate test disk and firmware variables

    sudo apt install --no-install-recommends ovmf
    bash tools/core-vault/vm-installer-test.sh uefi install
    bash tools/core-vault/vm-installer-test.sh uefi installed

Repeat the same installed checks and two-reboot persistence test. OVMF variable
files are created separately and are not overwritten on each test. BIOS/UEFI test
images are distinct. Do not reset or erase them merely to hide a failure.

## Live wallet export test with a virtual USB disk

On the build computer, install `mtools` once if `mformat` is unavailable:

    sudo apt install mtools
    bash tools/core-vault/vm-installer-test.sh bios live --usb-test

Select **Start Bitcoin Core Vault (Live RAM)**. Files and the Wallet Backup Save
chooser should show **VAULT_TEST**, a separate 4 GiB FAT32 USB device. Export a
synthetic encrypted wallet to that device. Its backing file is
`build-vm/vault-installer-v1/bios/usb-test.raw`; it remains between VM launches.
The `--usb-test` option also works with `install`, `installed` and UEFI. Existing
USB images are checked and reused without formatting them again. The installer
continues to reject USB devices as installation targets.

A physical USB plugged into the host is not automatically forwarded to QEMU.
Physical passthrough requires an explicitly selected `usb-host` device, exclusive
use of its storage by the guest and access to the corresponding host USB node.
The test script attaches only ordinary disposable files. Use the virtual USB for
export workflow tests; boot the ISO directly on a test computer for real USB
hardware acceptance. Do not access the backing filesystem from the host while
QEMU is using it.

## Test boundaries

See TEST-REPORT.md. The assistant environment did not have QEMU, a Calamares build
environment, or functional external downloading. It did not compile Calamares,
build a full ISO, boot it, install an OS, or test a physical machine. Source,
file-generation and mocked failure tests do not establish those outcomes.

## Sources used to check interfaces

- User-supplied installer input archive (SHA-256 in calamares/input-bundle.json).
- Calamares v3.3.14: src/modules/summary/SummaryViewStep.cpp and SummaryPage.cpp.
- Calamares v3.3.14: partition/partition.conf and finished/finished.conf.
- Debian Live Manual: installing custom packages via config/packages.chroot.

Calamares source patches and inherited disk guard: GPL-3.0-or-later.
New integration code: GPL-3.0-or-later. Product graphics are inherited from the
supplied project; this package grants no new trademark rights.
