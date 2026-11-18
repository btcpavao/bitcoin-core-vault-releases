#!/bin/bash
# Rebuild the exact hardware-tested Vault v0.8.0 release.
set -euo pipefail
umask 022
root=$(git -C "$(dirname "$0")" rev-parse --show-toplevel)
base_revision=8bbb8b76b98c7b879b7fe1a62bb51e1568d82a10
runtime_revision=0103f0fde7695156a50ebf2c2ee5966aafc5101e
base_digest=d88a386619a1654d62504606385f993823a931c13d59c1cb680a17b6083837ce
release_digest=0bc142508a35172ea92f645decc31be1373b05956e9a17d0ad01cee9bab84857
docker_command=(docker)
base_options=()
base_iso=
if [[ ${1:-} == --sudo-docker ]]; then
    docker_command=(sudo docker)
    base_options=(--sudo-docker)
    shift
fi
if [[ ${1:-} == --base-iso && $# -ge 2 ]]; then
    base_iso=$(realpath -e -- "$2")
    shift 2
fi
if [[ $# != 1 ]]; then
    echo "Usage: bash tools/rebuild/build-release.sh [--sudo-docker] [--base-iso VERIFIED_BASE_ISO] NEW_OUTPUT_DIRECTORY" >&2
    exit 2
fi
output=$(realpath -m -- "$1")
[[ ! -e $output && ! -L $1 ]] || { echo 'The output already exists.' >&2; exit 1; }
cd "$root"
revision=$(git rev-parse HEAD)
git diff --quiet HEAD || { echo 'Commit tracked changes before building.' >&2; exit 1; }
git cat-file -e "$base_revision^{commit}" || { echo 'The release requires the full Git history.' >&2; exit 1; }
git diff --quiet "$runtime_revision" "$revision" -- config || { echo 'The checkout differs from the v0.8.0 runtime.' >&2; exit 1; }
source tools/rebuild/inputs.env
work=$(mktemp -d -- "$(dirname "$output")/.vault-release-XXXXXXXX")
container=
cleanup() {
    if [[ -n $container ]]; then "${docker_command[@]}" rm -f "$container" >/dev/null || true; fi
    rm -rf -- "$work"
}
trap cleanup EXIT
if [[ -z $base_iso ]]; then
    git clone --quiet --no-checkout --local -- "$root" "$work/base-source"
    git -C "$work/base-source" checkout --quiet --detach "$base_revision"
    bash "$work/base-source/tools/rebuild/build.sh" "${base_options[@]}" "$work/base-result"
    base_iso=$work/base-result/bitcoin-core-vault-amd64.iso
fi
printf '%s  %s\n' "$base_digest" "$base_iso" | sha256sum --strict --check
git -c tar.umask=0022 archive --format=tar "$revision" > "$work/source.tar"
container=$("${docker_command[@]}" create --platform linux/amd64 \
    --mount "type=bind,source=$work/source.tar,target=/source.tar,readonly" \
    --mount "type=bind,source=$base_iso,target=/base.iso,readonly" \
    "$BUILDER_IMAGE" /bin/bash -ec 'mkdir /src; tar --no-same-owner -xf /source.tar -C /src; exec bash /src/tools/rebuild/finish-release-inside.sh')
"${docker_command[@]}" start --attach "$container"
[[ $("${docker_command[@]}" inspect --format '{{.State.ExitCode}}' "$container") == 0 ]]
mkdir "$work/result"
"${docker_command[@]}" cp "$container:/evidence/." - |
    tar --no-same-owner --no-same-permissions -xf - -C "$work/result"
(cd "$work/result" && printf '%s  bitcoin-core-vault-amd64.iso\n' "$release_digest" > SHA256SUMS && sha256sum --strict --check SHA256SUMS)
printf 'source_commit=%s\nruntime_commit=%s\nbase_commit=%s\nbase_sha256=%s\nbuilder_image=%s\ndebian_snapshot=%s\nsource_date_epoch=%s\n' \
    "$revision" "$runtime_revision" "$base_revision" "$base_digest" "$BUILDER_IMAGE" "$SNAPSHOT" "$SOURCE_DATE_EPOCH" > "$work/result/build-inputs.txt"
if [[ -d $work/base-result ]]; then
    mkdir "$work/result/clean-base"
    rm -- "$base_iso"
    mv "$work/base-result"/* "$work/result/clean-base/"
fi
mv -T --no-clobber -- "$work/result" "$output"
[[ ! -e $work/result ]] || { echo 'A concurrent process created the output directory.' >&2; exit 1; }
