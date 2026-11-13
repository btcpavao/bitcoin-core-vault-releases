# Rebuild Vault's two project-modified C++ applications and the ISO

The v0.6.0 release build recompiles the Calamares installer and the Thunar file manager. It uses the Debian snapshot and amd64 builder recorded in the release source. Each compiler runs in its own clean container. The image builder separately rebuilds Vault Backup. Debian system packages and the verified upstream Bitcoin Core and KeePassXC release binaries remain external inputs.

[Signed v0.6.0 release](https://github.com/btcpavao/bitcoin-core-vault-releases/releases/tag/v0.6.0) · [Exact source revision and comparison commands](REBUILD.md) · [Historical native-source candidate](rebuilds/71242344618b.md).

## Independent build

1. Use a separate disposable Linux amd64 VM with Git, Docker and Internet access. Approximately 40 GiB of free disk space gives the native compilers and ISO builder room. The upper bound depends on Docker's storage driver.
2. Clone this repository and check out `26e590741c968316b99416c51a53b9720d8134cb` for v0.6.0. Review the changes since v0.5.0 with `git diff 723d3a8957e86a06853e3ac059159c71174f3c50 HEAD`.
3. Run `bash tools/rebuild/build.sh ../vault-native-result`. If only Docker needs root, use `bash tools/rebuild/build.sh --sudo-docker ../vault-native-result`. The command starts fresh compilers for Calamares and Thunar, compares both resulting Debian packages against their records, puts the newly compiled copies in the ISO and runs the image-content checks.
4. Read `../vault-native-result/SHA256SUMS` and `../vault-native-result/native/`. Each package's evidence includes its full hash, executable hash, compiler package inventory and comparison with its historic version. A separate machine can run the same commit, then compare the two entire ISOs using `cmp`. The [general guide](REBUILD.md) covers verifying a signed release.
5. The release CI job also tests the same image in a UEFI virtual machine. It boots the image, exercises the offline wallet with synthetic data, installs on a blank virtual disk, detaches the ISO, then boots and checks the installed system. The test uses the archived public Vault GPG-era test harness identified in the workflow. ISO reproducibility and this installation test report separately.

Historical v0.5.0 artifacts supply archived corresponding source and historical comparison data. Both source-bearing input packages and the Calamares companion are pinned by their public SHA-256 checksums. The previous packages stay out of the ISO. `tools/rebuild/packages/build.sh` contains the compiler commands, their input hashes and the native package version changes. `config/packages.chroot/` contains the expected reviewed Debian packages used for full-byte comparisons.
