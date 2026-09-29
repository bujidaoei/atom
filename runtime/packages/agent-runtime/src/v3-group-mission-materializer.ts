import {
  forkV3GroupMissionSnapshot,
  V3GroupMissionAggregate,
  type V3GroupMissionSnapshot,
} from './v3-group-orchestrator.ts';
import type { V3GroupPromptMember } from './v3-group-prompts.ts';

export interface V3FrozenGroupMissionSeedMember {
  wakerId: string;
  name: string;
  roleName: string;
  bio: string;
  model: string | null;
  workspaceReferenceId: string | null;
  configurationVersionId: string | null;
}

export interface V3FrozenGroupMissionSeed {
  batchId: string;
  groupId: string;
  baseMissionId: string | null;
  membershipVersionId: string;
  leaderWakerId: string;
  conversationWorkspaceReferenceId: string | null;
  members: readonly V3FrozenGroupMissionSeedMember[];
}

export interface V3FrozenBaseGroupMission {
  id: string;
  conversationId: string;
  groupId: string;
  state: 'planning' | 'executing' | 'completed' | 'failed' | 'cancelled';
  snapshot: V3GroupMissionSnapshot;
}

export interface V3FrozenGroupMissionMaterialization {
  groupId: string;
  membershipVersionId: string;
  conversationWorkspaceReferenceId: string | null;
  prompt: string;
  mentionedWakerIds: string[];
  memberProfiles: V3GroupPromptMember[];
  snapshot: V3GroupMissionSnapshot;
}

function assertResolvedMember(frozen: V3FrozenGroupMissionSeedMember, resolved: V3GroupPromptMember): void {
  if (
    resolved.wakerId !== frozen.wakerId ||
    resolved.name !== frozen.name ||
    resolved.roleName !== frozen.roleName ||
    resolved.bio !== frozen.bio ||
    resolved.model !== frozen.model ||
    resolved.workspaceReferenceId !== frozen.workspaceReferenceId ||
    resolved.configurationVersionId !== frozen.configurationVersionId
  ) {
    throw new Error(`Frozen group member binding changed during materialization: ${frozen.wakerId}`);
  }
}

export async function materializeV3FrozenGroupMission(input: {
  runId: string;
  conversationId: string;
  prompt: string;
  seed: V3FrozenGroupMissionSeed;
  loadBaseMission(missionId: string): Promise<V3FrozenBaseGroupMission | undefined>;
  resolveMember(member: V3FrozenGroupMissionSeedMember): Promise<V3GroupPromptMember>;
}): Promise<V3FrozenGroupMissionMaterialization> {
  const prompt = input.prompt.trim();
  if (!prompt) throw new Error('Group message content or attachment is required');
  if (!input.seed.members.length) throw new Error('Frozen group mission seed has no members');
  const memberIds = input.seed.members.map(({ wakerId }) => wakerId);
  if (new Set(memberIds).size !== memberIds.length) {
    throw new Error('Frozen group mission seed has duplicate members');
  }
  if (!memberIds.includes(input.seed.leaderWakerId)) {
    throw new Error('Frozen group mission Leader is not a member');
  }
  for (const member of input.seed.members) {
    if (!member.model || !member.configurationVersionId) {
      throw new Error(`Frozen group member is missing execution configuration: ${member.wakerId}`);
    }
  }

  const baseMission = input.seed.baseMissionId
    ? await input.loadBaseMission(input.seed.baseMissionId)
    : undefined;
  if (input.seed.baseMissionId && !baseMission) {
    throw new Error(`Frozen base group mission not found: ${input.seed.baseMissionId}`);
  }
  if (
    baseMission &&
    (baseMission.id !== input.seed.baseMissionId ||
      baseMission.state !== 'completed' ||
      baseMission.groupId !== input.seed.groupId ||
      baseMission.conversationId !== input.conversationId)
  ) {
    throw new Error('Frozen base group mission does not match the accepted batch seed');
  }

  const memberProfiles = await Promise.all(
    input.seed.members.map(async (member) => {
      const resolved = await input.resolveMember(member);
      assertResolvedMember(member, resolved);
      return resolved;
    }),
  );
  const members = input.seed.members.map(({ wakerId, name, roleName }) => ({
    wakerId,
    name,
    roleName,
    available: true,
  }));
  const snapshot = baseMission
    ? forkV3GroupMissionSnapshot(
        baseMission.snapshot,
        input.runId,
        `${baseMission.snapshot.goal}\nFollow-up input: ${prompt}`,
      )
    : V3GroupMissionAggregate.create({
        missionId: input.runId,
        goal: prompt,
        leaderWakerId: input.seed.leaderWakerId,
        members,
      }).snapshot();
  snapshot.leaderWakerId = input.seed.leaderWakerId;
  snapshot.members = members;

  return {
    groupId: input.seed.groupId,
    membershipVersionId: input.seed.membershipVersionId,
    conversationWorkspaceReferenceId: input.seed.conversationWorkspaceReferenceId,
    prompt,
    mentionedWakerIds: memberProfiles
      .filter(({ name }) => prompt.includes(`@${name}`))
      .map(({ wakerId }) => wakerId),
    memberProfiles,
    snapshot,
  };
}
