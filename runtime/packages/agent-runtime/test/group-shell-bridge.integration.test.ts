import { randomUUID } from 'node:crypto';
import { mkdir, mkdtemp, rmdir } from 'node:fs/promises';
import { resolve } from 'node:path';
import Docker from 'dockerode';
import { expect, it } from 'vitest';
import { createV3GroupMessagingSandbox } from '../src/v3-group-messaging.ts';
import { executeSandboxCommand } from '../../../services/sandbox-broker/src/sandbox-executor.ts';
import {
  sandboxContainerOptions,
  inspectPolicyIsSafe,
} from '../../../services/sandbox-broker/src/docker-policy.ts';

const real = it.runIf(process.env.V5_GROUP_CLI_IMAGE);

real(
  'keeps repeated sends distinct but preserves their identities when a tool call is replayed',
  async () => {
    await withSandbox(async (sandbox, deliveries) => {
      const request = {
        toolCallId: 'replay',
        timeoutMs: 20000,
        command: 'for i in 1 2; do qoderwake messages send conversation --text SAME; done',
      };
      expect((await sandbox.exec('container', request)).exitCode).toBe(0);
      expect((await sandbox.exec('container', request)).exitCode).toBe(0);
      expect(deliveries).toHaveLength(4);
      expect(deliveries[0]!.id).not.toBe(deliveries[1]!.id);
      expect(deliveries.slice(0, 2)).toEqual(deliveries.slice(2));
    });
  },
  40000,
);

real(
  'does not publish after the real shell timeout',
  async () => {
    await withSandbox(async (sandbox, deliveries) => {
      const result = await sandbox.exec('container', {
        toolCallId: 'timeout',
        timeoutMs: 1000,
        command: 'sleep 5 && qoderwake messages send conversation --text LATE',
      });
      expect(result.timedOut).toBe(true);
      expect(deliveries).toEqual([]);
    });
  },
  30000,
);

real(
  'uses the isolated real shell for expansions, conditions, repeated CLI calls and scope rejection',
  async () => {
    await withSandbox(async (sandbox, deliveries) => {
      const help = await sandbox.exec('container', {
        toolCallId: 'redirected-help',
        timeoutMs: 20000,
        command: 'qoderwake messages send --help 2>&1',
      });
      expect(help.exitCode, help.stderr).toBe(0);
      expect(help.stdout).toContain('--file');
      const result = await sandbox.exec('container', {
        toolCallId: 'compound',
        timeoutMs: 20000,
        command: `value="hello world"; false && qoderwake messages send conversation --text WRONG; qoderwake messages send conversation --text "$value" --json && qoderwake messages send conversation --text 'second; literal $HOME' --json; qoderwake messages send other --text FORBIDDEN`,
      });
      expect(result.exitCode).not.toBe(0);
      expect(deliveries.map((item) => item.text)).toEqual(['hello world', 'second; literal $HOME']);
      expect(new Set(deliveries.map((item) => item.id)).size).toBe(2);
      expect(result.stdout).toContain('hello world');
      expect(result.stderr).toBeTruthy();
      const indirect = await sandbox.exec('container', {
        toolCallId: 'indirect',
        timeoutMs: 20000,
        command: 'cmd=qoder; cmd="${cmd}wake"; "$cmd" messages send conversation --text INDIRECT',
      });
      expect(indirect.exitCode).toBe(0);
      expect(deliveries.at(-1)?.text).toBe('INDIRECT');
      const quoted = await sandbox.exec('container', {
        toolCallId: 'quoted',
        timeoutMs: 20000,
        command:
          "true && 'qoderwake' 'messages' 'send' conversation --text 'QUOTED --help LITERAL' --not-mention --yes --json",
      });
      expect(quoted.exitCode).toBe(0);
      expect(deliveries.at(-1)?.text).toBe('QUOTED --help LITERAL');
      const beforeInvalid = deliveries.length;
      const invalid = await sandbox.exec('container', {
        toolCallId: 'empty-position',
        timeoutMs: 20000,
        command: "true && qoderwake '' messages send conversation --text WRONG",
      });
      expect(invalid.exitCode).not.toBe(0);
      expect(deliveries).toHaveLength(beforeInvalid);
    });
  },
  40000,
);

real(
  'aborts a sleeping shell before it can publish',
  async () => {
    await withSandbox(async (sandbox, deliveries) => {
      const abort = new AbortController();
      const timer = setTimeout(() => abort.abort(new Error('test stop')), 1000);
      try {
        await expect(
          sandbox.exec(
            'container',
            {
              toolCallId: 'cancel',
              timeoutMs: 20000,
              command: 'sleep 5 && qoderwake messages send conversation --text LATE',
            },
            abort.signal,
          ),
        ).rejects.toThrow();
        expect(deliveries).toEqual([]);
      } finally {
        clearTimeout(timer);
      }
    });
  },
  30000,
);

async function withSandbox(
  run: (
    sandbox: ReturnType<typeof createV3GroupMessagingSandbox>,
    deliveries: Array<{ text: string; id: string }>,
  ) => Promise<void>,
) {
  const docker = new Docker();
  const temporaryRoot = resolve('.tmp');
  await mkdir(temporaryRoot, { recursive: true });
  const workspace = await mkdtemp(resolve(temporaryRoot, 'group-cli-'));
  const container = await docker.createContainer(
    sandboxContainerOptions({
      runId: randomUUID(),
      workspacePath: workspace,
      image: process.env.V5_GROUP_CLI_IMAGE!,
    }),
  );
  const deliveries: Array<{ text: string; id: string }> = [];
  try {
    await container.start();
    expect(inspectPolicyIsSafe(await container.inspect())).toBe(true);
    const sandbox = createV3GroupMessagingSandbox({
      sandbox: {
        create: async () => container.id,
        exec: (_id, request, signal) => executeSandboxCommand(container, request, '10001:10001', signal),
        destroy: async () => {
          await container.remove({ force: true }).catch(() => undefined);
        },
      },
      shellBridge: true,
      conversationId: 'conversation',
      onDelivery: async (delivery, id) => {
        deliveries.push({ text: delivery.text, id });
        return {
          message: {
            id,
            sequence: deliveries.length,
            type: 'assistant.message',
            occurredAt: new Date().toISOString(),
            payload: { content: delivery.text, actorParticipantId: 'sender', mentionedParticipantIds: [] },
          },
          replayed: false,
        };
      },
      onList: async () => [],
      onGoalGet: async () => null,
      onGoalMutate: async () => {
        throw new Error('not used');
      },
    });
    await run(sandbox, deliveries);
  } finally {
    await container.remove({ force: true }).catch(() => undefined);
    await rmdir(workspace);
  }
}
