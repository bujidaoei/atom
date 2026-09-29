import { createHash } from 'node:crypto';
import { isAbsolute, relative, resolve } from 'node:path';

import type {
  ToolPolicyDecision,
  ToolPolicyEvaluator,
  ToolPolicyEvidence,
  ToolPolicyInput,
} from './tool-policy.ts';
import type { V3PermissionPolicyVersion } from '../../product-contracts/src/v3.ts';

export interface V3PolicyLayer {
  id: string;
  version: number;
  decisions: Readonly<Record<string, ToolPolicyDecision>>;
  toolGuard?: {
    enabledRuleIds: readonly string[];
    enabledShellEscapeRuleIds: readonly string[];
  };
  fileGuard?: { sensitivePaths: readonly string[] };
}

export interface V3ToolPolicyRequest {
  capability: string;
  operation: 'read' | 'write' | 'execute';
  target: string;
  workspaceRoot: string;
  command?: string;
}

export interface V3ToolPolicyResult {
  decision: ToolPolicyDecision;
  requestHash: string;
  normalizedTarget: string;
  ruleIds: string[];
  policyVersions: Array<{ id: string; version: number }>;
  reason: string;
}

function inside(parent: string, candidate: string): boolean {
  const distance = relative(parent, candidate);
  return distance === '' || (!distance.startsWith('..') && !isAbsolute(distance));
}

function normalizedCommandPath(value: string): string {
  return value.replaceAll('\\', '/').replace(/\/+$/u, '').toLocaleLowerCase('en-US');
}

