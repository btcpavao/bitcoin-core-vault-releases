# Vault local Settings

**Current scope: Vault v0.9.0.** Reconciled on 2026-11-26 against publication source `58f873fa727054f262b2f99bf742aff251cc5672`. See [the development baseline](../../../docs/development/CURRENT.md), [product inventory](../../../docs/development/PRODUCT.md) and [module map](../../../docs/development/MODULES.md). This document describes source behavior; it does not add a new runtime or hardware acceptance result.

## Windows and categories

The bottom-right desktop row is Settings, Restart, Shutdown, with the clock above it. The gear opens one reusable modeless Settings window with **Display Settings**, **Keyboard and Mouse**, **Date & Time**, and **Backup and Restore**. The latter launches the existing wallet backup and decryption tools; wallet recovery continues through Bitcoin Core's File → Restore Wallet action.

The visual treatment, control sizes and category icons follow the existing desktop style. Settings children can be minimized and reopened without duplication. Display changes recover off-screen child windows and keep Home on the current primary screen. Application launches refresh the confirmed interface scale through the shared display component. [UI.md](../../../docs/development/UI.md) records the actual dimensions, colors and labels.

Vault has no radio/network category, online updater, login management or account-creation UI. The local input implementation calls supported X11 controls (`setxkbmap`, `xset`, `xinput` and the Num Lock helper) as the desktop user. Its watcher reapplies supported saved preferences to matching devices after reconnect; it does not repeatedly force Num Lock while typing.

## RAM working state and installed device persistence

The account home and ordinary application state remain RAM-only in **both** modes. Settings working files are written beneath the validated private home. Symlink/path and filesystem checks protect those working destinations.

| Setting | Live RAM | Installed Vault |
| --- | --- | --- |
| Keyboard layout/options, repeat and supported device controls | Applies for this session | Applies and saves validated component data for restart |
| Pointer speeds | Applies for this session | Applies and saves validated pointer data |
| Confirmed display profile | RAM working profile | RAM working profile plus validated persistent device record |
| Time zone | RAM runtime zone | RAM runtime zone plus saved zone name |
| Manual date/time correction | Running clock only | Running clock plus UTC hardware-clock update/readback |
| Wallets, password databases, arbitrary files and normal app settings | Volatile | Volatile |

`vault_device_state.py` owns the limited persistence boundary. It accepts only `layout`, `input`, `pointer`, `display` and `timezone`. The root-owned store is `/var/lib/core-vault-device-settings/preferences.json`, with schema 1, bounded JSON, a private directory, a protected lock and atomic file replacement. It is not a persistent user home.

`installed_mode()` requires an ext4 root, no `boot=live`, and the protected `/etc/core-vault/installation.json` marker with the expected completed-installation stage and storage model. Live sessions do not call the persistence helper. An invalid or absent store does not cause restoration of some alternate home directory.

The fixed `/usr/local/libexec/core-vault-device-settings` helper accepts bounded JSON on stdin, no command-line arguments, and verifies the expected Vault account/caller. Polkit authorization is scoped to that helper and the active local session. The store revalidates each component. `core-vault-prepare` invokes `restore_at_boot()` after preparing the protected RAM home and before LightDM; it restores only the validated keyboard/input/pointer/display files and applies the saved zone name. On a rejected restore it reports the failure and retains image defaults.

Current authorities: `config/includes.chroot/usr/lib/core-vault/settings/vault_device_state.py`, `vault_input.py`, `vault_pointer.py`, `usr/local/libexec/core-vault-device-settings`, `core-vault-prepare`, and their runtime-template copies. Paths after the first one retain the `config/includes.chroot/` prefix as applicable.

## Display and USB device profiles

The display component owns display selection, the independently supervised **15-second Keep/Revert** transaction and profile validation. The session owns its watcher. Confirmed Vault display profiles remain at `/home/vault/.config/core-desktop/display.json` in RAM; installed persistence goes through the allowlisted store above. This is different from restoring a persistent home. See [DISPLAY-SETTINGS.md](DISPLAY-SETTINGS.md).

Export/Import device settings uses bounded validated JSON for keyboard layout/options, supported input preferences and an optional display profile. Export creates a new file and refuses to overwrite. Import validates before enabling actions. Input application and display review are separate: an imported display must still be applied and confirmed. Wallets, passphrases, network configuration, arbitrary paths and saved clock timestamps are outside the format.

Applied imported input preferences follow the same mode policy as ordinary Apply: session-only in Live, allowlisted persistence in installed Vault. An exported USB profile remains on the chosen USB medium. Device profiles are not wallet backups.

## Offline date and time

The fixed `/usr/local/libexec/core-vault-time` entry point runs isolated Python and accepts only bounded JSON containing a recognized `timezone` and optional `local_time`. It takes no command-line arguments and verifies the authorized Vault caller. Duplicate fields, invalid zones and ambiguous/nonexistent daylight-saving local times are rejected.

**Applying only a time zone does not set the clock.** The UI uses `local_time: null` unless the user explicitly enables **Set date and time manually**. The selected-zone preview continues to advance and does not send a stale editor value when applying only a zone.

Runtime zone files are root-owned under `/run/core-vault-time` and bind-mounted onto `/etc/localtime` and `/etc/timezone`. The helper validates paths/mounts. Debian Live's zoneinfo symlink is normalized only after checking the Live RAM overlay conditions. Installed mode saves the validated zone name through `save_component('timezone', name)`; boot restoration reapplies the zone without touching either clock.

For explicit manual correction, Live uses `clock_settime` on the running clock and does not write the hardware clock. Installed mode uses fixed `timedatectl --no-ask-password set-local-rtc 0` and `set-time` operations, verifies the UTC policy and checks the hardware-clock readback. An unreadable or incorrect RTC is reported as partial success rather than hidden behind a successful command exit. This is offline manual time handling; it does not enable NTP.

Current authorities are `vault_time.py`, `vault_time_ui.py` and the fixed helper. The older description saying installed time-zone preferences disappear at reboot and no hardware clock can be written is superseded by this v0.9.0 implementation.

## Focused verification

Available entry points are `tools/core-vault/test-settings-local.py`, `test-time-settings-local.py`, and `test-device-persistence.py`. The first two use PySide6/offscreen fixtures and stub privileged time effects. The persistence suite documents an unprivileged user namespace for genuine fixture root ownership:

```sh
QT_QPA_PLATFORM=offscreen python3 -B tools/core-vault/test-settings-local.py
QT_QPA_PLATFORM=offscreen python3 -B tools/core-vault/test-time-settings-local.py
unshare --user --map-root-user python3 -B tools/core-vault/test-device-persistence.py
```

Source/template equality remains part of a settings change. Actual helper authorization, display rollback, a Live restart that loses local preferences, an installed restart that retains only the allowlist, and explicit manual clock/RTC handling require their own disposable-VM or hardware evidence. Keep those results bound to the tested ISO; see the existing v0.9.0 release evidence for what was actually run.
