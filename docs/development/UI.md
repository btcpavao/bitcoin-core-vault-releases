# Vault visual and interaction baseline

This is the implemented **v0.9.0** reference, reviewed from source `58f873fa727054f262b2f99bf742aff251cc5672` on 2026-11-26. It does not redesign the interface. See [CURRENT.md](CURRENT.md), [PRODUCT.md](PRODUCT.md) and [MODULES.md](MODULES.md) before editing a surface.

## Reference sources and images

The main source authorities are `config/includes.chroot/usr/local/bin/core-vault-home`, `core-vault-taskbar`, `usr/lib/core-vault/settings/vault_settings.py`, `vault_time_ui.py`, and `usr/share/core-desktop/core_display_settings.py`. Paths after the first two are also relative to `config/includes.chroot/`. Matching runtime-template copies must travel with a runtime change.

Versioned visual references:

| Reference | Applicable scope |
| --- | --- |
| [v0.9.0 desktop capture, 1024](screenshots/vault-desktop-1024.png) | Copy of the versioned release asset; desktop appearance, not a capture of every settings/dialog state |
| [v0.9.0 desktop capture, 1280](screenshots/vault-desktop-1280.png) | Copy of the versioned release asset at the other release capture size |
| [`docs/screenshots/CAPTURE.json`](../screenshots/CAPTURE.json) and its images | **Historical v0.6.0** captures, identified by their own ISO hash; do not use them as v0.9.0 settings/taskbar acceptance |
| [v0.9.0 release record](../RELEASE-v0.9.0.md) | Exact final-image desktop checks at 1280×800 and 1024×768 and the limits of earlier evidence |

When adding evidence, retain the screenshot's product, ISO hash/source identity, Live/installed mode, resolution, interface scale and scenario. Do not replace an older screenshot's provenance label with a new version number.

## Surface, type and state colors

These are current values in the named components, not a claim that all applications use one centralized theme.

| Element | Current value |
| --- | --- |
| Home background | `#000000` |
| Home card | `#151515`, border `#333333`, 10 px radius |
| Home card hover / press | `#202020` with border `#555555` / `#101010` |
| Home primary / secondary text | `#ffffff` / `#a8a8a8` |
| Home card focus | Orange `#f7931a` border |
| Home-owned message box | `#191919`, text `#f0f0f0`; buttons `#272727`, border `#555555` |
| Power controls / message-box focus | Pale blue `#b7dafa`; retain this existing distinction from orange card focus |
| Settings surface / text | `#0b0b0b` / `#f2f2f2`; secondary `#b5b5b5` |
| Settings inputs | `#151515`, border `#666666`; focused controls have a 2 px orange border |
| Settings combo popup | `#121212`, white text, border `#4a4a4a`, selected row `#343434` |
| Taskbar | `#111111`, top border `#333333`, 40 logical px high |
| Taskbar active / minimized text | Active background `#272727`, white text / minimized text `#999999` |

Home explicitly sets DejaVu Sans at 10 pt as its application font. Its normal CSS sizes are title 28 px, subtitle 14 px, card title 14 px/600 and card description 11 px. Settings uses a 30 px/700 heading, 14 px control/card-title text and 11 px card descriptions. Those values scale through the existing Qt/display system; do not treat physical pixels and logical layout units as interchangeable.

## Home layout

Keep the existing ten-card order: Bitcoin Core, Wallet Backup, Decrypt Backup, KeePassXC, Editor, Brasero, Print & Labels, Files, Terminal, Vault Guide. A separate watch-only tile, Node wallet-discovery tile or Node synchronization row is not part of Vault Home.

The centered grid uses five columns when its computed width is at least 680 logical px, otherwise two. Its content width is bounded to 360–1120, horizontal gaps are 14, and card height is measured from available space with a normal maximum of 144. The fitting algorithm tries three density levels; it measures wrapped titles/descriptions rather than hiding them.

