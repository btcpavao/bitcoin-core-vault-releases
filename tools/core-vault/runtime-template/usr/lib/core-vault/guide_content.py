"""Standalone practical Vault/Node tutorial and Vault tool reference. No wallet or network access."""
from math import log2

# Explicit illustrative scenario, not a current rental quote or a measured Vault attack rate.
WORDLIST_SIZE = 7772
ATTACK_GPUS = 10000
GUESSES_PER_GPU_SECOND = 14800
USD_PER_GPU_HOUR = 0.89
SECONDS_PER_YEAR = 365.25 * 86400


def attack_example(words):
    possibilities = WORDLIST_SIZE ** words
    guesses = (possibilities + 1) / 2
    seconds = guesses / (ATTACK_GPUS * GUESSES_PER_GPU_SECOND)
    return dict(words=words, bits=words * log2(WORDLIST_SIZE),
                average_seconds=seconds,
                average_usd=seconds / 3600 * ATTACK_GPUS * USD_PER_GPU_HOUR)


def attack_table():
    rows = []
    for words in (4, 5, 6):
        data = attack_example(words)
        seconds, cost = data['average_seconds'], data['average_usd']
        duration = (f"about {seconds / 86400:,.0f} days" if words == 4 else
                    f"about {seconds / SECONDS_PER_YEAR:,.0f} years" if words == 5 else
                    f"about {seconds / SECONDS_PER_YEAR / 1e6:.1f} million years")
        money = (f"about US${cost / 1e6:.1f} million" if words == 4 else
                 f"about US${cost / 1e9:.0f} billion" if words == 5 else
                 f"about US${cost / 1e15:.2f} quadrillion")
        rows.append(f"<tr><td><b>{words} random words</b><br>about {data['bits']:.1f} bits</td>"
                    f"<td>{duration}</td><td>{money}</td></tr>")
    return ('<table border="1" cellpadding="9"><tr><th>Passphrase length</th>'
            '<th>Average time<br>10,000 assumed GPUs</th><th>Average rental cost<br>Illustrative USD</th>'
            '</tr>' + ''.join(rows) + '</table>')


