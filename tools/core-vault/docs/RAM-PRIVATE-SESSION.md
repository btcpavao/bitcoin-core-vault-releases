# RAM-only private session

**GPG feature branch:** the source extends the existing verified export chain
with symmetric `.gpg` backups beside default `.7z`. The published `v0.1.0` ISO
is unchanged and contains the 7z workflow. A rebuilt candidate ISO, its GUI,
real-wallet restoration and Finish acceptance still need their own evidence.
The dated entries below remain historical records, not acceptance of this
feature. See [the GPG profile](../../../docs/GPG-BACKUP.md) and
[encryption security levels](../../../docs/ENCRYPTION-SECURITY-LEVELS.md).

The installed internal disk contains Debian, program binaries and immutable
defaults. The Vault account home is a bind mount of `/run/core-vault/home`.
Both this home and the entire private workspace are on one explicit tmpfs
mounted with `noswap,nodev,nosuid,noexec`, mode 0700, UID/GID 1000 and a
50% RAM size limit. A missing RAM mount prevents the desktop and Core from
starting. The underlying installed `/home/vault` is root-owned, mode 000.

This prevents new private session material from reaching the internal OS disk
through the ordinary appliance workflow. It does not erase material that an
older system previously wrote to that disk. Live memory acquisition, malicious
firmware and an already compromised OS remain outside this boundary.

2026-10-05 — Live Core startup correction: the original Live ISO was reproduced
with `/var/tmp` on overlay; the launcher refused to start Core with
`Bitcoin Core requires volatile system temporary directories.` Native
`tmp.mount` and `var-tmp.mount` now provide the same protected RAM scratch policy
in Live and installed modes and are required before workspace checks and LightDM.
Source/template checks, systemd unit checks, 22 private-session tests and 49
installer tests pass. The rebuilt ISO passes all Live, installer and private-session
content gates, including the enabled temporary-mount symlinks.

Cold BIOS and UEFI Live boots of ISO SHA-256
`41a1992410100eefff1537e18e1220cb6146b168ceaa0c37b1ef2b2910cb2e70`
(752,877,568 bytes) open the official Core 31.1 GUI from the Home tile without
code or mount overlays. Both native temporary mounts are enabled protected tmpfs;
local RPC reports `networkactive=false` and zero connections. The test VMs use
separate disposable disks, no network adapter, and an ephemeral debug shell only
for diagnostics. Evidence is under
`/home/pavao/vault-test-results/live-core-20261005`.
This acceptance covers Live Core startup; the earlier full wallet, installation
and power-loss workflows have not been repeated on this rebuilt ISO.

2026-10-05 — GUI wallet correction: creating an unencrypted wallet in the Live
GUI reproduced an uncaught `std::logic_error`: `Attempt to write settings file
when dynamic settings are disabled.` The GUI wallet loader requests a startup
setting that the earlier `-nosettings` option prohibited. Core now uses explicit
`-settings=/home/vault/.bitcoin/settings.json` in the validated RAM home, with all
offline command-line restrictions retained and the official binary unchanged.
The actual launcher fixture passes startup-setting create/load/unload transitions,
encryption, confinement and same-process checks. A disposable BIOS Live session
with only the helper option changed in its volatile overlay also passes GUI wallet
creation, later encryption, close and reopen. This candidate test does not certify
a rebuilt ISO; final image content and cold boot acceptance remain required.
Evidence: `/home/pavao/vault-test-results/live-encrypt-20261005`.

2026-10-05 — Desktop and backup candidate: Num Lock is enabled once at session
startup. KeePassXC opens its stock generator with Passphrase and six words
seeded as the initial defaults. The bottom taskbar has a white Debian Home control, Minimize/Close
context actions and normal middle-click close. Sync Hide retains the native
Core control with fresh-frame and modal guards. Wallet Backup accepts wallets
with or without Core private-key encryption; its 7z archive remains encrypted.
Thunar snapshots selected wallets consistently and records a verified single
wallet export for Finish. These are source changes; the ISO must be rebuilt.

