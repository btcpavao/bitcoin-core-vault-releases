# Build Bitcoin Core Vault and compare the complete ISO

[Native-source candidate, exact revision, download and expected result](rebuilds/71242344618b.md) · [Earlier assembly candidate](rebuilds/9f466c5df912.md)

A checksum is a fingerprint of a file. One different byte changes its SHA-256 fingerprint. To check the path from source to download, build the precise published source revision on another computer and compare your ISO with the signed release. Reading the changes in the source is a separate step. Someone can publish a perfectly repeatable image containing unsafe code.

## Choose what you want to check

For the fully rebuilt project applications, select **`native-rebuild-candidate-71242344618b`**, commit `71242344618ba499278ea2abe49d7343a7f9a1c4`. This unsigned candidate compiles the modified Calamares installer, modified Thunar file manager and Vault Backup before assembling the complete ISO. The downloaded components include official Debian packages, Bitcoin Core and KeePassXC. Two clean builders produced SHA-256 `2b8f8fd5225b4b2ccee1d8ccc6847c647cb6f5d2481fa2d9ef94820a13b09ddc`.

The earlier assembly candidate uses recorded historical Calamares and Thunar packages. Stable v0.5.0 is a separate signed ISO produced by remastering an earlier local image. Its public source is `723d3a8957e86a06853e3ac059159c71174f3c50`. Its signed ISO digest identifies the historical bytes.


1. On a separate 64-bit Intel or AMD Linux machine or disposable Linux VM, install Git and Docker Engine. Use a machine without wallets, passphrases or signing keys. Docker needs to mount filesystems inside the build container. Allow several gigabytes for downloads and approximately 40 GiB of working space. Run `git --version` and `docker run --rm hello-world`. If your disposable Linux VM requires `sudo docker`, use `--sudo-docker` before the output directory in step 4. Your source and output stay under your own account.
2. Obtain the **full 40-character Git commit** from the release's signed build record, or from the exact candidate commit on GitHub. Keep its value and the release tag. During candidate testing, the commit identifies what you built without authenticating the author. The command below selects the native-source candidate. For a later release, substitute its full commit. The final command prints the commit so you can compare it with your record.

   ```bash
   git clone https://github.com/btcpavao/bitcoin-core-vault-releases.git vault-source
   cd vault-source
   revision=71242344618ba499278ea2abe49d7343a7f9a1c4
   git switch --detach "$revision" && git rev-parse HEAD
   ```

3. Review the changes. For the first rebuild candidate, start with the previously published v0.5.0 revision below. For a later release, use the previous signed revision instead. `--stat` lists the changed files. The second command shows the actual changes, including image hooks, settings, local packages and build tools. In the pager, press **Space** to continue and **q** to return.

   ```bash
   previous=723d3a8957e86a06853e3ac059159c71174f3c50
   git diff --stat "$previous" HEAD
   git diff "$previous" HEAD
   git ls-tree -r --long HEAD config/packages.chroot
   ```

   Git displays some files as binary. The source records and review instructions for Calamares, Thunar and Vault Backup are in the repository and the release. Check the installer and Home launchers, network configuration, scripts under `tools/`, the files added under `config/`, and any changed package against its corresponding source. Bitcoin Core's upstream signing attestations and the exact executable hashes are under `provenance/32.1/`. The builder also recreates Vault Backup from its source and checks the entire resulting Debian package against the committed copy. For the patched Thunar package, inspect its embedded source with the commands below. The v0.5.0 GitHub release carries the matching Calamares source bundle named `bitcoin-core-vault-v0.4.0-calamares-source.tar.xz`. Each build of the native-source candidate recompiles Calamares and Thunar in separate fresh containers, checks both Debian packages byte for byte against their expected copies and puts those freshly compiled files into the ISO. Downloadable corresponding sources and the native build procedure are listed in the [native build guide](NATIVE-REBUILD.md).

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

   For the unsigned native-source candidate, use the [recorded checksum and byte comparison](rebuilds/71242344618b.md). After checking it, continue at step 6. For an edition with a maintainer signature, use step 5.

