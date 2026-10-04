# Acceptance
1. Run targeted pytest contract suites plus existing workflow/migration/release regressions; build frontend and runtime.
2. Create real test project, wait for initial contract, refine twice (add audio then add mute), ensure no code build before approval.
3. Preview initial snapshot; current remains unchanged. Restore and reload; source document equals restored document and later history remains.
4. Refine restored version, approve displayed ID, inspect build input binding and actual generated app audio/mute behavior.
5. Test malformed model result, timeout/cancel, stale tab, duplicate key, cross-owner/project, old project baseline and multi-page history.
6. Desktop/mobile real browser: no exceptions/overflow, buttons accessible, pending text survives failure, build cannot discard edits.
7. Back up and rehearse migration, deploy exact committed image, verify public health/revision and owner workflow. Record IDs and outcomes in evidence.md, never secrets.
