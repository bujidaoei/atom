import type { WakeyNotificationPage, ReadWakeyNotifications } from './wakey-notifications.ts';
import type { V3CopySkillInput } from './skill-copy.ts';
import type {
  PluginCatalogInput,
  PluginCatalogPage,
  InstalledPlugin,
  InstallMarketPluginRequest,
  SetPluginEnabledRequest,
  UninstallPluginRequest,
  RetryPluginRequest,
  PluginInstallationRevision,
  PluginMarketComposition,
} from './v5-plugins.ts';
import type { ConnectorCatalogInput, ConnectorCatalogPage, ConnectorMarketDetail } from './v5-connectors.ts';
import type {
  V3Approval,
  V3WorkflowAutomation,
  V3WorkflowAutomationDispatchInput,
  V3CreateWorkflowAutomation,
  V3UpdateWorkflowAutomation,
  V3DeleteWorkflowAutomation,
  V3ApprovalWorkItem,
  V3AvatarObject,
  V3Artifact,
  V3Bootstrap,
  V3AiGatewayVirtualKeyInput,
  V3AiGatewayVirtualKeyStatus,
  V3AiGatewayVirtualKeyClaimResponse,
  V3LanguageSetting,
  V3LanguageSettingInput,
  V3ConversationArtifactManifest,
  V3Conversation,
  V3ConversationAttachment,
  V3ConfirmGroupPlan,
  V3CreateConversation,
  V3CreateExport,
  V3CreateGroup,
  V3CreateProject,
  V3CreateRoleTemplate,
  V3UpdateRoleTemplate,
  V3GenerateRoleDocumentsInput,
  V3RoleDocuments,
  V3CreateWaker,
  V3WakerPackageCoreImport,
  V3DurableEvent,
  V3GroupActivitySnapshot,
  V3Event,
  V3EventPage,
  V3ExportJob,
  V3ExpectedVersion,
  V3Group,
  V3GroupSkill,
  V3InstallGroupSkills,
  V3RemoveGroupSkill,
  V3GroupLifecycleInput,
  V3Idempotency,
  V3Page,
  V3PaginationInput,
  V3KnowledgeListInput,
  V3Principal,
  V3Project,
  V3ProjectLifecycleInput,
  V3RetryProjectPreparation,
  V3ProjectVisibility,
  V3ResolveApproval,
  V3RenameGroup,
  V3Run,
  V3RoleTemplate,
  V3SendMessage,
  V3Task,
  V3RenameTask,
  V3HideTask,
  V3PinTask,
  V3ReadTaskResult,
  V3TaskPage,
  V3UnreadCounts,
  V3UnreadQuery,
  V3MarkSubjectRead,
  V3UpdateWaker,
  V3UpdateProject,
  V3UpdateImPairing,
  V3Waker,
  V3GroupMembershipVersion,
  V3WakerLifecycleInput,
  V3WorkspaceReference,
  V3DocumentComparison,
  V3MemoryTimelineEvent,
  V3MemoryTimelineQuery,
  V3NetworkDiagnostics,
  V3DesktopMachineInventory,
  V3RestoreWakerDocument,
  V3UpdateWakerDocument,
  V3WakerConfigurationVersion,
  V3WakerDocumentKind,
  V3WakerDocumentVersion,
  V3PermissionPolicyKind,
  V3PermissionPolicyVersion,
  V3UpdatePermissionPolicy,
  V3PolicyDecisionEvidence,
  V3Automation,
  V3AutomationDispatchInput,
  V3AutomationDispatchResult,
  V3AutomationInvocation,
  V3AutomationInvocationListInput,
  V3AutomationLifecycleInput,
  V3CreateAutomation,
  V3UpdateAutomation,
  V3CreateWorkflow,
  V3ResolveWorkflowInput,
  V3UpdateWorkflow,
  V3UpdateWorkflowTriggers,
  V3Workflow,
  V3WorkflowLifecycleInput,
  V3WorkflowRollbackInput,
  V3WorkflowRun,
  V3WorkflowRunEvent,
  V3WorkflowRunInput,
  V3WorkflowNodeExecution,
  V3WorkflowVersion,
  V3WorkflowTriggerDispatchInput,
  V3CreateKnowledgeBase,
  V3CreateKnowledgeFolder,
  V3CreateKnowledgeSchedule,
  V3CreateKnowledgeUrlMaterial,
  V3CompileKnowledgeBase,
  V3InviteKnowledgeCollaborator,
  V3KnowledgeBase,
  V3KnowledgeFolder,
  V3KnowledgeCard,
  V3KnowledgeCollaborator,
  V3KnowledgeBinding,
  V3KnowledgeBindingInput,
  V3KnowledgeMaterial,
  V3KnowledgeMaterialContent,
  V3KnowledgeSchedule,
  V3KnowledgeScheduleRun,
  V3KnowledgeSettings,
  V3RenameKnowledgeBase,
  V3RenameKnowledgeFolder,
  V3RenameKnowledgeMaterial,
  V3DeleteKnowledgeSelection,
  V3UpdateKnowledgeSchedule,
  V3UpdateKnowledgeSettings,
  V3SkillInstallation,
  V3SkillComparison,
  V3SkillLifecycleInput,
  V3SkillMarketplaceCategory,
  V3SkillMarketplaceDetail,
  V3SkillMarketplacePage,
  V3SkillMarketplaceSort,
  V3SkillPackagePreparation,
  V3SkillPackagePreparationSource,
  V3SkillVersion,
  V3WakerBuiltinCapabilities,
  V3BrowserConnectorState,
  V3BrowserConnectorEnablement,
  V3SkillEvolutionPolicy,
  V3UpdateSkillEvolutionPolicy,
  V3UpdateBrowserConnectorEnablement,
  V3Connector,
  V3CreateConnector,
  V3UpdateConnector,
  V3ConnectorToolSelectionInput,
  V3ConnectorLifecycleInput,
  V3CreateImChannel,
  V3CreateImPairing,
  V3CreateManualImPairing,
  V3ImChannel,
  V3ImChannelLifecycleInput,
  V3ImQrAuthPollInput,
  V3ImQrAuthPollResult,
  V3ImQrAuthSession,
  V3ImQrAuthStartInput,
  V3ImPairingLifecycleInput,
  V3ImConversation,
  V3ImPairingRequest,
  V3ResolveImPairingRequest,
  V3UpdateImChannel,
} from './v3.ts';
import type { V3AuthMode, V3AuthSession } from './feishu-auth.ts';

export interface V3RequestContext {
  principal: V3Principal;
  correlationId: string;
}

export interface V3MutationContext extends V3RequestContext {
  idempotency: V3Idempotency;
}

export interface V3ModelAuthorization {
  assertAuthorized(model: string): void;
}

export interface V3AvatarUploadInput {
  fileName: string;
  mediaType: 'image/png' | 'image/jpeg';
  bytes: Uint8Array;
}

export interface V3SkillUploadInput {
  fileName: string;
  mediaType: 'text/markdown' | 'application/zip' | 'application/gzip';
  bytes: Uint8Array;
  selfEvolution: boolean;
  expectedConfigurationVersionId: string;
}

export interface V3SkillUpdateUploadInput extends V3SkillUploadInput {
  expectedVersion: number;
  changeSummary: string;
}

export interface V3SkillPackagePreparationUploadInput {
  fileName: string;
  mediaType: 'text/markdown' | 'application/zip' | 'application/gzip';
  bytes: Uint8Array;
  selfEvolution: boolean;
}

/**
 * Parsed, credential-free Skill package metadata retained until Waker creation.
 * The object key and package contents stay inside the data-access boundary.
 */
export interface V3SkillPackagePreparationInput {
  /** Candidate id generated by the package preparation service; preserves retry identity. */
  id?: string;
  source: V3SkillPackagePreparationSource;
  marketplaceSkillId?: string;
  fileName: string;
  mediaType: 'text/markdown' | 'application/zip' | 'application/gzip';
  name: string;
  description: string;
  markdown: string;
  inventory: string[];
  packageSha256: string;
  contentSha256: string;
  objectKey: string;
  sizeBytes: number;
  selfEvolution: boolean;
  expiresAt: string;
}

/** Internal preparation view used by the future atomic Waker consumer. */
export interface V3SkillPackagePreparationForCreate extends V3SkillPackagePreparation {
  markdown: string;
  inventory: string[];
  objectKey: string;
}

export interface V3SkillMarketplaceInput {
  query?: string;
  category?: V3SkillMarketplaceCategory;
  sort: V3SkillMarketplaceSort;
  page: number;
  pageSize: number;
}

export interface V3KnowledgeFileUploadInput {
  fileName: string;
  mediaType: string;
  bytes: Uint8Array;
  parentFolderId?: string | null;
}

export interface V3ConversationAttachmentUploadInput {
  fileName: string;
  mediaType: string;
  bytes: Uint8Array;
}

export interface V3ConversationAttachmentPreview {
  mediaType: string;
  bytes: Uint8Array;
}

export interface V3CreateKnowledgeFileMaterial {
  fileObjectId: string;
  title: string;
  sourceSha256: string;
  parentFolderId?: string | null;
}

export interface V3WakerListInput extends V3PaginationInput {
  query?: string;
  status?: V3Waker['status'];
  environment?: V3Waker['environment'];
}

export interface V3ConversationListInput extends V3PaginationInput {
  subjectType: V3Conversation['subjectType'];
  subjectId: string;
}

export interface V3TaskListInput extends V3PaginationInput {
  sourceType?: string;
  sourceId?: string;
  taskType?: V3Task['type'];
  taskTypeCategory?: 'group' | 'workflow' | 'individual' | 'automation';
  assigneeWakerId?: string;
  state?: V3Task['state'];
  stateCategory?: 'queued' | 'action' | 'running' | 'completed' | 'failed' | 'cancelled' | 'terminal';
  actionNeededOnly?: boolean;
  query?: string;
}

