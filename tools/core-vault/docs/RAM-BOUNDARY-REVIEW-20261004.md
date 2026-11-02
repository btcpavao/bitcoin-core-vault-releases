# Završni ISO test i popravak runtimea (2026-10-04)

**Aktualni status: novi ISO uspješno je izgrađen, ali završni test je otkrio dvije greške. Izvori su popravljeni; ISO treba ponovno izgraditi i prihvatiti.**

ISO SHA-256 `651fc0a648a0dcaccaa11ecf6036878d59e015f9c761d5bc0785bae66101d063` prolazi svježu BIOS/UEFI instalaciju i boot bez ISO-a. Prazni Finish ipak blokira systemdov `/run/user/1000/systemd/inaccessible/dir`. Priprema također ostavlja `.local` kao root:root 0700.

Core sada ima vlastiti `XDG_RUNTIME_DIR=/run/core-vault/state/core-runtime`; zajednički runtime desktopa je Coreu read-only i izvan writable wallet inventara. Priprema izričito postavlja vlasništvo `.local`, a storage i process dijagnostika provjeravaju te putanje. Nepoznati nečitljivi direktoriji u stvarnim writable RAM korijenima ostaju fail-closed. Sve četiri runtime datoteke imaju identične template kopije.

| Stvarni rezultat ovog nastavka | Status |
| --- | --- |
| Private-session tests | PASS 22/22 |
| Installer tests | PASS 49/49 |
| Source/package/startup/UI gates | PASS |
| Službeni Core u stvarnom launcheru, privatni runtime RW, shared runtime/media/OS/device RO, single instance | PASS |
| Svježa BIOS/UEFI instalacija i normalni boot bez ISO-a | PASS |
| Prazni Finish u originalnom izgrađenom ISO-u | FAIL; poznata runtime greška |
| Candidate overlay u BIOS instalaciji: inventory/create/encrypt/backup/virtual USB export/integrity/wrong password/restorewallet | PASS |
| Obnovljena adresa, label, public receive/change descriptors i locked encrypted wallet | PASS |
| GUI pogrešna lozinka zadržava sesiju; ispravne provjere i Finish gase VM | PASS |
| Cold boot nakon normalnog Finisha: prazni wallets/receipts/markeri | PASS |
| KeePassXC GUI startup | PASS smoke; puni KDBX/clipboard test nije prihvaćen |
| Nagli QMP quit s aktivnim Coreom i KeePassXC-om | Izveden |
| Offline scan normalnog Finisha, svih 25769803776 bajtova i četiri testne vrijednosti | PASS, nula pogodaka |
| Offline scan naglog prekida, svih 25769803776 bajtova i dvije testne vrijednosti | PASS, nula pogodaka |
| Boot nakon naglog prekida: prazni wallets/receipts/markeri | PASS candidate overlay |
| Novi ISO bez candidate overlaya | PENDING rebuild/acceptance |

Normalni raw disk SHA-256: `a79c8f8c44da14941e8235ec5bfae2bc21dd23a52d45d939fc938d97878b8018`.
Nagli prekid raw SHA-256: `7315d6c1da6b3def9a97ec94003bb6292299839c534383523f888929ab8000b5`.

Dokazi su u `/home/pavao/vault-test-results/ram-session-20261004/final-acceptance-1612`.
`launcher-fixed.log`, `installer-fixed.log`, `vm-bios/fixed-normal-finish-serial.log`, `fixed-normal-finish-scan.log`, `fixed-cold-boot-and-powerloss-serial.log`, `fixed-powerloss-scan.log` te UEFI diagnostics/screenshots su mjerodavni za ovaj nastavak. Marker scan pokriva samo konkretne sintetičke vrijednosti, uključujući deleted blokove. Candidate kod je privremeno bindan iz developer USB fixturea; interni OS source nije izmijenjen u VM-u. To nije prihvat finalnog ISO-a.

Probe sada drži marker u memoriji namjerno abortiranog procesa i vraća wallet iz stvarno izvezene arhive. Raw digest provjerava se prije restorea; post-load digest cijele baze uklonjen je iz recovery testa jer Core smije mijenjati bookkeeping. Umjesto toga provjeravaju se ownership, label, javni descriptori i zaključano/šifrirano stanje. Raniji neuspjeli log ostaje sačuvan.

