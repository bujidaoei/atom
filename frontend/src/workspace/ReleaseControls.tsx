import { useState } from "react";
import { api, ApiError, errorMessage } from "../lib/api";
import type { ProjectDetail, VerifiedPublication, VerificationStatus, PublicationSnapshot } from "../lib/types";
import { Button } from "../components/ui/Button";
import { SelectField, TextField } from "../components/ui/Field";

type PublishCommand = Parameters<typeof api.publishVerifiedRelease>[1];
type RestoreCommand = Parameters<typeof api.restorePublication>[2];
type Pending =
  | { kind: "reserve"; requestId: string; revisionId: string }
  | { kind: "publish"; command: PublishCommand }
  | { kind: "restore"; releaseId: string; command: RestoreCommand }
  | { kind: "withdraw"; releaseId: string; commandId: string; expectedGeneration: number };
const ID = /^[0-9a-f]{32}$/;
const SLUG = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const operationId = () => Array.from(crypto.getRandomValues(new Uint8Array(16)), value => value.toString(16).padStart(2, "0")).join("");
const storageKey = (project: string) => `atom.release.pending.${project}`;

function readPending(project: string): Pending | null {
  const raw = sessionStorage.getItem(storageKey(project));
  if (!raw) return null;
  const item = JSON.parse(raw);
  const id = (value: unknown) => typeof value === "string" && ID.test(value);
  const generation = (value: unknown) => Number.isSafeInteger(value) && Number(value) >= 0;
  const revision = (value: unknown) => typeof value === "string" && value.length > 0;
  if (item?.kind === "reserve" && id(item.requestId) && revision(item.revisionId)) return item;
  if (item?.kind === "withdraw" && id(item.releaseId) && id(item.commandId) && generation(item.expectedGeneration)) return item;
  const c = item?.command;
  if (!c || !generation(c.expectedGeneration) || !revision(c.expectedRevision)) throw new Error("invalid_pending");
  if (item.kind === "publish" && id(c.releaseId) && (c.verificationId === undefined || id(c.verificationId))
      && ["owner", "public"].includes(c.audience) && typeof c.slug === "string" && SLUG.test(c.slug) && c.slug.length <= 63) return item;
  if (item.kind === "restore" && id(item.releaseId) && id(c.commandId) && id(c.newReleaseId) && id(c.sourceReleaseId)) return item;
  throw new Error("invalid_pending");
}

