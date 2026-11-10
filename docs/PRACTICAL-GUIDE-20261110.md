# Practical Vault Guide — local test revision

Starts with a complete 13-step Vault/Node workflow, followed by the three-component
backup plan and the existing application chapters. The passphrase-choice chapter
replaces the old security-level framing and declares every numeric-model input.
Known entropy/wordlist assumptions, uncertain attacker knowledge, the $100,000
example, recovery simplicity, and additive sequential layer work are separated.
Core key encryption is distinguished from whole-file GPG backup confidentiality.
The UI uses the labels inspected in the bundled Core binary. No encryption, wallet,
RAM-warning, shutdown or networking code changes are included.

Before packaging, regenerate the canonical installer-payload manifest from the
final root tree. Verify all inner hashes and the unchanged installer verifier;
never carry forward old guide checksums or disable the installed-payload check.
Public releases, Node and physical user wallets/USB are outside this local change.
