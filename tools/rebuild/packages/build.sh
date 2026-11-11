#!/bin/bash
# Run in a new amd64 container of the image pinned in tools/rebuild/inputs.env.
set -euo pipefail
umask 022
kind=${1:?Pass calamares or thunar}
case "$kind" in calamares|thunar) ;; *) exit 2 ;; esac
[[ -d /src && -d /evidence && ! -e /build/native ]]
source /src/tools/rebuild/inputs.env
export SOURCE_DATE_EPOCH TZ=UTC LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONHASHSEED=0
export DEBIAN_FRONTEND=noninteractive
mkdir -p /build/native /evidence
cd /build/native
archive="https://snapshot.debian.org/archive/debian/$SNAPSHOT"
security="https://snapshot.debian.org/archive/debian-security/$SNAPSHOT"
for suite in trixie trixie-updates trixie-security; do
    mirror=$archive
    if [[ $suite == trixie-security ]]; then mirror=$security; fi
    curl --fail --location --retry 4 --silent --show-error -o "$suite.InRelease" "$mirror/dists/$suite/InRelease"
done
sha256sum --check /src/tools/rebuild/InRelease.sha256
rm -f /etc/apt/sources.list.d/debian.sources
key=/usr/share/keyrings/debian-archive-keyring.gpg
for suite in trixie trixie-updates trixie-security; do
    mirror=$archive
    if [[ $suite == trixie-security ]]; then mirror=$security; fi
    printf 'deb [check-valid-until=no signed-by=%s] %s %s main\n' "$key" "$mirror" "$suite"
    printf 'deb-src [check-valid-until=no signed-by=%s] %s %s main\n' "$key" "$mirror" "$suite"
done > /etc/apt/sources.list
if [[ $kind == thunar ]]; then
    # Older entries supply the precise private-prefix package versions in the archived manifest.
    for pair in 'debian trixie' 'debian-security trixie-security'; do
        read -r group suite <<<"$pair"
        mirror="https://snapshot.debian.org/archive/$group/20261004T120000Z"
        printf 'deb [check-valid-until=no signed-by=%s] %s %s main\n' "$key" "$mirror" "$suite" >> /etc/apt/sources.list
    done
fi
apt-get -o Acquire::Retries=4 update
apt-get install -y --no-install-recommends build-essential dpkg-dev fakeroot ca-certificates xz-utils python3 file
if [[ $kind == calamares ]]; then
    original=/src/config/packages.chroot/calamares_3.3.14-1+corevault4_amd64.deb
    echo "2aee74ce7ac20ae2fefe40b3a2c4c196ed79170b97d36b9d4d56976c7a650227  $original" | sha256sum --check
    curl --fail --location --retry 4 -o companion.tar.xz 'https://github.com/btcpavao/bitcoin-core-vault-releases/releases/download/v0.5.0/bitcoin-core-vault-v0.4.0-calamares-source.tar.xz'
    echo '62faea95f14b7d4314931d434fb647ee51e9430d7b83154681615487dddf8e6d  companion.tar.xz' | sha256sum --check
    tar -xOJf companion.tar.xz bitcoin-core-vault-v0.4.0-calamares-source/historical/patched-calamares-main-source.tar.gz > actual-source.tar.gz
    echo 'de3a01497ef80f2ada39ed9dbcee0478beea8a5386665293d4c9dd8b98c2c9f8  actual-source.tar.gz' | sha256sum --check
    tar --no-same-owner -xzf actual-source.tar.gz
    apt-get build-dep --no-install-recommends -y ./source
    (
        cd source
        export DEB_BUILD_OPTIONS='nocheck parallel=2'
        dpkg-buildpackage -us -uc -B -j2
    )
    cp calamares_3.3.14-1_amd64.deb /evidence/calamares-rebuilt.deb
    cp ./*.buildinfo /evidence/
else
    original=/src/config/packages.chroot/thunar_4.20.2-1+deb13u1+corevault1_amd64.deb
    echo "1cf16b20f4b72e9bf0c4cee76630e51d72bf3026057269df193d724a29f7cbf5  $original" | sha256sum --check
    dpkg-deb -x "$original" archived
    doc=$PWD/archived/usr/share/doc/thunar/core-vault-source
    echo "1136ba32c8a8c9e7ea4b31115dfa8afa523dd3c46e91330943b5d8c85a02b6e8  $doc/Thunar-core-vault-source.tar.xz" | sha256sum --check
    apt-get build-dep --no-install-recommends -y thunar=4.20.2-1+deb13u1
    apt-get install -y --no-install-recommends thunar=4.20.2-1+deb13u1
    tools=/src/tools/core-vault/thunar
    python3 "$tools/prepare-private-prefix.py" "$doc/deps-manifest.json" "$PWD/dependencies"
    mkdir source
    tar --no-same-owner --strip-components=1 -xJf "$doc/Thunar-core-vault-source.tar.xz" -C source
    python3 "$tools/build-thunar.py" "$PWD/source" "$PWD/dependencies/prefix" --jobs 2
    python3 "$tools/test-dispatch.py" "$PWD/source" "$PWD/dependencies/prefix" "$PWD/test-output"
    strip --strip-unneeded source/thunar/.libs/thunar
    stock=dependencies/debs/thunar_4.20.2-1+deb13u1_amd64.deb
    echo "7aadd1f69704d80b54ce3e08fd57bdeb62592df8eeffa7b9a1e853553e54efc1  $stock" | sha256sum --check
    dpkg-deb -R "$stock" package
    install -m 0755 source/thunar/.libs/thunar package/usr/bin/thunar
    cp -a "$doc" package/usr/share/doc/thunar/
    # Preserve the published source records. The adjacent report describes this new build.
    sed -i 's/^Version: 4.20.2-1+deb13u1$/Version: 4.20.2-1+deb13u1+corevault1/' package/DEBIAN/control
    (
        cd package
        find . -type f ! -path './DEBIAN/*' -printf '%P\0' | sort -z | xargs -0 md5sum > DEBIAN/md5sums
    )
    dpkg-deb --root-owner-group --build package /evidence/thunar-rebuilt.deb
fi
dpkg-query -W -f='${binary:Package}\t${Version}\n' | sort > /evidence/compiler-environment.tsv
dpkg-deb -x "$original" expected
dpkg-deb -x "/evidence/$kind-rebuilt.deb" rebuilt
for tree in expected rebuilt; do
    file "$tree/usr/bin/$kind"
    readelf -n "$tree/usr/bin/$kind" > "/evidence/$tree-$kind-notes.txt"
    cp "$tree/usr/bin/$kind" "/evidence/$tree-$kind.elf"
done
python3 /src/tools/rebuild/packages/report.py "$kind" "$original"
(cd /evidence && sha256sum "$kind-rebuilt.deb" "rebuilt-$kind.elf" > SHA256SUMS)
