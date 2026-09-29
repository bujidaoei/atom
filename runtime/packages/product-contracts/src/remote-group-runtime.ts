import { Type } from 'typebox';
import { V3EventSchema, V3RemoteAttachmentSchema } from './v3.ts';

const id = Type.String({ minLength: 1, maxLength: 256 });
const count = Type.Integer({ minimum: 0 });
export const RemoteGroupInboxPageSchema = Type.Object(
  {
    claimId: id,
    participantId: id,
    runId: id,
    context: Type.Array(V3EventSchema),
    messages: Type.Array(V3EventSchema),
    candidateCount: count,
    claimedCount: count,
    pendingCount: count,
    nextCursor: Type.Union([Type.String(), Type.Null()]),
    exhausted: Type.Boolean(),
    members: Type.Array(
      Type.Object(
        {
          id,
          kind: Type.Union([Type.Literal('waker'), Type.Literal('human')]),
          subjectId: id,
          name: Type.String(),
          roleName: Type.String(),
        },
        { additionalProperties: false },
      ),
    ),
  },
  { additionalProperties: false },
);

export const RemoteGroupDeliverySchema = Type.Object(
  { inbox: RemoteGroupInboxPageSchema },
  { additionalProperties: false },
);

const todo = Type.Object(
  {
    todo_id: id,
    content: Type.String(),
    status: Type.Union(
      ['pending', 'in_progress', 'completed', 'cancelled'].map((value) => Type.Literal(value)),
    ),
    created_at: Type.String(),
    updated_at: Type.String(),
  },
  { additionalProperties: false },
);
const goal = Type.Object(
  {
    goal: Type.Object(
      {
        id,
        status: Type.Union(['active', 'paused', 'completed'].map((value) => Type.Literal(value))),
        content: Type.String(),
        generation: count,
        revision: count,
        turnLimit: Type.Integer({ minimum: 1, maximum: 96 }),
        createdAt: Type.String(),
        updatedAt: Type.String(),
        createdBy: id,
        updatedBy: id,
        requestedBy: id,
        sourceMessageId: id,
        lastHumanMessageId: id,
        lastHumanMessageSequence: count,
        resultMessageId: Type.Union([id, Type.Null()]),
        pauseReason: Type.Union([
          Type.Null(),
          ...[
            'user_stop',
            'awaiting_user',
            'turn_limit',
            'no_progress',
            'execution_error',
            'leader_unavailable',
          ].map((value) => Type.Literal(value)),
        ]),
      },
      { additionalProperties: false },
    ),
    runtime: Type.Object(
      { turnCount: count, lastBusinessMessageSequence: count },
      { additionalProperties: false },
    ),
  },
  { additionalProperties: false },
);
export const RemoteGroupStateSchema = Type.Object(
  { todos: Type.Array(todo), goal: Type.Union([goal, Type.Null()]) },
  { additionalProperties: false },
);
export const RemoteGroupInitialSchema = Type.Object(
  {
    inbox: RemoteGroupInboxPageSchema,
    prompt: Type.String({ maxLength: 500_000 }),
    participantContext: Type.Object(
      {
        conversation: Type.Object({ id, title: Type.String() }, { additionalProperties: false }),
        group: Type.Object({ id, name: Type.String(), leaderWakerId: id }, { additionalProperties: false }),
        participantWakerId: id,
        ...RemoteGroupStateSchema.properties,
      },
      { additionalProperties: false },
    ),
  },
  { additionalProperties: false },
);
export const RemoteGroupAttachmentsSchema = Type.Object(
  {
    message: V3EventSchema,
    attachments: Type.Array(V3RemoteAttachmentSchema, { minItems: 1, maxItems: 20 }),
  },
  { additionalProperties: false },
);
export const RemoteGroupCommandResultSchema = Type.Object(
  {
    toolCallId: id,
    exitCode: Type.Integer(),
    stdout: Type.String(),
    stderr: Type.String(),
    timedOut: Type.Boolean(),
    truncated: Type.Boolean(),
  },
  { additionalProperties: false },
);
