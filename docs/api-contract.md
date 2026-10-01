# Atoms Demo — API 契约

后端 FastAPI，挂在 `/api` 下。除标注 `public` 外都要求登录态（HttpOnly Cookie `atom_session`）。
所有请求/响应均为 JSON，时间为 ISO-8601 UTC 字符串。

`GET /api/health` 为 public 的运行时依赖检查：运行时鉴权或连接失败时返回 HTTP 503、`{"ok":false,"runtime":false}`；成功返回 200、两个字段为 true。不表示模型、数据库恢复或整个平台已验收。Node 内部服务的 `/healthz`、`/v1/roles`、运行与取消接口均要求共享 Bearer 令牌，浏览器不持有该令牌。

前端开发时 Vite 把 `/api`、`/preview`、`/p` 代理到 `http://127.0.0.1:8000`。

---

## 0. 约定

错误统一形如：

```json
{ "detail": "人类可读的中文说明" }
```

常见状态码：`400` 参数错误 / `401` 未登录 / `402` 额度不足 / `403` 越权 / `404` 不存在 / `409` 状态冲突 / `502` 网关错误。

---

## 1. 认证 `public`

Atoms 用的是两步式：先填邮箱，后端回答这个邮箱是否已注册，前端据此渲染"登录"或"创建账户"。

### `POST /api/auth/lookup`

```json
// req
{ "email": "a@b.com" }
// res
{ "email": "a@b.com", "exists": true }
```

### `POST /api/auth/login`

```json
// req
{ "email": "a@b.com", "password": "..." }
// res  -> 同时 Set-Cookie: atom_session
{ "id": "...", "email": "a@b.com", "name": "a", "credits": 200, "canRevokeSessions": false }
```

### `POST /api/auth/register`

```json
// req
{ "email": "a@b.com", "password": "...", "name": "可选" }
// res 同 login
```

密码规则：至少 8 位，且不能是纯数字。

### `POST /api/auth/logout` → `{ "ok": true }`

### `GET /api/auth/me` → 同 login 的 user 对象；未登录返回 401

---

## 2. 设置

### `GET /api/settings`

```json
{
  "baseUrl": "https://ai-gateway.skg.com/v1",
  "model": "claude-sonnet-5",
  "apiKeyMasked": "sk*********************Gg",
  "hasUserKey": false,
  "source": "server",          // "server" | "user" | "unconfigured"
  "configurationError": null,  // 配置不完整时给出可修复错误，不发起模型请求
  "modelsStatus": "available", // "available" | "unavailable" | "unconfigured"
  "models": [                   // 来自网关 /models，60s 缓存
    { "id": "claude-sonnet-5" },
    { "id": "gpt-5.6-sol" }
  ]
}
```

`apiKeyMasked` 规则：**明文保留前 2 位和后 2 位，中间一律用 `*` 填充，`*` 的个数等于被遮盖的字符数**。长度 ≤ 4 时整串打码。

### `PUT /api/settings`

```json
// req，三个字段都可选，只传要改的
{ "baseUrl": "...", "apiKey": "...", "model": "..." }
// res 同 GET
```

自定义地址必须与个人 Key 成对保存；更换已绑定地址必须同时重新填写未打码的 Key。无效更新返回 400，不持久化、不请求服务。读取旧的不完整配置仍返回 200，`source=unconfigured`、`models=[]`；生成任务拒绝使用该配置。模型发现失败返回空列表，不能推断保存的模型可用，也不会补入猜测的模型。

### `DELETE /api/settings/api-key` → 同时清掉个人 Key 和自定义 Base URL，恢复服务端默认连接；保留模型选择；res 同 GET

---

## 3. 项目

### `GET /api/projects`

```json
{ "projects": [ProjectSummary] }
```

```ts
type ProjectSummary = {
  id: string;
  title: string;          // 未规划出来前等于截断的 prompt
  summary: string | null;
  kind: string | null;    // landing/dashboard/tool/game/store/portfolio/other
  status: ProjectStatus;
  slug: string | null;    // 已发布才有
  publishedAt: string | null;
  createdAt: string;
  updatedAt: string;
};

type ProjectStatus =
  | 'draft'              // 刚创建，还没规划
  | 'planning'           // Mike/Iris/Emma/Bob 正在跑
  | 'awaiting_approval'  // 契约已出，等用户确认
  | 'building'           // Alex 正在写代码
  | 'ready'              // 可预览
  | 'error';
```

