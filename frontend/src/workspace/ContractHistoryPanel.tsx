import { useEffect, useState } from 'react';
import { api, errorMessage } from '../lib/api';
import type { ContractDocument, ContractHistory, ContractSnapshot, ProjectStatus } from '../lib/types';
import { Button } from '../components/ui/Button';
import { HistoryList } from './HistoryList';
import { RequirementCards } from './RequirementCards';

export function ContractDetails({ document }: { document: ContractDocument }) {
  return <div className="space-y-s text-sm text-neutral-80">
    {document.scope.length ? <p><strong>本版包含：</strong>{document.scope.join('；')}</p> : null}
    {document.outOfScope.length ? <p><strong>本版不包含：</strong>{document.outOfScope.join('；')}</p> : null}
    {document.notes.length ? <details><summary className="cursor-pointer">已纳入的微调说明（{document.notes.length}）</summary>
      <ol className="mt-s list-inside list-decimal space-y-xs whitespace-pre-wrap">{document.notes.map((note, index) => <li key={index}>{note}</li>)}</ol></details> : null}
    {document.architecture ? <details><summary className="cursor-pointer">实现方案</summary><p className="mt-s whitespace-pre-wrap break-words leading-6">{document.architecture}</p></details> : null}
  </div>;
}

export function ContractHistoryPanel({ projectId, contract, status, disabled, onChanged }: {
  projectId: string; contract: ContractSnapshot | null; status: ProjectStatus; disabled: boolean; onChanged: () => Promise<void>;
}) {
  const [data, setData] = useState<ContractHistory | null>(null);
  const [before, setBefore] = useState<number>();
  const [refresh, setRefresh] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<ContractSnapshot | null>(null);
  const [previewBusy, setPreviewBusy] = useState<string | null>(null);
  const [restoring, setRestoring] = useState(false);
  const [selection, setSelection] = useState<{ id: string; version: number } | null>(null);
  useEffect(() => { setBefore(undefined); setSelection(null); setPreview(null); }, [projectId, contract?.id]);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError(null);
    void api.contractHistory(projectId, before, controller.signal).then(result => {
      if (!controller.signal.aborted) setData(result);
    }).catch(failure => { if (!controller.signal.aborted) setError(errorMessage(failure)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [projectId, contract?.id, status, before, refresh]);
  async function open(id: string) {
    setPreviewBusy(id); setError(null);
    try { setPreview((await api.contractSnapshot(projectId, id)).snapshot); }
    catch (failure) { setError(errorMessage(failure)); }
    finally { setPreviewBusy(null); }
  }
  async function restore() {
    if (!selection || disabled || restoring) return;
    setRestoring(true); setError(null);
    try {
      await api.restoreContract(projectId, selection.id, contract?.id ?? null);
      setSelection(null); setPreview(null); setBefore(undefined); setRefresh(value => value + 1);
      await onChanged();
    } catch (failure) { setError(errorMessage(failure)); }
    finally { setRestoring(false); }
  }
  return <section className="space-y-m border-t border-neutral-12 pt-l" aria-label="契约历史">
    <div className="flex items-center justify-between gap-m"><div><h2 className="text-md font-medium text-neutral-95">契约历史</h2>
      <p className="mt-xs text-sm text-neutral-60">每次成功微调都会保存快照。恢复只改变契约，不会回退代码或已发布的网站。</p></div>
      <Button size="sm" variant="secondary" disabled={loading} onClick={() => setRefresh(value => value + 1)}>刷新历史</Button></div>
    {loading ? <p role="status" className="text-sm text-neutral-60">正在读取契约历史…</p> : null}
    {error ? <p role="alert" className="text-sm text-danger-strong">{error}</p> : null}
    {selection ? <div className="space-y-s rounded-xl border border-brand-line p-m" role="region" aria-label="确认恢复契约">
      <p className="text-sm">恢复版本 {selection.version}？这会保存为一个新版本，现有历史全部保留。</p>
      <div className="flex gap-s"><Button disabled={disabled} loading={restoring} onClick={() => void restore()}>确认恢复</Button>
        <Button variant="secondary" disabled={restoring} onClick={() => setSelection(null)}>取消</Button></div>
    </div> : null}
    {preview ? <section className="space-y-m rounded-xl border border-brand-line p-m" aria-label={`契约版本 ${preview.version} 预览`}>
      <div className="flex items-center justify-between gap-s"><h3 className="font-medium">版本 {preview.version} · 只读预览</h3>
        <Button variant="secondary" size="sm" onClick={() => setPreview(null)}>关闭预览</Button></div>
      <p className="whitespace-pre-wrap break-words text-sm text-neutral-60">{preview.note}</p>
      <ContractDetails document={preview.document} />
      <RequirementCards requirements={preview.document.requirements} />
    </section> : null}
    {data && !loading && !error ? <HistoryList items={data.items.map(item => ({ ...item, current: item.id === data.currentId, description: item.note }))}
      empty="首次微调或确认构建时，会先保存已有契约作为历史起点。" disabled={disabled || restoring}
      previewBusy={previewBusy} onPreview={item => void open(item.id)} onRestore={setSelection}
      hasEarlier={data.nextCursor !== null} onEarlier={() => setBefore(data.nextCursor ?? undefined)}
      onLatest={before ? () => setBefore(undefined) : undefined} /> : null}
  </section>;
}
