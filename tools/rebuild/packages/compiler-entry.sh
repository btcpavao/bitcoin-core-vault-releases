#!/bin/bash
# Recover the reviewed historical source-bearing package used by the compiler
# recipe and its report from v0.5.0's release source snapshot.
set -euo pipefail
case "$1" in
  calamares) file=calamares_3.3.14-1+corevault4_amd64.deb ;;
  thunar) file=thunar_4.20.2-1+deb13u1+corevault1_amd64.deb ;;
  *) exit 2 ;;
esac
mkdir /historical
snapshot=/tmp/vault-0.5.0-source.tar.gz
curl --fail --silent --show-error --location --retry 4 \
    https://github.com/btcpavao/bitcoin-core-vault-releases/releases/download/v0.5.0/bitcoin-core-vault-v0.5.0-source.tar.gz \
    -o "$snapshot"
printf '%s  %s\n' 2d9f7e3b9b9af07ad366a5c2cd8ed8d6f532340ecd308134cada01d8321fd99a "$snapshot" | sha256sum --check
tar -xzOf "$snapshot" "bitcoin-core-vault-v0.5.0-source/config/packages.chroot/$file" > "/historical/$file"
export VAULT_HISTORICAL_PACKAGES=/historical
exec bash /src/tools/rebuild/packages/build.sh "$1"
