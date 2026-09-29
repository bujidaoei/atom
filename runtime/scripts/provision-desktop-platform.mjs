import { spawn } from 'node:child_process';
import { access } from 'node:fs/promises';
import { resolve } from 'node:path';
import { URL } from 'node:url';

import { createDesktopProvisioningChildEnvironment } from './desktop-provisioning-environment.mjs';
import { parseDesktopProvisioningEvidence } from './desktop-provisioning-evidence.mjs';

const argument = (name, fallback) => {
  const prefix = `--${name}=`;
  return process.argv.find((value) => value.startsWith(prefix))?.slice(prefix.length) ?? fallback;
};

const executable = resolve(argument('executable', 'apps/desktop/out/QoderWake-win32-x64/QoderWake.exe'));
const platformOrigin = argument('platform-origin', 'http://127.0.0.1:8080').replace(/\/+$/u, '');
const desktopToken = process.env.DESKTOP_PLATFORM_ACCESS_TOKEN?.trim() ?? '';
const browserToken = process.env.APP_ACCESS_TOKEN?.trim() ?? '';
const gatewayAdministratorKey = process.env.LITELLM_MASTER_KEY?.trim() ?? '';
const model = process.env.LITELLM_MODEL?.trim() ?? '';

await access(executable);
if (!desktopToken || desktopToken.length < 32 || !model) {
  throw new Error('Protected Desktop Platform token and configured model are required');
}
if (desktopToken === browserToken || desktopToken === gatewayAdministratorKey) {
  throw new Error(
    'Desktop Platform token must be distinct from browser and gateway administrator credentials',
  );
}
const origin = new URL(platformOrigin);
const loopback = ['127.0.0.1', '::1', 'localhost'].includes(origin.hostname);
if (origin.protocol !== 'https:' && !(loopback && origin.protocol === 'http:')) {
  throw new Error('Desktop Platform origin must use HTTPS except for loopback development');
}

const environment = createDesktopProvisioningChildEnvironment(process.env, {
  platformOrigin,
  desktopToken,
  model,
});

const child = spawn(executable, ['--provision-platform-config'], {
  env: environment,
  stdio: ['ignore', 'pipe', 'pipe'],
  windowsHide: true,
});
let stdout = '';
let stderr = '';
child.stdout.setEncoding('utf8');
child.stderr.setEncoding('utf8');
child.stdout.on('data', (chunk) => {
  stdout += chunk;
  if (stdout.length > 16_384) child.kill();
});
child.stderr.on('data', (chunk) => {
  stderr += chunk;
  if (stderr.length > 16_384) child.kill();
});
const result = await new Promise((resolveExit, rejectExit) => {
  child.once('error', rejectExit);
  child.once('exit', (code, signal) => resolveExit({ code, signal }));
});
if (result.code !== 0 || result.signal !== null) {
  const redacted = [desktopToken, browserToken, gatewayAdministratorKey]
    .filter(Boolean)
    .reduce((value, secret) => value.replaceAll(secret, '[REDACTED]'), stderr)
    .slice(-4_000);
  throw new Error(`Desktop Platform provisioning failed: ${redacted || JSON.stringify(result)}`);
}
let payload;
try {
  payload = parseDesktopProvisioningEvidence(stdout);
} catch (cause) {
  const redacted = [desktopToken, browserToken, gatewayAdministratorKey]
    .filter(Boolean)
    .reduce((value, secret) => value.replaceAll(secret, '[REDACTED]'), `${stdout}\n${stderr}`)
    .slice(-4_000);
  throw new Error(`Desktop Platform provisioning returned invalid evidence: ${redacted}`, { cause });
}
if (
  payload?.operation !== 'platform_config_provision' ||
  payload.status !== 'ready' ||
  payload.model !== model ||
  !Number.isSafeInteger(payload.availableModelCount) ||
  payload.availableModelCount < 1
) {
  throw new Error('Desktop Platform provisioning did not prove a ready model catalog');
}
process.stdout.write(
  `${JSON.stringify({
    status: payload.status,
    model: payload.model,
    availableModelCount: payload.availableModelCount,
    platformOrigin,
  })}\n`,
);
