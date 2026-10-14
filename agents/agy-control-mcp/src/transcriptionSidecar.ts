import { spawn, type ChildProcess } from "node:child_process";
import fs from "node:fs/promises";
import { existsSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { StringDecoder } from "node:string_decoder";
import type { ParsedDocument, ParsedElement } from "./documentTypes.js";

export const TRANSCRIPTION_EXTENSIONS = new Set([".aac", ".caf", ".flac", ".m4a", ".mkv", ".mov", ".mp3", ".mp4", ".ogg", ".opus", ".wav", ".webm", ".wma"]);
export const SIDECAR_PROTOCOL_VERSION = 1;
export class TranscriptionCancelledError extends Error {
  constructor(message = "Transcription was cancelled") {
    super(message);
    this.name = "TranscriptionCancelledError";
  }
}
const SHUTDOWN_GRACE_MS = 10_000;
const CANCEL_FALLBACK_MS = 15_000;

interface SegmentPayload { start_ms?: unknown; end_ms?: unknown; text?: unknown }

interface PendingRequest {
  id: string;
  kind: "transcribe" | "health";
  filePath?: string;
  cancelToken?: string;
  cancelled: boolean;
  timer: NodeJS.Timeout | undefined;
  cancelFallbackTimer: NodeJS.Timeout | undefined;
  resolve: (value: ParsedDocument | Record<string, unknown>) => void;
  reject: (error: Error) => void;
}

export interface TranscriptionAvailability {
  enabled: boolean;
  protocol_version: 1;
  application_home: string;
  python_path: string;
  model_directory: string;
  model_files_complete: boolean;
  reason?: string;
}

export interface TranscriptionSidecarOptions {
  applicationHome?: string;
  pythonPath?: string;
  modelDirectory?: string;
  timeoutSeconds?: number;
  /** Test seam: override the spawned executable (defaults to the configured Python interpreter). */
  spawnCommand?: string;
  /** Test seam: override the spawned argument list (defaults to ["-m", "phowhisper_app.sidecar"]). */
  spawnArgs?: string[];
  sharedLockRoot?: string;
}

function killProcessTree(pid: number): void {
  if (!process.platform.startsWith("win")) {
    try { process.kill(pid); } catch { /* already gone */ }
    return;
  }
  spawn("taskkill.exe", ["/PID", String(pid), "/T", "/F"], { windowsHide: true, stdio: "ignore" }).on("error", () => undefined);
}

/**
 * Persistent PhoWhisper sidecar manager.
 *
 * The Python worker is spawned once, health-checked (protocol + model revision) before the
 * first job, and reused across every transcription. A serial queue keeps recognition
 * single-flight. Crashes or invalid NDJSON fail the active jobs, clear pending state, and
 * allow exactly one sidecar restart at a later job. Cancellation sends the JSONL cancel
 * message first and only escalates to a process-tree kill as a fallback.
 */
export class PhoWhisperTranscriptionSidecar {
  private readonly applicationHome: string;
  private readonly configured: boolean;
  private readonly pythonPath: string;
  private readonly modelDirectory: string;
  private readonly jobTimeoutMs: number;
  private readonly spawnCommand: string;
  private readonly spawnArgs: string[];
  private readonly sharedLockRoot: string;
  private queue: Promise<unknown> = Promise.resolve();
  private activeTranscriptions = 0;
  private child: ChildProcess | undefined;
  private childReady = false;
  private spawnedOnce = false;
  private restartsUsed = 0;
  private pending = new Map<string, PendingRequest>();
  private stdoutBuffer = "";
  private stdoutDecoder = new StringDecoder("utf8");
  private stderrTail = "";
  private shuttingDown = false;
  private startupWaiter: { resolve: () => void; fail: (error: Error) => void } | undefined;

  constructor(options: TranscriptionSidecarOptions = {}) {
    // No machine-specific default: transcription is only enabled when PHOWHISPER_APP_HOME (or applicationHome) points at a real install.
    const configuredHome = options.applicationHome || process.env.PHOWHISPER_APP_HOME || "";
    this.applicationHome = configuredHome ? path.resolve(configuredHome) : "";
    this.configured = Boolean(configuredHome) && existsSync(this.applicationHome);
    const venvPython = process.platform === "win32" ? path.join(".venv", "Scripts", "python.exe") : path.join(".venv", "bin", "python");
    this.pythonPath = path.resolve(options.pythonPath || process.env.PHOWHISPER_PYTHON || path.join(this.applicationHome || ".", venvPython));
    this.modelDirectory = path.resolve(options.modelDirectory || process.env.PHOWHISPER_MODEL_DIR || path.join(this.applicationHome, "data", "models", "PhoWhisper-large-ct2"));
    this.jobTimeoutMs = Math.max(1, options.timeoutSeconds ?? Number(process.env.AGY_TRANSCRIPTION_TIMEOUT_SECONDS || 3600)) * 1000;
    this.spawnCommand = options.spawnCommand || this.pythonPath;
    this.spawnArgs = options.spawnArgs || ["-m", "phowhisper_app.sidecar"];
    // The GPU is one machine-wide resource, so the lease lives in the shared lock root every client uses.
    this.sharedLockRoot = path.resolve(options.sharedLockRoot || process.env.AGY_CONTROL_LOCK_ROOT || path.join(process.env.XDG_STATE_HOME || path.join(os.homedir(), ".local", "state"), "agy-control-mcp", "locks"));
  }

  supports(filePath: string): boolean {
    return TRANSCRIPTION_EXTENSIONS.has(path.extname(filePath).toLowerCase());
  }

  async availability(): Promise<TranscriptionAvailability> {
    const required = ["config.json", "model.bin", "preprocessor_config.json", "tokenizer.json"];
    const complete = await Promise.all(required.map((file) => fs.stat(path.join(this.modelDirectory, file)).then(() => true).catch(() => false)));
    return {
      enabled: this.configured, protocol_version: SIDECAR_PROTOCOL_VERSION, application_home: this.applicationHome,
      python_path: this.pythonPath, model_directory: this.modelDirectory,
      model_files_complete: complete.every(Boolean),
      ...(this.configured ? {} : { reason: "PhoWhisper is not configured; set PHOWHISPER_APP_HOME to an installed phowhisper_app directory to enable audio/video transcription." }),
    };
  }

  async transcribe(filePath: string, signal?: AbortSignal): Promise<ParsedDocument> {
    const previous = this.queue;
    let releaseQueue: () => void = () => undefined;
    this.queue = new Promise<void>((resolve) => { releaseQueue = resolve; });
    await previous.catch(() => undefined);
    try {
      if (this.shuttingDown) throw new Error("PhoWhisper sidecar is shutting down");
      if (signal?.aborted) throw new TranscriptionCancelledError("Transcription was cancelled before it started");
      this.activeTranscriptions += 1;
      const releaseGpu = await this.acquireSharedGpuLease(signal);
      try { return await this.runTranscription(filePath, signal); }
      finally { await releaseGpu(); }
    } finally {
      this.activeTranscriptions = Math.max(0, this.activeTranscriptions - 1);
      releaseQueue();
    }
  }

  activeCount(): number { return this.activeTranscriptions; }

  private async acquireSharedGpuLease(signal?: AbortSignal): Promise<() => Promise<void>> {
    const root = path.join(this.sharedLockRoot, "gpu-transcription", "0");
    const deadline = Date.now() + Math.min(this.jobTimeoutMs, 60_000);
    await fs.mkdir(path.dirname(root), { recursive: true });
    while (Date.now() < deadline) {
      if (signal?.aborted) throw new TranscriptionCancelledError();
      try {
        await fs.mkdir(root);
        await fs.writeFile(path.join(root, "owner.json"), JSON.stringify({ pid: process.pid, created_at: new Date().toISOString() }), "utf8");
        return async () => { await fs.rm(root, { recursive: true, force: true }); };
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
        const owner: { pid?: number; created_at?: string } = await fs.readFile(path.join(root, "owner.json"), "utf8").then((text) => JSON.parse(text) as { pid?: number; created_at?: string }).catch(() => ({} as { pid?: number; created_at?: string }));
        const age = owner.created_at ? Date.now() - Date.parse(owner.created_at) : Number.POSITIVE_INFINITY;
        let alive = false;
        if (typeof owner.pid === "number" && owner.pid > 0) {
          try { process.kill(owner.pid, 0); alive = true; } catch { alive = false; }
        }
        if (!alive || age > this.jobTimeoutMs + SHUTDOWN_GRACE_MS) await fs.rm(root, { recursive: true, force: true }).catch(() => undefined);
        await new Promise((resolve) => setTimeout(resolve, 100));
      }
    }
    throw new Error("Timed out waiting for the shared PhoWhisper GPU lease");
  }

  async shutdown(): Promise<void> {
    if (this.shuttingDown) return;
    this.shuttingDown = true;
    const child = this.child;
    if (!child || child.pid === undefined) return;
    for (const pending of [...this.pending.values()]) this.failPending(pending, new Error("PhoWhisper sidecar shut down before the transcription finished"));
    try { child.stdin?.write(`${JSON.stringify({ id: `shutdown-${Date.now()}`, type: "shutdown" })}\n`); }
    catch { /* fall through to the forced kill below */ }
    const exitedCleanly = await new Promise<boolean>((resolve) => {
      if (child.exitCode !== null) return resolve(true);
      const timer = setTimeout(() => resolve(false), SHUTDOWN_GRACE_MS);
      child.once("close", () => { clearTimeout(timer); resolve(true); });
    });
    if (!exitedCleanly) killProcessTree(child.pid);
    this.detachChild();
  }

  private detachChild(): void {
    this.child?.removeAllListeners();
    this.child = undefined;
    this.childReady = false;
    this.stdoutBuffer = "";
  }

  /** Spawn the sidecar (or restart it exactly once after a crash) and verify its health before any job. */
  private async ensureProcess(): Promise<ChildProcess> {
    if (this.shuttingDown) throw new Error("PhoWhisper sidecar is shutting down");
    if (this.child && this.childReady) return this.child;
    if (this.spawnedOnce) {
      if (this.restartLimitExhausted()) throw new Error("PhoWhisper sidecar crashed and exhausted its single allowed restart; restart the MCP server to transcribe again");
      this.restartsUsed += 1;
    }
    this.spawnedOnce = true;
    this.detachChild();
    for (const pending of [...this.pending.values()]) this.failPending(pending, new Error("PhoWhisper sidecar restarted before an earlier job finished"));
    const child = spawn(this.spawnCommand, this.spawnArgs, {
      cwd: this.applicationHome, windowsHide: true,
      env: {
        ...process.env, PYTHONIOENCODING: "utf-8", PYTHONPATH: path.join(this.applicationHome, "src"),
        PHOWHISPER_APP_HOME: this.applicationHome, PHOWHISPER_MODEL_DIR: this.modelDirectory,
      },
    });
    this.stderrTail = "";
    let startupError: Error | undefined;
    child.stderr?.on("data", (chunk: Buffer) => { this.stderrTail = `${this.stderrTail}${chunk.toString("utf8")}`.slice(-4000); });
    child.on("error", (error) => {
      startupError ||= error instanceof Error ? error : new Error(String(error));
      this.failActiveJobs(new Error(`PhoWhisper sidecar crashed: ${startupError.message}`));
    });
    // Single persistent stdout line dispatcher for the whole child lifetime.
    child.stdout?.on("data", (chunk: Buffer) => this.consumeStdout(chunk));
    await new Promise<void>((resolve, reject) => {
      const failStartup = (error: Error): void => {
        clearTimeout(timer);
        this.startupWaiter = undefined;
        reject(error);
      };
      const timer = setTimeout(() => failStartup(new Error(`PhoWhisper sidecar did not become ready: ${this.stderrTail.slice(-500) || "no diagnostics"}`)), 60_000);
      this.startupWaiter = {
        resolve: () => { clearTimeout(timer); this.startupWaiter = undefined; resolve(); },
        fail: failStartup,
      };
      child.once("close", () => failStartup(new Error(`PhoWhisper sidecar exited during startup: ${this.stderrTail.slice(-500) || "no diagnostics"}`)));
    }).finally(() => {
      child.removeAllListeners("close");
      child.on("close", () => this.failActiveJobs(new Error(`PhoWhisper sidecar crashed unexpectedly: ${this.stderrTail.slice(-500)}`)));
    });
    if (startupError) throw startupError;
    this.child = child;
    this.childReady = true;
    await this.healthCheck();
    return child;
  }

  private consumeStdout(chunk: Buffer): void {
    this.stdoutBuffer += this.stdoutDecoder.write(chunk);
    let newline = this.stdoutBuffer.indexOf("\n");
    while (newline >= 0) {
      const line = this.stdoutBuffer.slice(0, newline).trim();
      this.stdoutBuffer = this.stdoutBuffer.slice(newline + 1);
      newline = this.stdoutBuffer.indexOf("\n");
      if (!line) continue;
      if (line.includes('"event":"ready"')) {
        try {
          const event = JSON.parse(line) as Record<string, unknown>;
          if (Number(event.protocol_version) !== SIDECAR_PROTOCOL_VERSION) {
            this.startupWaiter?.fail(new Error(`Unsupported PhoWhisper sidecar protocol ${String(event.protocol_version)}`));
            return;
          }
          this.startupWaiter?.resolve();
          continue;
        } catch { /* fall through to normal dispatch */ }
      }
      this.dispatchLine(line);
    }
  }

  private restartLimitExhausted(): boolean {
    return this.restartsUsed >= 1;
  }

  private async healthCheck(): Promise<void> {
    const child = this.child!;
    const requestId = `health-${Date.now()}`;
    const report = await new Promise<Record<string, unknown>>((resolve, reject) => {
      const pending: PendingRequest = {
        id: requestId, kind: "health", cancelled: false, timer: undefined, cancelFallbackTimer: undefined,
        resolve: (value) => resolve(value as Record<string, unknown>),
        reject,
      };
      pending.timer = setTimeout(() => this.failPending(pending, new Error("PhoWhisper health check timed out")), 30_000);
      this.pending.set(requestId, pending);
      try { child.stdin?.write(`${JSON.stringify({ id: requestId, type: "health" })}\n`); }
      catch (error) { this.failPending(pending, new Error(`PhoWhisper health check failed to send: ${error instanceof Error ? error.message : String(error)}`)); }
    });
    if (Number(report.protocol_version) !== SIDECAR_PROTOCOL_VERSION) throw new Error(`Unsupported PhoWhisper sidecar protocol ${String(report.protocol_version)}`);
    if (report.model_files_complete !== true) throw new Error("PhoWhisper model files are incomplete; automatic model download is disabled");
  }

  /** Fail every in-flight job after a crash or invalid NDJSON so pending state never leaks. */
  private failActiveJobs(error: Error): void {
    this.childReady = false;
    for (const pending of [...this.pending.values()]) this.failPending(pending, error);
  }

  private failPending(pending: PendingRequest, error: Error): void {
    clearTimeout(pending.timer);
    clearTimeout(pending.cancelFallbackTimer);
    this.pending.delete(pending.id);
    pending.reject(error);
  }

  private dispatchLine(line: string): void {
    let event: Record<string, unknown>;
    try { event = JSON.parse(line) as Record<string, unknown>; }
    catch (error) {
      this.failActiveJobs(new Error(`Invalid sidecar NDJSON: ${error instanceof Error ? error.message : String(error)}`));
      return;
    }
    const id = event.id === undefined || event.id === null ? "" : String(event.id);
    if (["ready", "progress", "status"].includes(String(event.event))) return;
    const pending = this.pending.get(id);
    if (!pending) return;
    if (event.event === "accepted") {
      pending.cancelToken = typeof event.cancel_token === "string" ? event.cancel_token : undefined;
      return;
    }
    if (event.event === "error") {
      const status = String(event.status || "error");
      clearTimeout(pending.timer);
      clearTimeout(pending.cancelFallbackTimer);
      this.pending.delete(pending.id);
      if (pending.cancelled || status === "cancelled") pending.reject(new TranscriptionCancelledError(`PhoWhisper ${status}: ${String(event.error || "unknown error")}`));
      else pending.reject(new Error(`PhoWhisper ${status}: ${String(event.error || "unknown error")}`));
      return;
    }
    if (event.event === "result") {
      if (event.ok !== true) {
        this.failPending(pending, new Error(`PhoWhisper result failed: ${String(event.error || "unknown error")}`));
        return;
      }
      if (pending.kind === "health") {
        clearTimeout(pending.timer);
        this.pending.delete(pending.id);
        pending.resolve(event);
        return;
      }
      if (event.model_files_complete === false) {
        this.failPending(pending, new Error("PhoWhisper model files are incomplete; automatic model download is disabled"));
        return;
      }
      const elements: ParsedElement[] = (Array.isArray(event.segments) ? event.segments as SegmentPayload[] : []).map((segment, index): ParsedElement => ({
        ordinal: index + 1, element_type: "transcript", text: String(segment.text || "").trim(),
        start_ms: Number(segment.start_ms || 0), end_ms: Number(segment.end_ms || 0), confidence: "medium",
      })).filter((segment) => segment.text.length > 0);
      clearTimeout(pending.timer);
      clearTimeout(pending.cancelFallbackTimer);
      this.pending.delete(pending.id);
      pending.resolve({
        parser_version: "phowhisper-sidecar-v1", extraction_method: "phowhisper-jsonl",
        elements, warnings: [],
      } satisfies ParsedDocument);
    }
  }

  private async runTranscription(filePath: string, signal?: AbortSignal): Promise<ParsedDocument> {
    const availability = await this.availability();
    if (!availability.enabled) throw new Error(availability.reason || "PhoWhisper sidecar is not configured");
    if (!(await fs.stat(filePath).then((stat) => stat.isFile()).catch(() => false))) throw new Error(`Audio/video source does not exist: ${filePath}`);
    if (!availability.model_files_complete) throw new Error("PhoWhisper model files are incomplete; automatic model download is disabled");
    const child = await this.ensureProcess();
    // The abort may have fired while the persistent process was starting up.
    if (signal?.aborted) throw new TranscriptionCancelledError();
    const requestId = `transcribe-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    return await new Promise<ParsedDocument>((resolve, reject) => {
      const pending: PendingRequest = {
        id: requestId, kind: "transcribe", filePath, cancelled: false, timer: undefined, cancelFallbackTimer: undefined,
        resolve: (value) => resolve(value as ParsedDocument),
        reject,
      };
      pending.timer = setTimeout(() => this.failPending(pending, new Error(`PhoWhisper sidecar exceeded ${Math.round(this.jobTimeoutMs / 1000)} seconds`)), this.jobTimeoutMs);
      const onAbort = (): void => {
        pending.cancelled = true;
        // Protocol-first cancel: ask the sidecar to stop recognition gracefully.
        try { child.stdin?.write(`${JSON.stringify({ id: `${requestId}-cancel`, type: "cancel", cancel_token: pending.cancelToken })}\n`); }
        catch { /* fall through to the forced kill below */ }
        pending.cancelFallbackTimer = setTimeout(() => {
          this.failPending(pending, new TranscriptionCancelledError());
          // Process-tree kill is only the fallback when the protocol cancel did not land.
          if (child.pid !== undefined) killProcessTree(child.pid);
        }, CANCEL_FALLBACK_MS);
      };
      signal?.addEventListener("abort", onAbort, { once: true });
      this.pending.set(requestId, pending);
      try { child.stdin?.write(`${JSON.stringify({ id: requestId, type: "transcribe", audio_path: filePath })}\n`); }
      catch (error) { this.failPending(pending, new Error(`Failed to send transcription request: ${error instanceof Error ? error.message : String(error)}`)); }
    });
  }
}