### `POST /api/projects`

```json
// req
{ "prompt": "做一个记账小工具" }
// res
{ "project": ProjectDetail }
```

创建即返回 `draft`，不自动开跑。前端拿到后调 `/plan`。

### `GET /api/projects/{id}` → `{ "project": ProjectDetail }`

```ts
type ProjectDetail = ProjectSummary & {
  prompt: string;
  messages: Message[];
  requirements: Requirement[];
  files: FileEntry[];          // 工作区文件树（懒读，只有元信息）
  revisionId: string | null;
  incompleteSavedRevisionId: string | null; // 当前修订有已确认的非成功终态收据时才有值
  acceptance: AcceptanceRun | null;
  activeRunId: string | null;
  race: RaceSummary | null;
};

type Message = {
  id: string;
  role: 'user' | 'mike' | 'iris' | 'emma' | 'bob' | 'alex' | 'system';
  content: string;
  runId: string | null;
  createdAt: string;
};

type Requirement = {
  key: string;
  title: string;
  detail: string;
  checks: Check[];
};

type Check =
  | { type: 'exists'; selector: string }
  | { type: 'text'; selector: string; contains: string }
  | { type: 'flow'; selector: string; expect: string };

type FileEntry = { path: string; bytes: number; updatedAt: string };
```

### `DELETE /api/projects/{id}` → `{ "ok": true }`

### `GET /api/projects/{id}/files/{path}` → 文件原文（`text/plain`）

---

## 4. 主流程

三个动作都是**立即返回**，真正的进度走 SSE。

### `POST /api/projects/{id}/plan`

跑 Mike → Iris → Emma → Bob。结束后项目进 `awaiting_approval`，`requirements` 被填上。

res: `{ "runId": "..." }`

### `POST /api/projects/{id}/approve`

用户确认契约，触发 Alex 构建。结束后进 `ready`。

req（可选微调）：`{ "note": "顺便加个深色模式" }`
res: `{ "runId": "..." }`

### `POST /api/projects/{id}/revise`

在已有成果上继续改。

req: `{ "message": "把按钮改成绿色" }`
res: `{ "runId": "..." }`

### `POST /api/projects/{id}/cancel` → `{ "ok": true }`

---

## 5. 事件流（SSE）

### `GET /api/projects/{id}/events?after={seq}`

`text/event-stream`。断线重连时带上已收到的最大 `seq`，服务端补发历史再续上实时。

每条：

```
event: run
data: {"seq":128,"runId":"...","role":"alex","type":"tool.started","payload":{...},"at":"..."}
```

`type` 直接透传运行时的事件类型，前端至少要处理：

| type | payload 关键字段 | UI 含义 |
|---|---|---|
| `run.started` | — | 该角色开始 |
| `thinking.delta` | `delta` | 思考流，折叠展示 |
| `message.delta` | `delta` | 正文流 |
| `message.completed` | `text` | 正文定稿 |
| `tool.started` | `toolName`, `args` | 工具卡片出现 |
| `tool.completed` | `toolName`, `result` | 工具卡片收起 |
| `tool.failed` | `toolName`, `result` | 工具卡片标红 |
| `usage.updated` | `inputTokens`,`outputTokens` | 计费 |
| `run.completed` | `resultText` | 该角色结束 |
| `run.failed` | `message` | 该角色失败 |

另有两类平台事件（不来自运行时）：

| type | payload | 含义 |
|---|---|---|
| `squad.role_started` | `role` | 编排器切到下一个角色 |
| `project.updated` | `status`,`requirements?`,`files?` | 前端据此刷新项目 |

心跳：每 15 秒一条 `: ping`。

---

## 6. 预览与发布

### `GET /preview/{projectId}/*` `public*`

直接把工作区当静态站点serve，`/` 落到 `index.html`。带 `X-Frame-Options: SAMEORIGIN`，前端用 iframe 嵌。
`*` 需要登录态或项目已发布。

### `POST /api/projects/{id}/publish`