export interface V3ImConversationListInput extends V3PaginationInput {
  wakerId?: string;
  query?: string;
  type?: V3ImConversation['type'];
}

export interface V3ImDispatchBinding {
  wakerId: string | null;
  groupId: string | null;
  workspaceReferenceId: string | null;
  model: string;
}

export interface V3ImExternalEventResult {
  workspaceId: string;
  initiatorUserId: string | null;
  pairingVersionId: string | null;
  duplicate: boolean;
  conversationId: string;
  pairingRequestId: string | null;
  productConversationId: string | null;
  pairing: V3ImDispatchBinding | null;
}

export interface V3ImRunDelivery {
  runId: string;
  channelId: string;
  conversationId: string;
  externalReceiveRef: string;
  state: 'pending' | 'sent' | 'failed';
  attempt: number;
  failureDetail: string | null;
}

export interface V3ProjectListInput extends V3PaginationInput {
  visibility: V3ProjectVisibility;
  ownerWakerId?: string;
}

export interface V3SendMessageResult {
  conversationEvent: V3Event;
  task: V3Task;
  run: V3Run | null;
}

export type V3ConnectionState = 'connected' | 'reconnecting' | 'offline' | 'closed';

export interface V3EventObserver {
  event(event: V3DurableEvent): void;
  state(state: V3ConnectionState): void;
  error?(correlationId: string): void;
}

export interface V3EventSubscription {
  close(): void;
}

export interface V3EventSubscriptionPort {
  subscribe(
    input: { runId: string; afterSequence: number },
    observer: V3EventObserver,
  ): Promise<V3EventSubscription>;
}

export const V3_EMPTY_PROJECT_MEMORY_CONTENT = '## 项目概览\n\n## 参考摘要\n';

export interface V3MemoryDocumentQuery {
  scope: 'project';
  projectId: string;
}

export interface V3MemoryDocument {
  scope: 'project';
  scopeId: string;
  scopeLabel: string;
  projectId: string;
  path: string;
  content: string;
  hash: string;
  updatedAt: string;
  canonicalized: boolean;
}

export interface V3SaveMemoryDocumentInput {
  scope: 'project';
  projectId: string;
  content: string;
  expectedHash: string;
  reason: 'console_edit';
}

export function isV3MemoryDocumentQuery(value: unknown): value is V3MemoryDocumentQuery {
  if (!value || typeof value !== 'object') return false;
  const query = value as Record<string, unknown>;
  return (
    query.scope === 'project' &&
    typeof query.projectId === 'string' &&
    query.projectId.length > 0 &&
    query.projectId.length <= 128
  );
}

export function isV3SaveMemoryDocumentInput(value: unknown): value is V3SaveMemoryDocumentInput {
  if (!value || typeof value !== 'object') return false;
  const input = value as Record<string, unknown>;
  return (
    input.scope === 'project' &&
    typeof input.projectId === 'string' &&
    input.projectId.length > 0 &&
    input.projectId.length <= 128 &&
    typeof input.content === 'string' &&
    input.content.length <= 100_000 &&
    typeof input.expectedHash === 'string' &&
    /^[a-f0-9]{64}$/iu.test(input.expectedHash) &&
    input.reason === 'console_edit'
  );
}

export function isV3MemoryDocument(value: unknown): value is V3MemoryDocument {
  if (!value || typeof value !== 'object') return false;
  const document = value as Record<string, unknown>;
  return (
    document.scope === 'project' &&
    typeof document.scopeId === 'string' &&
    typeof document.scopeLabel === 'string' &&
    typeof document.projectId === 'string' &&
    typeof document.path === 'string' &&
    typeof document.content === 'string' &&
    typeof document.hash === 'string' &&
    typeof document.updatedAt === 'string' &&
    typeof document.canonicalized === 'boolean'
  );
}

/** Shared product boundary implemented by Cloud HTTP/WS and Desktop Local RPC. */
export interface V3ProductGateway extends V3EventSubscriptionPort {
  listPluginCatalog(input: PluginCatalogInput): Promise<PluginCatalogPage>;
  listConnectorCatalog(input: ConnectorCatalogInput): Promise<ConnectorCatalogPage>;
  getConnectorMarketDetail(marketId: string): Promise<ConnectorMarketDetail>;
  getPluginMarketComposition(marketId: string): Promise<PluginMarketComposition>;
  listInstalledPlugins(): Promise<InstalledPlugin[]>;
  installMarketPlugin(input: InstallMarketPluginRequest): Promise<PluginInstallationRevision>;
  setPluginEnabled(input: SetPluginEnabledRequest): Promise<PluginInstallationRevision>;
  uninstallPlugin(input: UninstallPluginRequest): Promise<PluginInstallationRevision>;
  retryPlugin(input: RetryPluginRequest): Promise<PluginInstallationRevision>;
  inspectPluginPackage(bytes: Uint8Array): Promise<{
    displayName: string;
    pluginName: string;
    version: string;
    skillNames: string[];
  }>;
  installUploadedPlugin(input: {
    wakerId: string;
    expectedConfigurationVersionId: string;
    bytes: Uint8Array;
    idempotencyKey: string;
  }): Promise<PluginInstallationRevision>;

  bootstrap(): Promise<V3Bootstrap>;

  getLanguageSetting(signal?: AbortSignal): Promise<V3LanguageSetting>;
  updateLanguageSetting(input: V3LanguageSettingInput): Promise<V3LanguageSetting>;

  uploadAvatar(input: V3AvatarUploadInput, idempotencyKey: string): Promise<V3AvatarObject>;
  avatarUrl(avatarObjectId: string): Promise<string>;

  listWakers(input?: V3WakerListInput): Promise<V3Page<V3Waker>>;
  listRoleTemplates(input?: V3PaginationInput): Promise<V3Page<V3RoleTemplate>>;
  createRoleTemplate(input: V3CreateRoleTemplate, idempotencyKey: string): Promise<V3RoleTemplate>;
  updateRoleTemplate(
    roleTemplateId: string,
    input: V3UpdateRoleTemplate,
    idempotencyKey: string,
  ): Promise<V3RoleTemplate>;
  generateRoleDocuments(input: V3GenerateRoleDocumentsInput, signal?: AbortSignal): Promise<V3RoleDocuments>;
  getWaker(wakerId: string): Promise<V3Waker>;
  ensureWakey(): Promise<V3Waker>;
  listWakeyNotifications(before?: number): Promise<WakeyNotificationPage>;
  readWakeyNotifications(input: ReadWakeyNotifications): Promise<void>;
  createWaker(input: V3CreateWaker, idempotencyKey: string): Promise<V3Waker>;
  updateWaker(wakerId: string, input: V3UpdateWaker): Promise<V3Waker>;
  changeWakerLifecycle(
    wakerId: string,
    input: V3WakerLifecycleInput,
    idempotencyKey: string,
  ): Promise<V3Waker>;
  getWakerConfiguration(wakerId: string): Promise<V3WakerConfigurationVersion>;
  listWakerDocumentVersions(
    wakerId: string,
    kind: V3WakerDocumentKind,
    input?: V3PaginationInput,
  ): Promise<V3Page<V3WakerDocumentVersion>>;
  updateWakerDocument(
    wakerId: string,
    kind: V3WakerDocumentKind,
    input: V3UpdateWakerDocument,
    idempotencyKey: string,
  ): Promise<V3WakerConfigurationVersion>;
  restoreWakerDocument(
    wakerId: string,
    kind: V3WakerDocumentKind,
    input: V3RestoreWakerDocument,
    idempotencyKey: string,
  ): Promise<V3WakerConfigurationVersion>;
  compareWakerDocumentVersions(
    wakerId: string,
    kind: V3WakerDocumentKind,
    fromVersionId: string,
    toVersionId: string,
  ): Promise<V3DocumentComparison>;
  listMemoryTimeline(wakerId: string, input?: V3MemoryTimelineQuery): Promise<V3Page<V3MemoryTimelineEvent>>;
  getMemoryDocument(wakerId: string, input: V3MemoryDocumentQuery): Promise<V3MemoryDocument>;
  saveMemoryDocument(
    wakerId: string,
    input: V3SaveMemoryDocumentInput,
    idempotencyKey: string,
  ): Promise<V3MemoryDocument>;
  getRunConfiguration(runId: string): Promise<V3WakerConfigurationVersion>;
  listWakerPermissionPolicies(wakerId: string): Promise<V3PermissionPolicyVersion[]>;
  listWakerPermissionPolicyVersions(
    wakerId: string,
    kind: V3PermissionPolicyKind,
    input?: V3PaginationInput,
  ): Promise<V3Page<V3PermissionPolicyVersion>>;
  updateWakerPermissionPolicy(
    wakerId: string,
    kind: V3PermissionPolicyKind,
    input: V3UpdatePermissionPolicy,
    idempotencyKey: string,
  ): Promise<V3WakerConfigurationVersion>;
  getRunPermissionPolicies(runId: string): Promise<V3PermissionPolicyVersion[]>;

  listGroups(input?: V3PaginationInput): Promise<V3Page<V3Group>>;
  getGroup(groupId: string): Promise<V3Group>;
  createGroup(input: V3CreateGroup, idempotencyKey: string): Promise<V3Group>;
  listGroupSkills(groupId: string): Promise<V3GroupSkill[]>;
  listGroupSops(groupId: string): Promise<V3GroupSkill[]>;
  removeGroupSkill(
    groupId: string,
    input: V3RemoveGroupSkill,
    idempotencyKey: string,
  ): Promise<V3GroupSkill[]>;
  installGroupSkills(
    groupId: string,
    input: V3InstallGroupSkills,
    idempotencyKey: string,
  ): Promise<V3GroupSkill[]>;
  updateGroup(groupId: string, input: V3CreateGroup & V3ExpectedVersion): Promise<V3Group>;
  renameGroup(groupId: string, input: V3RenameGroup): Promise<V3Group>;
  markGroupRead(groupId: string): Promise<V3Group>;
  listUnread(input: V3UnreadQuery): Promise<V3UnreadCounts>;
  markSubjectRead(input: V3MarkSubjectRead): Promise<V3UnreadCounts>;
  markAllRead(): Promise<V3UnreadCounts>;
  changeGroupLifecycle(
    groupId: string,
    input: V3GroupLifecycleInput,
    idempotencyKey: string,
  ): Promise<V3Group>;
  listGroupMembershipHistory(
    groupId: string,
    input?: V3PaginationInput,
  ): Promise<V3Page<V3GroupMembershipVersion>>;