Značajne promjene: `runtime.py`, `core-vault-prepare`, `core-vault-bitcoin`, `core-vault-security-check` i njihove template kopije; `check-private-session.py`, `test-private-session.py`, `test-core-launcher.py`, `test-installed-private-session.py`, `RAM-PRIVATE-SESSION.md` i ovaj izvještaj. Calamares i službeni Core binary nisu mijenjani.

Sljedeći postupak:
```bash
cd /home/pavao/core-signer-os
bash tools/core-vault/build-live-iso.sh
```
Desktop Commander blokira sudo, pa se build pokreće lokalno. Trenutni ISO gate pravilno odbija stari runtime payload.

## Povijesni izvještaj prije završnog builda

# Core Vault: RAM sesija i stvarni rezultati provjera

Datum: 2026-10-04. Projekt: `/home/pavao/core-signer-os`.

**Izvorni kod je integriran i aplikacijske provjere prolaze. Konačni ISO još
nije izgrađen ni prihvaćen.** Postojeći ISO sadrži starije datoteke i nova
provjera ga ispravno odbija. Završni BIOS/UEFI i forenzički testovi zato ostaju
otvoreni. Ovaj izvještaj dopunjuje `RAM-PRIVATE-SESSION.md`; raniji rezultati
kandidata u tom dokumentu nisu rezultati konačnog ISO-a.

## Arhitektura

Zadržana je postojeća Debian/Calamares arhitektura i minimalni Openbox/tint2
desktop s Thunarom. Sustav, aplikacije i statičke postavke ostaju na internom
disku. Systemd priprema `/run/core-vault` kao vlastiti zaštićeni tmpfs, zatim
veže njegov `home` preko stvarnog `/home/vault` prije pokretanja LightDM-a.
To pokriva aplikacije koje koriste HOME/XDG i one koje čitaju passwd HOME.
Core wallet nastaje izravno u RAM-u; ne premješta se s diska i ne briše se
naknadno kao zamjena za ovu granicu.

Dodana je unprivilegirana bubblewrap izolacija službenog Bitcoin Corea.
Core može zapisivati samo u provjerene RAM putanje. OS, vanjski mediji i
uređajni filesystem vidljivi su Coreu samo za čitanje. `/dev/shm` je također
samo za čitanje kako wallet ne bi ostao u zasebnom, nevidljivom tmpfs-u.
Podmount unutar dopuštenih RAM korijena zaustavlja pokretanje; time se sprječava
uvođenje drugog filesystema rekurzivnim bindom. Ne postoji fallback bez
izolacije. Postojeća lokalna RPC komunikacija, jedna Core instanca i offline
parametri ostaju sačuvani.

Efektivni mount određuje se kernelovim mount ID-em iz `fdinfo`, bez čitanja
sadržaja datoteke. Samo flat mount tablica može prikazati stari child mount
skriven novim RAM mountom roditelja; takav skriveni zapis nije zapisivo
odredište. Stvarni descendant bind istog tmpfs-a ipak se odbija.

Coreov nativni Backup Wallet i spremanje potpisanog PSBT-a koriste RAM.
Wallet Backup zasebno poziva službeni `backupwallet`, izrađuje šifrirani `.7z`
s enkripcijom sadržaja i naziva, zapisuje ga na odabrani medij te provjerava
arhivu i obnovljeni wallet u RAM-u. Potpisani PSBT korisnik prenosi preko Files.
Novopriložene ulazne datoteke prvo se kopiraju u Private Workspace.

Inventar obuhvaća i wallet izvan zadane mape, uključujući apsolutna/`../` RPC
imena te odjavljene wallete u RAM scratch putanjama. Normalni Finish zahtijeva
odgovarajući provjereni izvoz svakog walleta. Nakon urednog zaustavljanja Corea
ponovno uspoređuje inventar i logičke zapise baze, čisti clipboard te pokreće
postojeći uski systemd teardown i gašenje. Izričita hitna opcija može odbaciti
sesiju bez backupa. Gašenje ne tvrdi da fizički prepisuje RAM.

## Sigurnosne kontrole

