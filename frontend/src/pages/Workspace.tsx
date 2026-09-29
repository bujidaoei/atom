import { FormEvent, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, readError } from "../api";
import type { Project, RuntimeResult } from "../types";
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

const people = [
  { id: "mike", name: "Mike", job: "带队" },
  { id: "iris", name: "Iris", job: "研究" },
  { id: "emma", name: "Emma", job: "契约" },
  { id: "bob", name: "Bob", job: "结构" },
  { id: "alex", name: "Alex", job: "工程" },
] as const;

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
    if (!text) return;
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

  return (
    <div className="flex min-h-screen flex-col lg:h-screen">
      <header className="flex h-14 shrink-0 items-center gap-4 border-b border-line px-4">
        <Wordmark to="/app" />
        <h1 className="truncate text-sm font-medium">{project.name}</h1>
        <span className="hidden items-center gap-2 text-sm text-muted sm:inline-flex">
          <StatusDot tone={project.status === "error" ? "bad" : working ? "work" : project.status === "ready" ? "ok" : "wait"} />
          {statusLabel[project.status] || project.status}
        </span>
        {project.contract_locked ? (
          <span className="hidden font-mono text-xs text-muted md:inline">契约 v{project.contract_version} 已锁定</span>
        ) : null}
        <div className="ml-auto flex items-center gap-2">
          <button
            type="button"
            className={`h-8 rounded-lg px-3 text-sm ${pane === "preview" ? "bg-ink text-paper" : "text-muted"}`}
            onClick={() => setPane("preview")}
          >
            预览
          </button>
          <button
            type="button"
            className={`h-8 rounded-lg px-3 text-sm ${pane === "code" ? "bg-ink text-paper" : "text-muted"}`}
            onClick={() => setPane("code")}
          >
            代码
          </button>
          <Link to="/app/settings" className="px-2 text-sm text-muted hover:text-ink">
            网关
          </Link>
        </div>
      </header>

      <div className="grid lg:min-h-0 lg:flex-1 lg:grid-cols-[280px_minmax(0,1fr)_minmax(320px,0.95fr)]">
        <aside className="flex flex-col border-b border-line lg:min-h-0 lg:border-b-0 lg:border-r">
          <div className="border-b border-line px-4 py-4">
            <p className="text-xs text-muted">小队</p>
            <ul className="mt-3 space-y-3">
              {people.map((person) => {
                const note =
                  person.id === "mike"
                    ? project.lead_note
                    : person.id === "iris"
                      ? project.research_note
                      : person.id === "bob"
                        ? project.architecture_note
                        : person.id === "alex"
                          ? project.html
                            ? "页面已经写进项目"
                            : ""
                          : project.requirements.length
                            ? `${project.requirements.length} 条，${project.contract_locked ? "已锁定" : "等你确认"}`
                            : "";
                return (
                  <li key={person.id}>
                    <div className="flex items-baseline justify-between gap-3">
                      <span className="text-sm">
                        {person.name}
                        <span className="ml-2 text-xs text-muted">{person.job}</span>
                      </span>
                      <StatusDot tone={note ? "ok" : working ? "work" : "wait"} />
                    </div>
                    {note ? <p className="mt-1 line-clamp-3 text-xs leading-5 text-muted">{note}</p> : null}
                  </li>
                );
              })}
            </ul>
          </div>
          <div className="px-4 py-4 lg:min-h-0 lg:flex-1 lg:overflow-auto">
            <div className="flex items-baseline justify-between">
              <p className="text-xs text-muted">契约</p>
              {project.latest_acceptance ? (
                <p className="font-mono text-xs text-muted">
                  {project.latest_acceptance.passed}/{project.latest_acceptance.total}
                </p>
              ) : null}
            </div>
            {project.requirements.length === 0 ? (
              <p className="mt-3 text-sm text-muted">{working ? "正在写" : "还没有"}</p>
            ) : (
              <ul className="mt-3 divide-y divide-line border-y border-line">
                {project.requirements.map((item) => {
                  const result = acceptance.get(item.key);
                  return (
                    <li key={item.key} className="py-3">
                      <div className="flex items-start gap-2">
                        <span className="mt-1">
                          <StatusDot tone={result ? (result.ok ? "ok" : "bad") : "wait"} />
                        </span>
                        <div>
                          <p className="text-sm">
                            <span className="mr-2 font-mono text-xs text-muted">{item.key}</span>
                            {item.title}
                          </p>
                          <p className="mt-1 text-xs leading-5 text-muted">
                            {item.priority === "must" ? "必须" : "可以稍后"}
                            {item.detail ? ` · ${item.detail}` : ""}
                          </p>
                          {result && !result.ok ? (
                            <p className="mt-1 text-xs leading-5 text-clay">
                              {result.checks.find((check) => !check.ok)?.detail}
                            </p>
                          ) : null}
                        </div>
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
          <div className="border-t border-line p-4">
            <Button onClick={accept} disabled={!project.html || busy !== ""} className="w-full">
              {busy === "accept" ? "正在验收" : "跑验收"}
            </Button>
            <p className="mt-2 text-xs leading-5 text-muted">对照契约检查首屏，并在预览里真正点一次。</p>
          </div>
        </aside>

        <section className="flex min-h-[360px] flex-col border-b border-line lg:min-h-0 lg:border-b-0 lg:border-r">
          <div ref={logRef} className="px-5 lg:min-h-0 lg:flex-1 lg:overflow-auto">
            <p className="border-b border-line py-4 text-sm leading-6 text-muted">{project.prompt}</p>
            {project.messages.length === 0 && working ? (
              <p className="flex items-center gap-2 py-4 text-sm text-muted">
                <StatusDot tone="work" />
                正在把想法写成契约
              </p>
            ) : null}
            {project.messages.map((message) => (
              <article key={message.id} className="border-b border-line py-4">
                <p className="text-xs text-muted">{roleLabel[message.role] || message.role}</p>
                <p className="mt-1 whitespace-pre-wrap text-sm leading-6">{message.content}</p>
              </article>
            ))}
            {project.status === "building" || busy === "build" || busy === "revise" ? (
              <p className="flex items-center gap-2 py-4 text-sm text-muted">
                <StatusDot tone="work" />
                工程师正在改页面
              </p>
            ) : null}
          </div>

          <div className="border-t border-line p-4">
            {error ? <p className="mb-3 text-sm text-clay">{error}</p> : null}
            {project.pending_amendment ? (
              <div className="mb-3 rounded-lg border border-line bg-raised p-3">
                <p className="text-sm">这会改掉已锁定的契约</p>
                <p className="mt-1 text-sm leading-6 text-muted">{project.pending_amendment.reason}</p>
                <ul className="mt-2 space-y-1 text-sm">
                  {(project.pending_amendment.requirements || []).map((item) => (
                    <li key={item.key}>
                      <span className="mr-2 font-mono text-xs text-muted">{item.key}</span>
                      {item.title}
                    </li>
                  ))}
                </ul>
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
              <div className="flex flex-wrap gap-2">
                <Button onClick={() => run("build", () => api.build(id))} disabled={busy !== ""}>
                  {busy === "build" ? "正在构建" : "锁定并构建"}
                </Button>
                <Button variant="line" onClick={() => run("plan", () => api.plan(id))} disabled={busy !== ""}>
                  重写契约
                </Button>
              </div>
            ) : null}
            {project.contract_locked ? (
              <form onSubmit={send} className="flex items-end gap-2">
                <label className="min-w-0 flex-1">
                  <span className="sr-only">修改意见</span>
                  <textarea
                    value={instruction}
                    onChange={(event) => setInstruction(event.target.value)}
                    rows={2}
                    placeholder="想改哪里。推翻已锁定的条目时，会先请你确认。"
                    className="w-full resize-none rounded-lg border border-line bg-raised px-3 py-2 text-sm leading-6"
                    onKeyDown={(event) => {
                      if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
                        event.preventDefault();
                        event.currentTarget.form?.requestSubmit();
                      }
                    }}
                  />
                </label>
                <Button type="submit" disabled={busy !== "" || !instruction.trim()}>
                  发送
                </Button>
              </form>
            ) : null}
          </div>
        </section>

        <section className="min-h-[480px] bg-raised lg:min-h-0">
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
            <div className="flex h-full min-h-[480px] flex-col lg:min-h-0">
              <div className="flex gap-4 border-b border-line px-4">
                {project.files.map((file) => (
                  <button
                    key={file.path}
                    type="button"
                    onClick={() => setFilePath(file.path)}
                    className={`h-10 text-sm ${file.path === activeFile?.path ? "border-b-2 border-ink" : "text-muted"}`}
                  >
                    {file.path}
                  </button>
                ))}
              </div>
              <pre className="min-h-0 flex-1 overflow-auto bg-[#241f1b] p-4 font-mono text-[13px] leading-6 text-[#f4efe6]">
                {activeFile?.content || "还没有文件"}
              </pre>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
