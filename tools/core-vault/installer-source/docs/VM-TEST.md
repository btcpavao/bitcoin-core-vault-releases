# Required VM acceptance test — before any T530 installation

The package has NOT been compiled or boot-tested in the assistant's environment. Local static/fixture tests are not a substitute for this checklist. Do not use a wallet containing funds.

## Prerequisites on the online Debian build computer

```
sudo apt update
sudo apt install debootstrap python3-yaml qemu-system-x86 qemu-utils ovmf
```

Build using the supplied scripts only. Old `lb config --debian-installer live ...` commands re-enable the broken old path and must not be reused.

## Legacy BIOS

```
cd ~/core-signer-os
bash tools/core-offline/vm-test.sh bios install
```

The script creates a **24 GiB sparse qcow2 file**, not a physical partition. It passes no host block device to the guest and gives the guest no network adapter. The test disk has serial `CO_TEST_BIOS`; this is necessary for the disk identity guard.

Choose **Install Core Offline** from the boot menu. Keep the ISO attached during installation.

1. English UI; choose Croatian and test `y z č ć š ž đ @` in the normal text field. Do not enter a real passphrase.
2. Only the virtual disk is offered. Choose whole-disk erase. No manual/alongside/replace option should be available.
3. Check the read-only summary; confirm erasure only of the virtual disk.
4. No network, geographic timezone, account, password, desktop or package-selection pages.
5. Progress and final result must appear normally. Do not assume a frozen progress screen is success.
6. Restart. The VM should boot the installed disk, not start another installation.

Then stop the VM and boot without any ISO:

```
bash tools/core-offline/vm-test.sh bios installed
```

Check automatic `signer` login, fullscreen Core, Croatian typing, Options, minimize recovery, a disposable wallet creation, and both shutdown paths. `Return to Bitcoin Core` must preserve the current RAM session; the countdown and `Shut Down Immediately` must each power the VM off. A QEMU process ending after an orderly guest shutdown is the expected test result.

Create an empty practice wallet; reboot; the new Core session must not display the wallet. This is a functional persistence check, not a forensic proof. No wallet backup USB is automatically attached to these VMs.

## UEFI

Repeat with a separate virtual disk and writable firmware variable file:

```
bash tools/core-offline/vm-test.sh uefi install
bash tools/core-offline/vm-test.sh uefi installed
```

OVMF Secure Boot is not enabled. Require installed disk-only boot to work before claiming UEFI support. The test does not establish Secure Boot compatibility.

## Failure policy

Stop on any failed build hook or installer job. Capture the exact error, not just a screenshot of the splash. The installer log is `/run/core-offline-installer/installer.log` and the session launch log is `/run/user/1000/core-offline-installer-launch.log`; both are runtime logs.

The final target writes `/etc/core-offline/installation.json` with the selected keyboard and preserved payload hashes. This file records configuration checks, not proof that physical shutdown will work.

No retry automatically selects a disk or silently reinstalls. No error permits falling back to a generic Debian installer.

## Only after both VM modes pass

Create a backup of anything on the physical target disk. Disconnect all wallet-backup and unrelated storage. Flash the ISO using a currently verified USB path, not an old assumption that `/dev/sda` is still the stick. Boot the physical machine into the same firmware mode that was tested and select the whole internal target disk.

This first integration deliberately excludes USB-attached target disks, SD/eMMC, mounted volumes, active LVM/RAID/device mapper, and devices without a stable serial/WWN. If the internal disk is not offered, do not bypass the guard: inspect why.

Record BIOS/UEFI, disk model, RAM, ISO SHA-256, date and results. Never include wallet files, private keys, passphrases or personal device serials in a public report.
