#!/bin/bash
# Start a clean compiler for one native package. Arguments are internal to the builder.
set -euo pipefail
umask 022
kind=${1:?package name}
archive=${2:?absolute path to committed source tar}
output=${3:?new output directory}
case "$kind" in thunar|calamares) ;; *) exit 2 ;; esac
[[ -f "$archive" && ! -e "$output" && ! -L "$output" ]]
docker_command=(docker)
if [[ ${VAULT_SUDO_DOCKER:-0} == 1 ]]; then docker_command=(sudo docker); fi
source "$(dirname -- "$0")/inputs.env"
container=
cleanup() {
    if [[ -n $container ]]; then "${docker_command[@]}" rm -f "$container" >/dev/null || true; fi
}
trap cleanup EXIT
container=$("${docker_command[@]}" create --platform linux/amd64 --hostname native-builder \
    --mount "type=bind,source=$archive,target=/source.tar,readonly" --env "NATIVE_KIND=$kind" \
    "$BUILDER_IMAGE" /bin/bash -ec '
        mkdir /src /evidence
        tar --no-same-owner --no-same-permissions -xf /source.tar -C /src
        exec bash /src/tools/rebuild/packages/compiler-entry.sh "$NATIVE_KIND"
    ')
"${docker_command[@]}" start --attach "$container"
[[ $("${docker_command[@]}" inspect --format '{{.State.ExitCode}}' "$container") == 0 ]]
mkdir -- "$output"
"${docker_command[@]}" cp "$container:/evidence/." - |
    tar --no-same-owner --no-same-permissions -xf - -C "$output"
(cd "$output" && sha256sum --check SHA256SUMS)
