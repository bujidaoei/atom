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


008 T033 archive format/recovery-core increment:60 codec/planner checks pass, including actual independent subprocess recovery of full business-generated event dictionaries. Strict bounded canonical format binds captured context/plan metadata and requires an externally supplied archive digest. Durable storage, protected manifest authority, persisted recovery receipts and enterprise rollout remain open. See ../008-sandbox-broker/evidence.md; T033/T034 are not accepted.


008 T033 local storage increment:9 actual Linux filesystem/process cases and1 independent-volume writer-removal/read-container test pass for private no-overwrite audit archives. Protected manifest authority, persisted recovery receipts and service integration remain open; local durability is not legal/cloud immutability or production acceptance. Details: ../008-sandbox-broker/evidence.md. T033/T034 remain unchecked.


008 T033 offline schema9 increment: immutable archive manifests and separate recovery receipts added with74 migration/constraint/recovery tests passing. Protected ledger service integration and runtime9 compatibility remain open; metadata constraints do not prove archive IO or recovery. No serving upgrade or deletion authority. Details in ../008-sandbox-broker/evidence.md; T033/T034 remain unchecked.


008 T033 service increment: actual Linux archive publication/readback, source/context revalidation and immutable9 manifest/recovery registration connected.111 tests pass including8 real Linux integration scenarios and retention8/9 authority regression. Operator workflow/configuration and ordinary runtime9 acceptance remain open; no pruning/deployment. Details: ../008-sandbox-broker/evidence.md; T033/T034 stay unchecked.


008 T033 operator workflow: explicit archive/inspect/recover CLI and source-fenced continuation implemented;11 actual Linux integration cases pass, including102 real business events over100+2 pages and hold-after-first-page rejection. See ../008-sandbox-broker/evidence.md. Ordinary runtime9 and enterprise production acceptance remain open; T033/T034 unchecked.


008 schema9 compatibility increment:377 business/governance/main-TLS,64 revision9 and11 actual Linux archive tests pass. Ordinary consumer exact allowlists now include9; new destination/archive race uses real governance commands. Full runtime/browser/production9 acceptance and T033/T034 remain open. Detailed evidence: ../008-sandbox-broker/evidence.md.


008 schema9 runtime/browser evidence:6 actual main/own-runtime/broker cases and Chromium private-content login/revocation flow pass; Pi1905 locked files verified. This narrows previous compatibility gaps but does not prove live model, trusted verifier or production acceptance. T033/T034 remain open. See ../008-sandbox-broker/evidence.md.


008 T033 acceptance audit found and reproduced a recovery authority gap: in-process restore still has source database write access. Existing byte-recovery receipts are not isolated verification. Added unchecked T035 for fixed broker-owned recovery execution and versioned evidence before T033 acceptance; official sources and actual Linux negative evidence are in ../008-sandbox-broker/contracts/audit-governance.md and evidence.md. Enterprise acceptance remains open.


008 T035 worker foundation: fresh fixed broker-owned recovery execution and confirmed cleanup implemented;98 tests pass including4 actual isolated-container success/failure cases. Administrative transport and versioned receipt integration remain open; current CLI still has the documented in-process authority gap. T035/T033/T034 remain unchecked. Details: ../008-sandbox-broker/evidence.md.


008 T035 admin recovery endpoint implemented with authentication, bounded intake/send and cancellation-owned cleanup.24 ASGI/actual-Docker HTTP boundary tests pass. Client and versioned receipt integration remain open; current archive CLI is not yet isolated. See ../008-sandbox-broker/evidence.md.


008 T035 bounded client:42 client/transport checks pass including actual socket broker plus isolated Docker restore and strict provenance/full-payload rejection tests. No grant-signing key required by recovery client. Versioned receipt/owner wiring still open; T035/T033/T034 unchecked. See ../008-sandbox-broker/evidence.md.


T035 abrupt broker-death evidence (2026-10-01): real child processes exit with os._exit(73) after provisioning before restore, after full restore before cleanup, and after actual container removal before durable termination confirmation. Fresh Lifecycle startup reopens the same registry/lease, reconciles each interrupted attempt to terminated before readiness, and leaves no owned containers. A subsequent explicit call performs a fresh full-field restore with a distinct attempt; interrupted calls produce no successful return. Seven actual-container tests pass (40.482s, zero failures/errors/skips), including existing source/mount/socket denial and exit/output/timeout cases. This closes the previously untested internal recovery crash/restart boundary only. Versioned source receipts and archive owner/CLI integration remain open; schema9 historical receipts are unchanged. T035/T033/T034 remain unchecked.