  listWorkspaceReferences(input?: V3PaginationInput): Promise<V3Page<V3WorkspaceReference>>;
  listProjects(input: V3ProjectListInput): Promise<V3Page<V3Project>>;
  getProject(projectId: string): Promise<V3Project>;
  createProject(input: V3CreateProject, idempotencyKey: string): Promise<V3Project>;
  updateProject(projectId: string, input: V3UpdateProject, idempotencyKey: string): Promise<V3Project>;
  retryProjectPreparation(
    projectId: string,
    input: V3RetryProjectPreparation,
    idempotencyKey: string,
  ): Promise<V3Project>;
  changeProjectLifecycle(
    projectId: string,
    input: V3ProjectLifecycleInput,
    idempotencyKey: string,
  ): Promise<void>;
  /** Omit the executor to list all automations in the authenticated workspace. */
  listAutomations(wakerId: string | undefined, input?: V3PaginationInput): Promise<V3Page<V3Automation>>;
  getAutomation(automationId: string): Promise<V3Automation>;
  createAutomation(wakerId: string, input: V3CreateAutomation, idempotencyKey: string): Promise<V3Automation>;
  updateAutomation(
    automationId: string,
    input: V3UpdateAutomation,
    idempotencyKey: string,
  ): Promise<V3Automation>;
  changeAutomationLifecycle(
    automationId: string,
    input: V3AutomationLifecycleInput,
    idempotencyKey: string,
  ): Promise<V3Automation | undefined>;
  dispatchAutomation(
    automationId: string,
    input: V3AutomationDispatchInput,
    idempotencyKey: string,
  ): Promise<V3AutomationDispatchResult>;
  listAutomationInvocations(
    automationId: string,
    input?: V3AutomationInvocationListInput,
  ): Promise<V3Page<V3AutomationInvocation>>;
  listWorkflows(input?: V3PaginationInput): Promise<V3Page<V3Workflow>>;
  getWorkflow(workflowId: string): Promise<V3Workflow>;
  createWorkflow(input: V3CreateWorkflow, idempotencyKey: string): Promise<V3Workflow>;
  updateWorkflow(workflowId: string, input: V3UpdateWorkflow, idempotencyKey: string): Promise<V3Workflow>;
  listWorkflowAutomations(input?: V3PaginationInput): Promise<V3Page<V3WorkflowAutomation>>;
  getWorkflowAutomation(automationId: string): Promise<V3WorkflowAutomation>;
  createWorkflowAutomation(
    workflowId: string,
    input: V3CreateWorkflowAutomation,
    idempotencyKey: string,
  ): Promise<V3WorkflowAutomation>;
  updateWorkflowAutomation(
    automationId: string,
    input: V3UpdateWorkflowAutomation,
    idempotencyKey: string,
  ): Promise<V3WorkflowAutomation>;
  deleteWorkflowAutomation(
    automationId: string,
    input: V3DeleteWorkflowAutomation,
    idempotencyKey: string,
  ): Promise<void>;
  dispatchWorkflowAutomation(
    automationId: string,
    input: V3WorkflowAutomationDispatchInput,
    idempotencyKey: string,
  ): Promise<{ created: boolean; run: V3WorkflowRun }>;
  listWorkflowAutomationRuns(automationId: string, input?: V3PaginationInput): Promise<V3Page<V3WorkflowRun>>;
  updateWorkflowTriggers(
    workflowId: string,
    input: V3UpdateWorkflowTriggers,
    idempotencyKey: string,
  ): Promise<V3Workflow>;
  dispatchWorkflowTrigger(
    workflowId: string,
    input: V3WorkflowTriggerDispatchInput,
    idempotencyKey: string,
  ): Promise<{ created: boolean; run: V3WorkflowRun }>;
  changeWorkflowLifecycle(
    workflowId: string,
    input: V3WorkflowLifecycleInput,
    idempotencyKey: string,
  ): Promise<V3Workflow | undefined>;
  rollbackWorkflow(
    workflowId: string,
    input: V3WorkflowRollbackInput,
    idempotencyKey: string,
  ): Promise<V3Workflow>;
  listWorkflowVersions(workflowId: string, input?: V3PaginationInput): Promise<V3Page<V3WorkflowVersion>>;
  createWorkflowRun(
    workflowId: string,
    input: V3WorkflowRunInput,
    idempotencyKey: string,
  ): Promise<{ created: boolean; run: V3WorkflowRun }>;
  getWorkflowRun(runId: string): Promise<V3WorkflowRun>;
  listWorkflowRuns(workflowId: string, input?: V3PaginationInput): Promise<V3Page<V3WorkflowRun>>;
  listWorkflowNodeExecutions(runId: string): Promise<V3WorkflowNodeExecution[]>;
  listWorkflowRunEvents(runId: string, afterSequence?: number): Promise<V3Page<V3WorkflowRunEvent>>;
  resolveWorkflowInput(
    runId: string,
    input: V3ResolveWorkflowInput,
    idempotencyKey: string,
  ): Promise<V3WorkflowRun>;
  retryWorkflowRun(runId: string, idempotencyKey: string): Promise<V3WorkflowRun>;
  cancelWorkflowRun(runId: string, idempotencyKey: string): Promise<V3WorkflowRun>;
  listKnowledgeBases(input?: V3KnowledgeListInput): Promise<V3Page<V3KnowledgeBase>>;
  getKnowledgeBase(knowledgeBaseId: string): Promise<V3KnowledgeBase>;
  createKnowledgeBase(input: V3CreateKnowledgeBase, idempotencyKey: string): Promise<V3KnowledgeBase>;
  renameKnowledgeBase(
    knowledgeBaseId: string,
    input: V3RenameKnowledgeBase,
    idempotencyKey: string,
  ): Promise<V3KnowledgeBase>;
  deleteKnowledgeBase(knowledgeBaseId: string, idempotencyKey: string): Promise<void>;
  listKnowledgeFolders(knowledgeBaseId: string): Promise<V3KnowledgeFolder[]>;
  createKnowledgeFolder(
    knowledgeBaseId: string,
    input: V3CreateKnowledgeFolder,
    idempotencyKey: string,
  ): Promise<V3KnowledgeFolder>;
  renameKnowledgeFolder(
    knowledgeBaseId: string,
    folderId: string,
    input: V3RenameKnowledgeFolder,
    idempotencyKey: string,
  ): Promise<V3KnowledgeFolder>;
  deleteKnowledgeSelection(
    knowledgeBaseId: string,
    input: V3DeleteKnowledgeSelection,
    idempotencyKey: string,
  ): Promise<void>;
  listKnowledgeMaterials(
    knowledgeBaseId: string,
    input?: V3PaginationInput,
  ): Promise<V3Page<V3KnowledgeMaterial>>;
  listKnowledgeCards(knowledgeBaseId: string, input?: V3PaginationInput): Promise<V3Page<V3KnowledgeCard>>;
  listKnowledgeCollaborators(knowledgeBaseId: string): Promise<V3KnowledgeCollaborator[]>;
  inviteKnowledgeCollaborator(
    knowledgeBaseId: string,
    input: V3InviteKnowledgeCollaborator,
    idempotencyKey: string,
  ): Promise<V3KnowledgeCollaborator>;
  removeKnowledgeCollaborator(
    knowledgeBaseId: string,
    collaboratorId: string,
    idempotencyKey: string,
  ): Promise<void>;
  listKnowledgeSchedules(knowledgeBaseId: string): Promise<V3KnowledgeSchedule[]>;
  createKnowledgeSchedule(
    knowledgeBaseId: string,
    input: V3CreateKnowledgeSchedule,
    idempotencyKey: string,
  ): Promise<V3KnowledgeSchedule>;
  updateKnowledgeSchedule(
    knowledgeBaseId: string,
    scheduleId: string,
    input: V3UpdateKnowledgeSchedule,
    idempotencyKey: string,
  ): Promise<V3KnowledgeSchedule>;
  deleteKnowledgeSchedule(knowledgeBaseId: string, scheduleId: string, idempotencyKey: string): Promise<void>;
  listKnowledgeScheduleRuns(knowledgeBaseId: string, scheduleId: string): Promise<V3KnowledgeScheduleRun[]>;
  getKnowledgeSettings(knowledgeBaseId: string): Promise<V3KnowledgeSettings>;
  updateKnowledgeSettings(
    knowledgeBaseId: string,
    input: V3UpdateKnowledgeSettings,
    idempotencyKey: string,
  ): Promise<V3KnowledgeSettings>;
  compileKnowledgeBase(
    knowledgeBaseId: string,
    input: V3CompileKnowledgeBase,
    idempotencyKey: string,
  ): Promise<V3KnowledgeBase>;
  addKnowledgeUrlMaterial(
    knowledgeBaseId: string,
    input: V3CreateKnowledgeUrlMaterial,
    idempotencyKey: string,
  ): Promise<V3KnowledgeMaterial>;
  renameKnowledgeMaterial(
    knowledgeBaseId: string,
    materialId: string,
    input: V3RenameKnowledgeMaterial,
    idempotencyKey: string,
  ): Promise<V3KnowledgeMaterial>;
  addKnowledgeFileMaterial(
    knowledgeBaseId: string,
    input: V3KnowledgeFileUploadInput,
    idempotencyKey: string,
  ): Promise<V3KnowledgeMaterial>;
  getKnowledgeMaterialContent(
    knowledgeBaseId: string,
    materialId: string,
  ): Promise<V3KnowledgeMaterialContent>;
  knowledgeMaterialDownloadUrl(
    knowledgeBaseId: string,
    materialId: string,
    attachment?: boolean,
  ): Promise<string>;
  listKnowledgeBindings(wakerId?: string): Promise<V3KnowledgeBinding[]>;
  bindKnowledgeBase(
    knowledgeBaseId: string,
    input: V3KnowledgeBindingInput,
    idempotencyKey: string,
  ): Promise<V3KnowledgeBinding>;
  unbindKnowledgeBase(
    knowledgeBaseId: string,
    input: V3KnowledgeBindingInput,
    idempotencyKey: string,
  ): Promise<void>;
  listSkillMarketplace(input: V3SkillMarketplaceInput): Promise<V3SkillMarketplacePage>;
  getSkillMarketplaceDetail(marketplaceSkillId: string): Promise<V3SkillMarketplaceDetail>;
  prepareSkillPackageUpload(
    input: V3SkillPackagePreparationUploadInput,
    idempotencyKey: string,
  ): Promise<V3SkillPackagePreparation>;
  prepareMarketplaceSkill(
    marketplaceSkillId: string,
    selfEvolution: boolean,
    idempotencyKey: string,
  ): Promise<V3SkillPackagePreparation>;
  expireSkillPackagePreparation(preparationId: string, idempotencyKey: string): Promise<void>;
  installMarketplaceSkill(
    wakerId: string,
    marketplaceSkillId: string,
    input: { selfEvolution: boolean; expectedConfigurationVersionId: string },
    idempotencyKey: string,
  ): Promise<V3SkillInstallation>;
  listWakerSkills(wakerId: string, input?: V3PaginationInput): Promise<V3Page<V3SkillInstallation>>;
  installWakerSkill(
    wakerId: string,
    input: V3SkillUploadInput,
    idempotencyKey: string,
  ): Promise<V3SkillInstallation>;
  copyWakerSkill(
    wakerId: string,
    input: V3CopySkillInput,
    idempotencyKey: string,
  ): Promise<V3SkillInstallation>;
  updateWakerSkill(
    skillId: string,
    input: V3SkillUpdateUploadInput,
    idempotencyKey: string,
  ): Promise<V3SkillInstallation>;
  listWakerSkillVersions(skillId: string): Promise<V3SkillVersion[]>;
  compareWakerSkillVersions(
    skillId: string,
    fromVersionId: string | null,
    toVersionId: string,
  ): Promise<V3SkillComparison>;
  changeWakerSkillLifecycle(
    skillId: string,
    input: V3SkillLifecycleInput,
    idempotencyKey: string,
  ): Promise<V3SkillInstallation | undefined>;
  getWakerBuiltinCapabilities(wakerId: string): Promise<V3WakerBuiltinCapabilities>;
  updateWakerBuiltinCapabilities(
    wakerId: string,
    input: V3WakerBuiltinCapabilities,
    idempotencyKey: string,
  ): Promise<V3WakerBuiltinCapabilities>;
  getSkillEvolutionPolicy(wakerId: string): Promise<V3SkillEvolutionPolicy>;
  updateSkillEvolutionPolicy(
    wakerId: string,
    input: V3UpdateSkillEvolutionPolicy,
    idempotencyKey: string,
  ): Promise<V3SkillEvolutionPolicy>;
  getBrowserConnectorState(wakerId: string): Promise<V3BrowserConnectorState>;
  updateBrowserConnectorEnablement(
    wakerId: string,
    input: V3UpdateBrowserConnectorEnablement,
    idempotencyKey: string,
  ): Promise<V3BrowserConnectorState>;
  listWakerConnectors(wakerId: string, input?: V3PaginationInput): Promise<V3Page<V3Connector>>;
  createWakerConnector(
    wakerId: string,
    input: V3CreateConnector & { expectedConfigurationVersionId: string },
    idempotencyKey: string,
  ): Promise<V3Connector>;
  updateWakerConnector(
    connectorId: string,
    input: V3UpdateConnector,
    idempotencyKey: string,
  ): Promise<V3Connector>;
  diagnoseWakerConnector(connectorId: string, idempotencyKey: string): Promise<V3Connector>;
  updateWakerConnectorTools(
    connectorId: string,
    input: V3ConnectorToolSelectionInput,
    idempotencyKey: string,
  ): Promise<V3Connector>;
  changeWakerConnectorLifecycle(
    connectorId: string,
    input: V3ConnectorLifecycleInput,
    idempotencyKey: string,
  ): Promise<V3Connector | undefined>;
  listImChannels(input?: V3PaginationInput): Promise<V3Page<V3ImChannel>>;
  createImChannel(input: V3CreateImChannel, idempotencyKey: string): Promise<V3ImChannel>;
  updateImChannel(channelId: string, input: V3UpdateImChannel, idempotencyKey: string): Promise<V3ImChannel>;
  diagnoseImChannel(channelId: string, idempotencyKey: string): Promise<V3ImChannel>;
  startImChannelQr(input: V3ImQrAuthStartInput): Promise<V3ImQrAuthSession>;
  pollImChannelQr(input: V3ImQrAuthPollInput, idempotencyKey: string): Promise<V3ImQrAuthPollResult>;
  changeImChannelLifecycle(
    channelId: string,
    input: V3ImChannelLifecycleInput,
    idempotencyKey: string,
  ): Promise<V3ImChannel | undefined>;
  listImConversations(input?: V3ImConversationListInput): Promise<V3Page<V3ImConversation>>;
  listImPairingRequests(input?: V3PaginationInput): Promise<V3Page<V3ImPairingRequest>>;
  createImPairing(input: V3CreateImPairing, idempotencyKey: string): Promise<V3ImConversation>;
  createManualImPairing(input: V3CreateManualImPairing, idempotencyKey: string): Promise<V3ImConversation>;
  updateImPairing(
    conversationId: string,
    input: V3UpdateImPairing,
    idempotencyKey: string,
  ): Promise<V3ImConversation>;
  changeImPairingLifecycle(
    conversationId: string,
    input: V3ImPairingLifecycleInput,
    idempotencyKey: string,
  ): Promise<V3ImConversation | undefined>;
  resolveImPairingRequest(
    requestId: string,
    input: V3ResolveImPairingRequest,
    idempotencyKey: string,
  ): Promise<V3ImPairingRequest>;
  listConversations(input: V3ConversationListInput): Promise<V3Page<V3Conversation>>;
  getConversation(conversationId: string): Promise<V3Conversation | null>;
  uploadConversationAttachment(
    subjectType: V3Conversation['subjectType'],
    subjectId: string,
    input: V3ConversationAttachmentUploadInput,
    idempotencyKey: string,
  ): Promise<V3ConversationAttachment>;
  getConversationAttachment(attachmentId: string): Promise<V3ConversationAttachmentPreview>;
  removeConversationAttachment(attachmentId: string, idempotencyKey: string): Promise<void>;
  createConversation(input: V3CreateConversation, idempotencyKey: string): Promise<V3Conversation>;
  listConversationEvents(conversationId: string, afterSequence?: number): Promise<V3EventPage>;
  listGroupMessageHistory(conversationId: string, beforeSequence?: number): Promise<V3Page<V3Event>>;
  getGroupActivitySnapshot(conversationId: string): Promise<V3GroupActivitySnapshot>;
  listConversationRuns(
    conversationId: string,
    input?: { limit?: number; cursor?: string },
  ): Promise<import('./v3.ts').V3ConversationRunPage>;
  sendConversationMessage(
    conversationId: string,
    input: V3SendMessage,
    idempotencyKey: string,
  ): Promise<V3SendMessageResult>;
  confirmGroupPlan(runId: string, input: V3ConfirmGroupPlan, idempotencyKey: string): Promise<void>;

