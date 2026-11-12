# Bitcoin Core Vault — backup and recovery

This guide describes the current backup engine shipped with Vault v0.4.0.
The in-app Vault Guide contains the same workflow. Keep a copy of your own
recovery instructions outside the encrypted backup they explain.

## What a backup contains

| Selection | Payload after the final GPG layer is opened |
| --- | --- |
| One complete supported Bitcoin Core SQLite file named wallet.dat | wallet.dat directly; no TAR step |
| Other files, folders or several wallets | A standard TAR package containing the original names and structure |
| Older Vault TAR-based wallet backup | Its original TAR package; still recoverable in Vault |

New backups use symmetric GnuPG AES-256 CFB with MDC integrity protection.
Every added layer has an independent passphrase, and every layer must be
opened. You do not need a PGP keypair for these passphrase-based backups.
Vault also accepts its older AES-256 OCB backup profile during recovery;
test the exact external GnuPG application before relying on legacy-format
interoperability.

A typical two-layer wallet backup is named wallet.dat.gpg.gpg. Opening its
outer layer produces inner.gpg; opening the last layer produces wallet.dat.
Names can be changed, so record the required layer count and secret holders
in your recovery plan rather than inferring them from a filename.

## Core wallet encryption and GPG backup encryption

Bitcoin Core wallet encryption protects private-key material. Addresses,
public keys, transaction records and other wallet metadata can remain
readable. GPG protects the complete external backup payload.

Opening the GPG layers recovers the wallet file. Signing with a Core-encrypted
wallet still needs its separate Core passphrase. Do not count reuse of the
same passphrase as another independent secret. Multiple GPG layers control
access to one backup; they do not turn the wallet into Bitcoin multisig.

Start with one GPG layer unless a specific recovery plan needs more. Every
additional required secret adds another way recovery can fail. Keep usable
independent copies of the encrypted backup and of every required secret.
Keep geographically separated secrets independently accessible; storing
all of them in one immediately accessible database removes that separation.

## Create and verify a backup

1. Use **Wallet Backup** on Home for a consistent wallet snapshot. Use
   **Files → Create Encrypted Backup** for selected files and folders.
2. Keep one layer or choose **+ Add Encryption Layer**. Generate and confirm
   a fresh passphrase for every layer.
3. Select your mounted USB drive and choose a new filename to save the
   encrypted backup there. The default, Private Workspace, is temporary RAM.
4. Create the backup. Vault stages plaintext in verified RAM, verifies each
   encryption layer, then recovers the complete result and compares it with
   the original wallet snapshot or TAR package.
5. Vault checks the published encrypted copy. Make independent copies and
   practice restoring and signing with disposable test data.

Loaded wallets are snapshotted through Bitcoin Core. Supported closed
wallets use read-only SQLite backup. Original files are not encrypted in
place or deleted. Existing destination files are not overwritten.

A successful save in Private Workspace is not persistent. Copy anything
you need to keep to the intended external medium before ending the session.
The current operation limits are 16 layers, 10,000 TAR entries and up to
256 MiB per payload, reduced when available RAM is limited. Split larger sets.

## Passphrases and recovery dependencies

KeePassXC opens its Passphrase generator with six random words selected.
Generate each independent secret separately. You may change the word count;
do not use phrases invented from quotations or familiar sentences.

Clipboard clearing is initially disabled so you can confirm and record
multiple secrets. Other local applications may read clipboard contents.
You can enable a timeout in **Tools → Settings → Security → Clear clipboard
after**. A fresh private session restores image defaults.

Keep deliberate recovery copies of the required secrets. Do not put the
only secret inside the backup it unlocks, or the only password-manager
password inside that password database. A missing required secret cannot be
bypassed by Vault.

## Recover with Vault

1. Open **Decrypt Backup**, double-click the encrypted file in Files, or use
   **Decrypt Encrypted Backup** from its context menu.
2. Enter all required external passphrases in any order. Vault tries them
   against the outermost remaining layer.
