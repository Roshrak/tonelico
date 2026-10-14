import { spawn } from "node:child_process";
import { createWriteStream } from "node:fs";
import { StringDecoder } from "node:string_decoder";
import { redactSecrets } from "./promptCompiler.js";
import { execCommand, resolveExecutable } from "./processUtils.js";
import type { AgyEvent, AgyOutcome, TokenUsage } from "./types.js";

export type { AgyOutcome };

export interface RunnerJob {
  runId: string;
  command: string;
  args: string[];
  cwd: string;
  prompt: string;
  eventLogPath: string;
  stderrLogPath: string;
  timeoutSeconds: number;
  tokenBudget: number;
  maxLogBytes: number;
  conversationId?: string;
  conversationUsageBaseline?: TokenUsage;
  onEvent?: (event: AgyEvent) => void;
}

export interface AgyRunnerLike {
  run(job: RunnerJob): Promise<AgyOutcome>;
  kill(runId: string): Promise<void>;
  registerProcess(runId: string, child: ReturnType<typeof spawn> | undefined): void;
}

function addUsage(target: TokenUsage, usage?: TokenUsage): TokenUsage {
  target.input_tokens = (target.input_tokens || 0) + (usage?.input_tokens || 0);
  target.output_tokens = (target.output_tokens || 0) + (usage?.output_tokens || 0);
  target.thinking_tokens = (target.thinking_tokens || 0) + (usage?.thinking_tokens || 0);
  target.cache_read_tokens = (target.cache_read_tokens || 0) + (usage?.cache_read_tokens || 0);
  target.total_tokens = (target.total_tokens || 0) + (usage?.total_tokens || 0);
  return target;
}

function usageDelta(current: TokenUsage | undefined, baseline: TokenUsage | undefined): TokenUsage {
  const delta: TokenUsage = {};
  for (const key of ["input_tokens", "output_tokens", "thinking_tokens", "cache_read_tokens", "total_tokens"] as const) {
    const value = current?.[key];
    if (value !== undefined) delta[key] = Math.max(0, value - (baseline?.[key] || 0));
  }
  return delta;
}

function agyEnvironment(): NodeJS.ProcessEnv {
  const env: NodeJS.ProcessEnv = {};
  const sensitive = /(authorization|api[_-]?key|token|secret|password|credential|connection)/i;
  for (const [key, value] of Object.entries(process.env)) {
    if (value !== undefined && !sensitive.test(key)) env[key] = value;
  }
  return env;
}

export class AgyRunner implements AgyRunnerLike {
  private readonly processes = new Map<string, ReturnType<typeof spawn>>();

  registerProcess(runId: string, child: ReturnType<typeof spawn> | undefined): void {
    if (child) this.processes.set(runId, child);
  }

  async kill(runId: string): Promise<void> {
    const child = this.processes.get(runId);
    if (!child || child.pid === undefined) return;
    if (process.platform.startsWith("win")) {
      await execCommand("taskkill.exe", ["/PID", String(child.pid), "/T", "/F"], { timeout: 5000 }).catch(() => undefined);
    } else {
      try { process.kill(-child.pid, "SIGTERM"); }
      catch { child.kill("SIGTERM"); }
      const escalation = setTimeout(() => {
        if (child.pid === undefined || child.exitCode !== null) return;
        try { process.kill(-child.pid, "SIGKILL"); } catch { child.kill("SIGKILL"); }
      }, 5_000);
      escalation.unref();
    }
  }

