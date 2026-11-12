# Bitcoin Core Vault — GPG/TAR backup and recovery


Encryption & Backup Security Levels
Start with the simplest arrangement that meets your needs. Every extra required secret adds a recovery dependency. More layers are not automatically better.


Bitcoin Core wallet encryption
Core protects private-key material with its wallet passphrase. Public keys, addresses, transaction records and other metadata may remain readable in wallet.dat. Recovery needs the wallet file; spending with an encrypted wallet also needs the Core passphrase. Use Wallet Backup to create and verify an encrypted external copy before ending the private session.


One GPG layer — the default
GPG encrypts the complete TAR package, including wallet data, filenames and documents, using AES-256 CFB encryption with OpenPGP modification detection (MDC). Recovery requires the .gpg file and its passphrase. No GPG keypair is needed. Maintain multiple verified copies of the encrypted file and independent redundant arrangements for the secret.


Two or more GPG layers
Click + Add Encryption Layer. Each layer needs an independent passphrase, and all layers must be opened for recovery. The application supports up to 16 layers, including 10, but most plans should stay simpler.


StepResultPackage original filesStandard TAREncrypt with AGPG layer 1Encrypt that with BGPG layer 2Encrypt that with Cbackup.gpg, outer layer 3
Example: keep redundant encrypted backup copies in two locations; keep redundant copies of A with trusted holders in one region, B with independent holders in another, and C with independent holders in a third. Recovery requires one usable encrypted copy and A, B and C. Copies within each group reduce loss risk, while separation matters for theft resistance. Consider collusion, travel, incapacity and access delays.


An intermediate inner-layer copy bypasses every outer layer. Avoid retaining such copies when your plan depends on all layers. Keeping all passphrases in one database or on the same device also removes the intended separation. The backup file's external name, size and timestamps remain visible. Symmetric authentication detects damage or tampering; it does not prove who created the backup.


Bitcoin Core plus GPG
You may combine Core private-key encryption with one or more external GPG layers. Opening every external layer reveals wallet.dat and its metadata, but signing still needs the separate Core passphrase. Do not count reuse of the same passphrase as an additional independent secret. The GUI rejects repeated external passphrases; it cannot check the internal Core secret.


Threat models
Whole-file encryption provides privacy and resistance to theft of a backup without its secrets. Redundancy mitigates accidental loss; test every required component. Geographic separation can create logistical barriers to immediate coercion, but does not guarantee protection from continuing coercion or an attacker collecting secrets over time. A compromised signing computer may expose keys or every secret entered during recovery.


Inheritance needs understandable instructions, accessible software, dependable holders and a practiced recovery process. Too much complexity can prevent your family from recovering the wallet. Match the number of layers to actual independent handling and realistic recovery requirements.


Multiple GPG layers are not multisig
GPG layers control access to a backup of one wallet. Once opened, that wallet follows its ordinary Bitcoin signing rules. Multisig distributes transaction authorization across independent Bitcoin keys and enforces a signing threshold. Layered backup encryption does not create that threshold or distribute signing authorization.





KeePassXC
Home opens the stock KeePassXC generator on Passphrase with six words selected. Generate a new random phrase for every independent GPG layer. Paste it into the passphrase and confirmation fields for that layer. No password database is required to generate passphrases.


Six independent uniformly selected words from the 7,776-word EFF list provide about 77.5 bits of entropy; eight provide about 103.4 bits. These figures do not apply to quotations or phrases you invent. You may change the word count.


Clipboard default
Clear clipboard after is initially unchecked to allow time for copying multiple independent secrets. The secret remains available until replaced, explicitly cleared, or released by the session or clipboard owner. Other local applications may read it for longer. No clipboard-history application is installed by this workflow.


To enable automatic clearing, open Tools → Settings → Security → Clear clipboard after, choose the timeout, and save. Relaunching KeePassXC does not overwrite your choice. Both Live and installed Vault use volatile user profiles: a fresh private session starts with the image defaults. Finish Private Session clears the clipboard.


Keep a deliberate recovery copy of every required secret. A KeePassXC database may hold a copy, but keeping every secret in one immediately accessible database defeats their geographic separation. Never keep the only database inside the backup it unlocks, or the only database password inside that database.





Backup & verify
- Connect external backup media.
- Use Wallet Backup on Home for a wallet, or Files → Create Encrypted Backup for selected files and folders.
- One GPG layer is the default. Add more only for an explicit recovery plan. Generate and confirm a different passphrase for each.
- Choose a new .gpg destination. Click Create Encrypted Backup.
- Vault snapshots loaded wallets through Bitcoin Core and closed wallets through read-only SQLite backup. It packages the inputs in RAM, encrypts and verifies each layer, then decrypts the complete result and checks it against the original package.
- The published encrypted file is checked after copying. A direct wallet export is authenticated again and compared with the original verified wallet snapshot before its session receipt is saved.
- Make independent copies and perform a complete restore/signing drill at least annually.

Only ciphertext is staged at the destination and publication never replaces an existing backup. Originals remain available. Use Wallet Backup for a consistent snapshot of each current wallet. Shutdown confirmations do not check that backups exist or are current.


Provisional data remain in verified private RAM with swap forbidden by the Vault session policy. The operation is bounded to 16 layers, 10,000 TAR entries and at most 256 MiB per package, reduced when free RAM is limited. Split larger sets. Cancellation removes temporary data, but this is not a claim of secure erasure of Python/Qt memory or physical RAM.





Decrypt Encrypted Backup