  getRun(runId: string): Promise<V3Run>;
  listRunEvents(runId: string, afterSequence?: number): Promise<V3Page<V3DurableEvent>>;
  listRunEventHistory(
    runId: string,
    input?: { beforeSequence?: number; limit?: number },
  ): Promise<V3Page<V3DurableEvent>>;
  listArtifacts(runId: string): Promise<V3Artifact[]>;
  getConversationArtifacts(
    conversationId: string,
    signal?: AbortSignal,
  ): Promise<V3ConversationArtifactManifest>;
  artifactDownloadUrl(artifactId: string): Promise<string>;
  cancelRun(runId: string, idempotencyKey: string): Promise<void>;
  undoQueuedGroupInbox(runId: string, idempotencyKey: string): Promise<void>;
  sendQueuedRunNow(runId: string, idempotencyKey: string): Promise<void>;
  resolveApproval(approvalId: string, input: V3ResolveApproval): Promise<void>;
  listPendingApprovals(input?: V3PaginationInput): Promise<V3Page<V3ApprovalWorkItem>>;
  listTasks(input?: V3TaskListInput): Promise<V3TaskPage>;
  renameTask(taskId: string, input: V3RenameTask, idempotencyKey: string): Promise<V3Task>;
  hideTask(taskId: string, input: V3HideTask, idempotencyKey: string): Promise<void>;
  readTaskResult(taskId: string, input: V3ReadTaskResult, idempotencyKey: string): Promise<void>;
  pinTask(taskId: string, input: V3PinTask, idempotencyKey: string): Promise<V3Task>;
  createExport(input: V3CreateExport, idempotencyKey: string): Promise<V3ExportJob>;
  getExport(exportId: string): Promise<V3ExportJob>;
  exportDownloadUrl(exportId: string): Promise<string>;
}

export interface V3AvatarStorage {
  put(
    ownerId: string,
    name: string,
    body: Uint8Array,
    mediaType: string,
  ): Promise<{ key: string; sha256: string }>;
  signedDownloadUrl(key: string, expiresIn?: number, downloadName?: string): Promise<string>;
  delete(key: string): Promise<void>;
}

