# Build Bitcoin Core Vault and compare the complete ISO

A checksum is a fingerprint of a file. One different byte changes its SHA-256 fingerprint. To check the path from source to download, build the precise published source revision on another computer and compare your ISO with the signed release. Reading the changes in the source is a separate step. Someone can publish a perfectly repeatable image containing unsafe code.

## Choose what you want to check

Vault v0.5.0 is an existing signed release built from a locally modified earlier image. Its recorded source revision is `723d3a8957e86a06853e3ac059159c71174f3c50`. The recipe below starts with Debian packages and the committed Vault inputs. Its initial output is a candidate for a **new** release. A match with the v0.5.0 download has not been demonstrated. Use the exact commit of the rebuild-enabled release or candidate you are checking.

1. On a separate 64-bit Intel or AMD Linux machine or disposable Linux VM, install Git and Docker Engine. Use a machine without wallets, passphrases or signing keys. Docker needs to mount filesystems inside the build container. Allow several gigabytes for downloads and approximately 30 GiB of working space. Run `git --version` and `docker run --rm hello-world`. If Docker requires administrator rights, use a disposable VM where your account is allowed to run Docker.
2. Obtain the **full 40-character Git commit** from the release's signed build record, or from the exact candidate commit on GitHub. Keep its value and the release tag. During candidate testing, the commit identifies what you built without authenticating the author. Paste it at the prompt below. The final command prints the commit so you can compare it with your record.

   ```bash
   git clone https://github.com/btcpavao/bitcoin-core-vault-releases.git vault-source
   cd vault-source
   read -r -p 'Exact 40-character source commit: ' revision
   git switch --detach "$revision" && git rev-parse HEAD
   ```

3. Review the changes. For the first rebuild candidate, start with the previously published v0.5.0 revision below. For a later release, use the previous signed revision instead. `--stat` lists the changed files. The second command shows the actual changes, including image hooks, settings, local packages and build tools. In the pager, press **Space** to continue and **q** to return.

   ```bash
   previous=723d3a8957e86a06853e3ac059159c71174f3c50
   git diff --stat "$previous" HEAD
   git diff "$previous" HEAD
   git ls-tree -r --long HEAD config/packages.chroot
   ```

   Git displays some files as binary. The source records and review instructions for Calamares, Thunar and Vault Backup are in the repository and the release. Check the installer and Home launchers, network configuration, scripts under `tools/`, the files added under `config/`, and any changed package against its corresponding source. Bitcoin Core's upstream signing attestations and the exact executable hashes are under `provenance/32.1/`. The builder also recreates Vault Backup from its source and checks the entire resulting Debian package against the committed copy. For the patched Thunar package, inspect its embedded source with the commands below. The v0.5.0 GitHub release carries the matching Calamares source bundle named `bitcoin-core-vault-v0.4.0-calamares-source.tar.xz`. Recompiling Calamares, Thunar and upstream Core is a separate check from assembling the ISO using their recorded binaries.

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
     gpg --homedir "$keyring" --import btcpavao-pgp.asc
     gpg --homedir "$keyring" --verify SHA256SUMS.asc SHA256SUMS
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

`tools/rebuild/inputs.env` names the builder image by its immutable amd64 digest, an exact Debian snapshot and the timestamp used by live-build. `tools/rebuild/InRelease.sha256` fixes Debian's signed archive indexes. APT verifies packages against the signed indexes. `tools/core-vault/manifests/keepassxc-release.json` fixes the signed upstream KeePassXC AppImage. The repository records the two Core executable hashes and carries the three project-specific Debian packages under `config/packages.chroot/`. A successful run checks the generated installer payload and RAM policy inside the result.
