import { spawn } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";

export interface ExecResult {
  stdout: string;
  stderr: string;
}

export async function resolveExecutable(command: string): Promise<string> {
  // `where.exe` is the resolver itself. Resolving it through execCommand would
  // recurse (`where.exe` -> resolveExecutable("where.exe") -> ...), eventually
  // failing with an opaque Windows spawn error such as EFTYPE. This is most
  // visible for MCP stdio processes whose cwd is `dist/`.
  if (path.isAbsolute(command)) {
    await fs.access(command, fs.constants.X_OK);
    return command;
  }
  if (!process.platform.startsWith("win")) {
    for (const directory of (process.env.PATH || "").split(path.delimiter).filter(Boolean)) {
      const candidate = path.join(directory, command);
      try {
        await fs.access(candidate, fs.constants.X_OK);
        return candidate;
      } catch { /* Keep searching PATH. */ }
    }
    return command;
  }
  if (/^(?:cmd|where)\.exe$/i.test(command)) return command;
  return await new Promise((resolve) => {
    const locator = spawn("where.exe", [command], { windowsHide: true });
    let stdout = "";
    locator.stdout?.on("data", (chunk: Buffer) => { stdout += chunk.toString("utf8"); });
    locator.on("error", () => resolve(command));
    locator.on("close", () => {
      const candidates = stdout.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
      // `where git` can return a same-directory `git.js` before git.exe when
      // PATHEXT includes .JS. Node cannot launch that script directly, so only
      // retain formats accepted by CreateProcess for these control-plane tools.
      const executable = candidates.find((candidate) => {
        const extension = path.extname(candidate).toLowerCase();
        return !extension || [".exe", ".cmd", ".bat", ".com"].includes(extension);
      });
      resolve(executable || command);
    });
  });
}

export function execCommand(command: string, args: string[], options: { cwd?: string; timeout?: number; env?: NodeJS.ProcessEnv; maxOutputBytes?: number } = {}): Promise<ExecResult> {
  return (async () => {
    const executable = await resolveExecutable(command);
    return await new Promise<ExecResult>((resolve, reject) => {
      let child: ReturnType<typeof spawn>;
      try {
        child = spawn(executable, args, { cwd: options.cwd, env: options.env, windowsHide: true, detached: !process.platform.startsWith("win") });
      } catch (error) {
        const detail = error instanceof Error ? error.message : String(error);
        reject(new Error(`Failed to spawn ${executable} (cwd=${options.cwd || process.cwd()}): ${detail}`));
        return;
      }
    let stdout = "";
    let stderr = "";
    let settled = false;
    const maxOutputBytes = options.maxOutputBytes ?? 8 * 1024 * 1024;
    const finish = (operation: () => void) => {
      if (settled) return;
      settled = true;
      if (timer) clearTimeout(timer);
      operation();
    };
    const stop = (signal: NodeJS.Signals) => {
      if (child.pid === undefined) return;
      try {
        if (process.platform.startsWith("win")) child.kill(signal);
        else process.kill(-child.pid, signal);
      } catch { /* The child may already have exited. */ }
    };
    const timer = options.timeout ? setTimeout(() => {
      stop("SIGTERM");
      const escalation = setTimeout(() => stop("SIGKILL"), 5_000);
      escalation.unref();
    }, options.timeout) : undefined;
    const append = (target: "stdout" | "stderr", chunk: Buffer) => {
      if (settled) return;
      if (Buffer.byteLength(target === "stdout" ? stdout : stderr, "utf8") + chunk.byteLength > maxOutputBytes) {
        stop("SIGTERM");
        finish(() => reject(new Error(`Command output exceeded ${maxOutputBytes} bytes: ${command}`)));
        return;
      }
      if (target === "stdout") stdout += chunk.toString("utf8");
      else stderr += chunk.toString("utf8");
    };
    child.stdout?.on("data", (chunk: Buffer) => append("stdout", chunk));
    child.stderr?.on("data", (chunk: Buffer) => append("stderr", chunk));
    child.on("error", (error) => {
      finish(() => reject(error));
    });
    child.on("close", (code) => {
      finish(() => {
        if (code === 0) resolve({ stdout, stderr });
        else reject(Object.assign(new Error(`Command failed (${code}): ${command} ${args.join(" ")}\n${stderr || stdout}`), { code }));
      });
    });
    });
  })();
}