Open Decrypt Backup on Home, double-click a .gpg file in Files, or choose Decrypt Encrypted Backup from its context menu.


- Enter the available backup passphrases, in any order. Use + Add Passphrase for additional secrets.
- Choose Private Workspace or a writable USB drive, name a new folder and click Decrypt Backup.
- Vault authenticates each layer and restores the original filenames and folder structure into the chosen folder.

If a secret is missing or wrong, add or correct it and retry. Damage and unsupported encryption can also cause a failure. Partial recovered data are discarded on failure or cancellation. Existing files are never overwritten.


For an ordinary GPG file made outside Vault, select Recover one ordinary GPG layer only. This deliberately stops after one authenticated layer and saves recovered-file; it does not guess whether your original data are themselves encrypted. Rename or handle that file explicitly. Vault backups always use a standard TAR package as their final payload; an original GPG file inside the package is preserved unchanged.


Recovery defaults to Private Workspace in RAM. Selecting a USB drive saves the recovered files there without the outer GPG protection. They remain on the drive after shutdown. A recovered file alone is not a verified current-wallet export.





Recovery / inheritance
Keep secret-free instructions outside the encrypted backup. Identify the backup copies, required secret holders, compatible software and how an heir can obtain access. Do not put the only recovery instructions inside the backup they explain.


With Vault
- Open the encrypted backup.
- Enter every external passphrase in any order.
- Recover into a new Private Workspace folder.
- For a wallet, use Bitcoin Core's Restore Wallet on the recovered wallet.dat. Check expected addresses, labels and a signing test. If encrypted in Core, supply its separate internal passphrase when signing.

Without Vault
New backups use standard RFC 4880 AES-256 CFB+MDC symmetric encryption and standard TAR. GnuPG 2.4.7 is the tested Debian engine. Decrypt each layer in order with current GnuPG on a trusted macOS, Linux or Windows system; verify your own recovery software and workflow. Vault can still decrypt older OCB archives, which may not work with other GPG applications.


Work on a trusted offline system in an owned mode-0700 tmpfs directory with swap disabled and sufficient RAM. Do not run the following in an ordinary persistent Downloads folder. Use new output filenames. Let GnuPG prompt interactively; never put secrets in shell arguments, environment variables or a script.


umask 077
gpg --output layer2.gpg --decrypt backup.gpg
gpg --output layer1.gpg --decrypt layer2.gpg
gpg --output payload.tar --decrypt layer1.gpg
tar --list --file payload.tar
mkdir recovered
tar --extract --file payload.tar --directory recovered --no-same-owner --no-same-permissions
For the three-layer example, enter C, then B, then A. With one layer, decrypt backup.gpg directly to payload.tar. Proceed to the next command only after GPG exits successfully without authentication errors. Failed commands may leave provisional output; do not use it. Stock GPG does not advertise the total Vault layer count. If order was lost, try the available secrets on the outer layer, then repeat with the remaining secrets.


For your known backup, inspect TAR's listing before extracting into a new RAM directory. Reject absolute paths, parent traversal, links, devices and unexpected files. Do not extract an untrusted archive blindly. The Vault GUI performs its own strict validation. A file originally selected as a GPG or TAR file remains a file inside the final TAR; stop there rather than recursively opening it.


Practice with disposable data and the intended holders. Keep independent usable copies of every required secret. A missing required layer secret cannot be bypassed by Vault, and losing a password manager's unlocking secret is another recovery dependency.

## Shutdown and restart

These actions never request passphrases or verify backups. First confirm that you saved what you need; then confirm the loss of anything stored only in the RAM session. A 05:00 countdown follows. Cancel countdown, Esc or closing the window keeps the session open. Restart now or Shut down now explicitly skips the remaining delay. Core closes and the clipboard clears only after expiry or that explicit action. External copies remain; unsaved session data are lost.


Portable filename conventions
A Vault backup is standard TAR encrypted in consecutive GPG layers. A one-layer file has a name ending .tar.gpg; two layers use .tar.gpg.gpg; three use .tar.gpg.gpg.gpg. Decrypting strips one .gpg extension per layer in common desktop applications. The final output is a .tar archive, which contains the original wallet.dat and other selected files. Embedded encrypted literal names are always generic inner.gpg and payload.tar; wallet names, private paths and secrets are not embedded in those names. The external filename may reveal the number of encryption layers; rename the encrypted file if that metadata must remain confidential, and explicitly select the proper output filename during recovery. For pre-update backups with only one .gpg extension, a decrypted file without an extension may itself be another valid GPG layer; verify with a trusted GPG tool and rename it to inner.gpg rather than executing it.

Single-wallet recovery without TAR
When Wallet Backup creates an encrypted copy of exactly one Bitcoin Core SQLite
wallet.dat, it encrypts the verified wallet directly, without a TAR container.
Each passphrase remains a separate standard GPG layer. With two passphrases,
the default filename wallet.dat.gpg.gpg decrypts to inner.gpg and then directly
to wallet.dat; open the resulting file with Bitcoin Core's Restore Wallet.
On macOS, GPG Suite should use the embedded wallet.dat name, and the default
external filename also ends with .dat when both .gpg suffixes have been removed.

For multiple selected files, folders, or a file other than the supported
wallet.dat format, Vault still builds a standard TAR before GPG encryption.
Previous single-wallet GPG/TAR backups also remain recoverable. Vault checks
the authenticated decrypted content, not merely file extensions, to choose
which recovery path to use. Never execute an unknown recovered file.
