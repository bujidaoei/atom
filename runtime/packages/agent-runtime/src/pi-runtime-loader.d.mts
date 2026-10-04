import type { PiAgentSessionEvent, PiSessionMessage, ToolDefinition } from './pi-runtime-types.ts';

export function parseFrontmatter(content: string): { frontmatter: Record<string, unknown>; body: string };

export interface PiSessionManagerInstance {
  getBranch(): Array<
    | { type: 'message'; message: PiSessionMessage }
    | { type: 'session'; [key: string]: unknown }
    | { type: 'custom'; customType: string; data?: unknown }
  >;
  getSessionFile(): string | undefined;
  getSessionId(): string;
  appendCustomEntry(customType: string, data?: unknown): string;
}

export interface PiModelRuntimeInstance {
  registerProvider(provider: string, configuration: Record<string, unknown>): void;
  setRuntimeApiKey(provider: string, key: string): Promise<void>;
  getModel(provider: string, model: string): unknown;
}

export interface PiAgentSessionServices {
  settingsManager: { applyOverrides(overrides: { httpIdleTimeoutMs: number; retry: { provider: { timeoutMs: number } } }): void };
  getSkills(): ReadonlyArray<{ readonly name: string; readonly filePath: string }>;
  diagnostics: unknown;
  [key: string]: unknown;
}

export interface PiAgentSessionInstance {
  sessionManager: PiSessionManagerInstance;
  subscribe(listener: (event: PiAgentSessionEvent) => void): () => void;
  beforeNaturalCompletion(check: (signal: AbortSignal) => Promise<string | undefined>): () => void;
  afterToolTurn(check: (signal: AbortSignal) => Promise<string | undefined>): () => void;
  abort(): Promise<void>;
  steer(text: string): Promise<void>;
  prompt(
    prompt: string,
    options?: { images?: Array<{ type: 'image'; data: string; mimeType: string }> },
  ): Promise<void>;
}

export interface PiAgentSessionRuntimeInstance {
  session: PiAgentSessionInstance;
  dispose(): Promise<void>;
}

export const ModelRuntime: {
  create(options: {
    modelsPath: null;
    refreshOnCreate: boolean;
    allowModelNetwork: boolean;
  }): Promise<PiModelRuntimeInstance>;
};

export const SessionManager: {
  open(sessionPath: string, sessionDirectory: string, cwd: string): PiSessionManagerInstance;
  forkFrom(sourcePath: string, targetCwd: string, sessionDirectory?: string): PiSessionManagerInstance;
};

export function createAgentSessionServices(options: {
  cwd: string;
  agentDir: string;
  modelRuntime: PiModelRuntimeInstance;
  resourceLoaderOptions: Record<string, unknown>;
}): Promise<PiAgentSessionServices>;

export function createAgentSessionFromServices(options: {
  services: PiAgentSessionServices;
  sessionManager: PiSessionManagerInstance;
  sessionStartEvent?: unknown;
  model: unknown;
  thinkingLevel: 'off';
  tools: string[];
  customTools: ToolDefinition[];
}): Promise<{ session: PiAgentSessionInstance; [key: string]: unknown }>;

export function createAgentSessionRuntime(
  factory: (input: {
    cwd: string;
    agentDir: string;
    sessionManager: PiSessionManagerInstance;
    sessionStartEvent?: unknown;
  }) => Promise<unknown>,
  options: {
    cwd: string;
    agentDir: string;
    sessionManager: PiSessionManagerInstance;
  },
): Promise<PiAgentSessionRuntimeInstance>;

export function createWriteToolDefinition(
  cwd: string,
  options: {
    operations: {
      mkdir(path: string): Promise<void>;
      writeFile(path: string, content: string): Promise<void>;
    };
  },
): ToolDefinition;

export function createEditToolDefinition(
  cwd: string,
  options: {
    operations: {
      readFile(path: string): Promise<Buffer>;
      writeFile(path: string, content: string): Promise<void>;
      access(path: string): Promise<void>;
    };
  },
): ToolDefinition;

export function createReadToolDefinition(
  cwd: string,
  options: {
    autoResizeImages?: boolean;
    operations: {
      readFile(path: string): Promise<Buffer>;
      access(path: string): Promise<void>;
      detectImageMimeType?(path: string): Promise<string | null | undefined>;
    };
  },
): ToolDefinition;

export function detectSupportedImageMimeType(bytes: Uint8Array): string | null;
