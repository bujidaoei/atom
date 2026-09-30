# Atom 企业级升级：当前实现只读审计

日期：2026-09-30。范围：当前 Atom 接入路径（FastAPI、React、`runtime/src` 适配层、部署配置、001/002 Spec Kit）。本次仅静态审计，没有执行攻击、读取真实密钥、连接生产数据库或重跑历史测试。以下行号对应审计时工作树。上游 runtime 内含大量其他产品模块；其存在不等于 Atom 已接入这些能力。未修改 `runtime/pi` 或用户已有代码。

## 结论

现有产品已具备可靠 demo 的若干关键基础：真实 runtime、模型生成文件、持久化终态、取消和截断恢复、命令幂等、候选赛跑、契约覆盖校验和真实浏览器证据。但当前架构明确限制为单 API worker，不具备企业多租户安全、可信认证验收、水平扩容或高可用发布的完整边界。企业级不能由界面改造或新增几个管理页宣告完成。

## 优先级与源代码证据

| 优先级 | 已观察事实与风险 | 证据 | 企业化方向与验收 |
|---|---|---|---|
| P0 | 用户自定义模型地址与服务端模型密钥独立回退：只改 baseUrl 就可能把服务器 Bearer key 发往用户指定主机。地址只校验 http/https 前缀，同时存在 SSRF 面。 | `backend/app/routers/settings.py:34`、`:35`、`:61`；`backend/app/services/gateway.py:31`、`:33`；生成路径也如此：`backend/app/services/orchestrator.py:744`、`:745`。 | 统一 Provider Connection 解析和凭据绑定；服务器密钥仅能用于管理员可信 endpoint；BYOK 自定义 endpoint 必须显式携带自己的凭据；出口策略阻断私网、链路本地、回环和 DNS 重绑定。通过受控 HTTP 捕获测试证明服务器 key 不会流向自定义地址，不能用真实 key 做测试。 |
| P0 | 不可信生成页面与控制台/API 同源，iframe 同时允许脚本和同源。HttpOnly cookie 不会阻止同源脚本用浏览器自动附带 cookie 请求管理 API。公开发布页面也是同源。 | `backend/app/routers/preview.py:36`；`frontend/src/workspace/PreviewTab.tsx:107`；`deploy/nginx.conf:70` 的生成页面代理；`backend/app/routers/preview.py:70`。 | 将预览/发布移动到独立不可信站点域，控制台 cookie host-only；鉴权预览用短期能力 token。验收改为隔离服务端浏览器执行。安全回归证明生成页面不能读取项目/设置、调用发布/删除接口或访问父页面 DOM。 |
| P0 | LocalSandbox 是本机子进程适配器，不是 OS 安全边界：shell 继承 process.env；与 API、数据共处同一个容器。当前 builder 仅开放文件工具，这是重要约束，不能夸大为现在模型必然获得任意 shell，但未来扩展 shell/build/npm 会立即放大风险。 | `runtime/src/local-sandbox.ts:18`、`:58`、`:60`；`runtime/src/server.ts:109`、`:129`；`Dockerfile:28` 起未声明非 root USER；`docker-compose.yml:14` 共享数据卷。 | 保留 ProductAgentRuntime/Pi，替换 SandboxClient 适配器为隔离执行 worker；短期凭据、最小环境、独立 UID、CPU/RAM/PID/磁盘限制、网络出口策略、无宿主 socket 挂载；以跨租户文件和网络逃逸测试验证。不要把路径校验称作容器级隔离。 |
| P0 | 默认 session secret 可预测、cookie_secure 默认 false；runtime token 为空时授权直接放行。用户模型密钥以明文字符串存于数据库。实际生产是否覆盖这些默认值，本次未读取配置，不能推断。 | `backend/app/config.py:17`、`:18`、`:49`；`runtime/src/server.ts:185`；`backend/app/models.py:58`；`backend/app/routers/settings.py:70`。 | 明确环境模式，生产启动 fail-closed；secret manager 或 envelope encryption；轮换、撤销和访问审计；runtime 强制服务身份认证。测试缺失/弱配置启动失败和密钥非明文落库。 |
| P1 | 无组织/成员/角色模型，项目只有 user_id；项目所有者检查已存在。现有授权是个人账号隔离，不是企业 RBAC。 | `backend/app/models.py:31`、`:64`、`:68`；`backend/app/deps.py:42`。 | Organization/Membership/Role/ProjectGrant、最小权限、服务账号、邀请撤销、组织隔离数据访问层；SSO/SCIM 可后续接入。先用两个租户和不同角色跑 API 权限矩阵，不以隐藏按钮代替授权。 |
| P1 | 任务实际运行在进程内 asyncio.Task；启动 reconcile 会把所有历史 running 项目判为 interrupted。多 worker 会互相误判存活任务；重启目前实现明确终态而非 HA 接管。 | `backend/app/services/orchestrator.py:63`、`:148`、`:219`、`:232`；`backend/app/db.py:15`；`specs/002-workflow-integrity/plan.md:5`。 | 持久任务队列、租约/心跳、fencing token、数据库原子领取、重试分类、取消传播、幂等副作用；PostgreSQL 迁移。通过双 worker、kill -9、网络分区、重复投递与租约过期测试验证；不能只把 uvicorn workers 加大。 |
| P1 | durable event 是已有优势，但排序锁和订阅队列均为进程内；seq 读加写不是跨 worker 原子分配，数据库只建普通索引。4000 条尾部保留不能充当合规审计账本。 | `backend/app/events.py:54`、`:57`、`:87`、`:110`、`:143`；`backend/app/models.py:177`。 | 事务 outbox 与原子事件序号、唯一(project_id,seq)、跨进程广播、快照游标补偿；用户体验流与不可变审计日志分离。验证断线补偿、重复消费和慢消费者压力。 |
| P1 | acceptance 验证了完整覆盖，但 passed 仍由客户端提交；没有绑定源文件 digest、契约 revision、浏览器镜像或 runner 身份。发布仅检查 ready 和 index.html，未要求可信验收。 | `backend/app/routers/projects.py:261`、`:276`、`:285`；`backend/app/models.py:180`；`backend/app/routers/publish.py:26`、`:29`。 | Acceptance Evidence 绑定源版本、规格版本、runner 镜像、执行日志和截图；服务端隔离真实浏览器；策略决定哪些环境要求哪些 gates。保留客户端检查作用户反馈，不赋予其认证发布资格。验证伪造报告、过期报告和修改源码后的重新验收。 |
| P1 | 发布直接删除原目录再复制，文件变化和 DB commit 分离；中途失败可能导致线上缺失/部分文件，没有 release 对象或原子指针。 | `backend/app/storage.py:94`、`:96`、`:99`；`backend/app/routers/publish.py:33`、`:42`；`backend/app/models.py:266`。 | 不可变 Artifact/Release、内容 digest、环境晋升、原子切换、前一 release 回滚、部署审批和健康探测。注入复制/存储/DB 故障，证明旧发布继续可用。 |
| P1 | 额度是 demo 的每 turn 固定扣一分。先读余额再扣，没有预算预留；run_id 去重只应用层查询、无唯一约束，跨项目并发可能超用或账目漂移。 | `backend/app/services/credits.py:9`、`:15`、`:35`、`:44`；`backend/app/models.py:249`。 | 预算预留/结算/释放、账本唯一业务键、数据库约束、按组织/模型的成本可见性和上限；并发压测不允许重复计费或未授权透支。 |
| P1 | schema_guard 会检测缺列，但没有版本迁移；注释直接建议生产手工补字段。 | `backend/app/main.py:20`；`backend/app/schema_guard.py:13`、`:35`。 | 引入版本迁移、expand-contract、备份恢复演练、兼容性窗口和迁移 gate；从实际旧 schema 测试升级和回滚路径。 |
| P1 | health API 固定返回 HTTP 200 和 ok:true，即使 runtime:false；Docker curl -f 只检查 HTTP 状态，会误报健康。 | `backend/app/main.py:86`；`Dockerfile:87`。 | 分离 liveness/readiness、依赖超时、数据库/队列/存储健康；记录结构化 trace/run/tenant IDs；SLO、告警、仪表板和故障手册。验证 runtime 不可达会使 readiness 失败而非假健康。 |
| P2 | 登录缺少撤销/限流/企业身份机制；lookup 有意泄露账号存在性。没有在所审计 app/deploy 目录找到 OTel/Prometheus/Sentry/rate-limit/CSRF 的实现。缺少检索命中不是对整个依赖树不存在功能的证明。 | `backend/app/routers/auth.py:46`；`backend/app/security.py:35`；`backend/app/routers/auth.py:93`。 | 统一身份边界、会话撤销、速率限制、审计与安全事件；按威胁模型验证 Cookie/CSRF/Origin 策略。 |
| P2 | 模型列表请求失败时显示硬编码模型作为可选项；用户无法区分真实可用清单与推测值，违背不以假数据代替真实业务的升级目标。 | `backend/app/services/gateway.py:12`、`:47`。 | 保留带 freshness 的最后成功真实目录；未知/不可达状态明确呈现，禁止伪造可用性；模型能力、价格、来源有版本和观测时间。 |

