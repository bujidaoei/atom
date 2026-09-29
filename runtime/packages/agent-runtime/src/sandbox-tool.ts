import { Type } from 'typebox';

import type { ApprovalAdapter, SandboxClient } from '../../product-contracts/src/index.ts';
import type { ToolDefinition } from './pi-runtime-types.ts';
import type { ToolPolicyEvaluator } from './tool-policy.ts';
import type { ToolPolicyEvidence } from './tool-policy.ts';

const SandboxExecParameters = Type.Object(
  {
    command: Type.String({ minLength: 1, maxLength: 16_000 }),
    timeoutMs: Type.Optional(Type.Integer({ minimum: 1_000, maximum: 120_000 })),
  },
  { additionalProperties: false },
);

export interface SandboxExecToolOptions {
  runId: string;
  sandboxId: string;
  workspacePath: string;
  sandbox: SandboxClient;
  approvals: ApprovalAdapter;
  policy?: ToolPolicyEvaluator;
  onPolicyDecision?: (evidence: ToolPolicyEvidence) => Promise<void>;
}

export interface GuardedSandboxCommand {
  tool: string;
  operation: 'read' | 'write' | 'execute';
  target: string;
  command: string;
  timeoutMs: number;
  deniedMessage: string;
  rejectedMessage: string;
}

export async function guardSandboxOperation(
  options: SandboxExecToolOptions,
  toolCallId: string,
  input: GuardedSandboxCommand,
  signal: AbortSignal | undefined,
) {
  signal?.throwIfAborted();
  const policyInput = {
    tool: input.tool,
    operation: input.operation,
    target: input.target,
    command: input.command,
  };
  const policyEvidence = options.policy?.evaluateEvidence?.(policyInput);
  const policyDecision = policyEvidence?.decision ?? options.policy?.evaluate(policyInput) ?? 'ask';
  if (policyEvidence) await options.onPolicyDecision?.(policyEvidence);
  if (policyDecision === 'deny') {
    return {
      content: [{ type: 'text' as const, text: input.deniedMessage }],
      details: { approved: false, policyDecision },
      terminate: true,
    };
  }
  const decision =
    policyDecision === 'allow'
      ? 'approved'
      : await options.approvals.request({
          runId: options.runId,
          toolCallId,
          command: input.command,
          target: input.target,
          risk: input.operation,
          ...(policyEvidence
            ? {
                requestHash: policyEvidence.requestHash,
                ruleIds: policyEvidence.ruleIds,
                policyVersions: policyEvidence.policyVersions,
              }
            : {}),
        });
  signal?.throwIfAborted();
  if (decision === 'rejected') {
    return {
      content: [{ type: 'text' as const, text: input.rejectedMessage }],
      details: { approved: false, policyDecision },
      isError: true,
    };
  }
  return undefined;
}

export async function executeGuardedSandboxCommand(
  options: SandboxExecToolOptions,
  toolCallId: string,
  input: GuardedSandboxCommand,
  signal: AbortSignal | undefined,
) {
  const blocked = await guardSandboxOperation(options, toolCallId, input, signal);
  if (blocked) return blocked;
  const result = await options.sandbox.exec(
    options.sandboxId,
    { toolCallId, command: input.command, timeoutMs: input.timeoutMs },
    signal,
  );
  signal?.throwIfAborted();
  const output = [result.stdout, result.stderr].filter(Boolean).join('\n').trim();
  // Pi agent-loop derives tool failure from rejection, as its official Bash tool does.
  // Returning an isError property here would still emit a successful tool_execution_end.
  if (result.timedOut || result.exitCode !== 0) {
    const status = result.timedOut
      ? `Command timed out after ${input.timeoutMs / 1_000} seconds (exit code ${result.exitCode})`
      : `Command exited with code ${result.exitCode}`;
    throw new Error([output, status].filter(Boolean).join('\n\n'));
  }
  return {
    content: [{ type: 'text' as const, text: output || `(command exited with code ${result.exitCode})` }],
    details: result,
  };
}

export function createSandboxExecTool(
  options: SandboxExecToolOptions,
): ToolDefinition<typeof SandboxExecParameters> {
  return {
    name: 'sandbox_exec',
    label: 'Docker 沙箱命令',
    description:
      '在隔离的 Docker 沙箱中执行 Shell、Git、Python、Node 或其他 CLI 命令。不要假设可以直接访问宿主机。',
    promptSnippet: '在 Docker 沙箱中执行受审批和资源限制的命令',
    promptGuidelines: [
      '所有命令只能通过 sandbox_exec 执行。',
      '对工作区进行写操作前，先说明目的并等待审批。',
      '不要尝试访问 Docker Socket、宿主机凭据或工作区之外的路径。',
    ],
    parameters: SandboxExecParameters,
    executionMode: 'sequential',
    async execute(toolCallId, params, signal) {
      return executeGuardedSandboxCommand(
        options,
        toolCallId,
        {
          tool: 'Bash',
          operation: 'execute',
          target: options.workspacePath,
          command: params.command,
          timeoutMs: params.timeoutMs ?? 60_000,
          deniedMessage: '权限策略禁止执行该沙箱命令。',
          rejectedMessage: '用户拒绝了该沙箱命令。',
        },
        signal,
      );
    },
  };
}