  async run(job: RunnerJob): Promise<AgyOutcome> {
    const executable = await resolveExecutable(job.command);
    const child = spawn(executable, job.args, { cwd: job.cwd, windowsHide: true, env: agyEnvironment(), detached: !process.platform.startsWith("win") });
    const eventLog = createWriteStream(job.eventLogPath, { flags: "a", mode: 0o600 });
    const stderrLog = createWriteStream(job.stderrLogPath, { flags: "a", mode: 0o600 });
    const usage: TokenUsage = {};
    const stepUsage: TokenUsage = {};
    let result: AgyEvent["result"];
    let conversationId: string | undefined = job.conversationId;
    let model: string | undefined;
    let stderr = "";
    let stdoutBuffer = "";
    let stderrBuffer = "";
    let timedOut = false;
    let cancelledByBudget = false;
    let settled = false;
    const stdoutDecoder = new StringDecoder("utf8");
    const stderrDecoder = new StringDecoder("utf8");

    return await new Promise<AgyOutcome>((resolve) => {
      const finish = (outcome: AgyOutcome): void => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        this.processes.delete(job.runId);
        eventLog.end();
        stderrLog.end();
        resolve(outcome);
      };
      const stop = async (reason: "timeout" | "budget") => {
        if (reason === "timeout") timedOut = true;
        else cancelledByBudget = true;
        await this.kill(job.runId).catch(() => undefined);
      };
      const timer = setTimeout(() => { void stop("timeout"); }, job.timeoutSeconds * 1000);
      const writeEventLine = (event: AgyEvent) => {
        const copy = JSON.parse(JSON.stringify(event)) as AgyEvent;
        if (copy.event === "result" && copy.result) {
          copy.result.response = undefined;
          if (copy.result.structured_output && typeof copy.result.structured_output === "object") {
            const structured = copy.result.structured_output as Record<string, unknown>;
            if (typeof structured.patch === "string") structured.patch = `[patch omitted: ${Buffer.byteLength(structured.patch, "utf8")} bytes]`;
          }
        }
        eventLog.write(`${redactSecrets(JSON.stringify(copy)).text}\n`);
      };
      const appendStderr = (text: string) => {
        const clean = redactSecrets(text).text;
        stderr = `${stderr}${clean}`.slice(-job.maxLogBytes);
        stderrLog.write(clean);
      };
      const handleEvent = (line: string) => {
        if (!line.trim()) return;
        let event: AgyEvent;
        try { event = JSON.parse(line) as AgyEvent; }
        catch { eventLog.write(`${redactSecrets(line).text}\n`); return; }
        writeEventLine(event);
        job.onEvent?.(event);
        if (event.event === "init") {
          conversationId ||= event.init?.conversation_id;
          model ||= event.init?.model;
        }
        if (event.event === "step_update") {
          conversationId ||= event.step_update?.conversation_id;
          addUsage(stepUsage, event.step_update?.usage);
          const generated = (stepUsage.output_tokens || 0) + (stepUsage.thinking_tokens || 0);
          if (generated > job.tokenBudget && !cancelledByBudget) void stop("budget");
        }
        if (event.event === "result") {
          result = event.result;
          conversationId ||= event.result?.conversation_id;
          Object.assign(usage, usageDelta(event.result?.usage, job.conversationUsageBaseline));
          const generated = (usage.output_tokens || 0) + (usage.thinking_tokens || 0);
          if (generated > job.tokenBudget) cancelledByBudget = true;
        }
      };

      child.stdout?.on("data", (chunk: Buffer) => {
        stdoutBuffer += stdoutDecoder.write(chunk);
        let newline: number;
        while ((newline = stdoutBuffer.indexOf("\n")) >= 0) {
          const line = stdoutBuffer.slice(0, newline).replace(/\r$/, "");
          stdoutBuffer = stdoutBuffer.slice(newline + 1);
          handleEvent(line);
        }
        if (Buffer.byteLength(stdoutBuffer, "utf8") > job.maxLogBytes) void stop("budget");
      });
      child.stderr?.on("data", (chunk: Buffer) => {
        stderrBuffer += stderrDecoder.write(chunk);
        if (stderrBuffer.length > 8192) {
          appendStderr(stderrBuffer);
          stderrBuffer = "";
        }
      });
      child.stdin?.on("error", (error) => appendStderr(`stdin_error: ${error.message}\n`));

      child.on("error", (error) => finish({ state: "failed", failureReason: "spawn_failed", errorMessage: error.message, exitCode: null, usage: {} }));
      child.on("close", (code) => {
        stdoutBuffer += stdoutDecoder.end();
        if (stdoutBuffer.trim()) handleEvent(stdoutBuffer.replace(/\r$/, ""));
        stderrBuffer += stderrDecoder.end();
        if (stderrBuffer) appendStderr(stderrBuffer);
        if (cancelledByBudget) {
          finish({ state: "failed", failureReason: "budget_exceeded", errorMessage: "Token budget exceeded", exitCode: code, conversationId, model, structuredOutput: result?.structured_output, numTurns: result?.num_turns, usage, conversationUsage: result?.usage });
        } else if (timedOut) {
          finish({ state: "timeout", failureReason: "timeout", errorMessage: `AGY exceeded ${job.timeoutSeconds}s`, exitCode: code, conversationId, model, usage });
        } else if (/quota.*(exhaust|exceeded)|resource.*exhausted/i.test(`${stderr}${result?.response || ""}`)) {
          finish({ state: "failed", failureReason: "quota_exhausted", errorMessage: "AGY quota exhausted", exitCode: code, conversationId, model, usage });
        } else if (result) {
          const success = result.status === "SUCCESS" && result.structured_output !== undefined;
          finish({ state: success ? "done" : "partial", failureReason: success ? undefined : "agy_error", errorMessage: success ? undefined : `AGY status=${result.status || "UNKNOWN"} or missing structured output`, exitCode: code, conversationId, model, response: result.response, structuredOutput: result.structured_output, numTurns: result.num_turns, usage, conversationUsage: result.usage });
        } else {
          finish({ state: code === 0 ? "partial" : "failed", failureReason: code === 0 ? "agy_error" : "interrupted", errorMessage: stderr.slice(-2000) || "AGY ended without a stream-json result", exitCode: code, conversationId, model, usage });
        }
      });

      this.registerProcess(job.runId, child);
      const message = JSON.stringify({ event: "user", message: { content: job.prompt } });
      child.stdin?.end(`${message}\n`);
    });
  }
}