export function ReleaseControls({ project, publication, latest, policy, restore, onCancelRestore, onRefresh }: {
  project: ProjectDetail; publication: VerifiedPublication | null; latest: VerificationStatus | null;
  policy: "advisory" | "required"; restore: PublicationSnapshot | null; onCancelRestore: () => void; onRefresh: () => void;
}) {
  const [initial] = useState(() => { try { return { pending: readPending(project.id), blocked: false }; } catch { return { pending: null, blocked: true }; } });
  const [pending, setPending] = useState<Pending | null>(initial.pending);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [audience, setAudience] = useState<"owner" | "public">(publication?.audience ?? "public");
  const [slug, setSlug] = useState(publication?.slug ?? `project-${project.id.slice(0, 12).replace(/[^a-z0-9]/g, "")}`);
  const [withdraw, setWithdraw] = useState(false);
  const current = latest?.revisionId === project.revisionId ? latest : null;
  const verified = current?.state === "passed" && Boolean(current.total) && current.passed === current.total;
  const effectiveSlug = publication?.slug ?? slug;
  const mayPublish = project.status === "ready" && Boolean(project.revisionId) && (policy === "advisory" || verified);
  const locked = busy || Boolean(pending) || initial.blocked;

  function clear() {
    try { sessionStorage.removeItem(storageKey(project.id)); } catch { /* Replay remains idempotent if tab storage fails. */ }
    setPending(null); onCancelRestore(); setWithdraw(false); onRefresh();
  }
  async function send(command: Pending) {
    setBusy(true); setMessage(null);
    try {
      if (command.kind === "reserve") {
        const result = await api.reserveVerification(project.id, command.requestId);
        if (result.requestId !== command.requestId || result.revisionId !== command.revisionId) throw new Error("检查版本暂时无法确认");
        if (result.state === "reserved") await api.runVerification(project.id, result.requestId);
      } else if (command.kind === "publish") {
        const result = await api.publishVerifiedRelease(project.id, command.command);
        if (result.releaseId !== command.command.releaseId || result.generation !== command.command.expectedGeneration + 1) throw new Error("发布结果暂时无法确认");
      } else if (command.kind === "restore") {
        const result = await api.restorePublication(project.id, command.releaseId, command.command);
        if (result.releaseId !== command.command.newReleaseId || result.generation !== command.command.expectedGeneration + 1) throw new Error("恢复结果暂时无法确认");
      } else {
        const result = await api.unpublishVerifiedRelease(project.id, command.releaseId, { commandId: command.commandId, expectedGeneration: command.expectedGeneration });
        if (result.commandId !== command.commandId || result.generation !== command.expectedGeneration + 1) throw new Error("停止发布的结果暂时无法确认");
      }
      clear();
    } catch (failure) {
      if (failure instanceof ApiError && [400, 401, 403, 404, 409, 413, 422].includes(failure.status)) {
        try { sessionStorage.removeItem(storageKey(project.id)); } catch { /* The original request is safe to replay. */ }
        setPending(null);
        setMessage(`操作未完成：${failure.message}。请刷新后重试。`);
      } else setMessage(`结果暂时无法确认：${errorMessage(failure)}。可以安全重试本次操作。`);
    } finally { setBusy(false); }
  }
  function start(command: Pending) {
    if (locked) return;
    try { sessionStorage.setItem(storageKey(project.id), JSON.stringify(command)); setPending(command); }
    catch { setMessage("浏览器无法保存本次操作，请启用会话存储后重试。"); return; }
    void send(command);
  }
  function check() {
    if (project.revisionId) start({ kind: "reserve", requestId: current?.state === "reserved" ? current.requestId : operationId(), revisionId: project.revisionId });
  }

  return <section className="space-y-m rounded-xl border border-neutral-12 bg-base-default p-l" aria-label="发布操作">
    {initial.blocked ? <p role="alert" className="text-sm text-danger-strong">浏览器中保存的操作无法读取，请保留此标签页并联系管理员核对发布历史。</p> : null}
    {pending ? <div role="status" className="space-y-s rounded-lg bg-neutral-8 p-m text-sm"><p>上次操作的结果尚未确认。重试会继续同一次操作，不会重复创建版本。</p>
      <Button size="sm" loading={busy} onClick={() => void send(pending)}>重试本次操作</Button></div> : null}
    {message ? <p role="alert" className="text-sm text-danger-strong">{message}</p> : null}
    {restore && publication ? <div className="space-y-m rounded-lg bg-neutral-8 p-m" role="region" aria-label="确认恢复">
      <h3 className="font-medium">恢复到版本 {restore.version}？</h3>
      <p className="text-sm text-neutral-60">网站将切换到这个快照，{restore.audience === "public" ? "所有人可访问" : "仅自己可见"}。当前草稿保持不变，本次恢复也会保存在历史中。</p>
      <div className="flex gap-s"><Button size="sm" disabled={locked || !project.revisionId} onClick={() => {
        if (!project.revisionId) return;
        start({ kind: "restore", releaseId: publication.releaseId, command: { commandId: operationId(), newReleaseId: operationId(), sourceReleaseId: restore.releaseId, expectedRevision: project.revisionId, expectedGeneration: publication.generation } });
      }}>确认恢复</Button><Button size="sm" variant="secondary" disabled={busy} onClick={onCancelRestore}>取消</Button></div>
    </div> : null}
    <div><h3 className="font-medium text-neutral-95">{publication?.live ? "发布更新" : "发布网站"}</h3>
      <p className="mt-xs text-sm text-neutral-60">{policy === "advisory" ? "功能检查可按需运行，不影响发布。每次发布都会保留快照。" : "此项目启用了发布前检查，需要检查通过后发布。"}</p></div>
    <div className="grid gap-m sm:grid-cols-2">
      <SelectField label="谁可以访问" value={audience} disabled={locked} onChange={event => setAudience(event.target.value as "owner" | "public")}>
        <option value="public">所有人</option><option value="owner">仅自己</option>
      </SelectField>
      <TextField label="网站链接名称" value={effectiveSlug} maxLength={63} disabled={Boolean(publication) || locked}
        error={!SLUG.test(effectiveSlug) ? "使用小写英文字母、数字或连字符。" : null} onChange={event => setSlug(event.target.value)} />
    </div>
    <Button size="sm" loading={busy} disabled={locked || !mayPublish || !SLUG.test(effectiveSlug) || effectiveSlug.length > 63} onClick={() => {
      if (!project.revisionId) return;
      start({ kind: "publish", command: { releaseId: operationId(), expectedRevision: project.revisionId, expectedGeneration: publication?.generation ?? 0,
        audience, slug: effectiveSlug, ...(policy === "required" && current ? { verificationId: current.requestId } : {}) } });
    }}>{publication?.live ? "发布更新" : "发布网站"}</Button>
    {project.status !== "ready" ? <p role="status" className="text-sm text-neutral-60">请等待网页生成完成后发布。</p> : null}
    {policy === "required" ? <div className="space-y-s border-t border-neutral-12 pt-m">
      <p className="text-sm text-neutral-60">{verified ? "当前版本已通过检查。" : current?.state === "running" ? "功能检查进行中…" : "当前版本还需要通过功能检查。"}</p>
      <Button size="sm" variant="secondary" disabled={locked || project.status !== "ready" || current?.state === "running"} onClick={() => void check()}>检查功能</Button>
    </div> : null}
    {publication?.live ? <div className="border-t border-neutral-12 pt-m">
      {!withdraw ? <Button size="sm" variant="secondary" disabled={locked} onClick={() => setWithdraw(true)}>停止发布</Button> : <div className="space-y-s">
        <p className="text-sm text-neutral-60">停止后，公开链接将无法访问。历史快照会保留。</p><div className="flex gap-s">
          <Button size="sm" variant="danger" disabled={locked} onClick={() => start({ kind: "withdraw", releaseId: publication.releaseId, commandId: operationId(), expectedGeneration: publication.generation })}>确认停止发布</Button>
          <Button size="sm" variant="secondary" onClick={() => setWithdraw(false)}>取消</Button></div></div>}
    </div> : null}
  </section>;
}
