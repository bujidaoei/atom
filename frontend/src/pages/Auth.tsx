import { FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { PROMPT_KEY, api, readError } from "../api";
import { useSession } from "../session";
import { Button, Field, Wordmark, inputClass } from "../ui";

export function AuthPage({ mode }: { mode: "login" | "register" }) {
  const navigate = useNavigate();
  const { setUser } = useSession();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const isRegister = mode === "register";

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const user = isRegister
        ? await api.register({ name: name.trim(), email: email.trim(), password })
        : await api.login({ email: email.trim(), password });
      setUser(user);
      const pending = sessionStorage.getItem(PROMPT_KEY);
      if (pending) {
        const project = await api.createProject(pending);
        sessionStorage.removeItem(PROMPT_KEY);
        navigate(`/app/p/${project.id}`);
        return;
      }
      navigate("/app");
    } catch (err) {
      setError(readError(err));
      setBusy(false);
    }
  }

  return (
    <div className="grid min-h-screen md:grid-cols-[minmax(280px,0.8fr)_minmax(320px,1fr)]">
      <div className="flex flex-col justify-between border-b border-line px-6 py-6 md:border-b-0 md:border-r md:px-10 md:py-8">
        <Wordmark />
        <p className="max-w-sm py-10 font-display text-4xl leading-[1.15] tracking-[-0.03em] md:text-5xl">
          {isRegister ? "注册之后，这句话会变成一个项目。" : "回来继续改已经锁定的那一版。"}
        </p>
        <p className="text-sm text-muted">演示环境。请使用你愿意记住的密码。</p>
      </div>
      <form className="mx-auto flex w-full max-w-md flex-col justify-center px-6 py-12" onSubmit={submit}>
        <h1 className="text-2xl">{isRegister ? "注册" : "登录"}</h1>
        <div className="mt-8 space-y-5">
          {isRegister ? (
            <Field label="怎么称呼你">
              <input className={inputClass} value={name} onChange={(event) => setName(event.target.value)} required maxLength={40} />
            </Field>
          ) : null}
          <Field label="邮箱">
            <input
              className={inputClass}
              type="email"
              autoComplete="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
            />
          </Field>
          <Field label="密码" hint={isRegister ? "至少 8 位" : undefined}>
            <input
              className={inputClass}
              type="password"
              autoComplete={isRegister ? "new-password" : "current-password"}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
              minLength={isRegister ? 8 : 1}
            />
          </Field>
        </div>
        {error ? <p className="mt-4 text-sm text-clay">{error}</p> : null}
        <Button type="submit" className="mt-6" disabled={busy}>
          {busy ? "请稍等" : isRegister ? "注册并继续" : "登录"}
        </Button>
        <p className="mt-6 text-sm text-muted">
          {isRegister ? (
            <>
              已经有账号？ <Link to="/login">登录</Link>
            </>
          ) : (
            <>
              还没有账号？ <Link to="/register">注册</Link>
            </>
          )}
        </p>
      </form>
    </div>
  );
}