| Density | Header logo / title / subtitle | Card icon / title / description |
| --- | --- | --- |
| Normal | 48 / 28 / 14 | 42 / 14 / 11 |
| Reduced | 40 / 26 / 13 | 34 / 14 / 11 |
| Compact | 28 / 22 / 12 | 28 / 12 / 10 |

All values above are logical layout sizes. Unusually small displays retain scrolling so controls remain reachable. The old assertion about ten/eleven-card transitions and active Node synchronization is not a Vault layout requirement. Test support claims against the actual target resolution and scale; source fitting logic alone is not hardware validation.

The bottom-right stack contains the clock, then **Settings → Restart → Shutdown** from left to right. Each power/settings button is 48×48 with a 44×44 bundled icon. Clock text is measured to prevent clipping; clicking it opens Date & Time. The footer reserves the actual visible taskbar area, and the centered Debian credit stays separate from the right-hand controls. Vault has no peer-status line; the frozen 26 November Node source also removes its former footer peer-status line.

Tool cards expose accessible names/descriptions, wrapped labels and delayed hover explanations (800 ms). Icons keep their aspect ratio; bundled transparent artwork avoids unwanted square backgrounds. Preserve attribution for the elementary-xfce gear/power artwork.

## Windows, taskbar and navigation

- Settings and its children are nonmodal, reusable windows. Reopening a minimized instance restores it instead of creating a duplicate. Normal minimize/close and return-to-Settings behavior remain available outside an active protected operation.
- The Debian Home control returns to Home without relaunching an application. Window activation, minimize and close are window-manager operations; a taskbar close action must not force-kill an application.
- The taskbar appears when managed application windows exist, including minimized windows; with only Home it is hidden and releases its reserved work area.
- Full task titles remain until the sum no longer fits. Then buttons use icons and full-title hover text. Closing enough windows restores labels. A removed button is hidden before deferred deletion, preserving the v0.9.0 fix for stale compact icons over restored titles.
- Home/taskbar follow primary-screen changes and removal; off-screen child windows are recovered. Display changes must not restart Core or end the private session.
- Ordinary resizable applications/file dialogs follow the existing maximize policy. Fixed-size dialogs keep their native sizing. Avoid applying a global window flag to solve one dialog's issue.

## Settings and operation feedback

Settings contains four cards in this order: **Display Settings**, **Keyboard and Mouse**, **Date & Time**, **Backup and Restore**. Its layout uses four columns at dialog width ≥740, otherwise two; cards are 148 high with 14 gaps. The footer has **Export device settings…**, **Import device settings…** and **Exit**. Preserve these current labels unless changing copy is the explicit task.

Display **Apply** enters a 15-second **Keep changes / Revert** transaction with independent recovery. Import only stages a profile for review. The interface distinguishes a confirmed saved profile from an unconfirmed layout and reports a failed persistence attempt.

Date & Time shows a live preview in the selected zone. **Apply time zone** does not reset the clock. Checking **Set date and time manually** enables the editor and changes the action to **Apply date and time**. Its asynchronous helper disables this dialog's editing controls while applying; the current operation cannot be dismissed midway. Results distinguish Live session changes, installed saved zone, hardware-clock success and partial failure. Do not introduce a global desktop blocker for this local operation.

Backup creation and recovery retain their selected destination, progress, cancellation/error handling and no-overwrite semantics. A recovery destination on USB has a clear consequence different from RAM recovery. A canceled watch-only export is never presented as a successful export.

## Focused review after a visual change

Use only the affected scenarios from [MODULES.md](MODULES.md): normal and compact layout, keyboard focus, hover text, minimized/reopened window, taskbar compaction and label restoration, and relevant busy/error/cancel states. For a screen/scale change, include the clock/footer/taskbar boundary. For shared display or settings behavior, compare the corresponding Node implementation while retaining product-specific categories and persistence. Bind new captures to the candidate that produced them.