## Lifecycle and paths

`run-core\x2dvault.mount` provides the RAM filesystem. `core-vault-prepare.service`
copies only immutable `/etc/skel` defaults and creates private directories.
`home-vault.mount` binds the RAM home over the account's real passwd HOME before
LightDM starts. Thus applications using either HOME or getpwuid() reach RAM.
Live account provisioning completes before preparation; the installed account
already exists. Installer mode retains its dedicated Calamares session.

| Data | Location | Lifetime |
| --- | --- | --- |
| Account home / Qt / GTK / desktop state | `/home/vault` -> `/run/core-vault/home` | RAM session |
| Core datadir and logs/cookie/config | `/home/vault/.bitcoin` | RAM session |
| Core walletdir | `/home/vault/.bitcoin/wallets` | RAM session |
| Core private runtime / observer log | `/run/core-vault/state/core-runtime` | RAM session |
| User temporary working files | `/home/vault/Private Workspace` | RAM session |
| Consistent plaintext wallet backup and read-back verification | `/run/core-vault/export` | RAM session; temporary directories removed after use |
| GPG private working state and provisional decrypted output | Checked RAM temporary directories / Private Workspace | Operation; failed staging removed before publication |
| TMPDIR / TMP / TEMP | `/run/core-vault/tmp` | RAM session |
| XDG config/cache/data/state | Subdirectories of the RAM home | RAM session |
| Export receipts and archive hashes | `/run/core-vault/state` | RAM session |
| Ordinary system scratch / print spools | tmpfs `/tmp`, `/var/tmp`, `/var/log`, `/var/spool/cups`, `/var/cache/cups` | Boot |
| Intentional encrypted exports | Selected USB/external filesystem | Persistent on selected media |

No executable is copied into the private mount. Required programs remain in
the persistent, root-owned OS directories. Shell commands and Python scripts
can still be read by their interpreters; `noexec` is not an application sandbox.

Bitcoin Core now runs inside an unprivileged bubblewrap filesystem namespace.
The OS, removable media and device filesystem are read-only to Core. Only the
verified RAM home/workspace, Core's private runtime and RAM system scratch are
writable. The shared desktop runtime `/run/user/1000` remains read-only to Core;
the outer startup lock stays there. `/dev/shm` is also read-only, so an unloaded wallet cannot be hidden
in a child-only temporary filesystem. Core's local RPC and process identities
are preserved. There is no unsandboxed fallback when isolation cannot start.
Both launch stages also reject descendant mounts under the writable RAM roots;
recursive binds must not import a GVFS/portal filesystem or another tmpfs there.
Normal Core save dialogs therefore save raw wallet backups and signed PSBTs in
RAM. Wallet Backup exports encrypted archives separately; Files transfers signed
PSBTs. Copy newly attached imports to Private Workspace before opening in Core.
The installed `/media` mountpoint directory is protected tmpfs too, avoiding
persistent media-label directories without changing external child filesystems.

