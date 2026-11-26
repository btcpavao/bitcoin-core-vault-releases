# Bitcoin Core Vault & Node — Development Reference

This is the **Bitcoin Core Vault** entry in the two-product development reference. It records the actual project structure and the evidence needed to change it without restarting from obsolete state. The initial documentation branch is for review; it does not change an ISO or promote pending work into a release.

## Read only what the task needs

| Need | Read |
| --- | --- |
| Begin any task | [AGENTS.md](../../AGENTS.md), then [CURRENT.md](CURRENT.md) |
| Identify an artifact or build | [CURRENT.json](CURRENT.json) and its evidence pointers |
| Understand user-visible behavior and storage boundaries | [PRODUCT.md](PRODUCT.md) |
| Find editable files, dependencies and existing checks | [MODULES.md](MODULES.md) |
| Change appearance or window/navigation behavior | [UI.md](UI.md) |
| Change, build, update or publish | [SHARED-WORKFLOW.md](SHARED-WORKFLOW.md) and the relevant product instructions |
| Record a change, release, tester report or unfinished task | [TEMPLATES.md](TEMPLATES.md) |
| Understand which documents are current | [DOCUMENTATION.md](DOCUMENTATION.md) |

## Two systems, explicit differences

Vault is the offline signer and recovery environment. Node is the online validation, transaction preparation and broadcast environment. Shared styling and copied components do not erase differences in networking, private-session storage, privilege boundaries or update mechanisms. Product contracts live in each repository's PRODUCT and MODULES documents.

Use separate identities for published releases, checked local candidates and current source. Build recipes can have a different commit from application source. A successful source check is evidence at that layer; it is not a physical-machine or final-image test.

## Source of truth and maintenance

CURRENT.json contains the machine-readable observed state. Keep CURRENT.md synchronized whenever a candidate, release or active source is updated. State observations name their date and evidence; reconcile them with the live checkout/handoff before work. Product contracts describe the intended behavior at the stated revision, with source/runtime limitations explicit.

SHARED-WORKFLOW.md and TEMPLATES.md have one canonical source in the Vault repository. Node keeps verbatim mirrors authenticated by [shared-reference.json](shared-reference.json). Product-specific state and module maps are not mirrored. Existing detailed instructions remain authoritative within their declared scope; this index routes to them instead of duplicating their full content.

## Local review workspace

On ThinkCentre the prepared references are under `/home/pavao/development-reference-20261126/vault` and `/home/pavao/development-reference-20261126/node`. Each is on `docs/development-reference-20261126`, based on the frozen source recorded in CURRENT.json. These are sparse documentation worktrees; inspect Git for files outside the sparse selection.

The final delivery record identifies the two documentation commits and their diff scope. Before adopting them into a later development branch, inspect that branch and cherry-pick/merge the documentation changes without rewinding its application source. Resolve any changed behavior against that newer source, then refresh CURRENT. Do not build an old runtime simply to obtain these documents.

## Initial review decisions

The initial change reconciles current descriptions and adds navigation, contracts and workflow. It does not change runtime defaults, package versions, partitioning, signing or publication. Pavao reviews any unresolved difference between implemented behavior and the requested product intent; routine technical evidence reconciliation proceeds without repeated approval prompts.
