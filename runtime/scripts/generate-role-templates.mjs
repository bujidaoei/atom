// Regenerates packages/data-access/src/v3/official-role-templates.ts from the
// retained official employee-template catalog. Run after refreshing
// packages/data-access/src/v3/official-employee-templates.json.
import { readFileSync, writeFileSync } from 'node:fs';

const catalogPath = 'packages/data-access/src/v3/official-employee-templates.json';
const outputPath = 'packages/data-access/src/v3/official-role-templates.ts';

const IDENTITIES = new Map([
  [
    'common-software-developer',
    ['33000000-0000-4000-8000-000000000001', '33000000-0000-4000-8000-000000000011'],
  ],
  [
    'common-product-manager',
    ['33000000-0000-4000-8000-000000000002', '33000000-0000-4000-8000-000000000012'],
  ],
  [
    'common-frontend-developer',
    ['33000000-0000-4000-8000-000000000003', '33000000-0000-4000-8000-000000000013'],
  ],
  ['project-administrator', ['33000000-0000-4000-8000-000000000004', '33000000-0000-4000-8000-000000000014']],
  ['ux-ui-designer', ['33000000-0000-4000-8000-000000000005', '33000000-0000-4000-8000-000000000015']],
  ['common-qa-engineer', ['33000000-0000-4000-8000-000000000006', '33000000-0000-4000-8000-000000000016']],
  ['devops-engineer', ['33000000-0000-4000-8000-000000000007', '33000000-0000-4000-8000-000000000017']],
  ['operations-engineer', ['33000000-0000-4000-8000-000000000011', '33000000-0000-4000-8000-000000000021']],
  ['common-data-analyst', ['33000000-0000-4000-8000-000000000008', '33000000-0000-4000-8000-000000000018']],
  [
    'common-content-operator',
    ['33000000-0000-4000-8000-000000000009', '33000000-0000-4000-8000-000000000019'],
  ],
  ['group_qa_assistant', ['33000000-0000-4000-8000-000000000010', '33000000-0000-4000-8000-000000000020']],
]);

const catalog = JSON.parse(readFileSync(catalogPath, 'utf8')).data;
const literal = (value) => JSON.stringify(value);

const seeds = Object.entries(catalog)
  .sort(([, left], [, right]) => (left.sortOrder ?? 999) - (right.sortOrder ?? 999))
  .map(([roleType, role]) => {
    const ids = IDENTITIES.get(roleType);
    if (!ids) throw new Error(`no identity mapping for ${roleType}`);
    const name = JSON.parse(role.name);
    const description = JSON.parse(role.description);
    return `  {
    id: ${literal(ids[0])},
    versionId: ${literal(ids[1])},
    roleType: ${literal(roleType)},
    sortOrder: ${role.sortOrder ?? 999},
    name: ${literal(name.ZH)},
    nameEn: ${literal(name.EN)},
    summary: ${literal(description.ZH)},
    summaryEn: ${literal(description.EN)},
    avatarUrl: ${literal(role.avatar)},
    employeeVersion: ${literal(role.employee_version)},
    identity: ${literal(role.wakerContext.identity)},
    persona: ${literal(role.wakerContext.persona)},
    bible: ${literal(role.wakerContext.bible)},
    coreCapabilities: ${literal(JSON.stringify(role.coreCapabilities.ZH, null, 2))},
    workStyles: ${literal(JSON.stringify(role.workStyles.ZH, null, 2))},
    deliveryCommitments: ${literal(JSON.stringify(role.deliveryCommitments.ZH, null, 2))},
    coreCapabilitiesEn: ${literal(JSON.stringify(role.coreCapabilities.EN, null, 2))},
    workStylesEn: ${literal(JSON.stringify(role.workStyles.EN, null, 2))},
    deliveryCommitmentsEn: ${literal(JSON.stringify(role.deliveryCommitments.EN, null, 2))},
    defaultQuestions: ${literal(role.defaultQuestion.ZH ?? [])},
    defaultQuestionsEn: ${literal(role.defaultQuestion.EN ?? [])},
  }`;
  });

