# Bitcoin Core Vault: native startup Hide, 2026-10-01

The official Bitcoin Core 31.1 executable is preserved unchanged:
`fcd4c1a3193e0cb4eec9d980c835d822ad726627b0c01281b13f5c3c1f593fcb`.
The stock official binary failed to register on AT-SPI and lacks embedded adapter markers. A build-time bridge omission is consistent with those observations, but is an inference; exact upstream configure flags were not independently verified. Runtime packages cannot add bridge code if it was omitted at build time.

The bounded helper verifies process identity, an unambiguous Core main window,
absence of other mapped Core windows/dialogs, and the actual native warning panel
and Hide text through English OCR. It then sends one X11-addressed Return pair to
that window. The native overlay's focused default Hide button executes Core's own
close handler. No pointer movement, activation, global keyboard event, cover window,
LD_PRELOAD, binary patch or replacement Core build is used. The helper exits after
this single action and does not close a panel intentionally reopened later.
Core is launched with `-lang=en` because recognition is intentionally English-only.
OCR images and text remain in memory and are never included in runtime logs.
If proof is missing before delivery, the helper times out without sending input. Failed post-action verification cannot undo the sent action and causes no retry.

Observation, the last check and Core event handling are not atomic. A Core-owned dialog opened after the last check can change internal focus before Return is handled. Already mapped dialogs and menus block delivery; this does not prove the absence of that race. Tested foreign applications remain outside the addressed Core client.

Runtime dependencies are official Debian tesseract-ocr/tesseract-ocr-eng and the
existing Python/PySide6/X11 stack. Xvfb tests use extracted Debian OCR packages only
for the OCR subprocess; the Core process receives no altered library paths.

Restart and Shut Down use unchanged elementary-xfce-hidpi actions/48 SVGs selected
by the development panel at its 44px icon size. Attribution and GPL-3 text travel
with those resources. Qt's SVG icon plugin is included explicitly.

Source checks and ISO payload hashes do not prove GUI behavior. Actual Core tests
must record visible panel -> native Hide -> hidden panel, verify foreign input/focus,
manual reopen and process cleanup. Mandatory Live, BIOS and UEFI verification must
use the newly built ISO, standalone test qcow2 disks, no network and no host shares.

The backup integration package remains 0.4.1: these changes concern Vault launch
and Home presentation, not the encrypted archive implementation.

Official source references:
- https://github.com/bitcoin/bitcoin/blob/v31.1/src/qt/forms/modaloverlay.ui
- https://github.com/bitcoin/bitcoin/blob/v31.1/src/qt/modaloverlay.cpp
- https://github.com/qt/qtbase/blob/v6.8.3/src/widgets/widgets/qpushbutton.cpp
- https://github.com/qt/qtbase/blob/v6.8.3/src/widgets/kernel/qwidgetwindow.cpp

Test evidence is stored separately in the dated vault-test-results directory.
