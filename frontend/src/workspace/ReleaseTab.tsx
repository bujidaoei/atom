import { useCallback, useEffect, useState } from "react";
import { api, ApiError, errorMessage } from "../lib/api";
import type { ProjectDetail, VerifiedPublication, VerificationStatus } from "../lib/types";
import { Button } from "../components/ui/Button";

type Snapshot =
  | { kind: "loading" }
  | { kind: "unavailable" }
  | { kind: "error"; message: string }
  | { kind: "ready"; publication: VerifiedPublication | null; verification: VerificationStatus | null; verificationError: string | null };

function Evidence({ label, value }: { label: string; value: string }) {
  return <div className="min-w-0 rounded-xl border border-neutral-12 bg-base-default p-m">
    <dt className="text-xs text-neutral-60">{label}</dt>
    <dd className="mt-xs break-all font-mono text-xs text-neutral-95">{value}</dd>
  </div>;
}

export function ReleaseTab({ project }: { project: ProjectDetail }) {
  const [snapshot, setSnapshot] = useState<Snapshot>({ kind: "loading" });
  const [refreshIndex, setRefreshIndex] = useState(0);
  const refresh = useCallback(() => setRefreshIndex(value => value + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    setSnapshot({ kind: "loading" });
    async function load() {
      try {
        const { publication } = await api.currentVerifiedRelease(project.id, controller.signal);
        let verification: VerificationStatus | null = null;
        let verificationError: string | null = null;
        if (publication) {
          try {
            verification = await api.getVerification(project.id, publication.verificationId, controller.signal);
          } catch (error) {
            if (controller.signal.aborted) return;
            verificationError = errorMessage(error);
          }
        }
        if (!controller.signal.aborted) setSnapshot({ kind: "ready", publication, verification, verificationError });
      } catch (error) {
        if (controller.signal.aborted) return;
        if (error instanceof ApiError && error.status === 404) setSnapshot({ kind: "unavailable" });
        else setSnapshot({ kind: "error", message: errorMessage(error) });
      }
    }
    void load();
    return () => controller.abort();
  }, [project.id, project.revisionId, refreshIndex]);

  const publication = snapshot.kind === "ready" ? snapshot.publication : null;
  const stale = Boolean(publication && project.revisionId !== publication.revisionId);

  return <div className="min-h-0 flex-1 overflow-y-auto p-l" aria-label="发布工作台">
    <div className="mx-auto max-w-[780px] space-y-l">
      <div className="flex flex-wrap items-start justify-between gap-m">
        <div>
          <h2 className="text-lg font-semibold text-neutral-95">发布工作台</h2>
          <p className="mt-xs text-sm text-neutral-60">核对已登记的版本、可信验证和线上指针。每次发布都应明确选定受众。</p>
        </div>
        <Button size="sm" variant="secondary" onClick={refresh}>刷新状态</Button>
      </div>

      <dl className="grid gap-s sm:grid-cols-2">
        <Evidence label="当前登记修订" value={project.revisionId ?? "尚无已登记修订"} />
        <Evidence label="项目状态" value={project.status} />
      </dl>

      {snapshot.kind === "loading" ? <p role="status" className="text-sm text-neutral-60">正在读取发布账本…</p> : null}
      {snapshot.kind === "unavailable" ? <div role="status" className="rounded-xl border border-neutral-12 bg-neutral-8 p-l">
        <h3 className="font-medium text-neutral-95">可信发布尚未启用</h3>
        <p className="mt-xs text-sm text-neutral-60">当前服务没有提供可信验证和独立制品站点。这个版本只能在工作区预览；发布需要服务端完成验证、独立站点配置和迁移验收。</p>
      </div> : null}
      {snapshot.kind === "error" ? <div role="alert" className="rounded-xl border border-danger-strong p-l text-sm">
        发布状态无法确认：{snapshot.message}。请刷新状态后再判断，不能把查询失败视作未发布。
      </div> : null}
      {snapshot.kind === "ready" && !publication ? <div role="status" className="rounded-xl border border-neutral-12 bg-neutral-8 p-l">
        <h3 className="font-medium text-neutral-95">暂无已登记的发布指针</h3>
        <p className="mt-xs text-sm text-neutral-60">发布账本已连接，但当前没有线上版本。可信验证和发布操作仍需从经过验收的控制流程完成。</p>
      </div> : null}
      {publication ? <div className="space-y-m rounded-xl border border-neutral-12 bg-base-default p-l">
        <div className="flex flex-wrap items-center justify-between gap-s">
          <h3 className="font-medium text-neutral-95">{publication.live ? "线上版本" : "已撤回的版本"}</h3>
          <span className="text-xs text-neutral-60">第 {publication.generation} 代 · {publication.audience === "public" ? "公开" : "仅所有者"}</span>
        </div>
        {stale ? <p role="status" className="rounded-lg bg-neutral-8 p-s text-sm text-neutral-95">当前修订与线上版本不同。继续编辑不会自动更新线上内容。</p> : null}
        <dl className="grid gap-s sm:grid-cols-2">
          <Evidence label="发布版本" value={publication.releaseId} />
          <Evidence label="线上修订" value={publication.revisionId} />
          <Evidence label="契约摘要" value={publication.contractDigest} />
          <Evidence label="可信验证" value={publication.verificationId} />
        </dl>
        {snapshot.kind === "ready" && snapshot.verification ? <p className="text-sm text-neutral-60">
          验证结果：{snapshot.verification.state} · {snapshot.verification.passed ?? "—"}/{snapshot.verification.total ?? "—"} 项通过
        </p> : null}
        {snapshot.kind === "ready" && snapshot.verificationError ? <p role="alert" className="text-sm text-danger-strong">验证记录暂无法读取：{snapshot.verificationError}</p> : null}
        {publication.live && publication.pinnedUrl ? <a href={publication.pinnedUrl} target="_blank" rel="noreferrer" className="block break-all text-sm text-brand-text hover:underline">打开不可变版本：{publication.pinnedUrl}</a> : null}
        {publication.live && publication.sharingUrl ? <a href={publication.sharingUrl} target="_blank" rel="noreferrer" className="block break-all text-sm text-brand-text hover:underline">打开公开分享地址：{publication.sharingUrl}</a> : null}
        {!publication.live ? <p className="text-sm text-neutral-60">此指针已撤回，链接不可用；历史制品并未因此被改写。</p> : null}
      </div> : null}
    </div>
  </div>;
}
