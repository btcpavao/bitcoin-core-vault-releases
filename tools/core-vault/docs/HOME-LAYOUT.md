# Vault Home layout

**Current scope: Vault v0.9.0**, publication source `58f873fa727054f262b2f99bf742aff251cc5672`; documentation reconciled 2026-11-26. The detailed visual reference is [docs/development/UI.md](../../../docs/development/UI.md). This is Vault's layout, not Node's dynamic wallet/status layout.

Home has ten launchers in this order: Bitcoin Core, Wallet Backup, Decrypt Backup, KeePassXC, Editor, Brasero, Print & Labels, Files, Terminal, Vault Guide. There is no Node synchronization row or ten/eleven-card wallet-discovery transition in this Vault baseline.

`core-vault-home.layout_cards()` measures the header, wrapped title/description text, visible feedback, footer and available viewport. The centered content width is bounded to 360–1120 logical pixels. It uses five columns at computed width ≥680 and two below that threshold, with 14-pixel horizontal gaps and a normal card-height maximum of 144. It tries three density levels, reducing logo/icon sizes, text sizes and spacing only as needed. All card titles and descriptions remain reachable; unusually small layouts retain scrolling instead of clipping content.

The footer has a clock above Settings, Restart and Shutdown. Clock text is measured before sizing its zone. These controls remain clear of the taskbar's actual work-area reservation. The Debian credit is centered separately; no Node peer-status row is added.

The 40-logical-pixel taskbar is visible when managed application windows exist, including minimized ones. It uses full titles until they no longer fit, then compact icons with full-title hover text. Closing enough windows restores titles. Removed buttons are hidden before deferred deletion to preserve the accepted stale-icon fix. When only Home remains, the panel hides and releases its work-area reservation.

Home/taskbar follow primary-display changes and output removal. Off-screen child windows are recovered. The underlying display-scale integration preserves the existing logical/physical pixel handling; a layout change must not hard-code one monitor's physical resolution.

Source authorities:

- `config/includes.chroot/usr/local/bin/core-vault-home`: `TOOLS`, `ClockButton`, `layout_footer`, `fit_screen`, `apply_home_density`, `layout_cards`.
- `config/includes.chroot/usr/local/bin/core-vault-taskbar`: `HEIGHT`, `refresh`, `update_visibility`, `sync_reservation`.
- Matching `tools/core-vault/runtime-template/` copies.

Focused checks include `test-home-fit.py`, `test-settings-local.py`, `test-taskbar-controls-x11.py` and the window/display tests mapped in [MODULES.md](../../../docs/development/MODULES.md). Existing source tests' resolution lists are test scenarios, not blanket hardware certification. The v0.9.0 release records focused final-image desktop checks at 1280×800 and 1024×768; earlier or broader checks retain their original artifact scope.
