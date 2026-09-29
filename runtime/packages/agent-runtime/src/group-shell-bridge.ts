import { createHash, randomUUID } from 'node:crypto';
import { setTimeout as delay } from 'node:timers/promises';
import type {
  SandboxClient,
  SandboxExecRequest,
  SandboxExecResult,
} from '../../product-contracts/src/index.ts';

const quote = (value: string) => `'${value.replaceAll("'", "'\\''")}'`;
const argument = (value: string) => (/^[\w./-]+$/u.test(value) ? value : quote(value));
const READ = String.raw`import json,os,pathlib,sys
root=pathlib.Path(sys.argv[1]); result=[]
for item in sorted(root.glob('*.request'))[:128]:
 if item.is_symlink(): raise RuntimeError('Invalid control request')
 with item.open('rb') as f: data=f.read(16001)
 if len(data)>16000: raise RuntimeError('Control request too large')
 result.append({'id':item.stem,'args':json.loads(data)})
print(json.dumps(result))`;
const WRITE = String.raw`import base64,pathlib,sys
root=pathlib.Path(sys.argv[1]); path=root/(sys.argv[2]+'.result')
with path.open('ab') as f: f.write(base64.b64decode(sys.argv[3]))
if sys.argv[4]=='1':
 path.replace(root/(sys.argv[2]+'.response'))
 (root/(sys.argv[2]+'.request')).unlink(missing_ok=True)`;

/** Uses the real sandbox shell and shipped CLI; never interprets shell syntax on the host. */
export async function executeGroupShell(
  sandbox: SandboxClient,
  sandboxId: string,
  request: SandboxExecRequest,
  dispatch: (request: SandboxExecRequest, signal?: AbortSignal) => Promise<SandboxExecResult>,
  signal?: AbortSignal,
): Promise<SandboxExecResult> {
  signal?.throwIfAborted();
  const directory = `/tmp/workdude-control-${randomUUID()}`;
  const control = async (command: string) => {
    signal?.throwIfAborted();
    const result = await sandbox.exec(sandboxId, { ...request, command, timeoutMs: 5000 }, signal);
    if (result.exitCode !== 0 || result.truncated || result.timedOut) {
      throw new Error('Group shell control transport failed');
    }
    return result.stdout;
  };
  await control(`command -v qoderwake >/dev/null && mkdir -m 700 ${quote(directory)}`);
  let finished = false;
  const handled = new Set<string>();
  const occurrences = new Map<string, number>();
  const command = sandbox
    .exec(
      sandboxId,
      {
        ...request,
        command: `export WORKDUDE_CONTROL_DIR=${quote(directory)}\n${request.command}`,
      },
      signal,
    )
    .finally(() => {
      finished = true;
    });
  // Observe errors immediately while the other side of the transport is awaited.
  void command.catch(() => undefined);
  const pump = async () => {
    while (!finished) {
      const items: unknown = JSON.parse(await control(`python3 -c ${quote(READ)} ${quote(directory)}`));
      if (!Array.isArray(items)) throw new Error('Invalid Group shell control requests');
      for (const item of items) {
        signal?.throwIfAborted();
        if (finished) break;
        if (
          !item ||
          typeof item.id !== 'string' ||
          !/^[a-f0-9]{32}$/u.test(item.id) ||
          !Array.isArray(item.args) ||
          item.args.length > 256 ||
          item.args.some((arg: unknown) => typeof arg !== 'string' || arg.includes('\0'))
        ) {
          throw new Error('Invalid Group shell control arguments');
        }
        if (handled.has(item.id)) continue;
        if (handled.size >= 128) throw new Error('Group shell control invocation limit exceeded');
        handled.add(item.id);
        const digest = createHash('sha256').update(JSON.stringify(item.args)).digest('hex');
        const occurrence = (occurrences.get(digest) ?? 0) + 1;
        occurrences.set(digest, occurrence);
        const result = await dispatch(
          {
            ...request,
            toolCallId: `${request.toolCallId}:cli:${digest}:${occurrence}`,
            command: `qoderwake ${item.args.map(argument).join(' ')}`,
          },
          signal,
        );
        const bytes = Buffer.from(
          JSON.stringify({ stdout: result.stdout, stderr: result.stderr, exitCode: result.exitCode }),
        );
        if (bytes.length > 1_048_576) throw new Error('Group shell control response too large');
        const encoded = bytes.toString('base64');
        for (let offset = 0; offset < encoded.length; offset += 12000) {
          await control(
            `python3 -c ${quote(WRITE)} ${quote(directory)} ${quote(item.id)} ${quote(encoded.slice(offset, offset + 12000))} ${offset + 12000 >= encoded.length ? '1' : '0'}`,
          );
        }
      }
      if (!finished) await delay(100, undefined, signal ? { signal } : undefined);
    }
  };
  try {
    await pump();
    return await command;
  } finally {
    // Never let transport callbacks survive their Run. Destroy also stops descendants on failure.
    if (!finished) await sandbox.destroy(sandboxId).catch(() => undefined);
    await command.catch(() => undefined);
    if (!signal?.aborted) await control(`rm -rf -- ${quote(directory)}`).catch(() => undefined);
  }
}
