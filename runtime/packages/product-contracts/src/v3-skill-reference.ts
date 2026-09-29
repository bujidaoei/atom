export interface V3SkillReference {
  sourceId: string;
  name: string;
  token: string;
  start: number;
  end: number;
}

/** The official Add-content display token; source identity is opaque to the editor. */
export function v3SkillReferenceToken(sourceId: string, name: string): string {
  return `[[capability:${encodeURIComponent(JSON.stringify(['skill', sourceId, name]))}]]`;
}

export function v3SkillReferenceSource(versionId: string): string {
  return JSON.stringify(['skill', versionId]);
}

const pluginNamePattern = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/u;

export interface V3PluginReference {
  pluginName: string;
  name: string;
  token: string;
  start: number;
  end: number;
}

/** Official Add-content plugin chip: `[[capability:["plugin", pluginName, displayName]]]`. */
export function v3PluginReferenceToken(pluginName: string, name: string): string {
  return `[[capability:${encodeURIComponent(JSON.stringify(['plugin', pluginName, name]))}]]`;
}

export function v3PluginReferences(text: string): V3PluginReference[] {
  const references: V3PluginReference[] = [];
  for (const match of text.matchAll(/\[\[capability:([^\]\r\n]+)\]\]/gu)) {
    try {
      const tuple: unknown = JSON.parse(decodeURIComponent(match[1]!));
      if (
        !Array.isArray(tuple) ||
        tuple.length !== 3 ||
        tuple[0] !== 'plugin' ||
        typeof tuple[1] !== 'string' ||
        !pluginNamePattern.test(tuple[1]) ||
        typeof tuple[2] !== 'string' ||
        !tuple[2]
      )
        continue;
      references.push({
        pluginName: tuple[1],
        name: tuple[2],
        token: match[0],
        start: match.index,
        end: match.index + match[0].length,
      });
    } catch {
      // Ordinary user text may resemble a reference. Preserve malformed tokens verbatim.
    }
  }
  return references;
}

export function v3SkillReferences(text: string): V3SkillReference[] {
  const references: V3SkillReference[] = [];
  for (const match of text.matchAll(/\[\[capability:([^\]\r\n]+)\]\]/gu)) {
    try {
      const tuple: unknown = JSON.parse(decodeURIComponent(match[1]!));
      if (
        !Array.isArray(tuple) ||
        tuple.length !== 3 ||
        tuple[0] !== 'skill' ||
        typeof tuple[1] !== 'string' ||
        !tuple[1] ||
        typeof tuple[2] !== 'string' ||
        !tuple[2]
      )
        continue;
      references.push({
        sourceId: tuple[1],
        name: tuple[2],
        token: match[0],
        start: match.index,
        end: match.index + match[0].length,
      });
    } catch {
      // Ordinary user text may resemble a reference. Preserve malformed tokens verbatim.
    }
  }
  return references;
}
