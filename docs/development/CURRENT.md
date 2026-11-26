# Bitcoin Core Vault — current reference

**Observed:** 2026-11-26T09:20:25.203893+00:00 (UTC). Human-readable view of [CURRENT.json](CURRENT.json).

> This file records an observation. Before work, compare the current checkout, local changes and active handoff with this reference. A newer source, build or tester report may supersede a status below.

## Published standard release

- Release: [v0.9.0](https://github.com/btcpavao/bitcoin-core-vault-releases/releases/tag/v0.9.0); published 2026-11-25T11:10:16Z.
- ISO: `bitcoin-core-vault-v0.9.0-amd64.iso`; 1,133,379,584 bytes.
- SHA-256: `615067c09f573a4476c7039adc90e58f75a46bdf20a028fd3c58f3e300c832fe`.
- Signature observation: Signed-checksum assets are published; signatures were not reverified in this documentation pass.

## Last checked local candidate

- Status: **published_same_bytes**.
- Path on ThinkCentre: `/home/pavao/vault-release-assets-v0.9.0/bitcoin-core-vault-v0.9.0-amd64.iso`.
- SHA-256: `615067c09f573a4476c7039adc90e58f75a46bdf20a028fd3c58f3e300c832fe`; 1,133,379,584 bytes.
- Source identity: `58f873fa727054f262b2f99bf742aff251cc5672`.
- Source role: Publication freeze after accepted ISO; includes explicitly recorded review-metadata correction, not an exact clean build commit.
- Assembly: Local repacking of existing Vault base with reviewed native/runtime/kernel inputs
- Checksum observation: SHA-256 recomputed on ThinkCentre during the 2026-11-26 initial reference audit; matched the published release digest.

| Evidence layer | Recorded result |
| --- | --- |
| final iso live ui | Recorded PASS: Legacy BIOS QEMU, 1280x800 and 1024x768; no installation in this UI session. |
| maintainer report | Pavao accepted this candidate on 2026-11-25 in T530 context; do not infer all hardware modes. |
| prior installed settings | Carried-forward evidence with original ISO hashes and unchanged-component comparisons in ACCEPTANCE.json. |
| strict current source payload gate | NOT PASSED: accepted ISO retains old shred-policy review metadata; do not disable the gate. |
| independent whole iso reproducibility | NOT DEMONSTRATED for v0.9.0. |

Evidence records (their recorded hashes are in CURRENT.json):

- `/home/pavao/vault-release-assets-v0.9.0/BUILD-PROVENANCE.json`
- `/home/pavao/vault-release-assets-v0.9.0/ACCEPTANCE.json`

## Current development source

- Source checkout: `/home/pavao/vault-release-v0.9.0-20261125`.
- Frozen application commit: `58f873fa727054f262b2f99bf742aff251cc5672`.
- Source working tree at inspection: clean.
- Documentation checkout: `/home/pavao/development-reference-20261126/vault`.
- Documentation branch: `docs/development-reference-20261126`.
- Scope: Development documentation and reconciled current module notes; no runtime or ISO changes.

## Open items and boundaries

| ID | State | Description |
| --- | --- | --- |
| VAULT-PROVENANCE-001 | known_limitation | v0.9.0 whole-image independent byte equality is unestablished; preserve explicit metadata and T2/native source limitations. |
| VAULT-UPDATE-001 | not_implemented_as_general_capability | A general installed-Vault project-component updater is not established by this reference. |

## Refresh this reference

1. Inspect the actual source branch/HEAD, dirty inputs and active task record. Preserve concurrent work.
2. Read a completed acceptance or delivery record and verify the artifact hash before changing the checked-candidate identity. Copy exact test environments and explicit omissions; distinguish checked local evidence from completed delivery and publication.
3. Change published state only after observing the corresponding published release and asset identities. An experimental or draft release does not replace the standard channel by date alone.
4. Update CURRENT.json and this summary together, with the observation date and evidence references. Update PRODUCT/UI only where behavior or its verification actually changed.
5. Preserve previous release and acceptance evidence. Do not relabel old tests as tests of the new artifact.

A documentation commit does not become the application commit used for an already-built ISO. Keep the frozen application/build identities above even when this branch gains newer documentation commits.
