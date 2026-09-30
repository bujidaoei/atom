# 商业级 AI 开发产品研究：第一轮官方证据

研究日期：2026-09-30。状态：文档研究完成一轮，产品账户实测、压力/安全验证、Atom 实现与整体验收均未完成。所有事实只使用下列官方页面；“建议”是设计推论，不是产品现有能力或 Atom 已完成功能。价格与功能持续变化，本报告不固定套餐报价，不作采购排名。部分页面没有发布日期，日期代表访问日期。已读取项目 constitution；不修改 SHA-locked runtime/pi。

## 1. 比较对象与流程

| 产品 | 官方证据支持的核心流程 | 企业机制及需要正视的限制 | 对 Atom 的建议（未实现） |
|---|---|---|---|
| Cursor | 云端隔离环境执行任务，自动运行命令、迭代测试；前台/后台自治边界不同 | 官方明确自动命令和互联网访问带来提示注入/数据外流风险；必须在环境层控制网络、秘密与仓库范围 | 运行前展示能力范围；由控制面发放任务范围权限，在隔离 worker 执行，不把自然语言提示当安全边界 |
| GitHub Copilot cloud agent | 任务→受限运行环境→分支/草稿 PR→人工审查合并 | 代理不能批准/合并 PR；默认工作流运行有人工门槛，可配置自动运行 | 编写权、CI 执行权、合并权、生产发布权分别授权；PR 不等于已验收 |
| Devin | 仓库与环境准备→明确目标→可接管 IDE/终端/浏览器→PR→既有交付流水线 | 企业策略限制网络、MCP、Git、gh 凭据；强制策略只能收紧；会话超过 30 天不能继续 | 每任务稳定工作区和运行记录；持续目标靠持久产物/证据续接，不能只依赖长会话 |
| Replit | 规划→构建→项目/会话 checkpoint→预览→独立生产发布 | checkpoint 与生产数据库恢复范围必须分清；发布隐私策略有不追溯既有应用的情形 | 预览、生产、数据库恢复明确分离；恢复先显示影响范围并实际演练 |
| Lovable | 自然语言→真实应用与可编辑代码→预览迭代→发布；Git sync 接入工程流程 | 发布扫描、角色控制、发布对象控制是不同机制；安全发现默认不一定阻断发布 | 发布门槛成为确定性的服务端策略；明确“谁能修改/谁能发布/谁能访问” |
| Bolt | 提示构建→可视/代码编辑→预览→版本历史→发布 | 主要支持 JavaScript 后端；移动端缺少版本历史等管理能力，移动端发布为公开可见 | 项目创建先做能力适配检查；所有客户端应用相同的服务端发布策略 |
| Claude Code | 探索/规划→工具执行→验证→审查；支持权限、系统级隔离、会话恢复 | checkpoint 不跟踪 Bash 文件改动；沙箱缺失时默认可退化为无沙箱，需 failIfUnavailable 强制失败 | 恢复覆盖范围可查询；隔离不可用时失败关闭；执行后以实际产物验证恢复 |

