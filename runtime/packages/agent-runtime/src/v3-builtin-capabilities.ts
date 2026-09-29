import {
  defaultWakerBuiltinCapabilities,
  type V3WakerBuiltinCapabilities,
} from '../../product-contracts/src/v3.ts';
import type { V3RequestContext } from '../../product-contracts/src/v3-ports.ts';

/** Official served-bundle skill-id → persist-key map. */
export const OFFICIAL_WAKER_BUILTIN_SKILL_IDS = {
  'waker-memory': 'memory',
  'waker-knowledge': 'knowledge',
  'waker-im-channel-send': 'imChannelSend',
  'waker-im-chat-history': 'groupChatContext',
} as const satisfies Record<string, keyof V3WakerBuiltinCapabilities>;

export function officialBuiltinCapabilityForTool(name: string): keyof V3WakerBuiltinCapabilities | undefined {
  for (const [skillId, key] of Object.entries(OFFICIAL_WAKER_BUILTIN_SKILL_IDS)) {
    if (name === skillId || name.endsWith(`_${skillId}`)) return key;
  }
  return undefined;
}

export function filterToolsByWakerBuiltinCapabilities<T extends { name: string }>(
  tools: readonly T[],
  capabilities: V3WakerBuiltinCapabilities = defaultWakerBuiltinCapabilities(),
): T[] {
  return tools.filter((tool) => {
    const key = officialBuiltinCapabilityForTool(tool.name);
    return key === undefined || capabilities[key];
  });
}

export async function loadWakerBuiltinCapabilities(
  repository:
    | {
        getBuiltinCapabilities(
          context: V3RequestContext,
          wakerId: string,
        ): Promise<V3WakerBuiltinCapabilities | undefined>;
      }
    | undefined,
  context: V3RequestContext,
  wakerId: string,
): Promise<V3WakerBuiltinCapabilities> {
  return (await repository?.getBuiltinCapabilities(context, wakerId)) ?? defaultWakerBuiltinCapabilities();
}
