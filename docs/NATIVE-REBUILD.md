# Vault v0.9.0 native sources and rebuild boundaries

The released image uses Calamares `3.3.14-1+corevault10localrolesfix1` and Thunar `4.20.2-1+deb13u1+corevault2`. The matching package inputs are retained in `config/packages.chroot/`. The image also contains the verified upstream Bitcoin Core and KeePassXC binaries and pinned Debian/T2 inputs; inspecting or compiling a native application does not recreate the complete ISO.

[Release files](https://github.com/btcpavao/bitcoin-core-vault-releases/releases/tag/v0.9.0) · [ISO identity and source-build guide](REBUILD.md) · [Release validation scope](RELEASE-v0.9.0.md)

## Calamares v10: exact retained source companion

Download `bitcoin-core-vault-v0.9.0-calamares-source.tar.xz` from the release and authenticate it against the signed `SHA256SUMS` as described in [REBUILD.md](REBUILD.md). The archive is 2,716,080 bytes, SHA-256:

```text
c3b1fd896a8109669abe0a6871d267f4dcdf712b423b6eb9d02089f303cf3e76
```

The corresponding reviewed binary is `calamares_3.3.14-1+corevault10localrolesfix1_amd64.deb` (4,251,504 bytes), SHA-256:

```text
e46bb7e6006c973fd85775b454f059d83a77a99692d6d8d2f2a9c606998dd9c6
```

Inside `bitcoin-core-vault-v0.9.0-calamares-source/`:

- `source/` contains the complete retained patched application source, third-party source, licenses, CMake rules and Debian packaging.
- `build-evidence/` contains the exact retained v10 `.buildinfo`, `.changes`, original build result, local recipes and source-change records.
- `SOURCE-FILES.sha256` identifies the exported source and evidence files.
- `PROVENANCE.json` records the source origin, the matched final source inputs and exclusions.

This is the retained patched source from the original compiler tree, rather than a reconstructed pristine Debian `.dsc` package. Its eight recorded final changed inputs were compared with the retained source before export. Compiler objects, caches and generated package output are excluded.

### Compile the application independently

Use a disposable Debian 13 Trixie amd64 environment. Inspect `source/debian/control` for the build dependencies and the retained `.buildinfo` for the actual historical compiler/library versions. The recorded source uses the signed Debian snapshot `20261109T000000Z`; installing current package versions is not the same environment.

With those build dependencies installed, start in the extracted `source/` directory:

```bash
export DEB_BUILD_OPTIONS='nocheck parallel=4'
export DEB_BUILD_PROFILES=nocheck
export SOURCE_DATE_EPOCH=1795521600
export PYTHONDONTWRITEBYTECODE=1
export QT_QPA_PLATFORM=offscreen
dpkg-buildpackage -us -uc -b -j4
```

The `nocheck` settings match the recorded compiler configuration; installation and runtime acceptance are separate. This clean compilation command was not run during publication. The accepted binary was compiled incrementally with `dpkg-buildpackage -b -nc` in the retained compiler tree. A fresh build yielding identical binary/package bytes has not been established for v10. Compare any new output with the package hash above and preserve differences rather than treating source availability as proof of binary reproducibility.

The release source's `tools/core-vault/calamares/` files expose the maintained transformations and reviewed installer model/guards. Read them alongside the full as-used companion and `build-assets/core-vault-calamares-v1/package.json`.

## Thunar and Vault Backup

The Thunar package contains its matching source archive, patch and README under `/usr/share/doc/thunar/core-vault-source/`. Its package/source identities are recorded in `config/includes.chroot/usr/share/core-vault/thunar-shred.json` and the matching runtime template. This package is unchanged by the v0.9.0 installer/desktop work. Older native rebuild results remain attached to their named revisions.

The original Vault Backup source and package recipe remain in `tools/core-vault/backup-src/`, with reviewed package `core-vault-backup_0.7.6_all.deb`. No fresh Thunar or backup package compilation was performed for this publication.

## T2 kernel and firmware inputs

`tools/core-vault/manifests/t2-hardware-release.json` pins the T2 kernel `6.18.64-1-t2-trixie` and Intel/AMD graphics firmware `20250410-2` by exact version, architecture, size, URL and SHA-256. Its archived signed repository metadata is part of the release source. `prepare-t2-hardware.py` verifies these records and the downloaded binary inputs before image assembly.

The manifest records upstream build-script commit `0170d89f789365bfb1a52a0ea08e2568067d7de8`, Linux tag `v6.18.64`, and the T2 patch repository/branch. The upstream build referenced that patch branch as mutable `HEAD`. The exact historical patch commit is not known from those records, and a reproducible T2 source-to-binary build was not performed. The binary authentication evidence and this source provenance limitation are both retained.

## Historical native wrapper

The earlier `tools/rebuild/packages/build.sh` / `tools/rebuild/build.sh` wrapper describes older Calamares and ISO assembly assumptions. Its compiler wrapper now refuses unsupported current package versions before starting Docker, rather than running an older recipe against v10. It is not a demonstrated native rebuild path for the v0.9.0 package or ISO. For the successful v0.8.0 process, check out the [v0.8.0 tag](https://github.com/btcpavao/bitcoin-core-vault-releases/blob/v0.8.0/docs/NATIVE-REBUILD.md) and follow that version's guide. The prior documentation is also [preserved locally](history/v0.8.0/INDEX.md).
