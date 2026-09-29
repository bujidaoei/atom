/** Geometric wordmark placeholder — a real logo asset would replace the glyph. */
export function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <span className="inline-flex items-center gap-s">
      <span
        className="relative inline-flex h-6 w-6 items-center justify-center rounded-m bg-brand"
        aria-hidden="true"
      >
        <span className="h-[7px] w-[7px] rounded-full bg-white" />
        <span className="absolute inset-[3px] rounded-full border border-white/50" />
      </span>
      {compact ? null : (
        <span className="text-md font-medium tracking-[-0.01em] text-neutral-95">Atom</span>
      )}
    </span>
  );
}
