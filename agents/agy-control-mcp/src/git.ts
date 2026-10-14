import { spawn } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import { execCommand, resolveExecutable } from "./processUtils.js";

export interface ChangedPath {
  path: string;
  index_status: string;
  worktree_status: string;
}

const ALWAYS_FORBIDDEN = [
  /^\.git(?:\/|$)/i,
  /(^|\/)\.env(?:\.|$)/i,
  /(^|\/)\.ssh(?:\/|$)/i,
  /(^|\/)\.aws(?:\/|$)/i,
  /(^|\/)\.gnupg(?:\/|$)/i,
  /\.pem$/i,
  /\.pfx$/i,
  /\.p12$/i,
  /\.key$/i,
  /(^|\/)secrets?(?:[._-].*)?(?:\/|$)/i,
  /(^|\/)credentials?(?:[._-].*)?(?:\/|$)/i,
  /(^|\/)id_(?:rsa|ed25519|dsa|ecdsa)(?:\.pub)?$/i,
];

async function git(cwd: string, args: string[], timeout = 30000): Promise<string> {
  const { stdout } = await execCommand("git", args, { cwd, timeout });
  return stdout;
}

export async function repositoryRoot(input: string): Promise<string> {
  return (await git(input, ["rev-parse", "--show-toplevel"])).trim();
}

export async function currentHead(repoRoot: string): Promise<string> {
  return (await git(repoRoot, ["rev-parse", "HEAD"])).trim();
}

export async function assertNoTrackedChanges(repoRoot: string): Promise<void> {
  const status = await git(repoRoot, ["status", "--porcelain", "--untracked-files=no"]);
  if (status.trim()) throw new Error(`Repository has tracked changes; apply refused:\n${status}`);
}

export async function assertNoUntrackedFiles(repoRoot: string): Promise<void> {
  const status = await git(repoRoot, ["status", "--porcelain", "--untracked-files=all"]);
  const untracked = status.split(/\r?\n/).filter((line) => line.startsWith("?? "));
  if (untracked.length) throw new Error(`Repository has untracked files; snapshot mode is required:\n${untracked.join("\n")}`);
}

/** Create a private clone without changing the source repository's .git metadata. */
export async function createWorktree(repoRoot: string, worktreePath: string, expectedHead?: string): Promise<void> {
  await fs.mkdir(path.dirname(worktreePath), { recursive: true });
  await git(path.dirname(worktreePath), ["clone", "--no-local", "--no-hardlinks", "--no-checkout", repoRoot, worktreePath]);
  await git(worktreePath, ["checkout", "--detach", expectedHead || "HEAD"]);
}

export async function assertGitWorkspaceSafe(repoRoot: string): Promise<void> {
  const tracked = await git(repoRoot, ["ls-files", "-s", "-z"]);
  for (const record of tracked.split("\0").filter(Boolean)) {
    const tab = record.indexOf("\t");
    if (tab < 0) throw new Error("Git returned a malformed tracked-file record");
    const mode = record.slice(0, tab).split(/\s+/, 1)[0];
    const filePath = record.slice(tab + 1).replaceAll("\\", "/");
    if (mode === "120000") throw new Error(`Git workspace refuses tracked symlink: ${filePath}`);
    if (mode === "160000") throw new Error(`Git workspace refuses tracked submodule: ${filePath}`);
    if (ALWAYS_FORBIDDEN.some((rule) => rule.test(filePath))) throw new Error(`Git workspace refuses sensitive tracked path: ${filePath}`);
  }
}

