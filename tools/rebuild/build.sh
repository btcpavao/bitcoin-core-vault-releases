#!/bin/bash
# Run on a disposable amd64 Linux build computer with Docker and Git.
set -euo pipefail
umask 022
root=$(git -C "$(dirname -- "$0")" rev-parse --show-toplevel)
cd "$root"
docker_command=(docker)
if [[ ${1:-} == --sudo-docker ]]; then
    docker_command=(sudo docker)
    export VAULT_SUDO_DOCKER=1
    shift
fi
if (( $# != 1 )); then echo 'Usage: bash tools/rebuild/build.sh [--sudo-docker] NEW_OUTPUT_DIRECTORY' >&2; exit 2; fi
if [[ -e $1 || -L $1 ]]; then echo 'Output already exists. Use a new path.' >&2; exit 1; fi
git diff --quiet HEAD -- || { echo 'Tracked files have local edits. Commit or use a fresh checkout.' >&2; exit 1; }
source tools/rebuild/inputs.env
revision=$(git rev-parse --verify HEAD)
stage=$(mktemp -d)
container=
cleanup() {
    if [[ -n $container ]]; then "${docker_command[@]}" rm -f "$container" >/dev/null || true; fi
    rm -rf -- "$stage"
}
trap cleanup EXIT
git -c tar.umask=0022 archive --format=tar "$revision" > "$stage/source.tar"
mkdir "$stage/native"
for package in calamares thunar; do
    bash tools/rebuild/compile-package.sh "$package" "$stage/source.tar" "$stage/native/$package"
done
# Only committed files enter /work. The container sees no writable host directory.
container=$("${docker_command[@]}" create --platform linux/amd64 --hostname vault-builder \
    --cap-add SYS_ADMIN --security-opt seccomp=unconfined --security-opt apparmor=unconfined \
    --security-opt systempaths=unconfined --env "VAULT_REVISION=$revision" \
    --mount "type=bind,source=$stage/source.tar,target=/source.tar,readonly" \
    --mount "type=bind,source=$stage/native,target=/verified-native,readonly" \
    "$BUILDER_IMAGE" /bin/bash -ec \
    'mkdir /work; cd /work; tar --no-same-owner --no-same-permissions -xf /source.tar; exec bash tools/rebuild/inside.sh')
"${docker_command[@]}" start --attach "$container"
[[ $("${docker_command[@]}" inspect --format '{{.State.ExitCode}}' "$container") == 0 ]]
mkdir -- "$1"
"${docker_command[@]}" cp "$container:/evidence/." - | tar --no-same-owner --no-same-permissions -xf - -C "$1"
(cd "$1" && sha256sum --check SHA256SUMS)
