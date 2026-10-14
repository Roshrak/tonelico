import type { ModelTier, ResolvedTier, RoutingDecision, RoutingProfile } from "./types.js";

export const MODEL_ROUTING_POLICY_VERSION = "model-routing-v4";

export const TIER_CANDIDATES: Record<ResolvedTier, readonly string[]> = {
  fast: ["gemini-3.8-flash-high", "claude-opus-4-6-thinking"],
  reasoning: ["gemini-3.8-flash-high", "claude-opus-4-6-thinking"],
  expert: ["claude-opus-4-6-thinking", "gemini-3.8-flash-high"],
};

export const AUTOMATIC_MODEL_IDS = [...new Set(Object.values(TIER_CANDIDATES).flat())];
export const MANUAL_ONLY_MODEL_IDS = ["claude-sonnet-4-6", "gpt-oss-120b-medium"];

export interface ModelSelection {
  model: string;
  candidate_index: number;
  fallback_used: boolean;
  fallback_reason?: "primary_unavailable" | "quota_fallback" | "model_selection_fallback";
  candidate_chain: string[];
}

export function isDisallowedGemini37Effort(model: string): boolean {
  return /^gemini-3\.7-flash-(?:low|medium)$/i.test(model.trim());
}

export function assertAllowedWorkerModel(model: string): void {
  if (isDisallowedGemini37Effort(model)) throw new Error("model_effort_not_allowed");
}

export function selectModel(tier: ResolvedTier, available: ReadonlySet<string>, startIndex = 0, trigger?: ModelSelection["fallback_reason"]): ModelSelection | undefined {
  const candidateChain = [...TIER_CANDIDATES[tier]];
  for (let index = startIndex; index < candidateChain.length; index += 1) {
    const model = candidateChain[index];
    if (!available.has(model)) continue;
    const fallbackUsed = index > 0;
    return {
      model,
      candidate_index: index,
      fallback_used: fallbackUsed,
      fallback_reason: fallbackUsed ? (trigger || "primary_unavailable") : undefined,
      candidate_chain: candidateChain,
    };
  }
  return undefined;
}

export interface ImplementationRoutingInput {
  title: string;
  objective: string;
  target_state: string;
  context?: string;
  allowed_paths: string[];
}

function routingText(input: ImplementationRoutingInput): string {
  return `${input.title} ${input.objective} ${input.target_state} ${input.context || ""}`.toLowerCase();
}

export function classifyImplementation(input: ImplementationRoutingInput): { profile: RoutingProfile; tier: ResolvedTier; risk: "low" | "medium" | "high"; reason_codes: string[] } {
  const text = routingText(input);
  const highRiskReasons = [
    [/\bsecurity\b|\bauth(?:entication|orization)?\b|\bpermission(?:s)?\b/, "security_boundary"],
    [/\bcrypto(?:graphy)?\b|\bsecret(?:s)?\b|\bcredential(?:s)?\b/, "sensitive_security"],
    [/\brace\b|\bconcurren(?:cy|t)\b|\bdeadlock\b|\bflaky\b|\bnondeterministic\b|hard.to.reproduce/, "concurrency_or_nondeterminism"],
    [/\bcorruption\b|\bdata.loss\b|\brollback\b/, "data_integrity"],
  ].filter(([pattern]) => (pattern as RegExp).test(text)).map(([, code]) => String(code));
  if (highRiskReasons.length) return { profile: "high_risk_debug", tier: "expert", risk: "high", reason_codes: highRiskReasons };

  const deepReasons = [
    [/\bmigration\b|\bschema\b|\bapi contract\b|\bpublic api\b/, "contract_or_migration"],
    [/\barchitecture\b|\barchitectural\b|\balgorithm\b/, "architecture_or_algorithm"],
    [/\bcross[- ](?:service|module)\b|\broot cause\b|\bresearch.to.code\b|\bpdf.to.code\b/, "cross_boundary_reasoning"],
  ].filter(([pattern]) => (pattern as RegExp).test(text)).map(([, code]) => String(code));
  if (input.allowed_paths.length >= 8) deepReasons.push("large_path_scope");
  if (deepReasons.length) return { profile: "deep_reasoning", tier: "reasoning", risk: "medium", reason_codes: deepReasons };
  return { profile: "workhorse", tier: "fast", risk: "low", reason_codes: ["bounded_routine_implementation"] };
}

export function routingDecision(profile: RoutingProfile, reasonCodes: string[], requestedTier: ModelTier, resolvedTier: ResolvedTier): RoutingDecision {
  return {
    policy_version: MODEL_ROUTING_POLICY_VERSION,
    profile,
    reason_codes: reasonCodes,
    requested_tier: requestedTier,
    resolved_tier: resolvedTier,
    candidate_chain: [...TIER_CANDIDATES[resolvedTier]],
  };
}

export function documentAutoTier(role: string, evidenceTokens: number, evidenceItems: number, sourceCount: number): { tier: "fast" | "reasoning"; profile: RoutingProfile; reason_codes: string[] } {
  if (["cross-source-align", "contradiction-map", "coverage-check"].includes(role)) {
    return { tier: "reasoning", profile: "deep_reasoning", reason_codes: ["cross_source_or_coverage_role"] };
  }
  if (role === "table-normalize" && sourceCount > 1) {
    return { tier: "reasoning", profile: "deep_reasoning", reason_codes: ["multi_source_table"] };
  }
  if (evidenceTokens > 4000 || evidenceItems > 12) {
    return { tier: "reasoning", profile: "deep_reasoning", reason_codes: ["large_evidence_bundle"] };
  }
  return { tier: "fast", profile: "workhorse", reason_codes: ["bounded_clerical_role"] };
}
