#!/bin/bash
# Bitcoin Core Offline — Live-only VM test.
# No host block devices and no network are attached.
set -euo pipefail

MODE=${1:-bios}

case "$MODE" in
    bios|uefi) ;;
    *)
        echo 'Usage: vm-test.sh bios|uefi'
        exit 1
        ;;
esac

HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
ROOT=$(cd -- "$HERE/../.." && pwd)

ISO="$ROOT/live-image-amd64.hybrid.iso"
VM="$ROOT/build-vm/live-$MODE"

mkdir -p "$VM"

[[ -f "$ISO" && ! -L "$ISO" ]] || {
    echo 'Built ISO missing'
    exit 1
}

ARGS=(
    -m 4096
    -smp 2
    -nic none
    -vga std
    -cdrom "$ISO"
    -boot order=d
)

if [[ -r /dev/kvm && -w /dev/kvm ]]; then
    ARGS+=(
        -enable-kvm
        -cpu host
    )
fi

if [[ "$MODE" == "uefi" ]]; then

    CODE=/usr/share/OVMF/OVMF_CODE_4M.fd
    TEMPLATE=/usr/share/OVMF/OVMF_VARS_4M.fd
    VARS="$VM/vars.fd"

    [[ -r "$CODE" && -r "$TEMPLATE" ]] || {
        echo 'Install the Debian ovmf package first'
        exit 1
    }

    cp "$TEMPLATE" "$VARS"

    ARGS+=(
        -drive "if=pflash,format=raw,unit=0,readonly=on,file=$CODE"
        -drive "if=pflash,format=raw,unit=1,file=$VARS"
    )
fi

echo
echo "Bitcoin Core Offline — $MODE Live test"
echo
echo "Expected:"
echo "  1. Only one boot option: Start Bitcoin Core Offline (Live RAM)"
echo "  2. Branded Bitcoin Core / Powered by Debian boot"
echo "  3. Bitcoin Core opens automatically"
echo "  4. No installer appears anywhere"
echo "  5. File -> Exit opens the normal shutdown flow"
echo "  6. Shutdown powers off the VM"
echo
echo "No virtual hard disk is attached."
echo "No virtual network interface is attached."
echo

exec qemu-system-x86_64 "${ARGS[@]}"
