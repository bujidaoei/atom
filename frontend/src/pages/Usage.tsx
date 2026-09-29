import { useEffect, useState } from "react";
import { Button } from "../components/ui/Button";
import { EmptyState, ErrorState, LoadingState, Panel } from "../components/ui/States";
import { api, errorMessage } from "../lib/api";
import { useAuth } from "../lib/auth";
import { formatDateTime, formatNumber } from "../lib/format";
import type { Usage } from "../lib/types";

const REASON_LABEL: Record<string, string> = {
  plan: "规划",
  build: "构建",
  revise: "修改",
  race: "竞速",
  signup: "注册赠送",
  grant: "额度发放",
  refund: "退回",
};

export function UsagePage() {
  const { setCredits } = useAuth();
  const [usage, setUsage] = useState<Usage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getUsage();
      setUsage(data);
      setCredits(data.credits);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    // setCredits is stable; loading once on mount is intentional.
  }, []);

  return (
    <div className="mx-auto flex max-w-[840px] flex-col gap-xl px-l py-xxl">
      <header className="flex flex-wrap items-end justify-between gap-m">
        <div className="flex flex-col gap-xxs">
          <h1 className="text-2xl font-medium text-neutral-95">额度</h1>
          <p className="text-base text-neutral-60">
            每次 agent 出手扣 1 credit，Race Mode 每个 heat 各扣 1。
          </p>
        </div>
        <Button variant="secondary" size="sm" onClick={() => void load()} loading={loading}>
          刷新
        </Button>
      </header>

      {loading && !usage ? (
        <LoadingState label="读取额度" />
      ) : error ? (
        <ErrorState message={error} onRetry={() => void load()} />
      ) : usage ? (
        <>
          <div className="grid grid-cols-2 gap-m lg:grid-cols-4">
            <Metric label="剩余 credits" value={formatNumber(usage.credits)} emphasis />
            <Metric label="已消耗" value={formatNumber(usage.spent)} />
            <Metric label="运行次数" value={formatNumber(usage.runs)} />
            <Metric
              label="Token 合计"
              value={formatNumber(usage.inputTokens + usage.outputTokens)}
              hint={`入 ${formatNumber(usage.inputTokens)} · 出 ${formatNumber(usage.outputTokens)}`}
            />
          </div>

          <Panel className="overflow-hidden">
            <div className="flex items-center justify-between border-b border-neutral-12 px-l py-m">
              <h2 className="text-md font-medium text-neutral-95">流水</h2>
              <span className="text-sm text-neutral-60">{usage.ledger.length} 条</span>
            </div>

            {usage.ledger.length === 0 ? (
              <EmptyState
                icon="gauge"
                compact
                title="还没有流水"
                description="开始一个项目后，每次 agent 出手都会记在这里。"
              />
            ) : (
              <table className="w-full border-collapse text-base">
                <caption className="sr-only">额度流水</caption>
                <thead>
                  <tr className="text-left text-sm text-neutral-60">
                    <th scope="col" className="px-l py-s font-medium">
                      时间
                    </th>
                    <th scope="col" className="px-l py-s font-medium">
                      原因
                    </th>
                    <th scope="col" className="px-l py-s text-right font-medium">
                      变动
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {usage.ledger.map((entry, index) => (
                    <tr
                      key={`${entry.at}-${index}`}
                      className="border-t border-neutral-8 transition-colors duration-ui ease-ui hover:bg-neutral-4"
                    >
                      <td className="whitespace-nowrap px-l py-s text-neutral-80">
                        {formatDateTime(entry.at)}
                      </td>
                      <td className="px-l py-s text-neutral-80">
                        {REASON_LABEL[entry.reason] ?? entry.reason}
                      </td>
                      <td
                        className={`px-l py-s text-right font-mono text-sm ${
                          entry.delta < 0 ? "text-neutral-95" : "text-success-strong"
                        }`}
                      >
                        {entry.delta > 0 ? `+${entry.delta}` : entry.delta}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Panel>
        </>
      ) : null}
    </div>
  );
}

function Metric({
  label,
  value,
  hint,
  emphasis = false,
}: {
  label: string;
  value: string;
  hint?: string;
  emphasis?: boolean;
}) {
  return (
    <Panel className="flex flex-col gap-xxs p-l">
      <p className="text-sm text-neutral-60">{label}</p>
      <p
        className={`font-medium tabular-nums ${
          emphasis ? "text-3xl text-brand-text" : "text-3xl text-neutral-95"
        }`}
      >
        {value}
      </p>
      {hint ? <p className="text-xs text-neutral-40">{hint}</p> : null}
    </Panel>
  );
}
