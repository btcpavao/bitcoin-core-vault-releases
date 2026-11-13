# Build Bitcoin Core Vault and compare the complete ISO

Use the [v0.6.0 release](https://github.com/btcpavao/bitcoin-core-vault-releases/releases/tag/v0.6.0) and the Git revision
`26e590741c968316b99416c51a53b9720d8134cb` for this walkthrough. The
[release build on GitHub](https://github.com/btcpavao/bitcoin-core-vault-releases/actions/runs/43397223031) runs two clean builders, compares their
complete ISO files and installs the resulting image on a blank UEFI virtual disk.

The signature authenticates the maintainer’s checksum list. Rebuilding lets
you compare the bytes produced by the published source with those in your
download. Reviewing what the source does is a separate step.

## Build v0.6.0

1. On a separate 64-bit Intel or AMD Linux machine or disposable Linux VM, install Git and Docker Engine. Use a machine without wallets, passphrases or signing keys. Docker needs to mount filesystems inside the build container. Allow several gigabytes for downloads and approximately 40 GiB of working space. Run `git --version` and `docker run --rm hello-world`. If your disposable Linux VM requires `sudo docker`, use `--sudo-docker` before the output directory in step 4. Your source and output stay under your own account.
2. Clone the repository and check out the release revision. The final command must print the exact 40-character commit shown above. The source tarball attached to the release is useful for inspection. The build script needs a Git checkout to archive the committed tree.

   ```bash
   git clone https://github.com/btcpavao/bitcoin-core-vault-releases.git vault-source
   cd vault-source
   revision=26e590741c968316b99416c51a53b9720d8134cb
   git switch --detach "$revision" && git rev-parse HEAD
   ```

3. Review the changes. The previous signed stable release was v0.5.0. Compare its revision below with the v0.6.0 checkout. `--stat` lists the changed files. The second command shows the actual changes, including image hooks, settings, local packages and build tools. In the pager, press **Space** to continue and **q** to return.

   ```bash
   previous=723d3a8957e86a06853e3ac059159c71174f3c50
   git diff --stat "$previous" HEAD
   git diff "$previous" HEAD
   git ls-tree -r --long HEAD config/packages.chroot
   ```

   Git displays some files as binary. The source records and review instructions for Calamares, Thunar and Vault Backup are in the repository and the release. Check the installer and Home launchers, network configuration, scripts under `tools/`, the files added under `config/`, and any changed package against its corresponding source. Bitcoin Core's upstream signing attestations and the exact executable hashes are under `provenance/32.1/`. The builder also recreates Vault Backup from its source and checks the entire resulting Debian package against the committed copy. For the patched Thunar package, inspect its embedded source with the commands below. The v0.5.0 GitHub release carries the matching Calamares source bundle named `bitcoin-core-vault-v0.4.0-calamares-source.tar.xz`. The standard release build recompiles Calamares and Thunar in separate fresh containers, checks both Debian packages byte for byte against their expected copies and puts those freshly compiled files into the ISO. Downloadable corresponding sources and the native build procedure are listed in the [native build guide](NATIVE-REBUILD.md).

   ```bash
   dpkg-deb -x config/packages.chroot/thunar_*_amd64.deb ../thunar-review
   ls ../thunar-review/usr/share/doc/thunar/core-vault-source
   ls tools/core-vault/backup-src/src tools/core-vault/calamares tools/core-vault/thunar
   ```

4. From the checked-out directory, start the build and leave its terminal open. Choose a new output directory each time. The command reads committed files, downloads the named and verified inputs, runs the image checks and produces a file without writing to a USB drive.

   ```bash
   bash tools/rebuild/build.sh ../vault-result
   cat ../vault-result/build-inputs.txt
   cat ../vault-result/SHA256SUMS
   ```

   Keep `bitcoin-core-vault-amd64.iso`, the build-input record, package lists, archive metadata and build log. A second person can run the same commands with the same commit on their own computer. The GitHub workflow also builds on two separate hosted runners and compares both entire files. A copy made by the same hosting provider is useful for repeatability. A separately operated builder provides additional independent evidence.

5. Download `bitcoin-core-vault-v0.6.0-amd64.iso`, `SHA256SUMS`, `SHA256SUMS.asc` and `btcpavao-pgp.asc` from the [same v0.6.0 release](https://github.com/btcpavao/bitcoin-core-vault-releases/releases/tag/v0.6.0) into a new directory named `release` next to `vault-source`. From the source directory:

   ```bash
   cd ../release
   gpg --show-keys --with-fingerprint btcpavao-pgp.asc
   ```

   The maintainer’s full published fingerprint is `787A 2AAF B0D1 19CA 0522 B2A5 B9C9 9AF8 5788 96D0`. Confirm it through a separate channel you trust. Then run the block below in Bash with GnuPG 2.4.7 or newer (included with Debian 13) from the release directory. It checks the signature in a temporary keyring, reads the authenticated ISO entry, checks both files against it and compares them byte for byte.

   ```bash
   (
     set -euo pipefail
     keyring=$(mktemp -d)
     trap 'rm -rf -- "$keyring"' EXIT
     gpg --homedir "$keyring" --batch --import btcpavao-pgp.asc
     gpg --homedir "$keyring" --batch --assert-signer 787A2AAFB0D119CA0522B2A5B9C99AF8578896D0 --verify SHA256SUMS.asc SHA256SUMS
     published=bitcoin-core-vault-v0.6.0-amd64.iso
     rebuilt=../vault-result/bitcoin-core-vault-amd64.iso
     expected=$(awk -v name="$published" '$2 == name || $2 == "*" name {print $1; n++} END {if (n != 1) exit 1}' SHA256SUMS)
     [[ $expected =~ ^[0-9a-f]{64}$ ]]
     printf '%s  %s\n' "$expected" "$published" "$expected" "$rebuilt" | sha256sum --strict --check -
     cmp -- "$rebuilt" "$published"
     echo 'Your rebuilt ISO matches the signed Vault v0.6.0 download byte for byte.'
   )
   ```

   The published v0.6.0 ISO is 714,080,256 bytes. Its expected SHA-256 is `d1e3656099875e6cde7ed6c78fcf9ee3217d8bed4f8ccd5500b4231ad6bfa8ba`.

6. If hashes differ, keep both hashes, the exact commit, package lists and build logs. `diffoscope --html vault-difference.html first.iso second.iso` compares two files you already have (replace their names). If the build stops earlier, record the first failing command plus the preceding error. Report the discrepancy with those public records. An error, a skipped workflow or a difference is an open investigation.

### Using an LLM along the way

Copy public output into your LLM and ask, “I am following Vault's REBUILD.md. Please explain step 3 and this diff in plain language. Which files affect the installed Vault? Which inputs are prebuilt? Give me one read-only command to inspect the next file.” An LLM can help read the code and explain a failure. Share only public source, logs and checksums. Wallet files, seeds, passphrases and private PGP keys play no role in an ISO build.

### Inputs to inspect

`tools/rebuild/inputs.env` names the builder image by its immutable amd64 digest, an exact Debian snapshot and the timestamp used by live-build. `tools/rebuild/InRelease.sha256` fixes Debian's signed archive indexes. APT verifies packages against the signed indexes. `tools/core-vault/manifests/keepassxc-release.json` fixes the signed upstream KeePassXC AppImage. The repository records the two Core executable hashes and checks the freshly built custom packages against reference copies under `config/packages.chroot/`. A successful run checks the generated installer payload and RAM policy inside the result.


### Earlier releases and build records

[v0.5.0](https://github.com/btcpavao/bitcoin-core-vault-releases/releases/tag/v0.5.0) has its own signed checksum for an image assembled from an earlier local build. The [assembly candidate](rebuilds/9f466c5df912.md) and [native-source candidate](rebuilds/71242344618b.md) each have a separate unsigned ISO, source revision and comparison record.