| Kontrola | Konkretna implementacija |
| --- | --- |
| Privatni tmpfs | `run-core\\x2dvault.mount`: `noswap,nodev,nosuid,noexec`, UID/GID 1000, mode 0700, limit 50% RAM-a. |
| Core datadir | `/home/vault/.bitcoin`, na bindu privatnog tmpfs-a; uključuje logove, cookie, lockove i konfiguraciju. |
| Core walletdir | `/home/vault/.bitcoin/wallets`; eksplicitni argumenti i `-nosettings`. |
| Nativni Core izvoz | Bubblewrap ima read-only OS/medije i writable samo RAM; provjera prije i unutar izolacije. |
| HOME | Stvarni passwd HOME `/home/vault` bindan je na RAM; podložni diskovni direktorij root-owned, mode 000. |
| XDG i privremene putanje | XDG config/cache/data/state pod RAM HOME-om; TMPDIR/TMP/TEMP `/run/core-vault/tmp`. |
| Sistemski scratch | Instalirani `/tmp`, `/var/tmp`, `/var/log`, CUPS spool/cache i `/media` metapodaci imaju zaštićene tmpfs mountove. Vanjski child mountovi ostaju vanjski filesystemi. |
| Swap | Postojeća no-swap služba prije desktopa, nema instalacijskog swapa; startup odbija svaki aktivni swap. Nije dodan zram. |
| Hibernate/resume | Maskirane sleep/hibernate/suspend target jedinice, sleep/logind politika, `noresume` i initramfs resume isključen. |
| Suspend | Maskiran; normalni tijek završava sesiju i gasi računalo. |
| Dumpovi | `Storage=none`, `ProcessSizeMax=0`, kernel `core_pattern=/dev/null`, suid dumpovi 0, core limiti 0. |
| Journal i logovi | Journald `Storage=volatile`; `/var/log` RAM; maskirani trajni logger/coredump socket. Core log je u RAM datadiru. |
| Recent files | GTK recent isključen; ostalo stanje birača datoteka/desktopa ostaje u RAM HOME-u. Shell history `/dev/null`. |
| Thumbnails/cache | RAM XDG/HOME; nema novog indexera ili clipboard managera. |
| KeePassXC | RAM konfiguracija i stanje, bez update checka/remembered pathova, clipboard 10 s, idle lock 120 s; završetak čisti clipboard. Namjerno spremljeni vanjski KDBX ostaje šifriran na tom mediju. |
| Šifrirani backup | Postojeći Debian 7zip backend; službeni Core snapshot u RAM-u, šifrirani sadržaj/zaglavlje, test i read-back provjera, bez lozinki u argv/env/datotekama. |
| Provjera prije Finish | RAM potvrda izvoza, hash arhive, točno jedan šifrirani neprazni `wallet.dat`, ekstrakcija u RAM i usporedba logičkog SQLite sadržaja; ponovna provjera nakon zaustavljanja. |
| Uništenje i shutdown | Zaustavljanje Corea, LightDM-a i korisničkih procesa, unmount HOME-a i radnog tmpfs-a, fiksni poweroff/reboot pomoćnik, timeout/OnFailure gašenje. |
| Offline rad | Postojeći offline servis/firewall/modul politika; Core bez peer mreže, cookie RPC samo loopback. Nema nove mrežne ovisnosti pri radu. |

Ove kontrole koriste postojeće sistemske jedinice i instalacijski profil.
Shred ostaje pomoćni alat za vanjske datoteke; nije wallet sigurnosni
model. SSD wear leveling, TRIM ili prepisivanje blokova nisu potrebni za
normalni tijek u kojem plaintext nikada nije zapisan na interni disk.

## Značajne promjene u ovom nastavku

Za svaku navedenu `config/includes.chroot` runtime datoteku održana je identična
kopija pod `tools/core-vault/runtime-template`, na istoj relativnoj putanji.
Ranije implementirane jedinice i postojeći backup paket nisu zamijenjeni drugim
paralelnim sustavom. Potpun popis putanja ovog nastavka nalazi se na kraju.

