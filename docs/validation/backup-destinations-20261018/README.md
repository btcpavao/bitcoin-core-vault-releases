# Backup destinations and Home warning — 2026-10-18

Implemented in the candidate source and staged Debian package.

- Wallet Backup and Files → Create Encrypted Backup default to Private Workspace and accept other writable destinations without a media-type approval.
- Temporary/internal/external classification is optional receipt metadata. It does not authorize creation or verification; missing mount metadata does not block the operation.
- RAM backups receive the same authenticated wallet-snapshot read-back as other destinations. A receipt proves verified contents, not durable storage.
- Original files, no-overwrite publication, RAM-only plaintext staging, safe path checks and authentication remain enforced.
- Home now says: “Private session: wallets and working files stay in RAM until shutdown. Please back up all necessary files and wallets to external media before shutdown or restart, as all data kept only in RAM will be lost.”
- Two power confirmations and the five-minute countdown are unchanged. No backup passphrases are requested at shutdown/restart.
- Active runtime and template copies match. Guide/help and packaged instructions explain the destination choice and RAM lifetime.

Validation:
- 57 backup unit/integration tests pass, including actual tmpfs wallet export/recovery, internal-destination acceptance, copied archive verification, both UI routes without extra media prompts, metadata lookup failure, corruption, no-overwrite and cancellation.
- Real official Bitcoin Core 31.1 application fixture passes wallet backup/restore, loaded/unloaded/closed wallets and original address verification. Actual RAM destination detection is used, without a removable-media override. The fixture substitutes private-storage attestation for its isolated synthetic mount layout; it does not certify installed storage policy.
- 9 Qt backup-dialog tests, 13 shutdown/restart tests and 20 private-session tests pass.
- Home geometry passes 800×600, 1024×768, 1280×800 and 1920×1080. Warning visibility is separately checked and captured at 800×600 and 1366×768.
- Guide passes 18 chapters at four sizes and the layer selector checks.
- Ten top-level source gates pass, including backup package/source matching, private-session, shred, UI, Live, media, Files/recovery, Places, Core file dialogs and BleachBit removal. Nested checks are recorded in source-gates.log.
- Runtime/template equality, Python syntax and git diff --check pass.

Staged package: core-vault-backup_0.7.0_all.deb
SHA-256: 987ef5704575cfd3cfb5040e88c24287120b0c06133f2579ad5fde82f2742807

Screenshots use the host Qt icon fallback; production theme artwork is unchanged.
A fresh ISO build and VM/T530 test are still required. No existing ISO, physical USB, real wallet or host private session was modified by these tests.
