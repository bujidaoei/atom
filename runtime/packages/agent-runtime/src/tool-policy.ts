import { resolve, sep } from 'node:path';

export type ToolPolicyDecision = 'allow' | 'ask' | 'deny';
export type ToolOperation = 'read' | 'write' | 'execute';

export interface ToolPolicyInput {
  tool: string;
  operation: ToolOperation;
  target: string;
  command?: string;
}

export interface ToolPolicyEvidence {
  decision: ToolPolicyDecision;
  requestHash: string;
  normalizedTarget: string;
  ruleIds: string[];
  policyVersions: Array<{ id: string; version: number }>;
  reason: string;
}

export interface ToolPolicyEvaluator {
  evaluate(input: ToolPolicyInput): ToolPolicyDecision;
  evaluateEvidence?(input: ToolPolicyInput): ToolPolicyEvidence;
}

export interface ToolPolicyConfiguration {
  enabled: boolean;
  decisions?: Record<string, ToolPolicyDecision>;
  sensitivePaths?: string[];
}

function normalizePolicyPath(value: string): string {
  const normalized = resolve(value);
  return process.platform === 'win32' ? normalized.toLocaleLowerCase('en-US') : normalized;
}

function containsPath(parent: string, candidate: string): boolean {
  return candidate === parent || candidate.startsWith(`${parent}${sep}`);
}

export function compileToolPolicy(configuration: ToolPolicyConfiguration): ToolPolicyEvaluator {
  const sensitivePaths = (configuration.sensitivePaths ?? [])
    .filter((value) => value.trim())
    .map(normalizePolicyPath);
  const decisions = { ...configuration.decisions };

  return {
    evaluate(input) {
      if (!configuration.enabled) return 'ask';
      const target = normalizePolicyPath(input.target);
      if (sensitivePaths.some((sensitivePath) => containsPath(sensitivePath, target))) return 'ask';
      return decisions[input.tool] ?? 'ask';
    },
  };
}
