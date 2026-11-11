# Rebuild Vault's two project-modified C++ applications and the ISO

This separate candidate recompiles the Calamares installer and the Thunar file manager. It uses the same Debian snapshot and pinned amd64 builder as the earlier ISO assembly. Each compiler runs in its own clean container. The image builder separately rebuilds Vault Backup. Debian system packages and the verified upstream Bitcoin Core and KeePassXC release binaries remain external inputs.

## Independent build

1. Use a separate disposable Linux amd64 VM with Git, Docker and Internet access. Approximately 40 GiB of free disk space gives the native compilers and ISO builder room. The upper bound depends on Docker's storage driver.
2. Clone this repository and check out the full commit from the candidate build record. If testing a branch, use its exact 40-character commit. Inspect the changes from the previously matched assembly revision with `git diff 9f466c5df912d7f455d86aa34d85a39be7b143fc HEAD`.
3. Run `bash tools/rebuild/build.sh ../vault-native-result`. If only Docker needs root, use `bash tools/rebuild/build.sh --sudo-docker ../vault-native-result`. The command starts fresh compilers for Calamares and Thunar, compares both resulting Debian packages against their records, puts the newly compiled copies in the ISO and runs the image-content checks.
4. Read `../vault-native-result/SHA256SUMS` and `../vault-native-result/native/`. Each package's evidence includes its full hash, executable hash, compiler package inventory and comparison with its historic version. A separate machine can run the same commit, then compare the two entire ISOs using `cmp`. The [general guide](REBUILD.md) covers verifying a signed release.
5. The CI job also tests the same candidate in a UEFI virtual machine. It boots the image, exercises the offline wallet with synthetic data, installs on a blank virtual disk, detaches the ISO, then boots and checks the installed system. The test uses the archived public Vault GPG-era test harness identified in the workflow. ISO reproducibility and this installation test report separately.

Historical v0.5.0 artifacts supply archived corresponding source and historical comparison data. Both source-bearing input packages and the Calamares companion are pinned by their public SHA-256 checksums. The previous packages stay out of the ISO. `tools/rebuild/packages/build.sh` contains the compiler commands, their input hashes and the native package version changes. `config/packages.chroot/` contains the expected reviewed Debian packages used for full-byte comparisons.

## Hrvatske upute

1. Na odvojenoj 64-bitnoj Linux virtualnoj mašini pripremi Git i Docker. Postavljanje je opisano u [hrvatskim uputama za Vault](REBUILD.hr.md).
2. Preuzmi repozitorij, a zatim u terminalu odaberi točan commit iz zapisa o gradnji kandidata. `git rev-parse HEAD` ispisuje oznaku za usporedbu.
3. Pokreni `bash tools/rebuild/build.sh ../vault-native-result`. Ako koristiš `sudo docker`, pokreni `bash tools/rebuild/build.sh --sudo-docker ../vault-native-result`. Oba izmijenjena programa gradit će se iz njihovih izvora u zasebnim okruženjima. Zatim se ponovno gradi i paket Vault Backup te sastavlja ISO.
4. U direktoriju `../vault-native-result/native/` nalaze se podaci za provjeru kompajliranih programa. U `SHA256SUMS` je otisak cijelog ISO-a. Druga osoba može izgraditi istu reviziju i provjeriti podudaraju li se baš svi bajtovi naredbom `cmp`.
5. Pomoć LLM-a možeš zatražiti ovako: „Molim te, iz ove javne skripte objasni odakle dolazi izvor za Calamares i kako mogu provjeriti da u ISO zaista ulazi moj novokompajlirani program.“ Za odgovor mu je dovoljan javni kod ili ispis iz terminala.
