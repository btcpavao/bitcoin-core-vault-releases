"""Plain-language Vault Guide. Offline text only; no wallet or network access."""
from math import log2

# Historical teaching scenario, not a current rental quote or a Vault benchmark.
WORDLIST_SIZE = 7776
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
'Home & keyboard': '''<h2>Home &amp; keyboard</h2>
<p><b>Welcome to Bitcoin Core Vault.</b> This is the offline computer in a two-computer setup. Vault keeps the secret information used to approve a Bitcoin payment. Your separate online Node checks the blockchain, prepares payments and sends signed payments to the Bitcoin network.</p>
<h3>A few useful words</h3>
<p><b>Wallet:</b> a file that holds your Bitcoin address information and, for a signing wallet, the private keys that approve spending. The file is not a bag of coins: Bitcoin's network records who can spend.</p>
<p><b>Passphrase:</b> a password made from several words. <b>Encrypt</b> means lock information so it needs a secret to read it. <b>Decrypt</b> means unlock it. A <b>backup</b> is a separate saved copy; <b>restore</b> means use that copy again.</p>
<p><b>RAM</b> is temporary working memory. <b>Private Workspace</b> is a folder in RAM. Its files disappear when the private session ends, even when Vault is installed on the computer. An external USB drive or a written disc keeps files after shutdown.</p>
<h3>Find your way around</h3>
<p>Press <b>F12</b> to show Home, and F12 again to return to your application windows. Click a launcher to open a tool. With a keyboard, use <b>Tab</b> or <b>Shift+Tab</b> to move between controls and <b>Space</b> to activate the selected control.</p>
<p>Restart and Finish &amp; Shut Down show two warnings and then a five-minute countdown. Cancel is selected by default. Press <b>Esc</b> to keep working. Please read <b>Finish Private Session</b> before your first shutdown.</p>''',

'Bitcoin Core': '''<h2>Bitcoin Core</h2>
<p>Bitcoin Core is the wallet application inside Vault. Use it to create a wallet, check addresses, restore a wallet backup, and review and sign payment files while offline.</p>
<h3>What stays, and what disappears?</h3>
<p><b>The active wallet and Core's working files stay in RAM.</b> They disappear at shutdown or restart in both Live and installed Vault. Installing Vault keeps Debian and the applications on disk; it does not make this private session permanent.</p>
<h3>Your usual workflow</h3>
<p>Create or restore a wallet in Core → optionally encrypt its private keys → make and verify a backup → save independent copies outside RAM → review and sign payments offline when needed.</p>
<p>Open <b>Wallet Backup</b> on Home for a checked wallet export. For signed payment files or public watch-only exports, save in <b>Private Workspace</b> and copy the finished file to USB with <b>Files</b>. Core can read a mounted USB, but its USB view is read-only: it does not save directly to that drive. Copy input files into Private Workspace to keep working after disconnecting the drive.</p>
<h3>Two different passwords may have different jobs</h3>
<p><b>Core wallet encryption</b> locks the private keys used for signing. It does not hide every part of wallet.dat: addresses, labels and transaction history can still be readable. <b>GPG backup encryption</b> locks the whole exported file. Keep the Core passphrase separate from the GPG passphrase; opening the backup does not automatically unlock spending.</p>
<p>Vault keeps networking disabled. It does not download the blockchain or broadcast payments. Core's first synchronization panel is hidden automatically once; its bottom synchronization indicator can show it again. An offline balance may be incomplete or out of date. Use the online Node for current history, while independently checking every payment in Vault.</p>''',

'KeePassXC': '''<h2>KeePassXC</h2>
<p>KeePassXC generates random passwords and passphrases. Home opens its <b>Passphrase</b> generator with <b>six words</b> selected. You do not need to create a password database just to generate a phrase.</p>
<ol><li>Choose the word count you intend to use.</li><li>Generate a new random phrase. Please do not replace words with favourite words or turn it into a familiar quotation.</li><li>Copy it exactly into the backup passphrase and confirmation fields.</li><li>Keep a separate, recoverable record of that secret. Generate a fresh phrase for a different encryption layer.</li></ol>
<p>The <b>Encryption security levels</b> chapter compares 4, 5 and 6 random words using the earlier illustrative attack-cost model. The number of words is your choice; six is the starting setting, not a rule forced by the application.</p>
<h3>The clipboard is temporary shared storage</h3>
<p>Copying puts the secret on the clipboard so you can paste it. <b>Clear clipboard after</b> starts unchecked, allowing time to copy several independent secrets. Other applications in this session may read the clipboard while the secret remains there. Replace or clear it when finished. No clipboard-history application is installed by this workflow.</p>
<p>For automatic clearing, open <b>Tools → Settings → Security → Clear clipboard after</b> and choose a time. Relaunching KeePassXC keeps that choice within the current private session. A new Vault session starts with the image defaults. Finish Private Session clears the clipboard.</p>
<p>A KeePassXC database can store recovery records, but it is another file to back up and another password to recover. Do not put the only database inside the backup it unlocks, or its only password inside the database. Keeping all layer passphrases together also removes the separation you intended.</p>''',

