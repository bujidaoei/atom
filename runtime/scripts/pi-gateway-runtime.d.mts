import type { Buffer } from 'node:buffer';

export interface PiGatewayRuntimeManifest {
  schemaVersion: 1;
  source: {
    piGeneration: string;
    piManifestSha256: string;
    sourceLockSha256: string;
    piSourceManifestSha256: string;
  };
  policy: {
    provider: 'enterprise-gateway';
    api: 'openai-completions';
    builtinProviders: false;
    allowedRequestPath: 'chat/completions';
  };
  bundle: { path: 'runtime.mjs'; sha256: string; bytes: number };
  virtualModules: {
    entrySha256: string;
    compatSha256: string;
    providersSha256: string;
  };
  inputs: Record<string, string>;
  externalImports: string[];
  exports: string[];
}

export interface PinnedPiGatewayRuntime {
  generation: string;
  root: string;
  manifest: PiGatewayRuntimeManifest;
  manifestSha256: string;
  bundleSha256: string;
  bundlePath?: string;
}

export interface PiGatewayRuntimeFileSnapshot {
  readonly path: string;
  readonly content: Buffer;
}

export interface PiGatewayRuntimeSnapshot {
  repositoryRoot: string;
  reader: Required<PinnedPiGatewayRuntime>;
  pointerFile: PiGatewayRuntimeFileSnapshot;
  trustedFile: PiGatewayRuntimeFileSnapshot;
  manifestFile: PiGatewayRuntimeFileSnapshot;
  bundleFile: PiGatewayRuntimeFileSnapshot;
}

export function hasGatewayOnlyPiRuntimeBoundary(source: string): boolean;

export function buildPiGatewayRuntime(options?: { repositoryRoot?: string }): Promise<PinnedPiGatewayRuntime>;

export function pinPiGatewayRuntime(options?: {
  repositoryRoot?: string;
}): Promise<Required<PinnedPiGatewayRuntime>>;

export function readPiGatewayRuntimeSnapshot(options?: {
  repositoryRoot?: string;
}): Promise<PiGatewayRuntimeSnapshot>;

export function exportPiGatewayRuntime(options: {
  repositoryRoot?: string;
  destinationRoot: string;
}): Promise<{ destination: string; generation: string }>;
