import { FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { PROMPT_KEY, api } from "../api";
import { useSession } from "../session";
import { Wordmark } from "../ui";

const examples = [
  "给街角咖啡馆做一个今日烘焙看板，店员能把卖完的标出来，刷新后还在",
  "给自由职业者做一个回款记录，能记下客户、金额和有没有到账",
  "做一个小面试表，记下候选人、时间和一句备注",
];

const specimen = [
  ["R1", "店员能把一款面包标成售罄", "必须"],
  ["R2", "刷新之后，售罄状态还在", "必须"],
  ["R3", "页头写着今天的日期", "必须"],
];

export function LandingPage() {
  const { user } = useSession();
  const navigate = useNavigate();
  const [prompt, setPrompt] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function start(event: FormEvent) {
    event.preventDefault();
    const text = prompt.trim();
    if (text.length < 4) {
      setError("再多写一句，小队才知道要做什么");
      return;
    }
    setError("");
    if (!user) {
      sessionStorage.setItem(PROMPT_KEY, text);
      navigate("/register");
      return;
    }
    setBusy(true);
    try {
      const project = await api.createProject(text);
      navigate(`/app/p/${project.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "没能创建项目");
      setBusy(false);
    }
  }

  return (
    <div className="min-h-screen">
      <header className="flex items-center justify-between px-5 py-5 md:px-10">
        <Wordmark />
        <nav className="flex items-center gap-5 text-sm">
          <a href="#how" className="text-muted hover:text-ink">
            怎么做
          </a>
          {user ? (
            <Link to="/app" className="hover:text-copper">
              工作台
            </Link>
          ) : (
            <>
              <Link to="/login" className="text-muted hover:text-ink">
                登录
              </Link>
              <Link to="/register">注册</Link>
            </>
          )}
        </nav>
      </header>

      <main className="mx-auto grid max-w-6xl items-start gap-14 px-5 pb-8 pt-6 md:grid-cols-[minmax(0,1.15fr)_minmax(280px,0.85fr)] md:px-10 md:pt-14">
        <div>
          <h1 className="font-display text-[clamp(3.25rem,7vw,6.25rem)] font-medium leading-[0.9] tracking-[-0.035em]">
            先把话说死，
            <br />
            再让它长成页面。
          </h1>
          <p className="mt-8 max-w-md text-[17px] leading-7 text-muted">
            描述一个小产品。研究员、产品经理和架构师先写一份能锁定的契约。你点头之后，工程师才动手。验收台按契约把页面点一遍。
          </p>
          <form className="mt-10 max-w-xl rounded-[24px] bg-white px-4 pb-3 pt-3 shadow-[0_10px_40px_rgba(15,23,42,0.08)]" onSubmit={start}>
            <label htmlFor="idea" className="sr-only">
              想做什么
            </label>
            <textarea
              id="idea"
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              rows={3}
              placeholder="告知小队你的需求"
              className="w-full resize-none bg-transparent text-[15px] leading-7 outline-none placeholder:text-[#9aa0a6]"
            />
            <div className="mt-2 flex items-center justify-between gap-3">
              <button
                type="button"
                aria-label="聚焦输入"
                onClick={(event) => event.currentTarget.closest("form")?.querySelector("textarea")?.focus()}
                className="flex h-8 w-8 items-center justify-center rounded-full border border-[#e5e7eb] text-lg leading-none text-[#6b7280]"
              >
                +
              </button>
              <button
                type="submit"
                disabled={busy}
                className="inline-flex h-10 items-center rounded-full bg-[#3b6cff] px-5 text-sm text-white disabled:opacity-50"
              >
                {busy ? "正在创建" : "开始 →"}
              </button>
            </div>
            {error ? <p className="mt-3 text-sm text-clay">{error}</p> : null}
          </form>
          <div className="mt-3 flex max-w-xl flex-wrap gap-2">
            {examples.map((example) => (
              <button
                key={example}
                type="button"
                onClick={() => setPrompt(example)}
                className="rounded-full border border-line bg-white px-3 py-1.5 text-left text-xs text-muted hover:border-ink/30 hover:text-ink"
              >
                {example.slice(0, 18)}…
              </button>
            ))}
          </div>
        </div>

        <aside className="rounded-xl border border-line bg-raised p-5 shadow-sheet md:mt-6" aria-label="契约界面示例">
          <div className="flex items-baseline justify-between gap-3">
            <p className="font-mono text-xs text-muted">界面示例 · 不是你的项目</p>
            <p className="text-xs text-muted">契约 v1</p>
          </div>
          <ul className="mt-5 divide-y divide-line border-y border-line">
            {specimen.map(([key, title, priority]) => (
              <li key={key} className="grid grid-cols-[auto_1fr_auto] items-baseline gap-3 py-3 text-sm">
                <span className="font-mono text-xs text-muted">{key}</span>
                <span>{title}</span>
                <span className="text-xs text-muted">{priority}</span>
              </li>
            ))}
          </ul>
          <p className="mt-4 text-sm leading-6 text-muted">
            锁定之后，页面上的按钮、文字和一次真实点击，都要能对上这些条目。
          </p>
        </aside>
      </main>

      <section id="how" className="mt-12 border-t border-line">
        <ol className="mx-auto grid max-w-6xl md:grid-cols-5">
          {[
            ["01", "写下想法", "谁用、做什么、数据要不要留下来。"],
            ["02", "小队写契约", "研究、范围和页面结构先落成文字。"],
            ["03", "你来锁定", "没点头之前，工程师不改页面。"],
            ["04", "生成页面", "一个能点的网页，预览在右边。"],
            ["05", "按契约验收", "缺按钮或点了没反应，会标出来。"],
          ].map(([index, title, body], position) => (
            <li
              key={index}
              className={`px-5 py-8 md:px-6 ${position ? "border-t border-line md:border-l md:border-t-0" : ""}`}
            >
              <p className="font-mono text-xs text-copper">{index}</p>
              <h2 className="mt-4 text-lg">{title}</h2>
              <p className="mt-2 text-sm leading-6 text-muted">{body}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className="border-t border-line">
        <div className="mx-auto max-w-6xl px-5 py-14 md:px-10">
          <h2 className="font-display text-4xl font-medium tracking-[-0.03em]">这个演示实际能做的事</h2>
          <ul className="mt-8 divide-y divide-line border-y border-line text-sm leading-6">
            <li className="grid gap-2 py-4 md:grid-cols-[180px_1fr]">
              <span>会留下来</span>
              <span className="text-muted">账号、项目、对话、契约、生成的页面，以及预览里改过的数据。</span>
            </li>
            <li className="grid gap-2 py-4 md:grid-cols-[180px_1fr]">
              <span>会拦住跑偏</span>
              <span className="text-muted">
                契约锁定后，如果新指令推翻已有条目，会先请你确认修订，再重新生成。
              </span>
            </li>
            <li className="grid gap-2 py-4 md:grid-cols-[180px_1fr]">
              <span>这次没做</span>
              <span className="text-muted">多人协作、支付、拖拽改版，以及把生成的小页面再发布成独立网站。</span>
            </li>
          </ul>
          <p className="mt-8 text-xs text-muted">Atom 是一个可运行的演示，不是 atoms.dev 官方产品。</p>
        </div>
      </section>
    </div>
  );
}
