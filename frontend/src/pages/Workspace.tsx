import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Composer } from "../components/Composer";
import { Button, IconButton } from "../components/ui/Button";
import { Badge, StatusBadge } from "../components/ui/Badge";
import { Icon } from "../components/ui/Icon";
import type { IconName } from "../components/ui/Icon";
import { ErrorState, LoadingState } from "../components/ui/States";
import { api, ApiError, errorMessage, publishedUrl } from "../lib/api";
import { useAuth } from "../lib/auth";
import { agentMeta } from "../lib/agents";
import { isRunningStatus } from "../lib/format";
import { useProjects } from "../lib/projects";
import type { ProjectDetail, RunEventPayload, VerificationStatus } from "../lib/types";
import { Conversation } from "../workspace/Conversation";
import { ContractTab } from "../workspace/ContractTab";
import { CodeTab } from "../workspace/CodeTab";
import { PreviewTab } from "../workspace/PreviewTab";
import { RaceTab } from "../workspace/RaceTab";
import { ReleaseTab } from "../workspace/ReleaseTab";
import { runAcceptance } from "../workspace/acceptance";
import { useProjectStream } from "../workspace/useProjectStream";
import { ProjectLoader } from "../workspace/project-loader";

type TabId = "preview" | "code" | "contract" | "race" | "release";

const TABS: { id: TabId; label: string; icon: IconName }[] = [
  { id: "preview", label: "预览", icon: "eye" },
  { id: "code", label: "代码", icon: "code" },
  { id: "contract", label: "契约", icon: "contract" },
  { id: "race", label: "竞速", icon: "race" },
  { id: "release", label: "发布", icon: "external" },
];

export function WorkspacePage() {
  const { id } = useParams<{ id: string }>();
  return <ProjectWorkspace key={id} id={id} />;
}

