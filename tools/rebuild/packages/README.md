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
