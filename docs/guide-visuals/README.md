# Vault Guide visuals and Home order — 16 October 2026

All 18 Guide chapters now contain a local explanatory diagram. The diagrams are drawn from measured vector commands using existing QtGui; the UI needs no browser, JavaScript, network, SVG decoder or additional packages. Equivalent descriptions remain selectable text below each illustration. The SVG files in this directory are review artifacts generated from the same commands.

The encryption chapter has keyboard-accessible native controls for 1, 2 and 3 example GPG layers. It also contains a separate comparison between backup access and Bitcoin multisig authorization. These controls change only the illustration and never open files, inspect wallets, encrypt data or collect secrets.

The Guide retains 14 pt body text, 13 pt navigation and subtitle, 22 pt chapter titles and 17 pt subheadings. Diagram labels are measured at 18–20 px and reflow instead of shrinking. On windows narrower than 1000 px a chapter selector replaces the sidebar. Paragraphs retain comfortable line spacing; image paragraphs avoid artificial extra blank space.

## Home application order

1. Bitcoin Core
2. Wallet Backup
3. Decrypt Backup
4. KeePassXC
5. Editor
6. Brasero
7. Print & Labels
8. Files
9. Terminal
10. Vault Guide

Application commands and custody behavior are unchanged. Source/runtime desktop checks use the same order. The new Guide module is included in the reviewed runtime hashes and is explicitly required by the installer build hook.

## Validation

- Guide: all 18 chapters at 800×600, 1024×768, 1366×768 and 1920×1080; no horizontal overflow, illustrated content present and equivalent text available.
- The same checks pass at Qt scale factor 2, including 1/2/3-layer switching and compact chapter navigation.
- All 60 primary vector-layout combinations pass label-bound checks; the backup/multisig comparison was rendered and visually reviewed as well.
- Home: existing Qt geometry checks pass at four viewport sizes. Actual Tab traversal follows all ten requested application titles.
- Source/template equality, runtime hash checks, Home/Guide/printing source checks, keyboard/icon/UI gates, removed-component checks and changed shell/Python syntax pass.
- Existing cryptographic and Core implementations were not changed by this UI update.

Reproduce the new Guide checks with `python3 tools/core-vault/test-guide-visuals.py`. Use `--output docs/guide-visuals` to refresh screenshots and records. Use `QT_SCALE_FACTOR=2` for the high-DPI run. The CI workflow also runs the Guide check.

Screenshots here are offscreen previews. Home preview icons may use host-theme fallbacks; bundled production artwork was not changed. This UI revision still needs a newly built ISO and Live/installed VM acceptance. Existing booted VMs contain the earlier image.
