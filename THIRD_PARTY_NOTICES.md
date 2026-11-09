# Third-party notices

Bitcoin Core Vault combines original integration with independently licensed
software and artwork. The top-level [LICENSE](LICENSE) grants MIT terms only for
its stated original-code scope. It does not change upstream copyrights,
copyleft obligations, resource licenses or trademarks. Preserve the exact
component notices and source headers when redistributing their files.

## Current local Core 32.1 candidate

The local 29 October 2026 candidate upgrades the unmodified official Core
executables to 32.1 (Qt 6.8.4). Download hashes and eight verified release
signatures are recorded under `provenance/32.1/`. The verified upstream source
archive, including dependency recipes and patches, accompanies the local build
under `upstream/bitcoin-32.1.tar.gz`. No Core or Qt code was patched or rebuilt.
The Core 31.1 source-companion inventory below is historical and does not
assert corresponding-source completeness for the 32.1 candidate. Before public
distribution, refresh the full Qt/library source companions and license inventory.

## Historical released-image notices

These notices and the source companions accompany the unchanged 5 October 2026
image selected for release. They were prepared on 12 October; their presence
inside that existing ISO is not claimed. The image has SHA-256
`de24c7911e8d26f727ea5d00d6ee863f9e7615b1cb7e79e55095f4804490595d`.

## Component identity and license scope

| Component | Version / scope | License and retained notice |
| --- | --- | --- |
| Original Vault integration | Home, taskbar, session and other original helpers, configuration, tests and documentation within the top-level scope | Scoped MIT, copyright 2026 Pavao Pahljina. Existing file/component notices take precedence. |
| Local backup wrapper | `core-vault-backup` 0.7.0 | Existing MIT notice in `tools/core-vault/backup-src/LICENSE`; retained unchanged and installed as `/usr/share/doc/core-vault-backup/copyright`. Archive cryptography is provided separately by Debian 7zip. |
| Bitcoin Core | Unmodified official 31.1 executables | MIT for Core source; copyright 2009–2026 The Bitcoin Core developers and Bitcoin Developers. Preserve `Core-COPYING.txt`, `Core-debian-copyright.txt`, vendored-library and resource/font notices from the companion. |
| Qt used by the Core GUI | Pinned Qt 6.8.3, static build recipe | Qt runtime library components have LGPL-3.0/GPL-3.0 options as applicable. Tools, translations, exceptions and internal third-party code retain their per-file terms. The GUI and its static Qt libraries are not covered wholesale by Core's MIT license. |
| Calamares, locally patched | `3.3.14-1+corevault3` | GPL-3.0-or-later for the application and applicable patches; preserve source-file exceptions, including applicable slideshow/QML LGPL terms. `tools/core-vault/calamares/CoreOfflineGuard.h` already declares GPL-3.0-or-later. |
| Thunar, locally patched | `4.20.2-1+deb13u1+corevault1` | GPL-2.0-or-later for the application and modified action-manager code. `thunarx`/`tdb` library and documentation files retain their per-file LGPL/FDL terms; preserve `COPYING`, `COPYING.LIB` and source headers. |
| Debian system and application packages | Debian 13 Trixie; 771 installed packages in the selected image | Each package's own copyright/license and corresponding-source records apply. This includes the kernel, GNU tools, 7zip, KeePassXC, PySide6/Qt, Openbox, GTK/Xfce, media/printing tools, fonts and icon themes; no single MIT grant applies to the ISO. |

Primary component references:

