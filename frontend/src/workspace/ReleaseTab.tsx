import { useCallback, useEffect, useRef, useState } from "react";
import { api, errorMessage } from "../lib/api";
import { openRevisionPreview } from "../lib/previewAccess";
import type { ProjectDetail, VerifiedPublication, PublicationHistory, PublicationSnapshot, VerificationStatus } from "../lib/types";
import { Button } from "../components/ui/Button";
import { ReleaseControls } from "./ReleaseControls";

const timeLabel = (value: string) => new Date(value).toLocaleString("zh-CN");

export function ReleaseTab({ project }: { project: ProjectDetail }) {
  const [data, setData] = useState<{ publication: VerifiedPublication | null; history: PublicationHistory } | null>(null);
  const [latest, setLatest] = useState<VerificationStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [previewBusy, setPreviewBusy] = useState<string | null>(null);
  const [restore, setRestore] = useState<PublicationSnapshot | null>(null);
  const [refreshIndex, setRefreshIndex] = useState(0);
  const [cursor, setCursor] = useState<string | undefined>();
  const controls = useRef<HTMLDivElement>(null);
  const refresh = useCallback(() => { setCursor(undefined); setRefreshIndex(value => value + 1); }, []);

  async function openSnapshot(item: PublicationSnapshot) {
    setPreviewBusy(item.releaseId);
    setPreviewError(null);
    try {
      await openRevisionPreview(project.id, item.revisionId);
    } catch (failure) {
      setPreviewError(`无法打开版本预览：${errorMessage(failure)}`);
    } finally {
      setPreviewBusy(null);
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError(null); setRestore(null); setLatest(null);
    void Promise.all([api.currentVerifiedRelease(project.id, controller.signal), api.publicationHistory(project.id, cursor, controller.signal)])
      .then(async ([current, history]) => {
        if (controller.signal.aborted) return;
        setData({ publication: current.publication, history });
        if (history.publicationPolicy === "required") {
          const result = await api.latestVerification(project.id, controller.signal);
          if (!controller.signal.aborted) setLatest(result.verification);
        }
      })
      .catch(failure => { if (!controller.signal.aborted) setError(`暂时无法读取发布状态：${errorMessage(failure)}。你的编辑内容仍然保留。`); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [project.id, project.revisionId, refreshIndex, cursor]);

  useEffect(() => {
    if (latest?.state !== "running") return;
    const timer = window.setTimeout(refresh, 3000);
    return () => window.clearTimeout(timer);
  }, [latest, refresh]);

  const publication = data?.publication;
  const changed = publication && publication.revisionId !== project.revisionId;
  return <div className="min-h-0 flex-1 overflow-y-auto p-l" aria-label="发布与历史">
    <div className="mx-auto max-w-[780px] space-y-l">
      <div className="flex flex-wrap items-start justify-between gap-m">
        <div><h2 className="text-lg font-semibold text-neutral-95">发布与历史</h2>
          <p className="mt-xs text-sm text-neutral-60">每次发布都会保存一个快照。随时查看历史，也能恢复到之前的版本。</p></div>
        <Button size="sm" variant="secondary" disabled={loading} onClick={refresh}>刷新</Button>
      </div>
      {loading ? <p role="status" className="text-sm text-neutral-60">正在读取发布状态…</p> : null}
      {error ? <p role="alert" className="rounded-xl border border-danger-strong p-m text-sm text-danger-strong">{error}</p> : null}
      {data && !loading && !error ? <>
        <section className="space-y-m rounded-xl border border-neutral-12 bg-base-default p-l" aria-label="当前网站">
          <h3 className="font-medium text-neutral-95">{publication?.live ? "当前已发布" : publication ? "网站已停止发布" : "准备好分享你的作品了吗？"}</h3>
          <p className="text-sm text-neutral-60">{publication?.live
            ? changed ? "你有尚未发布的编辑。发布更新后，访问者才会看到新内容。" : "当前编辑与已发布版本一致。之后的编辑不会自动影响网站。"
            : publication ? "公开链接已关闭，历史快照仍然保留。你可以重新发布，也可以恢复历史版本。" : "发布后即可获得访问链接。继续编辑时，已发布的网站保持不变。"}</p>
          {publication?.sharingUrl ? <a href={publication.sharingUrl} target="_blank" rel="noreferrer" className="block break-all text-sm text-brand-text hover:underline">访问网站 ↗ {publication.sharingUrl}</a> : null}
        </section>
        <div ref={controls}><ReleaseControls key={project.id} project={project} publication={publication ?? null} latest={latest}
          policy={data.history.publicationPolicy} restore={restore} onCancelRestore={() => setRestore(null)} onRefresh={refresh} /></div>
        <section className="space-y-m" aria-label="发布历史">
          <div><h3 className="font-medium text-neutral-95">发布历史</h3><p className="mt-xs text-sm text-neutral-60">恢复只切换网站内容，不会覆盖你正在编辑的草稿或回退业务数据。</p></div>
          {previewError ? <p role="alert" className="text-sm text-danger-strong">{previewError}</p> : null}
          {!data.history.items.length ? <p className="rounded-xl border border-dashed border-neutral-20 p-l text-sm text-neutral-60">第一次发布后，快照会出现在这里。</p> :
            <ol className="space-y-s">{data.history.items.map(item => <li key={item.releaseId} className="rounded-xl border border-neutral-12 bg-base-default p-m">
              <div className="flex flex-wrap items-center justify-between gap-m">
                <div><p className="text-sm font-medium text-neutral-95">版本 {item.version}{item.isLive ? " · 当前版本" : ""}</p><p className="mt-xs text-xs text-neutral-60">{timeLabel(item.createdAt)}</p>
                  <p className="mt-xs text-xs text-neutral-60">{item.restoredFrom ? "从历史版本恢复" : "发布快照"} · {item.audience === "public" ? "公开" : "仅自己可见"}</p></div>
                <div className="flex items-center gap-m">
                  {item.previewUrl ? <a href={item.previewUrl} target="_blank" rel="noreferrer" className="text-sm text-brand-text hover:underline">预览</a>
                    : <Button size="sm" variant="secondary" loading={previewBusy === item.releaseId}
                        disabled={previewBusy !== null} onClick={() => void openSnapshot(item)}>预览</Button>}
                  {!item.isLive ? <Button size="sm" variant="secondary" onClick={() => { setRestore(item); controls.current?.scrollIntoView({ behavior: "smooth", block: "start" }); }}>恢复此版本</Button> : null}
                </div>
              </div>
            </li>)}</ol>}
          <div className="flex gap-s">{cursor ? <Button size="sm" variant="secondary" onClick={() => setCursor(undefined)}>返回最新版本</Button> : null}
            {data.history.nextCursor ? <Button size="sm" variant="secondary" onClick={() => setCursor(data.history.nextCursor ?? undefined)}>更早的版本</Button> : null}</div>
        </section>
      </> : null}
    </div>
  </div>;
}
