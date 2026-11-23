# Native partition installer candidate

This candidate keeps the existing Keyboard → Disk → Review shell and branding. The native Calamares source, the runtime guard and the boot finalizer are a single versioned change. Turning on the YAML manual option alone does not provide this implementation.

## Choices and scope

Disk shows only **Install to disk** and **Advanced partitioning**. Nothing is selected automatically. Install to disk replaces the selected physical disk; every other physical disk is preserved. Existing whole-disk BIOS and UEFI installation remain available. Advanced requires UEFI and a GPT layout. Legacy BIOS shows the reason the Advanced option is unavailable.

Advanced lists the real partition table. Edit assigns one existing partition to `/`, explicitly formatting it as ext4. The format checkbox starts unchecked. An existing same-disk FAT32 ESP of at least 128 MiB is reused without formatting; when several exist, select the desired ESP explicitly. If no ESP exists, Create layout can create a 512 MiB ESP in actual unallocated space. Existing filesystems are never shrunk or moved.

Create layout uses one selected unallocated span. It creates the current product's root and, optionally, an unformatted reservation for the other product. Node root must be at least 32 GiB; Vault root at least 16 GiB. The example Vault reservation is 32 GiB and editable. A Node reservation is editable and must be at least 32 GiB; it is not blindly fixed to the Vault example size. These minima are installation constraints, not estimates of full blockchain storage.

Erase selected disk inside Advanced is a separate explicit action. It stages a new GPT table and removes every existing partition from that selected physical disk. Review reports the whole-disk erase before execution. Selecting Create layout without that action cannot consume existing partitions or filesystem free space.

A verified reserved slot may be highlighted, but it is never formatted automatically. Recognition requires the product, serial/WWN, GPT disk GUID, PARTUUID, exact byte boundaries and absent filesystem signature to agree with a bounded metadata record on the ESP. A partition label alone is never sufficient. Edit and Review still require explicit consent.

## Guard and job order

`install_plan.py` validates the real native model and queued KPM jobs. The native serializer includes each job's actual device, its partition's device and path, byte span and final mount/format state. Other disks cannot receive a job, mount assignment or format intent. A pre-write probe compares the complete initial disk identity and partition layout. The existing live-USB, external/removable, mounted, active-swap, held-device and missing-identity checks remain active.

Before the partition jobs run, the accepted plan is written under root-only `/run/core-installer/confirmed-plan.json`. Native KPM jobs then execute. A reservation preparation job runs before mounting: it may clear stale filesystem signatures only inside newly created, reviewed companion reservations, after identity, boundaries and unmounted state are checked again. Existing empty partitions never enter that operation. Root and EFI filesystems use their explicit KPM create/format operations.

Review obtains the same native plan and blocks installation when validation fails. It lists the exact root/EFI/reserved/preserved partition actions and shows the selected physical disk model, size and path. The acknowledgement resets whenever Review is entered.

## Boot ownership

The products use distinct EFI vendor directories: `EFI/BitcoinCoreNode` and `EFI/BitcoinCoreVault`. The standard bootloader module does not overwrite the shared fallback. The finalizer writes only the confirmed mounted target and selected ESP. It creates `EFI/BOOT/BOOTX64.EFI` only if absent, or refreshes that file only when its same-product ownership record and exact hash match. Existing unrelated or other-product fallback bytes are preserved.

The newly installed system receives GRUB chainloader entries for verified peer installation records, discovered with read-only `mtype` access to internal ESPs. A reservation on the same ESP creates a conditional peer entry that becomes visible when the second product is installed. On two physical disks, the second installation can offer both products from its new default boot menu; the first OS root and GRUB configuration are not rewritten. Distinct firmware entries remain available. No `os-prober` mounting of another operating system is enabled.

## Verification boundary

Pure policy, identity and metadata tests do not prove that an ISO installs and boots correctly. Native source compilation also does not replace installation testing. Candidate acceptance requires disposable QEMU runs using the actual new images:

| Scenario | Required evidence |
| --- | --- |
| Whole-disk UEFI and BIOS | Install, remove ISO, boot installed product; Advanced unavailable in BIOS |
| Node first, same disk | Reserve Vault, install Vault into that verified slot, boot both |
| Vault first, same disk | Reserve Node at an adequate chosen size, install Node into that slot, boot both |
| Two physical disks | Select each intended disk, verify the other disk's existing partitions/files remain unchanged, boot both |
| Existing third-system partition | Explicit root format only; unchanged preserved partition hashes, ESP UUID and existing EFI files |
| Changed or unsafe target | Refuse before writes; no job starts on mounted/live/removable/changed identity |

A same-disk two-product fixture needs more than 64 GiB when both example roots are 32 GiB and EFI is 512 MiB; use a disposable 96 or 128 GiB sparse image. Stable widget names include `coreInstallDrive`, `coreInstallMethodErase`, `coreInstallMethodAdvanced`, `corePartitionTable`, `coreCreateLayout`, `coreEditPartition`, `coreEraseDisk`, `coreRootSizeGiB`, `coreReserveCompanion`, `coreReservedSizeGiB` and `coreFormatRootConsent`.

Run the fixture policy tests with `python3 tests/test_install_plan.py` and the existing eligibility tests with `python3 -m unittest discover -s tests -p test_installer_disks.py`. These commands do not open or change block devices. The Vault tree carries the same policy suite under `tools/core-vault/calamares/tests/`.
