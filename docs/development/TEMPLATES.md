# Small development templates

Vault maintains this canonical document; Node carries a verbatim mirror identified by the shared-document provenance record. Copy only the fields useful for the task. Link existing evidence instead of repeating it.

## Module contract

- **Module / product:** name; Vault, Node or explicitly shared consumers.
- **Purpose and behavior:** user-visible actions, defaults, states and relevant error/cancel behavior.
- **Authoritative source / generated consumers:** paths and generation/install command or existing documentation.
- **Interfaces and dependencies:** commands, services, paths, formats, permissions and dependent modules.
- **Data and boundaries:** persistent/temporary data touched; ownership; assumptions to preserve.
- **Evidence:** source revision, artifact/build, inspection or runtime environment and date.
- **Known issues / relevant checks:** links to current issues, regression scenarios and existing commands.

## Change record

- **Request / intended result:** one concrete behavior and its reason.
- **Starting point:** product, repository, branch/commit, local changes and candidate reference.
- **Scope and dependencies:** module(s), authoritative files and generated consumers.
- **Data / delivery impact:** migration, restart, package or ISO implications; “none” when established.
- **Verification:** relevant existing checks and acceptance scenario; result/evidence after execution.
- **Documentation / remaining work:** contracts or status updated; unresolved limitations.

## Release or candidate record

- **Identity / status:** product, version/build ID; candidate, checked candidate or published release.
- **Artifact:** exact filename, size, SHA-256 and location/release URL.
- **Source:** commit plus any exact saved patch/source snapshot and hash.
- **Build inputs:** build tooling/configuration and package manifest/snapshot references.
- **Changes / compatibility:** release notes, settings/data impact, supported delivery and rollback limits.
- **Checks:** source, staging, final artifact, VM and hardware evidence; identify unperformed checks.
- **Publication:** checksum/signature references, verification result and matching download links.
- **Known limitations:** open issues and environment-specific qualification.

Keep completed release evidence unchanged. Record later corrections explicitly rather than silently changing what the release was said to contain.

## Tester report

- **Product and exact build:** version shown, ISO filename and SHA-256 if available.
- **Machine / boot:** model, relevant hardware, firmware mode, live or installed; storage layout if relevant.
- **Steps:** shortest reproducible sequence, including relevant settings.
- **Expected / observed:** concrete behavior and whether it repeats.
- **Evidence:** screenshot and relevant sanitized log excerpt; time of occurrence if useful.
- **Impact / workaround:** blocked task, data impact and any successful workaround.

Do not attach wallet files, keys, passphrases, descriptors or Wi-Fi credentials. Request only logs needed for the reported problem and check them for sensitive content.

## Handoff / resume note

- **Task and current source:** scope, branch/commit and uncommitted work.
- **Completed:** behavior and authoritative/generated files changed.
- **Verified:** exact checks and artifact/environment references.
- **Pending or blocked:** concrete remaining work, failed/unperformed checks and known constraints.
- **Next step:** exact relevant path or command and expected result.
- **Read next:** current state, affected module and evidence links only.

A handoff records actual progress. It does not turn proposed work into completed work or supersede the current repository state.
