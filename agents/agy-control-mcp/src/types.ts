export type ModelTier = "auto" | "fast" | "reasoning" | "expert";
export type DelegationMode = "automatic" | "user_requested";
export type WorkspaceMode = "git" | "snapshot";
export type ResolvedTier = Exclude<ModelTier, "auto">;
export type RoutingProfile = "workhorse" | "deep_reasoning" | "high_risk_debug";

export interface RoutingDecision {
  policy_version: string;
  profile: RoutingProfile;
  reason_codes: string[];
  requested_tier: ModelTier;
  resolved_tier: ResolvedTier;
  candidate_chain: string[];
}

export interface ModelAttempt {
  tier: ResolvedTier;
  model: string;
  trigger: "primary" | "primary_unavailable" | "quota_fallback" | "model_selection_fallback" | "contract_escalation" | "transient_retry";
  outcome: string;
  usage?: TokenUsage;
  error?: string;
}
export type RunState =
  | "queued"
  | "running"
  | "ready_for_review"
  | "needs_follow_up"
  | "blocked"
  | "failed"
  | "cancelled"
  | "interrupted"
  | "applied"
  | "discarded";

export interface TokenUsage {
  input_tokens?: number;
  output_tokens?: number;
  thinking_tokens?: number;
  cache_read_tokens?: number;
  total_tokens?: number;
}

export interface AgyEvent {
  event?: "init" | "step_update" | "result" | string;
  init?: { conversation_id?: string; model?: string; permission_mode?: string };
  step_update?: {
    conversation_id?: string;
    step_index?: number;
    state?: string;
    step_type?: string;
    usage?: TokenUsage;
  };
  result?: {
    conversation_id?: string;
    status?: string;
    response?: string;
    structured_output?: unknown;
    num_turns?: number;
    usage?: TokenUsage;
  };
}

export interface AgyOutcome {
  state: "done" | "partial" | "failed" | "timeout" | "cancelled";
  failureReason?: "quota_exhausted" | "timeout" | "spawn_failed" | "agy_error" | "interrupted" | "budget_exceeded";
  errorMessage?: string;
  exitCode: number | null;
  conversationId?: string;
  model?: string;
  response?: string;
  structuredOutput?: unknown;
  numTurns?: number;
  usage: TokenUsage;
  conversationUsage?: TokenUsage;
}

export interface PromptAudit {
  tier: ResolvedTier;
  estimated_prompt_tokens: number;
  context_budget_tokens: number;
  redactions: string[];
  truncated_context: boolean;
  warnings: string[];
}

export interface CompiledPrompt {
  prompt: string;
  audit: PromptAudit;
}

export interface GateResult {
  name: string;
  passed: boolean;
  detail?: string;
}

export interface WorkerReport {
  patch: string;
  summary: string;
  confidence: number;
  changed_files: string[];
  assumptions?: string[];
  risks?: string[];
  tests_run?: string[];
  uncertainties?: string[];
  recommended_action: "ready_for_review" | "needs_changes" | "blocked";
}

export interface RunMetadata {
  run_id: string;
  repo_root: string;
  workspace_mode: WorkspaceMode;
  worktree_path: string;
  artifact_path: string;
  title: string;
  requested_tier: ModelTier;
  delegation_mode: DelegationMode;
  risk_level: "low" | "medium" | "high";
  routing_decision?: RoutingDecision;
  model_attempts?: ModelAttempt[];
  fallback_used?: boolean;
  fallback_reason?: string;
  state: RunState;
  phase?: string;
  selected_model?: string;
  conversation_id?: string;
  allowed_paths: string[];
  forbidden_paths: string[];
  success_criteria: string[];
  test_command: string;
  timeout_seconds: number;
  token_budget: number;
  usage: TokenUsage;
  conversation_usage?: TokenUsage;
  gates: GateResult[];
  prompt_audit?: PromptAudit;
  report_sha256?: string;
  patch_sha256?: string;
  base_commit: string;
  snapshot_baseline?: { files: Record<string, { sha256: string; size: number; mode: number }>; directories: string[] };
  snapshot_fingerprint?: string;
  actual_changed_paths: string[];
  unsafe_shell_command: true;
  error?: string;
  created_at: string;
  updated_at: string;
}

export interface DelegateInput {
  repo_root: string;
  workspace_mode?: "auto" | WorkspaceMode;
  title: string;
  objective: string;
  current_state: string;
  target_state: string;
  context?: string;
  allowed_paths: string[];
  forbidden_paths?: string[];
  success_criteria: string[];
  test_command: string;
  tier?: ModelTier;
  delegation_mode?: DelegationMode;
  timeout_seconds?: number;
  token_budget?: number;
}

export interface FollowUpInput {
  run_id: string;
  requested_correction: string;
  failing_tests_or_logs?: string;
  decisions_to_keep?: string[];
  updated_success_criteria?: string[];
  timeout_seconds?: number;
  token_budget?: number;
}
