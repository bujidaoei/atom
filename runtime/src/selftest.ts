/**
 * Proof-of-life for the vendored WorkDude runtime.
 *
 * Runs one real agent turn through the configured OpenAI-compatible gateway
 * using the unmodified ProductAgentRuntime, first chat-only and then with the
 * full tool surface writing into a scratch workspace.
 */
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { ProductAgentRuntime } from '../packages/agent-runtime/src/product-agent-runtime.ts';
import { LocalSandboxClient } from './local-sandbox.ts';

const baseUrl = process.env.ATOM_GATEWAY_BASE_URL ?? 'https://ai-gateway.skg.com/v1';
const masterKey = process.env.ATOM_GATEWAY_API_KEY ?? '';
const model = process.env.ATOM_GATEWAY_MODEL ?? 'claude-sonnet-5';

if (!masterKey) throw new Error('ATOM_GATEWAY_API_KEY is required');

const root = await mkdtemp(join(tmpdir(), 'atom-selftest-'));
const workspacePath = join(root, 'workspace');
const agentDir = join(root, 'agent');
const sessionPath = join(root, 'sessions', 'session.jsonl');

const sandbox = new LocalSandboxClient({ resolveWorkspace: () => workspacePath });
const seen: string[] = [];

function makeRuntime(enableTools: boolean) {
  return new ProductAgentRuntime({
    aiGateway: { baseUrl, masterKey, model, requestTimeoutMs: 180_000 },
    agentDir,
    sandbox,
    approvals: { request: async () => 'approved' as const },
    events: {
      async emit(type, payload) {
        seen.push(type);
        if (type === 'tool.started') console.log('  tool:', payload.toolName);
        if (type === 'tool.failed' || type === 'run.failed') {
          console.log(`  ${type}:`, JSON.stringify(payload).slice(0, 700));
        }
      },
    },
    enableTools,
    systemPrompt: enableTools
      ? 'You are Alex, the Engineer. Write files into the workspace with the write tool. Be terse.'
      : 'Answer in one short sentence.',
  });
}

try {
  console.log('--- pass 1: chat only ---');
  const chat = await makeRuntime(false).run({
    runId: '11111111-1111-4111-8111-111111111111',
    prompt: 'Reply with exactly: RUNTIME_OK',
    workspacePath,
    sessionPath,
  });
  console.log('text:', JSON.stringify(chat.resultText.trim().slice(0, 200)));
  console.log('usage:', JSON.stringify(chat.usage));

  console.log('--- pass 2: tools ---');
  const build = await makeRuntime(true).run({
    runId: '22222222-2222-4222-8222-222222222222',
    prompt:
      'Create index.html containing an <h1> that says Atoms Demo. ' +
      'Then run a shell command with sandbox_exec that lists the workspace. Then stop.',
    workspacePath,
    sessionPath: join(root, 'sessions', 'build.jsonl'),
  });
  console.log('text:', JSON.stringify(build.resultText.trim().slice(0, 300)));
  const html = await readFile(join(workspacePath, 'index.html'), 'utf8').catch(() => '<missing>');
  console.log('index.html:', JSON.stringify(html.slice(0, 300)));

  console.log('--- event types seen ---');
  console.log([...new Set(seen)].join(', '));
} finally {
  await rm(root, { recursive: true, force: true });
}
