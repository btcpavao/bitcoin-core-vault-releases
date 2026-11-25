#!/bin/bash
# Start a clean compiler for one native package. Arguments are internal to the builder.
set -euo pipefail
umask 022
kind=${1:?package name}
archive=${2:?absolute path to committed source tar}
output=${3:?new output directory}
case "$kind" in thunar|calamares) ;; *) exit 2 ;; esac
[[ -f "$archive" && ! -e "$output" && ! -L "$output" ]]
# This historical clean native recipe still emits corevault6. Fail before Docker
# rather than compiling an older package and presenting it as a current rebuild.
# Functional image assembly with the reviewed packages is documented separately.
if [[ $kind == calamares ]]; then
    python3 - "$archive" <<'NATIVE_VERSION'
import json, sys, tarfile
with tarfile.open(sys.argv[1], "r:*") as source:
    member = source.getmember("tools/core-vault/calamares/input-bundle.json")
    if not member.isfile() or member.size > 131072:
        raise SystemExit("Invalid Calamares input manifest in source archive.")
    with source.extractfile(member) as stream:
        version = json.load(stream).get("local_version")
if version != "3.3.14-1+corevault6":
    raise SystemExit(
        "Historical native recipe supports Calamares 3.3.14-1+corevault6, "
        f"but this source pins {version!r}. No native rebuild was performed. "
        "See docs/NATIVE-REBUILD.md for the matching source companion and "
        "docs/REBUILD.md for functional image assembly and reproducibility limits.")
NATIVE_VERSION
fi
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
