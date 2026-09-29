import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';

const argument = (name, fallback) => {
  const prefix = `--${name}=`;
  const value = process.argv.find((item) => item.startsWith(prefix))?.slice(prefix.length);
  return value || fallback;
};

const out = resolve(argument('out', 'apps/desktop/out/make/release-assets/RELEASE-NOTES.md'));
const [rootPackage, desktopPackage] = await Promise.all([
  readFile('package.json', 'utf8').then((text) => JSON.parse(text)),
  readFile('apps/desktop/package.json', 'utf8').then((text) => JSON.parse(text)),
]);
const version = argument('version', desktopPackage.version);
const tag = process.env.GITHUB_REF_NAME ?? `desktop-v${version}`;
const commit = process.env.GITHUB_SHA ?? 'local';

if (rootPackage.version !== desktopPackage.version) {
  throw new Error(
    `Root version ${rootPackage.version} does not match desktop version ${desktopPackage.version}.`,
  );
}
if (version !== desktopPackage.version) {
  throw new Error(
    `Release notes version ${version} does not match desktop package ${desktopPackage.version}.`,
  );
}

const notes = `# QoderWake ${version}

Source: \`${tag}\` @ \`${commit}\`

## Changes

- V4 keeps AI on the self-hosted LiteLLM gateway only. Provider keys stay server-side.
- Web and Windows/macOS/Linux Desktop now use the same Feishu OAuth identity service. Web uses an HttpOnly session cookie; Desktop uses the system browser, PKCE and OS-protected opaque session storage.
- Feishu token exchange defaults to v3. For the Feishu China Custom App only, operators may set FEISHU_TOKEN_ENDPOINT_VERSION=v2 when a fresh valid S256 exchange returns business code 20049; this uses the fixed historical v2 JSON endpoint for authorization-code exchange only, while refresh rotation remains on v3. The setting is server-only, never a client option, and must be reverted after the provider issue is resolved.
- Users can set or status-first claim an optional AI gateway virtual key from Settings. The server keeps it encrypted, shows only a first-two/last-two mask, and falls back to the protected gateway Master Key only when no user key is configured.
- Each target host reuses its source- and OS-bound verified Pi build cache; the expensive isolated Pi build runs once only when that host's cache is missing or fails integrity checks. Windows dependent jobs share their verified generation; platform caches are never copied across operating systems.
- Web and Desktop continue the official QoderWake replica. Extra product UI is not part of this release.

## Fixes

- Release publication now ships these notes with version, changes, fixes, known issues, and install/upgrade instructions.
- Native jobs still publish checksum, SBOM, and provenance assets per Windows/Linux/macOS label.
- Feishu OAuth refresh and Desktop broker binding now fail closed on tampered or invalid transactions while preserving valid sessions across retryable provider outages.

## Known issues

- The product probes only the configured HTTPS AI gateway base URL; plaintext listener policy belongs to the gateway operator and is not a WorkDude deployment gate.
- Waker Settings identity residual is still above the 0.005 visual gate. The compare stays an honest skip.
- Official Skill zip bodies are not installed. Create inserts official preset names and descriptions only.
- Official Windows tray right-click labels are still unmeasured. This release does not invent them.
- The macOS DMG maker currently depends on the archived \`image-size\` package, for which the upstream advisory has no released patch; it is a build-time optional dependency and is not included in the Desktop runtime. The release workflow retains the advisory as an explicit operator review item.
- A deployed instance must set WORKDUDE_AUTH_MODE=feishu, PUBLIC_BASE_URL, Feishu App ID/Secret, and register the exact FEISHU_WEB_REDIRECT_URI and FEISHU_DESKTOP_REDIRECT_URI in the Feishu developer console before OAuth can complete. Do not place those secrets in the Desktop package or browser.
- Production Platform API also requires a separate random FEISHU_AUTH_ENCRYPTION_KEY for OAuth verifier/code/refresh-token ciphertext; keep it distinct from APP_SECRET_ENCRYPTION_KEY and inject it only into Platform API.
- A clean Desktop profile needs the non-secret Platform API origin before first login. Run QoderWake.exe --provision-feishu-origin=https://<public-platform-host> once (or use the documented operator command); no Feishu or gateway credential is accepted. Unsigned macOS prerelease builds may require the platform's standard “Open”/Gatekeeper confirmation.
- The v2 compatibility profile is an explicit operator decision, not an automatic downgrade; drain pending OAuth transactions before changing it and do not put token-endpoint settings, App Secrets, or tokens in Desktop packages.

## Install and upgrade

- Windows x64: \`QoderWake-${version}-Windows-x64-Setup.exe\` or the matching zip.
- Linux x64: \`QoderWake-${version}-Linux-x64.deb\` or the matching zip.
- macOS Intel: \`QoderWake-${version}-macOS-x64.dmg\` or the matching zip.
- macOS Apple Silicon: \`QoderWake-${version}-macOS-arm64.dmg\` or the matching zip.
- Verify each file against \`SHA256SUMS-<label>.txt\` before install. Upgrade replaces the previous tagged build; keep the existing workspace directory.

The workflow first creates a draft and verifies every native asset, checksum, SBOM and provenance record. Publish the draft only after the verification job succeeds.
`;

await mkdir(dirname(out), { recursive: true });
await writeFile(out, notes, 'utf8');
process.stdout.write(`${JSON.stringify({ version, tag, commit, out })}\n`);
