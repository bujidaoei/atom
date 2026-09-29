import { describe, expect, it } from 'vitest';
import { Value } from 'typebox/value';

import {
  V3DesktopMachineRegistrationInputSchema,
  V3DesktopMachineSchema,
  V3NetworkDiagnosticsSchema,
  V3RemoteConversationLeaseSchema,
  V3RemoteConversationRunWorkSchema,
  V3RemoteMachineRegistrationResultSchema,
  V3RemoteWorkAckInputSchema,
  V3RemoteWorkPollResponseSchema,
} from '../src/v3.ts';

const machineId = '11111111-1111-4111-8111-111111111111';
const checkedAt = '2026-08-24T06:20:14.000Z';

describe('Desktop machine bridge contracts', () => {
  it('accepts the observed machine bridge registration and rejects unknown or invalid native identity', () => {
    const valid = {
      machine_name: 'DESKTOP-REFERENCE',
      machine_id: machineId,
      client_version: '0.1.0-beta.14',
      platform: 'win32',
      architecture: 'x64',
    };
    expect(Value.Check(V3DesktopMachineRegistrationInputSchema, valid)).toBe(true);
    expect(Value.Check(V3DesktopMachineRegistrationInputSchema, { ...valid, extra: true })).toBe(false);
    expect(Value.Check(V3DesktopMachineRegistrationInputSchema, { ...valid, platform: 'browser' })).toBe(
      false,
    );
    expect(Value.Check(V3DesktopMachineRegistrationInputSchema, { ...valid, machine_name: '' })).toBe(false);
    expect(Value.Check(V3DesktopMachineRegistrationInputSchema, { ...valid, machine_id: '../invalid' })).toBe(
      false,
    );
    expect(
      Value.Check(V3RemoteMachineRegistrationResultSchema, {
        machine_secret: 's'.repeat(43),
      }),
    ).toBe(true);
  });

  it('accepts only the observed conversation_run lease, empty poll, and exact ACK body', () => {
    const work = {
      id: '44444444-4444-4444-8444-444444444444',
      type: 'conversation_run',
      state: 'claimed',
      secret: 's'.repeat(43),
      token: 't'.repeat(43),
      created_at: checkedAt,
      data: {
        type: 'conversation_run',
        run_id: '55555555-5555-4555-8555-555555555555',
        epoch: 1,
        lease_token: 'l'.repeat(43),
        run_credential: 'r'.repeat(43),
        conversation_id: '66666666-6666-4666-8666-666666666666',
        participant_id: '77777777-7777-4777-8777-777777777777',
        waker_ref: { kind: 'v3/waker', id: '88888888-8888-4888-8888-888888888888' },
        waker_snapshot: {
          name: 'Remote Waker',
          role_name: 'Assistant',
          bio: 'Test responsibilities',
          system_prompt: 'Bound immutable system prompt',
        },
        employee_id: '88888888-8888-4888-8888-888888888888',
        config_revision: 'a'.repeat(64),
        trigger_message_ids: ['99999999-9999-4999-8999-999999999999'],
        resolved_model: 'gateway-model',
      },
    };
    expect(Value.Check(V3RemoteConversationRunWorkSchema, work)).toBe(true);
    const missingSecret: Partial<typeof work> = { ...work };
    delete missingSecret.secret;
    expect(Value.Check(V3RemoteConversationRunWorkSchema, missingSecret)).toBe(false);
    expect(Value.Check(V3RemoteWorkPollResponseSchema, work)).toBe(true);
    expect(Value.Check(V3RemoteWorkPollResponseSchema, {})).toBe(true);
    expect(Value.Check(V3RemoteWorkPollResponseSchema, { data: {} })).toBe(false);
    expect(
      Value.Check(V3RemoteConversationRunWorkSchema, {
        ...work,
        data: { ...work.data, trigger_message_ids: [] },
      }),
    ).toBe(false);
    expect(Value.Check(V3RemoteWorkAckInputSchema, { work_id: work.id })).toBe(true);
    expect(Value.Check(V3RemoteWorkAckInputSchema, { work_id: work.id, epoch: 1 })).toBe(false);
    expect(
      Value.Check(V3RemoteConversationLeaseSchema, {
        epoch: 1,
        lease_token: work.data.lease_token,
        run_credential: work.data.run_credential,
        runner_instance_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
      }),
    ).toBe(true);
  });

  it('projects a redacted machine and exactly three ordered diagnostic stages', () => {
    const machine = {
      id: machineId,
      deviceName: 'DESKTOP-REFERENCE',
      clientVersion: '0.1.0-beta.14',
      platform: 'win32',
      architecture: 'x64',
      registeredAt: checkedAt,
      lastSeenAt: checkedAt,
      lastPollAt: checkedAt,
      pollCount: 3,
      version: 4,
    };
    expect(Value.Check(V3DesktopMachineSchema, machine)).toBe(true);
    const diagnostics = {
      machineId,
      machine,
      checkedAt,
      checks: [
        {
          id: 'gateway',
          status: 'reachable',
          durationMs: 19,
          details: ['Endpoint: authenticated /v1/models', 'Status: 200 OK'],
        },
        {
          id: 'registration',
          status: 'reachable',
          durationMs: 0,
          details: ['Machine registered: yes'],
        },
        {
          id: 'work-return',
          status: 'reachable',
          durationMs: 0,
          details: ['Poll count: 3', 'Safety: diagnostic does not poll or consume Work'],
        },
      ],
    };
    expect(Value.Check(V3NetworkDiagnosticsSchema, diagnostics)).toBe(true);
    expect(
      Value.Check(V3NetworkDiagnosticsSchema, {
        ...diagnostics,
        checks: diagnostics.checks.slice().reverse(),
      }),
    ).toBe(false);
    expect(JSON.stringify(diagnostics)).not.toMatch(/authorization|token|secret|prompt/iu);
  });
});
