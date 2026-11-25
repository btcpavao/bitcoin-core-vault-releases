# Native partition installer

**v0.9.0 status:** The implementation below is included in the accepted release.
See [the release record](RELEASE-v0.9.0.md) for the exact ISO hash, final desktop
checks, earlier installer/settings evidence and Pavao's 25 November acceptance.
The dated development notes in this document preserve what was known during
earlier candidate revisions; they are not a statement that the accepted image
has had no testing. Physical T2 validation and the full firmware/disk matrix
remain separate, unclaimed results.

The implementation keeps the existing Keyboard → Disk → Review shell and branding. The native Calamares source, the runtime guard and the boot finalizer are a single versioned change. Turning on the YAML manual option alone does not provide this implementation.

## Choices and scope

Disk shows only **Install to disk** and **Advanced partitioning**. Nothing is selected automatically. Install to disk replaces the selected physical disk; every other physical disk is preserved. Existing whole-disk BIOS and UEFI installation remain available. This local Vault candidate supports Advanced in both UEFI and Legacy BIOS mode. UEFI uses GPT. Legacy BIOS supports GPT with a BIOS boot partition and existing MBR layouts. Node has not been changed by this local fix.

Advanced lists the real partition table. Edit assigns one existing partition to `/`, explicitly formatting it as ext4. The format checkbox starts unchecked. An existing same-disk FAT32 ESP of at least 128 MiB is reused without formatting; when several exist, select the desired ESP explicitly. If no ESP exists, Create layout can create a 512 MiB ESP in actual unallocated space. Existing filesystems are never shrunk or moved. In BIOS mode an existing GPT BIOS boot partition of at least 1 MiB is reused; otherwise Create layout can create a 2 MiB unformatted bios_grub partition in genuinely unallocated space. MBR uses the embedding gap before the first partition and requires at least 1 MiB there. The installer does not convert a preserved MBR disk to GPT. Existing primary and logical roots are formatted in place without deleting their partition entries or changing partition numbers. Existing extended containers are preserved; new logical partitions can only be appended after existing logical partitions, with EBR space retained. MBR primary layouts remain limited to four entries.

Create layout uses one selected unallocated span. It creates the current product's root and, optionally, an unformatted reservation for the other product. Node root must be at least 32 GiB; Vault root at least 16 GiB. The example Vault reservation is 32 GiB and editable. A Node reservation is editable and must be at least 32 GiB; it is not blindly fixed to the Vault example size. These minima are installation constraints, not estimates of full blockchain storage.

Erase selected disk inside Advanced is a separate explicit action. It stages a new GPT table and removes every existing partition from that selected physical disk. Review reports the whole-disk erase before execution. Selecting Create layout without that action cannot consume existing partitions or filesystem free space. A disk without a recognized partition table has a separate Initialize disk confirmation before staging GPT; unpartitioned data is explicitly treated as data that will be erased.

A verified reserved slot may be highlighted, but it is never formatted automatically. Recognition requires the product, serial/WWN, disk identity, PARTUUID, exact byte boundaries and absent filesystem signature to agree with a bounded metadata record. Existing UEFI records use the ESP and GPT identifiers (schema 1). BIOS records use /var/lib/bitcoin-core-installer on the installed root and GPT identifiers or the MBR disk signature/partition number (schema 2); they are read with bounded read-only debugfs access without mounting another root. A partition label alone is never sufficient. Edit and Review still require explicit consent.

## Guard and job order

`install_plan.py` validates the real native model and queued KPM jobs. The native serializer includes each job's actual device, its partition's device and path, byte span and final mount/format state. Other disks cannot receive a job, mount assignment or format intent. A pre-write probe compares the complete initial disk identity and partition layout. The existing live-USB, external/removable, mounted, active-swap, held-device and missing-identity checks remain active.

Before the partition jobs run, the accepted plan is written under root-only `/run/core-installer/confirmed-plan.json`. Native KPM jobs then execute. An unformatted-space preparation job runs before mounting: it may clear stale filesystem signatures only inside newly created, reviewed companion reservations or new BIOS boot partitions, after identity, boundaries and unmounted state are checked again. A reused BIOS boot partition is never wiped by this preparation. Existing empty partitions never enter that operation. Root and EFI filesystems use their explicit KPM create/format operations.

Review obtains the same native plan and blocks installation when validation fails. It lists the exact root/EFI/reserved/preserved partition actions and shows the selected physical disk model, size and path. The acknowledgement resets whenever Review is entered.

## Boot ownership

The products use distinct EFI vendor directories: `EFI/BitcoinCoreNode` and `EFI/BitcoinCoreVault`. The standard bootloader module does not overwrite the shared fallback. The finalizer writes only the confirmed mounted target and selected ESP. It creates `EFI/BOOT/BOOTX64.EFI` only if absent, or refreshes that file only when its same-product ownership record and exact hash match. Existing unrelated or other-product fallback bytes are preserved.

