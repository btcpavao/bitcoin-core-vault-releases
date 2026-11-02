# Bitcoin Core Vault — Calamares V1 integration contract

Status: agreed scope and integration preparation. This document is not an
implemented installer and does not certify a bootable installed system.

## Scope

Reuse the earlier Core Offline Calamares source patch, branding and pre-write
disk guard. Retain Calamares for partitioning, filesystem copy and bootloader
installation. Do not replace it with a separate imitation installer.

Preserve the working Vault desktop, 10-card Home, hover help, window controls,
Core launcher, VeraCrypt, USB/optical tools, printing and custody guide.

## User experience — English UI

Only two choices, followed by a clear confirmation:

1. Keyboard — “Choose your keyboard layout”. Layout selector, optional variant,
   and a small typing test. No language, location, timezone or keyboard-model page.
2. Disk — “Choose where to install Bitcoin Core Vault”. Show eligible internal
   drives with model, capacity and a short identifier. One drive per card/row.
   No partition diagrams, manual partitioning, filesystem selection or dual boot.
3. Review — “Ready to install”. Repeat keyboard, exact disk model/capacity/identity
   and the warning “Everything on this drive will be erased.” Require explicit
   acknowledgment and a final “Erase drive and install” button. Nothing should
   modify the target disk merely because it is selected.
4. Installing — actual Calamares progress, not simulated progress. Technical log
   remains available but collapsed. Prompt to keep power and boot media connected.
5. Finished — “Bitcoin Core Vault is ready” and “Restart into Bitcoin Core Vault”.
   No “Restart now” checkbox. Offer power off as a secondary action if supported
   by the reviewed finished module. Do not declare success after failed checks.

Black background, white primary text, muted secondary text, consistent controls,
Bitcoin logo and Bitcoin Core Vault title above, Debian logo and “Powered by
Debian” below. Preserve the visual conventions of the original Calamares work.
Test at least 800x600, 1024x768 and 1280x800 for clipping and control accessibility.

## Boot and installation modes

- Retain a Live Vault entry with toram.
- Add a separate Install Bitcoin Core Vault boot entry; immutable SquashFS remains
  on the boot medium throughout installation. Do not install the current writable
  Live session or any user-created files from that session.
- Installed system boots from its own internal disk, without boot=live, toram or
  installer flags, directly into the Vault desktop as account vault.
- No full-disk encryption, no password prompt at boot, no swap, no account wizard.
- Persistent /home/vault, including the normal Bitcoin Core datadir.
- A dedicated verified tmpfs for /home/vault/Private Workspace. A failed mount must
  not silently fall back to storing temporary sensitive work on the internal disk.
  Verify filesystem type and ownership at runtime. Escape spaces correctly in
  fstab or use a properly named systemd mount unit. RAM-only must be tested.
- No claim that tmpfs prevents applications from creating copies elsewhere or
  guarantees physical RAM sanitization.

## Target safety and installation correctness

- Dedicated whole INTERNAL drive only, matching the existing reviewed guard.
- Reject boot media, removable/USB targets, mounted/in-use/read-only targets and
  ambiguous identities. Revalidate the selected disk identity before writes.
- Keep the old guard checks and tests; do not weaken them to make a test pass.
- Support separately tested BIOS and UEFI boot paths. No Secure Boot claim until
  actually supported and tested. Users should not have to choose GPT/MBR manually.
- Retain no-network and no-swap protections before desktop login and during install.
- Preserve official Bitcoin binaries byte-for-byte; verify installed payloads.
- Reconcile renamed Vault user/service/asset paths against files actually present.
  Do not assume that replacing core-signer with core-vault creates those files.
- Installed autologin and account policy must be explicitly checked.
- Preserve VeraCrypt service policy and local printing permissions in the target.
- Remove the Calamares package, launcher, installer-specific privilege rule and
  installer-only files from the target, without blanket dependency autoremove.
- Keep the target-only separate mounted root check. Never run target.py on the
  developer computer's root filesystem.

## Acceptance gates before physical installation

1. Source/config/package validation and tests of the disk rejection cases.
2. BIOS VM with only a disposable file-backed test disk: install, reboot without
   ISO, desktop startup and clean shutdown.
3. Equivalent UEFI test with isolated OVMF variables.
4. Persistent dummy-file test through two reboots; separate Private Workspace
   dummy-file disappearance test and findmnt confirmation that it is tmpfs.
5. No installer or broad installer sudo remains after install.
6. Core launch, duplicate-launch handling, overlay, window controls, VeraCrypt
   disposable container, file Places, printing UI and USB/optical tools.
7. Only then a separately confirmed physical disk installation test. Physical
   installation erases the selected disk and requires its own explicit confirmation.
