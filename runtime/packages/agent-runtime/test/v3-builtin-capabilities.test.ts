import { describe, expect, it } from 'vitest';

import {
  defaultWakerBuiltinCapabilities,
  type V3WakerBuiltinCapabilities,
} from '../../product-contracts/src/v3.ts';
import {
  OFFICIAL_WAKER_BUILTIN_SKILL_IDS,
  filterToolsByWakerBuiltinCapabilities,
} from '../src/v3-builtin-capabilities.ts';
import { buildV3EffectiveSystemPrompt } from '../src/v3-effective-configuration.ts';
import { createHash } from 'node:crypto';
import { canonicalV3JsonbText } from '../../product-contracts/src/v3-canonical-json.ts';
import type { V3WakerConfigurationVersion, V3WakerDocumentVersion } from '../../product-contracts/src/v3.ts';

const snapshot = {
  profile: {
    name: 'Backend',
    roleName: 'Backend Engineer',
    bio: 'Builds durable services.',
    roleTemplateVersionId: null,
    avatarObjectId: null,
  },
  documents: {
    identity: '33333333-3333-4333-8333-333333333331',
    persona: '33333333-3333-4333-8333-333333333332',
    bible: '33333333-3333-4333-8333-333333333333',
    memory: '33333333-3333-4333-8333-333333333334',
    core_capabilities: '33333333-3333-4333-8333-333333333335',
    work_styles: '33333333-3333-4333-8333-333333333336',
    delivery_commitments: '33333333-3333-4333-8333-333333333337',
  },
  resources: {
    skillInstallationVersionIds: [],
    knowledgeBindingVersionIds: ['k1'],
    connectorToolSelectionVersionIds: [],
    imPairingVersionIds: [],
    permissionPolicyVersionIds: [],
  },
  modelPolicy: {},
};

const document = (content: string, kind: V3WakerDocumentVersion['kind']): V3WakerDocumentVersion => ({
  id: '33333333-3333-4333-8333-333333333331',
  documentId: '44444444-4444-4444-8444-444444444444',
  wakerId: '22222222-2222-4222-8222-222222222222',
  kind,
  number: 1,
  content,
  sha256: createHash('sha256').update(content).digest('hex'),
  changeSummary: 'test',
  restoredFromVersionId: null,
  createdBy: null,
  createdAt: '2026-08-14T00:00:00.000Z',
  isCurrent: true,
});

const resolved = {
  configuration: {
    id: '11111111-1111-4111-8111-111111111111',
    wakerId: '22222222-2222-4222-8222-222222222222',
    number: 7,
    effectiveSnapshot: snapshot,
    snapshotSha256: createHash('sha256').update(canonicalV3JsonbText(snapshot)).digest('hex'),
    createdBy: null,
    reason: 'test',
    createdAt: '2026-08-14T00:00:00.000Z',
  } satisfies V3WakerConfigurationVersion,
  documents: {
    identity: document('Build production APIs.', 'identity'),
    persona: document('Be precise.', 'persona'),
    bible: document('Test before reporting.', 'bible'),
    memory: document('The user prefers concise evidence.', 'memory'),
  },
};

describe('official Waker builtin capability gating', () => {
  it('maps official skill ids onto persist keys and omits disabled tools without deny copy', () => {
    expect(OFFICIAL_WAKER_BUILTIN_SKILL_IDS).toEqual({
      'waker-memory': 'memory',
      'waker-knowledge': 'knowledge',
      'waker-im-channel-send': 'imChannelSend',
      'waker-im-chat-history': 'groupChatContext',
    });
    const tools = [
      { name: 'mcp_a2222222_echo' },
      { name: 'waker-memory' },
      { name: 'mcp_a2222222_waker-knowledge' },
      { name: 'mcp_a2222222_waker-im-channel-send' },
      { name: 'waker-im-chat-history' },
      { name: 'waker-qa-record' },
    ];
    const disabled: V3WakerBuiltinCapabilities = {
      memory: false,
      knowledge: false,
      imChannelSend: false,
      groupChatContext: false,
    };
    expect(filterToolsByWakerBuiltinCapabilities(tools, disabled).map(({ name }) => name)).toEqual([
      'mcp_a2222222_echo',
      'waker-qa-record',
    ]);
    expect(
      filterToolsByWakerBuiltinCapabilities(tools, defaultWakerBuiltinCapabilities()).map(({ name }) => name),
    ).toEqual(tools.map(({ name }) => name));
  });

  it('omits memory and bound knowledge from the system prompt when those capabilities are off', () => {
    const prompt = buildV3EffectiveSystemPrompt(resolved, 'Bound notebook excerpt', {
      memory: false,
      knowledge: false,
      imChannelSend: true,
      groupChatContext: true,
    });
    expect(prompt).toContain('Build production APIs.');
    expect(prompt).not.toContain('The user prefers concise evidence.');
    expect(prompt).not.toContain('Bound notebook excerpt');
    expect(prompt).not.toMatch(/memory is disabled|capability denied|not allowed/iu);
  });
});