| Datoteka ili grupa | Razlog |
| --- | --- |
| `usr/local/bin/core-vault-bitcoin` | Stvarna Core izolacija i zadržavanje single-instance flocka u bwrap supervisoru. |
| `usr/local/libexec/core-vault-core-session` | Novi unutarnji entrypoint; provjera izolacije, adresirani Hide observer i exec službenog Corea. |
| `usr/lib/core-vault/runtime.py` | Vidljivi mountovi `findmnt --uniq` i kernel `mnt_id`, inventar walleta izvan walletdira, bind aliasi, provjera loaded RPC pokrivenosti i podmountova. |
| `usr/local/bin/core-vault-storage-check` | Core-specifična provjera mount granice prije i nakon ulaska u namespace. |
| `usr/lib/core-vault/export.py` | Backup trenutno učitanog pathlike walleta preko stvarnog RPC imena; bez ponovnog loadanja zaključane baze. |
| `usr/local/bin/core-vault-finish`, `core-vault-wallet-backup` | Odbijanje normalnog završetka/izvoza ako loaded wallet nije pokriven inventarom. |
| `usr/lib/core-vault-installer/target.py`, `core-vault-install-check` | Instalirani `/media` metapodaci u RAM-u i provjera fstab/mount politike; postojeći vanjski child mountovi ostaju sačuvani. |
| `usr/local/bin/core-vault-security-check` | Dijagnostika `/media` i stvarnog Core process-root RO stanja; neuspjela inspekcija prepoznatog Corea ne prolazi. |
| `usr/local/bin/core-vault-guide`, `usr/share/core-vault/shred-policy.json` | Kratke upute za RAM staging i izvoz; usklađen postojeći hash manifest. |
| Oba `core-vault.list.chroot` | Debian dependency `bubblewrap`. |
| Hookovi `0948`, `0950`, `0960` | Executable helper, provjera dependencyja i payload manifesta, novi observer entrypoint. |
| `check-private-session.py`, `check-installer-iso.py` | Doslovna source/ISO usporedba, bwrap payload i stvarni hashovi svih manifest datoteka. |
| `check-core-startup-v4.py`, `check-ui-polish-v4.py`, `check-backup-iso.py` | Provjere dvostupanjskog launchera i postojećih UI/backup očekivanja. |
| `test-private-session.py`, `calamares/tests/test_installer.py` | Negativne mount/inventory provjere i `/media` regresija. |
| `test-core-launcher.py`, `test-core-startup.py` | Stvarni produkcijski launcher s official Coreom, mount odbijanje, nativni RAM backup, jedna instanca i oslobađanje locka. |
| `test-core-wallet-export.py` | Stvarni pathlike wallet, regtest PSBT i restore iz izvorne izvezene `.7z` arhive. |
| `test-ui-polish-v4-qt.py` | Ispravna Finish očekivanja i opcionalni SVG plugin iz provjerenog Debian runtimea. |
| `docs/RAM-PRIVATE-SESSION.md`, ovaj izvještaj | Arhitektura, stvarno izvedeni testovi i nedovršeni finalni prihvat. |

Službeni Bitcoin Core 31.1 nije mijenjan. SHA-256 `bitcoin-qt`:
`fcd4c1a3193e0cb4eec9d980c835d822ad726627b0c01281b13f5c3c1f593fcb`.
Calamares compile inputi nisu promijenjeni ovim nastavkom: aktualni
`3.3.14-1+corevault3` paket prolazi remote prebuild gate. `target.py` se
isporučuje kao uključeni runtime izvor i provjerava odvojeno. Backup paket
`0.5.0` i njegov postojeći PTY/no-overwrite backend ostaju sačuvani.

## Stvarno izvedene provjere

Dokazi: `/home/pavao/vault-test-results/ram-session-20261004/continuation-20261004`.
Testovi koriste sintetičke wallete i lozinke; nisu korišteni stvarni ključevi.

| Provjera | Rezultat i granica |
| --- | --- |
| Privatna sesija | PASS, 19/19; negative swap/disk HOME/inventory/archive/Finish testovi, aktivni i skriveni podmountovi, kernel mount ID i fail-closed metadata provjere (`private19-final.log`). |
| Installer | PASS, 49/49; uključuje `/media` tmpfs, idempotenciju i očuvanje vanjskih child mountova. |
| Stvarni produkcijski launcher | PASS; službeni Core stvara/šifrira wallet i radi nativni backup u RAM-u, odbija native backup/createwallet na simuliranom OS/USB/device odredištu, zadržava jednu instancu i oslobađa lock nakon stopa. Stvarni nested bind odbija prije Corea, skriveni portal zapis ne blokira pozitivan test (`mount-boundary-launcher-final.log`). |
| Regtest i backup/restore | PASS; financiranje sintetičke transakcije, PSBT potpis prihvaćen u Coreu, pathlike wallet izvoz loaded/unloaded, 7zip read-back, wrong-password odbijanje, restore upravo iz izvezene arhive, digest valjan nakon stopa (`regtest-final.log`). |
| Source preflight | PASS, 14/14 (`preflight-summary.json`): backup, private-session, live, media, Home, Files/recovery, Places, Core dijalozi, Shred, BleachBit, startup, menu/progress, UI polish, power/Core. |
| Calamares paket | PASS source i staged-package gate (`package-gate-final.log`, ponovljen nakon posljednje promjene u `mount-boundary-package-final.log`); nije pokrenuta nova kompilacija nepromijenjenih compile inputa. |
| Home GUI regresija | PASS 800×600, 1024×768, 1280×800, 1920×1080: 12 centriranih kartica, footer, hover, stvarne ikone/power hover; routing PASS. |
| Postojeći ISO | Očekivani FAIL: `Stale private session payload in ISO: usr/lib/core-vault/runtime.py` (`stale-iso-final.log`). ISO nije odobren. |

