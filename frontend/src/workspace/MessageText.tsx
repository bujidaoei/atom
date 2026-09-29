import { Fragment, useMemo, type ReactNode } from "react";

type Block = { kind: "text"; body: string } | { kind: "code"; body: string; lang: string };

/** Minimal fenced-code splitter — agents answer in light markdown. */
function parseBlocks(source: string): Block[] {
  const blocks: Block[] = [];
  const pattern = /```([\w+-]*)\n?([\s\S]*?)(?:```|$)/g;
  let cursor = 0;
  let match: RegExpExecArray | null;

  while ((match = pattern.exec(source)) !== null) {
    if (match.index > cursor) {
      blocks.push({ kind: "text", body: source.slice(cursor, match.index) });
    }
    blocks.push({ kind: "code", body: match[2] ?? "", lang: match[1] ?? "" });
    cursor = match.index + match[0].length;
  }
  if (cursor < source.length) blocks.push({ kind: "text", body: source.slice(cursor) });
  return blocks.filter((block) => block.body.trim().length > 0);
}

/**
 * Renders `**bold**` and `` `code` `` inline.
 *
 * Agents reach for these two constantly — Bob names files in backticks and
 * labels sections in bold — and leaving the raw asterisks on screen makes
 * the transcript look broken. Anything beyond these two stays literal
 * rather than pulling in a markdown dependency.
 */
const INLINE = /(\*\*[^*\n]+\*\*|`[^`\n]+`)/g;

function renderInline(text: string): ReactNode[] {
  return text.split(INLINE).map((piece, index) => {
    if (piece.startsWith("**") && piece.endsWith("**") && piece.length > 4) {
      return (
        <strong key={index} className="font-semibold text-neutral-95">
          {piece.slice(2, -2)}
        </strong>
      );
    }
    if (piece.startsWith("`") && piece.endsWith("`") && piece.length > 2) {
      return (
        <code
          key={index}
          className="rounded-[4px] bg-base-secondary-alt px-[5px] py-[1px] font-mono text-[0.92em] text-neutral-80"
        >
          {piece.slice(1, -1)}
        </code>
      );
    }
    return <Fragment key={index}>{piece}</Fragment>;
  });
}

export function MessageText({ content }: { content: string }) {
  const blocks = useMemo(() => parseBlocks(content), [content]);

  if (blocks.length === 0) return null;

  return (
    <div className="flex flex-col gap-s">
      {blocks.map((block, index) =>
        block.kind === "code" ? (
          <pre
            key={index}
            className="overflow-x-auto rounded-m bg-base-secondary-alt px-m py-s font-mono text-sm leading-5 text-neutral-80"
          >
            {block.lang ? (
              <span className="mb-xxs block text-xs text-neutral-40">{block.lang}</span>
            ) : null}
            <code>{block.body.replace(/\n$/, "")}</code>
          </pre>
        ) : (
          <p
            key={index}
            className="whitespace-pre-wrap break-words text-base leading-6 text-neutral-95"
          >
            {renderInline(block.body.trim())}
          </p>
        ),
      )}
    </div>
  );
}
