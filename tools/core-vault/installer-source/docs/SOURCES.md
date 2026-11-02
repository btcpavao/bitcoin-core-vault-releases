# Implementation references

Primary references reviewed for this integration (version-specific where possible):

- Debian Trixie Calamares package and file list:
  https://packages.debian.org/trixie/calamares
  https://packages.debian.org/trixie/amd64/calamares/filelist
- Debian Trixie live-build `lb_config` manual: old saved configuration behavior, `--debian-installer none`, auto/config:
  https://manpages.debian.org/trixie/live-build/lb_config.1.en.html
- Calamares 3.3.14 settings and module order:
  https://github.com/calamares/calamares/blob/v3.3.14/settings.conf
- Branding and stylesheet API:
  https://github.com/calamares/calamares/blob/v3.3.14/src/branding/default/branding.desc
  https://github.com/calamares/calamares/blob/v3.3.14/src/calamares/CalamaresWindow.cpp
- Keyboard choices and target keyboard persistence:
  https://github.com/calamares/calamares/blob/v3.3.14/src/modules/keyboard/keyboard.conf
  https://github.com/calamares/calamares/blob/v3.3.14/src/modules/keyboard/KeyboardPage.cpp
- Disk UI, bootloader target and first-job safety insertion:
  https://github.com/calamares/calamares/blob/v3.3.14/src/modules/partition/gui/ChoicePage.cpp
  https://github.com/calamares/calamares/blob/v3.3.14/src/modules/partition/core/PartitionCoreModule.cpp
- Unpack/mount/fstab/bootloader/finished configurations:
  https://github.com/calamares/calamares/tree/v3.3.14/src/modules
- Calamares Job API:
  https://github.com/calamares/calamares/blob/v3.3.14/src/libcalamares/Job.h

The Calamares changes are distributed as source under GPL-3.0-or-later; original source notices are retained. The builder keeps the exact Debian source artifacts and binary checksums. Publish corresponding source if distributing the modified package/image. Brand assets were provided by the project author and retain their respective upstream terms; no endorsement is implied.