export interface V3AvatarRepository {
  upload(
    context: V3MutationContext,
    input: V3AvatarUploadInput,
    storage: V3AvatarStorage,
  ): Promise<V3AvatarObject>;
  downloadUrl(context: V3RequestContext, avatarObjectId: string, storage: V3AvatarStorage): Promise<string>;
}

export interface V3WakerRepository {
  listRoleTemplates(context: V3RequestContext, input: V3PaginationInput): Promise<V3Page<V3RoleTemplate>>;
  createRoleTemplate(context: V3MutationContext, input: V3CreateRoleTemplate): Promise<V3RoleTemplate>;
  updateRoleTemplate(
    context: V3MutationContext,
    roleTemplateId: string,
    input: V3UpdateRoleTemplate,
  ): Promise<V3RoleTemplate>;
  list(context: V3RequestContext, input: V3WakerListInput): Promise<V3Page<V3Waker>>;
  get(context: V3RequestContext, wakerId: string): Promise<V3Waker | undefined>;
  ensureWakey(context: V3MutationContext, environment: V3Waker['environment']): Promise<V3Waker>;
  listWakeyNotifications(context: V3RequestContext, before?: number): Promise<WakeyNotificationPage>;
  readWakeyNotifications(context: V3RequestContext, input: ReadWakeyNotifications): Promise<void>;
  create(context: V3MutationContext, input: V3CreateWaker): Promise<V3Waker>;
  /** Atomically creates the core Waker package payload in the backing store. */
  importCorePackage?(context: V3MutationContext, input: V3WakerPackageCoreImport): Promise<V3Waker>;
  /**
   * Atomically consumes a share link and creates its core Waker package. The
   * decoder runs while the share row and import transaction are locked, so a
   * validation failure cannot leave either side partially committed.
   */
  importSharedCorePackage?(
    context: V3MutationContext,
    input: {
      shareId: string;
      decode: (packageBytes: Uint8Array) => Promise<V3WakerPackageCoreImport>;
    },
  ): Promise<V3Waker>;
  update(context: V3RequestContext, wakerId: string, input: V3UpdateWaker): Promise<V3Waker>;
  changeLifecycle(
    context: V3MutationContext,
    wakerId: string,
    input: V3WakerLifecycleInput,
  ): Promise<V3Waker>;
}

export interface V3WakerConfigurationRepository {
  getCurrent(context: V3RequestContext, wakerId: string): Promise<V3WakerConfigurationVersion | undefined>;
  getVersion(
    context: V3RequestContext,
    configurationVersionId: string,
  ): Promise<V3WakerConfigurationVersion | undefined>;
  getForRun(context: V3RequestContext, runId: string): Promise<V3WakerConfigurationVersion | undefined>;
  listDocumentVersions(
    context: V3RequestContext,
    wakerId: string,
    kind: V3WakerDocumentKind,
    input: V3PaginationInput,
  ): Promise<V3Page<V3WakerDocumentVersion>>;
  getDocumentVersion(
    context: V3RequestContext,
    wakerId: string,
    kind: V3WakerDocumentKind,
    versionId: string,
  ): Promise<V3WakerDocumentVersion | undefined>;
  updateDocument(
    context: V3MutationContext,
    wakerId: string,
    kind: V3WakerDocumentKind,
    input: V3UpdateWakerDocument,
  ): Promise<V3WakerConfigurationVersion>;
  restoreDocument(
    context: V3MutationContext,
    wakerId: string,
    kind: V3WakerDocumentKind,
    input: V3RestoreWakerDocument,
  ): Promise<V3WakerConfigurationVersion>;
  compareDocumentVersions(
    context: V3RequestContext,
    wakerId: string,
    kind: V3WakerDocumentKind,
    fromVersionId: string,
    toVersionId: string,
  ): Promise<V3DocumentComparison>;
  listMemoryTimeline(
    context: V3RequestContext,
    wakerId: string,
    input: V3MemoryTimelineQuery,
  ): Promise<V3Page<V3MemoryTimelineEvent>>;
  getMemoryDocument(
    context: V3RequestContext,
    wakerId: string,
    input: V3MemoryDocumentQuery,
  ): Promise<V3MemoryDocument>;
  saveMemoryDocument(
    context: V3MutationContext,
    wakerId: string,
    input: V3SaveMemoryDocumentInput,
  ): Promise<V3MemoryDocument>;
}

export interface V3PermissionPolicyRepository {
  listCurrent(context: V3RequestContext, wakerId: string): Promise<V3PermissionPolicyVersion[]>;
  listVersions(
    context: V3RequestContext,
    wakerId: string,
    kind: V3PermissionPolicyKind,
    input: V3PaginationInput,
  ): Promise<V3Page<V3PermissionPolicyVersion>>;
  update(
    context: V3MutationContext,
    wakerId: string,
    kind: V3PermissionPolicyKind,
    input: V3UpdatePermissionPolicy,
  ): Promise<V3WakerConfigurationVersion>;
  getForConfiguration(
    context: V3RequestContext,
    configurationVersionId: string,
  ): Promise<V3PermissionPolicyVersion[]>;
  getForRun(context: V3RequestContext, runId: string): Promise<V3PermissionPolicyVersion[]>;
  recordDecision(
    context: V3RequestContext,
    input: Omit<V3PolicyDecisionEvidence, 'id' | 'occurredAt'>,
  ): Promise<V3PolicyDecisionEvidence>;
}

export interface V3GroupRepository {
  listSops(context: V3RequestContext, groupId: string): Promise<V3GroupSkill[]>;
  listSkills(context: V3RequestContext, groupId: string): Promise<V3GroupSkill[]>;
  removeSkill(
    context: V3MutationContext,
    groupId: string,
    input: V3RemoveGroupSkill,
  ): Promise<V3GroupSkill[]>;
  installSkills(
    context: V3MutationContext,
    groupId: string,
    input: V3InstallGroupSkills,
  ): Promise<V3GroupSkill[]>;
  list(context: V3RequestContext, input: V3PaginationInput): Promise<V3Page<V3Group>>;
  get(context: V3RequestContext, groupId: string): Promise<V3Group | undefined>;
  create(
    context: V3MutationContext,
    input: V3CreateGroup,
    authorization: V3ModelAuthorization,
  ): Promise<V3Group>;
  updateMembership(
    context: V3RequestContext,
    groupId: string,
    input: V3CreateGroup & V3ExpectedVersion,
    authorization: V3ModelAuthorization,
  ): Promise<V3Group>;
  rename(context: V3RequestContext, groupId: string, input: V3RenameGroup): Promise<V3Group>;
  markRead(context: V3RequestContext, groupId: string): Promise<V3Group>;
  changeLifecycle(
    context: V3MutationContext,
    groupId: string,
    input: V3GroupLifecycleInput,
  ): Promise<V3Group>;
  listMembershipHistory(
    context: V3RequestContext,
    groupId: string,
    input: V3PaginationInput,
  ): Promise<V3Page<V3GroupMembershipVersion>>;
}

export interface V3WorkspaceReferenceRepository {
  list(context: V3RequestContext, input: V3PaginationInput): Promise<V3Page<V3WorkspaceReference>>;
  get(context: V3RequestContext, referenceId: string): Promise<V3WorkspaceReference | undefined>;
  revoke(context: V3RequestContext, referenceId: string, expectedVersion: number): Promise<void>;
}

export interface V3ProjectRepository {
  list(context: V3RequestContext, input: V3ProjectListInput): Promise<V3Page<V3Project>>;
  get(context: V3RequestContext, projectId: string): Promise<V3Project | undefined>;
  create(context: V3MutationContext, input: V3CreateProject): Promise<V3Project>;
  update(context: V3MutationContext, projectId: string, input: V3UpdateProject): Promise<V3Project>;
  retryPreparation(
    context: V3MutationContext,
    projectId: string,
    input: V3RetryProjectPreparation,
  ): Promise<V3Project>;
  completePreparation(
    context: V3RequestContext,
    projectId: string,
    attempt: number,
    result: { state: 'ready' } | { state: 'error'; errorCode: string; errorDetail: string },
  ): Promise<V3Project>;
  changeLifecycle(
    context: V3MutationContext,
    projectId: string,
    input: V3ProjectLifecycleInput,
  ): Promise<void>;
}

export interface V3AutomationRepository {
  list(
    context: V3RequestContext,
    wakerId: string | undefined,
    input: V3PaginationInput,
  ): Promise<V3Page<V3Automation>>;
  get(context: V3RequestContext, automationId: string): Promise<V3Automation | undefined>;
  create(
    context: V3MutationContext,
    wakerId: string,
    input: V3CreateAutomation,
    authorization: V3ModelAuthorization,
  ): Promise<V3Automation>;
  update(
    context: V3MutationContext,
    automationId: string,
    input: V3UpdateAutomation,
    authorization: V3ModelAuthorization,
  ): Promise<V3Automation>;
  changeLifecycle(
    context: V3MutationContext,
    automationId: string,
    input: V3AutomationLifecycleInput,
    authorization?: V3ModelAuthorization,
  ): Promise<V3Automation | undefined>;
  dispatch(
    context: V3MutationContext,
    automationId: string,
    input: V3AutomationDispatchInput,
    authorization: V3ModelAuthorization,
  ): Promise<V3AutomationDispatchResult & { dispatchNow: boolean }>;
  listInvocations(
    context: V3RequestContext,
    automationId: string,
    input: V3AutomationInvocationListInput,
  ): Promise<V3Page<V3AutomationInvocation>>;
}

export interface V3WorkflowAutomationRepository {
  dispatchAutomation(
    context: V3MutationContext,
    automationId: string,
    input: V3WorkflowAutomationDispatchInput,
  ): Promise<{ created: boolean; run: V3WorkflowRun }>;
  listAutomationRuns(
    context: V3RequestContext,
    automationId: string,
    input: V3PaginationInput,
  ): Promise<V3Page<V3WorkflowRun>>;
  createAutomation(
    context: V3MutationContext,
    workflowId: string,
    input: V3CreateWorkflowAutomation,
  ): Promise<V3WorkflowAutomation>;
  updateAutomation(
    context: V3MutationContext,
    automationId: string,
    input: V3UpdateWorkflowAutomation,
  ): Promise<V3WorkflowAutomation>;
  deleteAutomation(
    context: V3MutationContext,
    automationId: string,
    input: V3DeleteWorkflowAutomation,
  ): Promise<void>;
  getAutomation(context: V3RequestContext, automationId: string): Promise<V3WorkflowAutomation | undefined>;
  listAutomations(context: V3RequestContext, input: V3PaginationInput): Promise<V3Page<V3WorkflowAutomation>>;
}

