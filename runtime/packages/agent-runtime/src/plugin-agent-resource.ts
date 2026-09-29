/**
 * Package adapter for Pi 0.86.1's examples/extensions/subagent/agents.ts format.
 * Pi provides frontmatter parsing and independent sessions; this only validates
 * declared archive resources. It neither starts an Agent nor selects a model.
 * Replace this adapter when Pi exposes equivalent scoped package discovery.
 */
export interface PluginAgentResource {
  name: string;
  description: string;
  path: string;
  systemPrompt: string;
  tools?: string[];
  allowedTools?: string[];
  /** Upstream hint only. Execution must retain the product gateway model policy. */
  modelHint?: string;
}

export async function parsePluginAgentResource(
  path: string,
  bytes: Uint8Array,
): Promise<PluginAgentResource> {
  if (bytes.byteLength > 512 * 1024) throw new Error('Plugin Agent resource exceeds size policy');
  const markdown = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  const { parseFrontmatter } = await import('./pi-runtime-loader.mjs');
  const { frontmatter, body } = parseFrontmatter(markdown);
  const { name, description, tools, model } = frontmatter;
  if (typeof name !== 'string' || !name.trim() || name.length > 128 || /[\r\n\t\0]/u.test(name))
    throw new Error('Invalid plugin Agent name');
  if (typeof description !== 'string' || !description.trim())
    throw new Error('Plugin Agent description is missing');
  if (!body.trim()) throw new Error('Plugin Agent instructions are missing');
  if (model !== undefined && (typeof model !== 'string' || !model.trim()))
    throw new Error('Invalid plugin Agent model hint');

  const parseTools = (value: unknown): string[] | undefined => {
    if (value === undefined) return undefined;
    const entries: unknown = typeof value === 'string' ? value.split(',') : value;
    // Unlike best-effort local discovery, malformed package constraints must not
    // become an unrestricted Agent. An explicit empty list remains empty.
    if (!Array.isArray(entries) || entries.some((entry) => typeof entry !== 'string' || !entry.trim()))
      throw new Error('Invalid plugin Agent tool restriction');
    return [...new Set((entries as string[]).map((entry) => entry.trim()))];
  };
  const toolNames = parseTools(tools);
  // Preserve the distinct Qoder/Claude spelling; execution must resolve both
  // constraints against the parent's available tools, never silently ignore one.
  const allowedTools = parseTools(frontmatter['allowed-tools']);
  return {
    name,
    description,
    path,
    systemPrompt: body,
    ...(toolNames === undefined ? {} : { tools: toolNames }),
    ...(allowedTools === undefined ? {} : { allowedTools }),
    ...(typeof model === 'string' ? { modelHint: model } : {}),
  };
}
