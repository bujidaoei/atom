import { useState } from "react";
import { api, ApiError, errorMessage } from "../lib/api";
import type { ProjectDetail, VerifiedPublication, VerificationStatus } from "../lib/types";
import { Button } from "../components/ui/Button";
import { SelectField, TextField } from "../components/ui/Field";

type PublishCommand = {
  releaseId: string;
  verificationId: string;
  expectedRevision: string;
  expectedGeneration: number;
  audience: "owner" | "public";
  slug: string;
};
type Pending =
  | { kind: "reserve"; requestId: string; revisionId: string }
  | { kind: "publish"; command: PublishCommand }
  | { kind: "withdraw"; releaseId: string; commandId: string; expectedGeneration: number };

const ID = /^[0-9a-f]{32}$/;
const SLUG = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

function operationId(): string {
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), value => value.toString(16).padStart(2, "0")).join("");
}

function storageKey(projectId: string): string {
  return `atom.release.pending.${projectId}`;
}

function readPending(projectId: string): Pending | null {
  try {
    const raw = sessionStorage.getItem(storageKey(projectId));
    if (!raw) return null;
    const value: unknown = JSON.parse(raw);
    if (!value || typeof value !== "object") return null;
    const item = value as Record<string, unknown>;
    if (item.kind === "reserve" && typeof item.requestId === "string" && ID.test(item.requestId)
        && typeof item.revisionId === "string" && item.revisionId.length > 0) return item as Pending;
    if (item.kind === "publish" && item.command && typeof item.command === "object") {
      const command = item.command as Record<string, unknown>;
      if (typeof command.releaseId === "string" && ID.test(command.releaseId)
          && typeof command.verificationId === "string" && ID.test(command.verificationId)
          && typeof command.expectedRevision === "string" && command.expectedRevision.length > 0
          && Number.isSafeInteger(command.expectedGeneration) && Number(command.expectedGeneration) >= 0
          && (command.audience === "owner" || command.audience === "public")
          && typeof command.slug === "string" && SLUG.test(command.slug) && command.slug.length <= 63) {
        return item as Pending;
      }
    }
    if (item.kind === "withdraw" && typeof item.releaseId === "string" && ID.test(item.releaseId)
        && typeof item.commandId === "string" && ID.test(item.commandId)
        && Number.isSafeInteger(item.expectedGeneration) && Number(item.expectedGeneration) >= 1) return item as Pending;
  } catch {
    // A malformed or unavailable tab store never authorizes a new mutation.
  }
  return null;
}

