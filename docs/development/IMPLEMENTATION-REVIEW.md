# Bitcoin Core Vault & Node — development reference implementation

Prepared on **26 November 2026** as isolated documentation branches. The source
and ISO identities are in each product's CURRENT record. This document is the
human entry point for reviewing the initial documentation change.

## Where to start

| Product | ThinkCentre reference entry |
| --- | --- |
| Vault | `/home/pavao/development-reference-20261126/vault/docs/development/README.md` |
| Node | `/home/pavao/development-reference-20261126/node/docs/development/README.md` |

Both repositories use branch `docs/development-reference-20261126`. The workspace
root `README.md` points to this review and its `AGENTS.md` routes a future task to
the correct product. Each product then loads its own current state and module.

The review archive contains the prepared documentation, reference captures and
Git patches. Relative source links resolve in the corresponding complete Git
repository; application code is not duplicated into the documentation archive.

## Delivered structure

| File | Purpose |
| --- | --- |
| `AGENTS.md` | Compact start, scope, verification and handoff instructions for a future agent |
| `docs/development/README.md` | Task-oriented index and two-product architecture context |
| `CURRENT.json` and `CURRENT.md` | Dated structured identity/status record and readable companion |
| `PRODUCT.md` | Implemented functions, storage/privacy boundaries, defaults and evidence limits |
| `MODULES.md` | Editable paths, generated consumers, dependencies, shared differences and existing checks |
| `UI.md` | Scoped source-derived style values, window/navigation rules and versioned visual evidence |
| `SHARED-WORKFLOW.md` | Focused changes, proportional checks, four delivery paths, builds and publication |
| `TEMPLATES.md` | Small module/change/release/tester/handoff forms |
| `DOCUMENTATION.md` | Current versus historical authority and maintenance rules |
| `shared-reference.json` | Canonical Vault edition and hash-verified Node mirror |

## Concrete corrections

- Vault Settings now distinguishes volatile Live preferences from validated
  installed-device persistence. Private wallets and the ordinary home remain in
  RAM in both modes.
- Vault Date & Time now describes zone-only Apply separately from explicit
  manual clock correction and installed RTC behavior.
- Vault Home documentation describes its ten fixed launchers rather than a
  copied Node synchronization/card-discovery layout.
- Vault Display instructions distinguish the RAM working profile from the
  installed preference store. Old cross-project test references are labeled
  rather than offered as nonexistent local commands.
- RAM-session history retains its dated scope; current Finish behavior is
  separated from superseded receipt-gated designs.
- Backup instructions consistently distinguish a supported direct single-wallet
  payload from a TAR-backed multi-file/folder backup. Invalid single inputs named
  `wallet.dat` are rejected by the direct-wallet validation path.
- Node Settings and Home notes reflect the frozen 26 November source: one footer
  Settings entry, removed former footer peer label, current categories and
  independent Software Updates navigation.
- The November 25 Node parity report remains historical evidence, with links to
  the current contract instead of silently extending its acceptance claims.

## Identity and evidence rules in use

Published release, last completed checked candidate and current development are
separate records. Vault v0.9.0 is the published accepted local image. Node's
published RC3 is distinct from later local candidates. The 26 November Node
source and delivered local artifact have their own identity and bounded VM
acceptance. The completed local delivery has been observed; GitHub publication
and physical-hardware acceptance are separate states.
CURRENT must be refreshed from completed evidence before a candidate is promoted.

The source commit, build-recipe commit, source-tree/archive hash and ISO SHA-256
are distinct fields. Vault's documented v0.9.0 review-metadata mismatch and
unestablished independent whole-image reproducibility remain explicit. Earlier
test results keep their original image and environment.

Vault reference captures are copied from its exact v0.9.0 release assets. Node
also includes actual November 26 ISO captures of installed Home and installer
Review from its completed bounded VM QA. Separate Node source/X11 captures are
interaction diagnostics with declared host limitations, not image-theme approval.
Screenshot records preserve file hashes, dimensions and scope.

## Verification of this documentation change

The delivery record contains the resulting documentation commits and exact
validation totals. Verification covers relative links against the frozen Git
trees and new files, source-path inventory, JSON validity, identity agreement,
shared-copy equality, whitespace and documentation-only diffs. An independent
review checked the product/state/update boundaries and found no blocking issue.

These checks verify the documentation change. They do not substitute for runtime,
ISO, hardware or installer checks; no new such tests are claimed by this change.
The existing active Node build has its own separate acceptance process.

## How the next change should begin

Use the workspace root as the reference entry, select Vault or Node, and read its
AGENTS and CURRENT files. Locate the affected row in MODULES, then load the
relevant product/UI contract and source. Confirm the actual current source and
pending work before editing. Finish with the relevant evidence and corresponding
documentation update.

The user can intentionally change a previous standard. Code is evidence of
implemented behavior, not automatic approval of a defect. Routine reversible
work and previously authorized actions proceed without another approval; unclear
product decisions and applicable access controls retain their actual scope.
