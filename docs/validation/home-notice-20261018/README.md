# Home warning on its own line

2026-10-18: Added an explicit line break before the backup warning. Full card and text sizes are preserved; outer vertical padding is reduced only on short screens to prevent overflow. Home self-test passes at 800x600, 1024x768, 1280x800 and 1920x1080; captures verify the line break and complete warning at 800x600 and 1366x768. Shred manifest and UI source checks pass. Host icon fallbacks are used in captures; production artwork is unchanged. A new ISO build is required for this final layout edit.