来源：[Cursor 安全](https://cursor.com/docs/cloud-agent/security)、[GitHub 风险与缓解](https://docs.github.com/en/copilot/concepts/security-governance-and-network-settings/risks-and-mitigations)、[Devin 概览](https://docs.devin.ai/get-started/devin-intro)、[Devin 发布](https://docs.devin.ai/product-guides/deployment-capabilities)、[Replit 版本控制](https://docs.replit.com/replit-workspace/workspace-features/version-control)、[Lovable 概览](https://docs.lovable.dev/introduction/welcome)、[Bolt 支持范围](https://support.bolt.new/concepts/supported-technologies)、[Claude checkpoint](https://code.claude.com/docs/en/checkpointing)。

## 2. 最有价值的机制与反例

### 2.1 权限需要可组合、不可被下级放宽

**官方事实**：Devin 强制安全 profile 在企业、组织、自动化、会话之间取更严格结果；网络/MCP allowlist 取交集，Git 只读优先，任一层移除 gh token 即移除。自托管 Outposts 的网络策略由运营方实施，控制台中存在策略不代表网络实际隔离。[Security Profiles](https://docs.devin.ai/product-guides/security-profiles)

**建议**：Atom 用组织→项目→环境→run 的确定性策略求交；将策略版本/生效权限写入 run 证据。给 worker 配置策略仍不足够，必须用真实拒绝测试证明禁止访问其他租户、宿主机与外网。保留自有 AgentRuntime，把授权和隔离放在它外围，不修改锁定 Pi 源码。

**官方事实**：Claude 沙箱把文件/网络限制施加给命令及子进程；可关闭无沙箱重试，配置 failIfUnavailable 阻止隔离缺失时继续执行；原生 Windows 不支持该沙箱，需要 WSL2。[Sandboxing](https://code.claude.com/docs/en/sandboxing)

**建议**：本地 Windows 开发成功不证明 Ubuntu 生产隔离有效；执行环境能力探测失败应阻止 run，而不是静默降级。

### 2.2 生成、测试、发布是三个不同的信任边界

**官方事实**：GitHub 限制代理凭据，并保留人工 PR 审查/合并和默认工作流审批。其设计明确承认注入风险并靠权限限制降低影响。[Risks and mitigations](https://docs.github.com/en/copilot/concepts/security-governance-and-network-settings/risks-and-mitigations)

**官方事实**：Lovable 发布对话框执行 Quick scan；Deep scan 为独立深度扫描。默认发现不阻断，管理员可阻断 critical，新的 Enterprise workspace 默认启用该阻断。企业可限制外部发布角色。构建失败会阻止发布。[Publish](https://docs.lovable.dev/features/publish)

**建议**：Atom 应保留 reviewable revision，验收证据绑定 commit SHA、artifact digest、测试命令、退出码和环境。测试运行之后代码/配置发生变化即使旧证据失效。不要因 agent 声称完成就把任务标绿。

### 2.3 恢复不等于聊天回退，也不等于数据库回退

**官方事实**：Claude checkpoint 只覆盖其文件编辑工具的修改，Bash 删除/移动/复制无法通过 rewind 撤销；保留范围受快照数量与保留策略约束。[Checkpointing](https://code.claude.com/docs/en/checkpointing)

**官方事实**：Replit 提供包含项目状态和会话上下文的 checkpoint；数据库恢复可选。生产数据库时间点恢复不恢复应用版本，需要应用回退并重新发布。[Checkpoint/rollback](https://docs.replit.com/features/version-control/checkpoints-and-rollbacks)、[Production database](https://docs.replit.com/pt/references/data-and-storage/production-databases)

**官方事实**：Bolt 从 backup 创建 fork 可保留当前版本；QuickStart 说明版本回退不耗 tokens，同时指出直接代码编辑的覆盖限制。[Project settings](https://support.bolt.new/building/using-bolt/project-settings)、[QuickStart](https://support.bolt.new/building/quickstart)

**建议**：定义四类恢复：会话续接、工作区恢复、应用版本回滚、数据恢复。每项都有覆盖范围、前置备份、外部副作用清单及成功验证。付款、邮件、第三方 API 调用不能虚假宣传“一键全部撤销”。

### 2.4 成本治理应约束动作，而非仅展示 token

**官方事实**：Devin Enterprise 提供组织/用户 ACU 上限，组织达到上限阻止新的计费工作，用户上限独立有效；具体单价来自企业合同。[Enterprise billing](https://docs.devin.ai/admin/billing/enterprise)

**官方事实**：Replit 支持按项目/资源/成员等查看用量；usage limit 与 service shutdown limit 会影响服务可用性；企业有成员限额。[Managing spend](https://docs.replit.com/billing/managing-spend)

**官方事实**：Lovable 有 workspace 默认及成员 credit 上限，区分 Build、Cloud、AI gateway、connector 消费。[Enterprise controls](https://docs.lovable.dev/introduction/lovable-for-enterprise)

**官方事实**：Claude 将本地估算与账单区分；组织可用管理员限额、API workspace 限额或云预算；OpenTelemetry 提供近实时成本/token 指标。[Costs](https://code.claude.com/docs/en/costs)

**建议**：Atom 引入组织/项目/run 多层预算，调用前预留、调用后结算、失败释放、重试幂等；区分模型消耗和生产托管费用，避免开发 token 耗尽意外停止线上业务。预算失败要成为持久 terminal outcome，并保留续跑上下文。

### 2.5 私有项目并不自动意味着私有预览或私有上线

**官方事实**：Replit 区分开发 URL 和生产部署权限；新发布隐私策略不自动改变既有应用，私有开发 URL 则可追溯。禁 ZIP 导出不等于所有外流路线被阻断；部署地域也不保证第三方服务数据地域一致。[Privacy/deployment](https://docs.replit.com/teams/privacy-and-deployment-settings)

**建议**：Atom 每个资源有显式 audience、owner、environment，设置变更展示受影响的既有对象并检测漂移；预览 token 短时、绑定用户/项目/版本，不能只依赖随机 URL。

## 3. 官方已知限制登记

| 条目 | 官方证据 | Atom 验证要点 |
|---|---|---|
| 自动命令存在提示注入和外流风险 | Cursor 安全页 | 恶意仓库说明/网页不能扩大权限；出口代理和秘密注入实测 |
| 过期会话不能续接 | [Devin Common Issues](https://docs.devin.ai/admin/common-issues) 指出 30 天后需新会话重给上下文 | 目标、需求、决策、证据独立持久化，不依赖活会话 |
| Github/Slack 组织连接可能已绑定别的 Devin 账户 | 同上 Common Issues | 集成连接归属可诊断、撤销/迁移有记录，不无限重试 |
| shell 修改不包含在会话 checkpoint | Claude checkpoint 页 | 使用 shell 写文件、删除、迁移后验证真实恢复边界 |
| 自托管安全策略需要基础设施执行 | Devin Security Profiles | policy 显示 enabled 但网络可访问时必须判失败 |
| 发布扫描不总是默认阻断 | Lovable Publish | 模拟 critical/扫描超时/无结果/旧结果，服务端均正确处理 |
| 私有发布新策略不自动修正既有应用 | Replit Privacy/deployment | 策略变更影响评估、存量风险列表及逐对象修复 |
| JavaScript 后端限定及移动端能力差异 | Bolt Supported technologies | 根据运行环境做能力检查，不在任务执行一半才发现不支持 |

以上是官方承认的边界/常见问题，不代表已调查所有公开故障、安全事件或账号内操作。

## 4. Atom 可形成的独特优势（设计候选）

1. **以证据驱动的交付进度**：Spec Kit 的需求→方案→任务→代码→测试→部署形成可追溯关系。每个完成标记必须有同版本真实证据，UI 展示“已编码/已验证/已上线”的独立状态；证据过期自动撤销验收状态。
2. **可解释的自主执行**：run 开始前得到能力、预算、截止时间；执行中显示批准来源和实际操作；结束后给出成功/失败/取消/超时等确定结局，断线后可恢复追踪。用户理解系统在何处等待和如何继续。
3. **可验证的企业私有交付**：使用自有 runtime，控制面与隔离 worker 分离，环境、发布包、数据迁移有各自版本和恢复合同；通过故障注入证明可恢复，而非仅给“回滚”按钮。
4. **项目级成本与结果对账**：把消耗关联到需求与验收结果，度量有效交付成本、重试浪费和恢复时间，避免把 token 数、生成行数当生产力。

这些是组合与工程化方向，不声称市场独有，也不宣称 Atom 已拥有。进入 specification 前仍需结合现有代码、目标用户与真实验收条件确定优先级。

## 5. 下一轮必须补充的证据

- 七产品账号内的真实 create→plan→build→test→review→publish→rollback 流程；未购买/登录的能力不能写成已验证。
- Cursor 的当前组织预算实际阻断语义、Github 当前计费限制、Bolt 的企业权限/数据库恢复语义，尚未获得足够页面级证据，保持未知。
- 各产品状态页与官方 release notes 中的实际事故、修复日期、SLA、RTO/RPO；当前仅完成文档边界比较。
- 同一有验收标准的小项目基准：真实模型、同一仓库、相同权限、成本、成功率、人工干预、失败恢复，不以官网营销描述估算效果。
- Atom 现有实现逐项 gap mapping，由主任务结合 code/spec/plan/tasks 完成；本子研究未读应用代码，不能认定缺失项已存在或已解决。
- 所有高可用、安全、灾备与线上验收维持未完成，直到对应测试/部署证据入库。

## Recovery-boundary refinement (2026-10-01)
Rechecked Replit's official checkpoint documentation: project/context restoration is distinct from optional development-database restoration, and production-database restoration is not automatic in that operation. Source: https://docs.replit.com/features/version-control/checkpoints-and-rollbacks . Its development/production documentation separates the environments, says Agent cannot directly modify production data, and discusses planned schema changes during publishing and isolated deployment previews. Source: https://docs.replit.com/features/data-and-storage/development-and-production . These are documented capabilities, not paid-account hands-on acceptance. The attempted Lovable version-history URL did not return usable content; no conclusion relies on it.

Atom design inference: show recovery scope explicitly across files, development data, production data, agent context and external effects. An immutable file revision must never promise complete environment rollback. Keep checkpoint durability, execution termination, independent acceptance and publication as separate evidence. Current 008 implements file artifacts and the registration ledger only; database restore is a separate offline operator workflow, and product-level recovery UX, database policy and preview acceptance remain open. This is a proposed cohesive product advantage, not a claim that competitors lack these capabilities.

## Release identity refinement (2026-10-01)
Retrieved https://docs.lovable.dev/features/publish successfully: snapshot publication, explicit updates, unpublished edits, audience controls and configurable critical-security blocking. This is documentation evidence, not hands-on acceptance or verification of the previously unavailable history page. Replit historical article https://replit.com/blog/introducing-deployment-rollbacks (updated 2024-08-30) describes new rollback deployments, configuration differences and retained-build constraints; its old numeric retention is not treated as current policy.
Atom source audit confirms mutable publication/adoption and timestamp/client-reported acceptance. Derived design: exact artifact/contract/verifier identity, transactional release pointer, explicit audience and recovery scope. See specs/008-sandbox-broker/contracts/revision-release.md. Intended capabilities are not claimed implemented or exclusive.

## Browser trust-boundary refinement (2026-10-01)
Source audit identifies same-origin preview/API routing and parent DOM-based acceptance in Atom. Mozilla MDN documents origin scheme/host/port, host-scoped secure cookies and CSP sandbox origin behavior. Exact links and derived design are in specs/008-sandbox-broker/contracts/content-origin.md. The design binds each serving version to a dedicated content host and separates private access and independent verification. This is architecture evidence, not a tested browser guarantee or a competitor exclusivity claim.
