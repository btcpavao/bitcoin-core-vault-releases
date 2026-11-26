# Bitcoin Core Vault — GPG backup and recovery

**Current payload scope: Vault v0.9.0**, reviewed against publication source `58f873fa727054f262b2f99bf742aff251cc5672` on 2026-11-26. A supported single `wallet.dat` is encrypted directly; grouped inputs and other selected files use TAR. See [the product baseline](../../../docs/development/PRODUCT.md#backups-and-recovery-contract) and `src/layered_backend.py` for the current implementation. This clarification adds no runtime test or platform-compatibility claim.


Encryption & Backup Security Levels
Start with the simplest arrangement that meets your needs. Every extra required secret adds a recovery dependency. More layers are not automatically better.


Bitcoin Core wallet encryption
Core protects private-key material with its wallet passphrase. Public keys, addresses, transaction records and other metadata may remain readable in wallet.dat. Recovery needs the wallet file; spending with an encrypted wallet also needs the Core passphrase. Use Wallet Backup to create and verify an encrypted external copy before ending the private session.


One GPG layer — the default
GPG encrypts the complete verified wallet file directly when the input is exactly one supported Bitcoin Core SQLite `wallet.dat`. Grouped inputs and other selected files are first put in a standard TAR package, including their filenames and folder structure. Both paths use AES-256 CFB encryption with an OpenPGP modification detection code (MDC). Recovery requires the .gpg file and its passphrase. No GPG keypair is needed. Maintain multiple verified copies of the encrypted file and independent redundant arrangements for the secret.


Two or more GPG layers
Click + Add Encryption Layer. Each layer needs an independent passphrase, and all layers must be opened for recovery. The application supports up to 16 layers, including 10, but most plans should stay simpler.


Prepare the plaintext payload in RAM: the verified single wallet directly, or a standard TAR for grouped/other inputs. Encrypt it with A (layer 1), encrypt that result with B (layer 2), then encrypt that result with C (layer 3). The same layering process applies to either payload type.
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
KeePassXC clears a copied passphrase after 10 seconds by default. Other applications in the session can read it during that time. If it expires before you finish, copy the same passphrase from the generator again.


To adjust the timeout, open Tools → Settings → Security → Clear clipboard after and save your choice. Relaunching KeePassXC does not overwrite your choice. Both Live and installed Vault use volatile user profiles: a fresh private session starts with the image defaults. Finish Private Session clears the clipboard.


Keep a deliberate recovery copy of every required secret. A KeePassXC database may hold a copy, but keeping every secret in one immediately accessible database defeats their geographic separation. Never keep the only database inside the backup it unlocks, or the only database password inside that database.





Backup & verify
- Use Wallet Backup on Home for a wallet, or Files → Create Encrypted Backup for selected files and folders.
- One GPG layer is the default. Add more only for an explicit recovery plan. Generate and confirm a different passphrase for each.
- Choose a new .gpg destination in Private Workspace, any other writable folder or external media. No external drive is required. Click Create Encrypted Backup.
- Vault snapshots loaded wallets through Bitcoin Core and closed wallets through read-only SQLite backup. It prepares the direct-wallet or TAR payload in RAM, encrypts and verifies each layer, then decrypts the complete result and checks it against the original payload.
- The published encrypted file is checked after copying. A direct wallet export is authenticated again and compared with the original verified wallet snapshot before its session receipt is saved.
- Make independent copies and perform a complete restore/signing drill at least annually.

You choose where to save and how to organize or copy backups. A backup saved only in Private Workspace or another RAM folder is lost when the session ends. Verification confirms its contents; it does not make RAM persistent. Copy anything you need to retain outside the RAM session before restarting or shutting down. The two warnings and five-minute countdown remain in place.

Only ciphertext is staged at the destination and publication never replaces an existing backup. Originals remain available. Use Wallet Backup for a consistent snapshot of each current wallet. Shutdown confirmations do not check that backups exist or are current.


Provisional data remain in verified private RAM with swap forbidden by the Vault session policy. The operation is bounded to 16 layers, 10,000 TAR entries and at most 256 MiB per package, reduced when free RAM is limited. Split larger sets. Cancellation removes temporary data, but this is not a claim of secure erasure of Python/Qt memory or physical RAM.





Decrypt Encrypted Backup

Open Decrypt Backup on Home, double-click a .gpg file in Files, or choose Decrypt Encrypted Backup from its context menu.


- Enter the available backup passphrases, in any order. Use + Add Passphrase for additional secrets.
- Choose Private Workspace or a writable USB drive, name a new folder and click Decrypt Backup.
- Vault authenticates each layer, then writes `wallet.dat` for a supported direct-wallet backup or restores the validated TAR contents and folder structure into the chosen folder.

If a secret is missing or wrong, add or correct it and retry. Damage and unsupported encryption can also cause a failure. Vault discards incomplete results in RAM. When copying authenticated files to USB, power loss or unplugging the drive can leave partial plaintext on the drive. Existing files are never overwritten.


For an ordinary GPG file made outside Vault, select Recover one ordinary GPG layer only. This deliberately stops after one authenticated layer and saves recovered-file; it does not guess whether your original data are themselves encrypted. Rename or handle that file explicitly. Vault backups finish with either a supported direct wallet or a validated TAR package. An original GPG file selected as backup input is preserved unchanged inside its TAR package; it is not recursively decrypted as another backup layer.


Recovery defaults to Private Workspace in RAM. Selecting a USB drive saves the recovered files there without the outer GPG protection. They remain on the drive after shutdown. A recovered file alone is not a verified current-wallet export.





Recovery / inheritance
Keep secret-free instructions outside the encrypted backup. Identify the backup copies, required secret holders, compatible software and how an heir can obtain access. Do not put the only recovery instructions inside the backup they explain.


With Vault
- Open the encrypted backup.
- Enter every external passphrase in any order.
- Recover into a new Private Workspace folder.
- For a wallet, use Bitcoin Core's Restore Wallet on the recovered wallet.dat. Check expected addresses, labels and a signing test. If encrypted in Core, supply its separate internal passphrase when signing.

Without Vault
For new backups, use a current GnuPG release supporting the widely implemented RFC 4880 AES-256 CFB+MDC profile. A direct-wallet backup needs Bitcoin Core to restore the resulting wallet; grouped backups and previous GPG/TAR backups additionally need standard TAR extraction. The tested Debian engine is GnuPG 2.4.7. macOS and Windows GUI compatibility must still be checked using real target applications. Old OCB archives remain recoverable by Vault's GnuPG 2.4 decoder.


Work on a trusted offline system in an owned mode-0700 tmpfs directory with swap disabled and sufficient RAM. Do not run the following in an ordinary persistent Downloads folder. Use new output filenames. Let GnuPG prompt interactively; never put secrets in shell arguments, environment variables or a script.


The following example is specifically for a known three-layer **TAR-backed** backup. For a supported direct-wallet backup, the last GPG output is `wallet.dat` and no TAR extraction follows.

```sh
umask 077
gpg --output layer2.gpg --decrypt backup.gpg
gpg --output layer1.gpg --decrypt layer2.gpg
gpg --output payload.tar --decrypt layer1.gpg
tar --list --file payload.tar
mkdir recovered
tar --extract --file payload.tar --directory recovered --no-same-owner --no-same-permissions
```

For this three-layer TAR example, enter C, then B, then A. With one TAR-backed layer, decrypt backup.gpg directly to payload.tar. Proceed to the next command only after GPG exits successfully without authentication errors. Failed commands may leave provisional output; do not use it. Stock GPG does not advertise the total Vault layer count. If order was lost, try the available secrets on the outer layer, then repeat with the remaining secrets.


For a known TAR-backed backup, inspect TAR's listing before extracting into a new RAM directory. Reject absolute paths, parent traversal, links, devices and unexpected files. Do not extract an untrusted archive blindly. The Vault GUI performs its own strict validation. A file originally selected as a GPG or TAR file remains a file inside the final TAR; stop there rather than recursively opening it.


Practice with disposable data and the intended holders. Keep independent usable copies of every required secret. A missing required layer secret cannot be bypassed by Vault, and losing a password manager's unlocking secret is another recovery dependency.

## Shutdown and restart

These actions never request passphrases or verify backups. First confirm that you saved what you need; then confirm the loss of anything stored only in the RAM session. A 05:00 countdown follows. Cancel countdown, Esc or closing the window keeps the session open. Restart now or Shut down now explicitly skips the remaining delay. Core closes and the clipboard clears only after expiry or that explicit action. External copies remain; unsaved session data are lost.


Portable filename conventions
A supported direct-wallet backup uses names such as `wallet.dat.gpg`, `wallet.dat.gpg.gpg` or `wallet.dat.gpg.gpg.gpg`; its final plaintext is the verified wallet file. A TAR-backed backup uses `.tar.gpg`, `.tar.gpg.gpg` or `.tar.gpg.gpg.gpg`; its final plaintext is a TAR archive containing the selected files. Common desktop applications may remove one `.gpg` extension per layer, but recovery must inspect authenticated content rather than trust extensions. Embedded literal names are fixed as `inner.gpg` for intermediate layers and either `wallet.dat` or `payload.tar` for the final payload; user-defined wallet names, private paths and secrets are not embedded in those names. The external filename may reveal the number of encryption layers; rename the encrypted file if that metadata must remain confidential, and explicitly select the proper output filename during recovery. For pre-update backups with only one .gpg extension, a decrypted file without an extension may itself be another valid GPG layer; verify with a trusted GPG tool and rename it to inner.gpg rather than executing it.

Single-wallet recovery without TAR
When Wallet Backup creates an encrypted copy of exactly one Bitcoin Core SQLite
wallet.dat, it encrypts the verified wallet directly, without a TAR container.
Each passphrase remains a separate standard GPG layer. With two passphrases,
the default filename wallet.dat.gpg.gpg decrypts to inner.gpg and then directly
to wallet.dat; open the resulting file with Bitcoin Core's Restore Wallet.
On macOS, GPG Suite should use the embedded wallet.dat name, and the default
external filename also ends with .dat when both .gpg suffixes have been removed.

For multiple selected files, folders, or a single file with a different name,
Vault builds a standard TAR before GPG encryption. A single input named
`wallet.dat` must pass the supported SQLite-wallet checks; invalid input is
refused rather than silently accepted as a direct wallet.
Previous single-wallet GPG/TAR backups also remain recoverable. Vault checks
the authenticated decrypted content, not merely file extensions, to choose
which recovery path to use. Never execute an unknown recovered file.
