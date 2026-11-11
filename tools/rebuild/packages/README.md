# Build the custom Vault native packages

Use a disposable amd64 Linux computer with Docker, Git, internet access and at least 25 GB of free space. No wallet, GPG key or password is needed. Clone this public repository, check out the commit shown on the Actions run, and open a terminal in the repository. The job uses the Debian archive signatures, snapshot and container image digest recorded in this commit.

Choose one component and run these commands. Set `package=thunar` to check the file manager. Keep each result in its own new directory.

```bash
package=calamares
source tools/rebuild/inputs.env
mkdir "result-$package"
docker run --rm --platform linux/amd64 --hostname native-builder \
  --mount "type=bind,source=$PWD,target=/src,readonly" \
  --mount "type=bind,source=$PWD/result-$package,target=/evidence" \
  "$BUILDER_IMAGE" bash /src/tools/rebuild/packages/build.sh "$package"
(cd "result-$package" && sha256sum --check SHA256SUMS)
cat "result-$package/historical-match.json"
```

`installed_elf.match` compares the bytes of the actual executable shipped in the published package with the executable from this build. `whole_deb.match` also covers metadata, documentation and every other file in the package. The original Calamares archive used an incremental compilation and replaced only the executable in a prior package. This recipe performs a complete Debian build of the archived patched tree. For Thunar the recipe uses its published patched source and pinned private-prefix build dependencies, runs the dispatch test, and packages the resulting executable with the authenticated Debian stock payload and archived source documentation. The artifacts are for review in a disposable environment.

Run **Recompile Vault native packages** in GitHub Actions to see comparisons between two separate builders for both components. Each build publishes package and executable SHA-256 hashes, installed compiler package versions, ELF build IDs, and a separate comparison against the historical release. A difference means the compared bytes differ. Review the exact source changes, compiler flags, build paths and binary differences before relying on the result.

The first pair of Thunar builds produced identical executables and identical rebuilt Debian packages. Compared with the historical Vault executable, exactly 20 of 1,002,336 bytes differed. All 20 were the GNU build ID. Every other byte, including instructions, read-only data and ELF headers, matched. The published evidence includes both full hashes, build IDs, byte counts and links to the two build jobs. [Thunar comparison for source commit d1a4d991](evidence/d1a4d991-thunar.json)


The new packages carry project revisions `3.3.14-1+corevault5` (Calamares) and `4.20.2-1+deb13u1+corevault2` (Thunar). To build from a checkout whose image already uses the new revisions, mount a directory containing the two historical v0.5.0 reference packages into the builder and set `VAULT_HISTORICAL_PACKAGES` to that mounted directory. The same pinned package hashes are checked before extracting source or comparing historical binaries.

Both clean Calamares compiles for the first comparison produced the same complete Debian package. The historical archive and the full new Debian build contain 570 paths each. All 40 native ELF files have matching `.text` machine-instruction sections. Their full ELF files differ. The historical main program records an extra build-directory library search path, and the new main program has no `DT_RUNPATH` entry. Its read-only data also differs at three Qt resource timestamps. Installer boot, disk selection, installation and reboot require acceptance on the full candidate image. [Calamares comparison for source commit d1a4d991](evidence/d1a4d991-calamares.json)

## Download and unpack the corresponding source

The source-only bundles for the versioned native packages include the patched code, build inputs and provenance. In a fresh clone containing the native compiler commit and this export tool, run the following using Debian 13 with Python 3, Git, GNU tar, xz and dpkg installed. The exporter checks the archived inputs against the frozen hashes before unpacking them.

```bash
python3 tools/rebuild/export-native-sources.py ../vault-native-sources
(cd ../vault-native-sources && sha256sum --check SHA256SUMS)
diff tools/rebuild/packages/evidence/938a22ba-sources.SHA256SUMS ../vault-native-sources/SHA256SUMS
```

An empty `diff` output and a zero exit status mean both source archives match the recorded bytes. Calamares contains `source/debian/changelog` for the new revision and the full patched source tree. Thunar includes the complete corresponding-source directory with its pinned dependency manifest, Debian originals and prepatched source archive.
