# Native watch-only workflow (Bitcoin Core 32.1)

Vault uses the unmodified Bitcoin Core GUI for export. Select the signing wallet,
then File → Export watch-only wallet. Save `watch-only.dat` in Private Workspace
and copy that public file to transfer media using Files. Core remains confined
to checked RAM write locations. Never transfer the original signing wallet.

On an online computer with Core 32.1 or newer, use File → Restore Wallet, select
the exported file and name the new wallet. Confirm watch-only status and compare
a receiving address independently before use. Older wallets may need a rescan;
pruned nodes may need blocks they no longer hold.

The native database includes public descriptors, cached derivations, transactions
and address book data, without private keys. It is not a signing backup. Keep a
separate verified encrypted signing-wallet backup offline. Encrypt the public
copy with Files → Create Encrypted Backup if desired; Core itself does not add
Vault's GPG wrapping. RAM-only copies disappear at shutdown.

The custom Home export card, polling, JSON/GPG export dialog, launcher and JSON
schema have been removed. Historical validation under docs/validation/watch-only
describes the retired tool, not current acceptance. Node will be updated separately.

Official release notes: https://bitcoincore.org/en/releases/32.1/
