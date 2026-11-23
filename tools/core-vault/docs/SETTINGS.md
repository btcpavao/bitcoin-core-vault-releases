# Vault local Settings

The bottom-right desktop row is Settings, Restart, Finish & Shut Down. The gear
opens one reusable modeless Settings window with Display Settings, Keyboard and
Mouse, Date & Time, and Backup and Restore. The latter launches the existing
wallet backup and decryption tools; recovery continues through Bitcoin Core's
File → Restore Wallet action.

The visual treatment, control sizes and common category icons follow the
existing Node/Vault desktop style. Settings children can be minimized and
reopened. Display changes recover off-screen child windows and keep Home on the
current primary screen. Application launches refresh the confirmed interface
scale from the shared display component.

## RAM-only device preferences

Input code is a local adaptation of Node's supported X11 controls. It calls
`setxkbmap`, `xset`, `xinput` and the existing Num Lock helper as the desktop user.
There is no system keyboard writer, radio control, network settings category,
online updater, login management or account creation.

Device preferences are written only after verifying `/home/vault` is the active
private RAM home. Preference paths must remain on that RAM filesystem and may
not traverse symlinks. The watcher reapplies supported settings to matching
devices after reconnect. It does not repeatedly force Num Lock while typing.

The shared display component owns safe display selection, its 15-second
Keep/Revert transaction and display-profile validation. The session owns its
background watcher. Vault never restores preferences from a persistent home.

## USB device profiles

Export device settings and Import device settings use the same allowlisted JSON
format as Node: keyboard layout/options, bounded input preferences and an
optional saved display profile. Export creates a new file and refuses to
overwrite an existing destination. Import validates before enabling actions.
Input application and display review are separate; the display must still be
applied and confirmed through Keep changes. Wallets, passphrases, network
settings, arbitrary paths and saved clock timestamps are outside the format.

Imported preferences remain in RAM. The user can explicitly save a profile on
USB for a later session. These preferences are not a wallet backup.

## Offline manual date and time

`/usr/local/libexec/core-vault-time` is a fixed isolated Python entry point.
Polkit authorizes only the `vault` user in an active local session for this exact
helper. It takes no command-line arguments. Its bounded JSON input accepts only
a recognized system zoneinfo name and a validated manual local date/time. It
rejects duplicate fields and ambiguous or skipped daylight-saving times.

The helper changes the running system clock with `clock_settime`. It does not
enable NTP or call a hardware-clock writer. A root-owned timezone file under
`/run/core-vault-time` is bind-mounted over the image's regular `/etc/localtime`
file. The image hook makes `/etc/localtime` a regular file in advance, avoiding a
bind over a zoneinfo symlink. The source and lock are fixed root-owned RAM paths;
unexpected existing mounts and unsafe ownership/modes are rejected. Runtime
timezone changes disappear when the system restarts. No clock value is exported
in a device profile.

## Verification and release checks

Run `tools/core-vault/test-settings-local.py` using PySide6 and
`QT_QPA_PLATFORM=offscreen`. It covers local-only categories, single-instance
navigation, the real footer, compact layout, off-screen recovery, launch-scale
refresh, RAM guards, date/time validation and rejection before privileged side
effects. Canonical runtime files and `runtime-template` copies must match.

These tests never change the host clock, keyboard, display, mounts or networking.
Before publishing a new ISO, exercise the actual helper under the installed
Vault Polkit/session policy in a disposable VM. Verify manual time changes, the
RAM timezone mount and its removal on reboot. Also verify display rollback,
USB profile review, local input changes and that device preferences reset in the
next Vault session while an explicitly exported USB profile remains available.
