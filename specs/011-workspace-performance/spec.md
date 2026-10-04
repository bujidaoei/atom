# Feature Specification: 工作区打开性能

**Feature Branch**: `codex/011-workspace-performance`
**Created**: 2026-10-04
**Status**: Implementation in validation; production acceptance pending
**Input**: 用户报告每次点击项目打开工作区很慢，要求深入线上排查、根因修复、真实验收、同步 GitHub main 并部署。

## User Scenarios & Testing

### User Story 1 - 快速打开已有项目 (Priority: P1)
用户点击项目后及时看到真实工作区，而非长时间等待历史活动重放。
**Independent Test**: 在真实线上已有项目中测量点击到工作区标题、对话和控制区可见的时间，同时记录请求数量和耗时。
**Acceptance Scenarios**:
1. Given 已有完成或失败项目，When 首次打开，Then 工作区读取真实持久化状态，不等待所有历史活动刷新完成。
2. Given 多个历史状态变化，When 重连和重放，Then 不按每条历史变化重复读取整个工作区，最终状态正确。

### User Story 2 - 快速切换与故障恢复 (Priority: P1)
**Independent Test**: 快速切换两个项目，注入读取延迟、失败和断流，检查隔离、错误提示和恢复。
**Acceptance Scenarios**:
1. Given A 的请求尚未结束，When 切换 B，Then A 不覆盖 B，废弃读取被取消。
2. Given 请求超时或失败，When 打开项目，Then 有界时间内显示真实可重试错误；后台更新失败保留已显示内容。
3. Given 活动生成，When 实时状态变化，Then 界面最终与持久状态一致，且无无限并发读取。

### User Story 3 - 可追溯安全发布 (Priority: P2)
**Independent Test**: 对照发布前后同批真实项目、受保护备份、提交和镜像标识、服务健康。
**Acceptance Scenarios**:
1. Given 完整测试证据，When 发布，Then 可追溯 GitHub 分支/main 和实际服务镜像，用户数据与既有功能保持完整。

### Edge Cases
- 空项目、竞速多候选、大量历史事件、没有已登记版本。
- 历史重放和实时更新交错、断线重连、慢网络、对象存储失败、版本在读取中变化。
- 未授权用户、其他用户项目、损坏制品、会话撤销。
- 预览工具栏窄容器、侧栏切换、字体加载/缩放：文字不得折成竖排；宽度充足时自动恢复。

## Requirements
### Functional Requirements
- **FR-001**: 通过实际服务器与浏览器采样确定根因，分别记录服务端与用户可见耗时，不把推测写成结论。
- **FR-002**: 初次成功读取即可展示工作区；重复刷新必须有界且不让旧结果覆盖新项目。
- **FR-003**: 保持鉴权、版本归属、制品完整性和错误语义，禁止用假数据或过期授权缓存提速。
- **FR-004**: 导航结束必须清理读取和订阅；网络失败提供可重试反馈。
- **FR-005**: 配套回归、并发/故障测试及真实线上浏览器验收；规格/方案/任务/证据同步。
- **FR-006**: 保留 SHA-locked Pi、未提交无关工作，发布前备份并记录恢复步骤。
- **FR-007**: 预览工具栏根据实际容器及完整内容的渲染宽度动态决定显示图标或图标加文字，不使用固定屏幕断点；按钮保持可访问名称和提示，网址可省略显示。

### Key Entities
- Workspace snapshot: 用户有权读取的当前项目、版本、文件、对话、候选和事件位置。
- Refresh lifecycle: 首次读取、后台刷新、重放、取消、失败和恢复状态。
- Release evidence: 源码版本、镜像、备份、实测结果与未通过的门禁。

## Success Criteria
### Measurable Outcomes
- **SC-001**: 同批至少三个真实已有项目、至少十次打开，用户可见耗时 p95 相比基线降低至少 60%，目标不超过 2 秒（健康网络）。
- **SC-002**: 历史状态事件突发不按事件数产生详情请求；每个工作区最多一个活动详情读取且最多合并一个待刷新。
- **SC-003**: 快速切换、延迟、失败、重连测试全部通过，未授权读取不成功，损坏制品不被当成有效数据。
- **SC-004**: 发布后实际版本与提交一致，健康、预览和已有发布站点通过实测，备份与恢复流程可追溯。
- **SC-005**: 连续调整工具栏宽度及侧栏开关时，文字不换行、不溢出，空间不足仅显示图标、充足自动恢复；字体宽度变化后重新计算，所有按钮仍可操作。

## Assumptions
- 用真实线上版本 fd191e5 为基线；origin/main 落后于线上，最终需保留线上功能再同步。
- 本次包含打开/刷新链路、工具栏自适应与 CR-002 生成等待策略；不改变模型选择、计费、发布策略或数据库业务语义。
- 生产浏览器探针仅使用短期会话、读取已有项目，测试会话结束撤销。

## Change CR-002: slow gateway tolerance
- FR-008: Generation defaults to 3600 seconds, configurable with project .env ATOM_BUILD_BUDGET_SECONDS and ATOM_RUN_TIMEOUT_SECONDS. Model waits, sidecar and race defaults inherit the effective budget; remove hidden 180/300/1800-second limits.
- FR-009: Preserve cancellation, durable terminal outcomes and broker security. Supported generation maximum is 7140 seconds plus 60 seconds cleanup; reject invalid configuration explicitly. Optional model timeout cannot be shorter than turn budgets.
- SC-006: Real delayed HTTP protocol test succeeds across the old 300-second boundary; persisted short provider timeout cannot override this run. Cancellation remains prompt. Distinguish protocol fixtures from live AI acceptance.
- Scope amendment: generation lifetime joins workspace performance and toolbar fit; model selection, billing and publishing semantics remain unchanged.
