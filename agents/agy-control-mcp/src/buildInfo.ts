import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

export interface BuildInfo {
  version: string;
  commit: string;
  built_at: string;
  dirty: boolean;
}

const fallback: BuildInfo = {
  version: "0.3.0",
  commit: process.env.AGY_CONTROL_BUILD_COMMIT || "unknown",
  built_at: process.env.AGY_CONTROL_BUILD_TIMESTAMP || "unknown",
  dirty: process.env.AGY_CONTROL_BUILD_DIRTY === "1",
};

export async function readBuildInfo(): Promise<BuildInfo> {
  const filename = path.join(path.dirname(fileURLToPath(import.meta.url)), "build-info.json");
  try {
    const parsed = JSON.parse(await fs.readFile(filename, "utf8")) as Partial<BuildInfo>;
    if (typeof parsed.version === "string" && typeof parsed.commit === "string" && typeof parsed.built_at === "string" && typeof parsed.dirty === "boolean") return parsed as BuildInfo;
  } catch { /* Test builds and direct source execution use the explicit fallback. */ }
  return fallback;
}
