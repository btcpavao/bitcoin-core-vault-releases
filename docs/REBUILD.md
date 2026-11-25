# Inspect and build Vault v0.9.0

The release file is `bitcoin-core-vault-v0.9.0-amd64.iso`, **1,133,379,584 bytes**, with SHA-256:

```text
615067c09f573a4476c7039adc90e58f75a46bdf20a028fd3c58f3e300c832fe
```

This is the exact locally assembled image approved for publication after testing. The tagged source, matching native source companion, pinned input manifests and retained build evidence support inspection and further builds. **A fresh independent build producing this complete v0.9.0 ISO byte for byte has not been demonstrated.** The v0.8.0 identical-build results apply to v0.8.0 only.

## 1. Authenticate the release files

Download the ISO, `SHA256SUMS`, `SHA256SUMS.asc`, `btcpavao-pgp.asc` and `SOURCE-COMMIT.txt` from the [v0.9.0 release](https://github.com/btcpavao/bitcoin-core-vault-releases/releases/tag/v0.9.0) into one directory. The project source snapshot is `bitcoin-core-vault-v0.9.0-source.tar.gz`; the patched installer source is `bitcoin-core-vault-v0.9.0-calamares-source.tar.xz`. Both companions are covered by the same checksum list.

Inspect the signing key with `gpg --show-keys --with-fingerprint btcpavao-pgp.asc` and confirm all 40 characters through a separate channel you trust:

```text
787A 2AAF B0D1 19CA 0522 B2A5 B9C9 9AF8 5788 96D0
```

In Bash with GnuPG 2.4.7 or newer, run the following from the download directory:

```bash
(
  set -euo pipefail
  vault_keyring=$(mktemp -d)
  trap 'rm -rf -- "$vault_keyring"' EXIT
  gpg --no-options --homedir "$vault_keyring" --batch --import btcpavao-pgp.asc
  gpg --no-options --homedir "$vault_keyring" --batch --no-auto-key-retrieve \
    --assert-signer 787A2AAFB0D119CA0522B2A5B9C99AF8578896D0 \
    --verify SHA256SUMS.asc SHA256SUMS
  for file in bitcoin-core-vault-v0.9.0-amd64.iso SOURCE-COMMIT.txt; do
    awk -v name="$file" '$2 == name || $2 == "*" name {print; n++} END {if (n != 1) exit 1}' SHA256SUMS |
      sha256sum --strict --check -
  done
)
```

The signature must match the confirmed key and both files must report `OK`. To verify an optional companion or provenance file, apply the same filename-specific check to its exact name in the signed list. Checksums identify the bytes; source review, reproducibility and hardware testing answer separate questions.

## 2. Get the exact project source

```bash
git clone https://github.com/btcpavao/bitcoin-core-vault-releases.git vault-source
cd vault-source
git switch --detach v0.9.0
git rev-parse HEAD
```

Compare the printed revision with the authenticated `SOURCE-COMMIT.txt`. The source tarball contains the tagged files; a Git checkout also preserves the published history for reviewing changes.

```bash
git diff --stat v0.8.0 v0.9.0
git diff v0.8.0 v0.9.0 -- config tools docs .github
```

The runtime files in `config/includes.chroot/` are copied into Vault. The paired files under `tools/core-vault/runtime-template/` are the maintained templates. Inspect the installer model/guards, device-settings persistence, time helpers, Home and taskbar together with their package manifests.

### Known metadata difference

The publication source corrects the Home entry in `usr/share/core-vault/shred-policy.json` after the desktop clock addition. The accepted ISO keeps the original review metadata. This JSON is used by source/build verification tools; installed Home and shred applications do not read it. The Home executable and the other seven reviewed programs are unchanged.

The release records both metadata hashes in `BUILD-PROVENANCE.json` and `source-runtime-verification.json`. The existing strict payload checker requires metadata equality and would reject this known difference. It has not been relaxed or bypassed, and no complete current source-to-ISO payload-gate pass is claimed. The separate comparison of 70 recorded inputs, including 60 installed custom files, remains exact for those listed files.

## 3. Understand the release inputs

| Input | Authoritative record |
| --- | --- |
| Approved ISO, original local candidate identity and release validation scope | Release `BUILD-PROVENANCE.json`, `build-inputs.txt` and [release notes](RELEASE-v0.9.0.md) |
| Recorded source inputs compared with the accepted ISO | Release `source-runtime-verification.json` |
| Runtime overlays and original local assembly | `tools/local-build/assemble-t2-candidate.py` and `pack-t2-desktop-tuning-v2.sh` |
| Calamares `3.3.14-1+corevault10localrolesfix1` | `build-assets/core-vault-calamares-v1/package.json`, the committed `.deb`, and the release's matching Calamares source companion |
| T2 kernel and Intel/AMD graphics firmware | `tools/core-vault/manifests/t2-hardware-release.json` and its archived signed metadata under `build-assets/core-vault-t2-v1/` |
| Unmodified Bitcoin Core and KeePassXC releases | Project release/provenance records and `prepare-keepassxc.py` / `check-core-release.py` |
| Complete installed package inventory | Release `image-packages.tsv` |

The local packaging script records the actual maintainer assembly, including historical absolute paths and intermediate ISO inputs. It cannot be run unchanged on another computer. It is not a portable exact-rebuild recipe.

The T2 helper fetches only the three named packages and checks their exact sizes and hashes. It first verifies the archived metadata listed in the manifest. Those records preserve the repository-signature validation performed when the pins were recorded; no T2 repository is enabled in the offline Vault system. The T2 binary is pinned, but the upstream build used a mutable patch-branch `HEAD`; a matching source-to-binary rebuild and an exact historical patch commit are not claimed.

## 4. Make a new functional source build

Use a disposable **Debian 13 amd64** build VM with internet access and at least 40 GiB of working space. The image builder needs root privileges inside that disposable environment. A build from current source is a new candidate and requires its own content, boot, installation and wallet-workflow checks before use.

The builder prerequisites used by the project are listed in `tools/rebuild/inside.sh`. For a direct live-build environment, install them along with Git and curl:

```bash
sudo apt-get update
sudo apt-get install --no-install-recommends \
  git curl sudo live-build debootstrap debian-archive-keyring \
  apt-utils ca-certificates wget rsync xorriso squashfs-tools isolinux \
  syslinux-common syslinux-utils grub-pc-bin grub-efi-amd64-bin mtools \
  dosfstools cpio file xz-utils python3 python3-pil python3-yaml \
  python3-pyside6.qtcore python3-pyside6.qtgui python3-pyside6.qtwidgets \
  fonts-dejavu-core xvfb xauth gpg gpgv libusb-1.0-0 libgl1 \
  libxcb-cursor0 libxkbcommon-x11-0 libfuse2t64
```

From the clean `v0.9.0` checkout:

```bash
export QT_QPA_PLATFORM=offscreen
export PYTHONDONTWRITEBYTECODE=1
bash tools/core-vault/build-live-iso.sh
```

The entry point prepares the pinned KeePassXC and T2 inputs, checks the reviewed project packages and runtime, invokes `live-build`, and then runs its image-content gates. Its output is `live-image-amd64.hybrid.iso`. Required locally modified package inputs, including the reviewed Calamares v10 package, remain in the release source; the large upstream T2 kernel and two firmware packages are fetched using their manifests. Previously downloaded T2 packages can be staged with `python3 tools/core-vault/prepare-t2-hardware.py --input-dir /path/to/verified-downloads`.

This complete fresh build was **not executed as part of v0.9.0 publication**. This section documents the functional source-build entry point; it does not certify a successful clean rebuild or equality with the released file. Preserve failures and logs instead of disabling a failing gate. Changes in Debian inputs, packaging metadata, filesystem layout and timestamps can change the output bytes.

`tools/rebuild/build-release.sh` and the earlier native wrapper are historical recipes. Their v0.8.0/corevault6 assumptions do not produce the published v0.9.0 image. Original binary comparison gates remain intact; matching current native package bytes have not been demonstrated with this recipe. Use the [v0.8.0 tag](https://github.com/btcpavao/bitcoin-core-vault-releases/blob/v0.8.0/docs/REBUILD.md) when following that historical recipe. Preserved documentation is also under [history/v0.8.0](history/v0.8.0/INDEX.md).

## 5. Compare without assuming the result

After authenticating the download, an independently built image can be compared with it:

```bash
sha256sum live-image-amd64.hybrid.iso /path/to/bitcoin-core-vault-v0.9.0-amd64.iso
cmp -- live-image-amd64.hybrid.iso /path/to/bitcoin-core-vault-v0.9.0-amd64.iso
```

`cmp` succeeds only if every byte matches. No such successful comparison is asserted for v0.9.0. Retain the source revision, package list, build log, hashes and first failing check when reporting a difference. [Native-package source details](NATIVE-REBUILD.md) distinguish inspecting or compiling a patched application from reproducing the entire ISO.
