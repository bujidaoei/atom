import { Type, type Static } from 'typebox';

import { V3WorkspaceReferenceSchema } from './v3.ts';

const Uuid = Type.String({ format: 'uuid' });
const Path = Type.String({ minLength: 1, maxLength: 4_096 });
const LeaseToken = Type.String({ minLength: 43, maxLength: 128, pattern: '^[A-Za-z0-9_-]+$' });

export const V3RemoteWorkspaceRequestInputSchema = Type.Union([
  Type.Object(
    { operation: Type.Literal('list_directory'), path: Type.Optional(Path) },
    { additionalProperties: false },
  ),
  Type.Object({ operation: Type.Literal('register_directory'), path: Path }, { additionalProperties: false }),
]);
export type V3RemoteWorkspaceRequestInput = Static<typeof V3RemoteWorkspaceRequestInputSchema>;

export const V3RemoteWorkspaceCommandSchema = Type.Object(
  {
    id: Uuid,
    operation: Type.Union([Type.Literal('list_directory'), Type.Literal('register_directory')]),
    path: Type.Union([Path, Type.Null()]),
    lease_token: LeaseToken,
  },
  { additionalProperties: false },
);
export type V3RemoteWorkspaceCommand = Static<typeof V3RemoteWorkspaceCommandSchema>;

export const V3RemoteDirectoryListingSchema = Type.Object(
  {
    path: Path,
    parent: Type.Union([Path, Type.Null()]),
    home: Path,
    drives: Type.Array(Type.String({ minLength: 1, maxLength: 8 }), { maxItems: 32 }),
    entries: Type.Array(
      Type.Object(
        {
          name: Type.String({ minLength: 1, maxLength: 255 }),
          kind: Type.Union([Type.Literal('directory'), Type.Literal('file')]),
        },
        { additionalProperties: false },
      ),
      { maxItems: 10_000 },
    ),
  },
  { additionalProperties: false },
);
export type V3RemoteDirectoryListing = Static<typeof V3RemoteDirectoryListingSchema>;

export const V3RemoteWorkspaceResultInputSchema = Type.Union([
  Type.Object(
    {
      request_id: Uuid,
      lease_token: LeaseToken,
      status: Type.Literal('completed'),
      listing: V3RemoteDirectoryListingSchema,
    },
    { additionalProperties: false },
  ),
  Type.Object(
    {
      request_id: Uuid,
      lease_token: LeaseToken,
      status: Type.Literal('completed'),
      reference: V3WorkspaceReferenceSchema,
    },
    { additionalProperties: false },
  ),
  Type.Object(
    {
      request_id: Uuid,
      lease_token: LeaseToken,
      status: Type.Literal('failed'),
      error_code: Type.Optional(Type.String({ minLength: 2, maxLength: 32, pattern: '^[A-Z][A-Z0-9_]+$' })),
    },
    { additionalProperties: false },
  ),
]);
export type V3RemoteWorkspaceResultInput = Static<typeof V3RemoteWorkspaceResultInputSchema>;

export const V3RemoteWorkspaceStatusSchema = Type.Union([
  Type.Object({ id: Uuid, status: Type.Literal('pending') }, { additionalProperties: false }),
  Type.Object(
    { id: Uuid, status: Type.Literal('completed'), listing: V3RemoteDirectoryListingSchema },
    { additionalProperties: false },
  ),
  Type.Object(
    { id: Uuid, status: Type.Literal('completed'), reference: V3WorkspaceReferenceSchema },
    { additionalProperties: false },
  ),
  Type.Object(
    { id: Uuid, status: Type.Literal('failed'), error_code: Type.Optional(Type.String()) },
    { additionalProperties: false },
  ),
  Type.Object({ id: Uuid, status: Type.Literal('expired') }, { additionalProperties: false }),
]);
export type V3RemoteWorkspaceStatus = Static<typeof V3RemoteWorkspaceStatusSchema>;
