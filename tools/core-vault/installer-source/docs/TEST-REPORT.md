# Local test report — 25 September 2026

## Executed here

- **28 Python unit tests: PASS.** Disk eligibility rejects removable/USB devices, USB sysfs paths with missing transport, mounted children, active swap, active mapped storage, missing stable IDs, small/read-only disks and non-block files. Target checks refuse `/` and unmounted directories. YAML/shell/Python syntax and the narrow installer sudoers syntax pass.
- **Patch application on a copy of the actual uploaded recipe: PASS.** Dry-run did not change the preseed. Application created backups, removed the old preseed and `.xinitrc`, preserved the six working components byte-for-byte, and passed the generated project checks. A second application was rejected instead of stacking another patch.
- **BIOS/UEFI boot-menu fixture: PASS.** The binary hook generated exactly two menu entries, no broken CD-ROM preseed argument and one installer-specific kernel flag. This is a file-generation test, not a boot test.
- `visudo -cf` parsed the installer-only rule without changing the host sudoers configuration.

## Not executed here

- Building the modified Calamares `.deb` with Debian's complete Qt/KPMcore dependency stack.
- Loading the actual Calamares Qt modules and rendering this theme.
- Formatting a virtual disk, copying a real SquashFS and installing GRUB.
- BIOS or UEFI boot of the resulting ISO / installed disk.
- Actual physical T530 keyboard, autologin, backup/restore or shutdown tests with this integration.

The assistant environment did not contain Calamares, QEMU or its Qt development stack. There is no claim that an ISO was built, an installer ran successfully, or this candidate is production-ready. `docs/VM-TEST.md` is the acceptance gate before physical installation.

## Original components intentionally preserved

See `expected-original-scripts.json` for SHA-256 values of the Core session, shutdown dialog, USB sidebar, eject/restore helpers and narrow poweroff rule. The installed-mode target job additionally compares the original Bitcoin Core binaries after unpacking.

## Exact unit-test output

```text
test_narrow_installer_sudoers_syntax (test_bundle.BundleTests.test_narrow_installer_sudoers_syntax) ... ok
test_no_wallet_paths_in_installer (test_bundle.BundleTests.test_no_wallet_paths_in_installer) ... ok
test_normal_entry_preserves_session (test_bundle.BundleTests.test_normal_entry_preserves_session) ... ok
test_python_syntax (test_bundle.BundleTests.test_python_syntax) ... ok
test_root_entry_checks_live_flag (test_bundle.BundleTests.test_root_entry_checks_live_flag) ... ok
test_sequence_only_two_config_pages (test_bundle.BundleTests.test_sequence_only_two_config_pages) ... ok
test_shell_syntax (test_bundle.BundleTests.test_shell_syntax) ... ok
test_yaml_valid (test_bundle.BundleTests.test_yaml_valid) ... ok
test_active_swap (test_bundle.DiskTests.test_active_swap) ... ok
test_child_mounted (test_bundle.DiskTests.test_child_mounted) ... ok
test_file_not_block_device (test_bundle.DiskTests.test_file_not_block_device) ... ok
test_holders (test_bundle.DiskTests.test_holders) ... ok
test_identity_changes (test_bundle.DiskTests.test_identity_changes) ... ok
test_iscsi (test_bundle.DiskTests.test_iscsi) ... ok
test_mapped_child (test_bundle.DiskTests.test_mapped_child) ... ok
test_no_stable_id (test_bundle.DiskTests.test_no_stable_id) ... ok
test_partition_rejected (test_bundle.DiskTests.test_partition_rejected) ... ok
test_read_only (test_bundle.DiskTests.test_read_only) ... ok
test_removable (test_bundle.DiskTests.test_removable) ... ok
test_root_disk_mounted (test_bundle.DiskTests.test_root_disk_mounted) ... ok
test_small (test_bundle.DiskTests.test_small) ... ok
test_usb (test_bundle.DiskTests.test_usb) ... ok
test_usb_sysfs_even_missing_transport (test_bundle.DiskTests.test_usb_sysfs_even_missing_transport) ... ok
test_valid_internal (test_bundle.DiskTests.test_valid_internal) ... ok
test_fstab_idempotent (test_bundle.TargetTests.test_fstab_idempotent) ... ok
test_refuse_host_root (test_bundle.TargetTests.test_refuse_host_root) ... ok
test_refuse_unmounted_directory (test_bundle.TargetTests.test_refuse_unmounted_directory) ... ok
test_swap_removed (test_bundle.TargetTests.test_swap_removed) ... ok

----------------------------------------------------------------------
Ran 28 tests in 0.031s

OK
```