The newly installed system receives GRUB chainloader entries for verified peer installation records, discovered with read-only `mtype` access to internal ESPs. A reservation on the same ESP creates a conditional peer entry that becomes visible when the second product is installed. On two physical disks, the second installation can offer both products from its new default boot menu; the first OS root and GRUB configuration are not rewritten. Distinct firmware entries remain available. No `os-prober` mounting of another operating system is enabled.

BIOS installation replaces the selected disk's MBR/embedding bootloader, as stated in Review. The standard GRUB install writes only to that selected disk. Verified Node/Vault metadata can produce peer GRUB configfile entries; other operating systems may need manual boot-menu configuration. A verified peer's separate /boot is recognized only from a same-disk ext4 UUID reference. Older BIOS Node installations without hardware-bound records may also receive a selectable menu entry through a separate compatibility detector. It requires the exact legacy installation marker, Debian 13 identity, an ext4 root UUID matching fstab, and a same-disk ext4 /boot when present. It never creates a verified ownership record or modifies the old installation. Generic os-prober scanning remains disabled. The second BIOS installation can add the first installed product to its menu; an empty reservation has no future filesystem UUID to guess.

## Verification boundary

**Historical note from the initial local candidate, 2026-11-24:** At that stage no automated tests or VM installs had been run and no GitHub publication or push had occurred. The table below describes the broader acceptance matrix; individual later results are dated and bound to their ISO hashes in the [v0.9.0 release record](RELEASE-v0.9.0.md). Do not treat every row as passed.

Pure policy, identity and metadata tests do not prove that an ISO installs and boots correctly. Native source compilation also does not replace installation testing. Candidate acceptance requires disposable QEMU runs using the actual new images:

| Scenario | Required evidence |
| --- | --- |
| Whole-disk UEFI and BIOS | Install, remove ISO, boot installed product |
| Advanced BIOS GPT and MBR | Select root or create layout, preserve other partitions and logical numbering, install, remove ISO, boot installed product |
| Node first, same disk | Reserve Vault, install Vault into that verified slot, boot both |
| Vault first, same disk | Reserve Node at an adequate chosen size, install Node into that slot, boot both |
| Two physical disks | Select each intended disk, verify the other disk's existing partitions/files remain unchanged, boot both |
| Existing third-system partition | Explicit root format only; unchanged preserved partition hashes, ESP UUID and existing EFI files |
| Changed or unsafe target | Refuse before writes; no job starts on mounted/live/removable/changed identity |

A same-disk two-product fixture needs more than 64 GiB when both example roots are 32 GiB and EFI is 512 MiB; use a disposable 96 or 128 GiB sparse image. Stable widget names include `coreInstallDrive`, `coreInstallMethodErase`, `coreInstallMethodAdvanced`, `corePartitionTable`, `coreCreateLayout`, `coreEditPartition`, `coreEraseDisk`, `coreRootSizeGiB`, `coreReserveCompanion`, `coreReservedSizeGiB` and `coreFormatRootConsent`.

Run the fixture policy tests with `python3 tests/test_install_plan.py` and the existing eligibility tests with `python3 -m unittest discover -s tests -p test_installer_disks.py`. These commands do not open or change block devices. The Vault tree carries the same policy suite under `tools/core-vault/calamares/tests/`.

## Hardware scope of the local candidate

The ISO is amd64: 64-bit Intel/AMD processors, Legacy BIOS or 64-bit UEFI. Apple Silicon and other non-x86 architectures are outside this image. 32-bit-only CPUs and machines with 32-bit-only EFI are not covered. Secure Boot support is not included in this image. The local T2 addition below supplies a separate T2 kernel and automatic selection; hardware compatibility still requires a physical-machine trial. Installation targets remain eligible internal SATA/NVMe disks with stable identities, not USB/removable media or active mapped/RAID/LVM storage. Existing partitions are not automatically shrunk, moved or converted.


## Automatic T2 support in the local Vault candidate

