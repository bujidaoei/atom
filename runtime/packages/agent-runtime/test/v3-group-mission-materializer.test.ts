import { describe, expect, it, vi } from 'vitest';

import { V3GroupMissionAggregate } from '../src/v3-group-orchestrator.ts';
import { materializeV3FrozenGroupMission } from '../src/v3-group-mission-materializer.ts';

const seed = {
  batchId: 'batch-waiting',
  groupId: 'group-1',
  baseMissionId: 'mission-completed',
  membershipVersionId: 'membership-frozen',
  leaderWakerId: 'leader-1',
  conversationWorkspaceReferenceId: 'workspace-frozen',
  members: [
    {
      wakerId: 'leader-1',
      name: 'Leader',
      roleName: 'Coordinator',
      bio: 'Frozen profile',
      model: 'gateway/frozen',
      workspaceReferenceId: 'member-workspace-frozen',
      configurationVersionId: 'configuration-frozen',
    },
  ],
} as const;

describe('V3 frozen group mission materialization', () => {
  it('uses only the seed baseline and frozen member bindings for each Run in one batch', async () => {
    const baseline = {
      id: 'mission-completed',
      conversationId: 'conversation-1',
      groupId: 'group-1',
      state: 'completed' as const,
      snapshot: V3GroupMissionAggregate.create({
        missionId: 'mission-completed',
        goal: 'Completed baseline',
        leaderWakerId: 'leader-1',
        members: [{ wakerId: 'leader-1', name: 'Old name', roleName: 'Old role', available: true }],
      }).snapshot(),
    };
    const loadBaseMission = vi.fn().mockResolvedValue(baseline);
    const resolveMember = vi.fn(async (member: (typeof seed.members)[number]) => ({
      ...member,
      effectiveSystemPrompt: 'Frozen effective prompt',
    }));

    const first = await materializeV3FrozenGroupMission({
      runId: 'run-b',
      conversationId: 'conversation-1',
      prompt: 'waiting B',
      seed,
      loadBaseMission,
      resolveMember,
    });
    const second = await materializeV3FrozenGroupMission({
      runId: 'run-c',
      conversationId: 'conversation-1',
      prompt: 'waiting C',
      seed,
      loadBaseMission,
      resolveMember,
    });

    expect(loadBaseMission).toHaveBeenNthCalledWith(1, 'mission-completed');
    expect(loadBaseMission).toHaveBeenNthCalledWith(2, 'mission-completed');
    expect(resolveMember).toHaveBeenCalledTimes(2);
    expect(first.membershipVersionId).toBe('membership-frozen');
    expect(first.memberProfiles[0]).toMatchObject({
      configurationVersionId: 'configuration-frozen',
      model: 'gateway/frozen',
      workspaceReferenceId: 'member-workspace-frozen',
    });
    expect(first.snapshot).toMatchObject({
      missionId: 'run-b',
      leaderWakerId: 'leader-1',
      members: [{ wakerId: 'leader-1', name: 'Leader', roleName: 'Coordinator', available: true }],
    });
    expect(second.snapshot.missionId).toBe('run-c');
    expect(baseline.snapshot.missionId).toBe('mission-completed');
  });

  it('fails closed when the frozen baseline cannot be reconstructed', async () => {
    await expect(
      materializeV3FrozenGroupMission({
        runId: 'run-b',
        conversationId: 'conversation-1',
        prompt: 'waiting B',
        seed,
        loadBaseMission: vi.fn().mockResolvedValue(undefined),
        resolveMember: vi.fn(),
      }),
    ).rejects.toThrow('Frozen base group mission not found');
  });
});
