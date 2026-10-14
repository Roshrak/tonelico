import { execFileSync } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
const packageJson = JSON.parse(await fs.readFile(path.join(root, "package.json"), "utf8"));
let commit = "unknown";
let dirty = false;
const gitOptions = { cwd: root, encoding: "utf8", windowsHide: true, stdio: ["ignore", "pipe", "ignore"] };
try { commit = execFileSync("git", ["rev-parse", "HEAD"], gitOptions).trim(); } catch { /* Source archives and initial repositories may not have a HEAD. */ }
try { dirty = Boolean(execFileSync("git", ["status", "--porcelain"], gitOptions).trim()); } catch { /* Source archives may not have Git metadata. */ }
await fs.writeFile(path.join(root, "dist", "build-info.json"), `${JSON.stringify({ version: packageJson.version, commit, built_at: new Date().toISOString(), dirty }, null, 2)}\n`, "utf8");
