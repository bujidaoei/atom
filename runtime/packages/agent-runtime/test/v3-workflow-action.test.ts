import { describe, expect, it, vi } from 'vitest';

import type { SandboxClient } from '../../product-contracts/src/index.ts';
import type { V3WorkflowNode } from '../../product-contracts/src/v3.ts';
import { executeV3WorkflowAction } from '../src/v3-workflow-action.ts';

const scriptNode: Extract<V3WorkflowNode, { type: 'action'; actionType: 'script' }> = {
  id: 'notify',
  name: 'Notify',
  next: [],
  type: 'action',
  actionId: 'notify-script',
  actionType: 'script',
  command: 'node scripts/notify.mjs',
  args: [],
};

const httpNode: Extract<V3WorkflowNode, { type: 'action'; actionType: 'http' }> = {
  id: 'webhook',
  name: 'Webhook',
  next: [],
  type: 'action',
  actionId: 'delivery-webhook',
  actionType: 'http',
  url: 'https://actions.example.test/deliver',
  method: 'POST',
  args: {},
};

const builtinNode: Extract<V3WorkflowNode, { type: 'action'; actionType: 'builtin' }> = {
  id: 'acceptance',
  name: 'Return acceptance result',
  next: [],
  type: 'action',
  actionId: 'return-acceptance-result',
  actionType: 'builtin',
  handlerSource: "return 'ACTION-BUILTIN-OK';",
  args: {},
};

describe('V3 WakerFlow Action executor', () => {
  it('runs inline JavaScript in the existing sandbox and returns its data envelope', async () => {
    const sandbox: SandboxClient = {
      create: vi.fn(async () => 'builtin-sandbox'),
      exec: vi.fn(async (_id, request) => ({
        toolCallId: request.toolCallId,
        exitCode: 0,
        stdout: '{"data":"ACTION-BUILTIN-OK"}',
        stderr: '',
        timedOut: false,
        truncated: false,
      })),
      destroy: vi.fn(async () => undefined),
    };
    await expect(
      executeV3WorkflowAction(
        {
          node: builtinNode,
          args: {},
          target: builtinNode.actionId,
          executionKey: 'run-builtin:acceptance',
        },
        { workspaceId: 'workspace-1', sandbox, timeoutMs: 5_000 },
      ),
    ).resolves.toEqual({ data: 'ACTION-BUILTIN-OK' });
    expect(sandbox.create).toHaveBeenCalledWith('run-builtin:acceptance', 'workspace-1');
    expect(sandbox.exec).toHaveBeenCalledWith(
      'builtin-sandbox',
      expect.objectContaining({
        toolCallId: 'run-builtin:acceptance',
        timeoutMs: 5_000,
        command: expect.stringContaining('node --input-type=module -e'),
      }),
      undefined,
    );
    expect(sandbox.destroy).toHaveBeenCalledWith('builtin-sandbox');
  });

  it.each([
    { stdout: 'not-json', truncated: false, timedOut: false, exitCode: 0, error: 'invalid JSON' },
    { stdout: '{"data":"partial"}', truncated: true, timedOut: false, exitCode: 0, error: 'output exceeded' },
    { stdout: '', truncated: false, timedOut: true, exitCode: 1, error: 'timed out' },
    { stdout: '', truncated: false, timedOut: false, exitCode: 7, error: 'exited with code 7' },
  ])(
    'rejects invalid builtin output and destroys its sandbox',
    async ({ stdout, truncated, timedOut, exitCode, error }) => {
      const sandbox: SandboxClient = {
        create: vi.fn(async () => 'builtin-sandbox'),
        exec: vi.fn(async () => ({
          toolCallId: 'run-builtin:acceptance',
          exitCode,
          stdout,
          stderr: '',
          timedOut,
          truncated,
        })),
        destroy: vi.fn(async () => undefined),
      };
      await expect(
        executeV3WorkflowAction(
          {
            node: builtinNode,
            args: {},
            target: builtinNode.actionId,
            executionKey: 'run-builtin:acceptance',
          },
          { workspaceId: 'workspace-1', sandbox },
        ),
      ).rejects.toThrow(error);
      expect(sandbox.destroy).toHaveBeenCalledWith('builtin-sandbox');
    },
  );

  it('runs Script Actions only through the sandbox and quotes declared args', async () => {
    const exec = vi.fn(async (_sandboxId, request) => ({
      toolCallId: request.toolCallId,
      exitCode: 0,
      stdout: 'delivered\n',
      stderr: '',
      timedOut: false,
      truncated: false,
    }));
    const sandbox: SandboxClient = {
      create: vi.fn(async () => 'sandbox-1'),
      exec,
      destroy: vi.fn(async () => undefined),
    };
    await expect(
      executeV3WorkflowAction(
        {
          node: scriptNode,
          args: ['customer one', "quote'check"],
          target: scriptNode.command,
          executionKey: 'run-1:notify',
        },
        { workspaceId: 'workspace-1', sandbox },
      ),
    ).resolves.toMatchObject({ exitCode: 0, stdout: 'delivered\n' });
    expect(sandbox.create).toHaveBeenCalledWith('run-1:notify', 'workspace-1');
    expect(exec.mock.calls[0]?.[1].command).toBe("node scripts/notify.mjs 'customer one' 'quote'\\''check'");
    expect(sandbox.destroy).toHaveBeenCalledWith('sandbox-1');
  });

  it('executes public HTTPS Actions with a JSON body and parses the real response', async () => {
    const fetcher = vi.fn(async (_url: string | URL | Request, init?: RequestInit) => {
      expect(init?.method).toBe('POST');
      expect(init?.body).toBe('{"delivery":"D-42"}');
      return new Response('{"accepted":true}', {
        status: 201,
        headers: { 'content-type': 'application/json' },
      });
    });
    await expect(
      executeV3WorkflowAction(
        {
          node: httpNode,
          args: { delivery: 'D-42' },
          target: httpNode.url,
          executionKey: 'run-2:webhook',
        },
        {
          workspaceId: 'workspace-1',
          fetch: fetcher,
          resolveHost: async () => ['203.0.113.10'],
        },
      ),
    ).resolves.toEqual({ status: 201, mediaType: 'application/json', body: { accepted: true } });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it('rejects private HTTP Action targets before issuing a request', async () => {
    const fetcher = vi.fn();
    await expect(
      executeV3WorkflowAction(
        {
          node: httpNode,
          args: {},
          target: 'https://internal.example.test/hook',
          executionKey: 'run-3:webhook',
        },
        {
          workspaceId: 'workspace-1',
          fetch: fetcher,
          resolveHost: async () => ['127.0.0.1'],
        },
      ),
    ).rejects.toThrow('non-public address');
    expect(fetcher).not.toHaveBeenCalled();
  });

  it('destroys the sandbox when a Script Action fails', async () => {
    const sandbox: SandboxClient = {
      create: vi.fn(async () => 'sandbox-2'),
      exec: vi.fn(async (sandboxId, request) => ({
        toolCallId: request.toolCallId,
        exitCode: 7,
        stdout: '',
        stderr: `failed in ${sandboxId}`,
        timedOut: false,
        truncated: false,
      })),
      destroy: vi.fn(async () => undefined),
    };
    await expect(
      executeV3WorkflowAction(
        {
          node: scriptNode,
          args: [],
          target: scriptNode.command,
          executionKey: 'run-4:notify',
        },
        { workspaceId: 'workspace-1', sandbox },
      ),
    ).rejects.toThrow('exited with code 7');
    expect(sandbox.destroy).toHaveBeenCalledWith('sandbox-2');
  });
});
