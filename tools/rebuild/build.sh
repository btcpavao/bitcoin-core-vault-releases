#!/bin/bash
# Run on a disposable amd64 Linux build computer with Docker and Git.
set -euo pipefail
umask 022
root=$(git -C "$(dirname -- "$0")" rev-parse --show-toplevel)
cd "$root"
if (( $# != 1 )); then echo 'Usage: bash tools/rebuild/build.sh NEW_OUTPUT_DIRECTORY' >&2; exit 2; fi
if [[ -e $1 || -L $1 ]]; then echo 'Output already exists. Use a new path.' >&2; exit 1; fi
git diff --quiet HEAD -- || { echo 'Tracked files have local edits. Commit or use a fresh checkout.' >&2; exit 1; }
source tools/rebuild/inputs.env
revision=$(git rev-parse --verify HEAD)
stage=$(mktemp -d)
container=
cleanup() {
    if [[ -n $container ]]; then docker rm -f "$container" >/dev/null || true; fi
    rm -rf -- "$stage"
}
trap cleanup EXIT
git archive --format=tar "$revision" > "$stage/source.tar"
# Only committed files enter /work. The container sees no writable host directory.
container=$(docker create --platform linux/amd64 --hostname vault-builder \
    --cap-add SYS_ADMIN --security-opt seccomp=unconfined --security-opt apparmor=unconfined \
    --security-opt systempaths=unconfined --env "VAULT_REVISION=$revision" \
    --mount "type=bind,source=$stage/source.tar,target=/source.tar,readonly" \
    "$BUILDER_IMAGE" /bin/bash -ec \
    'mkdir /work; cd /work; tar --no-same-owner -xf /source.tar; exec bash tools/rebuild/inside.sh')
docker start --attach "$container"
[[ $(docker inspect --format '{{.State.ExitCode}}' "$container") == 0 ]]
mkdir -- "$1"
docker cp "$container:/evidence/." "$1"
(cd "$1" && sha256sum --check SHA256SUMS)