## 值得保留的已实现能力

- `backend/app/services/commands.py:16` 与 `backend/app/models.py:195`：项目范围的 Idempotency-Key、规范化请求摘要、持久 replay；当前单 worker 边界应明确保留到迁移完成。
- `backend/app/services/orchestrator.py:120`、`:148`：取消传播、重启中断终态、部分文件保留；不是简单吞错后显示成功。
- `backend/app/events.py:59`、`:91`：SSE 队列有上限，溢出明确 resync，历史事件可重放。
- `backend/app/storage.py:75` 与 `runtime/src/local-sandbox.ts:138`：路径解析及符号链接校验；仍需与 OS 隔离配合。
- `runtime/src/server.ts:129`：工具权限收窄，现有 builder 不直接开放 shell；不要为了“企业功能丰富”无条件扩大权限。
- `Dockerfile:23`：构建验证 Pi SHA 锁。企业化应围绕 runtime 外围适配、调度和控制面，不改锁定源码。
- `specs/001-generation-reliability/evidence.md`、`specs/002-workflow-integrity/evidence.md`：区分确定性测试、故障注入、真实模型与浏览器验收；保留失败轮次，不把 timeout 的部分成果重分类为成功。
- `specs/002-workflow-integrity/deployment.md`：已有 revision、SQLite 在线备份、数据归档、旧镜像回滚和生产验证记录；这些是过往记录，本次没有重新验证服务器状态。

