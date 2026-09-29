import { createHash } from 'node:crypto';

import type {
  V3RequestContext,
  V3WakerConfigurationRepository,
} from '../../product-contracts/src/v3-ports.ts';
import type {
  V3WakerBuiltinCapabilities,
  V3WakerConfigurationVersion,
  V3WakerDocumentKind,
  V3WakerDocumentVersion,
} from '../../product-contracts/src/v3.ts';
import { defaultWakerBuiltinCapabilities } from '../../product-contracts/src/v3.ts';
import { canonicalV3JsonbText } from '../../product-contracts/src/v3-canonical-json.ts';

export interface V3ResolvedEffectiveConfiguration {
  configuration: V3WakerConfigurationVersion;
  /**
   * The four documents the official runtime injects into Run prompts. The
   * context documents (core capabilities, work styles, delivery commitments)
   * only back product surfaces and are not part of the system prompt.
   */
  documents: Record<
    Extract<V3WakerDocumentKind, 'identity' | 'persona' | 'bible' | 'memory'>,
    V3WakerDocumentVersion
  >;
}

function sha256(value: string): string {
  return createHash('sha256').update(value).digest('hex');
}

export async function resolveV3EffectiveConfiguration(
  repository: V3WakerConfigurationRepository,
  context: V3RequestContext,
  configurationVersionId: string,
): Promise<V3ResolvedEffectiveConfiguration> {
  const configuration = await repository.getVersion(context, configurationVersionId);
  if (!configuration) throw new Error(`Effective Waker configuration not found: ${configurationVersionId}`);
  if (sha256(canonicalV3JsonbText(configuration.effectiveSnapshot)) !== configuration.snapshotSha256) {
    throw new Error(`Effective Waker configuration integrity check failed: ${configurationVersionId}`);
  }
  const kinds = ['identity', 'persona', 'bible', 'memory'] as const;
  const entries = await Promise.all(
    kinds.map(async (kind) => {
      const versionId = configuration.effectiveSnapshot.documents[kind];
      const version = await repository.getDocumentVersion(context, configuration.wakerId, kind, versionId);
      if (!version) throw new Error(`Effective ${kind} document version not found: ${versionId}`);
      if (sha256(version.content) !== version.sha256) {
        throw new Error(`Effective ${kind} document integrity check failed: ${versionId}`);
      }
      return [kind, version] as const;
    }),
  );
  return {
    configuration,
    documents: Object.fromEntries(entries) as V3ResolvedEffectiveConfiguration['documents'],
  };
}

export function buildV3EffectiveSystemPrompt(
  resolved: V3ResolvedEffectiveConfiguration,
  boundKnowledge = '',
  capabilities: V3WakerBuiltinCapabilities = defaultWakerBuiltinCapabilities(),
): string {
  const { profile, resources } = resolved.configuration.effectiveSnapshot;
  const configuredResources = [
    ...resources.skillInstallationVersionIds.map((id) => `skill:${id}`),
    ...resources.knowledgeBindingVersionIds.map((id) => `knowledge:${id}`),
    ...resources.connectorToolSelectionVersionIds.map((id) => `connector:${id}`),
    ...resources.permissionPolicyVersionIds.map((id) => `permission:${id}`),
  ];
  const memorySection = capabilities.memory
    ? `\n## Durable Memory\n${resolved.documents.memory.content}\n`
    : '';
  const knowledgeSection =
    capabilities.knowledge && boundKnowledge ? `## Bound Knowledge\n${boundKnowledge}\n` : '';
  return `You are ${profile.name}, the ${profile.roleName} Waker in QoderWake.
Biography: ${profile.bio || 'No biography has been configured.'}

The configuration binding below is immutable for this Run. Follow it as operating context while preserving platform safety and the user request.
Configuration version: ${resolved.configuration.id} (number ${resolved.configuration.number})
Bound resource versions: ${configuredResources.join(', ') || 'none'}

## Identity
${resolved.documents.identity.content}

## Persona
${resolved.documents.persona.content}

## Operating Bible
${resolved.documents.bible.content}
${memorySection}
${knowledgeSection}
Plan before acting. Use read_file, glob, and grep for workspace inspection. Use write for new files or complete rewrites, and sandbox_exec for shell commands, builds, and verification. Never claim host access or evidence that was not produced by a successful operation. Keep changes inside the assigned workspace and report concrete results.`;
}
