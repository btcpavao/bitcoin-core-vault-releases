# Bitcoin Core Vault: development instructions

## Start with the current state

1. Read [the development entry](docs/development/README.md) and [CURRENT.md](docs/development/CURRENT.md). CURRENT.json is the structured state; CURRENT.md is its human-readable companion.
2. Inspect this checkout's HEAD, branch and local changes, plus the active build/handoff referenced there. A dated record is an observation, not proof that nothing newer exists.
3. Read only the affected row in [MODULES.md](docs/development/MODULES.md), its linked contract and relevant source/checks. Load [UI.md](docs/development/UI.md) for visual or interaction work and [SHARED-WORKFLOW.md](docs/development/SHARED-WORKFLOW.md) for build/update/release work.

## Bound the change

- Start from the appropriate current development source, preserving completed unreleased changes. Published release, checked local ISO and unbuilt source are separate identities.
- Preserve unrelated work. Record the starting commit and dirty inputs; use an isolated worktree when appropriate. Never reset another task's checkout or modify its running builder.
- Identify authoritative files and all installed/generated/template copies. Follow the existing copy/build mechanism and relevant equality checks.
- Keep the change focused on the requested behavior and necessary dependencies. Expand the scope when evidence requires it, recording why.
- Separate observed behavior, accepted intent and known defects. If code and instructions disagree, inspect the source/artifact/evidence and record the discrepancy. Do not turn an implementation defect into a permanent product rule.
- A user's new instruction may deliberately revise an existing standard. Update the affected contract in the same change. Routine reversible or already authorized work needs no additional confirmation.

## Preserve product boundaries

- Vault and Node share presentation conventions but have different networking, persistence and service policies. Review intentional product differences before transferring a change.
- Identify wallet, backup, configuration and disk effects before changing those paths. Use disposable test data and owned test disks for destructive validation.
- Keep official upstream applications, project integration, Debian packages and image assembly identities separate. A new ISO does not automatically update installed systems.

## Verify and finish

- Reuse meaningful existing checks from MODULES.md, proportional to the affected behavior. Add or broaden tests only for a concrete risk or required gate.
- Distinguish source checks, final-image inspection, VM behavior and physical hardware acceptance. Evidence must name the actual source/artifact and environment.
- Keep failing or unavailable gates visible. Do not weaken a gate to make a result pass, or carry an old full-image reproducibility claim onto a new image.
- Update current contracts/status with the code. Preserve completed release records, historical evidence and their original artifact identities.
- Use [TEMPLATES.md](docs/development/TEMPLATES.md) for a short handoff or tester report. End with changed behavior, evidence, remaining work and the exact resume path.

## Documentation workspace

The initial review branch is `docs/development-reference-20261126` in `btcpavao/bitcoin-core-vault-releases`. Its ThinkCentre checkout is sparse and intended for documentation review. Source files omitted from that checkout still exist in Git. Use the current source checkout or a deliberate full worktree for runtime work; absence from a sparse checkout is not deletion from the project.
