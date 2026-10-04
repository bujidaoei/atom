import type { Requirement } from "../lib/types";
import { Icon } from "../components/ui/Icon";
import { describeCheck } from "./acceptance";

export function RequirementCards({ requirements, outcomes = new Map() }: {
  requirements: Requirement[];
  outcomes?: Map<string, { passed: boolean; note: string }>;
}) {
  return <div className="space-y-m">{requirements.map((requirement, index) => (
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
        ))}</div>;
}
