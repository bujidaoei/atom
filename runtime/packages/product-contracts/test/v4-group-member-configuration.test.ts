import { describe, expect, it } from 'vitest';
import { Value } from 'typebox/value';

import {
  V3CreateGroupSchema,
  V3GroupMemberConfigurationSchema,
  V3GroupMembershipVersionSchema,
} from '../src/v3.ts';

const backendId = '11111111-1111-4111-8111-111111111111';
const frontendId = '22222222-2222-4222-8222-222222222222';

describe('V4 group member execution configuration contract', () => {
  it('requires a configured model and explicit workspace selection for every new member', () => {
    const input = {
      name: 'Delivery group',
      leaderWakerId: backendId,
      memberWakerIds: [backendId, frontendId],
      memberConfigurations: [
        { wakerId: backendId, model: 'gateway-model-backend', workspaceReferenceId: null },
        { wakerId: frontendId, model: 'gateway-model-frontend', workspaceReferenceId: null },
      ],
    };

    expect(Value.Check(V3CreateGroupSchema, input)).toBe(true);
    expect(Value.Check(V3CreateGroupSchema, { ...input, memberConfigurations: [] })).toBe(false);
    expect(
      Value.Check(V3CreateGroupSchema, {
        ...input,
        memberConfigurations: [
          { wakerId: backendId, model: '', workspaceReferenceId: null },
          input.memberConfigurations[1],
        ],
      }),
    ).toBe(false);
  });

  it('represents historical unconfigured members without inventing a model', () => {
    expect(
      Value.Check(V3GroupMemberConfigurationSchema, {
        wakerId: backendId,
        model: null,
        workspaceReferenceId: null,
        configurationState: 'requires_configuration',
      }),
    ).toBe(true);
  });

  it('persists member configuration inside the immutable membership version', () => {
    expect(
      Value.Check(V3GroupMembershipVersionSchema, {
        id: '33333333-3333-4333-8333-333333333333',
        groupId: '44444444-4444-4444-8444-444444444444',
        number: 2,
        leaderWakerId: backendId,
        memberWakerIds: [backendId],
        memberConfigurations: [
          {
            wakerId: backendId,
            model: 'gateway-model-backend',
            workspaceReferenceId: null,
            configurationState: 'ready',
          },
        ],
        reason: 'membership updated',
        createdBy: '55555555-5555-4555-8555-555555555555',
        createdAt: '2026-08-20T00:00:00.000Z',
      }),
    ).toBe(true);
  });
});