const banner = `// GENERATED FILE - do not edit by hand.
// Source: packages/data-access/src/v3/official-employee-templates.json
// (the official /api/employee-templates catalog refreshed on 2026-08-23).
// Regenerate with: node scripts/generate-role-templates.mjs

export interface OfficialRoleTemplateSeed {
  readonly id: string;
  readonly versionId: string;
  readonly roleType: string;
  readonly sortOrder: number;
  readonly name: string;
  readonly nameEn: string;
  readonly summary: string;
  readonly summaryEn: string;
  readonly avatarUrl: string;
  readonly employeeVersion: string;
  /** Official English role documents rendered on the Waker settings surface. */
  readonly identity: string;
  readonly persona: string;
  readonly bible: string;
  /** Official Chinese context documents (JSON payloads) behind the home About grid. */
  readonly coreCapabilities: string;
  readonly workStyles: string;
  readonly deliveryCommitments: string;
  readonly coreCapabilitiesEn: string;
  readonly workStylesEn: string;
  readonly deliveryCommitmentsEn: string;
  readonly defaultQuestions: readonly string[];
  readonly defaultQuestionsEn: readonly string[];
}

export const OFFICIAL_QODERWAKE_ROLE_TEMPLATES: readonly OfficialRoleTemplateSeed[] = [
`;

writeFileSync(outputPath, `${banner}${seeds.join(',\n')},\n] as const;\n`);
console.log(`wrote ${outputPath} with ${seeds.length} roles`);

// Emit the Cloud migration that carries the same six-document catalog.
const sqlPath = 'services/migrations/sql/041_v4_six_document_waker_model.sql';
const dollar = (value) => {
  if (value.includes('$qwdoc$')) throw new Error('content collides with dollar-quote tag');
  return `$qwdoc$${value}$qwdoc$`;
};
const baselineCatalogEntries = Object.entries(catalog).filter(
  ([roleType]) => roleType !== 'operations-engineer',
);
const templateUpdates = baselineCatalogEntries
  .map(([roleType, role]) => {
    const ids = IDENTITIES.get(roleType);
    const name = JSON.parse(role.name);
    const description = JSON.parse(role.description);
    return `UPDATE role_templates SET
  name = ${dollar(name.ZH)},
  summary = ${dollar(description.ZH)},
  updated_at = now()
WHERE id = '${ids[0]}'::uuid;

UPDATE role_template_versions SET
  identity_content = ${dollar(role.wakerContext.identity)},
  persona_content = ${dollar(role.wakerContext.persona)},
  bible_content = ${dollar(role.wakerContext.bible)},
  core_capabilities_content = ${dollar(JSON.stringify(role.coreCapabilities.ZH, null, 2))},
  work_styles_content = ${dollar(JSON.stringify(role.workStyles.ZH, null, 2))},
  delivery_commitments_content = ${dollar(JSON.stringify(role.deliveryCommitments.ZH, null, 2))},
  capability_metadata = ${dollar(
    JSON.stringify({
      defaultQuestions: { EN: role.defaultQuestion.EN ?? [], ZH: role.defaultQuestion.ZH ?? [] },
    }),
  )}::jsonb
WHERE id = '${ids[1]}'::uuid;`;
  })
  .join('\n\n');

