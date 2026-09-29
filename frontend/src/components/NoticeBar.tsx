import { useState } from "react";
import { Icon } from "./ui/Icon";

const DISMISS_KEY = "atom-notice-dismissed";

/** The closable notice pill Atoms keeps pinned at the top of the marketing page. */
export function NoticeBar() {
  const [dismissed, setDismissed] = useState(() => {
    try {
      return localStorage.getItem(DISMISS_KEY) === "1";
    } catch {
      return false;
    }
  });

  if (dismissed) return null;

  return (
    <div className="flex justify-center px-l pt-l">
      <div className="hairline flex max-w-full items-center gap-s rounded-full border-neutral-20 bg-base-tertiary px-m py-[5px] text-sm shadow-flat">
        <span className="rounded-full bg-brand-alpha-strong px-s py-[1px] text-xs font-medium text-brand-text">
          Demo
        </span>
        <span className="min-w-0 truncate text-neutral-80">
          5 位 agent 已上线，Sarah / Adrian / David 还在路上
        </span>
        <button
          type="button"
          onClick={() => {
            setDismissed(true);
            try {
              localStorage.setItem(DISMISS_KEY, "1");
            } catch {
              /* ignore */
            }
          }}
          aria-label="关闭提示"
          className="-mr-xxs ml-xxs inline-flex h-5 w-5 items-center justify-center rounded-full text-neutral-60 transition-colors duration-ui ease-ui hover:bg-neutral-12 hover:text-neutral-95 active:bg-neutral-16"
        >
          <Icon name="close" size={12} />
        </button>
      </div>
    </div>
  );
}
