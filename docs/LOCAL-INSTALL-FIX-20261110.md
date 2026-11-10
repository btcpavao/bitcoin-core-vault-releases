# Local Vault installer manifest repair

The Guide and RAM-warning remasters retained the v0.4.0 installer-payload.json.
Three changed files (Guide launcher/visuals and Home) retained old hashes, while
guide_content.py and ram_notice.py were not recorded. Live boot does not execute
the installed-target payload verifier, so its smoke test missed this packaging
error. The installed-target verifier correctly refused the stale manifest.

Regenerate the manifest with the canonical 0950 hook after all payload edits,
not during installation. Before doing so, validate every unchanged old record
and compare the five expected updated/new source paths with the frozen source.
Then run the exact-image check-installer-iso.py gate and real installation.
The installed-target hash validation, Core, GPG and session policy are unchanged.

Build gates now require every shipped core-vault Python module in the installed
manifest, plus root ownership/modes for the manifest and new Guide/RAM modules.
Future local images must pass the inner manifest gate as well as outer ISO hashes.
