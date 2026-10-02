/** Mirrors docs/api-contract.md. Keep field names byte-identical to the contract. */

export type User = {
  id: string;
  email: string;
  name: string;
  credits: number;
  canRevokeSessions: boolean;
};

export type LookupResult = {
  email: string;
  exists: boolean;
};

export type ModelOption = { id: string };

export type Settings = {
  baseUrl: string;
  model: string;
  apiKeyMasked: string;
  hasUserKey: boolean;
  source: "server" | "user" | "unconfigured";
  models: ModelOption[];
  modelsStatus: "available" | "unavailable" | "unconfigured";
  configurationError: string | null;
};

export type ProjectStatus =
  | "draft"
  | "planning"
  | "awaiting_approval"
  | "building"
  | "ready"
  | "error" | "cancelled" | "timed_out" | "interrupted";
// Persisted terminal outcomes are distinct from successful generation.

export type ProjectSummary = {
  id: string;
  title: string;
  summary: string | null;
  kind: string | null;
  status: ProjectStatus;
  slug: string | null;
  publishedAt: string | null;
  createdAt: string;
  updatedAt: string;
};

export type AgentRole = "mike" | "iris" | "emma" | "bob" | "alex";
export type MessageRole = AgentRole | "user" | "system";

export type Message = {
  id: string;
  role: MessageRole;
  content: string;
  runId: string | null;
  createdAt: string;
};

export type SetupStep =
  | { action: "fill"; selector: string; value: string }
  | { action: "click"; selector: string }
  | { action: "press"; selector: string; key: string };

export type Check =
  | { type: "exists"; selector: string }
  | { type: "text"; selector: string; contains: string }
  | { type: "flow"; selector: string; expect: string; setup?: SetupStep[] };

export type Requirement = {
  key: string;
  title: string;
  detail: string;
  checks: Check[];
};

export type FileEntry = {
  path: string;
  bytes: number;
  updatedAt: string;
};

export type AcceptanceResult = {
  key: string;
  checkIndex: number;
  passed: boolean;
  note: string;
};

export type AcceptanceRun = {
  id: string;
  passed: number;
  total: number;
  results: AcceptanceResult[];
  createdAt: string;
};

export type RaceHeat = {
  runStartedAt?: string | null;
  id: string;
  model: string;
  status: "queued" | "running" | "done" | "failed" | "cancelled" | "timed_out" | "interrupted" | "error";
  runId: string | null;
  revisionId: string | null;
  incompleteSavedRevisionId: string | null;
  previewUrl: string | null;
  elapsedMs: number | null;
  inputTokens: number;
  outputTokens: number;
  fileCount: number;
  bytes: number;
  error: string | null;
};

export type RaceSummary = {
  id: string;
  status: "running" | "done" | "failed" | "cancelled" | "interrupted" | "error";
  heats: RaceHeat[];
  winnerHeatId: string | null;
  createdAt: string;
};

export type ProjectDetail = ProjectSummary & {
  prompt: string;
  messages: Message[];
  requirements: Requirement[];
  files: FileEntry[];
  revisionId: string | null;
  incompleteSavedRevisionId: string | null;
  acceptance: AcceptanceRun | null;
  activeRunId: string | null;
  latestRun: { id: string; status: string; phase: string; error: string | null; startedAt: string; finishedAt: string | null } | null;
  buildBudgetSeconds: number;
  legacyPublicationAvailable: boolean;
  legacyAdoptionAvailable: boolean;
  race: RaceSummary | null;
};

export type VerifiedPublication = {
  releaseId: string;
  revisionId: string;
  verificationId: string | null;
  verificationMode: "advisory" | "required";
  contractDigest: string | null;
  policyDigest: string | null;
  audience: "owner" | "public";
  slug: string;
  generation: number;
  live: boolean;
  bindingId: string;
  pinnedUrl: string | null;
  sharingUrl: string | null;
};

export type PublicationSnapshot = {
  releaseId: string;
  version: number;
  revisionId: string;
  createdAt: string;
  audience: "owner" | "public";
  verificationMode: "advisory" | "required";
  verificationId: string | null;
  bindingId: string;
  previewUrl: string | null;
  isLive: boolean;
  restoredFrom: string | null;
};

export type PublicationHistory = {
  items: PublicationSnapshot[];
  nextCursor: string | null;
  publicationPolicy: "advisory" | "required";
};

export type VerificationStatus = {
  requestId: string;
  revisionId: string;
  contractDigest: string;
  state: "reserved" | "running" | "passed" | "failed" | "cancelled" | "timed_out" | "unresolved" | "expired";
  deadline: number;
  total: number | null;
  passed: number | null;
  completedAt: number | null;
};

export type LedgerEntry = {
  delta: number;
  reason: string;
  at: string;
};

export type Usage = {
  credits: number;
  spent: number;
  runs: number;
  inputTokens: number;
  outputTokens: number;
  ledger: LedgerEntry[];
};

export type PublishResult = { slug: string; url: string };

/** SSE payloads. The contract passes runtime `type` through verbatim, so the
 *  union stays open-ended and every payload field is optional. */
export type RunEventType =
  | "run.started"
  | "thinking.delta"
  | "message.delta"
  | "message.completed"
  | "tool.started"
  | "tool.completed"
  | "tool.failed"
  | "usage.updated"
  | "run.completed"
  | "run.failed"
  | "squad.role_started"
  | "project.updated";

export type RunEventPayload = {
  delta?: string;
  text?: string;
  toolName?: string;
  args?: Record<string, unknown> | string | null;
  result?: unknown;
  inputTokens?: number;
  outputTokens?: number;
  resultText?: string;
  message?: string;
  role?: MessageRole;
  status?: ProjectStatus;
  requirements?: Requirement[];
  files?: FileEntry[];
  heatId?: string;
};

export type RunEvent = {
  seq: number;
  runId: string | null;
  role: MessageRole | null;
  type: RunEventType | (string & {});
  payload: RunEventPayload;
  at: string;
};
