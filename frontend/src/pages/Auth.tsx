import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { AgentRow } from "../components/AgentRow";
import { Logo } from "../components/Logo";
import { ThemeToggle } from "../components/ThemeToggle";
import { Button } from "../components/ui/Button";
import { Icon } from "../components/ui/Icon";
import { TextField } from "../components/ui/Field";
import { api, errorMessage } from "../lib/api";
import { useAuth } from "../lib/auth";

type Step = "email" | "password";

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function validatePassword(value: string): string | null {
  if (value.length < 8) return "密码至少 8 位。";
  if (/^\d+$/.test(value)) return "密码不能是纯数字。";
  return null;
}

export function AuthPage({ mode }: { mode: "login" | "register" }) {
  const { user, signIn } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: string } | null)?.from ?? "/app";

  const [step, setStep] = useState<Step>("email");
  const [email, setEmail] = useState("");
  const [exists, setExists] = useState<boolean | null>(null);
  const [password, setPassword] = useState("");
  const [emailError, setEmailError] = useState<string | null>(null);
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const passwordRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (user) navigate(from, { replace: true });
  }, [user, from, navigate]);

  useEffect(() => {
    if (step === "password") passwordRef.current?.focus();
  }, [step]);

  async function submitEmail() {
    const trimmed = email.trim();
    if (!EMAIL_PATTERN.test(trimmed)) {
      setEmailError("请输入有效的邮箱地址。");
      return;
    }
    setEmailError(null);
    setFormError(null);
    setBusy(true);
    try {
      const result = await api.lookup(trimmed);
      setEmail(result.email);
      setExists(result.exists);
      setStep("password");
    } catch (err) {
      setFormError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function submitPassword() {
    const problem = exists ? (password ? null : "请输入密码。") : validatePassword(password);
    if (problem) {
      setPasswordError(problem);
      return;
    }
    setPasswordError(null);
    setFormError(null);
    setBusy(true);
    try {
      const account = exists
        ? await api.login(email, password)
        : await api.register(email, password);
      signIn(account);
      navigate(from, { replace: true });
    } catch (err) {
      setFormError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  function backToEmail() {
    setStep("email");
    setPassword("");
    setPasswordError(null);
    setFormError(null);
    setExists(null);
  }

  const heading =
    step === "email"
      ? mode === "register"
        ? "创建你的账户"
        : "登录 Atom"
      : exists
        ? "欢迎回来"
        : "创建你的账户";

  const subheading =
    step === "email"
      ? "先填邮箱，我们会判断你是登录还是注册。"
      : exists
        ? "输入密码继续。"
        : "为这个邮箱设置一个密码，至少 8 位且不能是纯数字。";

  return (
    <div className="flex min-h-screen flex-col bg-base-default">
      <header className="flex h-12 items-center justify-between px-l">
        <Link to="/" className="rounded-m px-xxs py-xxs hover:bg-neutral-8" aria-label="返回首页">
          <Logo />
        </Link>
        <ThemeToggle />
      </header>

      <main className="flex flex-1 items-start justify-center px-l pb-xxxl pt-xxl">
        <div className="w-full max-w-[400px]">
          <AgentRow size="sm" showUpcoming={false} className="mb-xl" />

          <div className="hairline rounded-xl border-neutral-12 bg-base-tertiary p-xl shadow-flat">
            <h1 className="text-2xl font-medium text-neutral-95">{heading}</h1>
            <p className="mt-xxs text-base text-neutral-60">{subheading}</p>

            <form
              className="mt-xl flex flex-col gap-l"
              onSubmit={(event) => {
                event.preventDefault();
                void (step === "email" ? submitEmail() : submitPassword());
              }}
            >
              {step === "email" ? (
                <TextField
                  label="邮箱"
                  type="email"
                  name="email"
                  autoComplete="email"
                  inputMode="email"
                  autoFocus
                  placeholder="you@example.com"
                  value={email}
                  error={emailError}
                  onChange={(event) => setEmail(event.target.value)}
                />
              ) : (
                <>
                  <TextField
                    label="邮箱"
                    type="email"
                    name="email"
                    value={email}
                    readOnly
                    disabled
                    onChange={() => undefined}
                    action={
                      <button
                        type="button"
                        onClick={backToEmail}
                        className="inline-flex items-center gap-xxs rounded-full px-xs py-[1px] text-sm text-brand-text transition-colors duration-ui ease-ui hover:bg-brand-alpha-soft active:bg-brand-alpha-strong"
                      >
                        <Icon name="arrow-left" size={12} />
                        返回
                      </button>
                    }
                  />
                  <TextField
                    ref={passwordRef}
                    label="密码"
                    type="password"
                    name="password"
                    autoComplete={exists ? "current-password" : "new-password"}
                    placeholder={exists ? "你的密码" : "至少 8 位，别用纯数字"}
                    value={password}
                    error={passwordError}
                    hint={exists ? undefined : "注册后会附带一份免费额度。"}
                    onChange={(event) => setPassword(event.target.value)}
                  />
                </>
              )}

              {formError ? (
                <p
                  role="alert"
                  className="flex items-start gap-xs rounded-m bg-danger-surface px-m py-s text-base text-danger-strong"
                >
                  <Icon name="alert" size={14} className="mt-[3px]" />
                  {formError}
                </p>
              ) : null}

              <Button type="submit" size="lg" block loading={busy}>
                {step === "email" ? "继续" : exists ? "登录" : "创建账户"}
              </Button>
            </form>
          </div>

          <p className="mt-l text-center text-sm text-neutral-60">
            {mode === "register" ? (
              <>
                已经有账号了？{" "}
                <Link to="/login" className="text-brand-text hover:underline">
                  去登录
                </Link>
              </>
            ) : (
              <>
                还没有账号？{" "}
                <Link to="/register" className="text-brand-text hover:underline">
                  去注册
                </Link>
              </>
            )}
          </p>
        </div>
      </main>
    </div>
  );
}
