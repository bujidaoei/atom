import { Type, type Static } from 'typebox';
import { Value } from 'typebox/value';

const Template = Type.Object(
  {
    skillId: Type.String({ pattern: '^[a-z0-9]+(?:-[a-z0-9]+)*$', maxLength: 160 }),
    version: Type.String({
      pattern:
        '^(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)(?:-[0-9A-Za-z-]+(?:\\.[0-9A-Za-z-]+)*)?(?:\\+[0-9A-Za-z-]+(?:\\.[0-9A-Za-z-]+)*)?$',
    }),
    displayName: Type.String(),
    template: Type.Object(
      {
        format: Type.Literal('qoder-sop-template/v1'),
        description: Type.String(),
        body: Type.String(),
      },
      { additionalProperties: false },
    ),
  },
  { additionalProperties: false },
);
export const V3SopTemplateSchema = Template;
export const V3SopReleaseSchema = Type.Object(
  {
    ...Template.properties,
    profileId: Type.String({ minLength: 1 }),
    releaseId: Type.String({ minLength: 1 }),
    digest: Type.String({ pattern: '^[a-f0-9]{64}$' }),
    metadata: Type.Object(
      {
        skill_kind: Type.Literal('sop'),
        skill_id: Type.String(),
        display_name: Type.String(),
        description: Type.String(),
      },
      { additionalProperties: false },
    ),
    createdAt: Type.String(),
  },
  { additionalProperties: false },
);
export const V3SopReleasesSchema = Type.Array(V3SopReleaseSchema);

export type V3SopTemplate = Static<typeof Template>;

export function parseV3SopTemplate(value: unknown): V3SopTemplate {
  if (!Value.Check(Template, value))
    throw new Error(
      'Invalid or unsupported SOP template. Expected the parameter-free qoder-sop-template/v1 format.',
    );
  const prerelease = value.version.split('+')[0]!.split('-').slice(1).join('-');
  if (prerelease.split('.').some((part) => /^0[0-9]+$/u.test(part)))
    throw new Error('SOP version must be a semantic version.');
  return value;
}

export interface V3SopRelease {
  profileId: string;
  releaseId: string;
  skillId: string;
  version: string;
  digest: string;
  displayName: string;
  template: V3SopTemplate['template'];
  metadata: { skill_kind: 'sop'; skill_id: string; display_name: string; description: string };
  createdAt: string;
}

export interface V3GroupSopSelection {
  profileId: string;
  version: string;
}

export interface V3GroupSopReplacement {
  expectedVersion: number;
  selections: V3GroupSopSelection[];
}

export interface V3GroupSopBindings {
  members?: V3GroupSopMember[];
  nodes?: V3GroupConversationNode[];
  group: {
    id: string;
    workspaceId: string;
    surfaceKind: 'group';
    title: string;
    defaultConversationId: string | null;
    revision: number;
    status: 'active';
    createdAt: string;
    updatedAt: string;
  };
  systemSkills: Array<{
    id: string;
    groupId: string;
    profileId: string;
    releaseId: string;
    skillId: string;
    profileName: string;
    profileMetadata: V3SopRelease['metadata'];
    version: string;
    digest: string;
    priority: number;
    bindingRevision: number;
    parameterValues: Record<string, never>;
  }>;
}

export interface V3GroupSopMember {
  id: string;
  wakerRef: { kind: 'core/human'; id: string } | { kind: 'qoder/waker'; id: string; revision: string };
  role: 'owner' | 'member';
  displayName: string;
  model?: string;
  leader?: true;
  avatar?: string;
  state: 'active';
}

export interface V3GroupConversationNode {
  id: string;
  groupId: string;
  conversationId: string;
  nodeType: 'group_conversation';
  title: string;
  sortOrder: number;
  status: 'active' | 'archived';
  locked: boolean;
  createdAt: string;
  updatedAt: string;
}

export function sopCatalogEntries(releases: readonly V3SopRelease[]) {
  const profiles = new Map<string, V3SopRelease[]>();
  for (const release of releases) {
    const existing = profiles.get(release.profileId) ?? [];
    existing.push(release);
    profiles.set(release.profileId, existing);
  }
  return [...profiles.values()].map((versions) => ({
    profileId: versions[0]!.profileId,
    name: versions[0]!.skillId,
    skillId: versions[0]!.skillId,
    metadata: versions[0]!.metadata,
    releases: versions.map((release) => ({
      id: release.releaseId,
      profileId: release.profileId,
      version: release.version,
      digest: release.digest,
      runtimeConstraints: {},
      template: release.template,
    })),
  }));
}
