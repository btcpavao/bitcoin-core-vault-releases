# Adaptive display size

Node and Vault share the same core-display-scale session helper. Video modes are
left unchanged: the X server retains the monitor's selected native mode.

At login, choose the primary active output, otherwise an internal eDP/LVDS/DSI
panel, otherwise the first active output. Validate its physical dimensions,
calculate density and round scaling to 25% steps (100–300%). Typical 15.6-inch
1366x768, 1600x900, 1920x1080 and 3840x2160 panels select 100%, 125%, 150% and
300%. An internal panel with missing physical dimensions uses its resolution
relative to 1366x768. An unknown external monitor defaults to 100%.
Cap scaling so each active output retains at least 800x600 logical pixels.

Xft.dpi is shared with Qt, GTK text and Openbox. Qt uses fractional scaling;
GTK3 uses integer widget scaling and density-adjusted text. GTK3's fractional
icon geometry can differ from Qt; this is an X11/GTK3 limitation.

The X11 session uses one shared scale, following the primary output. Mixed-DPI
monitors cannot each get independent scaling here. Initial detection runs before
the desktop starts. The shared Display Settings window changes supported video
modes separately from this DPI helper, with a Keep/Revert confirmation. Its
session watcher recovers usable outputs and reapplies the fit cap after monitor
changes. No framebuffer stretching is used for interface scaling.

The default preference remains /etc/core-display-scale.conf (auto or a number
such as 1.25 or 1.5). A confirmed ~/.config/core-desktop/display.json profile takes
precedence for that desktop, and Settings exposes Automatic and manual sizes.
The setting is safely capped for the active outputs. Explicit --scale and
CORE_UI_SCALE overrides retain highest precedence. The optional --product flag
selects Node or Vault preference validation.

Newly launched applications inherit refreshed Qt/GTK scale variables through
core_display.launch_environment(). Some already-open applications may need to be
reopened. Changing display settings never automatically closes an application or
ends Vault's private session. Vault preferences stay in its RAM-backed home;
save_profile rejects a persistent home destination. See DISPLAY-SETTINGS.md for
the shared UI, session integration, profile format and rollback behavior.

Diagnostics (read-only):
    core-display-scale --diagnose
    cat "$XDG_RUNTIME_DIR/core-display-scale.json"

Qt: https://doc.qt.io/qt-6/highdpi.html
GTK3: https://docs.gtk.org/gtk3/x11.html
