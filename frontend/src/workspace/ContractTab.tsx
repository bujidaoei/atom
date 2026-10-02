import { useMemo, useState } from "react";
import { AgentAvatar } from "../components/AgentAvatar";
import { Button } from "../components/ui/Button";
import { Icon } from "../components/ui/Icon";
import { TextAreaField } from "../components/ui/Field";
import { EmptyState, ErrorState } from "../components/ui/States";
import { formatDateTime } from "../lib/format";
import type { AcceptanceRun, ProjectStatus, Requirement } from "../lib/types";
import { countChecks, describeCheck } from "./acceptance";

type ContractTabProps = {
  status: ProjectStatus;
  requirements: Requirement[];
  acceptance: AcceptanceRun | null;
  onApprove: (note: string) => Promise<void>;
  approving: boolean;
  approveError: string | null;
  onRunAcceptance: () => Promise<void>;
  acceptanceRunning: boolean;
  acceptanceError: string | null;
  canRunAcceptance: boolean;
};

export function ContractTab({
  status,
  requirements,
  acceptance,
  onApprove,
  approving,
  approveError,
  onRunAcceptance,
  acceptanceRunning,
  acceptanceError,
  canRunAcceptance,
}: ContractTabProps) {
  const [note, setNote] = useState("");
  const total = countChecks(requirements);

  const outcomes = useMemo(() => {
    const map = new Map<string, { passed: boolean; note: string }>();
    for (const result of acceptance?.results ?? []) {
      map.set(`${result.key}:${result.checkIndex}`, { passed: result.passed, note: result.note });
    }
    return map;
  }, [acceptance]);

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
      {status === "awaiting_approval" ? (
        <div className="sticky top-0 z-10 border-b-2 border-brand-line bg-brand-alpha-soft px-l py-l backdrop-blur-sm">
          <div className="mx-auto flex max-w-[720px] flex-col gap-m">
            <div className="flex items-start gap-s">
              <AgentAvatar role="emma" size="md" />
              <div>
                <p className="text-md font-medium text-neutral-95">
                  契约已就绪，等你点头 Alex 才动手
                </p>
                <p className="mt-xxs text-base text-neutral-80">
                  {requirements.length} 条需求 · {total} 项可机检的验收条件。确认后会消耗额度开始构建。
                </p>
              </div>
            </div>

            <TextAreaField
              label="顺手微调（可选）"
              placeholder="例如：顺便加个深色模式。"
              value={note}
              rows={2}
              onChange={(event) => setNote(event.target.value)}
              hint="这段话会作为补充说明一起交给 Alex。"
            />

            {approveError ? <ErrorState title="开始构建失败" message={approveError} compact /> : null}

            <div className="flex flex-wrap items-center gap-m">
              <Button size="lg" loading={approving} onClick={() => void onApprove(note.trim())}>
                开始构建
              </Button>
              <span className="text-sm text-neutral-60">
                不满意？在左侧对话里直接说，squad 会重新规划。
              </span>
            </div>
          </div>
        </div>
      ) : null}

      <div className="mx-auto flex max-w-[720px] flex-col gap-l p-l">
        <div className="flex flex-wrap items-center justify-between gap-m">
          <div>
            <h2 className="text-md font-medium text-neutral-95">需求与功能检查</h2>
            <p className="mt-xxs text-sm text-neutral-60">
              在预览中操作按钮、填写输入并检查结果，帮助你发现功能问题。
            </p>
          </div>
          <Button
            variant="secondary"
            onClick={() => void onRunAcceptance()}
            loading={acceptanceRunning}
            disabled={!canRunAcceptance}
            title={canRunAcceptance ? "在预览中执行全部检查" : "先构建出可预览的页面"}
          >
            <Icon name="check" size={14} />
            检查功能
          </Button>
        </div>

        {acceptanceError ? <ErrorState title="检查未完成" message={acceptanceError} compact /> : null}

        {acceptance ? (
          <div
            className={[
              "hairline flex flex-wrap items-center gap-m rounded-l px-l py-m",
              acceptance.passed === acceptance.total
                ? "border-success-edge bg-success-surface"
                : "border-danger-edge bg-danger-surface",
            ].join(" ")}
          >
            <p className="text-2xl font-medium tabular-nums text-neutral-95">
              {acceptance.passed}
              <span className="text-neutral-40"> / {acceptance.total}</span>
            </p>
            <div className="flex flex-col">
              {acceptanceError ? <p className="text-xs text-neutral-60">上次已保存的检查结果</p> : null}
              <p className="text-base font-medium text-neutral-95">
                {acceptance.passed === acceptance.total ? "功能检查通过" : "发现功能问题"}
              </p>
              <p className="text-sm text-neutral-60">{formatDateTime(acceptance.createdAt)}</p>
            </div>
            <div className="ml-auto flex h-[6px] w-[140px] overflow-hidden rounded-full bg-neutral-12">
              <span
                className="h-full bg-success transition-[width] duration-ui ease-ui"
                style={{
                  width: `${acceptance.total ? (acceptance.passed / acceptance.total) * 100 : 0}%`,
                }}
              />
            </div>
          </div>
        ) : null}

        {requirements.map((requirement, index) => (
          <article
            key={requirement.key}
            className="hairline rounded-l border-neutral-12 bg-base-tertiary"
          >
            <header className="flex items-start gap-s border-b border-neutral-8 px-l py-m">
              <span className="mt-[2px] font-mono text-xs text-neutral-40">
                {String(index + 1).padStart(2, "0")}
              </span>
              <div className="min-w-0 flex-1">
                <h3 className="text-md font-medium text-neutral-95">{requirement.title}</h3>
                <p className="mt-xxs text-base leading-5 text-neutral-60">{requirement.detail}</p>
              </div>
              <span className="shrink-0 rounded-full bg-neutral-8 px-s py-[2px] font-mono text-xs text-neutral-60">
                {requirement.key}
              </span>
            </header>

            <ul className="flex flex-col divide-y divide-neutral-8">
              {requirement.checks.length === 0 ? (
                <li className="px-l py-s text-sm text-neutral-40">这条需求没有可机检的条件。</li>
              ) : (
                requirement.checks.map((check, checkIndex) => {
                  const outcome = outcomes.get(`${requirement.key}:${checkIndex}`);
                  return (
                    <li key={checkIndex} className="flex items-start gap-s px-l py-s">
                      <span
                        className={[
                          "mt-[1px] flex h-4 w-4 shrink-0 items-center justify-center rounded-full",
                          outcome === undefined
                            ? "bg-neutral-12 text-neutral-40"
                            : outcome.passed
                              ? "bg-success-chip text-success-strong"
                              : "bg-danger-chip text-danger-strong",
                        ].join(" ")}
                      >
                        {outcome === undefined ? (
                          <span className="h-[4px] w-[4px] rounded-full bg-current" />
                        ) : (
                          <Icon name={outcome.passed ? "check" : "close"} size={11} />
                        )}
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="font-mono text-xs leading-5 text-neutral-80">
                          <span className="mr-xs rounded-full bg-neutral-8 px-xs py-[1px] text-neutral-60">
                            {check.type}
                          </span>
                          {describeCheck(check)}
                        </p>
                        {outcome?.note ? (
                          <p
                            className={`mt-xxs text-xs leading-4 ${
                              outcome.passed ? "text-neutral-40" : "text-danger-strong"
                            }`}
                          >
                            {outcome.note}
                          </p>
                        ) : null}
                      </div>
                    </li>
                  );
                })
              )}
            </ul>
          </article>
        ))}
      </div>
    </div>
  );
}