export interface V3WorkflowRepository {
  list(context: V3RequestContext, input: V3PaginationInput): Promise<V3Page<V3Workflow>>;
  get(context: V3RequestContext, workflowId: string): Promise<V3Workflow | undefined>;
  create(context: V3MutationContext, input: V3CreateWorkflow): Promise<V3Workflow>;
  update(context: V3MutationContext, workflowId: string, input: V3UpdateWorkflow): Promise<V3Workflow>;
  updateTriggers(
    context: V3MutationContext,
    workflowId: string,
    input: V3UpdateWorkflowTriggers,
  ): Promise<V3Workflow>;
  dispatchTrigger(
    context: V3MutationContext,
    workflowId: string,
    input: V3WorkflowTriggerDispatchInput,
  ): Promise<{ created: boolean; run: V3WorkflowRun }>;
  changeLifecycle(
    context: V3MutationContext,
    workflowId: string,
    input: V3WorkflowLifecycleInput,
  ): Promise<V3Workflow | undefined>;
  rollback(
    context: V3MutationContext,
    workflowId: string,
    input: V3WorkflowRollbackInput,
  ): Promise<V3Workflow>;
  listVersions(
    context: V3RequestContext,
    workflowId: string,
    input: V3PaginationInput,
  ): Promise<V3Page<V3WorkflowVersion>>;
  createRun(
    context: V3MutationContext,
    workflowId: string,
    input: V3WorkflowRunInput,
  ): Promise<{ created: boolean; run: V3WorkflowRun }>;
  retryRun(
    context: V3MutationContext,
    sourceRunId: string,
  ): Promise<{ created: boolean; run: V3WorkflowRun }>;
  getRun(context: V3RequestContext, runId: string): Promise<V3WorkflowRun | undefined>;
  listRuns(
    context: V3RequestContext,
    workflowId: string,
    input: V3PaginationInput,
  ): Promise<V3Page<V3WorkflowRun>>;
  listRunEvents(
    context: V3RequestContext,
    runId: string,
    afterSequence: number,
    limit: number,
  ): Promise<V3Page<V3WorkflowRunEvent>>;
  listNodeExecutions(context: V3RequestContext, runId: string): Promise<V3WorkflowNodeExecution[]>;
  resolveInput(
    context: V3MutationContext,
    runId: string,
    input: V3ResolveWorkflowInput,
  ): Promise<V3WorkflowRun>;
  cancelRun(context: V3MutationContext, runId: string): Promise<V3WorkflowRun>;
}

export interface V3ImportKnowledgeEmailMaterials {
  title: string;
  parentFolderId: string | null;
  materials: Array<Omit<V3CreateKnowledgeFileMaterial, 'parentFolderId'>>;
}

export interface V3KnowledgeRepository {
  listBases(context: V3RequestContext, input: V3KnowledgeListInput): Promise<V3Page<V3KnowledgeBase>>;
  getBase(context: V3RequestContext, knowledgeBaseId: string): Promise<V3KnowledgeBase | undefined>;
  createBase(context: V3MutationContext, input: V3CreateKnowledgeBase): Promise<V3KnowledgeBase>;
  renameBase(
    context: V3MutationContext,
    knowledgeBaseId: string,
    input: V3RenameKnowledgeBase,
  ): Promise<V3KnowledgeBase>;
  deleteBase(context: V3MutationContext, knowledgeBaseId: string): Promise<void>;
  listFolders(context: V3RequestContext, knowledgeBaseId: string): Promise<V3KnowledgeFolder[]>;
  createFolder(
    context: V3MutationContext,
    knowledgeBaseId: string,
    input: V3CreateKnowledgeFolder,
  ): Promise<V3KnowledgeFolder>;
  renameFolder(
    context: V3MutationContext,
    knowledgeBaseId: string,
    folderId: string,
    input: V3RenameKnowledgeFolder,
  ): Promise<V3KnowledgeFolder>;
  deleteSelection(
    context: V3MutationContext,
    knowledgeBaseId: string,
    input: V3DeleteKnowledgeSelection,
  ): Promise<void>;
  listCards(
    context: V3RequestContext,
    knowledgeBaseId: string,
    input: V3PaginationInput,
  ): Promise<V3Page<V3KnowledgeCard>>;
  listCollaborators(context: V3RequestContext, knowledgeBaseId: string): Promise<V3KnowledgeCollaborator[]>;
  inviteCollaborator(
    context: V3MutationContext,
    knowledgeBaseId: string,
    input: V3InviteKnowledgeCollaborator,
  ): Promise<V3KnowledgeCollaborator>;
  removeCollaborator(
    context: V3MutationContext,
    knowledgeBaseId: string,
    collaboratorId: string,
  ): Promise<void>;
  listSchedules(context: V3RequestContext, knowledgeBaseId: string): Promise<V3KnowledgeSchedule[]>;
  createSchedule(
    context: V3MutationContext,
    knowledgeBaseId: string,
    input: V3CreateKnowledgeSchedule,
  ): Promise<V3KnowledgeSchedule>;
  updateSchedule(
    context: V3MutationContext,
    knowledgeBaseId: string,
    scheduleId: string,
    input: V3UpdateKnowledgeSchedule,
  ): Promise<V3KnowledgeSchedule>;
  deleteSchedule(context: V3MutationContext, knowledgeBaseId: string, scheduleId: string): Promise<void>;
  listScheduleRuns(
    context: V3RequestContext,
    knowledgeBaseId: string,
    scheduleId: string,
  ): Promise<V3KnowledgeScheduleRun[]>;
  getSettings(context: V3RequestContext, knowledgeBaseId: string): Promise<V3KnowledgeSettings>;
  updateSettings(
    context: V3MutationContext,
    knowledgeBaseId: string,
    input: V3UpdateKnowledgeSettings,
  ): Promise<V3KnowledgeSettings>;
  queueCompilation(
    context: V3MutationContext,
    knowledgeBaseId: string,
    input: V3CompileKnowledgeBase,
  ): Promise<V3KnowledgeBase>;
  listMaterials(
    context: V3RequestContext,
    knowledgeBaseId: string,
    input: V3PaginationInput,
  ): Promise<V3Page<V3KnowledgeMaterial>>;
  addUrlMaterial(
    context: V3MutationContext,
    knowledgeBaseId: string,
    input: V3CreateKnowledgeUrlMaterial,
  ): Promise<V3KnowledgeMaterial>;
  renameMaterial(
    context: V3MutationContext,
    knowledgeBaseId: string,
    materialId: string,
    input: V3RenameKnowledgeMaterial,
  ): Promise<V3KnowledgeMaterial>;
  addFileMaterial(
    context: V3MutationContext,
    knowledgeBaseId: string,
    input: V3CreateKnowledgeFileMaterial,
  ): Promise<V3KnowledgeMaterial>;
  importEmailMaterials(
    context: V3MutationContext,
    knowledgeBaseId: string,
    input: V3ImportKnowledgeEmailMaterials,
  ): Promise<V3KnowledgeMaterial[]>;
  listBindings(context: V3RequestContext, wakerId?: string): Promise<V3KnowledgeBinding[]>;
  bind(
    context: V3MutationContext,
    knowledgeBaseId: string,
    input: V3KnowledgeBindingInput,
  ): Promise<V3KnowledgeBinding>;
  unbind(context: V3MutationContext, knowledgeBaseId: string, input: V3KnowledgeBindingInput): Promise<void>;
}

export interface V3KnowledgeCardDraft {
  title: string;
  contentMarkdown: string;
  keywords: string[];
}

