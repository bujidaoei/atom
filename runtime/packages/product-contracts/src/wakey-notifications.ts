import { Type, type Static } from 'typebox';

export const WakeyNotificationSchema = Type.Object(
  {
    id: Type.String({ format: 'uuid' }),
    sequence: Type.Integer({ minimum: 1 }),
    kind: Type.Union([
      Type.Literal('info'),
      Type.Literal('success'),
      Type.Literal('warning'),
      Type.Literal('error'),
    ]),
    title: Type.String({ minLength: 1, maxLength: 200 }),
    body: Type.String({ maxLength: 4000 }),
    producer: Type.String({ minLength: 1, maxLength: 120 }),
    receivedAt: Type.String({ format: 'date-time' }),
    readAt: Type.Union([Type.String({ format: 'date-time' }), Type.Null()]),
    target: Type.Union([Type.String({ pattern: '^/(?!/)', maxLength: 2000 }), Type.Null()]),
  },
  { additionalProperties: false },
);
export type WakeyNotification = Static<typeof WakeyNotificationSchema>;
export const WakeyNotificationPageSchema = Type.Object(
  {
    items: Type.Array(WakeyNotificationSchema),
    unreadCount: Type.Integer({ minimum: 0 }),
    latestSequence: Type.Integer({ minimum: 0 }),
    nextBefore: Type.Union([Type.Integer({ minimum: 1 }), Type.Null()]),
  },
  { additionalProperties: false },
);
export type WakeyNotificationPage = Static<typeof WakeyNotificationPageSchema>;
export const ReadWakeyNotificationsSchema = Type.Union([
  Type.Object(
    { ids: Type.Array(Type.String({ format: 'uuid' }), { minItems: 1, maxItems: 100, uniqueItems: true }) },
    { additionalProperties: false },
  ),
  Type.Object({ throughSequence: Type.Integer({ minimum: 0 }) }, { additionalProperties: false }),
]);
export type ReadWakeyNotifications = Static<typeof ReadWakeyNotificationsSchema>;