The wallet inventory includes default wallets and `wallet.dat` files elsewhere
in the RAM home, workspace (including export and Core's private runtime) and
system scratch. The shared desktop runtime, including systemd's inaccessible
placeholder, is outside Core's writable roots and the wallet scan.
Loaded RPC names are matched to actual paths, including `../` and absolute names.
An unrecognized loaded wallet stops normal finish. Root-only scratch directories
that the Vault user can neither read nor write are skipped; unreadable directories
owned by Vault fail closed. Helpers remove their temporary backup/read-back files
before returning. Any residual wallet file remains subject to verification.

Mount probes use `findmnt --uniq` to select visible mounts. Ordinary `findmnt`
can return shadowed and active entries together inside the bind-mounted namespace;
`--first-only` was observed to select the shadowed read-only entry in testing.

## Controls

The existing no-swap service disables all active swap before the desktop. The
installer creates no swap. Swap/sleep/suspend/hibernate targets are masked;
logind ignores idle, lid and power/sleep keys. Resume is disabled in initramfs
and the installed kernel command line. No zram or persistent backing is added.

Coredump storage and processing remain disabled; kernel.core_pattern is
`/dev/null`, fs.suid_dumpable is zero, and core limits are zero for the session,
Vault user and system services. journald remains volatile; rsyslog and the
coredump socket are masked. Core's own logs stay in its RAM datadir.

The whole desktop inherits the private HOME and XDG variables. GTK recent files
are disabled; other recent lists, thumbnail caches, file-dialog state and crash
recovery files are confined to RAM. Terminal history uses `/dev/null`.
KeePassXC uses RAM configuration/state, no update checks or remembered paths,
a 10-second clipboard timeout and idle locking. A database explicitly saved to
external media remains an encrypted KeePass database there. Printer spool and
cache storage are volatile. Networking restrictions and the verified official
Bitcoin Core binary are preserved.

## Wallet export

Wallet Backup and Thunar share the same consistent snapshot policy. Loaded
wallets use Bitcoin Core's official `backupwallet` RPC, bound only to loopback
with cookie authentication. Closed or unloaded wallets use a normal read-only
SQLite backup transaction without loading them or bypassing database locks.
Core networking remains disabled.
Private-key wallets can be exported whether or not they are encrypted inside
Bitcoin Core; watch-only wallets can also be exported. Wallet Backup keeps
7z as the default and adds GPG for an individual file. 7z encrypts contents and
file names; GPG encrypts the whole file using the selected AES-256 CFB+MDC compatibility profile
and an empty literal filename. The external passphrase is independent of Core
encryption; it need not match any Core passphrase. The balanced recommendation
generates and stores the two passphrases independently.

The consistent raw backup is created in RAM. The Debian-7zip backend keeps its
encrypted-content/header checks and no-overwrite publication. GPG uses stock
Debian GnuPG with symmetric AES-256 and `--force-ocb`; a missing capability must
fail rather than silently changing the encryption profile. Its selected S2K is
iterated-and-salted mode 3, SHA-256, count 65,011,712. No keypair is created.

Both formats are decrypted back into RAM and compared against the expected
snapshot byte hash and logical SQLite wallet data. 7z requires exactly one
encrypted, nonempty `wallet.dat`; GPG additionally requires the accepted
protected-decryption profile and successful cryptographic authentication.
GPG output is provisional until authentication and all expected data checks
succeed, since a failed decryption can leave plaintext. Failed or interrupted
operations must not publish that provisional result or replace an existing
backup. A `.gpg` suffix alone is not verification.

Only verified exports receive a RAM-only format-aware receipt. Existing 7z
receipts remain compatible. Removable destinations are
preferred. Temporary destinations cannot be wallet exports; a destination not
recognized as removable needs an explicit confirmation. Generic Create
Encrypted Backup stays available for other files, with destination warnings.
Thunar's Create Encrypted Backup also accepts wallet.dat files. Loaded wallets
use Core's consistent backup RPC before archiving; closed SQLite wallets use a
read-only database snapshot. Plaintext snapshots and staging stay in checked
RAM and are removed after the operation.

7z passphrases are delivered through a non-echoing PTY; GPG passphrases use a
controlled anonymous input pipe with symmetric caching disabled. Neither is
put in argv, the environment, files or logs. Dumps remain disabled and GPG
state and temporary plaintext remain in verified RAM. Encrypted backups and
receipts contain no plaintext passphrase. Removing Python references does not
guarantee complete memory sanitization. Verification does not replace a complete
restore/inheritance drill, preferably at least annually.

Double-click recovery of `.gpg` uses the existing Files flow, requests its
external passphrase and publishes successful recovered output only in checked
RAM without replacing an existing file. The default output is `recovered-file`,
which may be selected in Core's restore flow for a wallet snapshot; recovery
does not automatically classify or name it `wallet.dat`. Generic recovery does
not by itself
record a wallet export. Arqiver remains the 7z reader; its user-selected
extraction destination can be persistent and is not automatically confined to
Private Workspace.

The four educational security levels do not alter export policy. Core-only
protection is not a valid normal Finish export. Manual GPG-inside-7z copies are
supplementary unless both-layer decryption, wallet comparison, restoration and
Finish have actually been proven end to end; retain a separate directly verified
single-layer `.7z` or `.gpg` wallet export. An inner GPG copy available elsewhere
bypasses the outer layer, so the effective recovery model depends on every copy.

GnuPG 2.4 or later is the recommended independent recovery environment for this
selected profile. The Linux 2.4.4 synthetic profile probe passed 38 cases; exact
Debian 13 runtime and candidate-image application acceptance are separate.
Windows Gpg4win and macOS GnuPG/GPG Suite recovery are unverified until directly
tested. No universal OpenPGP-reader compatibility is claimed.

Current descriptor/SQLite wallet databases are supported. Unknown or legacy
database formats may be refused by wallet export. Shutdown does not inspect wallet
formats or verify exports; the user must save recoverable copies before confirming.

## Finish and failure behavior

Home's power actions use the same finish UI for restart and shutdown. The first
warning explains RAM data loss and asks the user to confirm that backups,
passphrases and other required files are saved. The second warning confirms
that anything left only in the session will be unavailable afterward. Neither
step requests passphrases, inventories wallets nor verifies backup receipts.
Backup creation retains its full verification checks.

After the second confirmation, a monotonic 300-second countdown updates every
second. Core and the clipboard remain available. Cancel, Esc or closing the
window stops the timer and leaves the session open. An explicit Restart now or
Shut down now skips the delay. At expiry or explicit override, Core stops cleanly;
a stop failure cancels teardown. Only then are clipboard and X11 selection
cleared and the narrow privileged teardown requested. A shared per-user lock
prevents simultaneous restart and shutdown flows. A closed or crashed countdown
process has no pending system shutdown job.

The privileged helper accepts only `poweroff` or `reboot` and starts one fixed
system service. That service stops LightDM and the Vault user, unmounts the home
and RAM mounts without lazy unmount or recursive root deletion, then requests
shutdown. If a busy mount prevents teardown, power removal still discards the
volatile filesystem; a failure is not reported as successful unmounting.
Each teardown command has a bounded timeout within the system service budget;
OnFailure requests poweroff if the service itself fails or times out.

There is no passphrase-based shutdown gate or separate emergency discard path.
Hard power loss naturally loses the RAM filesystem. A Core or
GUI crash cannot persist the session to the OS drive through swap, dumps or
ordinary application state. This is volatility, not a claim that physical RAM
was securely overwritten.

Shredding remains an optional external-file tool. The Thunar helper
refuses Core wallet paths and directs users to the finish workflow.
Neither overwriting nor TRIM/sanitize is needed for normal wallet-session safety.

## Developer checks

From the source repository:

```bash
python3 tools/core-vault/check-private-session.py
python3 tools/core-vault/test-private-session.py
QT_QPA_PLATFORM=offscreen python3 tools/core-vault/test-finish-session.py
python3 tools/core-vault/test-core-wallet-export.py --core-root ./chroot
python3 tools/core-vault/test-core-launcher.py --core-root ./chroot --real-observer
python3 tools/core-vault/calamares/tests/test_installer.py
python3 tools/core-vault/check-home-suite.py
python3 tools/core-vault/check-installer.py --prebuild
python3 tools/core-vault/check-private-session.py --iso live-image-amd64.hybrid.iso
```

`test-private-session.py` creates only synthetic records on `/dev/shm`. It tests
disk-home and swap rejection, logical wallet change detection, symlink refusal,
real encrypted archive verification, wrong-password rejection, plaintext-header
rejection and tampering. It is not the installed-system forensic acceptance test.

`test-core-wallet-export.py` launches the official Core binary in an unprivileged,
read-only bubblewrap sandbox, creates and encrypts synthetic wallet data, uses
real Core backup/restore RPCs and real encrypted 7zip verification, and checks
the exported wallet digest after clean shutdown. Writable files stay in RAM.
Removable-media classification is mocked only for this application test; host
swap/mount policy and final ISO boot are not certified by it.

Inside the actual Vault session run `core-vault-security-check`. In a disposable
test VM, root can add `--scan-persistent` for a read-only internal-root filename
scan. The installed acceptance additionally needs real Core wallet creation,
encryption, official backup and archive export to a separate virtual USB device;
then finish/reboot/power-loss cases and an offline raw-image scan for unique test
markers and wallet names. No real keys or user backup media may be used.

Source and ISO-content gates do not substitute for those boot, application,
recovery, crash and forensic tests. Record actual results before accepting an ISO.

Continuation validation and the current build blocker are recorded in
`RAM-BOUNDARY-REVIEW-20261004.md`. That report supersedes the test counts below:
19 private-session tests and 49 installer tests now pass; actual launcher
confinement and exported-archive restore have also been exercised. The final ISO
still requires rebuilding and BIOS/UEFI/forensic acceptance.

## Implementacijski inventar i status (2026-10-04)

Ovaj odjeljak bilježi stanje razvoja. Konačni sigurnosni prihvat još nije završen.
Projekt je izmijenjen na `/home/pavao/core-signer-os`. Ranije nepovezane radne
izmjene nisu uključene u ovaj inventar. Za svaku izmijenjenu runtime datoteku iz
`config/includes.chroot` održava se odgovarajuća kopija na istoj relativnoj
putanji u `tools/core-vault/runtime-template`.

| Značajna datoteka | Svrha promjene |
| --- | --- |
| `config/hooks/live/0940-core-vault-backup.hook.chroot` | Usklađivanje i provjera novog backup paketa. |
| `config/hooks/live/0948-core-vault-private-session.hook.chroot` | Maske, jedinice, GTK/KeePassXC zadane postavke, volatile LightDM auth i zabrane dumpova/loggera. |
| `config/hooks/live/0950-core-vault-installer-check.hook.chroot` | Provjera paketa i manifest svih novih privatnih runtime datoteka. |
| `config/includes.chroot/etc/initramfs-tools/conf.d/core-vault-noresume` | Isključuje resume u initramfsu. |
| `config/includes.chroot/etc/security/limits.d/core-vault.conf` | Core dump limit 0 za Vault račun. |
| `config/includes.chroot/etc/sudoers.d/91-core-vault-poweroff` | Sudo dopušta samo dva točna argumenta uskog Finish pomoćnika. |
| `config/includes.chroot/etc/sysctl.d/80-core-vault-memory.conf` | Kernel dump putanja /dev/null i zabrana suid dumpova. |
| `config/includes.chroot/etc/systemd/logind.conf.d/core-vault.conf` | Isključeni sleep/lid/idle/power događaji koji bi zaobišli Finish. |
| `config/includes.chroot/etc/systemd/system.conf.d/core-vault.conf` | Core dump limit 0 za sistemske servise. |
| `config/includes.chroot/etc/systemd/system/core-vault-end-session@.service` | Root teardown uz sigurnosno gašenje pri padu ili isteku vremena. |
| `config/includes.chroot/etc/systemd/system/core-vault-prepare.service` | Priprema nakon live-config/no-swap, prije HOME-a i LightDM-a. |
| `config/includes.chroot/etc/systemd/system/core-vault-workspace-check.service` | Uvjet spremne RAM sesije prije prijave. |
| `config/includes.chroot/etc/systemd/system/home-vault.mount` | Bind RAM HOME-a preko stvarnog passwd HOME-a prije LightDM-a. |
| `config/includes.chroot/etc/systemd/system/lightdm.service.d/35-core-vault-safety.conf` | LightDM ovisi o provjerenom RAM HOME-u. |
| `config/includes.chroot/etc/systemd/system/run-core\x2dvault.mount` | Vlastiti tmpfs noswap,nodev,nosuid,noexec; 0700 UID/GID 1000, najviše 50% RAM-a. |
| `config/includes.chroot/usr/lib/core-vault-installer/target.py` | Instalirani HOME fallback 000/root, noswap scratch/log/print mountovi, maske i noresume. |
| `config/includes.chroot/usr/lib/core-vault/export.py` | Core backup u RAM-u, postojeće 7zip šifriranje, provjera sadržaja i odredišta te potvrda izvoza. |
| `config/includes.chroot/usr/lib/core-vault/runtime.py` | Provjera RAM mountova, inventar walleta, službeni snimak otvorene baze, usporedba SQLite zapisa i RAM potvrde izvoza. |
| `config/includes.chroot/usr/local/bin/core-vault-bitcoin` | Provjereni RAM datadir/walletdir i dinamičke postavke, lokalni RPC i odbijanje root računa. |
| `config/includes.chroot/usr/local/bin/core-vault-file-places` | RAM HOME i Private Workspace favoriti bez dupliranih sistemskih volumena. |
| `config/includes.chroot/usr/local/bin/core-vault-finish` | Provjera svakog walleta i arhive, uredno zatvaranje Corea, provjera zadnjeg zapisa te izričita hitna opcija. |
| `config/includes.chroot/usr/local/bin/core-vault-guide` | Jednostavne upute za RAM sesiju, backup, gubitak podataka i Finish. |
| `config/includes.chroot/usr/local/bin/core-vault-home` | Wallet Backup kartica, opis privatne sesije i Finish preko postojećih power kontrola. |
| `config/includes.chroot/usr/local/bin/core-vault-install-check` | Provjera novog instalacijskog i RAM sigurnosnog profila. |
| `config/includes.chroot/usr/local/bin/core-vault-keepassxc` | Provjera sesije i pokretanje KeePassXC-a s RAM postavkama. |
| `config/includes.chroot/usr/local/bin/core-vault-security-check` | Napredna dijagnostika RAM-a, swapa, dumpova, journala i aktivnih Core putanja. |
| `config/includes.chroot/usr/local/bin/core-vault-session` | HOME, XDG i privremene putanje za cijelu privatnu radnu sesiju; bez diskovnog fallbacka. |
| `config/includes.chroot/usr/local/bin/core-vault-shred` | Odbijanje Core wallet putanja; Shred ostaje pomoćni alat za vanjske datoteke. |
| `config/includes.chroot/usr/local/bin/core-vault-storage-check` | Zaustavlja pokretanje ako privatna pohrana nije valjana RAM sesija. |
| `config/includes.chroot/usr/local/bin/core-vault-wallet-backup` | Novi GUI ulaz za provjereni šifrirani wallet export na vanjski medij. |
| `config/includes.chroot/usr/local/libexec/core-vault-destroy` | Zatvaranje sesijskih procesa, zaustavljanje dvaju fiksnih mountova i gašenje; ograničeni timeouti. |
| `config/includes.chroot/usr/local/libexec/core-vault-prepare` | Priprema praznog RAM HOME-a iz statičkog /etc/skel predloška. |
| `config/includes.chroot/usr/local/sbin/core-vault-end-session` | Uska privilegirana naredba s isključivo poweroff/reboot argumentom. |
| `config/includes.chroot/usr/local/sbin/core-vault-installer` | Usklađivanje s novom provjerenom verzijom Calamaresa. |
| `config/includes.chroot/usr/share/core-vault/shred-policy.json` | Ažurirani hash manifest postojećeg Shred/Places/Guide runtimea. |
| `tools/core-vault/backup-src/build-package.sh` | Verzija backup paketa 0.5.1 i njegovo slaganje. |
| `tools/core-vault/backup-src/src/backup.py` | Upozorenja za odredišta, prednost vanjskim medijima, konzistentni wallet snapshot i potvrda pojedinačnog izvoza za Finish. |
| `tools/core-vault/build-live-iso.sh` | Zadržan postojeći live-build; nova preflight i završna ISO provjera privatne sesije. |
| `tools/core-vault/calamares/base_patch.py` | Usklađen završni tekst instalacije s volatilnom privatnom sesijom. |
| `tools/core-vault/calamares/package_state.py` | Provjera Calamares paketa corevault3. |
| `tools/core-vault/calamares/tests/test_installer.py` | Provjere novog instalacijskog profila i volatilnih putanja. |
| `tools/core-vault/check-backup-iso.py` | Usklađena provjera novog broja kartica, Finish putanje ili novih verzija paketa. |
| `tools/core-vault/check-backup.py` | Usklađena provjera novog broja kartica, Finish putanje ili novih verzija paketa. |
| `tools/core-vault/check-bleachbit.py` | Provjera odsutnosti uklonjene aplikacije, paketa i pomoćnika; GNU shred ostaje dostupan. |
| `tools/core-vault/check-installer.py` | Usklađena provjera novog broja kartica, Finish putanje ili novih verzija paketa. |
| `tools/core-vault/check-power-core.py` | Usklađena provjera novog broja kartica, Finish putanje ili novih verzija paketa. |
| `tools/core-vault/check-power-theme.py` | Usklađena provjera novog broja kartica, Finish putanje ili novih verzija paketa. |
| `tools/core-vault/check-private-session.py` | Usklađenost runtime predložaka, izvora i doslovnog sadržaja ISO-a. |
| `tools/core-vault/check-shred.py` | Provjera Thunar permanent-delete integracije i stvarnog GNU shred sadržaja u Live i instalacijskom payloadu. |
| `tools/core-vault/check-ui-polish-v4.py` | Usklađena provjera novog broja kartica, Finish putanje ili novih verzija paketa. |
| `tools/core-vault/docs/RAM-PRIVATE-SESSION.md` | Arhitektura, prijetnje, putanje, oporavak, provjere i stvarni status prihvata. |
| `tools/core-vault/prepare-installer.sh` | Staging nove Calamares verzije. |
| `tools/core-vault/test-core-wallet-export.py` | Stvarni Core create/encrypt/backup/restore i regtest PSBT testovi u izolaciji. |
| `tools/core-vault/test-installed-private-session.py` | Pripremljen test stvarne instalacije, vanjskog USB-a, crasha i testnih markera. |
| `tools/core-vault/test-private-session.py` | 10 sigurnosnih i regresijskih testova, stvarni 7zip i simulirani neodazivajući Core. |
| `tools/core-vault/scan-vm-private-markers.py` | Offline skeniranje cijele ugašene virtualne slike diska, uključujući obrisane blokove; odbija aktivnu sliku i stvarne uređaje. |
| `tools/core-vault/vm-private-session.py` | QMP upravlja isključivo vlastitim zasebnim testnim VM-om i slikom diska. |

Staged paketi: `calamares_3.3.14-1+corevault3_amd64.deb` i
`core-vault-backup_0.5.1_all.deb` u `config/packages.chroot`.
Službeni Core 31.1 binary nije mijenjan; SHA-256 bitcoin-qt:
`fcd4c1a3193e0cb4eec9d980c835d822ad726627b0c01281b13f5c3c1f593fcb`.

| Stvarno izvedena provjera | Rezultat i granica |
| --- | --- |
| Privatna sesija: 10 testova | PASS: disk HOME/swap odbijanje, hash promjena, symlink, potvrde izvoza, 7zip enkripcija, pogrešna lozinka, tamper, normalni i hitni Finish pri neodazivajućem Coreu. |
| Stvarni Core create/encrypt/backup/restore | PASS u izoliranom read-only bubblewrap okruženju; odredište je testni RAM i klasifikacija medija je simulirana. |
| Regtest financiranje i PSBT potpisivanje | PASS; Core prihvaća sintetički potpisanu transakciju, backup i restore prolaze, hash ostaje valjan nakon zatvaranja. |
| Instalacijski source testovi | PASS: 47 testova. |
| Home Qt geometrija | PASS na 800x600, 1024x768, 1280x800 i 1920x1080; 12 kartica. |
| Shred sintetički engine testovi | PASS: 24 testa; pomoćni alat, ne wallet sigurnosni model. |
| Backup stvarni 7zip i Qt dijalozi | PASS prethodno izvedenih roundtrip, password i dark-dialog provjera. |
| systemd unit graph | PASS, exit 0; uključuje završni OnFailure i ograničene timeoutove. |
| Preflight izvori i staged paketi | PASS. |
| Prvi ISO sadržaj | PASS nakon ispravaka testnog čitanja doslovnog systemd naziva i BleachBit symlinka. |
| Prvi BIOS Live boot i instalacija | PASS: RAM priprema/HOME/no-swap/Core-dump kernel policy potvrđeni; Calamares je uspješno instalirao na zasebni 24 GiB qcow2. |
| Prvi kandidat: boot bez ISO-a i dijagnostika | PASS: stvarni HOME/tmpfs, prazan swap, sleep/hibernate maske, dumpovi, volatile journal, TMPDIR i aktivne Core putanje; RPC networkactive=false, connections=0. |
| Prvi kandidat: GUI Finish bez walleta | PASS nakon clipboard popravka izvedenog samo u RAM-u VM-a; uski root helper ugasio je vlastiti VM. Core je prethodno zatvoren službenim CLI-em. |
| Prvi kandidat: crash i offline marker scan | PASS: marker u Private Workspace/cache/tmp i memoriji namjerno abortiranog procesa nije pronađen ni u jednom od 25769803776 skeniranih bajtova cijelog virtualnog diska. To nije wallet/UEFI/power-loss prihvat konačnog ISO-a. |
| Prvi kandidat: sljedeći boot | PASS: sva tri testna marker fajla nestala, walletdir prazan, bez RAM potvrde izvoza; security-check ponovno prolazi. |
| Konačni ISO s popravcima stvarnog wallet workflowa | PENDING: potreban ponovni postojeći live-build. |
| Konačni BIOS/UEFI workflow, KeePassXC, GUI Finish i crash/power-loss | PENDING; pripremljen zaseban VM/USB testni postupak. |
| Offline raw-disk marker scan nakon Finish/power-loss/reboota | PENDING; dosadašnji izvori i application testovi ga ne dokazuju. |

Prvi kandidat ISO ima 752877568 bajtova i SHA-256
`1449745bada4402a099f8490c40ef0247c87091e2da940114e83db9385f3601f`.
To nije konačni ISO: nakon stvarnih Core testova popravljeni su čitanje otvorene
SQLite baze preko službenog RAM backupa, parsiranje string RPC odgovora,
spremanje RAM potvrde izvoza, hitni Finish pri neodazivajućem Coreu i korištenje
stvarnog `QClipboard.Mode` enuma. GUI test za posljednji popravak izvršen je
iz izmijenjenog koda samo u RAM-u testnog VM-a, bez izmjene instaliranih datoteka.
Offline rezultat je `PASS_NO_SUPPLIED_MARKERS`, bez pogodaka. SHA-256 te sirove
24 GiB testne slike nakon Finish-a:
`8fdc3d68d7ea42e03bcd295cef5933a66467a758f827c2ad2e1074a1b39336f2`.
Ovaj rezultat pokriva samo navedeni jedinstveni marker i konkretni test.

Dokazi su u `/home/pavao/vault-test-results/ram-session-20261004`, uključujući
`private-tests-final.log`, `core-application-test.log`,
`regtest-application-test.log`, `installer-source-tests.log`,
`candidate-ram-marker-scan.log`,
`native-qt-prebuild.log`, package build rezultat i zasebne QMP manifest/snimke.
Izvorne datoteke prije zahvata sačuvane su u `sources-before.tar.gz`.

Za sljedeću izgradnju koristi se postojeći postupak:

```bash
cd /home/pavao/core-signer-os
bash tools/core-vault/build-live-iso.sh
```

Remote Desktop Commander blokira sudo; administratorsku izgradnju treba pokrenuti
lokalno. Taj blok nije zaobiđen. Izgrađeni kandidat nije proglašen forenzički
prihvaćenim niti konačnim izdanjem.
