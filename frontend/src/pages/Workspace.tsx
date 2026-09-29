import { FormEvent, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, readError } from "../api";
import type { Project, RuntimeResult } from "../types";
import { AgentFace, team } from "../agents";
import { ComposerDock } from "../ModelSelect";
import { Button, StatusDot, Wordmark, roleLabel, statusLabel } from "../ui";
import { PreviewPane } from "./PreviewPane";

const planJobs = new Map<string, Promise<Project>>();

function sharedPlan(id: string) {
  const existing = planJobs.get(id);
  if (existing) return existing;
  const job = api.plan(id).finally(() => planJobs.delete(id));
  planJobs.set(id, job);
  return job;
}

export function WorkspacePage() {
  const { id = "" } = useParams();
  const [project, setProject] = useState<Project | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [instruction, setInstruction] = useState("");
  const [pane, setPane] = useState<"preview" | "code">("preview");
  const [filePath, setFilePath] = useState("index.html");
  const [missing, setMissing] = useState(false);
  const logRef = useRef<HTMLDivElement>(null);
  const probeRef = useRef<(() => Promise<RuntimeResult[]>) | null>(null);

  useEffect(() => {
    let cancelled = false;
    setProject(null);
    setMissing(false);
    api
      .project(id)
      .then((next) => {
        if (!cancelled) setProject(next);
      })
      .catch((err) => {
        if (cancelled) return;
        if (err instanceof Error && "status" in err && (err as { status: number }).status === 404) setMissing(true);
        setError(readError(err));
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  useEffect(() => {
    if (!project || project.id !== id || project.status !== "draft") return;
    let cancelled = false;
    setBusy("plan");
    sharedPlan(project.id)
      .then((next) => {
        if (!cancelled && next.id === id) setProject(next);
      })
      .catch(async (err) => {
        if (cancelled) return;
        setError(readError(err));
        const fresh = await api.project(project.id).catch(() => null);
        if (fresh && !cancelled) setProject(fresh);
      })
      .finally(() => {
        if (!cancelled) setBusy("");
      });
    return () => {
      cancelled = true;
    };
  }, [project]);

  useEffect(() => {
    document.title = project ? `${project.name} · Atom` : "项目 · Atom";
  }, [project]);

  useEffect(() => {
    const node = logRef.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [project?.messages.length, project?.status, project?.pending_amendment]);

  async function run(label: string, action: () => Promise<Project>) {
    setBusy(label);
    setError("");
    try {
      setProject(await action());
    } catch (err) {
      setError(readError(err));
      const fresh = await api.project(id).catch(() => null);
      if (fresh) setProject(fresh);
    } finally {
      setBusy("");
    }
  }

  async function send(event: FormEvent) {
    event.preventDefault();
    const text = instruction.trim();
    if (!text || !project?.contract_locked) return;
    setInstruction("");
    await run("revise", () => api.revise(id, text));
  }

  async function accept() {
    if (!project) return;
    setBusy("accept");
    setError("");
    try {
      const needsRuntime = project.requirements.some((item) => item.checks.some((check) => check.op === "flow"));
      const runtime = needsRuntime ? await probeRef.current?.() : [];
      if (needsRuntime && !runtime) throw new Error("预览还没准备好");
      setProject(await api.accept(id, runtime || []));
    } catch (err) {
      setError(readError(err));
    } finally {
      setBusy("");
    }
  }

  if (missing) {
    return (
      <p className="px-6 py-10 text-sm">
        没有这个项目。 <Link to="/app">回工作台</Link>
      </p>
    );
  }
  if (!project) {
    return <p className="px-6 py-10 text-sm text-muted">正在打开项目</p>;
  }

  const acceptance = new Map(project.latest_acceptance?.items.map((item) => [item.key, item]) || []);
  const working = busy === "plan" || project.status === "planning" || busy === "build" || project.status === "building";
  const activeFile = project.files.find((file) => file.path === filePath) || project.files[0];
  const stepText =
    busy === "build" || project.status === "building"
      ? "正在生成页面"
      : project.status === "awaiting_approval"
        ? "契约写好了，等你批准"
        : project.status === "ready"
          ? "页面可以预览"
          : working
            ? "正在把想法写成契约"
            : statusLabel[project.status] || project.status;
  const consoleLines = [
    error,
    ...(project.latest_acceptance?.items.filter((item) => !item.ok).map((item) => item.checks.find((check) => !check.ok)?.detail || item.title) ||
      []),
  ].filter(Boolean);

  const personByRole = new Map<string, (typeof team)[number]>(team.map((person) => [person.id, person]));

  return (
    <div className="flex h-screen min-h-0 flex-col bg-[#f3f4f6]">
      <header className="flex h-12 shrink-0 items-center gap-3 border-b border-[#e7e7e7] bg-white px-3">
        <Wordmark to="/app" />
        <h1 className="min-w-0 truncate text-sm font-medium">{project.name}</h1>
        <Link to="/app/settings" className="ml-auto px-2 text-xs text-[#6b7280] hover:text-ink">
          网关
        </Link>
      </header>

      <div className="grid min-h-0 flex-1 lg:grid-cols-[minmax(320px,420px)_minmax(0,1fr)]">
        <aside className="flex min-h-[520px] flex-col border-b border-[#e7e7e7] bg-white lg:min-h-0 lg:border-b-0 lg:border-r">
          <div ref={logRef} className="min-h-0 flex-1 overflow-auto px-4 py-4">
            <p className="text-sm leading-6 text-[#1a1a1a]">{project.prompt}</p>
            {project.messages.length === 0 && working ? (
              <p className="mt-4 flex items-center gap-2 text-sm text-[#6b7280]">
                <StatusDot tone="work" />
                正在把想法写成契约
              </p>
            ) : null}
            <ul className="mt-4 space-y-4">
              {project.messages.map((message) => {
                const person = personByRole.get(message.role);
                return (
                  <li key={message.id} className="flex gap-2">
                    {person ? <AgentFace name={person.name} fill={person.fill} mouth={person.mouth} className="h-7 w-7 shrink-0" /> : <span className="w-7 shrink-0" />}
                    <div className="min-w-0">
                      <p className="text-xs text-[#6b7280]">{roleLabel[message.role] || message.role}</p>
                      <p className="mt-1 whitespace-pre-wrap text-sm leading-6">{message.content}</p>
                    </div>
                  </li>
                );
              })}
            </ul>
            {project.status === "building" || busy === "build" || busy === "revise" ? (
              <p className="mt-4 flex items-center gap-2 text-sm text-[#6b7280]">
                <StatusDot tone="work" />
                工程师正在改页面
              </p>
            ) : null}

            <div className="mt-6">
              <div className="flex items-baseline justify-between">
                <p className="text-xs text-[#6b7280]">契约</p>
                {project.latest_acceptance ? (
                  <p className="font-mono text-xs text-[#6b7280]">
                    {project.latest_acceptance.passed}/{project.latest_acceptance.total}
                  </p>
                ) : null}
              </div>
              {project.requirements.length === 0 ? (
                <p className="mt-3 text-sm text-[#6b7280]">{working ? "正在写" : "还没有"}</p>
              ) : (
                <ul className="mt-2">
                  {project.requirements.map((item) => {
                    const result = acceptance.get(item.key);
                    return (
                      <li key={item.key} className="flex items-start gap-2 py-2">
                        <span className="mt-1">
                          <StatusDot tone={result ? (result.ok ? "ok" : "bad") : "wait"} />
                        </span>
                        <div>
                          <p className="text-sm">{item.title}</p>
                          {result && !result.ok ? (
                            <p className="mt-1 text-xs leading-5 text-clay">{result.checks.find((check) => !check.ok)?.detail}</p>
                          ) : null}
                        </div>
                      </li>
                    );
                  })}
                </ul>
              )}
              <Button onClick={accept} disabled={!project.html || busy !== ""} className="mt-3">
                {busy === "accept" ? "正在验收" : "跑验收"}
              </Button>
            </div>

            {project.pending_amendment ? (
              <div className="mt-4 rounded-xl border border-[#e7e7e7] p-3">
                <p className="text-sm">这会改掉已锁定的契约</p>
                <p className="mt-1 text-sm leading-6 text-[#6b7280]">{project.pending_amendment.reason}</p>
                <div className="mt-3 flex gap-2">
                  <Button onClick={() => run("build", () => api.applyAmendment(id))} disabled={busy !== ""}>
                    修订并重建
                  </Button>
                  <Button variant="line" onClick={() => run("discard", () => api.discardAmendment(id))} disabled={busy !== ""}>
                    保持原契约
                  </Button>
                </div>
              </div>
            ) : null}
            {project.status === "error" ? (
              <Button
                className="mt-4"
                onClick={() =>
                  run(project.requirements.length ? "build" : "plan", () =>
                    project.requirements.length ? api.build(id) : api.plan(id),
                  )
                }
                disabled={busy !== ""}
              >
                再试一次
              </Button>
            ) : null}
            {project.status === "awaiting_approval" && !project.contract_locked ? (
              <div className="mt-4 flex flex-wrap gap-2">
                <Button onClick={() => run("build", () => api.build(id))} disabled={busy !== ""}>
                  {busy === "build" ? "正在构建" : "批准并构建"}
                </Button>
                <Button variant="line" onClick={() => run("plan", () => api.plan(id))} disabled={busy !== ""}>
                  重写契约
                </Button>
              </div>
            ) : null}
          </div>

          <div className="border-t border-[#e7e7e7] p-3">
            {error ? <p className="mb-2 text-sm text-clay">{error}</p> : null}
            <ComposerDock
              value={instruction}
              onChange={setInstruction}
              onSubmit={send}
              busy={busy !== ""}
              disabled={!project.contract_locked || busy !== "" || !instruction.trim()}
              placeholder="让智能体团队实现你的想法"
              onError={setError}
            />
          </div>
        </aside>

        <section className="flex min-h-[480px] flex-col bg-[#f3f4f6] lg:min-h-0">
          <div className="flex h-10 shrink-0 items-center gap-3 border-b border-[#e7e7e7] bg-white px-4 text-xs text-[#6b7280]">
            <StatusDot tone={project.status === "error" ? "bad" : working ? "work" : project.status === "ready" ? "ok" : "wait"} />
            <span>{stepText}</span>
            <div className="ml-auto flex gap-3">
              <button type="button" className={pane === "preview" ? "text-ink" : ""} onClick={() => setPane("preview")}>
                预览
              </button>
              <button type="button" className={pane === "code" ? "text-ink" : ""} onClick={() => setPane("code")}>
                代码
              </button>
            </div>
          </div>
          <div className="min-h-0 flex-1">
            {pane === "preview" ? (
              <PreviewPane
                projectId={project.id}
                html={project.html}
                previewState={project.preview_state}
                requirements={project.requirements}
                probeRef={probeRef}
                onStateError={setError}
              />
            ) : (
              <div className="flex h-full min-h-[320px] flex-col">
                <div className="flex gap-4 border-b border-[#e7e7e7] bg-white px-4">
                  {project.files.map((file) => (
                    <button
                      key={file.path}
                      type="button"
                      onClick={() => setFilePath(file.path)}
                      className={`h-10 text-sm ${file.path === activeFile?.path ? "border-b-2 border-ink" : "text-[#6b7280]"}`}
                    >
                      {file.path}
                    </button>
                  ))}
                </div>
                <pre className="min-h-0 flex-1 overflow-auto bg-[#1e1e1e] p-4 font-mono text-[13px] leading-6 text-[#f4efe6]">
                  {activeFile?.content || "还没有文件"}
                </pre>
              </div>
            )}
          </div>
          <div className="h-28 shrink-0 overflow-auto border-t border-[#111] bg-[#1e1e1e] px-3 py-2 font-mono text-xs leading-5 text-[#d4d4d4]">
            {consoleLines.length ? consoleLines.map((line) => <p key={line}>{line}</p>) : <p className="text-[#9ca3af]">控制台</p>}
          </div>
        </section>
      </div>
    </div>
  );
}
