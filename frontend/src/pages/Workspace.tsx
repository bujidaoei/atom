import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Composer } from "../components/Composer";
import { Button, IconButton } from "../components/ui/Button";
import { Badge, StatusBadge } from "../components/ui/Badge";
import { Icon } from "../components/ui/Icon";
import type { IconName } from "../components/ui/Icon";
import { ErrorState, LoadingState } from "../components/ui/States";
import { api, errorMessage, publishedUrl } from "../lib/api";
import { useAuth } from "../lib/auth";
import { agentMeta } from "../lib/agents";
import { isRunningStatus } from "../lib/format";
import { useProjects } from "../lib/projects";
import type { ProjectDetail, RunEventPayload } from "../lib/types";
import { Conversation } from "../workspace/Conversation";
import { ContractTab } from "../workspace/ContractTab";
import { CodeTab } from "../workspace/CodeTab";
import { PreviewTab } from "../workspace/PreviewTab";
import { RaceTab } from "../workspace/RaceTab";
import { runAcceptance } from "../workspace/acceptance";
import { useProjectStream } from "../workspace/useProjectStream";

type TabId = "preview" | "code" | "contract" | "race";

const TABS: { id: TabId; label: string; icon: IconName }[] = [
  { id: "preview", label: "预览", icon: "eye" },
  { id: "code", label: "代码", icon: "code" },
  { id: "contract", label: "契约", icon: "contract" },
  { id: "race", label: "竞速", icon: "race" },
];

export function WorkspacePage() {
  const { id } = useParams<{ id: string }>();
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
  const [publishBusy, setPublishBusy] = useState(false);
  const [previewToken, setPreviewToken] = useState(0);

  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const planKicked = useRef<string | null>(null);

  const load = useCallback(
    async (silent = false) => {
      if (!id) return;
      if (!silent) setLoading(true);
      try {
        const data = await api.getProject(id);
        setProject(data.project);
        upsert(data.project);
        setLoadError(null);
      } catch (err) {
        if (!silent) setLoadError(errorMessage(err));
      } finally {
        if (!silent) setLoading(false);
      }
    },
    [id, upsert],
  );

  useEffect(() => {
    void load();
  }, [load]);

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
    onProjectUpdated: handleProjectUpdated,
  });

  // A project created from the composer arrives as `draft`; plan it once the
  // stream is attached so Mike's first token is not lost.
  useEffect(() => {
    if (!id || !project) return;
    if (project.status !== "draft" || project.activeRunId) return;
    if (planKicked.current === id) return;
    // Wait for the stream to be attached, but don't strand the project if the
    // event endpoint is unreachable.
    if (stream.connection === "idle" || stream.connection === "connecting") return;
    planKicked.current = id;
    setStarting(true);
    api
      .plan(id)
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

  const running = project ? isRunningStatus(project.status) : false;

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
      const doc = iframeRef.current?.contentDocument;
      if (!doc || !doc.body) {
        throw new Error("预览还没加载完，先打开「预览」标签等页面出来再试。");
      }
      const results = await runAcceptance(doc, project.requirements);
      const data = await api.postAcceptance(id, results);
      setProject((current) => (current ? { ...current, acceptance: data.acceptance } : current));
    } catch (err) {
      setAcceptanceError(errorMessage(err));
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

  const activeMeta = agentMeta(stream.activeRole);
  const hasFiles = project.files.length > 0;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex shrink-0 flex-wrap items-center gap-s border-b border-neutral-12 bg-base-default px-l py-s">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-s">
            <h1 className="truncate text-md font-medium text-neutral-95">{project.title}</h1>
            <StatusBadge status={project.status} />
            {activeMeta ? (
              <Badge tone="bg-brand-alpha-soft text-brand-text">{activeMeta.name} 在跑</Badge>
            ) : null}
          </div>
          <p className="mt-xxs truncate text-xs text-neutral-40">{project.prompt}</p>
        </div>

        <div className="flex items-center gap-xs">
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

          <Button
            variant={project.slug ? "secondary" : "primary"}
            size="sm"
            loading={publishBusy}
            disabled={!hasFiles && !project.slug}
            onClick={() => void togglePublish()}
          >
            {project.slug ? "取消发布" : "发布"}
          </Button>

          <IconButton label="刷新项目" onClick={() => void load(true)}>
            <Icon name="refresh" size={14} />
          </IconButton>
        </div>
      </header>

      {actionError ? (
        <div className="shrink-0 px-l pt-s">
          <ErrorState title="操作失败" message={actionError} compact />
        </div>
      ) : null}

      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto md:flex-row md:overflow-hidden">
        <section
          className="flex min-h-[420px] flex-col border-b border-neutral-12 md:min-h-0 md:w-[46%] md:max-w-[560px] md:border-b-0 md:border-r"
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
              disabled={running}
              disabledReason="squad 正在跑，等这一轮结束再说。"
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

        <section className="flex min-h-[520px] min-w-0 flex-1 flex-col md:min-h-0" aria-label="产物面板">
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
                onApprove={approve}
                approving={approving}
                approveError={approveError}
                onRunAcceptance={runChecksNow}
                acceptanceRunning={acceptanceRunning}
                acceptanceError={acceptanceError}
                canRunAcceptance={hasFiles && project.requirements.length > 0}
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
                initialRace={project.race}
                heatActivity={stream.heatActivity}
                canStart={project.status !== "draft" && project.status !== "planning"}
                onAdopted={() => {
                  void load(true);
                  setPreviewToken((token) => token + 1);
                  setTab("preview");
                }}
              />
            </div>
          ) : null}
        </section>
      </div>
    </div>
  );
}
