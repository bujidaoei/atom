import { pathToFileURL } from 'node:url';

import { pinPiGatewayRuntime } from '../../../scripts/pi-gateway-runtime.mjs';

const reader = await pinPiGatewayRuntime({
  repositoryRoot: process.env.WORKDUDE_PI_CACHE_REPOSITORY_ROOT ?? process.cwd(),
});
const runtimeModule = await import(/* @vite-ignore */ pathToFileURL(reader.bundlePath).href);
const expectedExports = [
  'ModelRuntime',
  'SessionManager',
  'createAgentSessionFromServices',
  'createAgentSessionRuntime',
  'createAgentSessionServices',
  'createEditToolDefinition',
  'createReadToolDefinition',
  'detectSupportedImageMimeType',
  'createWriteToolDefinition',
  'parseFrontmatter',
];
if (
  JSON.stringify(Object.keys(runtimeModule).sort()) !== JSON.stringify([...expectedExports].sort()) ||
  expectedExports.some((name) => typeof runtimeModule[name] === 'undefined')
) {
  throw new Error('Pi gateway runtime exports do not match the product boundary');
}

export const createAgentSessionRuntime = runtimeModule.createAgentSessionRuntime;
export const createAgentSessionFromServices = runtimeModule.createAgentSessionFromServices;
export const createAgentSessionServices = runtimeModule.createAgentSessionServices;
export const createReadToolDefinition = runtimeModule.createReadToolDefinition;
export const createWriteToolDefinition = runtimeModule.createWriteToolDefinition;
export const createEditToolDefinition = runtimeModule.createEditToolDefinition;
export const ModelRuntime = runtimeModule.ModelRuntime;
export const SessionManager = runtimeModule.SessionManager;
export const parseFrontmatter = runtimeModule.parseFrontmatter;

export const detectSupportedImageMimeType = runtimeModule.detectSupportedImageMimeType;
