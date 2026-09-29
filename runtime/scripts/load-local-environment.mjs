import { existsSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath, URL } from 'node:url';

const repositoryRoot = fileURLToPath(new URL('../', import.meta.url));

// Node keeps already-set process variables when loading a file. Load the
// project configuration first, then fill missing gateway values from the
// separately protected local fallback file.
const projectEnvironment = join(repositoryRoot, '.env');
if (existsSync(projectEnvironment)) process.loadEnvFile(projectEnvironment);

for (const name of [
  'LITELLM_BASE_URL',
  'TOKEN_V3_AI_GATEWAY_BASE_URL',
  'LITELLM_MASTER_KEY',
  'TOKEN_V3_AI_GATEWAY_ADMIN_KEY',
  'TOKEN_V3_AI_GATEWAY_CONNECT_IP',
  'TOKEN_V3_AI_GATEWAY_BIND_INTERFACE',
]) {
  if (!process.env[name]?.trim()) delete process.env[name];
}

const gatewayFallback = join(repositoryRoot, '.env.gateway-defaults');
if (existsSync(gatewayFallback)) process.loadEnvFile(gatewayFallback);

const { configureGatewayLocalRoute } = await import('./gateway-local-route.mjs');
configureGatewayLocalRoute();
