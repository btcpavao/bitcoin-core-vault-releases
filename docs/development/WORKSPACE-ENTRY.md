# Local Vault and Node reference workspace

This file is the entry point for the paired documentation workspace prepared on
ThinkCentre at `/home/pavao/development-reference-20261126`. The parent
`AGENTS.md` points here; each child repository has its own scoped `AGENTS.md`.

For a new task, select the product from the user's request and read:

- Vault: `/home/pavao/development-reference-20261126/vault/AGENTS.md`
- Node: `/home/pavao/development-reference-20261126/node/AGENTS.md`

Then inspect that product's current source and active work from its
`docs/development/CURRENT.md`. These are dated observations; reconcile the real
HEAD, dirty files, new artifacts and active handoff before choosing a base.

The child checkouts are documentation branches, not automatically the active
runtime development branches. Their sparse checkout does not mean omitted
application files are deleted. Apply/adopt the documentation commits into an
appropriate newer development branch without rewinding its code. Preserve other
tasks' worktrees, builds and artifacts.

Shared workflow lives canonically in Vault and is mirrored in Node with content
hashes and provenance. Product behavior and state stay separate. A task affecting
one component needs its module contract and immediate dependencies, not the
entire project history.

On another machine, locate the corresponding repositories and evidence by Git
revision and artifact hash. These ThinkCentre paths are discovery hints, not
portable installation requirements. Current user instructions retain priority.