export function normalizeScopePath(value: string, allowSensitive = false): string {
  const normalized = value.replaceAll("\\", "/").replace(/^\.\//, "").trim();
  if (/[\u0000-\u001f\u007f]/.test(normalized)) throw new Error(`Scope path contains control characters: ${value}`);
  if (!normalized || path.posix.isAbsolute(normalized) || /^[A-Za-z]:\//.test(normalized)) throw new Error(`Scope path must be a non-empty repository-relative path: ${value}`);
  if (normalized === "**" || normalized === "." || normalized.split("/").some((segment) => segment === ".." || segment === "." || !segment) || normalized !== path.posix.normalize(normalized)) throw new Error(`Repository-wide and parent scope paths are not allowed: ${value}`);
  if (!allowSensitive && ALWAYS_FORBIDDEN.some((rule) => rule.test(normalized))) throw new Error(`Sensitive scope path is not allowed: ${value}`);
  return normalized.replace(/\/$/, "");
}

export function normalizeScopePaths(paths: string[], allowSensitive = false): string[] {
  return [...new Set(paths.map((item) => normalizeScopePath(item, allowSensitive)))];
}

function decodePorcelainPath(value: string): string {
  if (value.startsWith('"') && value.endsWith('"')) {
    try { return JSON.parse(value) as string; } catch { return value.slice(1, -1); }
  }
  return value;
}

export function parseChangedPaths(status: string): ChangedPath[] {
  if (status.includes("\0")) {
    const records = status.split("\0");
    const changes: ChangedPath[] = [];
    for (let index = 0; index < records.length; index += 1) {
      const line = records[index];
      if (!line) continue;
      const indexStatus = line[0] || " ";
      const worktreeStatus = line[1] || " ";
      const firstPath = line.slice(3).replaceAll("\\", "/");
      const rename = /[RC]/.test(`${indexStatus}${worktreeStatus}`);
      if (rename && records[index + 1]) {
        const secondPath = records[index + 1].replaceAll("\\", "/");
        changes.push({ path: firstPath, index_status: indexStatus, worktree_status: worktreeStatus });
        changes.push({ path: secondPath, index_status: indexStatus, worktree_status: worktreeStatus });
        index += 1;
      } else {
        changes.push({ path: firstPath, index_status: indexStatus, worktree_status: worktreeStatus });
      }
    }
    return changes;
  }
  return status.split("\n").filter(Boolean).map((line) => {
    const indexStatus = line[0] || " ";
    const worktreeStatus = line[1] || " ";
    const raw = line.slice(3);
    const renameMatch = /^(.*) -> (.*)$/.exec(raw);
    const filePath = decodePorcelainPath(renameMatch ? renameMatch[2] : raw);
    return { path: filePath.replaceAll("\\", "/"), index_status: indexStatus, worktree_status: worktreeStatus };
  });
}

function decodeGitQuotedPath(value: string): string {
  if (!value.startsWith('"') || !value.endsWith('"')) return value;
  let decoded = "";
  for (let index = 1; index < value.length - 1; index += 1) {
    const character = value[index];
    if (character !== "\\") { decoded += character; continue; }
    const escaped = value[++index];
    if (escaped === undefined) throw new Error("Patch contains an unterminated quoted path");
    if (/^[0-7]$/.test(escaped)) {
      let octal = escaped;
      for (let count = 0; count < 2 && /^[0-7]$/.test(value[index + 1] || ""); count += 1) octal += value[++index];
      decoded += String.fromCharCode(Number.parseInt(octal, 8));
    } else decoded += ({ a: "\a", b: "\b", t: "\t", n: "\n", v: "\v", f: "\f", r: "\r", "\\": "\\", '"': '"' } as Record<string, string>)[escaped] ?? escaped;
  }
  return decoded;
}

function patchTokens(value: string): string[] {
  const tokens: string[] = [];
  let index = 0;
  while (index < value.length) {
    while (/\s/.test(value[index] || "")) index += 1;
    if (index >= value.length) break;
    if (value[index] === '"') {
      const start = index;
      index += 1;
      let escaped = false;
      while (index < value.length) {
        if (!escaped && value[index] === '"') { index += 1; break; }
        escaped = !escaped && value[index] === "\\";
        if (value[index] !== "\\") escaped = false;
        index += 1;
      }
      if (value[index - 1] !== '"') throw new Error("Patch contains an unterminated quoted path");
      tokens.push(decodeGitQuotedPath(value.slice(start, index)));
    } else {
      const start = index;
      while (index < value.length && !/\s/.test(value[index])) index += 1;
      tokens.push(value.slice(start, index));
    }
  }
  return tokens;
}

function normalizedPatchPath(value: string, prefix: "a/" | "b/" | ""): string | undefined {
  if (value === "/dev/null") return undefined;
  const pathValue = prefix && value.startsWith(prefix) ? value.slice(prefix.length) : value;
  if (!pathValue || /[\u0000-\u001f\u007f]/.test(pathValue) || pathValue.includes("\\") || path.posix.isAbsolute(pathValue) || /^[A-Za-z]:\//.test(pathValue) || path.posix.normalize(pathValue) !== pathValue || pathValue.split("/").some((segment) => segment === ".." || segment === "." || !segment) || ALWAYS_FORBIDDEN.some((pattern) => pattern.test(pathValue))) {
    throw new Error(`Patch path is unsafe: ${value}`);
  }
  return pathValue;
}

export function patchPaths(patchContent: string): string[] {
  const paths = new Set<string>();
  let blockCount = 0;
  let blockPaths = new Set<string>();
  let headerPaths: string[] = [];
  let inHeader = false;
  const finishBlock = () => {
    for (const filePath of headerPaths) if (!blockPaths.has(filePath)) throw new Error(`Patch header path does not match its diff header: ${filePath}`);
  };
  for (const line of patchContent.split(/\r?\n/)) {
    if (line.startsWith("diff --git ")) {
      if (blockCount) finishBlock();
      const tokens = patchTokens(line.slice("diff --git ".length));
      if (tokens.length !== 2 || !tokens[0].startsWith("a/") || !tokens[1].startsWith("b/")) throw new Error("Patch has malformed diff headers");
      const oldPath = normalizedPatchPath(tokens[0], "a/");
      const newPath = normalizedPatchPath(tokens[1], "b/");
      blockPaths = new Set([oldPath, newPath].filter((item): item is string => Boolean(item)));
      if (!blockPaths.size) throw new Error("Patch has no filesystem path");
      headerPaths = [];
      inHeader = true;
      for (const filePath of blockPaths) {
        if (paths.has(filePath)) throw new Error(`Patch contains a duplicate path: ${filePath}`);
        paths.add(filePath);
      }
      blockCount += 1;
      continue;
    }
    if (line.startsWith("@@")) { inHeader = false; continue; }
    if (inHeader && (line.startsWith("--- ") || line.startsWith("+++ "))) {
      const tokens = patchTokens(line.slice(4));
      if (tokens.length !== 1) throw new Error("Patch has malformed file headers");
      const prefix = tokens[0] === "/dev/null" ? "" : line.startsWith("--- ") ? "a/" : "b/";
      const filePath = normalizedPatchPath(tokens[0], prefix);
      if (filePath) headerPaths.push(filePath);
    }
  }
  if (blockCount) finishBlock();
  if (!blockCount || !paths.size) throw new Error("Patch has no safe filesystem paths");
  return [...paths];
}

async function assertSafePatchTargets(repoRoot: string, patchContent: string): Promise<string[]> {
  if (/^(?:new file mode|old mode|new mode) (?:120000|160000)$/m.test(patchContent)) throw new Error("Patch cannot create or modify symlinks or submodules");
  const paths = patchPaths(patchContent);
  for (const relativePath of paths) {
    let current = repoRoot;
    for (const segment of relativePath.split("/").slice(0, -1)) {
      current = path.join(current, segment);
      const stats = await fs.lstat(current).catch((error: NodeJS.ErrnoException) => {
        if (error.code === "ENOENT") return undefined;
        throw error;
      });
      if (stats && (!stats.isDirectory() || stats.isSymbolicLink())) throw new Error(`Patch target parent is unsafe: ${relativePath}`);
    }
    const target = await fs.lstat(path.join(repoRoot, ...relativePath.split("/"))).catch((error: NodeJS.ErrnoException) => {
      if (error.code === "ENOENT") return undefined;
      throw error;
    });
    if (target && (target.isSymbolicLink() || !target.isFile())) throw new Error(`Patch target is unsafe: ${relativePath}`);
  }
  return paths;
}

function globRegex(pattern: string): RegExp {
  let source = "^";
  for (let index = 0; index < pattern.length; index += 1) {
    const character = pattern[index];
    if (character === "*" && pattern[index + 1] === "*") {
      source += ".*";
      index += 1;
    } else if (character === "*") source += "[^/]*";
    else source += /[.+^${}()|[\]\\]/.test(character) ? `\\${character}` : character;
  }
  return new RegExp(`${source}$`, "i");
}

export function matchesScope(filePath: string, patterns: string[]): boolean {
  const value = filePath.replaceAll("\\", "/").replace(/^\.\//, "");
  for (const pattern of patterns) {
    const normalized = pattern.replaceAll("\\", "/").replace(/^\.\//, "").replace(/\/$/, "");
    if (!normalized) continue;
    if (normalized === value) return true;
    if (normalized.endsWith("/**")) {
      const base = normalized.slice(0, -3).replace(/\/$/, "");
      if (value === base || value.startsWith(`${base}/`)) return true;
      continue;
    }
    if (normalized.includes("*")) {
      if (globRegex(normalized).test(value)) return true;
    } else if (`${value}/`.startsWith(`${normalized}/`)) return true;
  }
  return false;
}

export interface ScopeResult {
  passed: boolean;
  changed_paths: string[];
  violations: Array<{ path: string; reason: string }>;
}

export async function checkFileScope(worktree: string, allowedPaths: string[], forbiddenPaths: string[]): Promise<ScopeResult> {
  const status = await git(worktree, ["status", "--porcelain=v1", "-z", "--untracked-files=all"]);
  const changedPaths = parseChangedPaths(status);
  const violations: ScopeResult["violations"] = [];
  for (const change of changedPaths) {
    if (!matchesScope(change.path, allowedPaths)) violations.push({ path: change.path, reason: "outside_allowed_paths" });
    if (matchesScope(change.path, forbiddenPaths) || ALWAYS_FORBIDDEN.some((pattern) => pattern.test(change.path))) {
      violations.push({ path: change.path, reason: "forbidden_path" });
    }
    try {
      const stats = await fs.lstat(path.resolve(worktree, change.path));
      if (stats.isSymbolicLink()) violations.push({ path: change.path, reason: "symlink" });
      else if (!stats.isFile()) violations.push({ path: change.path, reason: "non_regular_file" });
    } catch {
      // Deleted paths cannot be lstat'd.
    }
  }
  return { passed: !violations.length, changed_paths: changedPaths.map((change) => change.path), violations };
}

export async function generatePatch(worktree: string, patchPath: string, maxPatchBytes = 8 * 1024 * 1024): Promise<{ stat: string; sha256: string }> {
  await git(worktree, ["add", "--intent-to-add", "--all"]);
  const diff = await git(worktree, ["diff", "--binary", "--no-ext-diff", "HEAD"], 120000);
  if (Buffer.byteLength(diff, "utf8") > maxPatchBytes) throw new Error(`Generated patch exceeds the configured size limit of ${maxPatchBytes} bytes`);
  await fs.writeFile(patchPath, diff, "utf8");
  const stat = await git(worktree, ["diff", "--stat", "HEAD"]).catch(() => "");
  const { createHash } = await import("node:crypto");
  return { stat: stat.trim() || "(empty diff)", sha256: createHash("sha256").update(diff).digest("hex") };
}

export async function worktreeFingerprint(worktree: string): Promise<string> {
  const diff = await git(worktree, ["diff", "--binary", "--no-ext-diff", "HEAD"], 120000);
  const status = await git(worktree, ["status", "--porcelain", "--untracked-files=all"]);
  const { createHash } = await import("node:crypto");
  return createHash("sha256").update(`${diff}\u0000${status}`).digest("hex");
}

function sanitizedTestEnvironment(): NodeJS.ProcessEnv {
  const env: NodeJS.ProcessEnv = {};
  const allowed = ["ComSpec", "HOMEDRIVE", "HOMEPATH", "LOCALAPPDATA", "APPDATA", "PATH", "PATHEXT", "ProgramData", "SystemDrive", "SystemRoot", "TEMP", "TMP", "USERPROFILE", "WINDIR", "npm_config_cache"];
  for (const key of allowed) if (process.env[key]) env[key] = process.env[key];
  env.AGY_WORKER = "1";
  env.CI = "1";
  return env;
}

export async function runTestCommand(command: string, cwd: string, timeoutSeconds: number, maxOutputBytes: number): Promise<{ passed: boolean; output: string; exitCode: number | null }> {
  const windows = process.platform.startsWith("win");
  const sandbox = windows ? undefined : await resolveExecutable("bwrap").catch(() => undefined);
  if (!windows && !sandbox) return { passed: false, output: "Delegated tests require bubblewrap on Linux", exitCode: null };
  const shell = windows ? command : sandbox!;
  const args = windows ? [] : ["--die-with-parent", "--unshare-all", "--new-session", "--ro-bind", "/", "/", "--bind", cwd, cwd, "--chdir", cwd, "/bin/sh", "-c", command];
  const spawnOptions = { cwd, windowsHide: true, shell: windows, detached: !windows, env: sanitizedTestEnvironment() };
  return await new Promise((resolve) => {
    const child = spawn(shell, args, spawnOptions);
    let output = "";
    let timedOut = false;
    let outputExceeded = false;
    let escalation: NodeJS.Timeout | undefined;
    const killTree = () => {
      if (process.platform.startsWith("win") && child.pid) void spawn("taskkill.exe", ["/PID", String(child.pid), "/T", "/F"], { windowsHide: true });
      else if (child.pid) {
        try { process.kill(-child.pid, "SIGTERM"); } catch { child.kill("SIGTERM"); }
      }
    };
    const timer = setTimeout(() => {
      timedOut = true;
      killTree();
      escalation = setTimeout(() => {
        if (process.platform.startsWith("win") && child.pid) void spawn("taskkill.exe", ["/PID", String(child.pid), "/T", "/F"], { windowsHide: true });
        else if (child.pid) {
          try { process.kill(-child.pid, "SIGKILL"); } catch { child.kill("SIGKILL"); }
        }
      }, 5_000);
      escalation.unref();
    }, timeoutSeconds * 1000);
    const append = (chunk: Buffer) => {
      if (outputExceeded) return;
      if (Buffer.byteLength(output, "utf8") + chunk.byteLength > maxOutputBytes) {
        outputExceeded = true;
        killTree();
        return;
      }
      output += chunk.toString("utf8");
    };
    child.stdout?.on("data", append);
    child.stderr?.on("data", append);
    child.on("error", (error) => {
      clearTimeout(timer);
      if (escalation) clearTimeout(escalation);
      resolve({ passed: false, output: error.message, exitCode: null });
    });
    child.on("close", (code) => {
      clearTimeout(timer);
      if (escalation) clearTimeout(escalation);
      resolve({ passed: code === 0 && !timedOut && !outputExceeded, output, exitCode: timedOut || outputExceeded ? null : code });
    });
  });
}

export async function assertNoUntrackedCollisions(repoRoot: string, changedPaths: string[]): Promise<void> {
  for (const relativePath of changedPaths) {
    const status = await git(repoRoot, ["ls-files", "--others", "--exclude-standard", "--", relativePath]);
    if (status.trim()) throw new Error(`Untracked file would collide with patch: ${relativePath}`);
  }
}

async function gitWithInput(cwd: string, args: string[], input: string, timeout = 30000): Promise<void> {
  await new Promise<void>((resolve, reject) => {
    const child = spawn("git", args, { cwd, windowsHide: true });
    let output = "";
    let settled = false;
    const finish = (error?: Error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (error) reject(error); else resolve();
    };
    const timer = setTimeout(() => {
      if (process.platform.startsWith("win") && child.pid) void spawn("taskkill.exe", ["/PID", String(child.pid), "/T", "/F"], { windowsHide: true });
      else child.kill("SIGTERM");
      finish(new Error(`Git command timed out: git ${args.join(" ")}`));
    }, timeout);
    const append = (chunk: Buffer) => { output = `${output}${chunk.toString("utf8")}`.slice(-64000); };
    child.stdout?.on("data", append);
    child.stderr?.on("data", append);
    child.stdin?.on("error", (error) => finish(error));
    child.on("error", (error) => finish(error));
    child.on("close", (code) => finish(code === 0 ? undefined : new Error(`Git command failed (${code}): git ${args.join(" ")}\n${output}`)));
    child.stdin?.end(input);
  });
}

export async function applyPatch(repoRoot: string, patchContent: string, expectedHead: string): Promise<void> {
  await assertSafePatchTargets(repoRoot, patchContent);
  await assertNoTrackedChanges(repoRoot);
  if (await currentHead(repoRoot) !== expectedHead) throw new Error("Repository HEAD changed before patch validation");
  await gitWithInput(repoRoot, ["apply", "--check", "--whitespace=nowarn", "-"], patchContent);
  await assertNoTrackedChanges(repoRoot);
  if (await currentHead(repoRoot) !== expectedHead) throw new Error("Repository HEAD changed before patch application");
  await gitWithInput(repoRoot, ["apply", "--whitespace=nowarn", "-"], patchContent);
}

export async function applySnapshotPatch(workspaceRoot: string, patchContent: string): Promise<void> {
  await assertSafePatchTargets(workspaceRoot, patchContent);
  await gitWithInput(workspaceRoot, ["apply", "--no-index", "--check", "--whitespace=nowarn", "-"], patchContent);
  await gitWithInput(workspaceRoot, ["apply", "--no-index", "--whitespace=nowarn", "-"], patchContent);
}
