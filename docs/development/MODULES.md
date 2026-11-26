# Vault module and change map

This map was checked against publication source `58f873fa727054f262b2f99bf742aff251cc5672` on 2026-11-26. Select the actual baseline through [CURRENT.md](CURRENT.md); read [PRODUCT.md](PRODUCT.md) for behavior and [SHARED-WORKFLOW.md](SHARED-WORKFLOW.md) for the change process. Listed tests are available entry points, not a claim that this documentation task ran them.

## Source classes

| Tree | Role and editing rule |
| --- | --- |
| `config/includes.chroot/` | Runtime payload copied into the image. A relative path below this directory is normally the corresponding installed absolute path. Edit the relevant source here, not a running installed copy. |
| `tools/core-vault/runtime-template/` | Mirrored runtime source used by preparation/checks. Where a counterpart exists, maintain the pair in the same change. Inspected Home, taskbar, shared display and all 12 settings files match their counterparts at this baseline. This does not assert equality for every file or for the accepted ISO's documented metadata exception. |
| `tools/core-vault/backup-src/` | Source and packaging for the backup application. `src/` and `tests/` are the reviewable inputs; rebuilding its package is separate from editing desktop wrappers. |
| `tools/core-vault/calamares/`, `tools/core-vault/installer-source/`, `tools/core-vault/installer-template/` | Installer policy/native integration, retained source and staged configuration. Read [ADVANCED-INSTALLATION.md](../ADVANCED-INSTALLATION.md) and [NATIVE-REBUILD.md](../NATIVE-REBUILD.md) before selecting the actual native build input. Do not assume an old template or older package recipe is the release's v10 native source. |
| `config/hooks/`, `config/package-lists/`, `auto/` | Image assembly, system defaults, packages and boot hooks. Changes can affect both Live and installed behavior. |
| `tools/core-vault/generate-branding.py` plus `tools/core-offline/branding/` | Generates tracked desktop/Plymouth image assets. Change source text/artwork and regenerate intentionally; do not hand-edit a generated bitmap alone. |
| `tools/local-build/` | Retained local assembly/repacking provenance, including historical absolute paths and intermediate-image dependencies. Not a general clean-build guarantee. |
| `tools/rebuild/` | Release-specific reconstruction recipes. Follow the selected release's `docs/REBUILD.md`; older successful v0.8.0 recipes do not establish v0.9.0 equality. |
| Build directories, chroots, package outputs, VM disks, ISO files | Generated artifacts. A fix only in these locations is not a complete source change. Record exact inputs if a deliberate repack is used. |
| Release manifests, signatures, accepted evidence | Immutable records of their artifact. Add new evidence for a new artifact; do not rewrite an old result to match new code. |

The authoritative source is a recorded revision and its reviewed changes, not whichever directory was edited most recently. Resolve source/template or source/image differences explicitly before building.

## Module inventory

Paths below `INC/` mean `config/includes.chroot/`; `VTOOLS/` means `tools/core-vault/`. These are abbreviations in this document, not new directories or environment variables.

