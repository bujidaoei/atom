import { createHash } from 'node:crypto';

import { describe, expect, it } from 'vitest';

import type {
  V3RequestContext,
  V3WakerConfigurationRepository,
} from '../../product-contracts/src/v3-ports.ts';
import type {
  V3WakerConfigurationVersion,
  V3WakerDocumentKind,
  V3WakerDocumentVersion,
} from '../../product-contracts/src/v3.ts';
import { canonicalV3JsonbText } from '../../product-contracts/src/v3-canonical-json.ts';
import {
  buildV3EffectiveSystemPrompt,
  resolveV3EffectiveConfiguration,
} from '../src/v3-effective-configuration.ts';

const context = {} as V3RequestContext;
const ids = {
  configuration: '11111111-1111-4111-8111-111111111111',
  waker: '22222222-2222-4222-8222-222222222222',
  identity: '33333333-3333-4333-8333-333333333331',
  persona: '33333333-3333-4333-8333-333333333332',
  bible: '33333333-3333-4333-8333-333333333333',
  memory: '33333333-3333-4333-8333-333333333334',
  core_capabilities: '33333333-3333-4333-8333-333333333335',
  work_styles: '33333333-3333-4333-8333-333333333336',
  delivery_commitments: '33333333-3333-4333-8333-333333333337',
};
const contents: Record<V3WakerDocumentKind, string> = {
  identity: 'Build production APIs.',
  persona: 'Be precise.',
  bible: 'Test before reporting.',
  memory: 'The user prefers concise evidence.',
  core_capabilities: '[{"name":"Code review","description":"Structured reports."}]',
  work_styles: '["Calm and precise"]',
  delivery_commitments: '[{"taskType":"Build","workflow":"Design → Test"}]',
};
const snapshot = {
  profile: {
    name: 'Backend',
    roleName: 'Backend Engineer',
    bio: 'Builds durable services.',
    roleTemplateVersionId: null,
    avatarObjectId: null,
  },
  documents: {
    identity: ids.identity,
    persona: ids.persona,
    bible: ids.bible,
    memory: ids.memory,
    core_capabilities: ids.core_capabilities,
    work_styles: ids.work_styles,
    delivery_commitments: ids.delivery_commitments,
  },
  resources: {
    skillInstallationVersionIds: [],
    knowledgeBindingVersionIds: [],
    connectorToolSelectionVersionIds: [],
    imPairingVersionIds: [],
    permissionPolicyVersionIds: [],
  },
  modelPolicy: {},
};
const configuration: V3WakerConfigurationVersion = {
  id: ids.configuration,
  wakerId: ids.waker,
  number: 7,
  effectiveSnapshot: snapshot,
  snapshotSha256: createHash('sha256').update(canonicalV3JsonbText(snapshot)).digest('hex'),
  createdBy: null,
  reason: 'test',
  createdAt: '2026-08-14T00:00:00.000Z',
};
const documents = Object.fromEntries(
  (Object.keys(contents) as V3WakerDocumentKind[]).map((kind) => {
    const version: V3WakerDocumentVersion = {
      id: ids[kind],
      documentId: '44444444-4444-4444-8444-444444444444',
      wakerId: ids.waker,
      kind,
      number: 1,
      content: contents[kind],
      sha256: createHash('sha256').update(contents[kind]).digest('hex'),
      changeSummary: 'test',
      restoredFromVersionId: null,
      createdBy: null,
      createdAt: '2026-08-14T00:00:00.000Z',
      isCurrent: true,
    };
    return [kind, version];
  }),
) as Record<V3WakerDocumentKind, V3WakerDocumentVersion>;

function repository(overrides: Partial<V3WakerConfigurationRepository> = {}): V3WakerConfigurationRepository {
  return {
    getVersion: async () => configuration,
    getDocumentVersion: async (_context, _wakerId, kind) => documents[kind],
    ...overrides,
  } as V3WakerConfigurationRepository;
}

describe('V3 effective Waker configuration', () => {
  it('resolves exact immutable document IDs and builds the PI system context', async () => {
    const resolved = await resolveV3EffectiveConfiguration(repository(), context, ids.configuration);
    expect(resolved.documents.memory.content).toBe(contents.memory);
    const prompt = buildV3EffectiveSystemPrompt(resolved);
    expect(prompt).toContain(`Configuration version: ${ids.configuration} (number 7)`);
    expect(prompt).toContain(contents.identity);
    expect(prompt).toContain(contents.persona);
    expect(prompt).toContain(contents.bible);
    expect(prompt).toContain(contents.memory);
  });

  it('fails closed when the immutable snapshot or a document fails integrity validation', async () => {
    await expect(
      resolveV3EffectiveConfiguration(
        repository({ getVersion: async () => ({ ...configuration, snapshotSha256: '0'.repeat(64) }) }),
        context,
        ids.configuration,
      ),
    ).rejects.toThrow(/configuration integrity/iu);
    await expect(
      resolveV3EffectiveConfiguration(
        repository({
          getDocumentVersion: async (_context, _wakerId, kind) =>
            kind === 'memory' ? { ...documents.memory, sha256: '0'.repeat(64) } : documents[kind],
        }),
        context,
        ids.configuration,
      ),
    ).rejects.toThrow(/memory document integrity/iu);
  });
});
