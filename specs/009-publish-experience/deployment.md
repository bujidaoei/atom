# Deployment and rollback record

Status: **not deployed**. This document separates observed production facts, rehearsal, and cutover evidence. Do not mark T013/T014 complete until every applicable entry below has a real result.

## Production inventory, read only

- Server: `159.75.231.98`, existing `atom-candidate` container; mounted application volume `/home/ubuntu/atom-staging/94bfcd7/data` → `/data`.
- Current application schema 10, 36 projects, 182 revision records, 62 registered snapshot artifacts totaling 1,023,761 bytes; 62 `.atomsnap` files observed. One project has a legacy public slug. The old `/p/{slug}` content is still served from `/data/published` on the console site.
- Existing public entry is the IP under `/atom/`. The owner has no domain and requests IP-only publication. Independent project browser origins and console-cookie isolation remain unresolved. Private COS storage does not provide this browser origin; a second port alone is insufficient because cookies are shared across ports.
- Server has approximately 11 GB free at inspection. No migration, COS import, service restart or public route change has occurred for feature 009.
- A root-private online SQLite backup exists at `/home/ubuntu/atom-staging/publish-experience-rehearsal-20261002/atom.db` (18,538,496 bytes, SHA256 `5e40bd7a746dc44fbc8abf84bf397c1edda738fe2e72c03e90d65e7d53ac3912`). A separate `migrated-fixed/` rehearsal copy completed schema10→16 with six verified predecessor backups, preserved counts (36/182/62/0), integrity and foreign key checks. The rehearsal discovered and fixed WAL-mode copy handling before schema12. This online database backup is **not** a quiesced full-volume cutover backup and the running service remains at schema10.

## Protected sequence

1. Record exact Git revision, image digest, runtime/pi source lock, current Caddy configuration, compose inputs, container health and database/broker versions. Take private SQLite online backup plus immutable artifact/published directory copy and verify checksums. Keep source volumes untouched.
2. Rehearse schema 10→11→12→13→14→15→16 against the backup in an isolated container built from that revision, with a distinct artifact directory and no public network routing. Check every predecessor backup and `verify`, `integrity_check`, `foreign_key_check`, project/publication counts and idempotent rerun.
3. Import all registered local artifacts using `python -m app.artifact_transfer --database ... --local-artifacts ...` with COS credentials only in the private service environment. The command checks source and COS bytes and emits a content-neutral inventory digest; partial transfer has no success receipt and may be retried. Run again after quiescing writers and compare receipt/digest before switching authoritative reads.
4. Handle the one legacy public site explicitly: retain its old link until exact published bytes have been captured as an immutable release on the isolated content site, owner/audience are checked, and the public browser flow succeeds. Do not silently point the old URL at a mutable draft. Record redirects or a sunset plan with user-visible continuity.
5. Configure the independent content ingress, HTTPS, host suffix, `ATOM_CONTENT_CONSOLE_BASE_PATH=/atom`, mounted database, COS settings and private browser capability. Do not expose COS keys or the shared bucket. Test a direct anonymous page, scripts/localStorage, owner-only snapshot, historical preview, unpublish, restore and foreign-account denial on both viewport sizes.
6. Deploy the exact tested image and database revision with a protected cutover and measured rollback. A rollback to an older image cannot read schema16, so preserve the pre-migration database and artifact backups and rehearse paired image/data restoration. If any health or acceptance gate fails, restore the complete pair rather than downgrading SQLite in place.

## Evidence still required

- Source commit/PR and target image digest: pending.
- Private backups and restore test: pending.
- Linux runtime/verifier/ingress, COS transfer and content migration: pending.
- Target owner/public production browser acceptance and rollback drill: pending.
