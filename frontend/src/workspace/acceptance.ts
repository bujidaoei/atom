import type { AcceptanceResult, Check, Requirement } from "../lib/types";

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

/** Poll for a selector so `flow` checks tolerate async re-renders. */
async function waitFor(doc: Document, selector: string, timeout = 1500): Promise<Element | null> {
  const deadline = Date.now() + timeout;
  for (;;) {
    const found = doc.querySelector(selector);
    if (found) return found;
    if (Date.now() >= deadline) return null;
    await sleep(60);
  }
}

function query(doc: Document, selector: string): { el: Element | null; error: string | null } {
  try {
    return { el: doc.querySelector(selector), error: null };
  } catch {
    return { el: null, error: `选择器无效：${selector}` };
  }
}

async function runCheck(doc: Document, check: Check): Promise<{ passed: boolean; note: string }> {
  if (check.type === "exists") {
    const { el, error } = query(doc, check.selector);
    if (error) return { passed: false, note: error };
    return el
      ? { passed: true, note: `匹配到 ${check.selector}` }
      : { passed: false, note: `页面上找不到 ${check.selector}` };
  }

  if (check.type === "text") {
    const { el, error } = query(doc, check.selector);
    if (error) return { passed: false, note: error };
    if (!el) return { passed: false, note: `页面上找不到 ${check.selector}` };
    const text = (el.textContent ?? "").replace(/\s+/g, " ").trim();
    return text.includes(check.contains)
      ? { passed: true, note: `包含「${check.contains}」` }
      : {
          passed: false,
          note: `未包含「${check.contains}」，实际是「${text.slice(0, 60)}」`,
        };
  }

  // flow: click, let the page settle, then assert the follow-up appears.
  const { el, error } = query(doc, check.selector);
  if (error) return { passed: false, note: error };
  if (!el) return { passed: false, note: `点不到 ${check.selector}` };
  try {
    (el as HTMLElement).click();
  } catch {
    return { passed: false, note: `${check.selector} 无法点击` };
  }
  await sleep(0);
  const appeared = await waitFor(doc, check.expect);
  return appeared
    ? { passed: true, note: `点击后出现了 ${check.expect}` }
    : { passed: false, note: `点击后 1.5s 内没有出现 ${check.expect}` };
}

/** Executes Emma's checks for real, inside the same-origin preview document. */
export async function runAcceptance(
  doc: Document,
  requirements: Requirement[],
): Promise<AcceptanceResult[]> {
  const results: AcceptanceResult[] = [];
  for (const requirement of requirements) {
    for (let index = 0; index < requirement.checks.length; index += 1) {
      const outcome = await runCheck(doc, requirement.checks[index]);
      results.push({
        key: requirement.key,
        checkIndex: index,
        passed: outcome.passed,
        note: outcome.note,
      });
    }
  }
  return results;
}

export function describeCheck(check: Check): string {
  switch (check.type) {
    case "exists":
      return `存在 ${check.selector}`;
    case "text":
      return `${check.selector} 的文字包含「${check.contains}」`;
    case "flow":
      return `点击 ${check.selector} 后出现 ${check.expect}`;
    default:
      return "未知检查";
  }
}

export function countChecks(requirements: Requirement[]): number {
  return requirements.reduce((total, requirement) => total + requirement.checks.length, 0);
}
