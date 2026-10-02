# IP-only publication design candidate

**Status:** architecture under review; no production activation or acceptance claim. The owner chose the server IP and has no domain. The design must preserve native `localStorage` for generated applications, including after a release is restored.

## Existing boundary that must change

The current `/preview/{project_id}` response and workspace iframe are both on the console origin, and the iframe has `allow-scripts allow-same-origin`. The console reads `contentDocument` to run the UI's functional checks. Thus isolating only the future public URL would leave generated preview code on the privileged console origin. Moving preview and checks is mandatory. The existing content service uses a distinct DNS host per **release**; on an IP address, a stable **project** origin is needed so publication updates and restores preserve browser storage.

## Candidate topology

- Console stays at `https://159.75.231.98/atom/` on port 443.
- Each project reserves two immutable HTTPS ports: one for its owner-only draft/historical preview, one for its public live page. A project's ports never change across releases and are never assigned to another project, even after unpublish or deletion; browsers can retain storage indefinitely. A bounded pool and an honest capacity error are required. No project shares an origin with another project or the console.
- The trusted content process serves exact registered snapshot bytes from private COS. It selects the project from a durable port-to-project ledger, then selects the live release or one authorized preview release. The public endpoint returns only public live bytes. The preview endpoint uses a binding-scoped, HttpOnly capability and never treats a release ID as authorization.
- Caddy gets explicit HTTPS IP listeners for committed project ports and passes an unmodified, validated Host. Unknown ports fail closed. The console listener does not proxy generated paths. A controller renders complete configuration from the ledger, validates it with `caddy adapt`, reloads atomically, probes each new listener, and reconciles after restart. Publication cannot become live until its listener is serving the intended project. Rollback pairs database state with the prior ingress configuration.
- The console session remains HttpOnly, but a new independent console-origin proof is required on **every** authenticated API request. Login stores only its hash in the durable session ledger and returns the proof to trusted console JavaScript, which keeps it in console-origin storage and sends it as a custom header. Existing sessions without proof must reauthenticate at cutover. The proof prevents a cross-port script from using or fixing a shared-host cookie alone, including browsers without `__Host-Http-` enforcement. All unsafe authenticated requests also require the exact console Host and Origin. No credentialed cross-origin CORS allowance is issued.
- Legacy published `/p/{slug}` URLs remain until the exact old bytes and link continuity are verified. The current same-origin draft preview is removed only after the isolated owner preview and functional checks have browser-tested replacements. No `allow-same-origin` sandbox on a console-origin generated document is accepted as an isolation boundary.

## Atomicity and isolation tests before adoption

1. Browser matrix: Chrome, Firefox and WebKit direct navigation, native `localStorage` persistence across public publish/update/restore, project A/B separation, preview/public separation, same-IP cookies across ports, and old/new sessions. Test desktop and mobile.
2. Hostile generated page: attempt to read parent DOM, console storage/API responses, another project's storage, private historical HTML, content-session cookies and COS credentials; attempt cookie planting, credentialed simple POST/form/GET, preflighted custom-header requests, popup/opener navigation and service worker registration. Console writes must reject foreign Origin/proof before mutation.
3. Release lifecycle: concurrent port reservations, pool exhaustion, listener reload failure, TLS renewal, port conflict, process crash between listener and database commits, unpublish, re-publish, restore and rollback. No failed stage may expose a different project or change the prior live release.
4. Production ingress: certificate-verified IP HTTPS on all chosen ports, Tencent Cloud firewall reachability, no console Cookie forwarded to content logs, exact Caddy config digest and restart reconciliation. Private COS remains inaccessible directly to anonymous users.

This is a candidate because Caddy syntax, local browser storage behavior and console-origin CSRF can be addressed in parts; the complete browser, credential and deployment gates are still open. Do not mark T012a2/T013/T014 complete based on this document.
