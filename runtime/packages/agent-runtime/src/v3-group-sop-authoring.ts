import { lstat, open, realpath } from 'node:fs/promises';
import { dirname, isAbsolute, relative, resolve } from 'node:path';
import { parseV3SopTemplate, type V3SopTemplate } from '../../product-contracts/src/v3-group-sop.ts';

async function workspaceFile(root: string, path: string): Promise<string> {
  const canonicalRoot = await realpath(root);
  const target = resolve(canonicalRoot, path);
  const distance = relative(canonicalRoot, target);
  if (
    !distance ||
    distance === '..' ||
    distance.startsWith('..\\') ||
    distance.startsWith('../') ||
    distance.includes(':') ||
    isAbsolute(distance)
  ) {
    throw new Error('SOP file must stay inside the assigned workspace.');
  }
  // Resolve existing ancestors before opening; do not follow junctions/symlinks.
  if ((await realpath(dirname(target))) !== dirname(target)) {
    throw new Error('SOP file must not traverse a filesystem link.');
  }
  return target;
}

export async function executeV3GroupSopAuthoring(
  tokens: string[],
  workspacePath: string,
  signal?: AbortSignal,
): Promise<string> {
  signal?.throwIfAborted();
  const [, , action, path, ...args] = tokens;
  if (tokens[0] !== 'qoderwake' || tokens[1] !== 'sop' || !path || path.includes('\0')) {
    throw new Error('Invalid SOP command.');
  }
  if (action === 'init') {
    const flags = new Map<string, string>();
    for (let index = 0; index < args.length; index += 2) {
      const key = args[index]!;
      const value = args[index + 1];
      if (!['--skill-id', '--version'].includes(key) || flags.has(key) || !value) {
        throw new Error('Expected sop init <file> --skill-id <id> --version <version>.');
      }
      flags.set(key, value);
    }
    const skillId = flags.get('--skill-id');
    const version = flags.get('--version');
    const template = parseV3SopTemplate({
      skillId,
      version,
      displayName: skillId,
      template: {
        format: 'qoder-sop-template/v1',
        description: `Follow the ${skillId} SOP`,
        body: `# ${skillId}\n\nDescribe the SOP here.\n`,
      },
    });
    const target = await workspaceFile(workspacePath, path);
    signal?.throwIfAborted();
    const file = await open(target, 'wx', 0o600);
    try {
      await file.writeFile(`${JSON.stringify(template, null, 2)}\n`, 'utf8');
    } finally {
      await file.close();
    }
    return `Created SOP template ${target}.`;
  }
  if (action !== 'validate' || args.length) throw new Error('Expected sop validate <file>.');
  const template = await readV3SopTemplate(workspacePath, path, signal);
  return `SOP template ${template.skillId}@${template.version} is valid.`;
}

export async function readV3SopTemplate(
  workspacePath: string,
  path: string,
  signal?: AbortSignal,
): Promise<V3SopTemplate> {
  const target = await workspaceFile(workspacePath, path);
  const before = await lstat(target, { bigint: true });
  if (!before.isFile() || before.isSymbolicLink() || before.nlink !== 1n || before.size > 1_048_576n) {
    throw new Error('SOP template must be a plain file of at most 1 MiB.');
  }
  signal?.throwIfAborted();
  const file = await open(target, 'r');
  let text: string;
  try {
    const opened = await file.stat({ bigint: true });
    if (opened.dev !== before.dev || opened.ino !== before.ino || opened.size !== before.size) {
      throw new Error('SOP template changed while opening.');
    }
    const bytes = Buffer.alloc(Number(before.size));
    let offset = 0;
    while (offset < bytes.length) {
      signal?.throwIfAborted();
      const { bytesRead } = await file.read(bytes, offset, bytes.length - offset, offset);
      if (!bytesRead) throw new Error('SOP template changed while reading.');
      offset += bytesRead;
    }
    const after = await file.stat({ bigint: true });
    const current = await lstat(target, { bigint: true });
    if (
      after.size !== before.size ||
      after.mtimeNs !== before.mtimeNs ||
      after.ctimeNs !== before.ctimeNs ||
      current.ino !== before.ino ||
      current.dev !== before.dev ||
      current.isSymbolicLink()
    ) {
      throw new Error('SOP template changed while reading.');
    }
    text = bytes.toString('utf8');
  } finally {
    await file.close();
  }
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    throw new Error('SOP template must contain valid JSON.');
  }
  const template = parseV3SopTemplate(value);
  return template;
}
