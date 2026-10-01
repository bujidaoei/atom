import { useEffect, useState } from "react";
import { AccountSessions } from "../components/AccountSessions";
import { Button } from "../components/ui/Button";
import { Badge } from "../components/ui/Badge";
import { Icon } from "../components/ui/Icon";
import { SelectField, TextField } from "../components/ui/Field";
import { ErrorState, LoadingState, Panel } from "../components/ui/States";
import { api, errorMessage } from "../lib/api";
import type { Settings } from "../lib/types";

export function SettingsPage() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [baseUrl, setBaseUrl] = useState("");
  const [model, setModel] = useState("");
  const [editingKey, setEditingKey] = useState(false);
  const [newKey, setNewKey] = useState("");
  const [saving, setSaving] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  function adopt(next: Settings) {
    setSettings(next);
    setBaseUrl(next.baseUrl);
    setModel(next.model);
    setEditingKey(false);
    setNewKey("");
  }

  async function load() {
    setLoading(true);
    setLoadError(null);
    try {
      adopt(await api.getSettings());
    } catch (err) {
      setLoadError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  const dirty =
    settings !== null &&
    (baseUrl.trim() !== settings.baseUrl ||
      model !== settings.model ||
      (editingKey && newKey.trim().length > 0));

  async function save() {
    if (!settings) return;
    setSaving(true);
    setSaveError(null);
    setSaved(false);
    try {
      const patch: { baseUrl?: string; model?: string; apiKey?: string } = {};
      if (baseUrl.trim() !== settings.baseUrl) patch.baseUrl = baseUrl.trim();
      if (model !== settings.model) patch.model = model;
      if (editingKey && newKey.trim()) patch.apiKey = newKey.trim();
      adopt(await api.updateSettings(patch));
      setSaved(true);
    } catch (err) {
      setSaveError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  async function restoreDefault() {
    setClearing(true);
    setSaveError(null);
    setSaved(false);
    try {
      adopt(await api.clearApiKey());
    } catch (err) {
      setSaveError(errorMessage(err));
    } finally {
      setClearing(false);
    }
  }

  return (
    <div className="mx-auto flex max-w-[640px] flex-col gap-xl px-l py-xxl">
      <header className="flex flex-col gap-xxs">
        <h1 className="text-2xl font-medium text-neutral-95">设置</h1>
        <p className="text-base text-neutral-60">
          配置 AI 网关。自定义地址需要自己的 Key；更换地址时请重新填写该服务的 Key。
        </p>
      </header>

      <AccountSessions />
      {loading ? (
        <LoadingState label="读取设置" />
      ) : loadError ? (
        <ErrorState message={loadError} onRetry={() => void load()} />
      ) : settings ? (
        <>
          <Panel className="flex flex-col gap-l p-xl">
            <div className="flex items-center justify-between gap-m">
              <h2 className="text-md font-medium text-neutral-95">网关</h2>
              <Badge
                tone={
                  settings.source === "user"
                    ? "bg-brand-alpha-strong text-brand-text"
                    : "bg-neutral-12 text-neutral-60"
                }
              >
                {settings.source === "unconfigured" ? "连接待配置" : settings.source === "user" ? "使用你的 key" : "服务端默认"}
              </Badge>
            </div>

            {settings.configurationError ? (
              <ErrorState title="连接需要修复" message={settings.configurationError} compact />
            ) : null}

            <TextField
              label="Base URL"
              value={baseUrl}
              mono
              placeholder="https://ai-gateway.example.com/v1"
              onChange={(event) => setBaseUrl(event.target.value)}
              hint="OpenAI 兼容端点，模型列表从它的 /models 读取。"
            />

            {editingKey ? (
              <TextField
                label="API Key"
                type="password"
                mono
                autoFocus
                autoComplete="off"
                spellCheck={false}
                value={newKey}
                placeholder="粘贴新的 key"
                onChange={(event) => setNewKey(event.target.value)}
                hint="仅向你配置的模型服务发送；页面只显示打码值。"
                action={
                  <button
                    type="button"
                    onClick={() => {
                      setEditingKey(false);
                      setNewKey("");
                    }}
                    className="rounded-full px-xs py-[1px] text-sm text-neutral-60 transition-colors duration-ui ease-ui hover:bg-neutral-8 hover:text-neutral-95"
                  >
                    取消
                  </button>
                }
              />
            ) : (
              <TextField
                label="API Key"
                value={settings.apiKeyMasked}
                mono
                readOnly
                disabled
                onChange={() => undefined}
                hint={
                  settings.source === "unconfigured"
                    ? "连接尚未完成配置，不会发起模型请求。"
                    : settings.hasUserKey
                    ? "这是你保存的 key（已打码）。"
                    : "当前使用服务端默认 key（已打码）。"
                }
                action={
                  <button
                    type="button"
                    onClick={() => setEditingKey(true)}
                    className="inline-flex items-center gap-xxs rounded-full px-xs py-[1px] text-sm text-brand-text transition-colors duration-ui ease-ui hover:bg-brand-alpha-soft active:bg-brand-alpha-strong"
                  >
                    <Icon name="eye" size={12} />
                    换一个 key
                  </button>
                }
              />
            )}

            <SelectField
              label="默认模型"
              value={model}
              onChange={(event) => setModel(event.target.value)}
              hint={
                settings.modelsStatus !== "available"
                  ? "尚未获取到可用模型列表；当前保存值不代表服务可用。"
                  : `网关返回了 ${settings.models.length} 个模型。`
              }
            >
              {settings.models.some((option) => option.id === model) ? null : (
                <option value={model}>{model}（当前）</option>
              )}
              {settings.models.map((option) => (
                <option key={option.id} value={option.id}>
                  {option.id}
                </option>
              ))}
            </SelectField>

            {saveError ? <ErrorState title="保存失败" message={saveError} compact /> : null}
            {saved && !dirty ? (
              <p className="flex items-center gap-xxs text-sm text-success-strong">
                <Icon name="check" size={13} />
                已保存
              </p>
            ) : null}

            <div className="flex flex-wrap items-center gap-s">
              <Button onClick={() => void save()} loading={saving} disabled={!dirty}>
                保存更改
              </Button>
              <Button
                variant="secondary"
                onClick={() => {
                  adopt(settings);
                  setSaved(false);
                  setSaveError(null);
                }}
                disabled={!dirty}
              >
                放弃修改
              </Button>
            </div>
          </Panel>

          <Panel className="flex flex-col gap-m p-xl">
            <h2 className="text-md font-medium text-neutral-95">恢复默认</h2>
            <p className="text-base text-neutral-60">
              同时清除个人 Key 和自定义 Base URL，恢复服务端默认连接。保留模型选择。
            </p>
            <div>
              <Button
                variant="danger"
                onClick={() => void restoreDefault()}
                loading={clearing}
                disabled={!settings.hasUserKey && settings.source !== "unconfigured"}
              >
                恢复服务端默认
              </Button>
            </div>
            {!settings.hasUserKey && settings.source !== "unconfigured" ? (
              <p className="text-sm text-neutral-40">你还没有自定义 key，无需恢复。</p>
            ) : null}
          </Panel>
        </>
      ) : null}
    </div>
  );
}
