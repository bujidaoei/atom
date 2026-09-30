import { createHash } from 'node:crypto';
import { link, mkdir, mkdtemp, open, rm, unlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';

import { Type } from 'typebox';

import { afterEach, describe, expect, it, vi } from 'vitest';

import type { ApprovalAdapter, SandboxClient } from '../../product-contracts/src/index.ts';
import {
  createProductPiReadTool,
  createWorkspaceTools,
  type PiReadToolDefinitionFactory,
} from '../src/workspace-tools.ts';

const workspacePath = resolve('test-workspace');
const temporaryRoots: string[] = [];

afterEach(async () => {
  await Promise.all(temporaryRoots.splice(0).map((root) => rm(root, { recursive: true, force: true })));
});

const readFactory: PiReadToolDefinitionFactory = (_cwd, options) => ({
  name: 'read',
  label: 'read',
  description: 'Pi Read fixture',
  parameters: Type.Object({ path: Type.String() }),
  executionMode: 'parallel',
  async execute(_toolCallId, params) {
    const path = (params as { path: string }).path;
    await options.operations.access(path);
    const bytes = await options.operations.readFile(path);
    const mimeType = await options.operations.detectImageMimeType?.(path);
    return {
      content: mimeType
        ? [
            { type: 'text', text: `Read image file [${mimeType}]` },
            { type: 'image', data: bytes.toString('base64'), mimeType },
          ]
        : [{ type: 'text', text: bytes.toString('utf8') }],
    };
  },
});

function harness(
  decision: 'allow' | 'ask' | 'deny' = 'allow',
  resourceRead?: ReturnType<PiReadToolDefinitionFactory>,
) {
  const request = vi.fn<ApprovalAdapter['request']>(async () => 'approved');
  const files = vi.fn<NonNullable<SandboxClient['fileOperation']>>(async (_sandboxId, input) => ({
    toolCallId: input.toolCallId,
    data: { text: 'README.md\npackage.json' },
  }));
  const tools = createWorkspaceTools(
    {
      runId: '11111111-1111-4111-8111-111111111111',
      sandboxId: 'sandbox',
      workspacePath,
      sandbox: { create: vi.fn(), exec: vi.fn(), fileOperation: files, destroy: vi.fn() },
      approvals: { request },
      policy: { evaluate: () => decision },
    },
    resourceRead,
  );
  return { tools, request, files };
}

describe('V3 semantic workspace tools', () => {
  it('routes installed resource absolute paths through Pi integrity checks, never unrestricted host reads', async () => {
    const root = await mkdtemp(join(tmpdir(), 'read-resource-routing-'));
    temporaryRoots.push(root);
    const path = join(root, 'proof.txt');
    const bytes = Buffer.from('VERIFIED-COMPANION');
    await writeFile(path, bytes);
    const resourceRead = createProductPiReadTool(
      {
        workspacePath,
        attachments: [
          {
            path,
            sizeBytes: bytes.length,
            sha256: createHash('sha256').update(bytes).digest('hex'),
            mediaType: 'text/plain',
          },
        ],
      },
      readFactory,
    );
    const { tools, files } = harness('deny', resourceRead);
    const read = tools.find((tool) => tool.name === 'read_file')!;
    expect(
      JSON.stringify(await read.execute('proof', { path }, undefined, undefined, {} as never)),
    ).toContain('VERIFIED-COMPANION');
    expect(files).not.toHaveBeenCalled();
    await expect(
      read.execute('foreign', { path: join(root, 'other.txt') }, undefined, undefined, {} as never),
    ).rejects.toThrow('not an authorized');
    await writeFile(path, 'TAMPERED-COMPANION');
    await expect(read.execute('changed', { path }, undefined, undefined, {} as never)).rejects.toThrow();
    await expect(
      read.execute('workspace', { path: 'secret.txt' }, undefined, undefined, {} as never),
    ).resolves.toMatchObject({ terminate: true, details: { policyDecision: 'deny' } });
    expect(files).not.toHaveBeenCalled();
  });
  it('exposes the same distinct tool categories shown by the official response chain', () => {
    expect(harness().tools.map((tool) => tool.name)).toEqual(['sandbox_exec', 'glob', 'grep', 'read_file']);
  });

  it('runs Glob in the sandbox with its real pattern and returns the real response', async () => {
    const { tools, files, request } = harness();
    const glob = tools.find((tool) => tool.name === 'glob')!;
    const result = await glob.execute(
      'glob-call',
      { pattern: '*', maxResults: 10 },
      undefined,
      undefined,
      {} as never,
    );

    expect(result.content).toEqual([{ type: 'text', text: 'README.md\npackage.json' }]);
    expect(request).not.toHaveBeenCalled();
    expect(files).toHaveBeenCalledWith(
      'sandbox',
      expect.objectContaining({
        toolCallId: 'glob-call',
        operation: { op: 'glob', pattern: '*', limit: 10 },
      }),
      undefined,
    );
  });

  it('rejects traversal before Read reaches approval or Docker', async () => {
    const { tools, files, request } = harness('ask');
    const read = tools.find((tool) => tool.name === 'read_file')!;

    await expect(
      read.execute('read-call', { path: '../outside.txt' }, undefined, undefined, {} as never),
    ).rejects.toThrow(/relative workspace path/iu);
    expect(request).not.toHaveBeenCalled();
    expect(files).not.toHaveBeenCalled();
  });

  it('applies Read policy and approval to the resolved workspace target', async () => {
    const { tools, files, request } = harness('ask');
    const read = tools.find((tool) => tool.name === 'read_file')!;
    await read.execute('read-call', { path: 'docs/PRD.md' }, undefined, undefined, {} as never);

    expect(request).toHaveBeenCalledWith(
      expect.objectContaining({
        command: expect.stringContaining('docs/PRD.md'),
        target: resolve(workspacePath, 'docs/PRD.md'),
        risk: 'read',
      }),
    );
    expect(files).toHaveBeenCalledOnce();
  });

  it('fails closed when policy denies Grep', async () => {
    const { tools, files, request } = harness('deny');
    const grep = tools.find((tool) => tool.name === 'grep')!;
    const result = await grep.execute(
      'grep-call',
      { pattern: 'TODO', path: '.' },
      undefined,
      undefined,
      {} as never,
    );

    expect(result).toMatchObject({ terminate: true, details: { policyDecision: 'deny' } });
    expect(request).not.toHaveBeenCalled();
    expect(files).not.toHaveBeenCalled();
  });

  it('reuses Pi Read for one exact integrity-bound conversation image and rejects other paths', async () => {
    const root = await mkdtemp(join(tmpdir(), 'workdude-v3-attachment-read-'));
    temporaryRoots.push(root);
    const attachmentPath = join(
      root,
      'cloud-conversations',
      'conversation-01',
      'attachments',
      'frontend.png',
    );
    await mkdir(dirname(attachmentPath), { recursive: true });
    const image = Buffer.from('89504e470d0a1a0a', 'hex');
    await writeFile(attachmentPath, image);
    const tool = createProductPiReadTool(
      {
        workspacePath: join(root, 'cloud-conversations', 'conversation-01', 'workers', 'member-01'),
        attachments: [
          {
            path: attachmentPath,
            mediaType: 'image/png',
            sizeBytes: image.byteLength,
            sha256: createHash('sha256').update(image).digest('hex'),
          },
        ],
      },
      readFactory,
    );

    await expect(
      tool.execute('read-image', { path: attachmentPath }, undefined, undefined, {} as never),
    ).resolves.toMatchObject({
      content: [
        { type: 'text', text: 'Read image file [image/png]' },
        { type: 'image', data: image.toString('base64'), mimeType: 'image/png' },
      ],
    });
    await expect(
      tool.execute('read-other', { path: join(root, 'other.png') }, undefined, undefined, {} as never),
    ).rejects.toThrow(/authorized product resource/iu);

    const hardLinkPath = join(dirname(attachmentPath), 'hard-linked.png');
    await link(attachmentPath, hardLinkPath);
    await expect(
      tool.execute('read-hard-linked', { path: attachmentPath }, undefined, undefined, {} as never),
    ).rejects.toThrow(/plain file/iu);
    await unlink(hardLinkPath);

    await writeFile(attachmentPath, Buffer.from('changed'));
    await expect(
      tool.execute('read-changed', { path: attachmentPath }, undefined, undefined, {} as never),
    ).rejects.toThrow(/size|checksum/iu);
  });

  it('reads an integrity-bound resource through a bounded descriptor operation', async () => {
    const root = await mkdtemp(join(tmpdir(), 'workdude-v3-bounded-resource-read-'));
    temporaryRoots.push(root);
    const attachmentPath = join(root, 'attachments', 'bounded.txt');
    const content = Buffer.from('bounded product resource');
    await mkdir(dirname(attachmentPath), { recursive: true });
    await writeFile(attachmentPath, content);
    const probe = await open(attachmentPath, 'r');
    type TestFileHandle = typeof probe;
    const fileHandlePrototype = Object.getPrototypeOf(probe) as Pick<TestFileHandle, 'readFile'>;
    await probe.close();
    const readFileSpy = vi
      .spyOn(fileHandlePrototype, 'readFile')
      .mockRejectedValue(new Error('unbounded descriptor read invoked'));
    try {
      const tool = createProductPiReadTool(
        {
          workspacePath: join(root, 'workspace'),
          attachments: [
            {
              path: attachmentPath,
              mediaType: 'text/plain',
              sizeBytes: content.byteLength,
              sha256: createHash('sha256').update(content).digest('hex'),
            },
          ],
        },
        readFactory,
      );

      await expect(
        tool.execute('read-bounded', { path: attachmentPath }, undefined, undefined, {} as never),
      ).resolves.toMatchObject({ content: [{ type: 'text', text: content.toString('utf8') }] });
      expect(readFileSpy).not.toHaveBeenCalled();
    } finally {
      readFileSpy.mockRestore();
    }
  });

  it('authorizes attachments claimed after the Read tool was created and revokes removed entries', async () => {
    const root = await mkdtemp(join(tmpdir(), 'workdude-v5-dynamic-read-'));
    temporaryRoots.push(root);
    const path = join(root, 'late-message.txt');
    const bytes = Buffer.from('LATER-CLAIM-ATTACHMENT');
    await writeFile(path, bytes);
    const entries: Array<{ path: string; mediaType: string; sizeBytes: number; sha256: string }> = [];
    const tool = createProductPiReadTool({ workspacePath: root, attachments: () => entries }, readFactory);
    const read = () => tool.execute('dynamic-read', { path }, undefined, undefined, {} as never);
    await expect(read()).rejects.toThrow('not an authorized product resource');
    entries.push({
      path,
      mediaType: 'text/plain',
      sizeBytes: bytes.byteLength,
      sha256: createHash('sha256').update(bytes).digest('hex'),
    });
    await expect(read()).resolves.toMatchObject({
      content: [{ type: 'text', text: 'LATER-CLAIM-ATTACHMENT' }],
    });
    await writeFile(path, Buffer.from('X'.repeat(bytes.length)));
    await expect(read()).rejects.toThrow('checksum mismatch');
    entries.splice(0);
    await expect(read()).rejects.toThrow('not an authorized product resource');
  });

  it('lets Pi read only integrity-bound files inside a materialized Skill directory', async () => {
    const root = await mkdtemp(join(tmpdir(), 'workdude-v3-skill-read-'));
    temporaryRoots.push(root);
    const skillDirectory = join(root, 'skills', 'bound-skill');
    const manifestPath = join(skillDirectory, 'SKILL.md');
    const emptyReferencePath = join(skillDirectory, 'references', 'empty.md');
    const referencePath = join(skillDirectory, 'references', 'guide.md');
    await mkdir(dirname(referencePath), { recursive: true });
    const manifest = Buffer.from('---\nname: bound-skill\ndescription: Bound Skill.\n---\nRead the guide.');
    const reference = Buffer.from('COMPANION-RESOURCE-OK');
    await writeFile(manifestPath, manifest);
    await writeFile(emptyReferencePath, '');
    await writeFile(referencePath, reference);
    const tool = createProductPiReadTool(
      {
        workspacePath: join(root, 'workspace'),
        attachments: [],
        skillDirectories: [
          {
            directoryPath: skillDirectory,
            files: [
              {
                path: manifestPath,
                sizeBytes: manifest.byteLength,
                sha256: createHash('sha256').update(manifest).digest('hex'),
                mediaType: 'text/markdown',
              },
              {
                path: emptyReferencePath,
                sizeBytes: 0,
                sha256: createHash('sha256').update('').digest('hex'),
                mediaType: 'text/markdown',
              },
              {
                path: referencePath,
                sizeBytes: reference.byteLength,
                sha256: createHash('sha256').update(reference).digest('hex'),
                mediaType: 'text/markdown',
              },
            ],
          },
        ],
      },
      readFactory,
    );

    await expect(
      tool.execute('read-skill-reference', { path: referencePath }, undefined, undefined, {} as never),
    ).resolves.toMatchObject({ content: [{ type: 'text', text: 'COMPANION-RESOURCE-OK' }] });
    await expect(
      tool.execute(
        'read-empty-skill-reference',
        { path: emptyReferencePath },
        undefined,
        undefined,
        {} as never,
      ),
    ).resolves.toMatchObject({ content: [{ type: 'text', text: '' }] });
    const unlistedPath = join(skillDirectory, 'references', 'unlisted.md');
    await writeFile(unlistedPath, 'not authorized');
    await expect(
      tool.execute('read-unlisted', { path: unlistedPath }, undefined, undefined, {} as never),
    ).rejects.toThrow(/authorized product resource/iu);
    await writeFile(referencePath, 'changed');
    await expect(
      tool.execute('read-modified-skill', { path: referencePath }, undefined, undefined, {} as never),
    ).rejects.toThrow(/size|checksum/iu);
  });
});
