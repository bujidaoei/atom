# Atom — Atoms 的可运行复刻

写一句话，一支 AI 小队把它变成一个真实能跑的网页应用。

这是 [atoms.dev](https://atoms.dev/) 的教学性复刻，不是官方产品。做它的目的是把 Atoms
那条「想法 → 多 agent 协作 → 人确认 → 真实代码 → 可预览可发布」的链路完整走通一遍。

---

## 它是怎么工作的

```
你写一句需求
   │
   ├─ Mike   Team Leader       拆成计划，决定这轮谁上场
   ├─ Iris   Deep Researcher   把需求变成一个聚焦的机会
   ├─ Emma   Product Manager   写成「可机器检查」的验收契约
   └─ Bob    Architect         定文件布局、状态方案、视觉方向
   │
   ▼
[ 你确认契约 ]   ← 人在环。不点头，一行代码都不会写
   │
   ▼
   Alex   Engineer   在真实工作区里用 write / edit / glob / grep /
                     read_file 写出多文件应用（平台负责静态校验）
   │
   ▼
预览（iframe 实时）→ 运行验收（真的在 DOM 上跑 Emma 的检查）→ 发布公开链接
```

Emma 写的不是一段描述，是一组选择器级别的检查：

```json
{ "type": "flow", "selector": "[data-testid='add-habit']", "expect": "[data-testid='habit-item']" }
```

点「运行验收」时，这些检查会在预览 iframe 里**真实执行**——查 DOM、点按钮、等元素出现。
所以结果可能是 8/9，并告诉你哪一条为什么没过。平台验证 agent，而不是相信它。

生成默认有 180 秒硬截止时间（规划单独计时）。网关明确截断时，同一会话最多恢复两次；
取消、超时、重启中断均持久化，刷新后可以继续处理已有文件。可预览不等于验收通过。
验收支持 `setup` 中的 `fill`、`click`、`press` 前置操作，并逐条记录真实结果。
本轮规格、实施任务和测试证据见 [Spec Kit](specs/001-generation-reliability/plan.md)。

---

## agent 运行时

核心的 agent 循环**没有重写**，是从 [workdude](https://github.com/earendil-works/pi) 项目
原样搬过来的：

| 内容 | 文件数 | 说明 |
|---|---|---|
| `runtime/pi/` | 1905 | Pi 0.87.1 内核源码树，逐文件 SHA256 锁定 |
| `runtime/packages/agent-runtime/` | 136 | `ProductAgentRuntime`，产品层运行时 |
| `runtime/packages/product-contracts/` | 44 | 端口与事件契约 |
| `runtime/scripts/` | 93 | 构建、校验、发布脚本 |
| `runtime/.cache/` | 3 | 预编译的网关 bundle（13.5 MB） |

可以自己验证它没被改过：

```bash
cd runtime && node scripts/verify-pi-source.mjs
# Vendored Pi source boundary verified at upstream f07218c4... (1905 files)
```

`ProductAgentRuntime` 是端口驱动的，本项目只实现了三个适配器（`runtime/src/`）：

- `LocalSandboxClient` — 用本地文件系统 + 子进程替代 workdude 的 Docker sandbox broker
- 自动批准的 `ApprovalAdapter`
- `ProductEventSink` — 把运行时事件转成 NDJSON 喂给 FastAPI

---

## 架构

```
浏览器
  │  SSE /api/projects/{id}/events
  ▼
nginx ──┬── /            静态 SPA（React + Vite + Tailwind）
        ├── /api/*       FastAPI（uvicorn）
        └── /preview|/p  生成的应用（由 API 从工作区 serve）
                │
                ▼
          FastAPI 编排器
                │  NDJSON over HTTP
                ▼
      Node agent 运行时 sidecar
                │  OpenAI 兼容
                ▼
            AI 网关
```

三个进程由 Supervisor 拉起，打成一个镜像，`docker compose up -d --build` 一键部署。
数据落 SQLite（WAL），生成的应用落在 `/data/projects/<id>/workspace/` 的真实目录里。

---

## 本地运行

启动前请先阅读 [配置要求](docs/configuration.md)：现在必须配置独立的会话签名密钥与运行时令牌，不再接受空值或示例密钥。企业化进展及未完成门禁见 [当前规格](specs/003-enterprise-foundation/spec.md)。

需要 Node 24+、Python 3.12+、[uv](https://docs.astral.sh/uv/)。

```bash
cp .env.example backend/.env    # 填上 ATOM_LLM_API_KEY
cd runtime  && npm install
cd ../backend && uv sync --group dev
cd ../frontend && npm install
```

起后端和运行时：

```powershell
pwsh scripts/dev.ps1        # Windows
```

```bash
bash scripts/dev.sh         # Linux / macOS
```

再起前端：

```bash
cd frontend && npm run dev
```

打开 http://127.0.0.1:5173 。

## 测试

```bash
cd backend && uv run pytest              # 31 个单元与接口测试
uv run python ../scripts/e2e.py          # 真实模型的端到端冒烟测试
cd ../frontend && npm run build          # 类型检查 + 构建
cd ../runtime && node scripts/verify-pi-source.mjs
```

## 部署

```bash
cp .env.example .env    # 填好密钥，ATOM_SECRET 换成随机值
docker compose up -d --build
```

---

## 关于模型选择

默认用 `deepseek-v4.1-flash`。这不是随便选的：实测网关对单次响应有大约 60 秒的上限，
慢模型写长文件时会被中途掐断。

| 模型 | 长流式输出 | 结果 |
|---|---|---|
| deepseek-v4.1-flash | 61.5s / 464 KB | 完整 |
| claude-sonnet-5 | 180s | 中断 |
| gpt-5.6-luna | 60.7s | 中断 |
| qwen3.7-plus | 60.4s | 中断 |

所以 Alex 的提示词要求它分多次小的工具调用来写文件，这既绕开了上限，
也正好是 agent 本该有的工作方式。可以在设置页换成任意模型。

## 说明

生成的应用在沙箱里执行，预览用 `X-Frame-Options: SAMEORIGIN` 限制在本站内嵌。
本项目是演示用途，与 atoms.dev 官方无关。
