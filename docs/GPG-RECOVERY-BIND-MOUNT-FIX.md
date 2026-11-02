# GPG recovery on the RAM HOME bind mount

On 14 October 2026, the genuine GPG recovery dialog in the frozen
`bd5fd3e7` ISO authenticated the input but failed before publishing its result.
The candidate ISO SHA-256 was
`eeb052c792155712e044eb24d140732169967fbf562cc8cc26694b06120993c5`.
That image must not be promoted as a completed GPG release.

Vault binds `/run/core-vault/home` to `/home/vault`. The two paths belong to the
same tmpfs device, but Linux no-overwrite rename cannot cross these mount
points. Recovery staged its plaintext under `/run/core-vault/export` and
attempted to publish it through the HOME bind mount, producing `EXDEV`.

Backup package **0.6.1** stages GPG working state and provisional plaintext in
the already verified, owned 0700 RAM-only Private Workspace. Authentication
and cancellation complete before atomic no-overwrite publication on that same
mount. The ciphertext, original wallet and existing recovered files remain
unchanged. No persistent plaintext or fallback copy is introduced.

A disposable ordinary Vault guest reproduced the baseline `EXDEV` and then
loaded the exact fixed `backup.py` as a fixture alongside the stock runtime and
GnuPG. Six checks passed: baseline failure reproduction, authenticated exact
recovery to RAM, existing-output refusal, wrong-passphrase refusal,
cancellation, and unchanged ciphertext. See
[gpg-recovery-bind-mount-regression.json](gpg-recovery-bind-mount-regression.json).
Only request/progress/message dialogs were substituted in that focused
regression; native GUI and rebuilt-image acceptance are separate checks.

The focused fixture is `tools/core-vault/test-gpg-recovery-bind-mount.py`.
It is delivered to an owned virtual USB with the fixed source as
`ci-fixed-backup.py`, and runs as the normal Vault desktop user on the baseline
image. It neither changes installed code nor accesses real wallets.
