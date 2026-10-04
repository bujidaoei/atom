# Implementation Plan: Secure responsive workspace preview

**Branch**: `codex/012-responsive-preview` | **Date**: 2026-10-04 | **Spec**: [spec.md](spec.md)

## Summary
Restore the existing three-mode toolbar and embed the isolated project preview. Give each view a stable resource namespace and path-scoped HttpOnly credential so concurrent revisions cannot overwrite each other. Preserve independent-window access. CR-001 also investigates and repairs the reported generated-JavaScript syntax failure and recovery pipeline using real failure evidence.

## Technical Context
Python 3.12+, FastAPI/Starlette, SQLite schema18, private verified artifacts; React19/TypeScript/Vite6 and existing Tailwind tokens. Existing pytest and real HTTPS Playwright Chromium/Firefox/WebKit tests. Linux Docker deployment with configured IP origin ledger/Caddy. No new dependency or schema migration is planned for preview. Preserve existing capacity/time/drain limits and immutable Pi lock. Acquisition deadline10s plus navigation deadline10s; viewport switches make no requests; refresh reuses a valid view.

## Constitution Check
Pass before and after design: clean worktree from fetched main; unrelated work preserved. Spec/tasks/evidence distinguish code, local tests, browser and live acceptance. Existing protected configuration/SSH keys keep credentials out of Git. No runtime/pi edits. Use only current schema18 deployment transaction and data/write fences; create a protected temporary rollback backup before cutover per constitution; remove only that backup after acceptance to respect the recorded no-retained-backup preference.

## Design
1. `preview_paths.py` owns canonical view namespace and root-resource redirects. Public selector is existing handoff hash, never a credential. Reject noncanonical paths/traversal/reserved generated paths.
2. Repository authorization matches selector plus secret/project/revision/source session. An explicit owner/source-scoped replacement revokes only the previous view atomically with issuance. Reuse v18 tables and quotas.
3. Port-specific `__Secure-atom_preview_<port>` cookie: Secure/HttpOnly/Lax/no Domain; Path=`/_atom/view/<selector>/`. Path limits ambient Cookie header growth, not authority; console proof remains essential across same-IP ports.
4. Root-relative requests redirect using an exact same-origin scoped Referer. Redirect serves no content; destination independently authenticates. Missing/ambiguous selector denies. Content uses same-origin referrers; no generated source rewriting.
5. Trusted bootstrap consumes grant, checks authenticated entry availability, emits UI-only status and navigates to scoped root. Trusted resume rechecks access on refresh. Parent validates source window, origin, selector, message shape; status never authorizes content or functional verification.
6. Preview-only CSP allows exact configured console frame ancestor; retain script/storage capability and existing network/worker/form restrictions. Public policy unchanged. Allowed console is derived from validated same-IP deployment topology.
7. `IsolatedPreview` owns generation fencing, acquisition, deadlines and retry. `PreviewSurface` measures panel and uniformly scales fixed768/390 widths. iframe identity survives mode changes. Toolbar supports existing link or fresh-grant popup without showing capability URLs.

## Visual Contract
Extension of approved Atom design: brand fidelity10, variance2, motion2, density7, asset dependence1. Reuse IBM Plex Sans/Mono, neutral/brand tokens, existing spacing/radii/flat shadows and device/refresh/external icons. Preserve selected/focus/disabled states. No unrelated redesign. Tablet/mobile fit narrow panels without changing internal layout width.

## Compatibility
Test relative/root-relative HTML/CSS/module/image resources and scoped navigation. Pages explicitly suppressing referrers or removing namespace through History API lose reliable root routing and fail closed; never choose latest revision. Same-IP HTTPS is same-site; test Lax-cookie embedding on all engines. Future cross-site domains need separate session transport acceptance.

## Project Structure
- `specs/012-responsive-preview/`: specification/research/model/protocol/tasks/evidence/deployment.
- `backend/app/preview_{access,cookie,paths,exchange,service,view}.py`, `routers/preview_access.py`: authorized immutable views.
- `frontend/src/lib/previewAccess.ts`, `workspace/{PreviewTab,PreviewToolbar,PreviewSurface,IsolatedPreview}.tsx`: lifecycle/viewport.
- Existing preview repository/HTTP/real TLS browser tests plus targeted generation repair tests.

## Execution and Acceptance
Write contract/failure tests first, implement scoped backend, build frontend/lifecycle/geometry, run real TLS browser/security matrix and inspect screenshots, investigate CR-001 real failure and implement bounded repair, run targeted integration, build exact labelled Linux image, push/synchronize main, deploy with current-generation gates, verify authenticated live three-mode and real generation recovery, synchronize final evidence.