## Spec Kit 推进建议

1. 新建企业化 feature，保持 001/002 既有完成状态仅覆盖其原范围。将上述事实记录为 Baseline Evidence，不重新宣告所有历史测试“本次通过”。
2. 第一阶段安全基础：provider 凭据边界、独立预览 origin、生产配置校验、可信 runner 设计；先阻断 P0，再允许面向不可信企业用户开放。
3. 第二阶段可靠控制面：组织权限、版本迁移、持久任务/租约/队列、PostgreSQL、事件 outbox、隔离执行。
4. 第三阶段可信交付：规格/任务/代码/验收 digest 关联、不可变 release、发布策略与回滚、审计和成本账本。
5. 第四阶段规模与运营：压力/混沌测试、SLO、备份恢复、容量/成本规划、企业身份集成。

每一阶段都要在 spec 给出用户可观察行为，在 plan 明确依赖边界和失败语义，在 tasks 拆解实现/调试/测试/验收，在 evidence 记录实际命令、revision、环境和结果。单服务器部署可以达成可恢复性，不能声称消除了宿主机单点；真正 HA 必须有独立故障域和实际 failover 演练。

可形成差异化的产品方向：把 Spec Kit 追踪关系变为平台的证据链，而非只是仓库文档；把多模型候选赛跑升级为“在同一规格、预算、安全策略和真实测试条件下比较可验证成果”；把发布前缺失证据变成清晰可执行的下一步。以上是设计建议，尚未实现或验收。
