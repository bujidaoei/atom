import { Type } from 'typebox';
import { verifiedPluginMcpToolNames } from './plugin-mcp-tool-identity.ts';
import type { ToolDefinition } from './pi-runtime-types.ts';
import { parsePluginAgentResource, type PluginAgentResource } from './plugin-agent-resource.ts';
import { readIntegrityBoundResource, type ProductSkillDirectory } from './workspace-tools.ts';
import {
  runPluginAgentSession,
  type PluginAgentSessionOptions,
  type PluginAgentSessionResult,
} from './plugin-agent-session.ts';

const aliases: Record<string, string> = {
  Read: 'read',
  Write: 'write',
  Edit: 'edit',
  Glob: 'glob',
  Grep: 'grep',
  Bash: 'sandbox_exec',
};

/** Restrictions only reduce the already authorized tool set; unknown names never enable tools. */
export function pluginAgentTools(
  agent: Pick<PluginAgentResource, 'tools' | 'allowedTools'>,
  tools: readonly ToolDefinition[],
  pluginName?: string,
): ToolDefinition[] {
  return tools.filter((tool) =>
    [agent.tools, agent.allowedTools].every(
      (restrictions) =>
        restrictions === undefined ||
        restrictions.some((raw) => {
          const name = aliases[raw] ?? raw;
          return [tool.name, ...verifiedPluginMcpToolNames(tool, pluginName)].some(
            (candidate) =>
              name === candidate ||
              (name.endsWith('*') &&
                !name.slice(0, -1).includes('*') &&
                candidate.startsWith(name.slice(0, -1))),
          );
        }),
    ),
  );
}

export async function createPluginAgentTool(options: {
  directories: readonly ProductSkillDirectory[];
  session: Omit<PluginAgentSessionOptions, 'task' | 'systemPrompt' | 'onEvent' | 'signal'>;
  parentSystemPrompt: string;
  onComplete?(result: PluginAgentSessionResult): Promise<void>;
}): Promise<ToolDefinition | undefined> {
  const agents = new Map<
    string,
    { agent: PluginAgentResource; file: ProductSkillDirectory['files'][number]; pluginName: string }
  >();
  for (const directory of options.directories) {
    for (const path of directory.agentPaths ?? []) {
      if (!directory.pluginName) throw new Error('Plugin Agent namespace is missing');
      const file = directory.files.find((file) => file.path === path);
      if (!file) throw new Error('Plugin Agent is outside its verified inventory');
      const agent = await parsePluginAgentResource(path, await readIntegrityBoundResource(file));
      const name = `${directory.pluginName}:${agent.name}`;
      if (agents.has(name)) throw new Error('Duplicate bound plugin Agent');
      agents.set(name, { agent, file, pluginName: directory.pluginName });
    }
  }
  if (!agents.size) return undefined;
  // Capture before the caller appends this dispatcher: children cannot recurse
  // into it or obtain tools registered later by unrelated resources.
  const tools = [...options.session.tools];
  return {
    name: 'plugin_agent',
    label: '插件子智能体',
    description: `Delegate a focused task to an installed plugin Agent in a separate context. Available Agents:\n${[...agents].map(([name, { agent }]) => `${name}: ${agent.description}`).join('\n')}`,
    parameters: Type.Object({ agent: Type.String({ minLength: 1 }), task: Type.String({ minLength: 1 }) }),
    executionMode: 'sequential',
    execute: async (_id, params, signal, onUpdate) => {
      const input = params as { agent: string; task: string };
      const selected = agents.get(input.agent);
      if (!selected) throw new Error('Requested plugin Agent is not installed in this task');
      signal?.throwIfAborted();
      // Recheck bytes immediately before use; do not trust a mutable cache after discovery.
      await readIntegrityBoundResource(selected.file);
      const result = await runPluginAgentSession({
        ...options.session,
        tools: pluginAgentTools(selected.agent, tools, selected.pluginName),
        task: input.task,
        systemPrompt: `${options.parentSystemPrompt}\n\nPlugin Agent: ${input.agent}\n${selected.agent.systemPrompt}`,
        ...(signal ? { signal } : {}),
        onEvent: async (event) => {
          onUpdate?.({ content: [], details: { agent: input.agent, event } });
        },
      });
      await options.onComplete?.(result);
      return {
        content: [
          {
            type: 'text',
            text: result.status === 'completed' ? result.text : result.error || 'Plugin Agent failed',
          },
        ],
        details: { agent: input.agent, ...result },
        isError: result.status !== 'completed',
      };
    },
  };
}