function ProjectWorkspace({ id }: { id: string | undefined }) {
  const { refresh: refreshProjects, upsert } = useProjects();
  const { refresh: refreshUser } = useAuth();

  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [tab, setTab] = useState<TabId>("preview");
  const [starting, setStarting] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [reviseText, setReviseText] = useState("");
  const [approving, setApproving] = useState(false);
  const [approveError, setApproveError] = useState<string | null>(null);
  const [acceptanceRunning, setAcceptanceRunning] = useState(false);
  const [acceptanceError, setAcceptanceError] = useState<string | null>(null);
  const [verification, setVerification] = useState<VerificationStatus | null>(null);
  const [publishBusy, setPublishBusy] = useState(false);
  const [previewToken, setPreviewToken] = useState(0);

  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const planKicked = useRef<string | null>(null);
  const alive = useRef(true);
  const loader = useRef<ProjectLoader<ProjectDetail> | null>(null);
  const hasSnapshot = useRef(false);
  useEffect(() => {
    alive.current = true;
    if (!id) return;
    const current = new ProjectLoader<ProjectDetail>({
      read: async signal => (await api.getProject(id, signal)).project,
      apply: snapshot => {
        if (snapshot.id !== id) throw new Error("工作区响应不匹配，请重试。");
        hasSnapshot.current = true;
        setProject(snapshot);
        upsert(snapshot);
        setLoadError(null);
        setLoading(false);
      },
      fail: error => {
        if (!hasSnapshot.current) setLoadError(errorMessage(error));
        setLoading(false);
      },
    });
    loader.current = current;
    void current.refresh();
    return () => {
      alive.current = false;
      current.dispose();
      loader.current = null;
    };
  }, [id, upsert]);

  const load = useCallback(async (silent = false) => {
    if (!silent && !hasSnapshot.current) { setLoading(true); setLoadError(null); }
    await loader.current?.refresh();
  }, []);

  const handleProjectUpdated = useCallback(
    (payload: RunEventPayload) => {
      void load(true);
      if (payload.status && !isRunningStatus(payload.status)) void refreshUser();
    },
    [load, refreshUser],
  );

  const stream = useProjectStream({
    projectId: id,
    enabled: Boolean(id),
    snapshotStatus: project?.status,
    snapshotEventSeq: project?.eventSeq,
    onProjectUpdated: handleProjectUpdated,
  });

  // A project created from the composer arrives as `draft`; plan it once the
  // stream is attached so Mike's first token is not lost.
  useEffect(() => {
    if (!id || !project) return;
    if (project.status !== "draft" || project.activeRunId) return;
    if (project.id !== id) return;
    if (planKicked.current === id) return;
    // Wait for the stream to be attached, but don't strand the project if the
    // event endpoint is unreachable.
    if (stream.connection === "idle" || stream.connection === "connecting") return;
    planKicked.current = id;
    setActionError(null);
    setStarting(true);
    api
      .plan(id, `initial-plan:${id}`)
      .then(() => void load(true))
      .catch((err: unknown) => setActionError(errorMessage(err)))
      .finally(() => setStarting(false));
  }, [id, project, stream.connection, load]);

  const fileSignature = useMemo(
    () => (project?.files ?? []).map((file) => `${file.path}:${file.updatedAt}`).join("|"),
    [project?.files],
  );

  useEffect(() => {
    if (fileSignature) setPreviewToken((token) => token + 1);
  }, [fileSignature]);

  useEffect(() => {
    if (!id || !project?.isolatedPreviewEnabled) { setVerification(null); return; }
    const controller = new AbortController();
    void api.latestVerification(id, controller.signal)
      .then(data => { if (!controller.signal.aborted) setVerification(
        data.verification?.current && data.verification.revisionId === project.revisionId ? data.verification : null); })
      .catch(error => { if (!controller.signal.aborted) setAcceptanceError(errorMessage(error)); });
    return () => controller.abort();
  }, [id, project?.isolatedPreviewEnabled, project?.revisionId]);

  useEffect(() => {
    if (!id || verification?.state !== "running") return;
    const timer = window.setTimeout(() => {
      void api.latestVerification(id)
        .then(data => setVerification(data.verification?.current ? data.verification : null))
        .catch(error => setAcceptanceError(errorMessage(error)));
    }, 3000);
    return () => window.clearTimeout(timer);
  }, [id, verification]);

  const running = project ? isRunningStatus(project.status) : false;
  useEffect(() => {
    if (!running && stream.connection !== "retrying") return;
    const timer = window.setInterval(() => void load(true), 3000);
    return () => window.clearInterval(timer);
  }, [running, stream.connection, load]);

  async function resume() {
    if (!id || !project) return;
    setStarting(true);
    setActionError(null);
    try {
      if (!project.requirements.length) await api.plan(id, project.status === "draft" ? `initial-plan:${id}` : undefined);
      else await api.revise(id, "继续未完成的生成，先检查已有文件并补齐契约，不要重复已完成的工作。");
      await load(true);
    } catch (err) { setActionError(errorMessage(err)); }
    finally { setStarting(false); }
  }

  async function submitRevise() {
    if (!id || !reviseText.trim()) return;
    setStarting(true);
    setActionError(null);
    try {
      await api.revise(id, reviseText.trim());
      setReviseText("");
      await load(true);
    } catch (err) {
      setActionError(errorMessage(err));
    } finally {
      setStarting(false);
    }
  }

  async function approve(note: string) {
    if (!id) return;
    setApproving(true);
    setApproveError(null);
    try {
      await api.approve(id, note || undefined);
      await load(true);
    } catch (err) {
      setApproveError(errorMessage(err));
    } finally {
      setApproving(false);
    }
  }

  async function cancel() {
    if (!id) return;
    setActionError(null);
    try {
      await api.cancel(id);
      await load(true);
    } catch (err) {
      setActionError(errorMessage(err));
    }
  }

  async function runChecksNow() {
    if (!id || !project) return;
    setAcceptanceRunning(true);
    setAcceptanceError(null);
    setTab("contract");
    try {
      if (project.isolatedPreviewEnabled) {
        if (!project.revisionId) throw new Error("当前还没有可检查的已保存版本。");
        const requestId = Array.from(crypto.getRandomValues(new Uint8Array(16)),
          value => value.toString(16).padStart(2, "0")).join("");
        const reserved = await api.reserveVerification(id, requestId);
        if (reserved.revisionId !== project.revisionId) throw new Error("检查版本已变化，请刷新后重试。");
        setVerification(reserved);
        try {
          const result = await api.runVerification(id, requestId);
          setVerification(result);
        } catch (error) {
          const latest = await api.getVerification(id, requestId);
          setVerification(latest);
          if (latest.state !== "passed" && latest.state !== "failed") throw error;
        }
        return;
      }
      let doc = iframeRef.current?.contentDocument;
      const deadline = Date.now() + 10000;
      while ((!doc?.body || doc.readyState !== "complete" || doc.URL === "about:blank") && Date.now() < deadline) {
        await new Promise(resolve => window.setTimeout(resolve, 100));
        doc = iframeRef.current?.contentDocument;
      }
      if (!doc?.body || doc.readyState !== "complete" || doc.URL === "about:blank") {
        throw new Error("预览加载超时，请刷新预览后重试。");
      }
      const results = await runAcceptance(doc, project.requirements);
      const data = await api.postAcceptance(id, results);
      setProject((current) => (current ? { ...current, acceptance: data.acceptance } : current));
    } catch (err) {
      setAcceptanceError(err instanceof ApiError && err.status >= 500
        ? "检查结果暂时无法保存，请稍后重试。这不代表网页功能不合格。"
        : errorMessage(err));
    } finally {
      setAcceptanceRunning(false);
    }
  }

  async function togglePublish() {
    if (!id || !project) return;
    setPublishBusy(true);
    setActionError(null);
    try {
      if (project.slug) {
        await api.unpublish(id);
      } else {
        await api.publish(id);
      }
      await load(true);
      await refreshProjects();
    } catch (err) {
      setActionError(errorMessage(err));
    } finally {
      setPublishBusy(false);
    }
  }

  if (loading) return <LoadingState label="打开工作区" />;

  if (loadError || !project) {
    return (
      <div className="mx-auto max-w-[520px] px-l py-xxl">
        <ErrorState
          title="打不开这个项目"
          message={loadError ?? "项目不存在或已被删除。"}
          onRetry={() => void load()}
        />
        <p className="mt-l text-sm text-neutral-60">
          <Link to="/app" className="text-brand-text hover:underline">
            返回工作台
          </Link>
        </p>
      </div>
    );
  }

  const activeMeta = agentMeta(running ? stream.activeRole : null);
  const hasFiles = project.files.length > 0;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex shrink-0 flex-wrap items-center gap-s border-b border-neutral-12 bg-base-default px-l py-s">
        <div className="min-w-0 w-full flex-1 sm:w-auto">
          <div className="flex items-center gap-s">
            <h1 className="truncate text-md font-medium text-neutral-95">{project.title}</h1>
            <span className="shrink-0"><StatusBadge status={project.status} /></span>
            {activeMeta ? (
              <Badge tone="bg-brand-alpha-soft text-brand-text">{activeMeta.name} 在跑</Badge>
            ) : null}
          </div>
          <p className="mt-xxs truncate text-xs text-neutral-40">{project.prompt}</p>
        </div>

        <div className="flex w-full items-center justify-between gap-xs sm:w-auto sm:justify-start">
          {stream.connection === "retrying" ? (
            <button
              type="button"
              onClick={stream.reconnectNow}
              className="inline-flex items-center gap-xxs rounded-full bg-danger-surface px-m py-[3px] text-xs text-danger-strong transition-colors duration-ui ease-ui hover:bg-danger-chip"
            >
              <Icon name="refresh" size={12} />
              连接中断，点击重连
            </button>
          ) : null}

          {running ? (
            <Button variant="secondary" size="sm" onClick={() => void cancel()}>
              <Icon name="stop" size={13} />
              停止
            </Button>
          ) : null}

          {project.slug ? (
            <a
              href={publishedUrl(project.slug)}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-xxs rounded-full px-m py-[3px] text-xs text-brand-text transition-colors duration-ui ease-ui hover:bg-brand-alpha-soft"
            >
              <Icon name="external" size={12} />
              /p/{project.slug}
            </a>
          ) : null}

          {project.legacyPublicationAvailable ? (
            <Button variant={project.slug ? "secondary" : "primary"} size="sm"
              loading={publishBusy} disabled={!project.slug && (!hasFiles || project.status !== "ready")}
              onClick={() => void togglePublish()}>
              {project.slug ? "取消发布" : "发布"}
            </Button>
          ) : (
            <Button variant="secondary" size="sm" onClick={() => setTab("release")}>发布与历史</Button>
          )}

          <IconButton label="刷新项目" onClick={() => void load(true)}>
            <Icon name="refresh" size={14} />
          </IconButton>
        </div>
      </header>

      {["error", "cancelled", "timed_out", "interrupted"].includes(project.status) ? (
        <div role="status" className="flex shrink-0 items-center gap-m border-b border-neutral-12 px-l py-s text-sm">
          <div className="flex-1">{project.latestRun?.error || "本轮未完成。"} {project.incompleteSavedRevisionId
            ? "已保存未完成版本，可预览文件；完成生成后才能发布这个版本。功能检查可按需运行。"
            : hasFiles ? "可预览当前已登记的版本，并继续修改。" : "可以重新尝试。"}</div>
          <Button size="sm" variant="secondary" loading={starting} onClick={() => void resume()}>{project.incompleteSavedRevisionId
            ? "从已保存版本继续生成" : hasFiles ? "基于已有版本重新生成" : "重新生成"}</Button>
        </div>
      ) : running ? <div role="status" className="px-l py-xs text-xs text-neutral-60">{project.status === "planning" ? "正在规划需求，完成后请确认契约" : project.race?.status === "running" ? "正在竞速，按所选时间上限运行" : `正在生成，本轮构建上限 ${project.buildBudgetSeconds} 秒`}；完成前可随时停止。</div> : null}

      {actionError ? (
        <div className="shrink-0 px-l pt-s">
          <ErrorState title="操作失败" message={actionError} compact />
          <div className="mt-xs flex gap-s">
            {project.status === "draft" ? <Button size="sm" loading={starting} onClick={() => void resume()}>重试启动</Button> : null}
            <Button size="sm" variant="secondary" onClick={() => setActionError(null)}>关闭提示</Button>
          </div>
        </div>
      ) : null}

      <div className={`flex min-h-0 flex-1 flex-col md:flex-row md:overflow-hidden ${tab === "release" ? "overflow-hidden" : "overflow-y-auto"}`}>
        <section
          className={`${tab === "release" ? "hidden md:flex" : "flex"} min-h-[420px] flex-col border-b border-neutral-12 md:min-h-0 md:w-[46%] md:max-w-[560px] md:border-b-0 md:border-r`}
          aria-label="对话"
        >
          <Conversation
            messages={project.messages}
            items={stream.items}
            liveRunIds={stream.runIdSet}
            starting={starting}
          />

          <div className="shrink-0 border-t border-neutral-12 p-m">
            <Composer
              value={reviseText}
              onChange={setReviseText}
              onSubmit={() => void submitRevise()}
              submitting={starting}
              disabled={running || project.status === "awaiting_approval"}
              disabledReason={running ? "正在生成，可点击停止结束这一轮。" : "请在契约页填写补充要求并确认。"}
              submitLabel="发送"
              minRows={1}
              placeholder={
                project.status === "awaiting_approval"
                  ? "对契约有意见？直接说，squad 会重新规划。"
                  : "接着改：例如把按钮改成绿色。"
              }
              meta={
                stream.inputTokens + stream.outputTokens > 0 ? (
                  <span className="font-mono text-xs">
                    本次 token 入 {stream.inputTokens} · 出 {stream.outputTokens}
                  </span>
                ) : undefined
              }
            />
          </div>
        </section>

        <section className={`flex min-w-0 flex-1 flex-col md:min-h-0 ${tab === "release" ? "min-h-0" : "min-h-[520px]"}`} aria-label="产物面板">
          <div
            role="tablist"
            aria-label="产物视图"
            className="flex shrink-0 items-center gap-xxs border-b border-neutral-12 px-m py-xs"
          >
            {TABS.map((item) => {
              const isActive = tab === item.id;
              return (
                <button
                  key={item.id}
                  type="button"
                  role="tab"
                  id={`tab-${item.id}`}
                  aria-selected={isActive}
                  aria-controls={`panel-${item.id}`}
                  onClick={() => setTab(item.id)}
                  className={[
                    "inline-flex h-7 items-center gap-xs rounded-full px-m text-sm transition-colors duration-ui ease-ui",
                    isActive
                      ? "bg-neutral-16 font-medium text-neutral-95"
                      : "text-neutral-60 hover:bg-neutral-8 hover:text-neutral-95 active:bg-neutral-12",
                  ].join(" ")}
                >
                  <Icon name={item.icon} size={13} />
                  {item.label}
                  {item.id === "contract" && project.status === "awaiting_approval" ? (
                    <span className="h-[5px] w-[5px] animate-pulse-soft rounded-full bg-brand" />
                  ) : null}
                  {item.id === "code" && hasFiles ? (
                    <span className="font-mono text-xs text-neutral-40">{project.files.length}</span>
                  ) : null}
                </button>
              );
            })}
          </div>

          {/* The preview iframe stays mounted so acceptance can reach its document. */}
          <div
            role="tabpanel"
            id="panel-preview"
            aria-labelledby="tab-preview"
            hidden={tab !== "preview"}
            className={`min-h-0 flex-1 ${tab === "preview" ? "flex flex-col" : "hidden"}`}
          >
            <PreviewTab
              projectId={project.id}
              status={project.status}
              hasFiles={hasFiles}
              isolated={project.isolatedPreviewEnabled}
              revisionId={project.revisionId}
              iframeRef={iframeRef}
              reloadToken={previewToken}
            />
          </div>

          {tab === "code" ? (
            <div
              role="tabpanel"
              id="panel-code"
              aria-labelledby="tab-code"
              className="flex min-h-0 flex-1 flex-col"
            >
              <CodeTab projectId={project.id} files={project.files} />
            </div>
          ) : null}

          {tab === "contract" ? (
            <div
              role="tabpanel"
              id="panel-contract"
              aria-labelledby="tab-contract"
              className="flex min-h-0 flex-1 flex-col"
            >
              <ContractTab
                status={project.status}
                requirements={project.requirements}
                acceptance={project.acceptance}
                isolated={project.isolatedPreviewEnabled}
                verification={verification}
                onApprove={approve}
                approving={approving}
                approveError={approveError}
                onRunAcceptance={runChecksNow}
                acceptanceRunning={acceptanceRunning}
                acceptanceError={acceptanceError}
                canRunAcceptance={!running && hasFiles && project.requirements.length > 0 &&
                  (!project.isolatedPreviewEnabled || (Boolean(project.revisionId) && verification?.state !== "running"))}
              />
            </div>
          ) : null}

          {tab === "race" ? (
            <div
              role="tabpanel"
              id="panel-race"
              aria-labelledby="tab-race"
              className="flex min-h-0 flex-1 flex-col"
            >
              <RaceTab
                projectId={project.id}
                isolatedPreview={project.isolatedPreviewEnabled}
                revisionAdoptionAvailable={project.revisionAdoptionAvailable}
                mainRevisionId={project.revisionId}
                initialRace={project.race}
                onChanged={() => { void load(true); }}
                heatActivity={stream.heatActivity}
                canStart={!running && !starting && project.requirements.length > 0}
                onAdopted={() => {
                  void load(true);
                  setPreviewToken((token) => token + 1);
                  setTab("preview");
                }}
              />
            </div>
          ) : null}

          {tab === "release" ? (
            <div role="tabpanel" id="panel-release" aria-labelledby="tab-release" className="flex min-h-0 flex-1 flex-col">
              <ReleaseTab project={project} />
            </div>
          ) : null}
        </section>
      </div>
    </div>
  );
}
