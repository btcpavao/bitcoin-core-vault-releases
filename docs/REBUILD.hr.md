# Kako samostalno izgraditi i provjeriti Bitcoin Core Vault

Možeš provjeriti što preuzimaš na dva načina. Čitanjem izvornog koda vidiš koje su datoteke i postavke autori promijenili. Izgradnjom na vlastitom računalu od tih izvora dobiješ ISO koji možeš usporediti sa službenim preuzimanjem. Za usporedbu se koristi SHA-256, otisak cijele datoteke. I jedan promijenjeni bajt mijenja taj otisak.

**Koju verziju mogu provjeriti?** Vault v0.5.0 ima potpisan popis otisaka i javne izvore u reviziji `723d3a8957e86a06853e3ac059159c71174f3c50`. Taj je ISO izvorno nastao preradom ranije lokalne slike. Novi postupak ispod kreće od Debianovih paketa i projektnih datoteka te gradi kandidata za sljedeće izdanje. Za potvrdu podudaranja treba provjeriti isti konkretni rezultat na oba računala.

Dva odvojena računala na GitHubu izgradila su bajt po bajt jednak ISO za javni kandidat `rebuild-candidate-9f466c5df912`. [Preuzimanje, točan commit, očekivani SHA-256 i zapis usporedbe](rebuilds/9f466c5df912.md).

## 1. Pripremi odvojeno računalo

Treba ti Linux na 64-bitnom Intelovu ili AMD-ovu računalu. Može poslužiti i nova Linux virtualna mašina s približno 30 GiB slobodnog prostora. Pokretanje gradnje ne traži fizički USB, wallet, Bitcoin ni privatni ključ. Koristiš terminal i internetsku vezu za preuzimanje provjerenih ulaza.

Na novoj Debian 13 virtualnoj mašini možeš instalirati Git i Docker ovako:

```bash
sudo apt update
sudo apt install git docker.io gnupg
sudo systemctl start docker
sudo docker run --rm hello-world
```

Zadnja naredba treba ispisati `Hello from Docker!`. Ako tvoj račun već može koristiti Docker, istu provjeru možeš pokrenuti bez `sudo`.

## 2. Preuzmi točnu reviziju

*Commit* je spremljeno stanje projekta. Njegova puna oznaka ima 40 znakova i određuje točne datoteke koje ćeš graditi. Kod objavljenog izdanja preuzmi oznaku iz potpisanog zapisa o gradnji. Kod probne verzije skopiraj punu oznaku iz kartice **Commits** u prijedlogu izmjene na GitHubu. Zatim pokreni ovaj blok i na upit zalijepi oznaku.

```bash
git clone https://github.com/btcpavao/bitcoin-core-vault-releases.git vault-source
cd vault-source
read -r -p 'Puna oznaka commita koji provjeravaš: ' revision
git switch --detach "$revision" && git rev-parse HEAD
```

Usporedi ispisanih 40 znakova s oznakom koju želiš provjeriti. Ako se prvi put susrećeš s porukom o `detached HEAD`, ona znači da gledaš točno spremljeno stanje umjesto grane koja se može mijenjati.

## 3. Pogledaj što se mijenjalo

Za usporedbu s objavljenim Vaultom v0.5.0 koristi njegovu poznatu reviziju. Nakon budućeg izdanja možeš na isti način unijeti reviziju prethodnog potpisanog izdanja.

```bash
previous=723d3a8957e86a06853e3ac059159c71174f3c50
git diff --stat "$previous" HEAD
git diff "$previous" HEAD
```

Prva naredba prikazuje popis promijenjenih datoteka. Druga prikazuje konkretne promjene po redcima. Razmaknica lista dalje, a tipka **q** vraća te u terminal. U `config/` su postavke i datoteke koje se uključuju u sustav. U `tools/` su postupci gradnje, provjere i dio izvornog koda. Kod datoteka koje Git označi kao `Binary files differ`, pregled uključuje i njihov izvor. Primjerice, javni paket Thunara sadrži njegov poseban izvorni paket, a uz Vault v0.5.0 može se preuzeti zaseban izvor izmijenjenog Calamaresa.

## 4. Izgradi svoj ISO

U terminalu koristi jednu od sljedeće dvije naredbe, ovisno o tome kako si u prvom koraku pokrenuo Docker.

```bash
# Ako je docker run radio bez sudo:
bash tools/rebuild/build.sh ../vault-result
```

```bash
# Ako je na novoj virtualnoj mašini Docker zahtijevao sudo:
bash tools/rebuild/build.sh --sudo-docker ../vault-result
```

