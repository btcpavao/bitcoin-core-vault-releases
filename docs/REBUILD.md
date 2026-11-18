# Build Vault v0.8.0 and compare it with the signed download

The release ISO is `bitcoin-core-vault-v0.8.0-amd64.iso` (714,407,936 bytes). Its SHA-256 is:

```text
0bc142508a35172ea92f645decc31be1373b05956e9a17d0ad01cee9bab84857
```

Use these instructions to rebuild the exact file that Pavao tested on the ThinkPad T530. You can also verify the download separately by following step 4.

## 1. Get the release source

Use an amd64 Linux computer or disposable Linux VM with Git, Docker Engine and internet access. Allow at least 40 GiB of free working space. Test that the build account can run `git --version` and `docker run --rm hello-world`. Use a computer without wallets or signing keys.

```bash
git clone https://github.com/btcpavao/bitcoin-core-vault-releases.git vault-source
cd vault-source
git switch --detach v0.8.0
git rev-parse HEAD
```

Compare the printed revision with `SOURCE-COMMIT.txt` from the [v0.8.0 release](https://github.com/btcpavao/bitcoin-core-vault-releases/releases/tag/v0.8.0). Keep the Git history. The release build uses earlier commits as well as the final tagged source. The source tarball contains the tagged files for offline inspection.

## 2. Inspect the changes

```bash
git diff --stat v0.7.0 v0.8.0
git diff v0.7.0 v0.8.0 -- config tools .github
```

Press **Space** to advance and **q** to leave the pager. Under `config/`, the desktop settings, offline-session scripts and installer files become part of Vault. Under `tools/`, the repository records how to build and check them. For the USB watch-only changes, inspect `config/includes.chroot/usr/lib/core-vault/public_export.py` and `export_view.py`.

`tools/rebuild/inputs.env` identifies the builder image by its immutable digest, the Debian archive snapshot, and the timestamp used to assemble the system. `tools/rebuild/InRelease.sha256` pins the signed Debian archive metadata. The builder verifies Bitcoin Core and KeePassXC against their upstream release records. It compiles the project-patched Calamares installer and Thunar file manager, and rebuilds the Vault Backup package. [Native package sources and build instructions](NATIVE-REBUILD.md)

## 3. Build the release

From `vault-source`, choose an output directory that does not already exist:

```bash
bash tools/rebuild/build-release.sh ../vault-result
```

If Docker on that machine requires `sudo`, run `bash tools/rebuild/build-release.sh --sudo-docker ../vault-result` instead.

The output to compare is `../vault-result/bitcoin-core-vault-amd64.iso`. The build leaves your USB drives untouched.

Vault v0.8.0 was tested after two small USB export changes were applied to a clean Vault build. To reproduce the exact ISO layout, the release recipe starts with the clean build from `8bbb8b76b98c7b879b7fe1a62bb51e1568d82a10` and packages the runtime changes through `0103f0fde7695156a50ebf2c2ee5966aafc5101e`. The source updates are visible in `git diff 8bbb8b7 0103f0f`. The builder checks the base before using it. [The clean base workflow run](https://github.com/btcpavao/bitcoin-core-vault-releases/actions/runs/44326522554) shows both builder jobs for that revision. [The release workflow](https://github.com/btcpavao/bitcoin-core-vault-releases/actions/workflows/vault-rebuild.yml?query=branch%3Av0.8.0) builds the final ISO twice, compares both files against the release hash and tests installation in a UEFI virtual machine. Each job reports its own result.

## 4. Verify the signed download and compare the build

Create a directory named `release` next to `vault-source`. Download `bitcoin-core-vault-v0.8.0-amd64.iso`, `SHA256SUMS`, `SHA256SUMS.asc` and `btcpavao-pgp.asc` into it from the [v0.8.0 release](https://github.com/btcpavao/bitcoin-core-vault-releases/releases/tag/v0.8.0). To authenticate `SOURCE-COMMIT.txt`, place it in the same directory.

Run `gpg --show-keys --with-fingerprint btcpavao-pgp.asc` in the download directory. Compare the full fingerprint with a value you have confirmed independently for BTC Pavao:

```text
787A 2AAF B0D1 19CA 0522 B2A5 B9C9 9AF8 5788 96D0
```

In Bash, using GnuPG 2.4.7 or later, check the signature before checking the downloaded files:

```bash
(
  set -euo pipefail
  keyring=$(mktemp -d)
  trap 'rm -rf -- "$keyring"' EXIT
  gpg --homedir "$keyring" --batch --import btcpavao-pgp.asc
  gpg --homedir "$keyring" --batch --assert-signer 787A2AAFB0D119CA0522B2A5B9C99AF8578896D0 \
    --verify SHA256SUMS.asc SHA256SUMS
  iso=bitcoin-core-vault-v0.8.0-amd64.iso
  awk -v name="$iso" '$2 == name || $2 == "*" name {print; n++} END {if (n != 1) exit 1}' SHA256SUMS |
    sha256sum --strict --check -
  if [[ -f SOURCE-COMMIT.txt ]]; then
    awk '$2 == "SOURCE-COMMIT.txt" || $2 == "*SOURCE-COMMIT.txt" {print; n++} END {if (n != 1) exit 1}' SHA256SUMS |
      sha256sum --strict --check -
  fi
)
```

After `sha256sum` reports `OK` for the ISO, compare the downloaded file with your rebuild:

```bash
cmp -- bitcoin-core-vault-v0.8.0-amd64.iso ../vault-result/bitcoin-core-vault-amd64.iso &&
  echo 'The complete rebuilt ISO matches the signed download byte for byte.'
```

If a check fails, keep the two hashes, your source revision, the Debian package list, and the first failing command from the build log. `diffoscope --html vault-difference.html first.iso second.iso` compares two local files. Please include the public logs when reporting a difference.

### Getting help from an LLM

Paste the relevant public command and its output, and ask: “What does this command check? Which files change the installed Vault? What should I inspect next?” A rebuild needs only the public source and dependencies. Keep personal wallet files, passphrases and private signing keys out of the conversation.
