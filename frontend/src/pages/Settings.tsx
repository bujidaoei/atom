import { FormEvent, useEffect, useState } from "react";
import { api, readError } from "../api";
import { AppShell } from "../Shell";
import type { SettingsView } from "../types";
import { Button, inputClass } from "../ui";

export function SettingsPage() {
  const [view, setView] = useState<SettingsView | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [editingKey, setEditingKey] = useState(false);
  const [keyDraft, setKeyDraft] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [baseUrl, setBaseUrl] = useState("");
  const [busy, setBusy] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    document.title = "网关设置 · Atom";
    api
      .settings()
      .then((next) => {
        setView(next);
        setBaseUrl(next.base_url);
      })
      .catch((err) => setError(readError(err)))
      .finally(() => setLoading(false));
  }, []);

  async function saveKey(event: FormEvent) {
    event.preventDefault();
    setBusy("key");
    setError("");
    setNotice("");
    try {
      const next = await api.saveSettings({ api_key: keyDraft.trim() });
      setView(next);
      setEditingKey(false);
      setKeyDraft("");
      setShowKey(false);
      setNotice("密钥已更新");
    } catch (err) {
      setError(readError(err));
    } finally {
      setBusy("");
    }
  }

  async function clearKey() {
    setBusy("clear");
    setError("");
    try {
      setView(await api.clearKey());
      setNotice("已改回服务器默认密钥");
    } catch (err) {
      setError(readError(err));
    } finally {
      setBusy("");
    }
  }

  async function saveBase(event: FormEvent) {
    event.preventDefault();
    setBusy("url");
    setError("");
    try {
      const next = await api.saveSettings({ base_url: baseUrl.trim() });
      setView(next);
      setBaseUrl(next.base_url);
      setNotice("地址已保存");
    } catch (err) {
      setError(readError(err));
    } finally {
      setBusy("");
    }
  }

  async function saveModel(model: string) {
    setError("");
    try {
      setView(await api.saveSettings({ model }));
      setNotice("模型已切换");
    } catch (err) {
      setError(readError(err));
    }
  }

  return (
    <AppShell>
      <main className="mx-auto max-w-4xl px-5 py-10 md:px-10">
        <h1 className="font-display text-5xl font-medium tracking-[-0.03em]">网关</h1>
        <p className="mt-3 max-w-xl text-sm leading-6 text-muted">
          模型请求走你配置的 OpenAI 兼容网关。密钥只在服务器上保存，页面上只显示前两位和后两位。
        </p>
        {loading ? <p className="mt-4 text-sm text-muted">正在读取网关配置</p> : null}
        {error ? <p className="mt-4 text-sm text-clay">{error}</p> : null}
        {notice ? <p className="mt-4 text-sm text-sage">{notice}</p> : null}

        <section className="mt-10 border-t border-line py-6">
          <div className="grid items-start gap-6 md:grid-cols-[minmax(0,1fr)_auto]">
            <div>
              <h2 className="text-base font-medium">AI 网关 API Key</h2>
              <p className="mt-2 max-w-xl text-sm leading-6 text-muted">
                可选。模型请求将优先使用你为本账号配置的网关 API Key；未配置时使用受保护的服务器默认密钥。
              </p>
            </div>
            <div className="md:text-right">
              <p className={`text-xs ${view?.configured ? "text-sage" : "text-muted"}`}>
                {view?.configured ? "已配置" : "未配置"}
                {view?.api_key_source === "server" ? " · 服务器默认" : ""}
                {view?.api_key_source === "user" ? " · 本账号" : ""}
              </p>
              {editingKey ? (
                <form className="mt-3 flex flex-wrap items-center gap-2 md:justify-end" onSubmit={saveKey}>
                  <input
                    className={`${inputClass} w-64 font-mono`}
                    type={showKey ? "text" : "password"}
                    value={keyDraft}
                    onChange={(event) => setKeyDraft(event.target.value)}
                    autoComplete="off"
                    aria-label="新的 API Key"
                    required
                  />
                  <button type="button" className="text-sm text-muted" onClick={() => setShowKey((value) => !value)}>
                    {showKey ? "隐藏" : "显示"}
                  </button>
                  <Button type="submit" disabled={busy === "key"}>
                    保存
                  </Button>
                  <Button
                    variant="line"
                    onClick={() => {
                      setEditingKey(false);
                      setKeyDraft("");
                    }}
                  >
                    取消
                  </Button>
                </form>
              ) : (
                <div className="mt-3 flex flex-wrap items-center gap-2 md:justify-end">
                  <code className="rounded-lg border border-line bg-raised px-3 py-2 font-mono text-sm">
                    {view?.api_key_masked || "未配置"}
                  </code>
                  <Button variant="line" onClick={() => setEditingKey(true)}>
                    更换
                  </Button>
                  <Button variant="line" onClick={clearKey} disabled={view?.api_key_source !== "user" || busy === "clear"}>
                    清除
                  </Button>
                </div>
              )}
            </div>
          </div>
        </section>

        <section className="border-t border-line py-6">
          <form className="grid items-end gap-4 md:grid-cols-[minmax(0,1fr)_auto]" onSubmit={saveBase}>
            <label>
              <span className="text-base font-medium">API 请求地址</span>
              <span className="mt-2 block text-sm text-muted">
                {view?.base_url_source === "user" ? "使用本账号地址" : "使用服务器默认地址"}
              </span>
              <input
                className={`${inputClass} mt-3 font-mono text-[#1c1915]`}
                value={baseUrl}
                onChange={(event) => setBaseUrl(event.target.value)}
                placeholder={loading ? "正在读取" : "https://"}
                aria-label="API 请求地址"
              />
            </label>
            <Button type="submit" variant="line" disabled={busy === "url"}>
              保存地址
            </Button>
          </form>
        </section>

        <section className="border-y border-line py-6">
          <label className="block">
            <span className="text-base font-medium">模型</span>
            <span className="mt-2 block max-w-xl text-sm leading-6 text-muted">
              默认用较快的模型，方便把契约、页面和验收走完。换成更强的模型，页面通常更好，等待也更长。
            </span>
            <p className="mt-3 text-sm text-[#1c1915]">{loading ? "正在读取模型" : view?.model || "还没有模型"}</p>
            <select
              className={`${inputClass} mt-2 max-w-md text-[#1c1915]`}
              value={view?.model || ""}
              disabled={!view}
              onChange={(event) => saveModel(event.target.value)}
              aria-label="模型"
            >
              {(view?.models || []).map((model) => (
                <option key={model.id} value={model.id}>
                  {model.id}
                </option>
              ))}
              {view && !(view.models || []).some((model) => model.id === view.model) ? (
                <option value={view.model}>{view.model}</option>
              ) : null}
            </select>
          </label>
        </section>
      </main>
    </AppShell>
  );
}
