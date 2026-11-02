# Build provenance — Vault v0.3.0

The released image is a testable binary distribution with a matching
standalone source snapshot. No byte-identical rebuild from that snapshot
on an independent clean host has been demonstrated.

Build host: Debian 13 (ThinkCentre); final binary built 2026-11-02.
Base Vault image used before final permissions repair:
`bitcoin-core-vault-32.1-direct-wallet-20261102-amd64.iso`,
SHA-256 `0911c903400e9b200c163729668eb2786b80c770896ad40b50a3b80cac3233bf`.
Final image SHA-256:
`26a1cb255db3cd48b5427a87c6692cb2cfce94bb249207acac90ea7e4f4bb047`.

The parent image had the correct code, Core 32.1, KeePassXC 2.8.0 and
backup module 0.7.3 but an unsafe remaster had reset non-root UID/GID.
The final ISO was constructed from this exact SquashFS by extracting it,
restoring the **24 non-root UID/GID/mode mappings** listed in
`tools/core-vault/manifests/critical-ownership-debian13.json` from the
known-good 2026-10-29 image, compressing the filesystem with
`mksquashfs -comp xz -b 131072`, and replacing
`/live/filesystem.squashfs` and its line in `/sha256sum.txt` using
`xorriso` with El Torito boot replay. The ELF and functional Calamares
3.3.14-1+corevault4 stayed unchanged.

In a complete fresh build, standard `live-build` should preserve those
numeric owners itself. The new `tools/core-vault/check-squashfs-ownership.py`
gate fails closed if they do not match the reviewed baseline.
Review `tools/core-vault/build-live-iso.sh` and
`tools/core-vault/prepare-installer.sh` for Debian package
dependencies, vendor patch application and Core signature checks.

Original verified upstream programs and locally patched Debian packages
retain their licenses. Relevant packages include
`config/packages.chroot/calamares_3.3.14-1+corevault4_amd64.deb`
and the corresponding source patch recipe under
`tools/core-vault/calamares/`; Thunar patches and source recipes are under
`tools/core-vault/thunar/`. Bitcoin Core 32.1 provenance and signature
verification records are under `provenance/32.1/`. See
`THIRD_PARTY_NOTICES.md` and `RELEASING.md`.

The source snapshot does not expose the full private development history.
Its public Git commit is documented separately in `SOURCE-COMMIT.txt`.