| Module | Primary editable inputs | Dependencies and data boundary | Focused existing checks |
| --- | --- | --- | --- |
| Home, clock, launcher grid | `INC/usr/local/bin/core-vault-home`; `INC/usr/share/core-vault/icons/` | Settings/time snapshot, application launch environment, primary-screen geometry; no network status or wallet discovery on Home | `VTOOLS/test-home-fit.py`, `test-settings-local.py`, `test-ram-notice.py`; `check-home-suite.py` is an aggregate check |
| Taskbar and Home navigation | `INC/usr/local/bin/core-vault-taskbar`, `core-vault-show-home`, `core-vault-focus-home`; `INC/usr/share/core-vault/openbox.xml` | EWMH/X11 window state and display scaling; window close requests are not process kills | `VTOOLS/test-taskbar-controls-x11.py`, `test-window-behavior-qt.py`, `test-window-behavior-x11.py`, `test-window-maximize-x11.py` |
| Settings shell and device profiles | `INC/usr/lib/core-vault/settings/vault_settings.py`, `device_profiles.py`, `device_profile_data.py` | Modeless reusable windows; bounded import/export; display apply remains a separate confirmation transaction | `VTOOLS/test-settings-local.py`, `test-device-persistence.py` |
| Keyboard and pointer | `INC/usr/lib/core-vault/settings/vault_input*.py`, `vault_pointer.py`; `core-vault-numlock` | Unprivileged X11 controls, RAM working preferences, allowlisted installed persistence; session watcher replays matching-device preferences | `VTOOLS/test-keyboard-x11.py`, `test-numlock-x11.py`, `test-device-persistence.py` |
| Installed device preference store | `INC/usr/lib/core-vault/settings/vault_device_state.py`; fixed `INC/usr/local/libexec/core-vault-device-settings`; Polkit action/rule; `core-vault-prepare` | Only layout/input/pointer/display/timezone; fixed root-owned record, validated installed marker, RAM restore destinations | `VTOOLS/test-device-persistence.py`; real installed/live reboot remains separate |
| Offline date/time | `INC/usr/lib/core-vault/settings/vault_time.py`, `vault_time_ui.py`; fixed `INC/usr/local/libexec/core-vault-time`; time Polkit action/rule | RAM zone mounts; zone-only apply does not set time; explicit installed correction updates/checks RTC; no NTP | `VTOOLS/test-time-settings-local.py`, `test-settings-local.py`; VM helper authorization and reboot checks |
| Display and scale | `INC/usr/share/core-desktop/core_display.py`, `core_display_settings.py`; `INC/usr/local/bin/core-display-*` | RandR, independent rollback worker, RAM recovery journal, hardware identity; installed Vault persists only validated profile | `VTOOLS/test-display-scale.py`, `test-display-x11.py`, `test-session-display-handoff.py`, `test-device-persistence.py`; inspect each test's runtime prerequisites |
| Private session and finish | `INC/usr/local/libexec/core-vault-prepare`, `core-vault-destroy`; private-session library, mounts/services; `INC/usr/local/bin/core-vault-session`, `core-vault-finish` | RAM home, swap/dump policy, clean Core stop, clipboard, narrowly scoped root teardown; no backup-verification gate at shutdown | `VTOOLS/check-private-session.py`, `test-private-session.py`, `test-installed-private-session.py`, `test-finish-session.py` |
| Core launch/confinement | `INC/usr/local/bin/core-vault-bitcoin`, `core-vault-hide-sync`, `core-vault-core-file-dialogs`; `INC/usr/lib/core-vault/runtime.py` | Verified upstream Core binaries, bubblewrap/private paths, loopback RPC; no unsandboxed fallback | `VTOOLS/check-core-release.py`, `test-core-launcher.py`, `test-core-startup.py`, `test-core-sync.py`, `test-core-file-dialogs.py` |
| Watch-only and PSBT USB export | `INC/usr/lib/core-vault/public_export.py`, `export_view.py`; `INC/usr/local/bin/core-vault-media-view`, file-dialog helpers | Validated public output staged in RAM; selected mounted destination; cancel/error/success semantics | `VTOOLS/test-public-export.py`, `test-core-export-view.py`, `test-native-watch-only.py`, `test-core-media-view.py` |
| Snapshot and encrypted backup | `INC/usr/lib/core-vault/export.py`; `INC/usr/local/bin/core-vault-wallet-backup`; `VTOOLS/backup-src/src/{backup,gpg_backend,layered_backend,destinations}.py` | Consistent supported wallet snapshot; plaintext RAM staging; new-file ciphertext publication; optional explicit plaintext USB recovery | `VTOOLS/backup-src/tests/test_direct_wallet_compat.py`, `test_gpg_backend.py`, `test_gpg_integration.py`, `test_layered_filenames.py`, `test_usb_destinations.py`, `test_wallet_inputs.py`; wrapper handoff tests |
| Files/removable media/deletion | `INC/usr/local/bin/core-vault-file-places`, `core-vault-shred`; Thunar integration under `VTOOLS/thunar/`; `INC/usr/share/core-vault/thunar-shred.json` | Media identity, writable selected destinations, backup actions; deletion policy must not weaken RAM or Core export boundaries | `VTOOLS/check-places-v2.py`, `check-thunar.py`, `test-thunar-wallet-backup.py`, `test-shred-engine.py`, `test-shred-gui.py` |
| Guides, printing, optical tools | `INC/usr/lib/core-vault/guide_content.py`, `guide_visuals.py`; `INC/usr/local/bin/core-vault-guide`, `core-vault-print`, `core-vault-optical-diagnostics` | Local user content, volatile spool/cache, upstream Brasero; actual optical hardware validation is separate | `VTOOLS/test-practical-guide.py`, `test-guide-visuals.py`, `test-optical-diagnostics.py`; `check-home-suite.py` includes printing policy |
| Installer, boot, T2 selection | `VTOOLS/calamares/`; installer templates/native source companion; `INC/usr/lib/core-vault/t2_*.py`; kernel/hardware manifests and hooks | Target disk identity, partition jobs, EFI/BIOS ownership, firmware paths, selected kernels; highest change impact | `VTOOLS/calamares/tests/test_install_plan.py`, `test_installer.py`, `test_raw_partition_roles.py`; image and disposable-install matrix |
| Packaging and release | Package lists/hooks, `VTOOLS/build-live-iso.sh`, release-specific recipes, `RELEASING.md` | Input pins, native packages, runtime/template parity, exact accepted image, licenses and source companions | Source/package gates, `check-live-iso.py`, `check-installer-iso.py`, `check-private-session.py --iso`; exact-image VM evidence separately |

