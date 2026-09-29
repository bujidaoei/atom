export type Role = "user" | "mike" | "iris" | "emma" | "bob" | "alex" | "system";

export type Check =
  | { op: "exists"; selector: string }
  | { op: "text"; contains: string }
  | {
      op: "flow";
      steps: Array<
        | { do: "fill"; selector: string; value?: string }
        | { do: "click"; selector: string }
        | { do: "see"; contains: string }
      >;
    };

export type Requirement = {
  key: string;
  title: string;
  detail: string;
  priority: "must" | "should";
  checks: Check[];
};

export type ActivityStep = {
  kind: "narration" | "tool" | "thinking";
  title: string;
  detail: string;
  status: "run" | "done";
};

export type Message = {
  id: string;
  role: Role;
  content: string;
  activity?: ActivityStep[];
  created_at: string;
};

export type AcceptanceItem = {
  key: string;
  title: string;
  priority: string;
  ok: boolean;
  checks: Array<{ op: string; ok: boolean; detail: string; index?: number }>;
};

export type Project = {
  id: string;
  name: string;
  prompt: string;
  status: string;
  error_message: string;
  contract_locked: boolean;
  contract_version: number;
  updated_at: string;
  lead_note: string;
  research_note: string;
  architecture_note: string;
  requirements: Requirement[];
  messages: Message[];
  html: string;
  files: Array<{ path: string; content: string }>;
  trace: Array<{ key: string; evidence: string }>;
  preview_state: Record<string, string>;
  pending_amendment: { reason?: string; requirements?: Requirement[] } | null;
  latest_acceptance: {
    id: string;
    passed: number;
    total: number;
    created_at: string;
    items: AcceptanceItem[];
  } | null;
};

export type ProjectSummary = {
  id: string;
  name: string;
  prompt: string;
  status: string;
  contract_locked: boolean;
  contract_version: number;
  updated_at: string;
};

export type User = {
  id: string;
  name: string;
  email: string;
};

export type SettingsView = {
  base_url: string;
  base_url_source: "user" | "server";
  model: string;
  model_source: "user" | "server";
  api_key_masked: string;
  api_key_source: "user" | "server" | "none";
  configured: boolean;
  models: Array<{ id: string; label: string }>;
};

export type Usage = {
  calls: number;
  prompt_tokens: number;
  completion_tokens: number;
};

export type RuntimeResult = {
  key: string;
  index: number;
  ok: boolean;
  detail: string;
};
