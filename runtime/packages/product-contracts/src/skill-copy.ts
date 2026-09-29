import { Type, type Static } from 'typebox';
import { V3SkillVersionSchema } from './v3.ts';

const id = V3SkillVersionSchema.properties.id;
export const V3CopySkillInputSchema = Type.Object(
  {
    sourceSkillId: id,
    sourceVersionId: id,
    expectedConfigurationVersionId: id,
  },
  { additionalProperties: false },
);
export type V3CopySkillInput = Static<typeof V3CopySkillInputSchema>;