const sql = `-- GENERATED FILE - do not edit by hand.
-- V4: the official six-document Waker model. Regenerate with:
--   node scripts/generate-role-templates.mjs

ALTER TABLE role_template_versions ADD COLUMN IF NOT EXISTS core_capabilities_content text NOT NULL DEFAULT '';
ALTER TABLE role_template_versions ADD COLUMN IF NOT EXISTS work_styles_content text NOT NULL DEFAULT '';
ALTER TABLE role_template_versions ADD COLUMN IF NOT EXISTS delivery_commitments_content text NOT NULL DEFAULT '';

ALTER TABLE waker_documents DROP CONSTRAINT IF EXISTS waker_documents_kind_check;
ALTER TABLE waker_documents ADD CONSTRAINT waker_documents_kind_check
  CHECK (kind IN ('identity', 'persona', 'bible', 'memory', 'profile',
                  'core_capabilities', 'work_styles', 'delivery_commitments'));

${templateUpdates}

-- Backfill the context documents for Wakers provisioned before this model.
INSERT INTO waker_documents (workspace_id, waker_id, kind)
SELECT w.workspace_id, w.id, kinds.kind
FROM wakers w
CROSS JOIN (VALUES ('core_capabilities'), ('work_styles'), ('delivery_commitments')) AS kinds(kind)
ON CONFLICT (waker_id, kind) DO NOTHING;

INSERT INTO waker_document_versions
  (document_id, number, content, sha256, created_by, change_summary)
SELECT d.id, 1,
  CASE d.kind
    WHEN 'core_capabilities' THEN COALESCE(rtv.core_capabilities_content, '')
    WHEN 'work_styles' THEN COALESCE(rtv.work_styles_content, '')
    ELSE COALESCE(rtv.delivery_commitments_content, '')
  END,
  encode(sha256(convert_to(
    CASE d.kind
      WHEN 'core_capabilities' THEN COALESCE(rtv.core_capabilities_content, '')
      WHEN 'work_styles' THEN COALESCE(rtv.work_styles_content, '')
      ELSE COALESCE(rtv.delivery_commitments_content, '')
    END, 'UTF8')), 'hex'),
  NULL, 'Initialized from effective Waker role'
FROM waker_documents d
JOIN wakers w ON w.id = d.waker_id
LEFT JOIN role_template_versions rtv ON rtv.id = w.role_template_version_id
WHERE d.kind IN ('core_capabilities', 'work_styles', 'delivery_commitments')
  AND d.current_version_id IS NULL;

UPDATE waker_documents d SET current_version_id = v.id, updated_at = now()
FROM waker_document_versions v
WHERE v.document_id = d.id AND v.number = 1 AND d.current_version_id IS NULL
  AND d.kind IN ('core_capabilities', 'work_styles', 'delivery_commitments');
`;
writeFileSync(sqlPath, sql);
console.log(`wrote ${sqlPath}`);

const operationsRole = catalog['operations-engineer'];
const operationsIds = IDENTITIES.get('operations-engineer');
if (!operationsRole || !operationsIds) throw new Error('operations-engineer template is required');
const operationsName = JSON.parse(operationsRole.name);
const operationsDescription = JSON.parse(operationsRole.description);
const operationsMigrationPath = 'services/migrations/sql/051_v4_operations_engineer_role.sql';
const operationsMigration = `-- GENERATED FILE - do not edit by hand.
-- V4: add the current official Operations Engineer role introduced after the
-- original ten-role catalog. Regenerate with:
--   node scripts/generate-role-templates.mjs

INSERT INTO role_templates (id,workspace_id,name,summary,source,status,current_version)
VALUES (
  '${operationsIds[0]}'::uuid,
  NULL,
  ${dollar(operationsName.ZH)},
  ${dollar(operationsDescription.ZH)},
  'builtin',
  'active',
  1
)
ON CONFLICT (id) DO UPDATE SET
  name=EXCLUDED.name,
  summary=EXCLUDED.summary,
  source='builtin',
  status='active',
  current_version=1,
  updated_at=now();

INSERT INTO role_template_versions
  (id,role_template_id,number,identity_content,persona_content,bible_content,
   core_capabilities_content,work_styles_content,delivery_commitments_content,
   capability_metadata)
VALUES (
  '${operationsIds[1]}'::uuid,
  '${operationsIds[0]}'::uuid,
  1,
  ${dollar(operationsRole.wakerContext.identity)},
  ${dollar(operationsRole.wakerContext.persona)},
  ${dollar(operationsRole.wakerContext.bible)},
  ${dollar(JSON.stringify(operationsRole.coreCapabilities.ZH, null, 2))},
  ${dollar(JSON.stringify(operationsRole.workStyles.ZH, null, 2))},
  ${dollar(JSON.stringify(operationsRole.deliveryCommitments.ZH, null, 2))},
  ${dollar(
    JSON.stringify({
      defaultQuestions: {
        EN: operationsRole.defaultQuestion.EN ?? [],
        ZH: operationsRole.defaultQuestion.ZH ?? [],
      },
    }),
  )}::jsonb
)
ON CONFLICT (id) DO UPDATE SET
  role_template_id=EXCLUDED.role_template_id,
  number=1,
  identity_content=EXCLUDED.identity_content,
  persona_content=EXCLUDED.persona_content,
  bible_content=EXCLUDED.bible_content,
  core_capabilities_content=EXCLUDED.core_capabilities_content,
  work_styles_content=EXCLUDED.work_styles_content,
  delivery_commitments_content=EXCLUDED.delivery_commitments_content,
  capability_metadata=EXCLUDED.capability_metadata;
`;
writeFileSync(operationsMigrationPath, operationsMigration);
console.log(`wrote ${operationsMigrationPath}`);
