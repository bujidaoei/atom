import { useCallback, useEffect, useMemo, useState } from "react";
import { Button } from "../components/ui/Button";
import { Badge } from "../components/ui/Badge";
import { Icon } from "../components/ui/Icon";
import { EmptyState, ErrorState, LoadingState } from "../components/ui/States";
import { Spinner } from "../components/ui/Spinner";
import { api, errorMessage, withBase } from "../lib/api";
import { formatBytes, formatElapsed, formatNumber } from "../lib/format";
import type { RaceHeat, RaceSummary } from "../lib/types";
import type { HeatActivity } from "./useProjectStream";

type RaceTabProps = {
  projectId: string;
  legacyAdoptionAvailable: boolean;
  initialRace: RaceSummary | null;
  heatActivity: Record<string, HeatActivity>;
  /** Called after a heat is adopted so the project and preview refresh. */
  onAdopted: () => void;
  onChanged: () => void;
  canStart: boolean;
};

const HEAT_STATUS: Record<RaceHeat["status"], { label: string; tone: string }> = {
  queued: { label: "排队中", tone: "bg-neutral-12 text-neutral-60" },
  running: { label: "构建中", tone: "bg-brand-alpha-strong text-brand-text" },
  done: { label: "已完成", tone: "bg-success-surface text-success-strong" },
  failed: { label: "失败", tone: "bg-danger-surface text-danger-strong" },
  error: { label: "失败", tone: "bg-danger-surface text-danger-strong" },
  cancelled: { label: "已停止", tone: "bg-neutral-12 text-neutral-60" },
  interrupted: { label: "已中断", tone: "bg-danger-surface text-danger-strong" },
  timed_out: { label: "已超时", tone: "bg-danger-surface text-danger-strong" },
};

