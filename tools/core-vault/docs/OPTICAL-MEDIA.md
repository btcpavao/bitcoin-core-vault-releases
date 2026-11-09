# Optical media investigation

The report is that an external USB DVD writer works in an installed operating
system but is absent from Brasero in Vault's stateless live session. Its model,
USB transport, media type and live-session logs are not available. This release
does not claim that this specific hardware failure has been reproduced or fixed.

## Published v0.3.0 audit

The actual ISO, not just the source package lists, contains:

- sr_mod, sg, cdrom, usb-storage, uas and USB host controller kernel modules.
- GVfs's UDisks2 volume monitor, its D-Bus activation service, UDisks2 and udev.
- Standard optical-device uaccess rules for block and SCSI generic devices.
- live-config's default live-user groups, including cdrom. The user is created
  at boot; an empty cdrom group in the unbooted squashfs is expected.
- Brasero 3.12.3-4, growisofs 7.1-14+b2, wodim/genisoimage,
  libburn4t64 and libisofs6t64, with growisofs, dvdrwformat, libburn and libisofs
  Brasero plugins. dvd+rw-format is present. Absence of the separate
  dvd+rw-tools package does not mean these burn backends are absent.
- dbus-x11 and libpam-systemd. The Xsession D-Bus setup and activatable GVfs
  monitor support direct Openbox sessions; a full GNOME desktop is not required.

Brasero is launched as the normal desktop user without a private device
namespace. There is no source override disabling GIO/GVfs or optical access.
Its upstream monitor enumerates existing GIO drives at startup and subscribes
to later drive/volume events. Each candidate must also pass an optical SCSI
inquiry. A failure to open/query a drive can therefore hide it in Brasero.
Neither a mounted filesystem nor a sidebar bookmark is required for burning.

No permission loosening, root Brasero launcher, forced USB driver binding or
speculative kernel quirk was added. usbutils is explicitly included for future
hardware identification.

## Read-only report on the affected session

Run this in Vault's Terminal as the logged-in desktop user, with the affected
writer attached:

```sh
core-vault-optical-diagnostics > "$HOME/Private Workspace/optical-diagnostics.json"
```

The report contains optical device identities, current-user access, selected
udev properties, kernel/module state, package versions and GIO/UDisks discovery.
It reads no wallet/file contents and does not open, mount, eject or write a drive.
The report stays in RAM until explicitly copied elsewhere.

Interpret the layers separately:

1. No optical sysfs device: inspect USB enumeration, kernel transport and power.
2. Sysfs device but no UDisks entry: inspect udev and system storage service.
3. UDisks entry but no GIO entry: inspect this desktop session's D-Bus/GVfs.
4. GIO entry but access denied: inspect the active session, groups and ACLs.
5. All above pass: Brasero's SCSI capability/media probe and the real device need
   testing. Access checks do not prove a subsequent open/ioctl will succeed.

Collect the report once with the empty drive and again after inserting media.
A normal user's report is necessary; running it as root conceals access issues.
Actual burn and read-back testing still requires the reported hardware and a
disposable blank disc.

## VM coverage and limits

QEMU can expose an optical reader over USB bulk-only transport:

```text
-device qemu-xhci,id=xhci
-device usb-bot,id=optical,bus=xhci.0
-drive if=none,id=optical-cd,media=cdrom,format=raw,file=SYNTHETIC.iso,readonly=on
-device scsi-cd,bus=optical.0,scsi-id=0,lun=0,drive=optical-cd
```

Use only a generated public fixture ISO. Omit file= for the empty-drive case;
usb-uas can separately exercise the UAS transport. Keep the canonical Vault
boot/RAM/offline settings. Inspect coldplug, media insertion and USB hotplug,
then assert that the normal user's report sees USB optical sysfs, UDisks and
GIO entries with expected device access.

QEMU's scsi-cd emulates a reader, not a writable blank DVD. Its absence from a
writer-only Brasero destination list is expected and is not a regression.
Such tests establish USB optical discovery, not writer compatibility or a
successful physical burn.

Primary implementation references:

- https://gitlab.gnome.org/GNOME/brasero/-/blob/master/libbrasero-media/brasero-medium-monitor.c
- https://manpages.debian.org/trixie/live-config-doc/live-config.7.en.html
- https://www.qemu.org/docs/master/system/devices/usb.html
