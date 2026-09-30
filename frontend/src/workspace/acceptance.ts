import type { AcceptanceResult, Check, Requirement, SetupStep } from "../lib/types";

async function prepare(doc: Document, steps: SetupStep[]) {
  if (steps.length > 12) throw new Error("前置步骤超过 12 项");
  const win = doc.defaultView;
  if (!win) throw new Error("预览窗口不可用");
  for (const [index, step] of steps.entries()) {
    const el = await waitFor(doc, step.selector);
    if (!el) throw new Error(`前置步骤 ${index + 1} 找不到 ${step.selector}`);
    if (el.matches(":disabled")) throw new Error(`前置步骤 ${index + 1} 的控件不可用`);
    if (step.action === "fill") {
      if (!el.matches("input,textarea,select")) throw new Error(`前置步骤 ${index + 1} 需要输入控件`);
      const input = el as HTMLInputElement;
      if (input.readOnly || ["file", "checkbox", "radio"].includes(input.type)) throw new Error("该控件不支持文本填入");
      const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(input), "value")?.set;
      if (!setter) throw new Error("输入控件缺少原生 value setter");
      setter.call(input, step.value);
      const EventConstructor = doc.createEvent("Event");
      EventConstructor.initEvent("input", true, false);
      input.dispatchEvent(EventConstructor);
      const changed = doc.createEvent("Event"); changed.initEvent("change", true, false);
      input.dispatchEvent(changed);
    } else if (step.action === "click") {
      (el as HTMLElement).click();
    } else if (step.action === "press") {
      (el as HTMLElement).focus();
      for (const type of ["keydown", "keyup"]) {
        const Keyboard = (win as Window & typeof globalThis).KeyboardEvent;
        const event = new Keyboard(type, { key: step.key, bubbles: true, cancelable: true });
        el.dispatchEvent(event);
      }
    } else throw new Error("未知前置操作");
    await sleep(0);
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function visibleWithinPreview(doc: Document, element: Element): boolean {
  // The preview tab can be hidden while the contract tab runs checks. Test
  // visibility inside its document, independently of the host tab's layout.
  for (let current: Element | null = element; current; current = current.parentElement) {
    const css = doc.defaultView?.getComputedStyle(current);
    if (current.hasAttribute("hidden") || css?.display === "none" || css?.visibility === "hidden") return false;
  }
  return true;
}

/** Poll for a selector so `flow` checks tolerate async re-renders. */
async function waitFor(doc: Document, selector: string, timeout = 1500, visible = false): Promise<Element | null> {
  const deadline = Date.now() + timeout;
  for (;;) {
    let found: Element | null;
    try { found = doc.querySelector(selector); }
    catch { throw new Error(`选择器无效：${selector}`); }
    if (found && (!visible || visibleWithinPreview(doc, found))) return found;
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
    let text = (el.textContent ?? "").replace(/\s+/g, " ").trim();
    const deadline = Date.now() + 1500;
    while (!text.includes(check.contains) && Date.now() < deadline) {
      await sleep(60);
      text = (doc.querySelector(check.selector)?.textContent ?? "").replace(/\s+/g, " ").trim();
    }
    return text.includes(check.contains)
      ? { passed: true, note: `包含「${check.contains}」` }
      : {
          passed: false,
          note: `未包含「${check.contains}」，实际是「${text.slice(0, 60)}」`,
        };
  }

  // flow: click, let the page settle, then assert the follow-up appears.
  await prepare(doc, check.setup ?? []);
  const { el, error } = query(doc, check.selector);
  if (error) return { passed: false, note: error };
  if (!el) return { passed: false, note: `点不到 ${check.selector}` };
  if (el.matches(":disabled")) return { passed: false, note: `${check.selector} 不可点击，请检查前置输入` };
  try {
    (el as HTMLElement).click();
  } catch {
    return { passed: false, note: `${check.selector} 无法点击` };
  }
  await sleep(0);
  const appeared = await waitFor(doc, check.expect, 1500, true);
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
      let outcome;
      try { outcome = await runCheck(doc, requirement.checks[index]); }
      catch (error) { outcome = { passed: false, note: error instanceof Error ? error.message : "验收执行失败" }; }
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
      return `${check.setup?.length ? `先完成 ${check.setup.length} 个前置步骤；` : ""}点击 ${check.selector} 后出现 ${check.expect}`;
    default:
      return "未知检查";
  }
}

export function countChecks(requirements: Requirement[]): number {
  return requirements.reduce((total, requirement) => total + requirement.checks.length, 0);
}
