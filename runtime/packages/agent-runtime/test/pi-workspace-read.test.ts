import { createHash } from 'node:crypto';
import { resolve } from 'node:path';
import { describe, expect, it, vi } from 'vitest';
import { createProductPiReadTool } from '../src/workspace-tools.ts';
// The loader verifies/pins the published gateway artifact used by the product.
// Rebuilding it requires the separate full Pi build cache and is not a read-tool test.
const { createReadToolDefinition, detectSupportedImageMimeType } =
  await import('../src/pi-runtime-loader.mjs');
import type { SandboxClient } from '../../product-contracts/src/index.ts';

function harness(decision: 'allow' | 'deny' = 'allow', bytes = Buffer.from('first\nsecond\nthird')) {
  const files = vi.fn<NonNullable<SandboxClient['fileOperation']>>(async (_id, input) => ({
    toolCallId: input.toolCallId,
    data: { base64: bytes.toString('base64'), sha256: createHash('sha256').update(bytes).digest('hex') },
  }));
  const evaluate = vi.fn(() => decision);
  const workspacePath = resolve('read-test-workspace');
  const tool = createProductPiReadTool(
    {
      workspacePath,
      attachments: [],
      detectImageMimeType: detectSupportedImageMimeType,
      workspace: {
        workspacePath,
        runId: 'read-run',
        sandboxId: 'read-sandbox',
        sandbox: { create: vi.fn(), exec: vi.fn(), fileOperation: files, destroy: vi.fn() },
        approvals: { request: vi.fn(async () => 'approved' as const) },
        policy: { evaluate },
      },
    },
    createReadToolDefinition,
  );
  return { tool, files, evaluate, workspacePath };
}

describe('Pi Read workspace dispatch', () => {
  it('uses sandbox bytes and Pi offset/limit without requiring product resources', async () => {
    const { tool, files, evaluate } = harness();
    const result = await tool.execute('read-1', { path: 'shared/proof.txt', offset: 2, limit: 1 }, undefined);
    expect(result.content[0]?.text).toContain('second');
    expect(result.content[0]?.text).not.toContain('first');
    expect(files).toHaveBeenCalledTimes(1);
    expect(evaluate).toHaveBeenCalled();
    expect(files.mock.calls[0]?.[1].operation).toEqual({ op: 'read_bytes', path: 'shared/proof.txt' });
  });

  it('denies external paths and honors policy before sandbox access', async () => {
    const allowed = harness();
    await expect(allowed.tool.execute('outside', { path: '../secret.txt' }, undefined)).rejects.toThrow();
    expect(allowed.files).not.toHaveBeenCalled();
    const denied = harness('deny');
    const result = await denied.tool.execute('denied', { path: 'shared/proof.txt' }, undefined);
    expect(result.details).toEqual({ approved: false, policyDecision: 'deny' });
    expect(result.terminate).toBe(true);
    expect(denied.files).not.toHaveBeenCalled();
  });

  it('reuses Pi image detection and emits image content from sandbox bytes', async () => {
    const bytes = Buffer.from('R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7', 'base64');
    const { tool, files } = harness('allow', bytes);
    const result = await tool.execute('image', { path: 'shared/pixel.gif' }, undefined);
    expect(result.content.some((item) => item.type === 'image')).toBe(true);
    expect(files).toHaveBeenCalledTimes(1);
  });

  it('propagates sandbox escape errors and cancellation', async () => {
    const h = harness();
    h.files.mockRejectedValueOnce(new Error('path escapes the workspace'));
    await expect(h.tool.execute('escape', { path: 'linked/proof.txt' }, undefined)).rejects.toThrow(
      'escapes',
    );
    const controller = new AbortController();
    controller.abort();
    await expect(h.tool.execute('cancel', { path: 'shared/proof.txt' }, controller.signal)).rejects.toThrow();
    expect(h.files).toHaveBeenCalledTimes(1);
  });
});