export function ReleaseControls({ project, publication, latest, onRefresh }: {
  project: ProjectDetail;
  publication: VerifiedPublication | null;
  latest: VerificationStatus | null;
  onRefresh: () => void;
}) {
  const [pending, setPending] = useState<Pending | null>(() => readPending(project.id));
  const [storageBlocked] = useState(() => {
    try {
      return sessionStorage.getItem(storageKey(project.id)) !== null && readPending(project.id) === null;
    } catch { return true; }
  });
  const [retryAllowed, setRetryAllowed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [audience, setAudience] = useState<"owner" | "public">("owner");
  const [slug, setSlug] = useState(publication?.slug ?? `project-${project.id.slice(0, 12).replace(/[^a-z0-9]/g, "")}`);
  const [publishConfirmed, setPublishConfirmed] = useState(false);
  const [withdrawConfirmed, setWithdrawConfirmed] = useState(false);

  function save(command: Pending): boolean {
    if (storageBlocked) {
      setMessage("原命令身份无法读取；为避免重复执行，请联系管理员核对服务端账本。");
      return false;
    }
    try {
      sessionStorage.setItem(storageKey(project.id), JSON.stringify(command));
      setPending(command);
      setRetryAllowed(false);
      return true;
    } catch {
      setMessage("无法保存操作身份；请启用此标签页的会话存储后再操作。");
      return false;
    }
  }

  function clear() {
    try { sessionStorage.removeItem(storageKey(project.id)); } catch { /* the server result remains authoritative */ }
    setPending(null);
    setRetryAllowed(false);
    onRefresh();
  }

  async function reconcile() {
    if (!pending || busy) return;
    setBusy(true);
    setMessage(null);
    setRetryAllowed(false);
    try {
      if (pending.kind === "reserve") {
        try {
          const current = await api.getVerification(project.id, pending.requestId);
          if (current.requestId !== pending.requestId || current.revisionId !== pending.revisionId) {
            setMessage("验证账本身份与原请求不一致，请停止操作并联系管理员。");
            return;
          }
          clear();
          return;
        } catch (error) {
          if (!(error instanceof ApiError && error.status === 404)) throw error;
          setRetryAllowed(true);
          setMessage("账本尚无这次预约；可以使用同一请求编号重试。");
          return;
        }
      }
      const { publication: current } = await api.currentVerifiedRelease(project.id);
      if (pending.kind === "publish") {
        if (current?.releaseId === pending.command.releaseId
            && current.generation === pending.command.expectedGeneration + 1) {
          clear();
          return;
        }
        if ((current?.generation ?? 0) === pending.command.expectedGeneration) {
          setRetryAllowed(true);
          setMessage("账本尚未登记这次发布；可以使用同一发布编号重试。");
          return;
        }
      } else {
        if (current?.releaseId === pending.releaseId && !current.live
            && current.generation === pending.expectedGeneration + 1) {
          clear();
          return;
        }
        if (current?.releaseId === pending.releaseId && current.live
            && current.generation === pending.expectedGeneration) {
          setRetryAllowed(true);
          setMessage("线上指针尚未撤回；可以使用同一命令编号重试。");
          return;
        }
      }
      setMessage("账本已发生其他变化，不能重放旧命令。请联系管理员核对发布历史。");
    } catch (error) {
      setMessage(`结果仍无法确认：${errorMessage(error)}。请稍后再次查询。`);
    } finally {
      setBusy(false);
    }
  }

  async function send(command: Pending) {
    setBusy(true);
    setMessage(null);
    try {
      if (command.kind === "reserve") {
        const result = await api.reserveVerification(project.id, command.requestId);
        if (result.requestId !== command.requestId || result.revisionId !== command.revisionId) {
          throw new Error("验证服务返回了不匹配的请求身份");
        }
      } else if (command.kind === "publish") {
        const result = await api.publishVerifiedRelease(project.id, command.command);
        if (result.releaseId !== command.command.releaseId
            || result.generation !== command.command.expectedGeneration + 1) {
          throw new Error("发布服务返回了不匹配的版本身份");
        }
      } else {
        const result = await api.unpublishVerifiedRelease(project.id, command.releaseId, {
          commandId: command.commandId, expectedGeneration: command.expectedGeneration,
        });
        if (result.commandId !== command.commandId || result.releaseId !== command.releaseId
            || result.generation !== command.expectedGeneration + 1) {
          throw new Error("撤回服务返回了不匹配的命令身份");
        }
      }
      clear();
    } catch (error) {
      if (error instanceof ApiError && [400, 401, 403, 404, 409, 413, 422].includes(error.status)) {
        try { sessionStorage.removeItem(storageKey(project.id)); } catch { /* no server mutation was acknowledged */ }
        setPending(null);
        setRetryAllowed(false);
        setMessage(`服务端已拒绝该命令：${error.message}。请刷新状态后重新检查条件。`);
        return;
      }
      setRetryAllowed(false);
      setMessage(`请求结果未确认：${errorMessage(error)}。请先查询账本，再决定是否重试原命令。`);
    } finally {
      setBusy(false);
    }
  }

  const currentRevision = project.revisionId;
  const currentVerification = latest?.revisionId === currentRevision ? latest : null;
  const verificationRunning = currentVerification?.state === "running";
  const verificationReserved = currentVerification?.state === "reserved";
  const verified = Boolean(currentRevision && currentVerification?.state === "passed"
    && currentVerification.total !== null && currentVerification.total > 0
    && currentVerification.passed === currentVerification.total);
  const mayVerify = project.status === "ready" && Boolean(currentRevision) && !verificationRunning && !verificationReserved;
  const mayPublish = project.status === "ready" && verified
    && !(publication?.live && publication.verificationId === currentVerification?.requestId);
  const effectiveSlug = publication?.slug ?? slug;
  const validSlug = effectiveSlug.length <= 63 && SLUG.test(effectiveSlug);

  return <div className="space-y-m rounded-xl border border-neutral-12 bg-base-default p-l" aria-label="可信发布操作">
    <div>
      <h3 className="font-medium text-neutral-95">验证与发布</h3>
      <p className="mt-xs text-sm text-neutral-60">先验证当前修订，再选择受众。结果以服务端账本为准；浏览器断线不会自动重发命令。</p>
    </div>

    {storageBlocked ? <p role="alert" className="text-sm text-danger-strong">此标签页保存的发布命令已损坏或无法读取。操作已锁定，请联系管理员核对服务端账本。</p> : null}

    {pending ? <div role="status" className="space-y-s rounded-lg border border-neutral-20 bg-neutral-8 p-m text-sm text-neutral-95">
      <p>有一条{pending.kind === "reserve" ? "验证预约" : pending.kind === "publish" ? "发布" : "撤回"}命令尚未确认。保留原命令身份，先核对账本。</p>
      <div className="flex flex-wrap gap-s">
        <Button size="sm" variant="secondary" loading={busy} onClick={() => void reconcile()}>查询账本</Button>
        {retryAllowed ? <Button size="sm" loading={busy} onClick={() => void send(pending)}>重试原命令</Button> : null}
      </div>
    </div> : null}
    {message ? <p role="alert" className="text-sm text-danger-strong">{message}</p> : null}

    <div className="space-y-s border-t border-neutral-12 pt-m">
      <p className="text-sm text-neutral-80">{currentVerification
        ? `当前修订的验证：${currentVerification.state} · ${currentVerification.requestId}`
        : "当前修订尚无验证记录。"}</p>
      {verificationReserved ? <Button size="sm" variant="secondary" disabled={storageBlocked || Boolean(pending)} loading={busy}
        onClick={() => {
          if (!currentVerification) return;
          setBusy(true);
          setMessage(null);
          void api.runVerification(project.id, currentVerification.requestId)
            .then(() => onRefresh())
            .catch(error => setMessage(`验证执行结果未确认：${errorMessage(error)}。请刷新账本查询同一请求。`))
            .finally(() => setBusy(false));
        }}>执行已预约验证</Button> :
        <Button size="sm" variant="secondary" disabled={storageBlocked || Boolean(pending) || !mayVerify} loading={busy}
          onClick={() => {
            if (!currentRevision) return;
            const command: Pending = { kind: "reserve", requestId: operationId(), revisionId: currentRevision };
            if (save(command)) void send(command);
          }}>预约当前修订验证</Button>}
      {verificationRunning ? <p role="status" className="text-sm text-neutral-60">独立验证仍在运行。请刷新状态查看结果。</p> : null}
    </div>

    <div className="space-y-m border-t border-neutral-12 pt-m">
      <p className="text-sm text-neutral-80">{verified ? "当前修订已有完整通过的可信验证。" : "当前修订尚无可用于发布的通过结果。"}</p>
      <div className="grid gap-m sm:grid-cols-2">
        <SelectField label="发布受众" value={audience} disabled={Boolean(pending) || busy}
          onChange={event => { setAudience(event.target.value as "owner" | "public"); setPublishConfirmed(false); }}>
          <option value="owner">仅项目所有者</option>
          <option value="public">公开访问</option>
        </SelectField>
        <TextField label="发布短链接" value={effectiveSlug} maxLength={63} disabled={Boolean(publication) || Boolean(pending) || busy}
          error={slug && !validSlug ? "仅允许小写英文字母、数字和中间连字符，最多 63 字符。" : null}
          onChange={event => { setSlug(event.target.value); setPublishConfirmed(false); }} mono />
      </div>
      {publication ? <p className="text-sm text-neutral-60">此项目的发布短链接已固定；撤回后重新发布仍使用同一路径。</p> : null}
      <label className="flex items-start gap-s text-sm text-neutral-80">
        <input type="checkbox" checked={publishConfirmed} disabled={Boolean(pending) || busy}
          onChange={event => setPublishConfirmed(event.target.checked)} />
        <span>我确认将修订 {currentRevision ?? "—"} 发布给{audience === "public" ? "所有访问者" : "项目所有者"}；此操作会更新线上指针。</span>
      </label>
      <Button size="sm" disabled={storageBlocked || Boolean(pending) || !mayPublish || !validSlug || !publishConfirmed} loading={busy}
        onClick={() => {
          if (!currentRevision || !currentVerification || !mayPublish) return;
          const command: Pending = { kind: "publish", command: {
            releaseId: operationId(), verificationId: currentVerification.requestId,
            expectedRevision: currentRevision, expectedGeneration: publication?.generation ?? 0,
            audience, slug: effectiveSlug,
          } };
          if (save(command)) void send(command);
        }}>{publication?.live ? "更新可信发布" : "发布经验证版本"}</Button>
    </div>

    {publication?.live ? <div className="space-y-s border-t border-neutral-12 pt-m">
      <label className="flex items-start gap-s text-sm text-neutral-80">
        <input type="checkbox" checked={withdrawConfirmed} disabled={Boolean(pending) || busy}
          onChange={event => setWithdrawConfirmed(event.target.checked)} />
        <span>我确认撤回线上版本 {publication.releaseId}。现有公开链接将停止访问，历史制品保留。</span>
      </label>
      <Button size="sm" variant="danger" disabled={storageBlocked || Boolean(pending) || !withdrawConfirmed} loading={busy}
        onClick={() => {
          const command: Pending = { kind: "withdraw", releaseId: publication.releaseId,
            commandId: operationId(), expectedGeneration: publication.generation };
          if (save(command)) void send(command);
        }}>撤回线上版本</Button>
    </div> : null}
  </div>;
}
