# Feature Specification: Atom 企业级交付基础

**Feature Branch**: `codex/003-enterprise-foundation`
**Created**: 2026-09-30
**Status**: Draft — 研究进行中；本规格下产品能力均未验收
**Input**: 基于 Atoms 全流程和主流商业开发产品官方资料升级 Demo；使用自有 runtime，不复刻 UI；Spec Kit 管理全生命周期，最终交付指定 GitHub 和服务器。

## User Scenarios & Testing

### User Story 1 - 可信执行边界 (Priority: P1)
作为组织管理员，我希望生成代码、预览和连接器只能访问任务明确授权的资源。
**Why this priority**: 共享执行环境与跨项目访问风险阻断商业使用。
**Independent Test**: 两组织各两个项目，以无生产凭据的样例测试跨项目访问、预览脚本、网络出口和授权撤销。
**Acceptance Scenarios**:
1. **Given** 项目 A 的程序，**When** 访问项目 B 或控制台会话，**Then** 拒绝并产生脱敏审计记录。
2. **Given** 默认模型凭据，**When** 成员更换服务地址，**Then** 默认凭据不能流向新地址，无授权组合则拒绝执行。
3. **Given** 已撤销权限，**When** 旧会话调用敏感操作，**Then** 执行前重新鉴权并拒绝。

### User Story 2 - 可恢复且有预算的长任务 (Priority: P1)
作为开发者，我希望提交、排队、停止和重试有真实状态与累计成本，不因刷新或重启产生重复副作用。
**Why this priority**: 可靠执行决定自动开发工具是否可以持续使用。
**Independent Test**: 中断浏览器、停止工作进程、重复投递请求并核对恢复与账目。
**Acceptance Scenarios**:
1. **Given** 已接受任务，**When** 工作进程退出，**Then** 120 秒内显示恢复或明确终止，保留原始证据。
2. **Given** 重复请求，**When** 重试，**Then** 不重复业务提交或计费；不同内容使用同一请求身份被拒绝。
3. **Given** 预算耗尽，**When** 请求后续付费操作，**Then** 停止新增操作并显示实耗和未完成事项。

### User Story 3 - 证据驱动的版本与发布 (Priority: P1)
作为验收者，我希望需求、代码、测试和生产版本逐项关联，代理的完成声明不替代验收。
**Why this priority**: 防止虚假完成是企业可信交付的基础。
**Independent Test**: 真实生成小应用，执行成功与失败验收，随后修改版本并检查发布阻断。
**Acceptance Scenarios**:
1. **Given** 缺少真实测试证据，**When** 申请验收或发布，**Then** 保持未验收并列出缺口。
2. **Given** 已验证版本，**When** 代码或关键配置改变，**Then** 旧证据不能用于新版本通过结论。
3. **Given** 发布失败，**When** 恢复已知可用版本，**Then** 验证线上业务并明确数据库和外部操作的恢复边界。

### User Story 4 - 企业协作与可迁移交付 (Priority: P2)
作为团队，我希望从现有仓库开始，分别管理编写、审批、发布和审计，并导出可重建交付物。
**Why this priority**: 企业已有代码与流程，升级应支持渐进接入。
**Independent Test**: 独立测试仓库与不同角色完成需求到审阅、发布、撤销访问流程。
**Acceptance Scenarios**:
1. **Given** 授权仓库，**When** 提交代理改动，**Then** 独立变更接受审阅，不能覆盖冲突或绕过保护。
2. **Given** 普通成员，**When** 请求生产发布或修改策略，**Then** 按权限拒绝；授权角色可执行。
3. **Given** 交付版本，**When** 干净环境重建，**Then** 依赖、配置要求和产物可核验，无隐含秘密依赖。

### Edge Cases
- 停止与完成竞态、过期工作进程回写、供应商超时但已计费。
- 事件游标过期、重复回调、跨组织对象枚举、执行中撤销权限。
- 恶意预览脚本、提示注入、重定向和内部网络访问。
- 仓库双向冲突、数据库结构不兼容、无法撤回的第三方操作。
- 单机故障、备份不可恢复、测试报告与最新代码不一致。

