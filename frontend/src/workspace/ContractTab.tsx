import { useEffect, useMemo, useState } from "react";
import { AgentAvatar } from "../components/AgentAvatar";
import { Button } from "../components/ui/Button";
import { Icon } from "../components/ui/Icon";
import { TextAreaField } from "../components/ui/Field";
import { EmptyState, ErrorState } from "../components/ui/States";
import { formatDateTime } from "../lib/format";
import type { AcceptanceRun, ProjectStatus, Requirement, VerificationStatus } from "../lib/types";
import { api, errorMessage } from "../lib/api";
import type { ContractSnapshot } from "../lib/types";
import { ContractHistoryPanel, ContractDetails } from "./ContractHistoryPanel";
import { RequirementCards } from "./RequirementCards";
import { countChecks } from "./acceptance";

type ContractTabProps = {
  projectId: string;
  contract: ContractSnapshot | null;
  onChanged: () => Promise<void>;
  status: ProjectStatus;
  requirements: Requirement[];
  acceptance: AcceptanceRun | null;
  isolated: boolean;
  verification: VerificationStatus | null;
  onApprove: () => Promise<void>;
  approving: boolean;
  approveError: string | null;
  onRunAcceptance: () => Promise<void>;
  acceptanceRunning: boolean;
  acceptanceError: string | null;
  canRunAcceptance: boolean;
};

