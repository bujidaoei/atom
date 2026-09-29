import type { V3GroupInboxPage } from '../../product-contracts/src/v3-ports.ts';
import type { V3Event } from '../../product-contracts/src/v3.ts';

export function formatV3GroupInboxPage(page: V3GroupInboxPage, conversationId: string): string {
  if (page.exhausted) return '[Inbox] 当前没有新交付消息。';
  const render = (events: readonly V3Event[], budget: number) =>
    events.map((event, index) => {
      const content = typeof event.payload.content === 'string' ? event.payload.content : '';
      const max = Math.max(200, Math.floor(budget / Math.max(events.length, 1)));
      const sender = page.members.find(
        (member) =>
          member.id === event.payload.actorParticipantId ||
          member.subjectId === event.payload.actorId ||
          member.subjectId === event.payload.participantWakerId,
      );
      const attachments = Array.isArray(event.payload.materializedAttachments)
        ? event.payload.materializedAttachments
            .map((item) => {
              const file = item as { fileName: string; path: string };
              return `附件：${file.fileName} → ${file.path}`;
            })
            .join('\n')
        : '';
      const privateReaders = event.payload.privateParticipantIds;
      const privacy =
        Array.isArray(privateReaders) && privateReaders.length
          ? `\n私密读者（另含发送者）：${JSON.stringify(privateReaders)}`
          : '';
      return `${index + 1}. [seq${event.sequence}] [id=${event.id}] ${sender?.name ?? 'User'}${privacy}\n正文：${content.length > max ? `${content.slice(0, max)}\n[正文已截取；读取完整消息：qoderwake messages list ${conversationId} --after-seq ${event.sequence - 1} --limit 1 --json]` : content}${attachments ? `\n${attachments}` : ''}`;
    });
  return [
    '当前 Run 使用 passive 协议：host 管理消息交付和运行收尾。不要手动 claim/read、轮询或等待 Inbox。',
    '完成已交付请求的必要工作和可见回复后正常结束。新的请求会由 host 追加交付或启动后续 Run。',
    '必要交接使用 --mention 唤醒明确成员；已发送成功的回复不要重复发送。可用 messages list 定向读取历史。',
    `交付批次：${page.claimId}`,
    `当前Run：${page.runId}`,
    `当前身份：${page.participantId}`,
    `所属会话：${conversationId}`,
    '【给你的上下文】以下是参考，不是待办；不要单独回复。',
    ...render(page.context, 16 * 1024),
    `【已交付消息】本批 ${page.messages.length} 条`,
    ...render(page.messages, 47 * 1024),
    '【群成员】',
    ...page.members.map(({ id, name, kind, roleName }) => `- ${name} | ${kind} | ${roleName} | id=${id}`),
  ].join('\n\n');
}
