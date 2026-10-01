import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { Button, LinkButton } from "../components/ui/Button";
import { ErrorState, LoadingState, Panel } from "../components/ui/States";
import { ThemeToggle } from "../components/ThemeToggle";
import { api, errorMessage } from "../lib/api";
import { accessQuery, accessScope, handoffDestination } from "../lib/content-access";
import type { AccessScope } from "../lib/content-access";

export function ContentAccessPage() {
  const { search } = useLocation();
  const query = useMemo(() => accessQuery(search), [search]);
  const [scope, setScope] = useState<AccessScope | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [blocked, setBlocked] = useState(false);
  const [now, setNow] = useState(Date.now());
  const generation = useRef(0);
  const submitting = useRef(false);
  const issueController = useRef<AbortController | null>(null);

  useEffect(() => {
    generation.current += 1;
    setScope(null); setError(null); setBlocked(false); setBusy(false); submitting.current = false;
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 10000);
    let current = true;
    if (query) api.inspectContentAccess(query.binding, query.challenge, controller.signal)
      .then(value => { if (current) setScope(accessScope(value, query.binding)); })
      .catch(reason => { if (current) setError(errorMessage(reason)); });
    return () => {
      current = false; generation.current += 1; controller.abort(); issueController.current?.abort();
      window.clearTimeout(timeout);
    };
  }, [query]);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  async function openContent() {
    if (!scope || !query || submitting.current || blocked || Date.now() >= scope.expiresAt * 1000) return;
    const requestGeneration = generation.current;
    submitting.current = true; setBusy(true); setError(null);
    const controller = new AbortController(); issueController.current = controller;
    const timeout = window.setTimeout(() => controller.abort(), 10000);
    try {
      const result = await api.issueContentAccess(query.binding, query.challenge, controller.signal);
      if (generation.current === requestGeneration && !controller.signal.aborted) window.location.replace(handoffDestination(result, scope));
    } catch (reason) {
      if (generation.current === requestGeneration && !controller.signal.aborted) setError(errorMessage(reason));
      else if (generation.current === requestGeneration) setError("请求未能确认完成，请返回项目重新打开访问链接。");
      if (generation.current === requestGeneration) { setBlocked(true); setBusy(false); }
    } finally { window.clearTimeout(timeout); }
  }

  const expired = !!scope && now >= scope.expiresAt * 1000;
  return <div className="min-h-dvh bg-base-secondary text-neutral-95">
    <header className="mx-auto flex max-w-3xl items-center justify-between px-l py-xl">
      <Link to="/app" className="font-medium text-md rounded-m">Atom</Link><ThemeToggle />
    </header>
    <main className="mx-auto max-w-2xl px-l pb-xxxl pt-xl [text-wrap:pretty]">
      <p className="text-sm text-neutral-60 mb-s">项目访问</p>
      <h1 className="text-2xl font-medium tracking-tight mb-m">确认要打开的版本</h1>
      <p className="text-base text-neutral-60 mb-xl">确认后将在独立内容页面打开项目。此授权仅用于查看所列版本。</p>
      {!query ? <ErrorState title="访问链接无效" message="请返回项目，从项目入口重新打开访问链接。" /> :
        !scope && !error ? <LoadingState label="正在核对项目与版本" /> : null}
      {scope ? <Panel className="p-xl mb-l">
        <p className="text-sm text-neutral-60 mb-xs">项目</p>
        <h2 className="text-xl font-medium break-words mb-xl">{scope.projectTitle}</h2>
        <dl className="grid grid-cols-1 sm:grid-cols-[7rem_minmax(0,1fr)] gap-x-l gap-y-s text-base">
          <dt className="text-neutral-60">版本状态</dt><dd>{scope.isCurrentRelease ? "当前发布版本" : "历史发布版本"}</dd>
          <dt className="text-neutral-60">发布版本</dt><dd className="font-mono text-sm break-all">{scope.releaseId}</dd>
          <dt className="text-neutral-60">内容修订</dt><dd className="font-mono text-sm break-all">{scope.revisionId}</dd>
          <dt className="text-neutral-60">可见范围</dt><dd>{scope.audience === "owner" ? "仅项目所有者" : "公开发布"}</dd>
          <dt className="text-neutral-60">确认有效期</dt><dd>{new Date(scope.expiresAt * 1000).toLocaleTimeString("zh-CN")}</dd>
        </dl>
        {!scope.isCurrentRelease ? <p className="mt-l text-base text-neutral-80">你将打开历史版本，内容可能与当前发布版本不同。</p> : null}
      </Panel> : null}
      {error ? <ErrorState title="暂时无法打开" message={error} /> : null}
      {expired ? <p role="status" className="my-l text-base text-danger-strong">确认已过期，请返回项目重新打开访问链接。</p> : null}
      <div className="mt-xl flex flex-wrap items-center gap-m">
        <Button size="lg" loading={busy} disabled={!scope || expired || blocked} onClick={() => void openContent()}>确认并打开</Button>
        <LinkButton variant="secondary" size="lg" to="/app">返回项目</LinkButton>
      </div>
      <p className="mt-l text-sm text-neutral-60">退出登录或发布状态变化后，需要重新确认访问。</p>
    </main>
  </div>;
}
