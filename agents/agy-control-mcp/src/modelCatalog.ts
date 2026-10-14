import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { TIER_CANDIDATES } from "./modelPolicy.js";
import type { ResolvedTier } from "./types.js";

const execFileAsync = promisify(execFile);

export interface ModelInfo {
  id: string;
  tier: ResolvedTier;
}

export { TIER_CANDIDATES };

export function classifyModel(id: string): ResolvedTier {
  if (id.includes("opus")) return "expert";
  if (id.includes("gemini-3.1-pro") || id.includes("sonnet")) return "reasoning";
  return "fast";
}

export async function discoverModels(command = "agy", configuredIds: string[] = []): Promise<ModelInfo[]> {
  if (configuredIds.length) return [...new Set(configuredIds)].map((id) => ({ id, tier: classifyModel(id) }));
  try {
    const { stdout } = await execFileAsync(command, ["models"], { timeout: 15000, maxBuffer: 1024 * 1024 });
    const ids = [...new Set(
      stdout
        .split(/\r?\n/)
        .map((line) => line.trim().split(/\s+/)[0] || "")
        .filter((id) => /^[a-z0-9][a-z0-9._-]*$/.test(id) && id !== "Fetching")
    )];
    return ids.map((id) => ({ id, tier: classifyModel(id) }));
  } catch { return []; }
}