export function RaceTab({
  projectId,
  legacyAdoptionAvailable,
  initialRace,
  heatActivity,
  onAdopted,
  onChanged,
  canStart,
}: RaceTabProps) {
  const [race, setRace] = useState<RaceSummary | null>(initialRace);
  const [models, setModels] = useState<string[]>([]);
  const [modelsError, setModelsError] = useState<string | null>(null);
  const [loadingModels, setLoadingModels] = useState(true);
  const [selected, setSelected] = useState<string[]>([]);
  const [starting, setStarting] = useState(false);
  const [budget, setBudget] = useState(180);
  const [startError, setStartError] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());

  // A project refetch can briefly report `race: null` right after a race is
  // kicked off, so a locally started race is never clobbered.
  useEffect(() => {
    if (initialRace) setRace(initialRace);
  }, [initialRace]);

  useEffect(() => {
    let cancelled = false;
    api
      .getSettings()
      .then((settings) => {
        if (cancelled) return;
        const ids = settings.models.map((model) => model.id);
        setModels(ids.length > 0 ? ids : [settings.model]);
        setSelected(ids.slice(0, 2));
      })
      .catch((err: unknown) => {
        if (!cancelled) setModelsError(errorMessage(err));
      })
      .finally(() => {
        if (!cancelled) setLoadingModels(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const refreshRace = useCallback(async () => {
    try {
      const data = await api.getRace(projectId);
      setRace(data.race);
    } catch {
      /* transient — the next tick retries */
    }
  }, [projectId]);

  // Heats report progress over SSE, but totals (tokens, bytes) come from here.
  const running = race?.status === "running";
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => {
      setNow(Date.now());
      onChanged();
      void refreshRace();
    }, 2500);
    return () => window.clearInterval(timer);
  }, [running, refreshRace]);

  const startedAt = useMemo(
    () => (race ? new Date(race.createdAt).getTime() : null),
    [race],
  );

  function toggleModel(id: string) {
    setSelected((current) =>
      current.includes(id)
        ? current.filter((item) => item !== id)
        : current.length >= 4
          ? current
          : [...current, id],
    );
  }

  async function startRace() {
    setStarting(true);
    setStartError(null);
    try {
      const result = await api.startRace(projectId, selected, budget);
      setRace({
        id: result.raceId,
        status: "running",
        heats: result.heats,
        winnerHeatId: null,
        createdAt: new Date().toISOString(),
      });
      setNow(Date.now());
    } catch (err) {
      setStartError(errorMessage(err));
    } finally {
      setStarting(false);
    }
  }

  const columns =
    (race?.heats.length ?? 0) >= 3 ? "lg:grid-cols-3" : "lg:grid-cols-2";

  return (
    <div className="min-h-0 flex-1 overflow-y-auto p-l">
      <div className="mx-auto flex max-w-[1000px] flex-col gap-l">
        <section className="hairline flex flex-col gap-m rounded-l border-neutral-12 bg-base-tertiary p-l">
          <div>
            <h2 className="text-md font-medium text-neutral-95">竞速构建</h2>
            <p className="mt-xxs text-sm text-neutral-60">
              同一份契约交给 2–4 个模型并行构建，挑一个合入主工作区。每个 heat 各扣 1 credit。
            </p>
          </div>

          {loadingModels ? (
            <LoadingState label="读取模型列表" />
          ) : modelsError ? (
            <ErrorState message={modelsError} compact />
          ) : (
            <>
              <div className="flex flex-wrap gap-xs">
                {models.map((id) => {
                  const active = selected.includes(id);
                  const atLimit = !active && selected.length >= 4;
                  return (
                    <button
                      key={id}
                      type="button"
                      onClick={() => toggleModel(id)}
                      disabled={atLimit}
                      aria-pressed={active}
                      className={[
                        "hairline inline-flex items-center gap-xs rounded-full px-m py-[3px] font-mono text-xs transition-colors duration-ui ease-ui",
                        active
                          ? "border-brand-line bg-brand-alpha-strong text-brand-text"
                          : "border-neutral-12 bg-base-secondary text-neutral-80 hover:border-neutral-20 hover:text-neutral-95",
                        atLimit ? "cursor-not-allowed opacity-40" : "",
                      ].join(" ")}
                    >
                      {active ? <Icon name="check" size={11} /> : null}
                      {id}
                    </button>
                  );
                })}
              </div>

              {startError ? <ErrorState title="发起竞速失败" message={startError} compact /> : null}

              <div className="flex flex-wrap items-center gap-m">
                <label className="flex items-center gap-s text-sm text-neutral-60">
                  每个模型时间上限
                  <select aria-label="每个模型时间上限" value={budget} disabled={running || starting}
                    onChange={event => setBudget(Number(event.target.value))}
                    className="rounded-m border border-neutral-12 bg-base-secondary px-s py-xs text-neutral-95">
                    <option value={180}>3 分钟</option><option value={360}>6 分钟</option><option value={600}>10 分钟</option>
                  </select>
                </label>
                <Button
                  onClick={() => void startRace()}
                  loading={starting}
                  disabled={selected.length < 2 || selected.length > 4 || !canStart || running}
                >
                  <Icon name="race" size={14} />
                  {running ? "正在竞速" : "开始竞速"}
                </Button>
                <span className="text-sm text-neutral-60">
                  已选 {selected.length} 个
                  {selected.length < 2 ? "，至少要 2 个" : selected.length > 4 ? "，最多 4 个" : ""}
                  {canStart ? "" : " · 需要先确认契约"}
                </span>
              </div>
            </>
          )}
        </section>

        {race === null ? (
          <div className="hairline rounded-l border-dashed border-neutral-20">
            <EmptyState
              icon="race"
              title="还没有跑过竞速"
              description="选好模型点「开始竞速」，几份产物会并排出现在这里。"
            />
          </div>
        ) : (
          <section className="flex flex-col gap-m">
            <div className="flex items-center gap-s">
              <h3 className="text-md font-medium text-neutral-95">本轮 heats</h3>
              <Badge
                tone={
                  race.status === "running"
                    ? "bg-brand-alpha-strong text-brand-text"
                    : "bg-neutral-12 text-neutral-60"
                }
              >
                {race.status === "running" ? "进行中" : "已结束"}
              </Badge>
              <button
                type="button"
                onClick={() => void refreshRace()}
                className="ml-auto inline-flex items-center gap-xxs rounded-m px-s py-[2px] text-xs text-neutral-60 transition-colors duration-ui ease-ui hover:bg-neutral-8 hover:text-neutral-95"
              >
                <Icon name="refresh" size={12} />
                刷新
              </button>
            </div>

            <div className={`grid grid-cols-1 gap-m ${columns}`}>
              {race.heats.map((heat) => (
                <HeatCard
                  key={heat.id}
                  projectId={projectId}
                  legacyAdoptionAvailable={legacyAdoptionAvailable}
                  heat={heat}
                  activity={heatActivity[heat.id]}
                  isWinner={race.winnerHeatId === heat.id}
                  raceRunning={running}
                  budget={budget}
                  onRetried={() => { void refreshRace(); onChanged(); }}
                  liveElapsed={
                    heat.status === "running" && (heat.runStartedAt || startedAt)
                      ? (heat.elapsedMs ?? 0) + Math.max(0, now - (heat.runStartedAt ? Date.parse(heat.runStartedAt) : startedAt!))
                      : heat.elapsedMs
                  }
                  onAdopted={onAdopted}
                />
              ))}
            </div>
          </section>
        )}
      </div>
    </div>
  );
}

function HeatCard({
  projectId,
  legacyAdoptionAvailable,
  heat,
  activity,
  isWinner,
  raceRunning,
  budget,
  onRetried,
  liveElapsed,
  onAdopted,
}: {
  projectId: string;
  legacyAdoptionAvailable: boolean;
  heat: RaceHeat;
  activity: HeatActivity | undefined;
  isWinner: boolean;
  raceRunning: boolean;
  budget: number;
  onRetried: () => void;
  liveElapsed: number | null;
  onAdopted: () => void;
}) {
  const [adopting, setAdopting] = useState(false);
  const [adoptError, setAdoptError] = useState<string | null>(null);
  const status = HEAT_STATUS[heat.status];
  const incompleteSaved = Boolean(heat.incompleteSavedRevisionId);
  const retryLabel = incompleteSaved ? '从已保存版本继续生成'
    : heat.revisionId ? '基于已有版本重新生成' : '重新生成此赛道';

  return (
    <article
      className={[
        "hairline flex flex-col overflow-hidden rounded-l bg-base-tertiary transition-[border-color] duration-ui ease-ui",
        isWinner ? "border-brand-line" : "border-neutral-12",
      ].join(" ")}
    >
      <header className="flex items-center gap-s border-b border-neutral-8 px-m py-s">
        <span className="min-w-0 flex-1 truncate font-mono text-xs text-neutral-95">
          {heat.model}
        </span>
        {isWinner ? <Badge tone="bg-brand-alpha-strong text-brand-text">已采用</Badge> : null}
        {incompleteSaved && heat.status !== 'running' ? <Badge tone="bg-brand-alpha-strong text-brand-text">已保存未完成版本</Badge> : null}
        <Badge tone={status.tone}>
          {heat.status === "running" ? <Spinner size={10} /> : null}
          {status.label}
        </Badge>
      </header>

      <div className="relative aspect-[16/10] bg-base-secondary-alt">
        {heat.previewUrl && (heat.status === "done" || heat.fileCount > 0) ? (
          <iframe
            src={`${withBase(heat.previewUrl)}?run=${heat.runId ?? ""}&status=${heat.status}`}
            title={`${heat.model} 的预览`}
            sandbox="allow-scripts allow-same-origin"
            tabIndex={-1}
            className="h-full w-full border-0 bg-white"
          />
        ) : (
          <div className="flex h-full items-center justify-center px-m text-center">
            <p className="text-sm text-neutral-40">
              {!["queued", "running", "done"].includes(heat.status)
                ? (heat.error ?? "这一路失败了")
                : (activity?.label ?? "等待第一个文件…")}
            </p>
          </div>
        )}
      </div>

      <dl className="grid grid-cols-2 gap-x-m gap-y-xs border-t border-neutral-8 px-m py-s text-xs">
        <Stat label="耗时" value={formatElapsed(liveElapsed)} />
        <Stat label="文件" value={`${heat.fileCount} 个 · ${formatBytes(heat.bytes)}`} />
        <Stat label="入 token" value={formatNumber(heat.inputTokens)} />
        <Stat label="出 token" value={formatNumber(heat.outputTokens)} />
      </dl>

      {activity && heat.status === "running" ? (
        <p className="truncate border-t border-neutral-8 px-m py-xs font-mono text-xs text-neutral-60">
          {activity.label}
        </p>
      ) : null}

      {adoptError ? (
        <p className="border-t border-neutral-8 px-m py-xs text-xs text-danger-strong" role="alert">
          {adoptError}
        </p>
      ) : null}

      {heat.error && !["running", "queued", "done"].includes(heat.status) ? (
        <p className="border-t border-neutral-8 px-m py-s text-xs text-neutral-60">{heat.error}。可在上方调整时间上限后{retryLabel}；未完成版本尚未通过验收，不能采用或发布。</p>
      ) : null}

      <footer className="mt-auto flex items-center gap-s border-t border-neutral-8 px-m py-s">
        {!["running", "queued", "done"].includes(heat.status) ? (
          <Button size="sm" variant="secondary" loading={adopting} disabled={raceRunning}
            onClick={() => {
              setAdopting(true); setAdoptError(null);
              api.retryHeat(projectId, heat.id, budget).then(onRetried)
                .catch((err: unknown) => setAdoptError(errorMessage(err)))
                .finally(() => setAdopting(false));
            }}>{retryLabel}</Button>
        ) : null}
        <Button
          size="sm"
          variant={isWinner ? "secondary" : "primary"}
          loading={adopting}
          disabled={heat.status !== "done" || raceRunning || !legacyAdoptionAvailable}
          title={!legacyAdoptionAvailable ? "隔离赛道尚无按修订确认的采用入口" : undefined}
          onClick={() => {
            setAdopting(true);
            setAdoptError(null);
            api
              .adoptHeat(projectId, heat.id)
              .then(() => onAdopted())
              .catch((err: unknown) => setAdoptError(errorMessage(err)))
              .finally(() => setAdopting(false));
          }}
        >
          采用
        </Button>
        {heat.status === "done" && !legacyAdoptionAvailable ? (
          <span className="text-xs text-neutral-60">按修订采用尚未开放</span>
        ) : null}
        {heat.previewUrl ? (
          <a
            href={withBase(heat.previewUrl)}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-xxs rounded-m px-s py-[2px] text-xs text-neutral-60 transition-colors duration-ui ease-ui hover:bg-neutral-8 hover:text-neutral-95"
          >
            <Icon name="external" size={12} />
            单独打开
          </a>
        ) : null}
      </footer>
    </article>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col">
      <dt className="text-neutral-40">{label}</dt>
      <dd className="font-mono text-neutral-80">{value}</dd>
    </div>
  );
}
