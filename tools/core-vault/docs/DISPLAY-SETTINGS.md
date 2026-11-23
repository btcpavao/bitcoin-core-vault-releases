# Shared display settings

Node and Vault use the same native PySide6 Display Settings dialog and the same
unprivileged RandR backend. They keep the existing X11/Openbox desktop; no full
desktop environment, network screen-sharing service or root GUI is added.

## User workflow

Open **Settings → Display Settings**. Choose a display mode:

- **Built-in display only** enables the laptop panel.
- **Mirror displays** uses one resolution, refresh rate and orientation supported
  by all included connected displays. This also covers a local HDMI/DisplayPort
  capture device that advertises compatible modes.
- **Extend desktop** places the other connected displays to the right, left,
  above or below the selected primary display.
- **External display only** enables the selected external display.

Resolution, refresh rate, primary display and arrangement come from live RandR
queries. A connected but disabled monitor remains selectable. No custom modeline
or shell command can be imported through the UI or profile format. Rotation is
under **Advanced**. The interface-size selector is separate from resolution.

**Apply** starts an independently supervised change. **Keep changes** confirms
it; **Revert**, closing the confirmation, closing its owning dialog, losing the
GUI process, or reaching the 15-second deadline restores the previous layout.
The previous preference file is unchanged until confirmation. Applying a layout
does not close applications, restart Bitcoin Core, or end the Vault session.

Display settings include a bounded JSON export/import. Imported settings are
staged in the form for review and still require Apply and Keep. The combined
device-settings workflow can embed the same validated display profile alongside
separately validated keyboard/mouse preferences; it never copies a home directory.

## Persistence

Confirmed profiles are stored at `~/.config/core-desktop/display.json`, mode 0600.
Node's installed home persists them. Vault uses the fixed path
`/home/vault/.config/core-desktop/display.json`, rejects symlink ancestors, and
writes only when the actual destination filesystem is tmpfs, including any
nested mount. Vault exports go only to
the destination explicitly chosen by the user.

A layout is automatically restored only when every connected output has the same
connector and EDID SHA-256 identity as the saved profile. Every selected mode and
refresh rate is checked again. If any monitor lacks EDID, layout replay is skipped
and the current hardware-selected mode is retained. The user can still review and
apply supported modes manually. Unknown-monitor profiles are not treated as proof
of hardware identity.

Interface scale is a user preference independent of the monitor identity. The
shared scaling helper reads the validated profile after the existing `/etc`
default, while explicit command-line/environment overrides retain precedence.
The existing fit cap keeps at least 800×600 logical pixels where the hardware
allows it. Node's portable configuration backup transfers scale separately and
does not transplant monitor positions to another machine.

## Session integration

Before the existing DPI helper:

    core-display-settings --product node --restore
    core-display-scale --product node -- <session command>

Use `vault` for the Vault session. Start one session-owned background process
after X is ready:

    core-display-settings --product node --watch

The session kills that watcher during its ordinary cleanup. The watcher recovers
an available output after disconnection, replays a matching confirmed profile on
reconnection, and reapplies the existing DPI fit calculation. Home/taskbar windows
must follow `primaryScreenChanged` and output removal. Before launching a new
application, use `core_display.launch_environment()` so newly opened GTK programs
inherit the current integer widget scale as well as the shared Xft DPI. Existing
GTK applications may need to be reopened; no automatic application restart is
performed.

Qt embedding API:

    from core_display_settings import DisplaySettingsDialog
    dialog = DisplaySettingsDialog(product='node', parent=parent)

An optional `imported_profile` argument stages a validated profile without applying
it. The standalone command is `core-display-settings --product node`. The read-only
diagnostic command is `core-display-settings --product node --diagnose`.

## Transaction and failure recovery

The independent worker receives only declarative JSON over a private pipe. It
holds a nonblocking session lock, snapshots the current modes, primary output,
positions, transforms, panning and Xft DPI, then applies a bounded argument array
to `/usr/bin/xrandr`. There is no shell expansion, privilege escalation or arbitrary
executable/path field in profiles. Hardware identity and applied state are checked
before accepting Keep.

Before changing the display, the worker records a bounded recovery journal under
`$XDG_RUNTIME_DIR/core-display/pending.json` (private session directory, mode 0600).
The journal is not a permanent saved profile. Pipe EOF or SIGTERM triggers direct
rollback. If the worker is killed without cleanup, the next watcher pass or GUI
recovery acquires its now-free lock and restores from the strictly validated RAM
journal. The journal also preserves the previous confirmed profile if a crash
interrupts committing new preferences. Lock ownership prevents a second Apply or
the watcher from racing a pending transaction.

If an old monitor has disappeared, rollback restores compatible outputs or
enables an available panel. Its UI scale is capped for the remaining hardware.
An absent or failing X server can prevent immediate hardware recovery; the
watcher retries while the session is alive. These checks do not claim that an
unplugged display, a failed GPU, or power loss can be repaired in software.

## Profile format

The profile is at most 32 KiB and has these exact top-level keys:

- `kind`: `bitcoin-core-display-settings`
- `version`: `1`
- `product`: `node` or `vault`
- `hardware`: connector names and EDID SHA-256 values (or null when unavailable)
- `layout`: enabled outputs, shared scale, preset and arrangement

Each enabled output declares its connector name, reported mode name, supported
refresh rate, nonnegative x/y position, one allowed rotation, and primary flag.
Exactly one output is primary and at least one stays enabled. Unknown keys,
duplicate JSON fields, nonfinite numbers, invalid names, oversized files,
symlink files and nonregular import files are rejected.

Pure API helpers for other settings workflows are `validate_scale(value)`,
`validate_profile(value)`, `load_saved(product)`, `profile_path(product)` and
`save_profile(product, value)`. Validation does not require a live X server.
Live application always uses a separately checked transaction.

## Verification and limits

`tests/test_shared_display.py` uses disposable simulated devices and real child
processes for timeout, EOF, GUI death, worker death, interrupted commit and
concurrent-change scenarios. `tests/test_shared_display_ui.py` exercises the native
Qt dialog offscreen with simulated devices. Neither suite calls host xrandr.
Actual RandR mode changes must additionally be exercised in a disposable X11 VM;
physical monitors/capture devices need hardware testing before compatibility is
claimed. Shared X11 scale remains one value for the desktop, not independent
per-monitor scaling. Network screen sharing is outside this feature.

`tests/shared_display_x11_smoke.py` creates and terminates its own authenticated
Xvfb server, with private HOME/runtime paths, and never connects to the caller's
DISPLAY. It exercises the real xrandr/xrdb backend, primary selection, DPI,
confirmation, rollback and worker recovery. Xvfb reports a fixed virtual mode
with unspecified refresh; this is exposed as Automatic, and no refresh rate is
forced. Unsupported orientations and unnecessary panning resets are not offered
or sent to that output. The dated acceptance record is
`docs/qa/display-settings-20261123.json`.