Home GUI test prvo je naišao na nedostajući SVG plugin na razvojnom hostu i
zastarjela tekstualna očekivanja testa. Nakon usklađenja testa, ponovno je
prošao uz `--runtime-root ./chroot`, koristeći plugin postojećeg Debian imagea.
Mjerodavan završni rezultat je `home-qt-verified-runtime-final.log`; povijesni
neuspjeli logovi nisu uklonjeni. Vizualni produkcijski Home kod nije mijenjan.

Launcher fixture zamjenjuje samo installed storage checker označenom RAM
provjerom; stvarna produkcijska mount-child provjera i oba launcher entrypointa
ostaju uključeni. Test potvrđuje Core filesystem granicu, ne installed noswap
flagove, systemd boot redoslijed, stvarni USB ni rad window managera. Regtest
application test simulira klasifikaciju odredišnog medija. Te granice ne
zamjenjuju finalni VM prihvat.

Završna mount-boundary provjera izvora, startup provjera i package gate također
prolaze (`mount-boundary-checks-final.json`). Launcher koristi SHA-256
`d19fa171bd77da114b530607c4f8cbb83f549e9830ebb341f892a49e4004637c`,
unutarnji helper
`a6a69253db36a5bc232e1ae272e7df6fba264757844bad7b157c046c24769331`.
Python syntax provjera prolazi za 29 izmijenjenih source datoteka, shell syntax
za sedam. Prvi preširoki podmount test otkrio je skriveni inherited portal zapis;
nakon kernel-ID popravka završni nativni test prolazi. Raniji neuspjeli log
`mount-boundary-launcher.log` ostaje sačuvan kao razvojni dokaz.

## Izgradnja i preostali prihvat

Postojeći ISO ima 752877568 bajtova i SHA-256
`1449745bada4402a099f8490c40ef0247c87091e2da940114e83db9385f3601f`.
To je prethodni kandidat, ne novi finalni artifact. Remote Desktop Commander
konfiguracija `blockedCommands` izričito blokira `sudo`; postojeći build
skript zahtijeva `sudo lb clean` i `sudo lb build`. Konfiguracija nije mijenjana
niti je blok zaobiđen. Build treba pokrenuti lokalno na razvojnom računalu:

```bash
cd /home/pavao/core-signer-os
bash tools/core-vault/build-live-iso.sh
```

Skript uključuje postojeće preflight, build, installer ISO i private-session
ISO gateove. Nakon uspješne izgradnje treba zamrznuti novi ISO/hash i izvršiti:

1. Zasebnu čistu BIOS i UEFI instalaciju na disposable virtualni interni disk;
   zatim boot bez ISO-a i `core-vault-security-check` unutar Vault sesije.
2. Stvarni wallet create/encrypt, nativni RAM backup, verified `.7z` izvoz na
   zasebni virtualni USB, odspajanje/neispravan backup i oporavak iz arhive.
3. KeePassXC i desktop recent/cache/clipboard putanje, GUI Finish s walletom,
   ponovni boot s praznim HOME/walletdir/state te vizualni startup/installer.
4. Core/GUI crash, namjerni crash testnog procesa i nagli prekid napajanja;
   zatim offline scan cijele ugašene slike internog diska za jedinstveni marker
   i wallet nazive, uključujući obrisane blokove.

Pripremljeni alati: `vm-private-session.py`, `test-installed-private-session.py`
i `scan-vm-private-markers.py`. Kontroler provjerava identitet vlastitog QEMU
procesa/diska; ne upravlja hostom niti korisnikovim stvarnim medijima.
Raniji BIOS/marker test prethodnog kandidata opisan u arhitekturnom dokumentu
ne certificira ovaj kod ni finalni ISO.