'Brasero': '''<h2>Brasero</h2>
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
<p>Use this tool for printed recovery instructions, backup inventories, test pages and labels for USB drives or discs. A clear label helps you find the right backup later.</p>
<p>Templates do not automatically insert private keys, seed phrases or wallet passwords. Keep ordinary labels free of secrets: a backup name, date and location reference are usually enough.</p>
<p>Printing a secret creates another copy on paper and may leave traces in the printer. Treat that paper and printer deliberately. Store recovery instructions where the intended person can find them without first opening the encrypted backup they explain.</p>''',

'Files': '''<h2>Files</h2>
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
<p>Editor opens plain-text notes. Use it for a backup inventory, a checklist or recovery instructions someone else can understand.</p>
<p>Where you save determines whether the note lasts. <b>Private Workspace is temporary</b>; an intentional copy on external media remains after shutdown. Keep temporary sensitive notes in Private Workspace and encrypt them before saving a lasting copy when needed.</p>
<p>For ordinary recovery instructions, describe which files and secrets are needed without writing all secrets into the same document.</p>''',

'Terminal': '''<h2>Terminal</h2>
<p>Terminal is a window where you type commands instead of clicking buttons. Most everyday Vault work can be done without it.</p>
<p>Use it for a verified advanced procedure or a requested diagnostic. <b>RPC</b> means commands sent to Bitcoin Core's local control interface. It is not a separate wallet or a Bitcoin website.</p>
<p>Read a command before running it. Commands can change temporary files and external drives. Please do not paste untrusted commands or put a real passphrase into a command, script or environment variable. Let GPG ask for the secret in its password prompt.</p>
<p>The Recovery / inheritance chapter includes a standard GPG example. Use its RAM-only working location instructions, not a persistent Downloads folder.</p>''',

'Private Workspace': '''<h2>Private Workspace</h2>
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
<ol><li>Open Bitcoin Core and create the wallet you intend to use. Start with a disposable test wallet while learning.</li><li>If you want Core to lock the wallet's private keys, generate a separate random Core passphrase and use Core's wallet-encryption option.</li><li>Open <b>Wallet Backup</b> on Home and choose a new .gpg destination. Private Workspace is allowed, but remember that it is temporary.</li><li>Generate a fresh GPG backup passphrase in KeePassXC and confirm it. One GPG layer is the default. Add separate layers only when your recovery plan needs them.</li><li>Create the checked backup, save independent copies outside RAM, and keep every required passphrase separately recoverable.</li><li>Restore a disposable copy, compare addresses and practise signing a test payment before relying on the process.</li></ol>
<p>Core encryption and backup encryption are separate. A wallet can receive external GPG protection whether or not you encrypted its keys in Core. The Core passphrase is not entered into the GPG recovery dialog; it is needed later for signing if Core encryption is enabled.</p>''',

'Generate a passphrase': '''<h2>Generate an encryption passphrase</h2>
<p>A passphrase is a password written as words. What matters here is that the words are <b>independently chosen at random</b>, not that they form an impressive-looking sentence.</p>
<ol><li>Open KeePassXC from Home. The generator starts on Passphrase with six words.</li><li>Select the intended word count and large EFF wordlist, then generate locally.</li><li>Keep the exact words, order, spaces and capitalization. Please do not change them into a quotation or a personal phrase.</li><li>Record the secret through your recovery arrangements. Generate a new phrase for a different layer, not a small variation of the first one.</li></ol>
<p>As a rough comparison, six random words from the full 7,776-word EFF list give about 77.5 bits of unpredictability; eight give about 103.4 bits. More bits mean more possible phrases for an attacker to search. A different or filtered wordlist has a slightly different count. The next chapter explains 4, 5 and 6 words with a simple time-and-cost model.</p>
<p><b>The word boxes in this Guide are placeholders, not passwords to use.</b> Always generate your own. Clipboard clearing starts off; you can enable it in Tools → Settings → Security. Please keep a recoverable copy without placing every independent layer's secret in one location.</p>''',