function commandReferencesPath(command: string, path: string, workspaceRoot: string): boolean {
  const normalizedCommand = normalizedCommandPath(command);
  const candidates = [normalizedCommandPath(resolve(path))];
  const relativePath = relative(resolve(workspaceRoot), resolve(path));
  if (relativePath && !relativePath.startsWith('..') && !isAbsolute(relativePath)) {
    candidates.push(normalizedCommandPath(relativePath).replace(/^\.\//u, ''));
  }
  return candidates.some((candidate) => {
    if (!candidate) return false;
    let offset = normalizedCommand.indexOf(candidate);
    while (offset >= 0) {
      const before = normalizedCommand[offset - 1];
      const after = normalizedCommand[offset + candidate.length];
      const startsAtBoundary = before === undefined || /[\s'"=:(]/u.test(before);
      const endsAtBoundary = after === undefined || /[\s'";&|/)]/u.test(after);
      if (startsAtBoundary && endsAtBoundary) return true;
      offset = normalizedCommand.indexOf(candidate, offset + 1);
    }
    return false;
  });
}

function hash(value: object): string {
  return createHash('sha256').update(JSON.stringify(value)).digest('hex');
}

const RULE_PATTERNS: Readonly<Record<string, RegExp>> = {
  TOOL_CMD_FS_DESTRUCTION:
    /\b(?:mkfs(?:\.[a-z0-9]+)?|fdisk|parted|diskpart\s+clean)\b|\bdd\b[^\n]*\bof=\s*\/(?:dev|proc|sys)\//iu,
  TOOL_CMD_DANGEROUS_RM: /\brm\s+(?:-[a-z]*r[a-z]*f|-rf|-fr)\s+(?:\/|~|\$HOME|\*|\.[.]?(?:\/|$))/iu,
  TOOL_CMD_DANGEROUS_MV: /\bmv\s+(?:-[a-z]*f[a-z]*\s+)?(?:\/etc|\/usr|\/var|~\/\.ssh)\b/iu,
  TOOL_CMD_DOS_FORK_BOMB: /:\s*\(\s*\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:|\bkillall\s+-9\b/iu,
  TOOL_CMD_SYSTEM_REBOOT: /\b(?:reboot|shutdown|halt|poweroff)\b/iu,
  TOOL_CMD_SERVICE_RESTART: /\b(?:systemctl|service|sc(?:\.exe)?)\s+(?:restart|stop|disable)\b/iu,
  TOOL_CMD_PROCESS_KILL: /\b(?:pkill|killall|taskkill)\b|\bkill\s+-9\b/iu,
  TOOL_CMD_PIPE_TO_SHELL: /\b(?:curl|wget)\b[^\n|]*\|\s*(?:ba|z|fi)?sh\b/iu,
  TOOL_CMD_OBFUSCATED_EXEC: /\bbase64\s+(?:-d|--decode)\b[^|]*\|\s*(?:ba|z|fi)?sh\b/iu,
  TOOL_CMD_IFS_INJECTION: /\$\{?IFS\}?/u,
  TOOL_CMD_UNICODE_WHITESPACE: /[\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]/u,
  TOOL_CMD_JQ_SYSTEM: /\bjq\b[^\n]*\bsystem\s*\(/iu,
  TOOL_CMD_JQ_FILE_FLAGS: /\bjq\b[^\n]*(?:--(?:rawfile|slurpfile|argfile)|\s-L\s)/iu,
  TOOL_CMD_ZSH_DANGEROUS: /\bzsh\b[^\n]*(?:\beval\b|\bzmodload\b|\$\{\([^)]*\)\})/iu,
  TOOL_CMD_REVERSE_SHELL: /\b(?:nc|ncat|netcat|socat)\b[^\n]*(?:-e\s|EXEC:)|\/dev\/tcp\//iu,
  TOOL_WEBFETCH_LOCAL_LOOPBACK:
    /(?:https?:\/\/)?(?:localhost|127(?:\.\d{1,3}){3}|\[?::1\]?|169\.254\.169\.254)(?::|\/|$)/iu,
  TOOL_CMD_SYSTEM_TAMPERING: /(?:\/etc\/(?:cron|sudoers)|~?\/\.ssh\/|authorized_keys)/iu,
  TOOL_CMD_PROC_ENVIRON: /\/proc\/(?:self|\d+)\/environ/iu,
  TOOL_WEBFETCH_FILE_SCHEME: /\b(?:file|gopher|dict|ftp):\/\//iu,
  TOOL_CMD_PRIVILEGE_ESCALATION: /\b(?:sudo|su|doas|pkexec|runas)\b/iu,
  TOOL_CMD_UNSAFE_PERMISSIONS: /\bchmod\s+(?:-R\s+)?777\b|\bchattr\s+\+[ai]\b/iu,
};

export function detectV3ToolGuardRules(command: string, enabledRuleIds: readonly string[]): string[] {
  return enabledRuleIds.filter((id) => {
    if (id === 'TOOL_CMD_CONTROL_CHARS') {
      return [...command].some((character) => {
        const code = character.codePointAt(0) ?? 0;
        return code === 127 || (code < 32 && code !== 9 && code !== 10 && code !== 13);
      });
    }
    return RULE_PATTERNS[id]?.test(command);
  });
}

function shellTextOutsideSingleQuotes(command: string): string {
  let result = '';
  let singleQuoted = false;
  let doubleQuoted = false;
  let escaped = false;
  for (const character of command) {
    if (escaped) {
      result += character === '\n' || character === '\r' ? character : ' ';
      escaped = false;
      continue;
    }
    if (!singleQuoted && character === '\\') {
      result += ' ';
      escaped = true;
      continue;
    }
    if (!doubleQuoted && character === "'") {
      singleQuoted = !singleQuoted;
      result += ' ';
      continue;
    }
    if (!singleQuoted && character === '"') {
      doubleQuoted = !doubleQuoted;
    }
    result += singleQuoted && character !== '\n' && character !== '\r' ? ' ' : character;
  }
  return result;
}

function hasShellCommentQuoteDesync(command: string): boolean {
  let singleQuoted = false;
  let doubleQuoted = false;
  let escaped = false;
  for (let index = 0; index < command.length; index += 1) {
    const character = command[index]!;
    if (escaped) {
      escaped = false;
      continue;
    }
    if (!singleQuoted && character === '\\') {
      escaped = true;
      continue;
    }
    if (!doubleQuoted && character === "'") {
      singleQuoted = !singleQuoted;
      continue;
    }
    if (!singleQuoted && character === '"') {
      doubleQuoted = !doubleQuoted;
      continue;
    }
    if (singleQuoted || doubleQuoted || character !== '#') continue;
    const previous = index === 0 ? '' : command[index - 1]!;
    if (index > 0 && !/[\s;&|()<>]/u.test(previous)) continue;
    const lineEnd = command.indexOf('\n', index + 1);
    const comment = command.slice(index + 1, lineEnd === -1 ? undefined : lineEnd);
    if (/['"]/u.test(comment)) return true;
  }
  return false;
}

export function detectV3ShellEscapeRules(command: string, enabledRuleIds: readonly string[]): string[] {
  const executableText = shellTextOutsideSingleQuotes(command);
  const tests: Readonly<Record<string, () => boolean>> = {
    SHELL_COMMAND_SUBSTITUTION: () =>
      /`[^`]+`|\$\([^)]*\)|[<=]\([^)]*\)|\$\[[^\]]*\]|(?:^|\s)=[^\s]+|<#/u.test(executableText),
    SHELL_OBFUSCATED_FLAGS: () => /\$['"]|(?:''|"")-|['"]--?[a-z0-9][^'"]*['"]/iu.test(command),
    SHELL_BACKSLASH_WHITESPACE: () => /\\[ \t]/u.test(command),
    SHELL_BACKSLASH_OPERATOR: () =>
      /\\[|&<>]/u.test(command) ||
      (/\\;/u.test(command) && !/find\b[^\n]*-exec\b[^\n]*\{\}\s*\\;\s*$/iu.test(command)),
    SHELL_NEWLINES: () =>
      /\r/u.test(command) ||
      (/\n\s*\S/u.test(command) && !/<<[-]?\s*['"]?([A-Z_][A-Z0-9_]*)['"]?[\s\S]*\n\1\s*$/iu.test(command)),
    SHELL_COMMENT_QUOTE_DESYNC: () => hasShellCommentQuoteDesync(command),
    SHELL_QUOTED_NEWLINE: () => /(['"])[^\n]*\n\s*#[\s\S]*\1/u.test(command),
  };
  return enabledRuleIds.filter((id) => tests[id]?.());
}

export function evaluateV3ToolPolicy(
  request: V3ToolPolicyRequest,
  layers: readonly V3PolicyLayer[],
): V3ToolPolicyResult {
  const workspaceRoot = resolve(request.workspaceRoot);
  const normalizedTarget = resolve(request.target);
  const policyVersions = layers.map(({ id, version }) => ({ id, version }));
  const requestHash = hash({
    capability: request.capability,
    operation: request.operation,
    target: normalizedTarget,
    workspaceRoot,
    command: request.command ?? '',
    policyVersions,
  });
  if (!inside(workspaceRoot, normalizedTarget)) {
    return {
      decision: 'deny',
      requestHash,
      normalizedTarget,
      ruleIds: ['host.workspace-boundary'],
      policyVersions,
      reason: 'target is outside the assigned workspace',
    };
  }
  const decisions = layers.flatMap((layer) => {
    const decision = layer.decisions[request.capability];
    return decision ? [{ id: `${layer.id}.${request.capability}`, decision }] : [];
  });
  const denied = decisions.filter(({ decision }) => decision === 'deny').map(({ id }) => id);
  if (denied.length) {
    return {
      decision: 'deny',
      requestHash,
      normalizedTarget,
      ruleIds: denied,
      policyVersions,
      reason: 'one or more effective policy layers deny this capability',
    };
  }
  const guardRules = request.command
    ? layers.flatMap((layer) => [
        ...(layer.toolGuard ? detectV3ToolGuardRules(request.command!, layer.toolGuard.enabledRuleIds) : []),
        ...(request.capability === 'Bash' && layer.toolGuard
          ? detectV3ShellEscapeRules(request.command!, layer.toolGuard.enabledShellEscapeRuleIds)
          : []),
      ])
    : [];
  const sensitivePaths = layers.flatMap((layer) => layer.fileGuard?.sensitivePaths ?? []);
  const sensitive = sensitivePaths.some(
    (path) =>
      inside(resolve(path), normalizedTarget) ||
      (request.command ? commandReferencesPath(request.command, path, workspaceRoot) : false),
  );
  const asked = [
    ...decisions.filter(({ decision }) => decision === 'ask').map(({ id }) => id),
    ...guardRules,
    ...(sensitive ? ['file_guard.sensitive_path'] : []),
  ];
  return {
    decision: asked.length || decisions.length === 0 ? 'ask' : 'allow',
    requestHash,
    normalizedTarget,
    ruleIds: asked.length ? [...new Set(asked)] : decisions.map(({ id }) => id),
    policyVersions,
    reason: asked.length ? 'explicit user approval is required' : 'all effective policy layers allow',
  };
}

export function permissionPolicyLayers(versions: readonly V3PermissionPolicyVersion[]): V3PolicyLayer[] {
  return versions.flatMap((policy) => {
    const configuration = policy.configuration;
    if (configuration.kind === 'builtin_tools') {
      return configuration.enabled
        ? [{ id: policy.id, version: policy.number, decisions: configuration.decisions }]
        : [];
    }
    if (configuration.kind === 'host_capability') {
      return [{ id: policy.id, version: policy.number, decisions: configuration.decisions }];
    }
    if (configuration.kind === 'tool_guard') {
      return configuration.enabled
        ? [
            {
              id: policy.id,
              version: policy.number,
              decisions: {},
              toolGuard: {
                enabledRuleIds: configuration.enabledRuleIds,
                enabledShellEscapeRuleIds: configuration.enabledShellEscapeRuleIds,
              },
            },
          ]
        : [];
    }
    if (configuration.kind === 'file_guard') {
      return configuration.enabled
        ? [
            {
              id: policy.id,
              version: policy.number,
              decisions: {},
              fileGuard: { sensitivePaths: configuration.sensitivePaths },
            },
          ]
        : [];
    }
    return [];
  });
}

export function assertV3ModelSecurity(versions: readonly V3PermissionPolicyVersion[], model: string): void {
  const configuration = versions.find(({ kind }) => kind === 'model_security')?.configuration;
  if (
    configuration?.kind === 'model_security' &&
    configuration.enabled &&
    !configuration.allowedModels.includes(model)
  ) {
    throw new Error(`Model security policy does not allow model: ${model}`);
  }
}

export function compileV3ToolPolicy(
  workspaceRoot: string,
  layers: readonly V3PolicyLayer[],
): ToolPolicyEvaluator {
  const evidence = (input: ToolPolicyInput): ToolPolicyEvidence =>
    evaluateV3ToolPolicy(
      {
        capability: input.tool,
        operation: input.operation,
        target: input.target,
        workspaceRoot,
        ...(input.command ? { command: input.command } : {}),
      },
      layers,
    );
  return {
    evaluate(input) {
      return evidence(input).decision;
    },
    evaluateEvidence: evidence,
  };
}