## Stvarne granice

- Konačni installed/BIOS/UEFI/USB/Finish/crash/power-loss i raw-disk prihvat još
  nije izvršen za novu sliku; uvjet dovršenosti zadatka zato nije ispunjen.
- Core je write-confined. Ostale aplikacije imaju volatile HOME/cache/tmp,
  ali Files/terminal/archive alati mogu pri namjernoj korisničkoj operaciji
  kopirati plaintext na odabrani zapisivi vanjski medij. To nije globalna
  zabrana svakog ručnog izvoza. Normalni wallet izvoz vodi kroz Wallet Backup.
- Nestanak RAM-a gubi neizvezene promjene; backup mora biti spremljen i ponovno
  provjeren prije normalnog Finish-a. Hard power loss nema priliku za provjeru.
- Normalni verified Finish podržava aktualne descriptor/SQLite wallete;
  nepoznat/legacy format odbija umjesto da ga proglasi sigurnim za uništenje.
- Novi model ne briše stare tragove koje je ranija verzija već mogla zapisati
  na interni disk. Live RAM acquisition i kompromitirani firmware/OS nisu
  pokriveni ovim modelom.

## Potpuni popis izmijenjenih putanja ovog nastavka

Popis se uspoređuje s početnim izvorima pročitanima s razvojnog računala;
uključuje runtime-template parove i nove datoteke, bez ranijih tuđih izmjena.

```text
config/hooks/live/0948-core-vault-private-session.hook.chroot
config/hooks/live/0950-core-vault-installer-check.hook.chroot
config/hooks/live/0960-core-vault-sync-accessibility.hook.chroot
config/includes.chroot/usr/lib/core-vault-installer/target.py
config/includes.chroot/usr/lib/core-vault/export.py
config/includes.chroot/usr/lib/core-vault/runtime.py
config/includes.chroot/usr/local/bin/core-vault-bitcoin
config/includes.chroot/usr/local/bin/core-vault-finish
config/includes.chroot/usr/local/bin/core-vault-guide
config/includes.chroot/usr/local/bin/core-vault-install-check
config/includes.chroot/usr/local/bin/core-vault-security-check
config/includes.chroot/usr/local/bin/core-vault-storage-check
config/includes.chroot/usr/local/bin/core-vault-wallet-backup
config/includes.chroot/usr/local/libexec/core-vault-core-session
config/includes.chroot/usr/share/core-vault/shred-policy.json
config/package-lists/core-vault.list.chroot
tools/core-vault/calamares/tests/test_installer.py
tools/core-vault/check-backup-iso.py
tools/core-vault/check-core-startup-v4.py
tools/core-vault/check-installer-iso.py
tools/core-vault/check-private-session.py
tools/core-vault/check-ui-polish-v4.py
tools/core-vault/docs/RAM-BOUNDARY-REVIEW-20261004.md
tools/core-vault/docs/RAM-PRIVATE-SESSION.md
tools/core-vault/manifests/core-vault.list.chroot
tools/core-vault/runtime-template/usr/lib/core-vault-installer/target.py
tools/core-vault/runtime-template/usr/lib/core-vault/export.py
tools/core-vault/runtime-template/usr/lib/core-vault/runtime.py
tools/core-vault/runtime-template/usr/local/bin/core-vault-bitcoin
tools/core-vault/runtime-template/usr/local/bin/core-vault-finish
tools/core-vault/runtime-template/usr/local/bin/core-vault-guide
tools/core-vault/runtime-template/usr/local/bin/core-vault-install-check
tools/core-vault/runtime-template/usr/local/bin/core-vault-security-check
tools/core-vault/runtime-template/usr/local/bin/core-vault-storage-check
tools/core-vault/runtime-template/usr/local/bin/core-vault-wallet-backup
tools/core-vault/runtime-template/usr/local/libexec/core-vault-core-session
tools/core-vault/runtime-template/usr/share/core-vault/shred-policy.json
tools/core-vault/test-core-launcher.py
tools/core-vault/test-core-startup.py
tools/core-vault/test-core-wallet-export.py
tools/core-vault/test-private-session.py
tools/core-vault/test-ui-polish-v4-qt.py
```
