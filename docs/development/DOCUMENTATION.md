# Documentation authority and maintenance

## Read claims according to their role

| Kind | Authority and use |
| --- | --- |
| Current user request and accepted product decision | Intended change; can deliberately revise an older standard. Record the resulting decision with the affected contract. |
| PRODUCT, MODULES and UI | Current product contract and implementation map at their stated revision; distinguish observed behavior, accepted intent and a known defect. |
| CURRENT.json / CURRENT.md | Dated identity/status index; reconcile against the current source, artifact and active handoff before work. |
| Existing module instructions | Detailed scoped implementation guidance, as linked from MODULES. A contradiction is evidence to investigate, not a reason to restore obsolete behavior. |
| Release, acceptance and provenance records | Historical facts about the named artifact; do not silently rewrite or extend their test claims. |
| Dated design notes and proposals | Historical rationale or proposed behavior, unless explicitly reconciled as current. |
| Code and actual artifact/runtime observations | Evidence of what is implemented, not automatic approval of every behavior or defect. |

Resolve a conflict by checking its product/mode, revision and evidence. If the current requested behavior is clear, implement it and update the contract. Ask the user only when an unresolved product decision materially changes the task; routine reconciliation and already-authorized work proceed.

## One source for shared process

The canonical SHARED-WORKFLOW.md and TEMPLATES.md live at `docs/development/` in the Vault source repository. Node carries verbatim copies. `shared-reference.json` records the canonical paths, edition and SHA-256 digests; the Node mirror also records the corresponding canonical documentation commit when available.

To change shared process, edit the Vault copies first, review the change, update the edition/digests and copy those exact bytes into Node. Verify both pairs with SHA-256 before committing the mirror. Do not copy product-specific CURRENT, PRODUCT, MODULES or UI documents between products. Each product keeps its own behavior and evidence.

## Update documents with the change

- A behavior/default/format change updates the relevant product contract.
- An editable path, generated consumer or dependency change updates MODULES.
- A visual or navigation change updates UI and its relevant screenshot/evidence reference.
- A source/candidate/release promotion updates CURRENT, without changing the old release record.
- A fixed recurring defect retains a concise regression scenario and its affected/fixed build identities.
- A new decision records its reason and applicability; a short entry in the change record is sufficient until a larger decision merits its own document.

Module entries link existing checks. This documentation pass does not execute every check or certify hardware. A test file's presence only establishes available coverage.

## Local and portable references

Repository-relative links are portable with the source. Absolute `/home/pavao/` paths identify retained ThinkCentre artifacts and workspaces; another machine must obtain the corresponding hash-identified evidence or source rather than assume those paths exist. Release URLs and hashes provide the public references. Sparse worktrees can omit source files physically; inspect the Git tree before declaring a path absent.

## Initial reconciliation

The Settings and Display notes now distinguish Live RAM preferences from allowlisted installed-device persistence. The Home layout note describes Vault rather than Node synchronization. RAM-session notes identify current boundaries and keep the old dated implementation narrative historical. Original signed release artifacts and acceptance records are unchanged.

The historical source archive for v0.9.0 will still contain its original documentation; corrections on this branch do not alter those published bytes. The known publication review-metadata difference remains visible in CURRENT and the original release provenance.