SECTIONS = {
'Start here: Vault & Node': '''<h2>Start here: Vault &amp; Node</h2>
<p>This tutorial takes you through the complete setup: create a signing wallet offline, protect and duplicate its backup, export a public watch-only copy, receive on your online Node, then sign and broadcast a payment. The remaining chapters explain each tool in this workflow.</p>
<p><b>Vault stays offline and holds the signing keys. Node stays online and uses a watch-only wallet.</b> Public wallet information and transaction files move between them on removable media. The original signing wallet and its decrypted backups stay offline.</p>
<h3>1. Prepare the two computers and backup media</h3>
<p>Start Bitcoin Core Vault on the offline computer. Your active wallet and Private Workspace are in RAM in both Live and installed Vault. Save what you need outside RAM before restarting or shutting down.</p>
<p>Have at least two independent destinations for the encrypted backup: separate USB drives, or USB and a compatible writable CD/DVD. Also prepare separate places for multiple copies of each passphrase. A second folder on the same USB is not protection against losing that USB. Use a clearly distinguished transfer USB for the watch-only export and PSBT files.</p>
<p>Begin with a disposable wallet and a small receive-and-spend test. Complete a recovery test before relying on the setup for savings.</p>
<h3>2. Generate the Bitcoin Core wallet passphrase</h3>
<p>Open <b>KeePassXC</b> from Home. Its generator opens on <b>Passphrase</b> with six words. Generate a fresh random phrase and keep the words, order, separators and capitalization exactly as generated. This is your <b>Core passphrase</b>, used to unlock the wallet's private keys for signing.</p>
<p>Make more than one accurate recovery copy promptly; legible paper records are one option. Check each copy before clearing the clipboard. Keep these records away from the future encrypted backup and from the GPG-passphrase records. A KeePassXC database is optional, not necessary for generation. The chapter <b>How to choose a passphrase</b> explains the 4-, 5- and 6-word trade-off.</p>
<h3>3. Create and encrypt the signing wallet in Core</h3>
<p>Open <b>Bitcoin Core → File → Create Wallet</b>, give the wallet a recognizable local name and select <b>Encrypt Wallet</b>. For this ordinary signing wallet, leave <b>Disable Private Keys</b> and <b>Make Blank Wallet</b> unchecked. Create the wallet and enter the Core passphrase when asked. You are creating a wallet that can sign, not the watch-only copy.</p>
<p>For an existing unencrypted wallet, select it and use <b>Settings → Encrypt Wallet</b>. Follow Core's confirmation and make a new backup after encryption; do not treat an older unencrypted copy as protected. Check that the intended wallet is selected and its encryption is enabled before proceeding.</p>
<p>Core encryption protects private keys, not the entire wallet database. Someone with only a Core-encrypted wallet.dat may still inspect addresses and recorded history; a synchronized node may discover associated balances. They cannot normally sign without unlocking the private keys. The next step adds privacy for the complete backup file.</p>
<h3>4. Generate a different GPG passphrase</h3>
<p>Return to KeePassXC and generate a new independent phrase. This is your <b>GPG passphrase</b>. It opens the encrypted backup file; it is not the Core passphrase. Do not reuse the first phrase or make a small alteration to it.</p>
<p>Make redundant copies of this secret too, and store them separately from both the encrypted backup copies and the Core-passphrase copies. Record which secret has which role without placing the secrets together. Never keep the only copy in this RAM session.</p>
<h3>5. Create the whole-file encrypted backup</h3>
<p>Open <b>Wallet Backup</b> on Home. Select the wallet if more than one is present. Keep one GPG layer for the basic setup, enter and confirm the GPG passphrase, and choose a new output name with <b>Choose…</b>. A neutral filename such as <b>archive-01.gpg</b> avoids advertising “Bitcoin wallet” in the outer name; it does not conceal the OpenPGP format or file size.</p>
<p>Choose a writable USB destination, or Private Workspace temporarily, then click <b>Create Encrypted Backup</b>. Wait for successful verification. Vault creates a consistent wallet snapshot, encrypts it, decrypts the result for comparison and checks the destination copy. The original wallet remains available in RAM.</p>
<p><b>The result now has three separately held components:</b> the encrypted .gpg file, its GPG passphrase, and the Core passphrase inside the wallet's protection. Opening the GPG file reveals the still-Core-encrypted wallet.dat. Signing then needs the Core passphrase.</p>
<h3>6. Duplicate the encrypted file on independent media</h3>
<p>Use <b>Files</b> to copy the final .gpg file to at least two independent media or locations. A verified backup left only in Private Workspace is still temporary. Open the external drive and check the saved filename and size; then test recovery from the actual copy as described below.</p>
<p>For optical storage, open <b>Brasero → Data project</b>, add the final encrypted .gpg file, select a compatible writer and blank disc, and burn. Read the finished disc back and test its backup. Do not burn the decrypted wallet or include its passphrases on the same disc. Without a compatible writer, use separate USB drives instead.</p>
<p>Place backup copies in different locations. Do the same for each passphrase, while keeping the three component groups separate. You need one usable copy from every group, not every physical copy. The next chapter gives a concrete storage plan.</p>
<h3>7. Prove recovery before sending significant funds</h3>
<p>From an external copy, open <b>Decrypt Backup</b>, supply the GPG passphrase and recover into a new Private Workspace folder. For this single-wallet backup the result is <b>wallet.dat</b>. Use <b>Bitcoin Core → File → Restore Wallet</b>, select that file and give the restored test copy a new name.</p>
<p>Compare known receiving addresses with the original wallet. When you perform the small spend test in steps 11–13, confirm that the restored copy can sign with the separately stored Core passphrase. This checks all three components, not just whether a .gpg file exists. Keep decrypted recovery files offline; do not copy them to the online Node.</p>
<h3>8. Export a public watch-only wallet from Vault</h3>
<p>Select the intended signing wallet in Core and choose <b>File → Export watch-only wallet</b>. Save <b>watch-only.dat</b> in <b>Private Workspace</b>, the default destination. Use Files to copy only that exported public file to your transfer USB. Core's USB view in Vault is read-only, so this save-then-copy step is deliberate.</p>
<p>A watch-only copy contains public address information, not private keys. It cannot authorize a payment, but it can reveal wallet activity. It is not a replacement for the signing-wallet backup. Check that you copied the export, not the original wallet.dat.</p>
<h3>9. Import the public wallet on Bitcoin Core Node</h3>
<p>On the online computer, use the Node image with Core 32.1 or newer. Open <b>Bitcoin Core → File → Restore Wallet</b>, choose watch-only.dat and give the wallet a name. Confirm that it is watch-only. Do not enter either signing-wallet passphrase on the Node for this workflow.</p>
<p>Let Node synchronize and complete any wallet scan. Synchronization checks the blockchain; a wallet scan looks for transactions belonging to this wallet. An older wallet may need blocks a pruned node has already removed. An unfinished scan is not a verified balance.</p>
<h3>10. Obtain and verify a receiving address</h3>
<p>Select the watch-only wallet on Node and open <b>Receive → Create new receiving address</b>. Confirm the selected wallet and Bitcoin network. Before sending funds, independently compare the address with the matching wallet in Vault. For a new matching export with neither side advanced, requesting the first address on each side should match; if address counters have diverged, stop and reconcile the matching address/index rather than assuming different addresses are equivalent.</p>
<p>Use a small first payment and let Node show its confirmations. Receiving does not require the offline signing keys. An offline Vault is not a source of up-to-date balances.</p>
<h3>11. Prepare an unsigned PSBT on Node</h3>
<p>When spending, open <b>Send</b> in the matching watch-only wallet. Enter the recipient, amount and fee, review them, then choose <b>Create Unsigned</b> to create a <b>PSBT</b>—a Partially Signed Bitcoin Transaction. It is a file containing the proposed payment and the information a signer needs; creating it does not spend anything.</p>
<p>Use <b>Save…</b> in the transaction dialog to save the .psbt file. You can use Node's PSBT Transfer Folder temporarily, but copy the file to the transfer USB before ending that RAM session. Transfer only the payment file to Vault.</p>
<h3>12. Review and sign the PSBT offline in Vault</h3>
<p>In a new Vault session, first recover the encrypted backup with its GPG passphrase and restore wallet.dat in Core. Select that signing wallet. Copy the unsigned .psbt from USB into Private Workspace, then choose <b>File → Load PSBT from file…</b> in Core.</p>
<p>Independently verify the actual recipient addresses, amounts, fee and change. <b>Change</b> is the remainder returned to an address of your own wallet; confirm Core recognizes it as yours. A file arriving from your Node is not a reason to skip this review.</p>
<p>Select <b>Sign Tx</b> and enter the <b>Core passphrase</b> when asked. Confirm the transaction is fully signed and ready to broadcast. Save the signed PSBT under a distinct name in Private Workspace, then copy it to the transfer USB with Files. Keep private keys and recovered wallet files offline.</p>
<h3>13. Return to Node and broadcast</h3>
<p>On the online, synchronized Node, load the signed PSBT with <b>File → Load PSBT from file…</b>. Review it again, then choose <b>Broadcast Tx</b>. Node sends the signed transaction to the Bitcoin network and displays the result. Broadcasting is not a confirmation: follow the transaction in Core until it receives the confirmations you require.</p>
<p>Before closing Vault, save any new backup or notes you need. Use <b>Restart</b> or <b>Finish &amp; Shut Down</b> only after saving outside RAM. The Home reminder and countdown are warnings, not proof that a recoverable backup exists.</p>
<h3>Which tool does which part?</h3>
<table border="1" cellpadding="8"><tr><th>Tool</th><th>Role in this workflow</th></tr>
<tr><td>Bitcoin Core</td><td>Create/encrypt and restore the signing wallet; export watch-only; inspect and sign PSBTs.</td></tr>
<tr><td>KeePassXC</td><td>Generate independent random passphrases; optionally store secret records in a separately recoverable database.</td></tr>
<tr><td>Wallet Backup / Decrypt Backup</td><td>Create a verified whole-file encrypted backup; recover it into RAM.</td></tr>
<tr><td>Files / Private Workspace</td><td>Manage temporary work and deliberately transfer finished outputs to external media.</td></tr>
<tr><td>Brasero / Print &amp; Labels / Editor</td><td>Write backup discs; prepare paper records, labels and understandable recovery instructions.</td></tr>
<tr><td>Terminal</td><td>Optional advanced verification and recovery commands—not required for the basic graphical workflow.</td></tr></table>
<p>For technical background, the Bitcoin Core offline-signing tutorial and BIP 174 describe the online/offline PSBT division of work. References: github.com/bitcoin/bitcoin/blob/master/doc/offline-signing-tutorial.md and bips.dev/174. The buttons above follow this image's Core workflow; backup and storage controls are provided by Vault.</p>''',

'Backup components & storage': '''<h2>Backup components &amp; storage</h2>
<p><b>Use the simplest arrangement that achieves the intended protection and that you can reliably recover.</b> The basic arrangement recommended in this Vault Guide is Core wallet encryption plus one external GPG layer, using two independently generated passphrases. This is the Vault workflow recommendation, not a claim that Bitcoin Core mandates a particular backup policy.</p>
<p>The illustration starts with one GPG layer. Select two layers to see the four-component arrangement, or three to see five components. These buttons change only the illustration.</p>
<h3>Three components, not just three physical copies</h3>
<table border="1" cellpadding="8"><tr><th>Component</th><th>What it does</th><th>How to preserve it</th></tr>
<tr><td><b>1. Encrypted .gpg file</b></td><td>Contains the complete wallet backup, including the Core-encrypted private keys.</td><td>Keep several verified copies on independent media and in separate locations.</td></tr>
<tr><td><b>2. GPG passphrase</b></td><td>Opens the .gpg file and reveals wallet.dat.</td><td>Keep multiple accurate copies, separate from the file and Core secret.</td></tr>
<tr><td><b>3. Core passphrase</b></td><td>Unlocks the wallet's private keys for signing after recovery.</td><td>Keep multiple accurate copies, separate from the file and GPG secret.</td></tr></table>
<p>For example, file copies F1 and F2 are in locations A and B; GPG-secret copies G1 and G2 are in C and D; Core-secret copies C1 and C2 are in E and F. These are <b>six physical copies of three logical components</b>. Recovery needs F1 <b>or</b> F2, G1 <b>or</b> G2, and C1 <b>or</b> C2.</p>
<p>Choose holders and locations that are independent in practice. Two envelopes lost in one fire or controlled by one person are not independent against that event. Consider access, cooperation between holders, travel, incapacity and inheritance. Every required component needs redundancy so that no single lost record prevents recovery.</p>
<h3>Passphrase copies: make them promptly and check them</h3>
<p>Paper is an option. Write the exact words, order, separators and capitalization; compare the copies before ending the RAM session. Use discreet identifiers that you and the intended heirs can connect through separate recovery instructions. Avoid labels exposing a balance or placing all secrets with the wallet file.</p>
<p>A KeePassXC database can be another copy, but its database file and unlocking secret also need recovery arrangements. Do not keep the only secret inside the backup it opens, and do not keep all supposedly separate secrets in one readily accessible database. Memory can supplement records, not replace them.</p>
<h3>What one isolated component reveals</h3>
<p>With strong, uncompromised encryption, the .gpg file alone does not expose the wallet contents, addresses, balance or transaction history without successful decryption. An isolated passphrase does not contain an address, balance or spending key and does not identify the wallet it belongs to. None of these three components, by itself, enables spending in this arrangement.</p>
<p>This is the privacy benefit of separating the components. It does <b>not</b> make a secret safe to disclose or a stolen encrypted file irrelevant. A phrase can be recognized as a password, and the file can be recognized as OpenPGP-encrypted data. Outer filenames, sizes, timestamps, labels, acquisition circumstances and other records can reveal context. A neutral filename reduces an obvious label, not every clue.</p>
<h3>Why GPG is useful even with Core encryption</h3>
<p>A Core-encrypted wallet.dat still contains readable public wallet information. Someone obtaining it may inspect stored addresses/history or scan the blockchain for related activity, although spending still needs the Core secret. GPG encrypts the <b>whole backup payload</b>, adding privacy for those records as well as another independent access secret. No GPG keypair is needed for this passphrase-based backup.</p>
<h3>Four components: add one independent GPG layer</h3>
<p>Choose <b>+ Add Encryption Layer</b> during backup creation and generate a different GPG phrase. The arrangement becomes: <b>outermost encrypted file + GPG secret A + GPG secret B + Core secret</b>. That is four logical components; make redundant copies of each and preserve their separation.</p>
<p>Do not distribute an intermediate inner file or decrypted wallet when your plan relies on the outer layers: doing so bypasses those layers. Layer order should be documented for manual recovery, although Vault's recovery dialog accepts the available GPG phrases in any order. Adding layers does not change the wallet into Bitcoin multisig.</p>
<h3>Keep the plan recoverable</h3>
<p>Use more layers only when they add useful independent separation. Extra required secrets increase recovery dependencies and coordination. Practise restoring and signing with the intended records and holders, keep readable instructions outside the encrypted file, and renew backups after wallet encryption, passphrase changes, imported keys or other changes that require a new wallet backup. Keep older copies identified until the replacement has been recovered successfully.</p>''',

'Home & keyboard': '''<h2>Home &amp; keyboard</h2>
<p><b>Welcome to Bitcoin Core Vault.</b> This is the offline computer in a two-computer setup. Vault keeps the secret information used to approve a Bitcoin payment. Your separate online Node checks the blockchain, prepares payments and sends signed payments to the Bitcoin network.</p>
<p>For the complete setup and first payment, read <b>Start here: Vault &amp; Node</b>. This chapter covers navigation and temporary storage.</p>
<h3>Terms used in the workflow</h3>
<p><b>Wallet:</b> a file that holds your Bitcoin address information and, for a signing wallet, the private keys that approve spending. Bitcoin ownership and transfers are recorded on the blockchain; the wallet provides the keys and records needed to use them.</p>
<p><b>Passphrase:</b> a password made from several words. <b>Encrypt</b> means lock information so it needs a secret to read it. <b>Decrypt</b> means unlock it. A <b>backup</b> is a separate saved copy; <b>restore</b> means use that copy again.</p>
<p><b>RAM</b> is temporary working memory. <b>Private Workspace</b> is a folder in RAM. Its files disappear when the private session ends, even when Vault is installed on the computer. An external USB drive or a written disc keeps files after shutdown.</p>
<h3>A reminder when files are in RAM</h3>
<p>After you create or import a wallet or save files in Private Workspace or other user working folders, a reminder appears below the Home launchers, above the Debian logo. Please back up what you need to external media before restarting or shutting down. Closing the application does not save its RAM files elsewhere.</p>
<p>The reminder checks for saved files, not their contents or whether an external backup is complete. It remains while the RAM files are present, even after you make a backup, and goes away when the monitored working files are removed. Routine application settings and logs are excluded. Unsaved editor text may not yet be a file, so no reminder is not proof that nothing needs saving. The existing shutdown warnings still apply.</p>
<h3>Find your way around</h3>
<p>Press <b>F12</b> to show Home, and F12 again to return to your application windows. Click a launcher to open a tool. With a keyboard, use <b>Tab</b> or <b>Shift+Tab</b> to move between controls and <b>Space</b> to activate the selected control.</p>
<p>Restart and Finish &amp; Shut Down show two warnings and then a five-minute countdown. Cancel is selected by default. Press <b>Esc</b> to keep working. Please read <b>Finish Private Session</b> before your first shutdown.</p>''',

'Bitcoin Core': '''<h2>Bitcoin Core</h2>
<p>Bitcoin Core is the wallet application inside Vault. Use it to create a wallet, check addresses, restore a wallet backup, and review and sign payment files while offline.</p>
<h3>What stays, and what disappears?</h3>
<p><b>The active wallet and Core's working files stay in RAM.</b> They disappear at shutdown or restart in both Live and installed Vault. Installing Vault keeps Debian and the applications on disk; it does not make this private session permanent.</p>
<h3>Your usual workflow</h3>
<p>Create or restore a wallet in Core → encrypt its private keys with the separate Core passphrase → make and verify a backup → save independent copies outside RAM → review and sign payments offline when needed.</p>
<p>Open <b>Wallet Backup</b> on Home for a checked wallet export. For signed payment files or public watch-only exports, save in <b>Private Workspace</b> and copy the finished file to USB with <b>Files</b>. Core can read a mounted USB, but its USB view is read-only: it does not save directly to that drive. Copy input files into Private Workspace to keep working after disconnecting the drive.</p>
<h3>Two different passwords may have different jobs</h3>
<p><b>Core wallet encryption</b> locks the private keys used for signing. It does not hide every part of wallet.dat: addresses, labels and transaction history can still be readable. <b>GPG backup encryption</b> locks the whole exported file. Keep the Core passphrase separate from the GPG passphrase; opening the backup does not automatically unlock spending.</p>
<p>Vault keeps networking disabled. It does not download the blockchain or broadcast payments. Core's first synchronization panel is hidden automatically once; its bottom synchronization indicator can show it again. An offline balance may be incomplete or out of date. Use the online Node for current history, while independently checking every payment in Vault.</p>''',

'KeePassXC': '''<h2>KeePassXC</h2>
<p>KeePassXC generates random passwords and passphrases. Home opens its <b>Passphrase</b> generator with <b>six words</b> selected. You do not need to create a password database just to generate a phrase.</p>
<ol><li>Choose the word count you intend to use.</li><li>Generate a new random phrase. Please do not replace words with favourite words or turn it into a familiar quotation.</li><li>Copy it exactly into the backup passphrase and confirmation fields.</li><li>Keep a separate, recoverable record of that secret. Generate a fresh phrase for a different encryption layer.</li></ol>
<p>The <b>How to choose a passphrase</b> chapter compares 4, 5 and 6 random words using an explicit illustrative attack-cost model. The number of words is your choice; six is the starting setting, not a rule forced by the application.</p>
<h3>The clipboard is temporary shared storage</h3>
<p>Copying puts the secret on the clipboard so you can paste it. <b>Clear clipboard after</b> starts unchecked, allowing time to copy several independent secrets. Other applications in this session may read the clipboard while the secret remains there. Replace or clear it when finished. No clipboard-history application is installed by this workflow.</p>
<p>For automatic clearing, open <b>Tools → Settings → Security → Clear clipboard after</b> and choose a time. Relaunching KeePassXC keeps that choice within the current private session. A new Vault session starts with the image defaults. Finish Private Session clears the clipboard.</p>
<p>A KeePassXC database can store recovery records, but it is another file to back up and another password to recover. Do not put the only database inside the backup it unlocks, or its only password inside the database. Keeping all layer passphrases together also removes the separation you intended.</p>''',

'Brasero': '''<h2>Brasero</h2>
<p>Use Brasero for the optical-disc branch of tutorial step 6: write the final encrypted backup, not the decrypted wallet or its secrets.</p>
<p>Brasero writes files to a CD or DVD. A finished disc is a separate physical backup, not part of temporary RAM.</p>
<h3>Write and check a backup disc</h3>
<ol><li>Make and verify the encrypted backup first.</li><li>Connect a compatible CD/DVD writer and open <b>Brasero → Data project</b>.</li><li>Add the encrypted files, select the writer, insert a suitable blank disc and burn the project.</li><li>Read the finished disc back and test recovery. A successful burn message alone does not prove that the backup opens.</li><li>Label it and keep another verified copy in a separate location.</li></ol>
<p>A disc reader cannot burn discs. M-DISC needs compatible media and a compatible writer. Internal and USB optical drives use the same desktop discovery.</p>
<h3>If an external writer is missing</h3>
<p>Check the power supply and cable, try a direct USB port, reconnect the writer and reopen Brasero. A blank disc does not have to appear as a folder in Files for the writer to work in Brasero.</p>
<p>For a support report, open Terminal and run:</p>
<pre>core-vault-optical-diagnostics &gt; "$HOME/Private Workspace/optical-report.json"</pre>
<p>The report lists the drive, access permissions and how the desktop sees it. It does not read files from the disc or test burning. Please include the drive model when reporting a problem and save the report outside RAM before shutdown.</p>''',

'Print & Labels': '''<h2>Print &amp; Labels</h2>
<p>Use this tool for the paper records and media labels in the three-component storage plan. Keep secret records separate from file copies.</p>
<p>Use this tool for printed recovery instructions, backup inventories, test pages and labels for USB drives or discs. A clear label helps you find the right backup later.</p>
<p>Templates do not automatically insert private keys, seed phrases or wallet passwords. Keep ordinary labels free of secrets: a backup name, date and location reference are usually enough.</p>
<p>Printing a secret creates another copy on paper and may leave traces in the printer. Treat that paper and printer deliberately. Store recovery instructions where the intended person can find them without first opening the encrypted backup they explain.</p>''',

'Files': '''<h2>Files</h2>
<p>Use Files for tutorial steps 6, 8 and 11–13: duplicate encrypted backups and move public wallet exports or PSBTs between RAM and removable media.</p>
<p>Files is the file manager. It lets you open folders and copy files. <b>Bitcoin Core</b>, <b>Private Workspace</b> and the Vault user's home folder are temporary RAM locations. USB drives and discs are separate storage that can keep your saved files.</p>
<h3>The same Places in your applications</h3>
<p>Files, Core, KeePassXC, Editor and the included file choosers have wide sidebars. Look there for Bitcoin Core, Private Workspace and mounted USB drives. <b>Mounted</b> simply means the drive is connected and its files are available to open.</p>
<p>Core and other Qt file choosers also show <b>USB Media</b>. If you connect a drive while a chooser is open, reopen the chooser or select USB Media. The application itself can stay open.</p>
<h3>Save from Core, then transfer with Files</h3>
<p>Core's USB view is read-only. Save a public watch-only wallet or signed PSBT in Private Workspace, then use Files to copy that specific export to your transfer USB. Keep the original signing wallet offline. For a signing-wallet backup, use Wallet Backup.</p>
<h3>Encrypt selected files</h3>
<p>Select files or folders and choose <b>Create Encrypted Backup</b>. A single supported wallet.dat is encrypted directly. Other selections are first put in a <b>TAR</b>, a container that keeps files and folder names together, then encrypted. TAR alone is not encryption. Give top-level selections distinct names; use separate named folders for several files all called wallet.dat. Links and special device files are refused.</p>
<p>Choose a new .gpg destination and confirm each independently generated passphrase. The originals are not encrypted in place or deleted. Double-click a .gpg file to recover it into Private Workspace.</p>
<h3>Delete or eject carefully</h3>
<p><b>Permanently Delete…</b> overwrites supported ordinary files and removes them without Trash or Undo. SSDs and USB flash devices may keep older copies that overwriting cannot reach. This is not a promise that every past copy is erased.</p>
<p>Finish copying, close files using the drive, then select Eject/Unmount. If the drive is busy, close the relevant application and retry. Do not unplug it during a write.</p>''',

'Editor': '''<h2>Editor</h2>
<p>Use Editor to record the three components, where their redundant copies can be obtained, and the recovery order without putting all secrets in the instructions.</p>
<p>Editor opens plain-text notes. Use it for a backup inventory, a checklist or recovery instructions someone else can understand.</p>
<p>Where you save determines whether the note lasts. <b>Private Workspace is temporary</b>; an intentional copy on external media remains after shutdown. Keep temporary sensitive notes in Private Workspace and encrypt them before saving a lasting copy when needed.</p>
<p>For ordinary recovery instructions, describe which files and secrets are needed without writing all secrets into the same document.</p>''',

'Terminal': '''<h2>Terminal</h2>
<p>Terminal is optional in the basic tutorial. Use it only for an advanced recovery or diagnostic procedure you understand.</p>
<p>Terminal is a window where you type commands instead of clicking buttons. Most everyday Vault work can be done without it.</p>
<p>Use it for a verified advanced procedure or a requested diagnostic. <b>RPC</b> means commands sent to Bitcoin Core's local control interface. It is not a separate wallet or a Bitcoin website.</p>
<p>Read a command before running it. Commands can change temporary files and external drives. Please do not paste untrusted commands or put a real passphrase into a command, script or environment variable. Let GPG ask for the secret in its password prompt.</p>
<p>The Recovery / inheritance chapter includes a standard GPG example. Use its RAM-only working location instructions, not a persistent Downloads folder.</p>''',

'Private Workspace': '''<h2>Private Workspace</h2>
<p>Private Workspace is the temporary staging area used throughout the tutorial. Saving here is different from saving a lasting external backup.</p>
<p><b>This folder lives in RAM.</b> Use it as a temporary worktable for decrypted files, exported payment files and sensitive notes. It is easy to find in the application sidebars.</p>
<p><b>Nothing here survives the end of the private session.</b> Shutdown, restart or power loss can remove all of it. This applies even when Vault's operating system is installed on the internal disk.</p>
<h3>The default for watch-only exports</h3>
<p><b>Bitcoin Core → File → Export watch-only wallet</b> starts in Private Workspace. Name and save the public export there, then use Files to copy it to the intended USB. A successful save in RAM does not make a lasting backup.</p>
<p>Before ending the session, save whatever you need to external media and confirm it is readable. RAM-only operation is not a guarantee of physical RAM overwriting, and it cannot make a compromised running computer trustworthy.</p>''',

'USB & optical media': '''<h2>USB &amp; optical media</h2>
<p>Files deliberately saved on USB drives and written discs can remain after Vault shuts down. Use clearly labelled media so you can distinguish public payment transfers from encrypted signing-wallet backups.</p>
<h3>Find a drive</h3>
<p>Connect it and look in the left sidebar of Files or the file chooser. If needed, click it to mount it: that makes the files available. In Core and other Qt applications, reopen an already-open chooser or select <b>USB Media</b> to see a newly connected drive.</p>
<p>Core reads USB files but cannot save directly to its read-only USB view. Save public watch-only exports and signed PSBTs in Private Workspace, then copy them with Files. The encrypted backup tools can write verified encrypted output directly to writable external media.</p>
<h3>Keep the roles separate</h3>
<p>Transfer media carry public watch-only copies or payment files. Backup media hold verified encrypted copies. Do not carry an original signing wallet or decrypted signing backup onto the online Node. Keep independent usable backup copies on different devices and in different locations.</p>
<h3>Remove media safely</h3>
<p>Wait for copying or burning to finish, close files using the medium and select <b>Files → Eject/Unmount</b>. If it is still busy, close the relevant application and retry. A blank optical disc is not an ordinary mounted folder; see Brasero if the writer is missing. Periodically test the actual backup, not just its label.</p>''',

'Create & encrypt a wallet': '''<h2>Create &amp; encrypt a wallet</h2>
<p>This is steps 2–5 of <b>Start here: Vault &amp; Node</b>. The basic setup uses Core wallet encryption and one external GPG layer, with independently generated secrets.</p>
<ol><li>Generate the <b>Core passphrase</b> in KeePassXC and make accurate redundant records.</li><li>In <b>Bitcoin Core → File → Create Wallet</b>, name the wallet and select Encrypt Wallet. Leave Disable Private Keys and Make Blank Wallet unchecked for a normal signing wallet. Enter the Core phrase when prompted.</li><li>For an existing unencrypted wallet, use <b>Settings → Encrypt Wallet</b>. Make a fresh backup after encryption.</li><li>Generate a <b>different GPG passphrase</b> in KeePassXC and make separately stored redundant copies.</li><li>Use <b>Wallet Backup</b>, select the wallet, enter and confirm the GPG phrase, choose a new .gpg output and create the verified backup.</li><li>Save verified file copies outside RAM and prove recovery, address matching and signing with a disposable wallet before relying on the process.</li></ol>
<p>Core encryption protects private keys. GPG encryption protects the complete backup file, including its public wallet records. The Core phrase is not entered into the GPG recovery dialog. Wallet Backup can also encrypt a wallet without Core encryption, but then the basic arrangement has only the file and GPG secret; it does not have the separate Core signing lock recommended here.</p>''',

'Generate a passphrase': '''<h2>Generate an encryption passphrase</h2>
<p>A passphrase is a password written as words. What matters here is that the words are <b>independently chosen at random</b>, not that they form an impressive-looking sentence.</p>
<ol><li>Open KeePassXC from Home. The generator starts on Passphrase with six words.</li><li>Select the intended word count and large EFF wordlist, then generate locally.</li><li>Keep the exact words, order, spaces and capitalization. Please do not change them into a quotation or a personal phrase.</li><li>Record the secret through your recovery arrangements. Generate a new phrase for a different layer, not a small variation of the first one.</li></ol>
<p>As a rough comparison, six random words from the full 7,776-word EFF list give about 77.5 bits of unpredictability; eight give about 103.4 bits. More bits mean more possible phrases for an attacker to search. A different or filtered wordlist has a slightly different count. The chapter <b>How to choose a passphrase</b> explains 4, 5 and 6 words with a declared time-and-cost model.</p>
<p><b>The word boxes in this Guide are placeholders, not passwords to use.</b> Always generate your own. Clipboard clearing starts off; you can enable it in Tools → Settings → Security. Please keep a recoverable copy without placing every independent layer's secret in one location.</p>''',

'How to choose a passphrase': '''<h2>How to choose a passphrase</h2>
<p><b>Choose the least complicated arrangement that gives enough protection for your value, storage horizon and recovery plan.</b> A short random phrase is easier to record, check and enter; extra words increase resistance to guessing but add handling effort. More length is not automatically a better overall recovery plan, and shorter is not automatically sufficient.</p>
<h3>Word count, randomness and entropy</h3>
<p>KeePassXC's generator chooses words independently at random. The large EFF wordlist bundled in this image has <b>7,772 entries</b>. With n words there are 7,772<sup>n</sup> possible ordered phrases. Repetition is allowed by the model; the order matters. The fixed spaces between words do not add extra uncertainty.</p>
<p><b>Entropy</b> expresses that range of possibilities in bits: n × log<sub>2</sub>(7,772). Four random words give about <b>51.7 bits</b>, five about <b>64.6 bits</b>, and six about <b>77.5 bits</b>. Each additional independent word multiplies the search space by 7,772. These values describe the generation method, not a phrase you invent, shorten or turn into a quotation.</p>
<h3>Brute force means paying for repeated guesses</h3>
<p>An attacker with an encrypted file can test candidate passphrases offline. There is no online login rate limit to stop that process. Assuming uniform random generation and no better attack, a successful exhaustive search takes about <b>half the candidate space on average</b>; it can succeed earlier or later.</p>
<p>To translate the search space into time and money, we must assume a guessing rate and a hardware cost. The worked example below uses <b>10,000 GPUs</b>, each making <b>14,800 complete guesses per second</b>, at <b>US$0.89 per GPU-hour</b>. GPUs are parallel computing devices. These are <b>illustrative planning assumptions, not measured performance for this ISO or a current rental quote</b>. The attacker is assumed to know the wordlist and exact word count, but not the words.</p>
''' + attack_table() + '''
<p>For one layer, average time = half the candidate space ÷ combined guessing rate. Average cost = that time in hours × the cost of all GPUs. More GPUs reduce elapsed time; at the same per-GPU rate and price they do not reduce total computing cost. Faster or cheaper guesses reduce both the cost and the relevant time estimates. The very long durations are fixed-rate comparisons, not predictions of future hardware.</p>
<h3>Example: US$100,000 behind a four-word phrase</h3>
<p>Suppose an attacker knows that a wallet controls US$100,000 and that its single GPG layer uses four independently generated words from this list. Under the stated model, the average cost of recovering that phrase is about <b>US$30.5 million</b>—far more than the possible prize. On those assumptions, brute force is economically unattractive to a purely profit-seeking attacker. That is the reasoning to compare, not a claim that four words safely protect every wallet below US$30.5 million.</p>
<p>The average cost is not a fee the attacker must pay before any chance of success: they can get lucky early, stop after a smaller budget or have a much cheaper method. Actual hardware, the file's password derivation, other targets and non-financial motives can change the decision. Plan for future Bitcoin value and the number of years the backup will remain useful, rather than matching today's value closely to one cost estimate.</p>
<h3>What the attacker knows—and may not know</h3>
<p>A GPG file does not directly disclose its passphrase word count or the Bitcoin balance in the encrypted wallet. A person finding an isolated file may not even know its contents are a wallet. A person finding only a random phrase has no address or balance to inspect. This <b>information asymmetry</b> can make selecting a profitable target harder.</p>
<p>But the attacker does not need certainty about either fact to start guessing: they can make estimates or obtain clues from filenames, public activity, a separate watch-only copy, known defaults or other information. OpenPGP's format and password-derivation parameters are inspectable. For the strength calculation, assume the method and word count are known. Treat the privacy of the amount and context as an additional advantage, not extra entropy or the basis of a guarantee that nobody will try.</p>
<h3>Why six words is the Vault starting recommendation</h3>
<p>Six random words provide a large additional margin over four or five while remaining manageable for most written recovery records. The generator therefore starts at six. This accommodates uncertainty about attack costs, future hardware, future wallet value and storage duration without requiring very long phrases by default.</p>
<p>Four or five words can be considered in a deliberately assessed model when they provide ample margin and simpler handling is important. Six is the starting choice when those assumptions have not been established. Longer phrases may be appropriate for other requirements; they are not a substitute for accurate redundant copies. EFF recommends at least six words for important password-manager and disk-encryption use, but that advice does not calibrate the GPG cost table here.</p>
<h3>Extra GPG layers: work adds, not multiplies</h3>
<p>An independently generated GPG layer adds another secret an attacker must recover when no layer secret is already known. In this format, successful decryption of a layer can be checked. The attacker can attack the outer layer, obtain the inner file, then attack that layer. For this sequential attack, <b>expected work and costs add</b>.</p>
<p>Using the same assumptions for both layers, two independent four-word GPG layers give roughly <b>US$61 million</b> and <b>285 days</b> of average sequential work on the same 10,000-GPU fleet. That is about twice the single-layer effort, <b>not</b> the strength of a single eight-word phrase. More hardware can change elapsed time. Known secrets or a retained inner copy bypass the corresponding work.</p>
<p>Core wallet encryption is a separate stage with a different password-to-key calculation. Its expected attack cost cannot be copied from this GPG table or added as another identical GPG layer. Keep its passphrase independent; additional GPG layers are mainly useful when they provide useful separation between holders or locations as well as extra guessing work.</p>
<h3>Connect strength with your recovery plan</h3>
<p>The basic recommendation in this Guide is <b>one Core passphrase + one different GPG passphrase + the final encrypted file</b>: three logical components. Duplicate each, keep the groups separate and test recovery. An extra GPG layer adds a fourth component and another recovery dependency. Use only the number of components you can keep independently available.</p>
<p>Longer phrases can require more copying, typing and checking. Reduce transcription and loss risk with legible records, exact comparison, redundant storage and recovery drills; do not rely only on memory. A modest phrase that meets a well-supported requirement and is reliably recoverable can be preferable to unnecessary complexity. A phrase whose guessing resistance is inadequate is not made sufficient by easier storage.</p>
<h3>Technical scope of the numerical example</h3>
<p>New Vault backups use <b>AES-256 CFB with MDC integrity protection</b> and <b>iterated-and-salted SHA-256 S2K, count 65,011,712 bytes</b>. S2K is the computation converting the passphrase into an encryption key. Its settings affect guessing cost but do not change the number of possible phrases. The 14,800-guess rate above is a scenario input, not a benchmark of this configuration. A measured attack rate for this exact format is needed before treating the figures as a security budget. Core wallet encryption and KeePassXC database encryption use different derivation methods.</p>
<p>Whole-file encryption protects contents, but not against a compromised computer recording the secret, a stolen passphrase, coercion or a lost required component. The GPG header, outer filename, size and timestamps may remain observable. Paper copies and encrypted files still deserve careful handling.</p>
<h3>Multiple GPG layers are not multisig</h3>
<p>GPG layers control access to the backup. Bitcoin multisig is a transaction rule requiring a specified number of signatures from different Bitcoin keys. Recovering a layered backup does not change the wallet's signing rule.</p>
<h3>References and assumptions</h3>
<p>Passphrase generation: KeePassXC User Guide, “Password Generator” — keepassxc.org/docs/KeePassXC_UserGuide. Random-word guidance: EFF, “Creating Strong Passwords” — ssd.eff.org/module/creating-strong-passwords. File format and derivation: RFC 4880, sections 3.7 and 5.3 — rfc-editor.org/rfc/rfc4880; GnuPG OpenPGP options — gnupg.org/documentation/manuals/gnupg/OpenPGP-Options.html. The installed backup source fixes the format and S2K values above. The GPU rate and price are declared illustrative inputs; these references do not certify them.</p>''',

'Backup & verify': '''<h2>Backup &amp; verify</h2>
<p>This is the backup-and-recovery check from tutorial steps 5–7. Keep redundant copies of every required component, not only the encrypted file.</p>
<p>A useful backup is a separate copy that you can actually open and use. Saving it is the first step; checking it and practising recovery are the next steps.</p>
<ol><li>Use <b>Wallet Backup</b> on Home for a wallet, or <b>Files → Create Encrypted Backup</b> for other selections.</li><li>Start with one GPG layer unless your recovery plan needs more. Generate and confirm a different phrase for each layer.</li><li>Choose a new .gpg destination in Private Workspace, another writable folder or external media, and create the backup.</li><li>Wait for verification to finish. Vault takes a consistent wallet snapshot, encrypts it, opens the result again and compares the recovered data with the snapshot. It also checks the destination copy.</li><li>If you saved in RAM, copy the backup to lasting external storage. Keep independent copies and separately recoverable secrets.</li><li>Practise a complete restore and a signing test with disposable data, including the people and software your recovery plan uses. Repeat the drill periodically, at least annually.</li></ol>
<p>A <b>snapshot</b> is a consistent copy taken for this backup. Loaded wallets are copied through Core; closed wallets use the read-only SQLite database backup method. One supported wallet.dat is encrypted directly; other files are packaged in TAR in RAM. The tool checks every layer and the full recovered result. A direct-wallet export is authenticated and compared again before its temporary session receipt is saved.</p>
<p>Only encrypted data are staged at the destination. Existing backup files are not overwritten and originals remain. <b>Verification does not make RAM permanent.</b> A checked .gpg file saved only in Private Workspace still disappears at shutdown. Shutdown warnings do not check whether the backup exists or is current.</p>
<p>The operation allows up to 16 layers, 10,000 TAR entries and 256 MiB per package, with lower limits when free RAM is tight. MiB is a file-size unit. Split larger sets. Cancelling discards temporary output but does not promise physical memory erasure. The private session forbids swap, which would otherwise let temporary memory spill onto a disk.</p>
<h3>Know your backup format</h3>
<p>A two-layer wallet backup can be named <b>wallet.dat.gpg.gpg</b>. Its outer layer opens to <b>inner.gpg</b>, and the last layer opens to <b>wallet.dat</b>, with no TAR extraction. Grouped files use a TAR container. Record the required layers in your instructions; a filename alone does not establish them. Vault also recovers older GPG/TAR and older OCB-format backups. Please test the exact recovery software you intend to use.</p>''',

'Finish Private Session': '''<h2>Finish Private Session</h2>
<p><b>Before closing Vault, save everything you need outside RAM.</b> That includes current wallet backups, required passphrases, password databases, notes and signed payment files. Keep the secrets separately recoverable according to your plan.</p>
<ol><li>Choose <b>Restart</b> or <b>Finish &amp; Shut Down</b>.</li><li>The first warning says RAM-only files will be lost. Choose <b>I've saved what I need</b> only after checking your own saved copies.</li><li>The second warning asks you to confirm the loss of unsaved session data. Continue to start the <b>five-minute countdown</b>.</li><li>The timer runs from <b>05:00 to 00:00</b>. You can still work. <b>Cancel countdown</b>, Esc or closing the countdown window cancels the power action. <b>Restart now</b> or <b>Shut down now</b> explicitly skips the remaining wait.</li><li>At the end, Core closes cleanly, the clipboard is cleared and the RAM session ends. If Core cannot close, the power action stops and the workspace remains available.</li></ol>
<p><b>This is a warning process, not a backup test.</b> It asks for no passphrases and does not verify that you saved a usable or current backup. Verification happens during backup creation; a recovery drill checks the wider plan.</p>
<p>External copies remain on their media. Power loss can end the session without any warning. RAM-only storage does not protect against someone inspecting a running computer's memory or a computer already compromised.</p>''',

'Sign a PSBT offline': '''<h2>Sign a PSBT offline</h2>
<p>A <b>PSBT</b> is a Partially Signed Bitcoin Transaction: a portable payment file carrying transaction details and signing information. The online Node prepares it; offline Vault reviews and signs it; the online Node broadcasts the completed transaction. The signing keys do not move with the payment file.</p>
<ol><li>On the synchronized Node, select the watch-only wallet, fill in Send, review recipient/amount/fee and choose <b>Create Unsigned</b>. Save the .psbt with <b>Save…</b> and copy it to your transfer USB.</li><li>In Vault, restore the signing wallet from its GPG backup when starting a new RAM session. Copy the PSBT into Private Workspace and open <b>File → Load PSBT from file…</b> in Core.</li><li>Check recipient addresses independently, check amounts and fee, and confirm that change belongs to your wallet. Stop if the details or wallet do not match.</li><li>Choose <b>Sign Tx</b> and enter the <b>Core passphrase</b>, not the external GPG phrase. Confirm that all required signatures are present.</li><li>Choose <b>Save…</b> and save a distinctly named signed PSBT in Private Workspace. Core's USB view is read-only; copy the signed file to USB using Files.</li><li>Back on Node, load the signed PSBT, review it and choose <b>Broadcast Tx</b>. Follow confirmations in Core.</li></ol>
<p>Keep only public exports or transaction files on the transfer medium. Do not move the original signing wallet, decrypted wallet backups or passphrase records onto the online Node. A fully signed payment file may be broadcast by anyone holding it; protect its privacy and do not sign a payment you are not ready to authorize.</p>
<p>Signing authorizes a specific transaction. Broadcasting sends it to peers; inclusion in a block provides a confirmation. A failure to broadcast is not fixed by exposing the signing keys online.</p>''',

'Recovery / inheritance': '''<h2>Recovery / inheritance</h2>
<p>The standard tutorial uses one encrypted file, its GPG secret and the separate Core secret. Obtain one usable copy of each component; for extra GPG layers, obtain each additional required secret too.</p>
<p>Write instructions that another intended person can follow. Keep them outside the encrypted backup, without placing every secret in the instructions. Identify the file copies, required secret holders, compatible software and how access can be obtained. Do not hide the only instructions inside the file they explain.</p>
<h3>With Vault</h3>
<ol><li>Open the encrypted backup in Decrypt Backup.</li><li>Enter all external GPG passphrases in any order. Vault finds which opens the current outer layer.</li><li>Recover into a new Private Workspace folder.</li><li>For a wallet, open <b>Bitcoin Core → File → Restore Wallet</b> and select the recovered wallet.dat.</li><li>Check known addresses and labels, and practise a signing test. A Core-encrypted wallet still needs its separate Core passphrase for signing.</li></ol>
<p>A current single-wallet backup recovers directly to wallet.dat. Grouped files and older TAR-based wallet backups recover from a checked TAR container. Older Vault OCB backups remain supported.</p>
<h3>Without Vault: an advanced fallback</h3>
<p>Use compatible GnuPG and Bitcoin Core on a trusted offline computer. Current backups need AES-256 CFB and OpenPGP MDC support. Older OCB files need support for that format. TAR is needed for grouped or older TAR backups, not a current direct-wallet backup. Test this fallback with a disposable backup before depending on it.</p>
<p>Prepare a private RAM folder first: technically, an owned <b>tmpfs</b> directory with <b>mode 0700</b> (only your account can access it), enough RAM and swap disabled. A normal Downloads folder is not a substitute. Use new output filenames and let GPG ask for the passphrases interactively; do not put secrets in commands, scripts or environment variables.</p>
<h3>Example: two-layer single-wallet backup</h3>
<pre>umask 077
gpg --output inner.gpg --decrypt wallet.dat.gpg.gpg &amp;&amp;
gpg --output wallet.dat --decrypt inner.gpg</pre>
<p>The first command opens the outer layer; the second opens the inner layer. Enter the outer secret first, then the inner one. For one layer, decrypt wallet.dat.gpg directly to wallet.dat. Restore that file with Core. There is no TAR extraction for this direct-wallet format. The <b>&amp;&amp;</b> means the next command runs only if the previous one succeeds; <b>umask 077</b> makes new files private to your account.</p>
<h3>Example: grouped files in a TAR payload</h3>
<p>After opening the known GPG layers, write the final result to <b>payload.tar</b>. First list its contents:</p>
<pre>tar --list --file payload.tar</pre>
<p>Check that every name is expected. Reject absolute paths, paths containing parent traversal such as ../, links, devices and other unexpected items. Then extract trusted contents into a new RAM folder:</p>
<pre>mkdir recovered &amp;&amp;
tar --extract --file payload.tar --directory recovered --no-same-owner --no-same-permissions</pre>
<p><b>Proceed only when every GPG command succeeds without an integrity/authentication error.</b> A failed command may leave unfinished output; do not use it. Standard GPG does not tell you the total number of Vault layers, so keep that in the plan. Vault validates archive paths for you; manual extraction does not replace those checks.</p>
<p>If an original .gpg or TAR file was one of the packaged documents, it remains that original file. Stop at the documented payload instead of repeatedly opening everything. Practise with the intended holders. Missing a required layer secret cannot be bypassed by Vault; forgetting a password manager's unlocking secret is another dependency.</p>''',

'Decrypt Backup': '''<h2>Decrypt Encrypted Backup</h2>
<p>Use this at tutorial step 7 and at the beginning of a later signing session. Recover offline, then restore wallet.dat in Core.</p>
<p>Decryption opens a locked backup and recovers its contents. Open <b>Decrypt Backup</b> on Home, double-click a .gpg file in Files, or choose <b>Decrypt Encrypted Backup</b> in its right-click menu.</p>
<ol><li>Enter the available external backup passphrases. Use <b>+ Add Passphrase</b> for additional layers; their order does not matter here.</li><li>Choose a new recovery folder name and select <b>Decrypt Backup</b>.</li><li>Wait for the checks to finish. Vault opens and checks each layer, then places the recovered wallet.dat or original packaged files in Private Workspace.</li></ol>
<p>Wrong or missing passphrases, damaged files and unsupported encryption can all cause failure. Correct or add the secret and retry when appropriate. Failed or cancelled recovery discards partial output, and existing files are not overwritten.</p>
<h3>A GPG file from another program</h3>
<p>Choose <b>Recover one ordinary GPG layer only</b> to open exactly one checked layer. Its output is named <b>recovered-file</b>. This mode does not guess whether your original content was itself encrypted; name and handle it deliberately. Normal Vault recovery recognises a complete supported wallet.dat or a validated TAR. An original .gpg file inside a TAR stays unchanged.</p>
<p><b>Recovered plaintext is unlocked information.</b> It stays in RAM and disappears at the end of the session unless deliberately exported. A recovered file is not by itself a verified backup of the current wallet. Please restore, check addresses and practise a test before trusting a recovery plan.</p>''',

'Watch-Only Wallet in Bitcoin Core': '''<h2>Watch-Only Wallet in Bitcoin Core</h2>
<p>A <b>watch-only wallet</b> is a public copy: it can watch addresses and help prepare a payment, but it has no private spending keys. Vault keeps the signing wallet offline; your online Node uses the public copy.</p>
<p>This is tutorial steps 8–10. The public copy belongs on Node; the signing-wallet backup and both passphrases remain separate and offline.</p>
<h3>Export from Vault</h3>
<ol><li>Open Core and select the signing wallet.</li><li>Choose <b>File → Export watch-only wallet</b>.</li><li>The save dialog starts in <b>Private Workspace</b>. Save the public copy as <b>watch-only.dat</b>. Core writes only to checked RAM locations in Vault.</li><li>Use Files to copy that exported public file to the transfer USB. Please check the filename so you do not move the original signing wallet by mistake.</li></ol>
<p>Mounted USB drives appear in the wide sidebar, but Core's view is read-only. Reopen a chooser or select USB Media after connecting a new drive.</p>
<h3>Restore on the online Node</h3>
<ol><li>Use Bitcoin Core <b>32.1 or newer</b> on the online computer.</li><li>Choose <b>File → Restore Wallet</b>, select watch-only.dat and give it a new wallet name.</li><li>Confirm that it is watch-only. Independently compare a receiving address with Vault before using it.</li></ol>
<p>The export is a native Core wallet database. It contains public <b>descriptors</b> (instructions for producing the wallet's addresses), address-book information and transactions, without private keys. It replaces Vault's earlier JSON export: this file does not need a separate Vault export button or Node JSON importer.</p>
<h3>Keep public information private</h3>
<p>The public copy can reveal addresses, labels and activity. Encrypt it with Files → Create Encrypted Backup for private storage or transfer when needed, then decrypt it on a trusted computer before Restore Wallet. It cannot recover the signing keys. Keep a separate verified backup of the original signing wallet using Wallet Backup.</p>
<p>An older wallet may need a <b>rescan</b>: Core checks older blocks for its transactions. A <b>pruned</b> Node has removed old block files to save space and may no longer have the required history. An unfinished scan is not a verified balance.</p>
<p>Prepare a PSBT online, check recipients, amounts, fee, change and wallet address information in Vault, then return only the signed transaction for broadcast. Save needed exports outside Private Workspace before shutdown.</p>''',

}