'Encryption security levels': '''<h2>Encryption &amp; Backup Security Levels</h2>
<p><b>Choose protection for the value and the time you need to protect.</b> Start with a manageable plan, then add strength where it helps. More required secrets also mean more things you must recover correctly.</p>
<h3>What does brute force mean?</h3>
<p>Someone who steals an encrypted backup can try candidate passphrases on their own computers. This is an <b>offline guessing attack</b>: they do not need permission from Vault and there is no online account that locks them out. Randomness makes the candidate list large. The file's password-to-key calculation makes each guess cost work.</p>
<h3>4, 5 or 6 random KeePassXC words: a rough comparison</h3>
<p><b>Illustrative calculation, not a measured cracking test of this ISO.</b> We retain the earlier discussion's assumptions: the full 7,776-word EFF list, 10,000 graphics processors (GPUs), 14,800 complete guesses per second per GPU, and US$0.89 per GPU-hour. These are model inputs, not a current rental quote or a guaranteed attacker cost. Each row is the <b>average successful search</b>, roughly half of all possible phrases.</p>
''' + attack_table() + '''
<p>The examples are lengths, not sample secrets: <b>word 1 · word 2 · word 3 · word 4</b>; add a newly generated fifth or sixth word for the longer lengths. Never use those literal placeholders. In this model every extra independent word multiplies the search work by 7,776.</p>
<h3>How to use these numbers</h3>
<p>Compare the possible value an attacker could recover with the cost of attacking it, and leave a <b>large margin</b> for cheaper hardware, improved attacks, price changes and years of storage. For example, US$100,000 is far below the model's US$30.5 million four-word cost; US$10 million is much closer. Neither comparison proves that four words are safe for that amount. Five and six words provide much more guessing resistance at a small typing cost; six remains Vault's generator default.</p>
<p><b>Do not treat a dollar figure as a maximum safe balance.</b> The time is not a minimum waiting period: an attacker can be lucky early. With only 1% of the combinations tried, success probability is about 1% under this uniform-random model. More GPUs shorten the time; at the same rental rate they do not reduce total model cost. Faster or cheaper guesses reduce the cost. The enormous long-term figures are comparisons at a fixed assumed speed, not forecasts of computers millions of years from now.</p>
<p>These estimates concern guessing a secret, not malware, a copied passphrase, coercion, a lost backup or a broken recovery plan. If an attacker obtains the secret directly, this cost table offers no protection.</p>
<h3>What the calculation does and does not measure</h3>
<p>There are <b>7,776 to the power of the word count</b> possible ordered phrases. Average guesses are approximately half that number. Divide by the combined guesses per second for time; multiply the hours by the rental cost of all GPUs for dollars. The decimal units above use a billion as 1,000 million and a quadrillion as 1,000 trillion.</p>
<p>The earlier 14,800-guess assumption was an extrapolation for a SHA-512-based GPG password calculation, not a benchmark of the current Vault backup. This image uses <b>SHA-256, iterated-and-salted S2K, count 65,011,712 bytes</b>. S2K is the work that turns your words into an encryption key; a salt is extra random data that makes each file's calculation different. The current file format, S2K settings and actual attack hardware must be benchmarked before treating the numbers as its cracking cost. This table must not be substituted for the different Core-wallet or KeePassXC-database password calculations.</p>
<h3>Bitcoin Core wallet encryption</h3>
<p>Core locks its private signing keys with the Core passphrase. Public addresses and transaction records may still be readable in wallet.dat. You need a usable wallet file to recover; spending from a Core-encrypted wallet also needs its Core passphrase.</p>
<h3>One GPG layer — the default</h3>
<p>A single supported wallet.dat is encrypted directly. Other files and folders first become a standard TAR package. GPG locks the entire exported payload, using <b>AES-256 CFB with MDC integrity protection</b>. In plain language: AES encrypts the contents and the integrity check helps detect damage or changes. You need the encrypted file and its GPG passphrase; no GPG keypair is needed for this symmetric backup encryption. Keep redundant copies of both the file and a separately protected recovery record for the secret.</p>
<h3>Two or more GPG layers</h3>
<p><b>+ Add Encryption Layer</b> puts another locked layer around the previous one. Generate a different passphrase for each layer. For example: original wallet → lock with A → lock that result with B. Recovery needs one intact outer backup and both A and B. The tool permits up to 16 layers, including 10, but a simpler plan is easier to practise.</p>
<p>For a three-layer plan, you might keep redundant file copies in two locations, redundant A records with trusted holders in one region, B in a second and C in a third. Copies within a group protect against loss; every required group must still be available. Consider travel, cooperation between holders, incapacity and access delays. Please do not multiply the table's costs together: individually checkable layers can be attacked in sequence.</p>
<p>Keep only the intended outermost backup in distributed storage. An inner copy bypasses the layers outside it. Reusing the same phrase or keeping all secrets together removes the intended independence. The app rejects duplicate external phrases but cannot compare them with the separate Core secret.</p>
<p>Opening all GPG layers reveals the wallet file and its metadata; an internally encrypted wallet still needs the Core passphrase for signing. The outer filename, size and dates remain visible. An integrity check does not identify who created a file.</p>
<h3>Multiple GPG layers are not multisig</h3>
<p>Layers control who can <b>open a backup</b>. Once recovered, the wallet still follows its ordinary Bitcoin signing rules. <b>Multisig</b> means a payment requires a specified number of signatures from different Bitcoin keys. Adding backup layers does not create that signing rule.</p>
<p>Extra locations may make immediate theft or coercion harder, but cannot guarantee safety from ongoing coercion or a compromised signing computer. Keep the recovery instructions understandable to your family, and practise obtaining every required component.</p>
<h3>Sources and model notes</h3>
<p>EFF, “Dice-Generated Passphrases” (eff.org/dice), explains random word selection and recommends six words for most applications. The KeePassXC User Guide describes its Passphrase generator (keepassxc.org/docs/KeePassXC_UserGuide). GnuPG's “OpenPGP protocol specific options” documents the S2K controls (gnupg.org/documentation/manuals/gnupg/OpenPGP-Options.html). These sources do not certify the assumed GPU rate or dollar cost. Model arithmetic reviewed 9 November 2026; no network connection is needed to read this Guide.</p>''',

