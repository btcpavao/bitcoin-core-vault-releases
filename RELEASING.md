# Releasing Bitcoin Core Vault

This procedure publishes the Debian Vault project in
[`btcpavao/bitcoin-core-vault-releases`](https://github.com/btcpavao/bitcoin-core-vault-releases).
Preserve this repository’s published Git history. The separate
`btcpavao/core-vault` Tauri application is a different project.

## Current v0.9.0 publication

The accepted v0.9.0 image is the unchanged local desktop-tuning-v2 candidate,
SHA-256 `615067c09f573a4476c7039adc90e58f75a46bdf20a028fd3c58f3e300c832fe`,
1,133,379,584 bytes. Use the versioned asset name
`bitcoin-core-vault-v0.9.0-amd64.iso` and retain its original build identity in
`BUILD-PROVENANCE.json`. The [current guide](docs/REBUILD.md) separates a
functional source-build entry point from the missing independent byte-identical
rebuild evidence. Older v0.8.0 compiler/repacking commands and successful
comparisons remain tied to the [v0.8.0 tag](https://github.com/btcpavao/bitcoin-core-vault-releases/tree/v0.8.0).

The public manifest must cover the final ISO name, tagged source archive,
`SOURCE-COMMIT.txt`, matching Calamares source companion and provenance/evidence
files. Upload and verify the draft assets before the maintainer signs that exact
manifest. Publish the finished signature and release before switching the public
website's signed-download links. Keep unrun checks and historical tests clearly
separated from final-image results.

## 1. Freeze the authoritative source

Use the project on the build computer. Preserve its existing Git history and
local changes. Review the complete staged file list before committing.

Include the build configuration, current helpers, immutable desktop defaults,
installer patches, package manifests, artwork provenance, tests and documentation.
Keep required verified Core binaries and locally patched `.deb` inputs if they
remain part of the build contract. Replacing them with downloads requires exact
versions, authenticated provenance and checksum verification in the preparation
script; merely ignoring them makes the build incomplete.

Exclude generated chroots, caches, VM disks, build logs, local backups, Python
bytecode, RPC cookies, wallet databases, private keys and password databases.
Do not broadly ignore `.config` or `.bitcoin` below `config/includes.chroot`:
immutable account defaults are legitimate source inputs.

Record a Git commit and release tag. Preserve the September RC1 tag as history.
Do not overwrite an existing release asset or move an already-published tag.

## 2. Complete the repository documentation

Publish the README, build preparation instructions, recovery procedure,
component license/provenance notices and current test status. Describe the
RAM-only account home as well as the workspace: normal private session files
are volatile even when the OS is installed on an internal disk.

For the maintainer report of 12 October 2026, record: “Bitcoin Core Vault works
on a ThinkPad T530, as reported by Pavao.” Bind stronger release-specific claims
to the actual ISO checksum and recorded test evidence. Firmware mode, installation
mode and every workflow must not be inferred from this general report.

Keep earlier candidate and failing-image reports as dated historical evidence.
The current README must lead with the current release status rather than a
superseded kiosk or persistent-home design.

## 3. Check a clean source checkout

Document all host packages and preparation steps. Check that a fresh checkout
obtains every required build input and matching manifest. Keep package versions
aligned with the current gates: Core 32.1, backup 0.7.6, Calamares
3.3.14-1+corevault10localrolesfix1 and Thunar 4.20.2-1+deb13u1+corevault2. Confirm these versions against the authoritative tree
before publication.

For a published version, follow the build entry point and limitations in its
tagged [build instructions](docs/REBUILD.md). v0.9.0 exposes
`tools/core-vault/build-live-iso.sh` for a new functional image build. The older
`tools/rebuild/build.sh` native path is not a proven v10/v0.9.0 recipe; its
compiler wrapper refuses unsupported package versions before starting Docker.
Record the actual release packaging inputs and compare the completed artifact
with the image approved for publication. Do not describe a new source build as
byte-identical until the complete-file comparison has passed.

The builder runs source/package gates and then ISO content gates. A successful
content check is separate from boot, installation and wallet recovery testing.

## 4. Verify the exact release image

Against the frozen source tree, run:

```bash
python3 tools/core-vault/check-live-iso.py live-image-amd64.hybrid.iso
python3 tools/core-vault/check-installer-iso.py live-image-amd64.hybrid.iso
python3 tools/core-vault/check-private-session.py --iso live-image-amd64.hybrid.iso
```

Retain the test results for the image being released. Record the SHA-256, byte
size, build date, source commit and component versions. Do not substitute a
checksum from an older image or mark an unrun test as passed.

Verify the archive-based recovery flow using synthetic wallets: create a wallet,
export an encrypted `.gpg`, decrypt into RAM, restore in Core and confirm the
expected labelled address. Include open, unloaded and closed Core cases. The
archive passphrase is independent of Core's optional private-key encryption.

## 5. Prepare licenses and corresponding sources

Document the license of the project's own code separately from upstream code,
bundled libraries and artwork. Preserve exact upstream copyright and license
files, including Core's bundled dependencies and adapted Debian logo notices.

For ISO or patched binary distribution, make the matching corresponding sources
available alongside the binaries. New Calamares builds save patched source, Debian source artifacts and build
information under:

```text
build-assets/core-vault-calamares-v1/source-artifacts/
```

Retain those artifacts even though the builder workspace is excluded from Git.
v0.9.0 additionally publishes `bitcoin-core-vault-v0.9.0-calamares-source.tar.xz`,
an export of the complete retained as-used v10 source and original incremental
build evidence. Its provenance explicitly distinguishes it from a fresh clean
binary rebuild or a pristine Debian source package. The pinned T2 binary and
its signed repository metadata remain recorded separately, including the
upstream mutable patch-reference limitation.
For v0.1.0, the available old source-artifact folder belonged to an earlier
package. Its replacement companion was reconstructed from the verified Debian
source and recorded inputs matching the current package. It includes a
provenance record; it is not an original build log or a bit-reproducibility claim.
The Thunar package contain source/patch/build-recipe payloads; run their
existing gates and verify that the source accompanies the released versions.
Include the required sources/build materials for other distributed components
under their licenses. Generic upstream homepage links do not establish that
the matching source for a locally patched package has been supplied.

Do not sign checksums with a newly invented maintainer identity. If a release
signature is used, it must use the maintainer's chosen signing key and a published,
verifiable fingerprint. SHA-256 checksums alone detect changed bytes; they are
not an independent proof of the publisher's identity.

## 6. Publish the release artifacts

Store the ISO as a GitHub Release asset, with a stable versioned name such as
`bitcoin-core-vault-VERSION-amd64.iso`. The release should contain:

- the ISO;
- `SHA256SUMS` for the final asset filenames;
- the matching source companions and component provenance;
- release notes linking the exact source commit and test results;
- a checksum signature if maintainer signing has been configured.

Generate hashes after the final filenames and source bundles are fixed:

```bash
sha256sum bitcoin-core-vault-VERSION-amd64.iso > SHA256SUMS
sha256sum -c SHA256SUMS
```

Add each companion archive to `SHA256SUMS`. Keep hashes and filenames consistent
with the downloaded assets. Upload to a draft release, verify uploaded asset digests (or download and hash when no server digest is
available), and then publish the release.

GitHub release assets must each be smaller than 2 GiB. The ISO belongs in Release
assets; ordinary Git repository files have a 100 MiB limit. Official references:

- https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases
- https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github