T035 distinct receipt schema foundation (2026-10-01): explicit offline schema10 adds security_audit_isolated_recoveries with protocol fixed to audit-recovery-v2, pinned image, policy digest, verifier/attempt identity, exact archive/payload digests/count, complete canonical response digest and verification time. Archive relationship/time constraints and immutable update/delete/primary-key/alternate verifier-attempt replacement guards apply. Historical schema9 receipts remain untouched and are never promoted; migration creates no isolated evidence.62 migration/constraint/backup tests pass (9.642s, no failures/errors/skips), including sources0..9, full backup restoration, actual pre/post-commit process death, late rollback, CLI preservation and schema10 receipt backup. Frozen migrations1..9 are unchanged. Owner/CLI issuance and ordinary serving compatibility with10 remain unimplemented; do not migrate serving/production databases to10. T035/T033/T034 remain unchecked.


T035 archive owner isolated receipt integration (2026-10-01): AuditArchiving.recover_isolated reads bounded committed bytes using the immutable ledger digest, validates every manifest anchor, calls the real configured AuditRecoveryClient and only then commits distinct schema10 evidence. The canonical full broker envelope digest is persisted. The write transaction rechecks the exact archive row; same recovery ID requires archive/verifier/image/policy identity and returns existing evidence after store validation without rerunning recovery. No source transaction spans network IO. Source file preparation is read-only in a worker thread; cancellation before successful transport cannot schedule a write, while the bounded final transaction is synchronous and owned. RetentionRepository supports exact8/9/10; archive publication/inspection supports9/10, and legacy recover refuses10. Inspection reports isolated and historical receipt counts separately.99 tests pass (61.849s, zero failures/errors/skips), including six real Linux store/network/broker/worker scenarios and retention8/9/10 plus legacy archive regression; the six scenarios were rerun successfully after adding inspection-count assertions. CLI isolated recovery, receipt commit-crash acceptance and ordinary serving10 compatibility remain open. T035/T033/T034 remain unchecked; no production migration/deletion/deployment.


T035 operator CLI and receipt commit-death acceptance (2026-10-01): archive_admin now exposes recover-isolated with required archive/recovery/verifier IDs, broker origin, expected pinned image and policy digest. It reads the existing ATOM_BROKER_ADMIN_TOKEN environment variable, never a command-line secret, and reports bounded error codes/receipt metadata without raw archive events. Nine actual Linux owner/network/broker/worker scenarios pass (45.189s, no failures/errors/skips), including actual CLI process death immediately before/after its isolated receipt COMMIT. Before-commit death leaves zero receipts and explicit retry performs a second real worker attempt; after-commit death leaves one receipt and retries return identical persisted evidence with one total worker attempt. Missing credentials fail safely; exact replay and distinct historical/isolated inspection counts are verified. Three legacy CLI/multi-page regressions also pass. This supersedes prior CLI-not-connected and receipt-commit-crash-not-tested statements only. Serving10 integration, deployment TLS/configuration and full T035/T033 acceptance remain open; T035/T033/T034 stay unchecked. No production migration, pruning, push or deployment occurred.


Schema10 serving compatibility increment (2026-10-01): access/content/revision/verification/publication/audit consumers now explicitly admit exact schema10 and preserve full schema/journal checking inside owning transactions. Governance and delivery retain existing generation/registry state behavior; ordinary schema8 serving remains unsupported.457 business/audit/crash/governance/export/main-TLS tests pass (117.661s),64 schema10 revision repository tests pass (17.306s), and6 real main/own Node runtime/broker/container scenarios pass on10, all without failures/errors/skips. Runtime covers valid/invalid/disconnected model output, cancellation, deadline and checkpoint deadline, with synthetic model stream and export disabled; main TLS export is separate actual receiver evidence. Pi1905 files verify against f07218c4d4bbc12bef056a7058c3dd49dfe41abe. This supersedes earlier serving10/runtime10-not-integrated statements at these tested scopes only. Browser10, live model/verifier, deployment TLS/configuration and full retention acceptance remain open. T035/T033/T034 remain unchecked; no production database migration, push or deployment.
