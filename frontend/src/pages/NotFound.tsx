import { Link } from "react-router-dom";
import { Logo } from "../components/Logo";
import { LinkButton } from "../components/ui/Button";

export function NotFoundPage() {
  return (
    <div className="flex min-h-screen flex-col bg-base-default">
      <header className="flex h-12 items-center px-l">
        <Link to="/" className="rounded-m px-xxs py-xxs hover:bg-neutral-8" aria-label="返回首页">
          <Logo />
        </Link>
      </header>
      <main className="flex flex-1 flex-col items-center justify-center gap-m px-l pb-xxxl">
        <p className="font-mono text-sm text-neutral-40">404</p>
        <h1 className="text-h1 font-medium text-neutral-95">这里没有页面</h1>
        <p className="max-w-[40ch] text-center text-base text-neutral-60">
          链接可能过期了，或者这个项目已经被删除。
        </p>
        <LinkButton to="/app">回到工作台</LinkButton>
      </main>
    </div>
  );
}
