import { v3PluginReferences, v3SkillReferences } from '../../product-contracts/src/v3-skill-reference.ts';

type LoadedSkill = { name: string; filePath: string };

/** Adapt product display references using only the current Run's Pi-loaded resources. */
export function resolveV3SkillReferencePrompt(
  text: string,
  skills: ReadonlyMap<string, LoadedSkill>,
  plugins?: ReadonlyMap<string, readonly LoadedSkill[]>,
): string {
  const references = [
    ...v3SkillReferences(text).map((reference) => ({
      start: reference.start,
      end: reference.end,
      resources: skills.has(reference.sourceId) ? [skills.get(reference.sourceId)!] : [],
      replacement: skills.get(reference.sourceId) ? `/${skills.get(reference.sourceId)!.name}` : '',
      plugin: false,
      missing: `Selected Skill is not available in this Run: ${reference.name}`,
    })),
    ...(plugins
      ? v3PluginReferences(text).map((reference) => ({
          start: reference.start,
          end: reference.end,
          resources: plugins.get(reference.pluginName) ?? [],
          replacement: `@${reference.pluginName}`,
          plugin: true,
          missing: `Selected Plugin is not available in this Run: ${reference.name}`,
        }))
      : []),
  ].sort((left, right) => left.start - right.start);
  if (references.length === 0) return text;
  const selected: LoadedSkill[] = [];
  let cursor = 0;
  let prompt = '';
  for (const reference of references) {
    if (!reference.resources.length) throw new Error(reference.missing);
    selected.push(...reference.resources);
    prompt += `${text.slice(cursor, reference.start)}${reference.replacement}`;
    cursor = reference.end;
  }
  prompt += text.slice(cursor);
  return `<system-reminder>\nThe user selected these installed resources. For a selected plugin, choose the resources relevant to the request; selecting a plugin does not request every bundled workflow. Read the relevant source and follow its instructions:\n${selected.map((skill) => `- ${skill.name}: ${skill.filePath}`).join('\n')}\nUse these exact loaded sources; do not substitute a same-named resource.\n</system-reminder>\n\n${prompt}`;
}