3. Keep Private Workspace for a temporary recovery, or select your writable
   USB drive and name a new folder on it. Files recovered to USB remain there
   after shutdown with the outer GPG encryption removed.
4. Vault authenticates the layers and validates the final wallet or TAR
   payload. A direct-wallet backup becomes wallet.dat; packaged backups
   recover their original files and folders.
5. For a wallet, use **Bitcoin Core → File → Restore Wallet**. Check expected
   addresses and labels, then practice signing. Supply the separate Core
   passphrase when signing if that wallet's private keys are encrypted.

Missing or incorrect secrets, damage and unsupported formats can cause a
failure. Partial results are discarded on failure or cancellation, and
existing files are never overwritten.

For an ordinary GPG file not made as a Vault backup, select **Recover one
ordinary GPG layer only**. This stops after one authenticated layer and saves
recovered-file. An original GPG file inside a Vault TAR package remains an
original encrypted file; recovery does not recursively open it.

## Recover without Vault

Use trusted offline recovery software and a private RAM filesystem with
swap disabled. Do not run these examples in a persistent Downloads folder.
Choose new output names. Enter secrets only at GnuPG's interactive prompt,
never in command arguments, environment variables or scripts.

For a two-layer current single-wallet backup:

    umask 077
    gpg --output inner.gpg --decrypt wallet.dat.gpg.gpg &&
    gpg --output wallet.dat --decrypt inner.gpg

Enter the outer passphrase first, then the inner passphrase. With one layer,
decrypt wallet.dat.gpg directly to wallet.dat. Restore it through Bitcoin
Core's **File → Restore Wallet**. There is no TAR extraction in this case.

For grouped files or an older TAR-based backup, the final GPG operation
writes payload.tar instead of wallet.dat. Inspect it before extraction:

    tar --list --file payload.tar

After checking the listing, extract into a new RAM directory:

    mkdir recovered &&
    tar --extract --file payload.tar --directory recovered --no-same-owner --no-same-permissions

Proceed only when every GPG operation exits successfully without integrity
or authentication errors. Failed operations can leave provisional output;
do not use it. Do not blindly extract an untrusted archive. Reject absolute
paths, parent traversal, links, devices and unexpected files. Vault performs
its own strict validation.

Test the intended recovery build with a disposable backup. Software that
opens current CFB+MDC files may not support older OCB files. A file's suffix
does not prove its contents or layer count.

## Public transfers and external media

**Bitcoin Core → File → Export watch-only wallet** now starts in
**Private Workspace**. Save the public export there, then use **Files** to
copy that specific file to the intended transfer USB. It can be restored
on an online Bitcoin Core 32.1-or-newer node. Compare receiving addresses
independently before using the public wallet.

Core's USB view is read-only. It can read connected drives, but saves signed
PSBTs and public watch-only exports in private RAM. Copy completed transfer
files with Files. Keep the original signing wallet and its decrypted
backups offline.

Files and the included file choosers use wide Places sidebars. Mounted
USB drives appear alongside Bitcoin Core and Private Workspace. Qt
choosers also provide **USB Media**. Reopen an already-open chooser after
connecting a drive, or use that entry.

Wait for copying to finish, close files using the drive and eject/unmount
it through Files. For optical backups, burn only the verified encrypted
files, read the finished disc back and verify recovery. A compatible writer
and disc are required; a blank disc need not appear as a mounted folder.

If Brasero does not list an external writer, check its power, cable and USB
port, reconnect it and reopen Brasero. The read-only diagnostic command is:

    core-vault-optical-diagnostics > "$HOME/Private Workspace/optical-report.json"

It reports hardware identity, access and discovery; it does not test burning.
Keep the report with the drive model if further investigation is needed.

## Before ending the session

Confirm that needed backups, public transfers, documents and recovery
instructions have been saved outside RAM. Restart and shutdown show two
warnings and a five-minute countdown; these confirmations do not verify
that your backups exist or are current.

Vault's private home, wallet data, decrypted files and workspace disappear
when the session ends. External copies remain. This is a volatile-storage
policy, not a claim that every physical RAM cell or old flash-storage copy
has been overwritten.