## Requirements
### Functional Requirements
- **FR-001**: 项目、运行、文件、事件、费用、连接器与证据访问必须校验组织和项目范围，默认私有。
- **FR-002**: 平台秘密与不可信执行隔离；凭据绑定授权目的地，日志与导出脱敏。
- **FR-003**: 工具执行最小权限；任务策略不能放宽组织策略。
- **FR-004**: 任务具有持久状态、截止时间、停止确认、恢复语义与重复保护。
- **FR-005**: 预算可预留、结算、释放和对账；并发不能超额预留，失败记录已发生消耗。
- **FR-006**: 验收结论绑定需求、版本、环境、时间和真实证据，未经验证不得完成。
- **FR-007**: 发布与编辑权限分离；只有满足组织门禁的同版本产物可发布。
- **FR-008**: 发布包含可核查备份、健康检查与恢复记录；不能把代码恢复当作数据恢复。
- **FR-009**: 支持现有仓库受控变更、显式冲突处理与可复现导出。
- **FR-010**: 保留自有 agent runtime 与锁定 Pi；升级走独立变更与回归。
- **FR-011**: specification、plan、tasks、代码和证据同步，区分事实、假设和实测。
- **FR-012**: 操作者可关联任务错误、耗时、资源、供应商故障与部署版本，且不泄漏秘密。

### Key Entities
- Organization / Membership / Project：所属关系、角色和授权范围。
- Execution / Attempt / Command：意图、尝试、状态和去重身份。
- Budget / UsageEntry：预留、实耗和结算。
- Requirement / Revision / Evidence / Acceptance：可追溯交付关系。
- ConnectorGrant / PolicyDecision：授权范围和执行决策。
- Release / Backup / RecoveryRecord：生产版本与恢复证据。

## Success Criteria
### Measurable Outcomes
- **SC-001**: 权限矩阵中跨组织和未授权请求全部拒绝，测试秘密不出现在日志和导出。
- **SC-002**: 100 次重复投递、20 次进程故障中无重复业务提交，已接受任务 120 秒内明确恢复或终止。
- **SC-003**: 100% 验收和发布结论关联同版本真实证据，变更后不错误复用旧结果。
- **SC-004**: 10 个并行任务无超额预留、重复结算或漏记已知消耗。
- **SC-005**: 隔离环境备份恢复 30 分钟内恢复业务，数据恢复点损失不超过 5 分钟；须实测后才能宣称达到。
- **SC-006**: 初始拟定容量为 50 在线成员、10 并行执行，非生成操作 95% 在 2 秒内完成；记录资源规格。
- **SC-007**: 可用性目标 99.9%/月，需观测窗口和冗余故障演练；单机部署不等于满足。

## Assumptions
- 当前先研究，未经验证不启动大规模重写；暂以私有部署友好和组织隔离为基线，市场定位答复可调整阶段顺序。
- 指定服务器是首个交付环境，容量与拓扑未核验，不能承诺单机高可用。
- 竞品文档能力与实测严格分开；生成积分额度等待明确授权。
- 首期不含广告投放、营销增长、模型训练、替换 runtime 和 UI 复刻。
- 数值是拟定验收目标，不是测量结果或对外 SLA。


FR-008/FR-012 design refinement from official Atoms/GitHub/GitLab research: recovery evidence should state source/current revision, schema/data recovery point, publication generation, unresolved external effects and audit coverage independently. Audit retention must preserve historical receiver obligations absent from current config. Proposed governance/recovery-manifest contract is in008/contracts/audit-governance.md; no new acceptance/SLA claim.


008 T033 progress (2026-10-01): bounded exact8 read-only retention planner and operator CLI implemented,59 planner/authority/migration checks pass; details in ../008-sandbox-broker/evidence.md and contracts/audit-governance.md. Context/generation fencing includes active holds and all relevant registered destinations; output explicitly grants no deletion authority and has no archive validation. Archive/independent restore/runtime8 compatibility/production rollout remain open. This is a component increment, not enterprise acceptance.
