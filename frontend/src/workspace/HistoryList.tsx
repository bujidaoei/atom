import type { ReactNode } from 'react';
import { Button } from '../components/ui/Button';

export type HistoryItem = { id: string; version: number; createdAt: string; current: boolean; description: string };

/** Shared snapshot presentation; each domain owns preview and restoration semantics. */
export function HistoryList<T extends HistoryItem>({ items, empty, onPreview, onRestore, previewBusy, disabled,
  previewLink, hasEarlier, onEarlier, onLatest }: {
  items: T[]; empty: string; onPreview: (item: T) => void; onRestore: (item: T) => void;
  previewBusy?: string | null; disabled?: boolean; previewLink?: (item: T) => ReactNode;
  hasEarlier: boolean; onEarlier: () => void; onLatest?: () => void;
}) {
  return <>
    {!items.length ? <p className="rounded-xl border border-dashed border-neutral-20 p-l text-sm text-neutral-60">{empty}</p> :
      <ol className="space-y-s">{items.map(item => <li key={item.id} className="rounded-xl border border-neutral-12 bg-base-default p-m">
        <div className="flex flex-wrap items-center justify-between gap-m">
          <div className="min-w-0 flex-1"><p className="text-sm font-medium text-neutral-95">版本 {item.version}{item.current ? ' · 当前版本' : ''}</p>
            <p className="mt-xs text-xs text-neutral-60">{new Date(item.createdAt).toLocaleString('zh-CN')}</p>
            <p className="mt-xs whitespace-pre-wrap break-words text-xs text-neutral-60">{item.description}</p></div>
          <div className="flex items-center gap-m">
            {previewLink?.(item) ?? <Button size="sm" variant="secondary" loading={previewBusy === item.id}
              disabled={Boolean(previewBusy)} onClick={() => onPreview(item)}>预览</Button>}
            {!item.current ? <Button size="sm" variant="secondary" disabled={disabled} onClick={() => onRestore(item)}>恢复此版本</Button> : null}
          </div>
        </div>
      </li>)}</ol>}
    <div className="flex gap-s">{onLatest ? <Button size="sm" variant="secondary" onClick={onLatest}>返回最新版本</Button> : null}
      {hasEarlier ? <Button size="sm" variant="secondary" onClick={onEarlier}>更早的版本</Button> : null}</div>
  </>;
}