Pričekaj završetak. Izgradnja preuzima Debianove pakete iz točno određene snimke arhive, provjerava potpise i otiske te sastavlja cijeli sustav. Na kraju u ispisu treba pisati `bitcoin-core-vault-amd64.iso: OK`. Za ponavljanje koristi novo ime direktorija.

```bash
cat ../vault-result/build-inputs.txt
cat ../vault-result/SHA256SUMS
```

Sačuvaj izgrađeni ISO, otisak, zapis o korištenim ulazima i popis paketa. Vrijednost `source_commit` u zapisu treba biti jednaka oznaci iz drugog koraka.

## 5. Usporedi cijeli ISO

**Ako provjeravaš kandidata**, druga osoba pokrene korake 1–4 na svom računalu s istim commitom. Razmijenite SHA-256. Ako imaš i njezinu datoteku, možeš usporediti svaki bajt. Ovaj primjer pretpostavlja da je druga datoteka spremljena kao `../drugi-vault.iso`.

```bash
sha256sum ../vault-result/bitcoin-core-vault-amd64.iso ../drugi-vault.iso
cmp -- ../vault-result/bitcoin-core-vault-amd64.iso ../drugi-vault.iso && echo 'ISO datoteke su jednake.'
```

**Ako provjeravaš objavljeno izdanje**, preuzmi njegov ISO, `SHA256SUMS`, `SHA256SUMS.asc` i `btcpavao-pgp.asc` u direktorij `release` pokraj `vault-source`. Puni otisak Pavaova PGP ključa za v0.5.0 glasi `787A 2AAF B0D1 19CA 0522 B2A5 B9C9 9AF8 5788 96D0`. Puni otisak za izdanje koje provjeravaš potvrdi zasebnim kanalom kojem već vjeruješ, primjerice izravno s Pavaom.

```bash
cd ../release
keyring=$(mktemp -d)
gpg --homedir "$keyring" --show-keys --with-fingerprint btcpavao-pgp.asc
```

Kad potvrdiš otisak ključa, pokreni ovaj blok u Bashu. Zahtijeva upravo jedan ISO u direktoriju `release`. Provjerava potpis, zatim računa SHA-256 za **obje** datoteke i uspoređuje ih bajt po bajt.

```bash
(
  set -euo pipefail
  shopt -s nullglob
  isos=(*.iso)
  [[ ${#isos[@]} == 1 ]] || { echo 'Ovdje treba biti jedan preuzeti ISO.'; exit 1; }
  read -r -p 'Puni PGP otisak koji si neovisno potvrdio: ' trusted
  trusted=${trusted//[[:space:]]/}
  [[ ${trusted^^} =~ ^[0-9A-F]{40}$ ]]
  actual=$(gpg --homedir "$keyring" --batch --with-colons --show-keys btcpavao-pgp.asc |
    awk -F: '$1=="pub" { primary=1; next } primary && $1=="fpr" { print $10; primary=0 }')
  [[ $actual == "${trusted^^}" ]]
  gpg --homedir "$keyring" --batch --dearmor --output "$keyring/confirmed.gpg" btcpavao-pgp.asc
  gpg --homedir "$keyring" --batch --no-default-keyring --keyring "$keyring/confirmed.gpg" \
    --no-auto-key-retrieve --verify SHA256SUMS.asc SHA256SUMS
  expected=$(awk -v name="${isos[0]}" '($2 == name || $2 == "*" name) { print $1 }' SHA256SUMS)
  [[ $expected =~ ^[[:xdigit:]]{64}$ ]]
  printf '%s  %s\n' "$expected" "${isos[0]}" | sha256sum --check
  printf '%s  %s\n' "$expected" ../vault-result/bitcoin-core-vault-amd64.iso | sha256sum --check
  cmp -- "${isos[0]}" ../vault-result/bitcoin-core-vault-amd64.iso
  echo 'Potpisano izdanje i moj ISO jednaki su do zadnjeg bajta.'
)
```

Ako provjera pokaže razliku, zapiši oba otiska, commit i prvu pogrešku iz terminala. Sačuvaj obje slike za tehničku usporedbu. Alat `diffoscope` može pokazati razlike unutar ISO datoteka. Podudaranje potvrđuje koje su se datoteke proizvele iz tih ulaza. Za procjenu sigurnosti pregledaj i što programi zaista rade.

## Primjer pitanja za LLM

> Pratim upute za gradnju Bitcoin Core Vaulta. Stao sam na koraku 3. Ovo je javni ispis naredbe git diff. Molim te, objasni koje promjene utječu na instalirani sustav, gdje se provjeravaju Debianovi paketi i koju bih jednu datoteku trebao pročitati sljedeću. Ako se nešto ne može zaključiti iz ispisa, navedi što nedostaje.

LLM-u pošalji javni ispis, commit ili dio koda. Za provjeru gradnje dovoljni su javni podaci.