The same ISO keeps the two existing **Live RAM** and **Install** choices. There is no T2/non-T2 question. Before loading Linux, GRUB reads SMBIOS manufacturer and product name and matches both against `/usr/share/core-vault/t2-models.json`. EFI machines matching `Apple Inc.` or `Apple Computer, Inc.` and one of the following 16 exact identifiers use the T2 kernel. All other machines, including Legacy BIOS, use the standard kernel. This follows the [GNU GRUB SMBIOS interface](https://www.gnu.org/software/grub/manual/grub/html_node/smbios.html) and the [Linux T2 model list](https://github.com/torvalds/linux/blob/master/security/integrity/platform_certs/load_uefi.c).

| Family | Matched identifiers |
| --- | --- |
| MacBook Pro | `MacBookPro15,1`, `MacBookPro15,2`, `MacBookPro15,3`, `MacBookPro15,4`, `MacBookPro16,1`, `MacBookPro16,2`, `MacBookPro16,3`, `MacBookPro16,4` |
| MacBook Air | `MacBookAir8,1`, `MacBookAir8,2`, `MacBookAir9,1` |
| Desktops | `Macmini8,1`, `MacPro7,1`, `iMac20,1`, `iMac20,2`, `iMacPro1,1` |

`/etc/core-vault/kernel-profile.json` pins standard Debian `6.12.116+deb13-amd64` and T2 `6.18.64-1-t2-trixie`. The ISO stores their boot pairs under `/live/` and `/live/t2/` respectively. The installed default, `core-vault-auto`, repeats the same SMBIOS selection at every boot and loads the corresponding versioned pair from `/boot`; it does not inherit the build machine's hardware choice. Both paths share the detection renderer. Runtime hardware helpers independently check DMI; `core-vault.hardware=t2` is only a live diagnostic marker.

Only the T2 branch receives `intel_iommu=on iommu=pt pm_async=off`. There is no global `efi=noruntime` workaround. The installed entry uses the target root UUID, retains ordinary display/quiet options and `noresume`, and excludes live/installer arguments. Calamares' Debian initramfs module defaults to `kernel: all`: it recreates initramfs images for both installed kernels. The T2 initramfs hook adds the BCE virtual USB host plus input, Touch Bar and graphics modules only for the T2 release. Existing BIOS partitioning support and the standard kernel path are retained.

### Mac preparation and EFI space

Firmware authorization still requires the owner's action before booting the USB. Start macOS Recovery with **Command-R**, open **Utilities → Startup Security Utility**, authenticate, select **No Security**, and allow booting from external or removable media. Then hold **Option** at startup and select the USB's EFI boot entry. The ISO cannot change these pre-boot security choices automatically. See [Apple's Startup Security Utility instructions](https://support.apple.com/en-us/102522) and [t2linux's pre-install instructions](https://wiki.t2linux.org/guides/preinstall/).

T2 bootloader installation avoids NVRAM writes and needs a usable Vault-owned EFI fallback. If the selected ESP already contains another system's shared fallback, the installer preserves it and requires a separate suitable ESP. The compiled native Advanced UI now supports creating a **512 MiB FAT32 ESP** from genuinely unallocated space even when an existing ESP is assigned: select the root, select a free span, choose **Create layout**, and confirm **Create separate EFI partition**. The new ESP becomes `/boot/efi`; the old ESP's files and flags and the existing partition boundaries are preserved. There must be at least 512 MiB of usable aligned free space, and Review must still be confirmed before disk writes. No APFS shrink or automatic reclamation of filesystem free space is provided.

This addition targets Vault. Matching a model is not a claim that every peripheral works: [t2linux's feature status](https://wiki.t2linux.org/state/) records remaining device-specific limitations. Apple Silicon is outside this amd64 image. **Historical scope of the initial T2 candidate:** That revision had no automated tests, VM boot/install runs or physical T2 installation trial. Later Vault installation and desktop results are recorded separately; source review and compilation do not establish physical T2 validation.

## T530 partition-preview lifecycle fix

The local T530 revision addresses the reported crash after editing an existing partition and selecting Erase disk. The Advanced table stores value identities (device path, partition path, boundaries and state) instead of raw pointers into preview objects that a reset can destroy. It clears stale rows under signal blocking before resetting the plan, restores the selected disk by its path, and resolves the currently selected partition from the current model. Model-changing resets run on the GUI thread. Bootloader model rebuilds expose one complete reset, with programmatic selection changes prevented from feeding back into a new reset. Storage requirements are initialized before the first choice evaluation.

Create layout is available for a selected unallocated span, or Initialize disk when no recognized partition table is present. Selecting an existing filesystem partition does not make its internal free space available to a new partition layout. Edit assigns and formats that one partition. Erase selected disk stages replacement of that physical disk's complete layout, then selects its new unallocated area for Create layout. The final Review and explicit installation confirmation still precede all disk writes.

The image includes the Qt6 QML modules required by the shipped slideshow (QtQml, Models, WorkerScript, QtQuick and Window), with qml6-module-qtquick-window also required by the native Calamares package. The SMART helper is installed for on-demand disk inspection; the background smartd services are explicitly masked. Launcher diagnostics now record the actual Calamares return code and signal name before the log tail.

Historical scope of this first T530 revision: the fixes were based on the photographed log and static source review. The photos did not include a signal or backtrace proving a unique runtime cause. The missing QtQuick.Window import was a separate confirmed packaging problem. No automated tests, installer execution, VM boots or physical disk writes were performed during that revision. Later partition-role fixes, installation checks and the maintainer's successful installation/acceptance are recorded in the [v0.9.0 release record](RELEASE-v0.9.0.md), with their own evidence boundaries.