## Important ownership details

**Settings is not the owner of all persistent data.** The settings UI gathers validated values; the fixed helpers perform privileged writes. Add a new persistent field only through a reviewed schema and restore path. Saving an arbitrary UI dictionary, home directory or clock timestamp would change the current product boundary.

**Shared appearance does not imply identical runtime policy.** `core_display.py`/`core_display_settings.py` and device-profile concepts have counterparts in Node, but each repository contains a copy. Check both exact revisions before transferring a change. Node uses its persistent account home; Vault's working profile stays in RAM and its allowlisted installed store is separate. Vault retains local-only settings, no updater or network category, and no Node chainstate/status surface.

**Native binaries are a separate boundary.** Altering a Calamares Python guard, native C++ UI, package dependency or boot finalizer can require a different native package and source companion. A changed YAML flag alone does not supply the advanced-partition implementation. The accepted v0.9.0 native provenance is documented rather than represented as a new clean binary-equality result.

## Selecting checks without rereading everything

1. Identify the changed module and data/privilege boundary in this table.
2. Read the relevant test entry point and prerequisites. Some checks aggregate other checks, create bytecode, need PySide6/X11 fixtures or expect a prepared root; their names alone do not establish isolation.
3. Use a focused fixture check for the changed behavior and the nearby preserved behavior. If the change touches a shared module, include the corresponding product's affected path.
4. Escalate to a disposable VM for actual display changes, Polkit authorization, session mounts, device persistence, boot or installation. Run destructive installer scenarios only on disposable virtual disks.
5. Record evidence against the exact tested source and artifact. A fixture pass is not an ISO pass; an earlier ISO result is not a new final-image result.

Examples of existing isolated entry points, when their dependencies are available:

```sh
QT_QPA_PLATFORM=offscreen python3 -B tools/core-vault/test-settings-local.py
QT_QPA_PLATFORM=offscreen python3 -B tools/core-vault/test-time-settings-local.py
unshare --user --map-root-user python3 -B tools/core-vault/test-device-persistence.py
```

The last command uses fixture ownership in an unprivileged user namespace; it is not an instruction to change the host's device settings. If user namespaces are unavailable, record that limitation and use an appropriate disposable environment. Do not run `build-live-iso.sh` to validate a prose edit: it contains image preparation, `lb clean` and a full build.
