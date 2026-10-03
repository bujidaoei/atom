/** Incremental parser for the server's bounded `event`/`data` SSE frames. */
export type SseFrame = { event: string; data: string };

export const MAX_SSE_PENDING = 8 * 1024 * 1024;

export function splitSseFrames(input: string): { frames: SseFrame[]; pending: string } {
  const normalized = input.replace(/\r\n/g, "\n");
  const frames: SseFrame[] = [];
  let cursor = 0;

  while (true) {
    const end = normalized.indexOf("\n\n", cursor);
    if (end === -1) break;
    const lines = normalized.slice(cursor, end).split("\n");
    cursor = end + 2;
    let event = "message";
    const data: string[] = [];
    for (const line of lines) {
      if (line.startsWith("event:")) event = line.slice(6).trimStart();
      else if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
    }
    if (data.length) frames.push({ event, data: data.join("\n") });
  }

  const pending = normalized.slice(cursor);
  if (pending.length > MAX_SSE_PENDING) throw new Error("stream_frame_too_large");
  return { frames, pending };
}
