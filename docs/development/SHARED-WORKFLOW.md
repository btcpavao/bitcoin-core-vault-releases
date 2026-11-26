# Shared development workflow

This is the common working standard for Bitcoin Core Vault and Bitcoin Core Node.
Vault maintains the canonical document; Node carries a verbatim mirror. The shared-document provenance record identifies the canonical repository, path, revision and file hash. Product state and product-specific contracts remain in their respective repositories.

## 1. Establish the starting point

Keep these identities separate for each product:

| State | Required evidence |
| --- | --- |
| Published release | Release URL/tag, exact ISO filename and SHA-256, source/build provenance, published checksums and signatures. |
| Last checked local candidate | Exact artifact and SHA-256, source/build provenance, checks actually performed and their environment. |
| Current development | Repository, branch/HEAD, local changes, generated outputs and approved work since the candidate. |

“Latest” filenames, modification times, a successful build or a release label do not establish that an artifact passed runtime checks. A source inspection does not establish that the same code is present in an ISO.

Before editing, inspect the current branch/HEAD and working tree, including relevant untracked files. Reconcile them with the current-state record and existing work. Preserve unrelated changes; do not reset, overwrite or silently discard them. Use a focused branch/worktree when it helps isolate the task.

Start from the appropriate current development state, including completed unreleased work. Do not restart from an older published release or an arbitrary old build directory merely because it is available. Record any intentional backport separately.

## 2. Load only the relevant context

Read the repository's `AGENTS.md`, development index and current-state record first. Then load the affected module's contract, relevant decisions, existing checks and necessary source files. Expand to a dependency only when the task or evidence warrants it.

Current module contracts describe expected behavior; release records describe immutable historical facts; plans describe proposed work. Keep those roles visible. Mark obsolete guidance as superseded and link its replacement. Do not promote a remembered conversation, planned feature or historical test into a current implementation claim.

Use explicit evidence labels: **source inspected**, **artifact inspected**, **runtime checked** (with environment), **planned**, **known issue**, or **not checked**. Record the revision/build and date to which a statement applies.

## 3. Make a bounded change

State the intended behavior, affected product/module, relevant data and immediate dependencies. Identify the authoritative source files before editing. Locate templates, generated copies, installation hooks, service definitions and other consumers of those files.

Edit the authoritative source and regenerate or synchronize its consumers through the existing process. Do not fix only an installed copy or one generated copy and leave the build source stale. If the generation process itself is broken, record and repair that cause within the task's necessary scope.

Respect module contracts: command/interface names, paths, permissions, exit status, state formats, process lifecycle and cancellation behavior. Check changes to shared components against their Vault and Node consumers. Similar appearance does not imply identical network, persistence or service requirements.

Use the existing architecture and checks. Extract a component or add a test when it resolves a concrete maintenance or regression risk. A small fix does not require a general rewrite, new framework or mandatory refactor.

The user's requested behavior can intentionally revise an existing standard. Record the decision and update affected contracts; do not treat previous defaults as permanently immutable. Routine reversible work and already authorized actions do not require another approval. Applicable access controls and release gates still apply; do not bypass or fabricate a passing result.

## 4. Verify the appropriate layer

Distinguish source checks, build/staging checks, final-artifact inspection, VM checks and physical-hardware checks. Report which layers were exercised. Source or staging success alone does not prove final-ISO behavior.

| Change | Typical necessary evidence |
| --- | --- |
| Copy, icon or spacing | Relevant rendered screen and affected action; no mandatory full ISO rebuild for a documentation-only change. |
| Window, launcher or shared dialog | Changed interaction plus affected consumers and relevant previous regressions. |
| Backup, restore, wallet handling or permissions | Success and relevant failure/cancellation paths with disposable test data. |
| Boot, installer or disk selection | Relevant VM/disk scenarios and targeted hardware checks; preserve-data behavior where applicable. |
| Kernel, driver or foundational dependency | Broader checks selected from the affected hardware and component dependencies. |

Prefer existing meaningful checks. Add coverage for a consequential contract or recurring defect, not a test that merely repeats implementation details. Broaden testing only for a concrete risk or required release gate. Never use a user's real wallet or backup as disposable test data.

For a release, inspect the final ISO and run its documented release checks. Record the exact tested bytes. A rebuild that changes the artifact creates a new candidate requiring appropriate verification. A waived or unavailable check must remain visible with its reason; it must not become a pass.

Store evidence with the source/build identity, command or scenario, result and environment. Version reference screenshots by product and build/revision, recording resolution/UI scale and relevant state. Preserve historical evidence; update current references without overwriting the record of what an earlier release contained.

## 5. Select the delivery path explicitly

| Path | What must be controlled |
| --- | --- |
| Debian packages | Existing supported updater/repositories, package versions, dependency changes, service/reboot effects and resulting package manifest. |
| Upstream applications (Core, KeePassXC) | Product-specific verification of the exact upstream release, integration and data compatibility, and the applicable restart behavior. |
| Project integration and content | Existing delivery mechanism, owned files, generated consumers, settings compatibility and migrations. Source changes alone are not an installed-system update. |
| ISO replacement | Boot/installer/image contents, pinned build inputs, final artifact identity, checksums/signatures and release evidence. |

Use mechanisms that the current product actually implements. Versioned project packages are a possible future improvement, not an assumed existing capability. Keep unrelated dependency upgrades outside a narrow fix unless they are required and recorded.

For live Vault operation from an immutable ISO, document the verified replacement-media path. Do not enable networking as an implicit update mechanism. Describe installed-mode updates only where that mode and its mechanism are implemented and checked.

Before an update, identify persistent data and settings it can touch, ownership boundaries, prerequisites and interruption behavior. Preserve user wallets, backups and configuration according to the module contract. Make data migrations explicit, versioned and recoverable where possible.

Document rollback limits before relying on rollback. Reverting application files does not necessarily revert a migrated wallet, database, partition layout or settings schema. Record compatible previous versions, required backups and recovery steps; do not promise a universal one-click rollback.

## 6. Build and publish with traceable inputs

Record source commit and build-tool identity, relevant configuration, package/source snapshots and resulting manifest. If the build uses uncommitted or otherwise untracked inputs, preserve the exact patch/source snapshot and hash before building. A commit alone must not imply a clean build when that was not true.

Keep source identity, build-input identity and final-artifact SHA-256 separate. Record verification of third-party downloads against the project's documented trust sources. A successful rebuild and a bit-for-bit reproduction are distinct results; claim only the demonstrated level.

Publish the tested artifact with its corresponding source/provenance, checksums, signatures, release notes and known limitations through the existing release process. Check that download links point to those exact artifacts. Do not silently replace a published artifact or rewrite its evidence to describe subsequent development.

Update the current-state record after promotion. Keep the release evidence immutable and the current index pointed at the appropriate published release, checked candidate and development state.

## 7. Finish with a compact handoff

Update affected contracts and current status alongside the code. Summarize the behavior changed, relevant files/modules, verification evidence and remaining limitations. Distinguish completed work from pending work and identify the exact resume point.

Use the small templates in [TEMPLATES.md](TEMPLATES.md); omit fields that add no useful information. A second document should not duplicate authoritative state already recorded elsewhere: link it.
