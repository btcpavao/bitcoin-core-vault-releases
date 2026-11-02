# Bitcoin Core Vault: desktop correction V3

## Diagnosed causes

- `panel_dock = 1` embeds tint2 into Openbox's legacy dock. Repeating
  `panel_position = bottom ...` does not disable the legacy dock.
- tint2 background IDs start at 1. ID 0 is transparent.
- A generic `QWidget { background: black; }` matches child `QLabel` widgets.
  The previous patch made title/description labels transparent but left icon
  labels black.
- Frameless + stays-below + maximized is still a normal window. Home now sets
  `WA_X11NetWmWindowTypeDesktop` before mapping, uses actual monitor geometry,
  and reserves the real bottom-panel area inside its layout.

## Scope

This changes only the Vault desktop, Openbox session/panel configuration and
matching runtime templates. The Bitcoin Core binary/wrapper, offline networking
rules, installer, user storage policy and boot splash are not modified.

This does NOT fix or certify the separate Private Workspace mount policy,
software supply chain, application-specific singleton handling or shutdown
safety for unsaved documents. Those need their own tests.

Target: the single-monitor Debian 13 / Openbox / PySide6 Vault V1 environment.
No claim is made about mixed-DPI multi-monitor configurations.

## Apply on the BUILD computer, not inside the Live environment

```
python3 apply.py --project "$HOME/core-signer-os"
```

The patch requires the `vault-v1` branch and the existing Vault files. It makes
per-file backups preserving directory structure outside the Git working tree.
It does not use sudo, run a build, stage or commit anything.

## Preview BEFORE rebuilding the ISO

The build host needs Debian packages:

```
sudo apt install --no-install-recommends python3-pyside6.qtwidgets tint2 openbox xserver-xephyr x11-utils
```

Openbox already belongs to the build/test prerequisites. The preview script
checks all dependencies before opening the nested X server. These preview
packages are installed on the build computer only; Xephyr is NOT added to the ISO.

```
cd ~/core-signer-os
bash tools/core-vault/preview-desktop.sh 1280x800
```

Qt first renders the real UI offscreen at 800x600, 1024x768, 1280x800 and
1920x1080. It checks equal card sizes, centering, footer clearance and the
absence of a black icon-label strip. Then Xephyr runs a separate authenticated
X server with temporary HOME/config/runtime directories, real Openbox, real
tint2 and the same Home code in PREVIEW mode. Buttons open harmless dummy windows;
Core, wallets and archives are never opened and poweroff is disabled.

The terminal must show `VAULT DESKTOP X11 CHECK PASSED`: one actual DESKTOP
window, one actual DOCK panel, top strut 0, bottom strut 40, full-width panel
flush with the desktop bottom, and eight equal-size cards.

Exercise minimize/restore with the taskbar and F12. With keyboard grabbing
disabled, the host can intercept Alt+Tab; test Alt+Tab conclusively in QEMU. Close the outer Xephyr window to
stop only the preview processes. The user's ordinary desktop is not replaced.

## Build and re-test on the actual Vault ISO

The patch also adds a build hook that repeats the Qt self-test inside the
actual build chroot. It does not change the installer or storage setup.

Only after preview checks and visual acceptance:

```
bash tools/core-vault/build-live-iso.sh
```

In the new Vault VM terminal, run:

```
python3 /path/to/inspect-desktop.py
```

The inspector is also in `/usr/local/bin/core-vault-desktop-check` in the
patched ISO. It only reads X11 window properties and the runtime geometry
report. Success does not prove offline isolation or custody security.

## Verification status of the delivered patch

The assistant environment supports Python syntax/XML/shell checks and an
Openbox/X11 window-contract test. It has no usable PySide6 or tint2 installation
and could not retrieve packages. Therefore the complete Qt rendering and real
tint2 tests are deliberately executable on the build host before any ISO rebuild;
no unrun Qt/tint2 test is represented as a pass.

## Primary references

- https://manpages.debian.org/trixie/tint2/tint2.1.en.html
- https://openbox.org/help/Configuration
- https://doc.qt.io/qt-6/stylesheet-syntax.html
- https://doc.qt.io/qt-6/qt.html
- https://specifications.freedesktop.org/wm-spec/latest/ar01s05.html
