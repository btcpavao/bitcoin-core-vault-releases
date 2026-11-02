# Local Core 32.1 candidate — 29 October 2026

Updated official bitcoin-qt and bitcoin-cli to 32.1. SHA256SUMS was verified
against eight signatures using release keys already in the Node repository.
See provenance/32.1 for hashes and verification details. Both binaries remain
unmodified. The official source and binary archives are retained with the local build.

Removed the custom watch-only Home card, wallet polling, export dialog, backend,
launcher, JSON schema and their retired tests. The Guide now explains Core's
File → Export watch-only wallet and File → Restore Wallet, saving the public
.dat file in RAM and copying it with Files. General encrypted backup is unchanged.

Application validation with disposable wallets: native public export/restore
preserves derivations, labels and transactions; private descriptors are unavailable;
watch-only prepares but cannot sign PSBT; signer completes a valid transaction.
The real Vault launcher permits native export to RAM and rejects writes to
forbidden destinations. Encrypted GPG wallet backup, restore and recovered-wallet
PSBT signing pass with Core 32.1. Home fits 800×600 through 1920×1080 without scroll.
Guide layout, file-dialog settings and source identity gates pass.

These are application/source checks. The exact ISO's build log and VM evidence
are recorded separately with the local artifact. Physical T530 testing is pending.
Node and GitHub are unchanged. Full updated Qt/dependency source companions
must be prepared before public distribution; historical 31.1 records remain historical.
