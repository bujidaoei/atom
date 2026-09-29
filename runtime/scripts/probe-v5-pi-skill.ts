import { createHash, randomUUID } from 'node:crypto';
import { mkdir, writeFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { ProductAgentRuntime } from '../packages/agent-runtime/src/product-agent-runtime.ts';

const key = process.env.LITELLM_MASTER_KEY || process.env.ADMIN_KEY;
if (!key) throw new Error('Gateway credential unavailable');
const runId = randomUUID();
const root = resolve('.tmp', `v5-real-skill-${runId}`);
const directoryPath = join(root, 'skill');
await mkdir(join(directoryPath, 'references'), { recursive: true });
const marker = `GROUP-SKILL-REAL-${randomUUID()}`;
const manifest =
  '---\nname: group-verification\ndescription: Read the verification marker from the companion reference.\n---\nUse the read tool to read references/marker.md relative to this Skill directory. Return only its verification marker. Do not guess the marker or execute commands.';
const contents = [
  { path: join(directoryPath, 'SKILL.md'), text: manifest },
  { path: join(directoryPath, 'references', 'marker.md'), text: marker },
];
for (const file of contents) await writeFile(file.path, file.text);
const events: Array<{ type: string; toolName?: unknown; args?: unknown }> = [];
const runtime = new ProductAgentRuntime({
  aiGateway: {
    baseUrl: 'https://ai-gateway.skg.com/v1',
    masterKey: key,
    model: process.env.LITELLM_MODEL || 'glm-5.2',
    requestTimeoutMs: 90000,
  },
  agentDir: join(root, 'agent'),
  enableTools: false,
  sandbox: {
    create: async () => {
      throw new Error('Shell sandbox unavailable in read-only verification');
    },
    exec: async () => {
      throw new Error('Shell execution unavailable');
    },
    destroy: async () => undefined,
  },
  approvals: { request: async () => 'rejected' },
  events: {
    emit: async (type, payload) => {
      events.push({ type, toolName: payload.toolName, args: payload.args });
    },
  },
  skillDirectories: [
    {
      directoryPath,
      files: contents.map((file) => ({
        path: file.path,
        sizeBytes: Buffer.byteLength(file.text),
        sha256: createHash('sha256').update(file.text).digest('hex'),
        mediaType: 'text/markdown',
      })),
    },
  ],
});
try {
  const result = await runtime.run({
    runId,
    prompt:
      'Use the group-verification Skill to obtain its verification marker. Read the Skill and its companion reference, then return the marker exactly. Do not execute commands or change any files.',
    workspacePath: join(root, 'workspace'),
    sessionPath: join(root, 'sessions', 'run.jsonl'),
    signal: AbortSignal.timeout(120000),
  });
  const receipt = {
    checkedAt: new Date().toISOString(),
    model: process.env.LITELLM_MODEL || 'glm-5.2',
    markerFound: result.resultText.includes(marker),
    exactFormat: result.resultText.trim() === marker,
    successfulReads: events.filter((event) => event.type === 'tool.completed' && event.toolName === 'read')
      .length,
    resultText: result.resultText,
    usage: result.usage,
    providerCorrelationId: result.providerCorrelationId,
    events,
    sessionFile: result.sessionFile,
  };
  await writeFile(join(root, 'receipt.json'), JSON.stringify(receipt, null, 2));
  console.log(
    JSON.stringify({
      checkedAt: receipt.checkedAt,
      model: receipt.model,
      markerFound: receipt.markerFound,
      exactFormat: receipt.exactFormat,
      successfulReads: receipt.successfulReads,
      usage: receipt.usage,
      tools: events.filter((event) => event.type.startsWith('tool.')),
      receiptPath: join(root, 'receipt.json'),
    }),
  );
  if (!receipt.markerFound || receipt.successfulReads < 2) process.exitCode = 1;
} catch (error) {
  console.log(
    JSON.stringify({
      error: error instanceof Error ? error.message.replaceAll(key, '[redacted]') : 'Run failed',
      root,
    }),
  );
  process.exitCode = 1;
}