- [Qt 6.8 licensing](https://doc.qt.io/qt-6.8/licensing.html) and [LGPL terms](https://doc.qt.io/qt-6.8/lgpl.html).
- [Calamares Debian copyright](https://metadata.ftp-master.debian.org/changelogs/main/c/calamares/calamares_3.3.14-1_copyright).
- [Thunar Debian copyright](https://metadata.ftp-master.debian.org/changelogs/main/t/thunar/thunar_4.20.2-1%2Bdeb13u1_copyright).

## Core, Qt and pinned library sources

The companion `core-31.1-static-qt-6.8.3-sources.tar.gz` contains the official
Core 31.1 source, its recipes/patches, the pinned Qt source inputs and the
associated dependency source inputs. Its current SHA-256 is
`23ebaa50c3a5e4317cdcb3186d05ec95c24b0927be892d27066455d0cedfeca9`.
Release asset filenames and digests are confirmed by the release's `SHA256SUMS`.

The archive preserves `Core-COPYING.txt`, `Core-debian-copyright.txt` and 295
copied license/copyright/Qt-attribution files under `notices/`. Repository copies
are under [LICENSES/](LICENSES/), including
[Bitcoin-Core-MIT.txt](LICENSES/Bitcoin-Core-MIT.txt),
[Bitcoin-Core-debian-copyright.txt](LICENSES/Bitcoin-Core-debian-copyright.txt)
and `LICENSES/core-and-libraries/`. Its
`library-source-plan.json`, `library-source-downloads.json`, `source-files.json`
and `SOURCES_SHA256SUMS` record original URLs, recipe pins and payload hashes.
Use these exact notices and source headers for license expressions rather than
inferring terms from an archive filename.

| Pinned source input | Source archive |
| --- | --- |
| Boost 1.90.0 | `boost-1.90.0-cmake.tar.gz` |
| libevent 2.1.12-stable | `libevent-2.1.12-stable.tar.gz` |
| libqrencode 4.1.1 | `qrencode-4.1.1.tar.gz` |
| Expat 2.7.3 | `expat-2.7.3.tar.gz` |
| libxcb 1.17.0 | `libxcb-1.17.0.tar.gz` |
| xcb-proto 1.17.0 | `xcb-proto-1.17.0.tar.gz` |
| libXau 1.0.12 | `libXau-1.0.12.tar.gz` |
| xproto 7.0.31 | `xproto-7.0.31.tar.gz` |
| libxkbcommon 0.8.4 | `libxkbcommon-0.8.4.tar.xz` |
| xcb-util 0.4.1 | `xcb-util-0.4.1.tar.gz` |
| xcb-util-cursor 0.1.6 | `xcb-util-cursor-0.1.6.tar.gz` |
| xcb-util-renderutil 0.3.10 | `xcb-util-renderutil-0.3.10.tar.gz` |
| xcb-util-keysyms 0.4.1 | `xcb-util-keysyms-0.4.1.tar.gz` |
| xcb-util-image 0.4.1 | `xcb-util-image-0.4.1.tar.gz` |
| xcb-util-wm 0.4.2 | `xcb-util-wm-0.4.2.tar.gz` |
| SQLite 3.50.4 | `sqlite-autoconf-3500400.tar.gz` |
| ZeroMQ 4.3.5 | `zeromq-4.3.5.tar.gz` |
| Cap'n Proto 1.3.0 native input | `capnproto-cxx-1.3.0.tar.gz` |
| FreeType 2.11.1 | `freetype-2.11.1.tar.gz` |
| Fontconfig 2.12.6 | `fontconfig-2.12.6.tar.gz` |
| SystemTap 5.3 header/build input | `systemtap-5.3.tar.gz` |

This is a source-input inventory, including headers and build tools; it is not a
claim that all 21 components are linked into the running GUI. Vendored
`libmultiprocess`, `secp256k1`, LevelDB and Core's own third-party code remain in
`bitcoin-31.1.tar.gz` with their notices. Qt inputs include
`qtbase-everywhere-src-6.8.3.tar.xz`, `qttranslations-everywhere-src-6.8.3.tar.xz`,
`qttools-everywhere-src-6.8.3.tar.xz` and the recorded top-level CMake inputs.

The source, patches and build instructions support modifying/rebuilding Core
and relinking with modified library sources under their applicable licenses.
This project adds no restriction on reverse engineering for debugging such
library modifications. Source preparation did not execute a Core/Qt rebuild,
prove bit-for-bit reproducibility or perform a new maintainer-key verification.
The individual licenses and their source/relink requirements continue to apply.

## Locally modified native packages

The companion `bitcoin-core-vault-v0.1.0-modified-sources.tar.xz` preserves
licenses, corresponding source, local patches and build materials for the
historical release versions (including its then-shipped archive manager). The current GPG-only candidate omits that archive manager. It is 15,396,184 bytes with
SHA-256 `90292892663be063c57d8eb8e51ad44a85b3cca549fbe0ef6a606de401a4f99b`.
Upstream-derived patches remain under the applicable upstream license.

Thunar's package carries these recorded paths:

- `/usr/share/doc/thunar/copyright`
- `/usr/share/doc/thunar/core-vault-source/Thunar-core-vault-source.tar.xz`
- `/usr/share/doc/thunar/core-vault-source/core-vault-permanent-delete.patch`
- `/usr/share/doc/thunar/core-vault-source/README.md`

The current Thunar source/package hashes are in
config/includes.chroot/usr/share/core-vault/thunar-shred.json, with matching
runtime-template records. Calamares' current
matching source companion was reconstructed from verified Debian source and
recorded build inputs; its provenance record distinguishes this reconstruction
from an original build log or a binary-reproducibility result. See
[RELEASING.md](RELEASING.md) for the distribution and verification procedure.

The installed Debian packages retain their own `/usr/share/doc/PACKAGE/copyright`
and `/usr/share/common-licenses` records. Matching Debian package/source access
is recorded separately from these locally modified packages. Preserve that
access record and the release's package manifest when redistributing the ISO.

## Artwork

### elementary-xfce power icons

The unchanged `system-shutdown.svg` and `system-reboot.svg` used under
`config/includes.chroot/usr/share/core-vault/icons/` are from elementary-xfce
0.21-1 and retain GPL-3.0-or-later. Copyright 2007–2013 Daniel Foré and 2010–2022
Simon Steinbeiß. Matching files under `tools/core-vault/runtime-template/` have
the same terms. The copied `copyright`, `GPL-3.txt` and `NOTICE.txt` are under
`usr/share/core-vault/licenses/elementary-xfce/` in the active and template trees.
The source companion preserves these notices and source assets; repository
license copies are under [LICENSES/elementary-xfce/](LICENSES/elementary-xfce/).

Primary reference: [elementary-xfce Debian copyright](https://metadata.ftp-master.debian.org/changelogs/main/e/elementary-xfce/elementary-xfce_0.21-1_copyright).

### elementary-xfce Guide icons

The Guide reuses Node's unchanged document-save and document-import artwork as
icons/settings-chain-backup.png and icons/settings-chain-import.png, plus its
librsvg rendering of the existing system-shutdown.svg as system-shutdown.png. These are
from Debian elementary-xfce-icon-theme 0.21-1 and retain GPL-3.0-or-later,
copyright 2007–2013 Daniel Foré and 2010–2022 Simon Steinbeiß. Exact upstream
paths and hashes are in [guide-icons.json](LICENSES/elementary-xfce/guide-icons.json).
Preserve [GUIDE-ICONS-NOTICE.txt](LICENSES/elementary-xfce/GUIDE-ICONS-NOTICE.txt),
the adjacent copyright and GPL-3.txt, and the matching installed/template copies.
Existing Bitcoin/decryption artwork is reused; other chapters use installed
application-theme icons under their original package licenses.

### Adapted Debian Open Use Logo

The identified white taskbar artwork `icons/debian-white.svg` and its rendered
`icons/debian-white.png` derive from the Debian Open Use Logo. Copyright 1999
Software in the Public Interest, Inc.; original creator Raul Silva. Vault's
adaptation changes fills to white and changes framing/translation. It selects
**Creative Commons Attribution-ShareAlike 3.0 Unported (CC BY-SA 3.0)** for these
identified logo adaptations; they are outside the project's MIT grant.

The `branding/debian-open-logo/` section of the Core/Qt companion preserves the
original reference, adapted assets, attribution/change notice and full CC BY-SA
3.0 legal text. Repository copies are
[LICENSES/debian-open-logo/NOTICE.txt](LICENSES/debian-open-logo/NOTICE.txt) and
[LICENSES/debian-open-logo/CC-BY-SA-3.0.txt](LICENSES/debian-open-logo/CC-BY-SA-3.0.txt).
Keep that notice and license with redistributed adaptations.

Primary references: [Debian logos and license choices](https://www.debian.org/logos/)
and [CC BY-SA 3.0 legal text](https://creativecommons.org/licenses/by-sa/3.0/legalcode.txt).
The use of Debian branding does not imply Debian approval of this distribution.

The red Debian branding input also decodes pixel-for-pixel to Wikimedia's
500-pixel render of [Openlogo-debianV2.svg](https://commons.wikimedia.org/wiki/File:Openlogo-debianV2.svg),
which traces its source to Debian's Open Use Logo. The installed red PNG is an
exact resize of that reference. These red adaptations use the same selected
CC BY-SA 3.0 terms, SPI copyright and Raul Silva attribution. Their reference
artwork and comparison record are in [LICENSES/debian-red-logo/](LICENSES/debian-red-logo/).

### Bitcoin logo

The maintainer-supplied `bitcoin-logo.webp` decodes pixel-for-pixel to the
Wikimedia 960×960 render of [File:Bitcoin.svg](https://commons.wikimedia.org/wiki/File:Bitcoin.svg).
Wikimedia credits Grayliptrot's standalone derivation from Bitboy's Bitcoin logo
and marks this simple logo as public domain. Bitboy's current
[bitmap release](https://bitcointalk.org/index.php?topic=1631.msg19455#msg19455) and
[vector release](https://bitcointalk.org/index.php?topic=1756.msg21619#msg21619)
expressly dedicate his graphics to the public domain. These posts were edited
in 2014; this notice does not claim the dedication dates to their original 2010
publication.

`tools/core-offline/branding/bitcoin.png` and its source/installer copies are
small derivatives of this graphic; `bitcoin-ui.png` is an exact resize of the
128-pixel input. The historical download URL and resampler are unrecorded.
This artwork is outside the MIT integration grant. The reference artwork,
pixel comparison, hashes and attribution are preserved in the accompanying
branding source records and [LICENSES/bitcoin-logo/](LICENSES/bitcoin-logo/).
The use of Bitcoin or Debian branding does not imply project endorsement.

## ISO bootloader sources

`bitcoin-core-vault-bootloader-sources.tar` supplies the exact source sets and
notices for GRUB `2.12-9+deb13u2`, Syslinux
`3:6.04~git20190206.bf6db5b4+dfsg1-3.1`, Unifont `1:15.1.01-1` and
live-build `1:20250505+deb13u1`. It contains authenticated package/source
metadata, build inputs, a portable verifier and a record of the ISO-generated
ISOLINUX boot table and hybrid MBR changes. Their individual code/font license
terms remain in force; they are not covered by the integration MIT grant.

The generated EFI executable and PF2 font were reproduced byte-for-byte from
those recorded inputs. FAT images were inventoried rather than reproduced.
This component verification does not establish whole-ISO reproducibility,
Secure Boot support or successful firmware boot.
