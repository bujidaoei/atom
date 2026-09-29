import type { V3ConversationAttachment } from './v3.ts';

export async function compensateUploadedConversationAttachments(
  attachments: readonly V3ConversationAttachment[],
  removeAttachment: (attachmentId: string, idempotencyKey: string) => Promise<void>,
): Promise<V3ConversationAttachment[]> {
  const results = await Promise.allSettled(
    attachments.map((attachment) => removeAttachment(attachment.id, crypto.randomUUID())),
  );
  return attachments.filter((_, index) => results[index]?.status === 'rejected');
}