export function ContractTab({
  projectId, contract, onChanged,
  status,
  requirements,
  acceptance,
  isolated,
  verification,
  onApprove,
  approving,
  approveError,
  onRunAcceptance,
  acceptanceRunning,
  acceptanceError,
  canRunAcceptance,
}: ContractTabProps) {
  const draftKey = `atom.contract-draft.${projectId}`;
  const [note, setNote] = useState(() => {
    try { return sessionStorage.getItem(draftKey) ?? ""; } catch { return ""; }
  });
  useEffect(() => {
    try { if (note) sessionStorage.setItem(draftKey, note); else sessionStorage.removeItem(draftKey); }
    catch { /* Draft remains in component memory when browser storage is unavailable. */ }
  }, [draftKey, note]);
  const [refining, setRefining] = useState(false);
  const [refineError, setRefineError] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState<{ version: string | null; note: string } | null>(() => {
    try { return JSON.parse(sessionStorage.getItem(`${draftKey}.submitted`) ?? "null"); } catch { return null; }
  });
  useEffect(() => {
    try { if (submitted) sessionStorage.setItem(`${draftKey}.submitted`, JSON.stringify(submitted));
      else sessionStorage.removeItem(`${draftKey}.submitted`); } catch { /* Server head remains authoritative. */ }
  }, [draftKey, submitted]);
  const busy = refining || approving || status === "planning" || status === "building";
  const editable = requirements.length > 0 && !busy;
  useEffect(() => {
    if (submitted && contract && contract.id !== submitted.version && contract.note === submitted.note) {
      setNote(current => current.trim() === submitted.note ? "" : current);
      setSubmitted(null);
    }
  }, [contract, submitted]);
  async function refine() {
    const message = note.trim();
    if (!message || busy) return;
    setRefining(true); setRefineError(null);
    try {
      setSubmitted({ version: contract?.id ?? null, note: message });
      await api.refineContract(projectId, message, contract?.id ?? null);
      await onChanged();
    } catch (error) { setRefineError(errorMessage(error)); }
    finally { setRefining(false); }
  }
  const total = countChecks(requirements);

  const outcomes = useMemo(() => {
    const map = new Map<string, { passed: boolean; note: string }>();
    const results = isolated ? verification?.results : acceptance?.results;
    for (const result of results ?? []) {
      map.set(`${result.key}:${result.checkIndex}`, { passed: result.passed, note: result.note });
    }
    return map;
  }, [acceptance, isolated, verification]);
  const completed = isolated
    ? verification?.state === "passed" || verification?.state === "failed"
    : acceptance !== null;
  const passed = isolated ? verification?.passed : acceptance?.passed;
  const checked = isolated ? verification?.total : acceptance?.total;
  const checkedAt = isolated && verification?.completedAt
    ? new Date(verification.completedAt * 1000).toISOString()
    : acceptance?.createdAt;

  if (requirements.length === 0) {
    return (
      <EmptyState
        icon="contract"
        title="契约还没写好"
        description={
          status === "draft" || status === "planning"
            ? "Emma 正在把你的想法整理成可机检的需求，稍等一下。"
            : "这个项目还没有需求清单。可以在左侧让 squad 重新规划。"
        }
      />
    );
  }

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      {requirements.length > 0 ? (
        <div className="sticky top-0 z-10 border-b-2 border-brand-line bg-brand-alpha-soft px-l py-l backdrop-blur-sm">
          <div className="mx-auto flex max-w-[720px] flex-col gap-m">
            <div className="flex items-start gap-s">
              <AgentAvatar role="emma" size="md" />
              <div>
                <p className="text-md font-medium text-neutral-95">
                  {busy ? "正在处理，请稍候…" : "先微调契约，满意后再开始构建"}
                </p>
                <p className="mt-xxs text-base text-neutral-80">
                  {contract ? `版本 ${contract.version} · ` : ""}{requirements.length} 条需求 · {total} 项检查。微调会调用规划模型；开始构建后 Alex 才会修改代码。
                </p>
              </div>
            </div>

            <TextAreaField
              label="顺手微调（可选）"
              placeholder="例如：顺便加个深色模式。"
              value={note}
              rows={2}
              onChange={(event) => setNote(event.target.value)}
              hint="点击“继续微调”更新完整契约并保存快照，确认满意后再开始构建。"
              disabled={busy}
              maxLength={4000}
            />

            {refineError ? <ErrorState title="微调失败，原契约已保留" message={refineError} compact /> : null}
            {approveError ? <ErrorState title="开始构建失败" message={approveError} compact /> : null}

            <div className="flex flex-wrap items-center gap-m">
              <Button size="lg" variant="secondary" loading={refining || status === "planning"} disabled={!editable || !note.trim()} onClick={() => void refine()}>
                继续微调
              </Button>
              <Button size="lg" loading={approving} disabled={busy || Boolean(note.trim()) || status !== "awaiting_approval"} onClick={() => void onApprove()}>
                开始构建
              </Button>
              <span className="text-sm text-neutral-60">
                {note.trim() ? "有尚未提交的修改，请先继续微调。" : status === "ready" ? "可继续微调需求，再按新契约构建。" : "历史版本可在下方预览或恢复。"}
              </span>
            </div>
          </div>
        </div>
      ) : null}

      <div className="mx-auto flex max-w-[720px] flex-col gap-l p-l">
        {contract ? <ContractDetails document={contract.document} /> : null}
        <div className="flex flex-wrap items-center justify-between gap-m">
          <div>
            <h2 className="text-md font-medium text-neutral-95">需求与功能检查</h2>
            <p className="mt-xxs text-sm text-neutral-60">
              {isolated ? "在隔离浏览器中检查已保存的版本，帮助你发现功能问题。" :
                "在预览中操作按钮、填写输入并检查结果，帮助你发现功能问题。"}
            </p>
          </div>
          <Button
            variant="secondary"
            onClick={() => void onRunAcceptance()}
            loading={acceptanceRunning}
            disabled={!canRunAcceptance}
            title={canRunAcceptance ? "执行全部功能检查" : "先构建出可检查的页面"}
          >
            <Icon name="check" size={14} />
            检查功能
          </Button>
        </div>

        {acceptanceError ? <ErrorState title="检查未完成" message={acceptanceError} compact /> : null}

        {isolated && verification?.state === "running" ?
          <p role="status" className="text-sm text-neutral-60">隔离浏览器正在检查版本，结果会自动更新。</p> : null}
        {isolated && verification && ["cancelled", "timed_out", "unresolved", "expired"].includes(verification.state) ?
          <p role="status" className="text-sm text-neutral-60">这次检查没有完成，请重新运行；发布仍按项目策略处理。</p> : null}

        {completed && passed !== null && passed !== undefined && checked !== null && checked !== undefined ? (
          <div
            className={[
              "hairline flex flex-wrap items-center gap-m rounded-l px-l py-m",
              passed === checked
                ? "border-success-edge bg-success-surface"
                : "border-danger-edge bg-danger-surface",
            ].join(" ")}
          >
            <p className="text-2xl font-medium tabular-nums text-neutral-95">
              {passed}
              <span className="text-neutral-40"> / {checked}</span>
            </p>
            <div className="flex flex-col">
              {acceptanceError ? <p className="text-xs text-neutral-60">上次已保存的检查结果</p> : null}
              <p className="text-base font-medium text-neutral-95">
                {passed === checked ? "功能检查通过" : "发现功能问题"}
              </p>
              {checkedAt ? <p className="text-sm text-neutral-60">{formatDateTime(checkedAt)}</p> : null}
            </div>
            <div className="ml-auto flex h-[6px] w-[140px] overflow-hidden rounded-full bg-neutral-12">
              <span
                className="h-full bg-success transition-[width] duration-ui ease-ui"
                style={{
                  width: `${checked ? (passed / checked) * 100 : 0}%`,
                }}
              />
            </div>
          </div>
        ) : null}

        <RequirementCards requirements={requirements} outcomes={outcomes} />
        <ContractHistoryPanel projectId={projectId} contract={contract} status={status} disabled={busy || Boolean(note.trim())}
          onChanged={onChanged} />
      </div>
    </div>
  );
}
