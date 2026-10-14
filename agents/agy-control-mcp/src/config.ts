import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import type { ResolvedTier } from "./types.js";

function positiveInteger(name: string, fallback: number): number {
  const value = Number(process.env[name]);
  return Number.isFinite(value) && value > 0 ? Math.floor(value) : fallback;
}

function xdgDirectory(variable: "XDG_STATE_HOME" | "XDG_DATA_HOME", fallback: string): string {
  return process.env[variable] || path.join(os.homedir(), ".local", fallback);
}
const bundledStudyHerdHome = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "resources", "study-herd");

export interface ControlConfig {
  root: string;
  lockRoot: string;
  client: string;
  studyHerdHome: string;
  agyCommand: string;
  live: boolean;
  defaultTimeoutSeconds: number;
  maxTimeoutSeconds: number;
  budgets: Record<ResolvedTier, number>;
  contextBudgets: Record<ResolvedTier, number>;
  concurrency: Record<ResolvedTier, number>;
  globalConcurrency: number;
  maxPatchBytes: number;
  maxLogBytes: number;
  artifactRetentionDays: number;
  modelIds: string[];
  orchestrationMaxTasks: number;
  orchestrationMaxParallel: number;
  orchestrationMaxDepth: number;
  orchestrationMaxAttempts: number;
}

// Each commander client (Claude Code, Codex, OpenCode, Hermes, ...) gets its own state root so persisted
// workflows and runs are never recovered by the wrong process. Capacity locks are shared across clients
// because they throttle the single AGY backend that all of them drive.
export function clientName(value: string | undefined): string {
  const normalized = (value || "").trim().toLowerCase();
  return /^[a-z0-9][a-z0-9-]{0,31}$/.test(normalized) ? normalized : "default";
}

export function loadConfig(overrides: Partial<ControlConfig> = {}): ControlConfig {
  const stateHome = xdgDirectory("XDG_STATE_HOME", "state");
  const client = overrides.client || clientName(process.env.AGY_CONTROL_CLIENT);
  const sharedBase = path.join(stateHome, "agy-control-mcp");
  return {
    client,
    // "codex" keeps the original unsuffixed root, where Codex's existing workflows and documents already live.
    root: overrides.root || process.env.AGY_CONTROL_ROOT || (client === "default" || client === "codex" ? sharedBase : `${sharedBase}-${client}`),
    // An explicit root (tests, embedding) keeps its own locks so it never contends with the live AGY backend.
    lockRoot: overrides.lockRoot || process.env.AGY_CONTROL_LOCK_ROOT || (overrides.root ? path.join(overrides.root, "locks") : path.join(sharedBase, "locks")),
    studyHerdHome: overrides.studyHerdHome || process.env.AGY_STUDY_HERD_HOME || bundledStudyHerdHome,
    agyCommand: overrides.agyCommand || process.env.AGY_BIN || "agy",
    live: overrides.live ?? /^(1|true|yes)$/i.test(process.env.AGY_CONTROL_LIVE || ""),
    defaultTimeoutSeconds: positiveInteger("AGY_CONTROL_TIMEOUT", 900),
    maxTimeoutSeconds: positiveInteger("AGY_CONTROL_MAX_TIMEOUT", 3600),
    budgets:
      overrides.budgets || {
        fast: positiveInteger("AGY_CONTROL_FAST_BUDGET", 14000),
        reasoning: positiveInteger("AGY_CONTROL_REASONING_BUDGET", 24000),
        expert: positiveInteger("AGY_CONTROL_EXPERT_BUDGET", 36000)
      },
    contextBudgets:
      overrides.contextBudgets ||
      { fast: 3600, reasoning: 9600, expert: 14400 },
    concurrency: overrides.concurrency || { fast: 3, reasoning: 1, expert: 1 },
    globalConcurrency: overrides.globalConcurrency ?? positiveInteger("AGY_CONTROL_GLOBAL_CONCURRENCY", 4),
    maxPatchBytes: overrides.maxPatchBytes ?? positiveInteger("AGY_CONTROL_MAX_PATCH_BYTES", 2 * 1024 * 1024),
    maxLogBytes: overrides.maxLogBytes ?? positiveInteger("AGY_CONTROL_MAX_LOG_BYTES", 256 * 1024),
    artifactRetentionDays: overrides.artifactRetentionDays ?? positiveInteger("AGY_CONTROL_ARTIFACT_RETENTION_DAYS", 30),
    modelIds: overrides.modelIds ?? [...new Set((process.env.AGY_CONTROL_MODELS || "").split(",").map((item) => item.trim()).filter((item) => /^[a-z0-9][a-z0-9._-]*$/i.test(item)))],
    orchestrationMaxTasks: overrides.orchestrationMaxTasks ?? positiveInteger("AGY_CONTROL_MAX_WORKFLOW_TASKS", 32),
    orchestrationMaxParallel: overrides.orchestrationMaxParallel ?? positiveInteger("AGY_CONTROL_MAX_WORKFLOW_PARALLEL", 4),
    orchestrationMaxDepth: overrides.orchestrationMaxDepth ?? positiveInteger("AGY_CONTROL_MAX_WORKFLOW_DEPTH", 3),
    orchestrationMaxAttempts: overrides.orchestrationMaxAttempts ?? positiveInteger("AGY_CONTROL_MAX_WORKFLOW_ATTEMPTS", 3)
  };
}
