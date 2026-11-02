#!/bin/bash
# Safe nested desktop preview. App cards open dummy windows; poweroff is disabled.
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
if [[ $(id -u) == 0 ]]; then echo 'Run the preview as the normal desktop user, not with sudo.' >&2; exit 1; fi
: "${DISPLAY:?Run this from the ThinkCentre graphical desktop terminal}"
SIZE=${1:-1280x800}
[[ $SIZE =~ ^[0-9]{3,4}x[0-9]{3,4}$ ]] || { echo 'Use WIDTHxHEIGHT, e.g. 1280x800'; exit 1; }
for CMD in Xephyr openbox xprop xwininfo; do
    command -v "$CMD" >/dev/null || { echo "Missing build-host preview tool: $CMD" >&2; exit 1; }
done
/usr/bin/python3 -c 'from PySide6.QtWidgets import QApplication'
HOME_APP="$ROOT/config/includes.chroot/usr/local/bin/core-vault-home"
ASSETS="$ROOT/config/includes.chroot/usr/share/core-vault"
/usr/bin/python3 "$HOME_APP" --self-test --assets "$ASSETS"
/usr/bin/python3 "$ROOT/tools/core-vault/test-window-behavior-qt.py" --project "$ROOT"
TMP=$(mktemp -d /tmp/core-vault-preview.XXXXXXXX)
chmod 0700 "$TMP"
mkdir -p "$TMP/home" "$TMP/config" "$TMP/runtime"
# VAULT_WINDOW_PREVIEW_V12
mkdir -p "$TMP/home/.themes/CoreVault/openbox-3"
cp "$ROOT/config/includes.chroot/usr/share/themes/CoreVault/openbox-3/themerc" \
   "$TMP/home/.themes/CoreVault/openbox-3/themerc"
chmod 0700 "$TMP/runtime"
# Wildcard Xauthority entry, only for this private nested X server.
/usr/bin/python3 - "$TMP/Xauthority" <<'PY'
from pathlib import Path
import os, struct, sys
fields = [b'', b'', b'MIT-MAGIC-COOKIE-1', os.urandom(16)]
Path(sys.argv[1]).write_bytes(struct.pack('>H', 65535) + b''.join(
    struct.pack('>H', len(f)) + f for f in fields))
os.chmod(sys.argv[1], 0o600)
PY
PIDS=()
cleanup() {
    for ((i=${#PIDS[@]}-1; i>=0; i--)); do kill "${PIDS[i]}" 2>/dev/null || true; done
    # Only temporary preview files are removed, never project/user data.
    rm -rf -- "$TMP"
}
trap cleanup EXIT
trap 'exit 0' INT TERM
Xephyr -displayfd 3 -screen "$SIZE" -nolisten tcp -no-host-grab \
    -auth "$TMP/Xauthority" 3>"$TMP/display" >"$TMP/xephyr.log" 2>&1 &
SERVER=$!; PIDS+=("$SERVER")
for ((i=0;i<100;i++)); do
    [[ -s "$TMP/display" ]] && break
    kill -0 "$SERVER" 2>/dev/null || { cat "$TMP/xephyr.log"; exit 1; }
    sleep 0.1
done
D=$(cat "$TMP/display")
[[ $D =~ ^[0-9]+$ ]] || { cat "$TMP/xephyr.log"; exit 1; }
export DISPLAY=":$D" XAUTHORITY="$TMP/Xauthority"
export HOME="$TMP/home" XDG_CONFIG_HOME="$TMP/config" XDG_RUNTIME_DIR="$TMP/runtime"
unset SESSION_MANAGER DBUS_SESSION_BUS_ADDRESS
openbox --sm-disable --config-file "$ASSETS/openbox.xml" >"$TMP/openbox.log" 2>&1 &
PIDS+=("$!")
READY=0
for ((i=0;i<100;i++)); do
    if xprop -root _NET_SUPPORTING_WM_CHECK 2>/dev/null | grep -Eq '0x[1-9a-fA-F][0-9a-fA-F]*'; then READY=1; break; fi
    sleep 0.1
done
[[ $READY == 1 ]] || { cat "$TMP/openbox.log"; exit 1; }
/usr/bin/python3 "$ROOT/config/includes.chroot/usr/local/bin/core-vault-taskbar" \
    --preview --assets "$ASSETS" >"$TMP/taskbar.log" 2>&1 &
PIDS+=("$!")
/usr/bin/python3 "$HOME_APP" --preview --assets "$ASSETS" >"$TMP/home.log" 2>&1 &
PIDS+=("$!")
sleep 3
if ! /usr/bin/python3 "$ROOT/tools/core-vault/inspect-desktop.py"; then
    echo 'Preview geometry check failed. Logs follow:'
    cat "$TMP/taskbar.log" "$TMP/home.log"
    exit 1
fi
echo
CORE_VAULT_NESTED_PREVIEW=1 /usr/bin/python3 \
  "$ROOT/tools/core-vault/test-window-behavior-x11.py" --project "$ROOT" || {
    echo 'Background-click test failed. Desktop logs:'
    cat "$TMP/openbox.log" "$TMP/home.log"
    exit 1
}
echo 'PREVIEW ONLY: cards open harmless test windows. Poweroff is disabled.'
echo 'Try minimizing/restoring several windows, Alt+Tab and F12.'
echo 'Close the Xephyr outer window to return to your unchanged host desktop.'
wait "$SERVER" || true
