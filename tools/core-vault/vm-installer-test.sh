#!/bin/bash
# Ordinary file-backed test disks only; no physical disk/USB passthrough.
set -euo pipefail
MODE=${1:-bios};PHASE=${2:-install}
USB_TEST=${3:-}
case "$MODE/$PHASE" in bios/live|bios/install|bios/installed|uefi/live|uefi/install|uefi/installed) ;; *) echo 'Usage: vm-installer-test.sh bios|uefi live|install|installed [--usb-test]';exit 2;; esac
[[ $# -le 3 && ( -z "$USB_TEST" || "$USB_TEST" == --usb-test ) ]] || { echo 'Please use --usb-test for the optional virtual USB disk.';exit 2; }
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
ROOT=$(cd -- "$HERE/../.." && pwd)
VM="$ROOT/build-vm/vault-installer-v1/$MODE"
mkdir -p "$VM"
DISK="$VM/target.qcow2"
[[ ! -L "$DISK" && ! -L "$VM" ]] || { echo 'Symlinked VM path refused';exit 1; }
if [[ ! -e "$DISK" ]]; then
    [[ $PHASE != installed ]] || { echo 'No installed test disk exists';exit 1; }
    qemu-img create -f qcow2 "$DISK" 24G
fi
[[ -f "$DISK" ]] || { echo 'Test disk must be a regular file';exit 1; }
python3 - "$DISK" <<'PY'
import json,subprocess,sys
info=json.loads(subprocess.check_output(['qemu-img','info','--output=json',sys.argv[1]]))
if info.get('format')!='qcow2' or any(k in info for k in ('backing-filename','full-backing-filename','data-file')):
    raise SystemExit('Only a standalone qcow2 without a backing or external data file is allowed.')
if 'data-file' in info.get('format-specific',{}).get('data',{}):
    raise SystemExit('External data file refused.')
PY
ARGS=(-name "Bitcoin Core Vault — $MODE $PHASE" -machine q35,accel=kvm:tcg
      -m 4096 -smp 2 -nic none -vga std -no-reboot
      -device qemu-xhci,id=usb
      -drive "file=$DISK,if=none,id=target,format=qcow2"
      -device "virtio-blk-pci,drive=target,serial=CV_TEST_${MODE^^}")
if [[ $USB_TEST == --usb-test ]]; then
    python3 "$HERE/prepare-vm-usb.py" "$VM"
    ARGS+=(-drive "file=$VM/usb-test.raw,if=none,id=backup,format=raw"
           -device "usb-storage,bus=usb.0,drive=backup,removable=on,id=backup-usb,serial=CV_TEST_USB_${MODE^^}")
    echo 'Virtual USB: VAULT_TEST, 4 GiB FAT32. Its contents persist between test boots.'
fi
if [[ $MODE == uefi ]]; then
    CODE=/usr/share/OVMF/OVMF_CODE_4M.fd
    VARS=/usr/share/OVMF/OVMF_VARS_4M.fd
    [[ -f "$CODE" && -f "$VARS" ]] || { echo 'Please install ovmf on the build computer.';exit 1; }
    [[ ! -L "$VM/vars.fd" ]] || { echo 'Unsafe UEFI variable path';exit 1; }
    [[ -f "$VM/vars.fd" ]] || cp "$VARS" "$VM/vars.fd"
    ARGS+=(-drive "if=pflash,format=raw,unit=0,readonly=on,file=$CODE"
           -drive "if=pflash,format=raw,unit=1,file=$VM/vars.fd")
fi
if [[ $PHASE != installed ]]; then
    ISO="$ROOT/live-image-amd64.hybrid.iso"
    [[ -f "$ISO" && ! -L "$ISO" ]] || { echo 'Built ISO missing';exit 1; }
    ARGS+=(-cdrom "$ISO" -boot order=d)
    if [[ $PHASE == live ]]; then
        echo 'Please choose Start Bitcoin Core Vault (Live RAM).'
    else
        echo 'Please choose Install Bitcoin Core Vault; its target is the disposable 24 GiB disk.'
        echo 'Finish -> Restart exits QEMU intentionally; next use the installed phase (without ISO).'
    fi
else
    ARGS+=(-boot order=c)
    echo 'Booting the installed test disk without ISO. No installation commands are sent.'
fi
exec qemu-system-x86_64 "${ARGS[@]}"