把当前工作区快照到发布目录，分配 slug。

res: `{ "slug": "sunny-ledger-4f2a", "url": "/p/sunny-ledger-4f2a" }`

### `POST /api/projects/{id}/unpublish` → `{ "ok": true }`

### `GET /p/{slug}/*` `public` → 发布后的静态站点

---

## 7. 验收（延展能力之一）

Emma 写的 `checks` 由前端在预览 iframe 里真实执行，结果回传。

### `POST /api/projects/{id}/acceptance`

```json
// req：前端在 iframe 中跑完后回报
{ "results": [ { "key": "add-entry", "checkIndex": 0, "passed": true, "note": "" } ] }
// res
{ "acceptance": AcceptanceRun }
```

```ts
type AcceptanceRun = {
  id: string;
  passed: number;
  total: number;
  results: { key: string; checkIndex: number; passed: boolean; note: string }[];
  createdAt: string;
};
```

---

## 8. Race Mode（延展能力之二）

同一份契约同时交给多个模型构建，产出并排对比，用户选一个胜出者合入主工作区。

### `POST /api/projects/{id}/race`

```json
// req
{ "models": ["claude-sonnet-5", "gpt-5.6-sol", "deepseek-v4-pro"] }
// res
{ "raceId": "...", "heats": [RaceHeat] }
```

2 到 4 个模型。每个 heat 在独立工作区并行跑 Alex。

### `GET /api/projects/{id}/race` → `{ "race": RaceSummary | null }`

```ts
type RaceSummary = {
  id: string;
  status: 'running' | 'done';
  heats: RaceHeat[];
  winnerHeatId: string | null;
  createdAt: string;
};

type RaceHeat = {
  id: string;
  model: string;
  status: 'queued' | 'running' | 'done' | 'failed' | 'cancelled' | 'timed_out' | 'interrupted' | 'error';
  runId: string | null;
  revisionId: string | null;
  incompleteSavedRevisionId: string | null;
  previewUrl: string | null;   // /preview/{projectId}/race/{heatId}/
  elapsedMs: number | null;
  inputTokens: number;
  outputTokens: number;
  fileCount: number;
  bytes: number;
  error: string | null;
};
```

heat 的事件同样走项目 SSE，`payload.heatId` 区分。

### `POST /api/projects/{id}/race/{heatId}/adopt`

把该 heat 的产物覆盖进主工作区，项目回到 `ready`。

res: `{ "ok": true }`

---

## 9. 额度

### `GET /api/usage`

```json
{
  "credits": 182,
  "spent": 18,
  "runs": 7,
  "inputTokens": 48211,
  "outputTokens": 9033,
  "ledger": [ { "delta": -3, "reason": "build", "at": "..." } ]
}
```

每次 agent turn 扣 1 credit，Race Mode 每个 heat 各扣 1。额度为 0 时相关接口返回 402。
# Workflow integrity additions (2026-09-30)

Plan, approve, revise, race and individual heat retry accept an optional `Idempotency-Key` header (1–128 characters). A matching project/key/action/body replays the original receipt even after completion or cancellation. Reusing a key for different input returns 409. The UI uses `initial-plan:<projectId>` for automatic first planning and fresh keys for intentional new operations. Network retries reuse the key. Receipts are durable; execution remains single-worker.

Race creation accepts `budgetSeconds` (180–600, default 180). `POST /api/projects/{id}/race/{heatId}/retry` accepts `budgetSeconds` (same bounds, default 360) and returns `runId`. Only unsuccessful terminal heats in the current owned race may be retried. Files and previous runs are retained, other heats are unchanged, and adoption remains explicit. Heat details expose `runStartedAt` in UTC; elapsed time and usage accumulate across attempts. Partial files may have a preview URL without being eligible for adoption.


账户会话能力：register/login/me 的 user 对象包含 canRevokeSessions，只有 durable 会话模式为 true。此字段用于显示操作入口，服务端仍独立鉴权。POST /api/auth/logout-all 要求正确 Origin 与 X-Atom-Intent: revoke-account-sessions；事务成功返回 {"ok":true} 并清除当前 Cookie。旧会话全部失效，之后重新登录仍允许；失败不得显示退出成功。
