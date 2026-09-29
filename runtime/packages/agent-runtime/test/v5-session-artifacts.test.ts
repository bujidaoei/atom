import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';

import {
  createPresentFilesTool,
  inferSessionArtifactType,
  markdownLocalFileTargets,
  presentLinkedSessionFiles,
  PRESENT_FILES_TOOL_NAME,
  sessionArtifactMediaType,
  sessionArtifactOutputDir,
  type SessionArtifactFile,
} from '../src/session-artifacts.ts';

const conversationId = '33333333-3333-4333-8333-333333333333';
const roots: string[] = [];

async function workspace() {
  const root = await mkdtemp(join(tmpdir(), 'present-files-'));
  roots.push(root);
  const presented: SessionArtifactFile[] = [];
  const tool = createPresentFilesTool({
    workspacePath: root,
    sink: {
      conversationId,
      recordProcessFile: async () => undefined,
      presentFile: async (file) => {
        presented.push(file);
      },
    },
  });
  return { root, presented, tool };
}

function body(result: { content: Array<{ type: string; text?: string }> }) {
  return JSON.parse(result.content[0]!.text!) as {
    success: boolean;
    presented: Array<{ type: string; title: string; outputPath: string; copied: boolean }>;
    rejected: Array<{ path: string; reason: string }>;
    outputDir: string;
  };
}

afterEach(async () => {
  await Promise.all(roots.splice(0).map((root) => rm(root, { recursive: true, force: true })));
});

describe('official present_files semantics', () => {
  it('uses the official tool name, extension types and MIME map', () => {
    expect(PRESENT_FILES_TOOL_NAME).toBe('mcp__plugin_wake_mcp_adapter__present_files');
    expect(inferSessionArtifactType('deck.pptx')).toBe('presentation');
    expect(inferSessionArtifactType('report.PDF')).toBe('document');
    expect(inferSessionArtifactType('photo.png')).toBe('media');
    expect(inferSessionArtifactType('bundle.tgz')).toBe('archive');
    expect(inferSessionArtifactType('data.bin')).toBe('other');
    expect(sessionArtifactMediaType('a.xlsx')).toBe(
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    );
    expect(sessionArtifactMediaType('a.unknown')).toBe('application/octet-stream');
  });

  it('copies workspace files into <cwd>/<conversation>/_output and reports them', async () => {
    const { root, presented, tool } = await workspace();
    await mkdir(join(root, 'vibe_images'));
    await writeFile(join(root, 'vibe_images', 'dog.png'), 'png-bytes');
    const result = await tool.execute(
      'call',
      {
        files: [
          {
            file_path: join(root, 'vibe_images', 'dog.png'),
            title: '叼着蓝色气球的金毛',
            description: 'AI 生成的金毛寻回犬叼蓝色气球图片',
            artifactType: 'media',
          },
        ],
      },
      undefined,
    );
    const output = sessionArtifactOutputDir(root, conversationId);
    const parsed = body(result);
    expect(parsed.success).toBe(true);
    expect(parsed.outputDir).toBe(output);
    expect(parsed.presented).toEqual([
      {
        type: 'media',
        title: '叼着蓝色气球的金毛',
        outputPath: expect.stringContaining('dog.png'),
        copied: true,
      },
    ]);
    expect(await readFile(join(output, 'dog.png'), 'utf8')).toBe('png-bytes');
    expect(presented).toEqual([
      expect.objectContaining({
        relativePath: 'dog.png',
        mediaType: 'image/png',
        artifactType: 'media',
        title: '叼着蓝色气球的金毛',
        description: 'AI 生成的金毛寻回犬叼蓝色气球图片',
      }),
    ]);
  });

  it('reuses identical copies, suffixes conflicting names and defaults the title to the file name', async () => {
    const { root, presented, tool } = await workspace();
    await writeFile(join(root, 'report.md'), 'first');
    await tool.execute('a', { files: [{ file_path: 'report.md' }] }, undefined);
    await tool.execute('b', { files: [{ file_path: 'report.md' }] }, undefined);
    await writeFile(join(root, 'report.md'), 'second');
    await tool.execute('c', { files: [{ file_path: 'report.md' }] }, undefined);
    expect(
      presented.map(({ relativePath, title, artifactType }) => [relativePath, title, artifactType]),
    ).toEqual([
      ['report.md', 'report.md', 'document'],
      ['report.md', 'report.md', 'document'],
      ['report-2.md', 'report-2.md', 'document'],
    ]);
  });

  it('delivers local files linked by the final reply, like the official CLI, and ignores remote or outside links', async () => {
    const { root, presented } = await workspace();
    await mkdir(join(root, 'vibe_images'));
    await writeFile(join(root, 'vibe_images', '金毛.png'), 'png');
    await writeFile(join(root, 'notes.txt'), 'not a presentable link type');
    const outside = await mkdtemp(join(tmpdir(), 'outside-link-'));
    roots.push(outside);
    await writeFile(join(outside, 'x.pdf'), 'pdf');
    const markdown = [
      `![金毛叼蓝色气球](${join(root, 'vibe_images', '金毛.png')})`,
      '[说明](notes.txt)',
      `[外部](${join(outside, 'x.pdf')})`,
      '![remote](https://example.com/a.png)',
    ].join('\n');
    expect(markdownLocalFileTargets(markdown, root)).toEqual([
      join(root, 'vibe_images', '金毛.png'),
      join(outside, 'x.pdf'),
    ]);
    const delivered = await presentLinkedSessionFiles({
      markdown,
      workspacePath: root,
      sink: {
        conversationId,
        recordProcessFile: async () => undefined,
        presentFile: async (file) => {
          presented.push(file);
        },
      },
    });
    expect(delivered).toBe(1);
    expect(presented).toEqual([
      expect.objectContaining({ relativePath: '金毛.png', artifactType: 'media', title: '金毛.png' }),
    ]);
  });

  it('rejects files outside the session target directory without publishing them', async () => {
    const { presented, tool } = await workspace();
    const outside = await mkdtemp(join(tmpdir(), 'outside-'));
    roots.push(outside);
    await writeFile(join(outside, 'secret.txt'), 'no');
    const result = await tool.execute(
      'call',
      { files: [{ file_path: join(outside, 'secret.txt') }] },
      undefined,
    );
    const parsed = body(result);
    expect(parsed.success).toBe(false);
    expect(parsed.rejected[0]!.reason).toContain('file is outside the session target directory');
    expect(presented).toEqual([]);
    expect(result).toMatchObject({ isError: true });
  });
});
