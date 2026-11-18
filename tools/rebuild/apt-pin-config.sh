#!/bin/bash
# Emit a build-only APT hook that checks the local indexes used by the solver.
set -euo pipefail
here=$(dirname "$0")
source "$here/inputs.env"
[[ $SNAPSHOT =~ ^[0-9]{8}T[0-9]{6}Z$ ]]
echo 'APT::Update::Error-Mode "any";'
while read -r digest index; do
    case "$index" in
        trixie.InRelease|trixie-updates.InRelease) archive=debian ;;
        trixie-security.InRelease) archive=debian-security ;;
        *) exit 1 ;;
    esac
    [[ $digest =~ ^[0-9a-f]{64}$ ]]
    path="/var/lib/apt/lists/snapshot.debian.org_archive_${archive}_${SNAPSHOT}_dists_${index%.InRelease}_InRelease"
    printf 'APT::Update::Post-Invoke { "echo %s  %s | sha256sum --check --status"; };\n' "$digest" "$path"
done < "$here/InRelease.sha256"