'Backup & verify': '''<h2>Backup &amp; verify</h2>
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
<p>A <b>PSBT</b> is a Partially Signed Bitcoin Transaction: a payment file prepared online, checked and signed offline, then brought back online to be sent. Signing approves the payment; <b>broadcasting</b> sends the signed payment to the network. Vault does the first, not the second.</p>
<ol><li>Bring the unsigned PSBT on removable media. Copy it into Private Workspace with Files, then open it in Core. Core can also read the USB directly.</li><li>Independently check the recipients, amounts, fee and <b>change</b>—the part returned to an address of your own wallet. Check that the right wallet and address information are used.</li><li>Sign with the intended wallet. If Core encrypted its private keys, enter that separate Core passphrase.</li><li>Save the signed PSBT in Private Workspace; Core's USB view is read-only.</li><li>Copy only the signed PSBT to the transfer medium with Files.</li><li>Return it to the online Node for broadcast. Vault stays offline.</li></ol>
<p>For a newly attached drive, reopen an already-open chooser or select USB Media. Keep the original signing wallet and its decrypted backups in the offline environment. A PSBT is a payment-transfer file, not your signing-wallet backup.</p>''',

'Recovery / inheritance': '''<h2>Recovery / inheritance</h2>
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
<p>Decryption opens a locked backup and recovers its contents. Open <b>Decrypt Backup</b> on Home, double-click a .gpg file in Files, or choose <b>Decrypt Encrypted Backup</b> in its right-click menu.</p>
<ol><li>Enter the available external backup passphrases. Use <b>+ Add Passphrase</b> for additional layers; their order does not matter here.</li><li>Choose a new recovery folder name and select <b>Decrypt Backup</b>.</li><li>Wait for the checks to finish. Vault opens and checks each layer, then places the recovered wallet.dat or original packaged files in Private Workspace.</li></ol>
<p>Wrong or missing passphrases, damaged files and unsupported encryption can all cause failure. Correct or add the secret and retry when appropriate. Failed or cancelled recovery discards partial output, and existing files are not overwritten.</p>
<h3>A GPG file from another program</h3>
<p>Choose <b>Recover one ordinary GPG layer only</b> to open exactly one checked layer. Its output is named <b>recovered-file</b>. This mode does not guess whether your original content was itself encrypted; name and handle it deliberately. Normal Vault recovery recognises a complete supported wallet.dat or a validated TAR. An original .gpg file inside a TAR stays unchanged.</p>
<p><b>Recovered plaintext is unlocked information.</b> It stays in RAM and disappears at the end of the session unless deliberately exported. A recovered file is not by itself a verified backup of the current wallet. Please restore, check addresses and practise a test before trusting a recovery plan.</p>''',

'Watch-Only Wallet in Bitcoin Core': '''<h2>Watch-Only Wallet in Bitcoin Core</h2>
<p>A <b>watch-only wallet</b> is a public copy: it can watch addresses and help prepare a payment, but it has no private spending keys. Vault keeps the signing wallet offline; your online Node uses the public copy.</p>
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
