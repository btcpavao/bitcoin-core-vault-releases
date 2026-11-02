# Review of the uploaded Core Offline recipe

Input: `core-offline-config.tar.gz`, uploaded 25 September 2026.
The archive was inspected without following its absolute symlinks. SHA-256 is recorded in `source-archive.sha256`.

## Confirmed in this archive

- `config/binary` still contains `file=/cdrom/install/preseed.cfg` and `LB_DEBIAN_INSTALLER_PRESEEDFILE="preseed.cfg"`.
- A preseed exists in `config/binary_debian-installer/`, not as `/preseed.cfg` in `config/includes.installer/`.
- Installed-mode repair still relies on d-i's `late_command` rather than the tested Live user-creation path.
- `config/includes.chroot/etc/skel/.xinitrc` remains from the earlier startx path despite migration to LightDM.
- `0300-lightdm-display-setup.hook.chroot` assigns the display-setup script to `lightdm:lightdm`. The replacement gives that root-executed script root ownership, mode 0755.
- The original session script has the current result-based shutdown state machine and narrow sudo poweroff command. It is preserved, not replaced.
- The USB sidebar helper watches `/media/signer`. It is preserved.
- Live and installed boot parameters are different concerns: `toram` belongs to Live; an installed ext4 root boots without `boot=live`.

## Integration design

The old d-i route is removed rather than further preseed-patched. Both boot entries use the same Live kernel: one starts the original Core session; the other starts Calamares through a fixed, root-owned, live-only launcher.

Calamares remains the partitioning, unpacking and bootloader engine. A version-bounded source patch restricts its UI to whole-disk erase, hides unrelated keyboard-model controls, adds the matching product header/footer and inserts a read-only disk-identity check before partition jobs. It also skips OS probing, because this edition neither resizes nor installs alongside another OS.

A selected disk must be internal/non-removable, writable, unmounted, at least 16 GiB, free of active mapped holders/swap and have a serial/WWN. The identity is checked again before writes. These are risk reductions, not a claim that a hot-swappable device can never change after a check.

The original immutable SquashFS is copied, not the running Live root or a user's session. Target jobs create a locked technical account, persist the chosen keyboard, set English/UTC, ensure RAM home/logs and no swap, preserve Core payload hashes and validate narrow poweroff permission **as signer**, without actually shutting down the installation host.

The installed copy of the Calamares package, its configuration, launcher and installer sudo rule are removed. Dependencies are not blindly auto-removed. This adds size to the Live ISO; the build manifest must report the real size and package list.

## Boundaries

This is an integration candidate, not a security certification or tested release ISO. We did not reproduce the reported installed-mode poweroff failure here, so it is not honest to claim its exact runtime cause was proven from `status 1` alone. The new target checks validate the likely policy/account failure points and stop installation if they fail.

The shell, Python and configuration checks below do not prove that Qt plugins load, GRUB boots, every disk controller works, or a specific laptop powers off. The supplied BIOS and UEFI VM tests, followed by physical acceptance, remain mandatory.

The original network/USB threat model, poweroff shortcut safety, residual RAM and firmware issues are outside this installer review. Reusing the original working scripts preserves behavior; it does not certify all of it.
