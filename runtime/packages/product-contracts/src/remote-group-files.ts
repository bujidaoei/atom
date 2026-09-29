import { Type, type Static } from 'typebox';
import { Value } from 'typebox/value';
import { V3EventSchema } from './v3.ts';

export const REMOTE_GROUP_FILE_MAX_BYTES = 50 * 1024 * 1024;
const MAX_METADATA_BYTES = 512 * 1024;
export const REMOTE_GROUP_FILE_BODY_LIMIT = REMOTE_GROUP_FILE_MAX_BYTES + MAX_METADATA_BYTES + 4;
export const RemoteGroupFileMetadataSchema = Type.Object(
  {
    toolCallId: Type.String({ minLength: 1, maxLength: 256 }),
    fileName: Type.String({ minLength: 1, maxLength: 255 }),
    mediaType: Type.String({ minLength: 1, maxLength: 200 }),
    sizeBytes: Type.Integer({ minimum: 1, maximum: REMOTE_GROUP_FILE_MAX_BYTES }),
    sha256: Type.String({ pattern: '^[a-f0-9]{64}$' }),
    delivery: Type.Object(
      {
        text: Type.String({ maxLength: 100_000 }),
        mentionTarget: Type.Union([Type.Null(), Type.String({ minLength: 1, maxLength: 256 })]),
        privateTargets: Type.Optional(
          Type.Array(Type.String({ minLength: 1, maxLength: 256 }), { maxItems: 100, uniqueItems: true }),
        ),
      },
      { additionalProperties: false },
    ),
  },
  { additionalProperties: false },
);
export type RemoteGroupFileMetadata = Static<typeof RemoteGroupFileMetadataSchema>;
export const RemoteGroupFileReceiptSchema = Type.Object(
  { message: V3EventSchema, replayed: Type.Boolean() },
  { additionalProperties: false },
);

/** Length-prefixed JSON keeps message text out of HTTP headers and transfers file bytes without base64 expansion. */
export function encodeRemoteGroupFileUpload(
  metadata: RemoteGroupFileMetadata,
  bytes: Uint8Array,
): Uint8Array {
  if (!Value.Check(RemoteGroupFileMetadataSchema, metadata) || metadata.sizeBytes !== bytes.byteLength)
    throw new Error('Invalid group file upload');
  const json = new TextEncoder().encode(JSON.stringify(metadata));
  if (json.byteLength > MAX_METADATA_BYTES) throw new Error('Group file metadata exceeds the limit');
  const body = new Uint8Array(4 + json.byteLength + bytes.byteLength);
  new DataView(body.buffer).setUint32(0, json.byteLength, false);
  body.set(json, 4);
  body.set(bytes, 4 + json.byteLength);
  return body;
}

export function decodeRemoteGroupFileUpload(body: Uint8Array): {
  metadata: RemoteGroupFileMetadata;
  bytes: Uint8Array;
} {
  if (body.byteLength < 5 || body.byteLength > REMOTE_GROUP_FILE_BODY_LIMIT)
    throw new Error('Invalid group file upload size');
  const size = new DataView(body.buffer, body.byteOffset, body.byteLength).getUint32(0, false);
  if (!size || size > MAX_METADATA_BYTES || size + 4 >= body.byteLength)
    throw new Error('Invalid group file metadata length');
  const metadata: unknown = JSON.parse(
    new TextDecoder('utf-8', { fatal: true }).decode(body.subarray(4, 4 + size)),
  );
  const bytes = body.subarray(4 + size);
  if (!Value.Check(RemoteGroupFileMetadataSchema, metadata) || metadata.sizeBytes !== bytes.byteLength)
    throw new Error('Invalid group file upload');
  return { metadata, bytes };
}
