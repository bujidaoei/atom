import { realpath, stat } from 'node:fs/promises';
import { isAbsolute, relative, resolve, sep } from 'node:path';
import type { PluginMcpDeclaration } from '../../data-access/src/v3/plugin-mcp-declarations.ts';

// Pi 0.86.1 core/extensions/types.ts supports external tools; it does not resolve
// Qoder plugin paths. This adapter only prepares launch data for that existing
// tool path. Replace it if upstream adds an equivalent package resolver.
/** Resolve verified package data at the runtime host, never at the API host. */
export async function resolvePluginMcpLaunch(
  declaration: PluginMcpDeclaration,
  packageDirectory: string,
  variables: Readonly<Record<string, string>> = {},
  platform: NodeJS.Platform = process.platform,
) {
  const root = await realpath(packageDirectory);
  const expand = (value: string): string => {
    const expanded = value.replace(/\$\{([A-Za-z_][A-Za-z0-9_]*)\}/gu, (_match, key: string) => {
      if (key === 'PLUGIN_ROOT') return root;
      if (!Object.hasOwn(variables, key)) throw new Error(`Plugin MCP variable is required: ${key}`);
      return variables[key]!;
    });
    if (expanded.includes('${') || expanded.includes('\0'))
      throw new Error('Unsupported plugin MCP variable expression');
    return expanded;
  };
  const inside = async (path: string) => {
    const canonical = await realpath(resolve(root, path));
    const delta = relative(root, canonical);
    if (isAbsolute(delta) || delta === '..' || delta.startsWith(`..${sep}`))
      throw new Error('Plugin MCP launch path escapes its package');
    return canonical;
  };
  let command = declaration.command;
  if (command) {
    // Executable variables are intentionally not evaluated: the package format
    // uses a bare executable or a ./-relative entry point for command.
    if (command.includes('${')) throw new Error('Plugin MCP command cannot contain variables');
    if (command.startsWith('./')) {
      let target = command;
      if (platform === 'win32' && !/\.(?:exe|com|cmd|bat)$/iu.test(target)) {
        // A shipped Windows twin is an explicit package entry, not a shell
        // command synthesized from a POSIX script. MCP SDK handles its launch.
        try {
          const candidate = await inside(`${target}.cmd`);
          if ((await stat(candidate)).isFile()) target = `${target}.cmd`;
        } catch (error) {
          if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error;
        }
      }
      command = await inside(target);
      if (!(await stat(command)).isFile()) throw new Error('Plugin MCP command is not a file');
    } else if (isAbsolute(command) || /[\\/]/u.test(command)) {
      throw new Error('Plugin MCP command must be bare or package-relative');
    }
  }
  const cwd = await inside(expand(declaration.cwd ?? '.'));
  if (!(await stat(cwd)).isDirectory()) throw new Error('Plugin MCP cwd is not a directory');
  const mapValues = (input: Record<string, string>) =>
    Object.fromEntries(Object.entries(input).map(([key, value]) => [key, expand(value)]));
  return {
    command,
    arguments: declaration.arguments.map(expand),
    url: declaration.url === null ? null : expand(declaration.url),
    cwd,
    environment: mapValues(declaration.environment),
    headers: mapValues(declaration.headers),
  };
}