5. For an actual release, obtain its ISO, `SHA256SUMS`, `SHA256SUMS.asc` and `btcpavao-pgp.asc` from the same GitHub release. Put only those files in a new directory named `release` next to `vault-source`. For v0.5.0 the published fingerprint is `787A 2AAF B0D1 19CA 0522 B2A5 B9C9 9AF8 5788 96D0`. Confirm the complete fingerprint for the release you are checking with Pavao through a separate channel you already trust. In the release directory, use an empty temporary GPG keyring so the verification can only use the key you just checked.

   ```bash
   cd ../release
   keyring=$(mktemp -d)
   gpg --homedir "$keyring" --show-keys --with-fingerprint btcpavao-pgp.asc
   ```

   After comparing the fingerprint, run the following lines **in Bash**. The commands require exactly one ISO in that directory and exactly one signed manifest entry for that filename. Both the downloaded and rebuilt file must pass. A candidate without a signed release can instead be compared directly with another builder's candidate using `cmp`.

   ```bash
   (
     set -euo pipefail
     shopt -s nullglob
     isos=(*.iso)
     [[ ${#isos[@]} == 1 ]] || { echo 'Place exactly one release ISO here.'; exit 1; }
     read -r -p 'Independently confirmed PGP fingerprint: ' trusted
     trusted=${trusted//[[:space:]]/}
     [[ ${trusted^^} =~ ^[0-9A-F]{40}$ ]]
     actual=$(gpg --homedir "$keyring" --batch --with-colons --show-keys btcpavao-pgp.asc |
       awk -F: '$1=="pub" { primary=1; next } primary && $1=="fpr" { print $10; primary=0 }')
     [[ $actual == "${trusted^^}" ]]
     gpg --homedir "$keyring" --batch --dearmor --output "$keyring/confirmed.gpg" btcpavao-pgp.asc
     gpg --homedir "$keyring" --batch --no-default-keyring --keyring "$keyring/confirmed.gpg" \
       --no-auto-key-retrieve --verify SHA256SUMS.asc SHA256SUMS
     expected=$(awk -v name="${isos[0]}" '($2 == name || $2 == "*" name) { print $1 }' SHA256SUMS)
     [[ $expected =~ ^[[:xdigit:]]{64}$ ]]
     printf '%s  %s\n' "$expected" "${isos[0]}" | sha256sum --check
     printf '%s  %s\n' "$expected" ../vault-result/bitcoin-core-vault-amd64.iso | sha256sum --check
     cmp -- "${isos[0]}" ../vault-result/bitcoin-core-vault-amd64.iso
     echo 'The signed release ISO and the rebuilt ISO match byte for byte.'
   )
   ```

6. If hashes differ, keep both hashes, the exact commit, package lists and build logs. `diffoscope --html vault-difference.html first.iso second.iso` compares two files you already have (replace their names). If the build stops earlier, record the first failing command plus the preceding error. Report the discrepancy with those public records. An error, a skipped workflow or a difference is an open investigation.

### Using an LLM along the way

Copy public output into your LLM and ask, “I am following Vault's REBUILD.md. Please explain step 3 and this diff in plain language. Which files affect the installed Vault? Which inputs are prebuilt? Give me one read-only command to inspect the next file.” An LLM can help read the code and explain a failure. Share only public source, logs and checksums. Wallet files, seeds, passphrases and private PGP keys play no role in an ISO build.

### Inputs to inspect

`tools/rebuild/inputs.env` names the builder image by its immutable amd64 digest, an exact Debian snapshot and the timestamp used by live-build. `tools/rebuild/InRelease.sha256` fixes Debian's signed archive indexes. APT verifies packages against the signed indexes. `tools/core-vault/manifests/keepassxc-release.json` fixes the signed upstream KeePassXC AppImage. The repository records the two Core executable hashes and checks the freshly built custom packages against reference copies under `config/packages.chroot/`. A successful run checks the generated installer payload and RAM policy inside the result.