export interface V3SkillConnectorRepository {
  listBoundConnectorConfigurations(
    context: V3RequestContext,
    versionIds: readonly string[],
  ): Promise<
    Array<{
      versionId: string;
      connectorId: string;
      name: string;
      transport: V3Connector['transport'];
      command: string | null;
      arguments: string[];
      url: string | null;
      timeoutSeconds: number;
      selectedTools: string[];
      secretRefs: Record<string, string>;
    }>
  >;
  listSkills(
    context: V3RequestContext,
    wakerId: string,
    input: V3PaginationInput,
  ): Promise<V3Page<V3SkillInstallation>>;
  isSkillPackageReferenced(context: V3RequestContext, objectKey: string): Promise<boolean>;
  installSkill(
    context: V3MutationContext,
    wakerId: string,
    input: {
      // Trusted host publication only; never populated by public upload inputs.
      evolutionPolicyVersion?: number;
      marketplaceSkillId?: string;
      name: string;
      description: string;
      source: V3SkillInstallation['source'];
      contentSha256: string;
      packageSha256: string;
      inventory?: string[];
      fileName: string;
      markdown: string;
      selfEvolution: boolean;
      objectKey: string | null;
      sizeBytes: number;
      mediaType: string;
      expectedConfigurationVersionId: string;
      changeSummary: string;
    },
  ): Promise<V3SkillInstallation>;
  updateSkill(
    context: V3MutationContext,
    skillId: string,
    input: {
      // Trusted runtime only; never populated by user upload/API inputs.
      evolutionPolicyVersion?: number;
      managedOperation?: 'edit' | 'write_file';
      name: string;
      description: string;
      source: V3SkillInstallation['source'];
      contentSha256: string;
      packageSha256: string;
      inventory?: string[];
      fileName: string;
      markdown: string;
      selfEvolution: boolean;
      objectKey: string | null;
      sizeBytes: number;
      mediaType: string;
      expectedVersion: number;
      expectedConfigurationVersionId: string;
      changeSummary: string;
    },
  ): Promise<V3SkillInstallation>;
  listSkillVersions(context: V3RequestContext, skillId: string): Promise<V3SkillVersion[]>;
  compareSkillVersions(
    context: V3RequestContext,
    skillId: string,
    fromVersionId: string | null,
    toVersionId: string,
  ): Promise<V3SkillComparison>;
  changeSkillLifecycle(
    context: V3MutationContext,
    skillId: string,
    input: V3SkillLifecycleInput,
  ): Promise<V3SkillInstallation | undefined>;
  getBuiltinCapabilities(
    context: V3RequestContext,
    wakerId: string,
  ): Promise<V3WakerBuiltinCapabilities | undefined>;
  updateBuiltinCapabilities(
    context: V3MutationContext,
    wakerId: string,
    input: V3WakerBuiltinCapabilities,
  ): Promise<V3WakerBuiltinCapabilities>;
  getBrowserConnectorEnablement(
    context: V3RequestContext,
    wakerId: string,
  ): Promise<V3BrowserConnectorEnablement | undefined>;
  updateBrowserConnectorEnablement(
    context: V3MutationContext,
    wakerId: string,
    input: V3UpdateBrowserConnectorEnablement,
  ): Promise<V3BrowserConnectorEnablement>;
  getSkillEvolutionPolicy(
    context: V3RequestContext,
    wakerId: string,
  ): Promise<V3SkillEvolutionPolicy | undefined>;
  updateSkillEvolutionPolicy(
    context: V3MutationContext,
    wakerId: string,
    input: V3UpdateSkillEvolutionPolicy,
  ): Promise<V3SkillEvolutionPolicy>;
  listConnectors(
    context: V3RequestContext,
    wakerId: string,
    input: V3PaginationInput,
  ): Promise<V3Page<V3Connector>>;
  createConnector(
    context: V3MutationContext,
    wakerId: string,
    input: V3CreateConnector & {
      expectedConfigurationVersionId: string;
      secretRefs: Record<string, string>;
    },
  ): Promise<V3Connector>;
  updateConnector(
    context: V3MutationContext,
    connectorId: string,
    input: Omit<V3UpdateConnector, 'environment'> & { secretRefs: Record<string, string> },
  ): Promise<V3Connector>;
  getConnector(context: V3RequestContext, connectorId: string): Promise<V3Connector | undefined>;
  recordConnectorDiagnostic(
    context: V3MutationContext,
    connectorId: string,
    diagnostic: V3Connector['diagnostic'],
  ): Promise<V3Connector>;
  updateConnectorTools(
    context: V3MutationContext,
    connectorId: string,
    input: V3ConnectorToolSelectionInput,
  ): Promise<V3Connector>;
  changeConnectorLifecycle(
    context: V3MutationContext,
    connectorId: string,
    input: V3ConnectorLifecycleInput,
  ): Promise<V3Connector | undefined>;
  getConnectorSecretRefs(context: V3RequestContext, connectorId: string): Promise<Record<string, string>>;
}

/**
 * Stages a parsed Skill package before an atomic Waker creation consumes it.
 * Implementations must scope every read and mutation to the authenticated
 * workspace/user and must never expose objectKey or package contents through
 * the public preparation result.
 */
export interface V3SkillPackagePreparationRepository {
  isObjectReferenced(context: V3RequestContext, objectKey: string): Promise<boolean>;
  create(
    context: V3MutationContext,
    input: V3SkillPackagePreparationInput,
  ): Promise<V3SkillPackagePreparation>;
  getForCreate(
    context: V3RequestContext,
    preparationId: string,
  ): Promise<V3SkillPackagePreparationForCreate | undefined>;
  expire(context: V3MutationContext, preparationId: string): Promise<{ objectKey?: string }>;
}

export interface V3ImRepository {
  getInboundChannel(
    channelId: string,
  ): Promise<{ workspaceId: string; channel: V3ImChannel; secretRefs: Record<string, string> } | undefined>;
  listChannels(context: V3RequestContext, input: V3PaginationInput): Promise<V3Page<V3ImChannel>>;
  getChannel(context: V3RequestContext, channelId: string): Promise<V3ImChannel | undefined>;
  createChannel(
    context: V3MutationContext,
    input: Omit<V3CreateImChannel, 'credentials'> & { secretRefs: Record<string, string> },
  ): Promise<V3ImChannel>;
  updateChannel(
    context: V3MutationContext,
    channelId: string,
    input: Omit<V3UpdateImChannel, 'credentials'> & { secretRefs: Record<string, string> },
  ): Promise<V3ImChannel>;
  recordChannelDiagnostic(
    context: V3MutationContext,
    channelId: string,
    diagnostic: V3ImChannel['diagnostic'],
  ): Promise<V3ImChannel>;
  changeChannelLifecycle(
    context: V3MutationContext,
    channelId: string,
    input: V3ImChannelLifecycleInput,
  ): Promise<V3ImChannel | undefined>;
  getChannelSecretRefs(context: V3RequestContext, channelId: string): Promise<Record<string, string>>;
  listConversations(
    context: V3RequestContext,
    input: V3ImConversationListInput,
  ): Promise<V3Page<V3ImConversation>>;
  listPairingRequests(
    context: V3RequestContext,
    input: V3PaginationInput,
  ): Promise<V3Page<V3ImPairingRequest>>;
  createPairing(
    context: V3MutationContext,
    input: V3CreateImPairing,
    authorization: V3ModelAuthorization,
  ): Promise<V3ImConversation>;
  createManualPairing(
    context: V3MutationContext,
    input: Omit<V3CreateManualImPairing, 'receiveId'> & {
      externalIdentity: string;
      externalReceiveRef: string;
    },
    authorization: V3ModelAuthorization,
  ): Promise<V3ImConversation>;
  updatePairing(
    context: V3MutationContext,
    conversationId: string,
    input: V3UpdateImPairing,
    authorization: V3ModelAuthorization,
  ): Promise<V3ImConversation>;
  changePairingLifecycle(
    context: V3MutationContext,
    conversationId: string,
    input: V3ImPairingLifecycleInput,
    authorization?: V3ModelAuthorization,
  ): Promise<V3ImConversation | undefined>;
  resolvePairingRequest(
    context: V3MutationContext,
    requestId: string,
    input: V3ResolveImPairingRequest,
    authorization?: V3ModelAuthorization,
  ): Promise<V3ImPairingRequest>;
  recordExternalEvent(
    channelId: string,
    input: {
      deliveryId: string;
      externalConversationIdentity: string;
      alternateExternalIdentities?: string[];
      conversationName: string;
      conversationType: V3ImConversation['type'];
      payloadSha256: string;
      occurredAt: string;
      defaultModel: string;
      authorizeModel(model: string): void;
    },
  ): Promise<V3ImExternalEventResult>;
  bindProductConversation(
    context: V3RequestContext,
    conversationId: string,
    productConversationId: string,
    externalReceiveRef: string,
  ): Promise<string>;
  recordRunDelivery(context: V3RequestContext, runId: string, conversationId: string): Promise<void>;
  getRunDelivery(context: V3RequestContext, runId: string): Promise<V3ImRunDelivery | undefined>;
  recordRunDeliveryOutcome(
    context: V3RequestContext,
    runId: string,
    state: 'sent' | 'failed',
    failureDetail: string | null,
  ): Promise<void>;
}

export interface V3ConversationRepository {
  getGroupActivitySnapshot(
    context: V3RequestContext,
    conversationId: string,
  ): Promise<V3GroupActivitySnapshot>;
  listGroupMessageHistory(
    context: V3RequestContext,
    conversationId: string,
    beforeSequence?: number,
  ): Promise<V3Page<V3Event>>;
  list(context: V3RequestContext, input: V3ConversationListInput): Promise<V3Page<V3Conversation>>;
  get(context: V3RequestContext, conversationId: string): Promise<V3Conversation | undefined>;
  create(context: V3MutationContext, input: V3CreateConversation): Promise<V3Conversation>;
  appendEvent(
    context: V3RequestContext,
    conversationId: string,
    event: Omit<V3Event, 'id' | 'sequence' | 'occurredAt'>,
  ): Promise<V3Event>;
  listEvents(
    context: V3RequestContext,
    conversationId: string,
    afterSequence: number,
    limit: number,
  ): Promise<V3EventPage>;
  listUnread(context: V3RequestContext, input: V3UnreadQuery): Promise<V3UnreadCounts>;
  markSubjectRead(context: V3RequestContext, input: V3MarkSubjectRead): Promise<V3UnreadCounts>;
  markAllRead(context: V3RequestContext): Promise<V3UnreadCounts>;
}

export interface V3GroupRunQueueTransition {
  targetBatchId: string;
  affectedRunIds: string[];
  preemptedRunIds: string[];
  releasedRunIds: string[];
  dispatchRunIds: string[];
}

export interface V3GroupMessagePublicationInput {
  attachmentIds?: string[];
  toolCallId: string;
  text: string;
  mentionTarget: string | null;
  privateTargets?: string[];
  executionClaim: { dispatchKey: string; claimId: string };
  authorizeModel(model: string): void;
}

export interface V3GroupMessagePublication {
  message: V3Event;
  replayed: boolean;
  event: V3DurableEvent;
  handoffTransition: V3GroupRunQueueTransition | null;
}

export interface V3GroupInboxParticipant {
  id: string;
  conversationId: string;
  kind: 'waker' | 'human';
  subjectId: string;
  name: string;
  activeRunId: string | null;
  contextSeenSequence: number;
}

export interface V3GroupCompletionInspection {
  ready: boolean;
  conversationId: string;
  runId: string;
  participantId: string;
  claimId: string;
  unreadMessageIds: string[];
  pendingMessageIds: string[];
  checkpoint: 'required' | 'valid';
  publishedMessages: Array<{ id: string; sequence: number }>;
}

