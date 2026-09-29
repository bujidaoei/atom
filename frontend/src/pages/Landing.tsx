import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { AgentRow } from "../components/AgentRow";
import { Composer } from "../components/Composer";
import { Logo } from "../components/Logo";
import { NoticeBar } from "../components/NoticeBar";
import { ThemeToggle } from "../components/ThemeToggle";
import { Button, LinkButton } from "../components/ui/Button";
import { Icon } from "../components/ui/Icon";
import { AGENTS } from "../lib/agents";
import { stashPendingPrompt, useAuth } from "../lib/auth";
import { EXAMPLE_PROMPTS } from "../lib/examples";
import { useCreateProject } from "../lib/useCreateProject";

export function LandingPage() {
  const { user, ready } = useAuth();
  const navigate = useNavigate();
  const [prompt, setPrompt] = useState("");
  const { create, submitting, error } = useCreateProject();

  function handleSubmit() {
    const trimmed = prompt.trim();
    if (!trimmed) return;
    if (!user) {
      stashPendingPrompt(trimmed);
      navigate("/login", { state: { from: "/app" } });
      return;
    }
    void create(trimmed);
  }

  return (
    <div className="min-h-screen bg-base-default">
      <header className="sticky top-0 z-20 border-b border-neutral-12 bg-utilities-header backdrop-blur-md">
        <div className="mx-auto flex h-12 max-w-[1120px] items-center justify-between px-l">
          <Link to="/" className="rounded-m px-xxs py-xxs hover:bg-neutral-8" aria-label="Atom">
            <Logo />
          </Link>
          <nav className="flex items-center gap-s">
            <a
              href="#gallery"
              className="hidden rounded-full px-m py-xxs text-base text-neutral-80 transition-colors duration-ui ease-ui hover:bg-neutral-8 hover:text-neutral-95 sm:inline-block"
            >
              能构建什么
            </a>
            <ThemeToggle />
            {ready && user ? (
              <LinkButton to="/app" size="sm">
                进入工作台
              </LinkButton>
            ) : (
              <>
                <Link
                  to="/login"
                  className="rounded-full px-m py-xxs text-base text-neutral-80 transition-colors duration-ui ease-ui hover:bg-neutral-8 hover:text-neutral-95"
                >
                  登录
                </Link>
                <LinkButton to="/register" size="sm">
                  开始使用
                </LinkButton>
              </>
            )}
          </nav>
        </div>
      </header>

      <NoticeBar />

      <section className="mx-auto flex max-w-[1120px] flex-col items-center px-l pb-xxxl pt-xxl">
        <AgentRow size="lg" className="mb-xl" />

        <h1 className="text-center text-h1 font-medium tracking-[-0.01em] text-neutral-95">
          把想法变成可运行的产品
        </h1>
        <p className="mt-m max-w-[52ch] text-center text-md text-neutral-60">
          写一句话。Mike 拆需求，Iris 查资料，Emma 写成可机检的契约，Bob 定架构，
          你确认之后 Alex 才动手写代码。
        </p>

        <div className="mt-xl w-full max-w-[720px]">
          <Composer
            value={prompt}
            onChange={setPrompt}
            onSubmit={handleSubmit}
            submitting={submitting}
            error={error}
            submitLabel={user ? "开始构建" : "开始"}
            placeholder="例如：做一个记账小工具，可以按分类筛选并显示本月结余。"
            meta={
              user ? undefined : (
                <span className="hidden sm:inline">未登录也可以先写，提交时再登录</span>
              )
            }
          />
        </div>

        <ol className="mt-xxl grid w-full max-w-[880px] grid-cols-1 gap-s sm:grid-cols-3 lg:grid-cols-5">
          {AGENTS.map((agent, index) => (
            <li
              key={agent.role}
              className="hairline flex flex-col gap-xs rounded-l border-neutral-12 bg-base-tertiary p-m"
            >
              <div className="flex items-center gap-xs">
                <span className="text-xs font-medium text-neutral-40">
                  {String(index + 1).padStart(2, "0")}
                </span>
                <span className={`h-[6px] w-[6px] rounded-full ${agent.bg}`} aria-hidden="true" />
                <span className="text-sm font-medium text-neutral-95">{agent.name}</span>
              </div>
              <p className="text-sm leading-5 text-neutral-60">{agent.blurb}</p>
            </li>
          ))}
        </ol>
      </section>

      <section id="gallery" className="border-t border-neutral-12 bg-base-secondary">
        <div className="mx-auto max-w-[1120px] px-l py-xxxl">
          <div className="flex flex-wrap items-baseline justify-between gap-s">
            <h2 className="text-2xl font-medium text-neutral-95">能构建什么</h2>
            <p className="text-base text-neutral-60">点一个例子，它会填进上面的输入框。</p>
          </div>

          <div className="mt-xl grid grid-cols-1 gap-m sm:grid-cols-2 lg:grid-cols-3">
            {EXAMPLE_PROMPTS.map((example) => (
              <button
                key={example.title}
                type="button"
                onClick={() => {
                  setPrompt(example.prompt);
                  window.scrollTo({ top: 0, behavior: "smooth" });
                }}
                className="hairline group flex flex-col items-start gap-s rounded-l border-neutral-12 bg-base-tertiary p-l text-left transition-[border-color,box-shadow,transform] duration-ui ease-ui hover:-translate-y-[2px] hover:border-neutral-20 hover:shadow-flat focus-visible:-translate-y-[2px] active:translate-y-0"
              >
                <span className="rounded-full bg-neutral-12 px-s py-[2px] text-xs font-medium text-neutral-60">
                  {example.label}
                </span>
                <span className="text-md font-medium text-neutral-95">{example.title}</span>
                <span className="text-base leading-5 text-neutral-60">{example.prompt}</span>
                <span className="mt-auto inline-flex items-center gap-xxs pt-s text-sm text-brand-text opacity-0 transition-opacity duration-ui ease-ui group-hover:opacity-100 group-focus-visible:opacity-100">
                  填入输入框
                  <Icon name="arrow-right" size={13} />
                </span>
              </button>
            ))}
          </div>

          {!user && ready ? (
            <div className="mt-xxl flex flex-col items-center gap-m rounded-xl bg-base-tertiary p-xl hairline border-neutral-12">
              <p className="text-center text-md text-neutral-80">
                注册后每次 agent 出手扣 1 credit，新账号自带额度。
              </p>
              <Button onClick={() => navigate("/register")}>创建账户</Button>
            </div>
          ) : null}
        </div>
      </section>

      <footer className="bg-utilities-footer">
        <div className="mx-auto flex max-w-[1120px] flex-col gap-xs px-l py-xl text-sm text-white/60">
          <p className="text-white/80">Atom — Atoms 的教学复刻</p>
          <p>本站为演示项目，产物仅供预览，不代表 atoms.dev 官方实现。</p>
        </div>
      </footer>
    </div>
  );
}