export interface V3GroupInboxPage {
  claimId: string;
  participantId: string;
  runId: string;
  context: V3Event[];
  messages: V3Event[];
  candidateCount: number;
  claimedCount: number;
  pendingCount: number;
  nextCursor: string | null;
  exhausted: boolean;
  members: Array<Pick<V3GroupInboxParticipant, 'id' | 'kind' | 'subjectId' | 'name'> & { roleName: string }>;
}

export interface V3GroupInboxReadResult {
  readCount: number;
  alreadyReadCount: number;
  unreadCount: number;
}

export interface V3GroupInboxClaimInput {
  executionClaim: { dispatchKey: string; claimId: string };
  limit?: number;
  cursor?: string;
  initial?: boolean;
  /** Host-only delivery of queued arrivals into the current unfinished batch. */
  arrivals?: boolean;
}

export interface V3ExecutionRepository {
  getTask(context: V3RequestContext, taskId: string): Promise<V3Task | undefined>;
  listTasks(context: V3RequestContext, input: V3TaskListInput): Promise<V3TaskPage>;
  renameTask(context: V3MutationContext, taskId: string, input: V3RenameTask): Promise<V3Task>;
  hideTask(context: V3MutationContext, taskId: string, input: V3HideTask): Promise<void>;
  readTaskResult(context: V3MutationContext, taskId: string, input: V3ReadTaskResult): Promise<void>;
  pinTask(context: V3MutationContext, taskId: string, input: V3PinTask): Promise<V3Task>;
  getRun(context: V3RequestContext, runId: string): Promise<V3Run | undefined>;
  appendRunEvent(
    context: V3RequestContext,
    runId: string,
    event: Omit<V3DurableEvent, 'id' | 'workspaceId' | 'runId' | 'sequence' | 'occurredAt'>,
  ): Promise<V3DurableEvent>;
  listRunEvents(
    context: V3RequestContext,
    runId: string,
    afterSequence: number,
    limit: number,
  ): Promise<V3Page<V3DurableEvent>>;
  listRunEventHistory(
    context: V3RequestContext,
    runId: string,
    input?: { beforeSequence?: number; limit?: number },
  ): Promise<V3Page<V3DurableEvent>>;
  cancelRun(context: V3MutationContext, runId: string): Promise<V3Run | V3GroupRunQueueTransition>;
  undoQueuedGroupInbox(context: V3MutationContext, runId: string): Promise<V3GroupRunQueueTransition>;
  sendQueuedRunNow(context: V3MutationContext, runId: string): Promise<V3GroupRunQueueTransition>;
  createApproval(
    context: V3RequestContext,
    runId: string,
    input: {
      capability: string;
      requestHash: string;
      scope: string;
      risk: V3Approval['risk'];
      policyVersion: number;
      expiresAt: string;
    },
  ): Promise<{ approval: V3Approval; event: V3DurableEvent }>;
  getApproval(context: V3RequestContext, approvalId: string): Promise<V3Approval | undefined>;
  /** An earlier approval in the run's task was granted `rememberedFor: 'task'` for this exact scope. */
  hasTaskRememberedApproval(
    context: V3RequestContext,
    runId: string,
    input: { capability: string; scope: string },
  ): Promise<boolean>;
  listPendingApprovals(
    context: V3RequestContext,
    input: V3PaginationInput,
  ): Promise<V3Page<V3ApprovalWorkItem>>;
  resolveApproval(
    context: V3MutationContext,
    approvalId: string,
    input: V3ResolveApproval,
  ): Promise<V3Approval>;
  createArtifact(
    context: V3RequestContext,
    runId: string,
    input: Omit<V3Artifact, 'id' | 'runId' | 'createdAt'>,
  ): Promise<V3Artifact>;
  getArtifact(context: V3RequestContext, artifactId: string): Promise<V3Artifact | undefined>;
  listArtifacts(context: V3RequestContext, runId: string): Promise<V3Artifact[]>;
  listConversationArtifacts(context: V3RequestContext, conversationId: string): Promise<V3Artifact[]>;
}

export interface V3RepositorySet {
  wakers: V3WakerRepository;
  groups: V3GroupRepository;
  workspaceReferences: V3WorkspaceReferenceRepository;
  conversations: V3ConversationRepository;
  execution: V3ExecutionRepository;
}

export interface V3RepositoryTransactionPort {
  transaction<T>(operation: (repositories: V3RepositorySet) => Promise<T>): Promise<T>;
}

export interface V3ExecutionDispatchRequest {
  context: V3MutationContext;
  conversationId: string;
  taskId: string;
  workspaceReferenceId: string | null;
  effectiveConfigurationVersionId: string;
  executionTarget: V3Run['executionTarget'];
}

export interface V3ExecutionDispatchPort {
  dispatch(input: V3ExecutionDispatchRequest): Promise<V3Run>;
  cancel(context: V3MutationContext, runId: string): Promise<void>;
}

export type V3DirectoryListing = {
  path: string;
  parent: string | null;
  home: string;
  drives: string[];
  entries: Array<{ name: string; kind: 'directory' | 'file' }>;
};

export interface V3WorkspacePlatformCapability {
  selectDirectory(): Promise<V3WorkspaceReference | null>;
  selectSensitiveDirectory?(): Promise<string | null>;
  listDirectory?(path?: string, signal?: AbortSignal): Promise<V3DirectoryListing>;
  uploadDirectConversationAttachments?(wakerId: string, paths: string[]): Promise<V3ConversationAttachment[]>;
  registerDirectory?(path: string): Promise<V3WorkspaceReference | null>;
  list(): Promise<V3WorkspaceReference[]>;
  revoke(referenceId: string): Promise<void>;
}

export interface V3ArtifactPlatformCapability {
  reveal(artifactId: string): Promise<void>;
  saveAs(artifactId: string): Promise<boolean>;
}

export interface V3ConfigurationPlatformCapability {
  open(): Promise<void> | void;
}

export interface V3AutomationPlatformCapability {
  apiOrigin: string;
  /** User-initiated copy of the desktop-only local API credential; never expose it in web capabilities. */
  copyAccessToken?(): Promise<void>;
}

export interface V3DesktopUpdateState {
  status: 'idle' | 'checking' | 'downloading' | 'ready' | 'restarting' | 'failed';
  currentVersion: string;
  availableVersion?: string;
  received?: number;
  total?: number;
  detail?: string;
}

export interface V3ReleasePlatformCapability {
  currentVersion: string;
  getUpdateState?(): Promise<V3DesktopUpdateState>;
  restart?(): Promise<void>;
  check?(): Promise<{
    status: 'current' | 'available';
    currentVersion: string;
    availableVersion?: string;
  }>;
  openDownloads(): Promise<void> | void;
}

export interface V3SystemPreferences {
  launchAtStartup: boolean;
  keepSystemAwake: boolean;
  allowRemoteConfiguration: boolean;
}

export interface V3SystemPlatformCapability {
  get(): Promise<V3SystemPreferences>;
  set(key: keyof V3SystemPreferences, value: boolean): Promise<V3SystemPreferences>;
}

export interface V3NetworkPlatformCapability {
  currentDeviceId?(): Promise<string>;
  diagnose(): Promise<V3NetworkDiagnostics>;
  listDevices?(): Promise<V3DesktopMachineInventory>;
  unbindDevice?(id: string): Promise<void>;
  renameDevice?(id: string, name: string): Promise<void>;
}

/** Shared end-user auth capability; implementations never expose provider tokens. */
export interface V3AuthPlatformCapability {
  readonly mode: V3AuthMode;
  getSession(): Promise<V3AuthSession>;
  login(): Promise<V3AuthSession>;
  /** Optional administrator sign-in; the key never crosses into the renderer session. */
  adminLogin?(apiKey: string): Promise<V3AuthSession>;
  logout(): Promise<void>;
}

/**
 * Trusted host boundary for an optional per-user AI gateway virtual key.
 * Implementations must never return the plaintext key; only its masked status
 * crosses into the renderer.
 */
export interface V3AiGatewayVirtualKeyPlatformCapability {
  get(): Promise<V3AiGatewayVirtualKeyStatus>;
  set(input: V3AiGatewayVirtualKeyInput): Promise<V3AiGatewayVirtualKeyStatus>;
  clear(): Promise<V3AiGatewayVirtualKeyStatus>;
  /** Status-first claim; retryRejected is reserved for the first request of a new user action. */
  claim?(signal?: AbortSignal, retryRejected?: boolean): Promise<V3AiGatewayVirtualKeyClaimResponse>;
  /** Last bounded server-advertised retry delay for a pending claim. */
  claimRetryDelayMs?(): number | undefined | Promise<number | undefined>;
  /** Monotonic local write generation used to reject stale auto-claim results. */
  claimMutationVersion?(): number;
}

export interface V3BrowserPlatformCapability {
  getState(wakerId: string): Promise<V3BrowserConnectorState>;
  openWebStore(): Promise<void>;
  copyExtensionsAddress(): Promise<void>;
  openFallbackDirectory(): Promise<void>;
  copyFallbackPath(): Promise<void>;
  checkTabs(wakerId: string): Promise<void>;
}

export interface V3PlatformCapabilities {
  environment: 'web' | 'desktop';
  navigation?: 'browser' | 'memory';
  deviceName?: string;
  workspace?: V3WorkspacePlatformCapability;
  /** Device-scoped directory browser for project sources, including remote Web sessions. */
  projectDirectory?: Required<Pick<V3WorkspacePlatformCapability, 'listDirectory' | 'registerDirectory'>>;
  artifact?: V3ArtifactPlatformCapability;
  configuration?: V3ConfigurationPlatformCapability;
  automation?: V3AutomationPlatformCapability;
  release?: V3ReleasePlatformCapability;
  system?: V3SystemPlatformCapability;
  network?: V3NetworkPlatformCapability;
  aiGatewayVirtualKey?: V3AiGatewayVirtualKeyPlatformCapability;
  auth?: V3AuthPlatformCapability;
  browser?: V3BrowserPlatformCapability;
}
