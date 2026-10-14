#!/usr/bin/env node
import fs from "node:fs/promises";
import os from "node:os";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import {
  buildScope,
  buildSourceIndex,
  ScopeError,
  summarizeSourceIndex,
  validateDraftTopics,
  validateScopeContract,
} from "./studyCore.js";
import { appendAttempt, deriveProgress, loadConcepts } from "./studyProgress.js";
import { AntigravityClerkRunner } from "./studyRunner.js";
import { validateTaskObject, validateWorkerResultObject, validateWorkerSemantics } from "./studyValidation.js";

const execFileAsync = promisify(execFile);

type ParsedArguments = { positionals: string[]; flags: Map<string, string | string[] | boolean> };

function emit(payload: Record<string, unknown>): void {
  process.stdout.write(`${JSON.stringify(payload, null, 2)}\n`);
}

async function readJsonObject(filePath: string): Promise<Record<string, unknown>> {
  const payload = JSON.parse(await fs.readFile(filePath, "utf8")) as unknown;
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) throw new Error(`Expected JSON object in ${filePath}`);
  return payload as Record<string, unknown>;
}

async function writeJson(filePath: string, payload: unknown): Promise<void> {
  await fs.mkdir(path.dirname(path.resolve(filePath)), { recursive: true });
  await fs.writeFile(filePath, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
}

function parseArguments(argv: string[]): ParsedArguments {
  const result: ParsedArguments = { positionals: [], flags: new Map() };
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (!argument.startsWith("--")) {
      result.positionals.push(argument);
      continue;
    }
    const key = argument.slice(2);
    if (key === "correct" || key === "incorrect") {
      result.flags.set(key, true);
      continue;
    }
    const next = argv[++index];
    if (next === undefined) throw new Error(`Missing value for --${key}`);
    const existing = result.flags.get(key);
    if (existing === undefined) result.flags.set(key, next);
    else if (Array.isArray(existing)) existing.push(next);
    else result.flags.set(key, [String(existing), next]);
  }
  return result;
}

function strings(flags: Map<string, string | string[] | boolean>, key: string): string[] {
  const value = flags.get(key);
  if (!value) return [];
  return Array.isArray(value) ? value : typeof value === "string" ? [value] : [];
}

function required(flags: Map<string, string | string[] | boolean>, key: string): string {
  const value = flags.get(key);
  if (typeof value !== "string" || !value.trim()) throw new Error(`--${key} is required`);
  return value;
}

function parsePages(value: string): [number, number] {
  const [start, end] = value.split(":");
  const first = Number(start);
  const second = Number(end);
  if (!Number.isInteger(first) || !Number.isInteger(second)) throw new Error("Pages must use START:END, for example 1:13");
  return [first, second];
}

function fail(message: string): never {
  emit({ status: "error", error: message });
  process.exitCode = 1;
  return process.exit(process.exitCode) as never;
}

async function which(command: string): Promise<string | null> {
  try {
    const { stdout } = await execFileAsync("where.exe", [command], { timeout: 5000 });
    return stdout.split(/\r?\n/).map((line) => line.trim()).find(Boolean) || null;
  } catch { return null; }
}

async function doctor(): Promise<Record<string, unknown>> {
  let agyPath = await which("agy");
  if (!agyPath && process.env.LOCALAPPDATA) {
    const fallback = path.join(process.env.LOCALAPPDATA, "agy", "bin", "agy.exe");
    agyPath = await fs.stat(fallback).then(() => fallback).catch(() => null);
  }
  let antigravity: Record<string, unknown>;
  if (!agyPath) antigravity = { installed: false, ready: false, reason: "agy was not found on PATH", path: null, capabilities: {} };
  else {
    try {
      const completed = await execFileAsync(agyPath, ["--help"], { timeout: 15000 });
      const help = `${completed.stdout}\n${completed.stderr}`.toLowerCase();
      const capabilities = { print_mode: help.includes("--print") || help.includes("-p"), json_output: help.includes("--output-format"), json_schema: help.includes("--json-schema") };
      const ready = Object.values(capabilities).every(Boolean);
      antigravity = { installed: true, ready, reason: ready ? null : "agy lacks a required structured-output capability", path: agyPath, capabilities };
    } catch (error) {
      antigravity = { installed: true, ready: false, reason: `Could not execute agy: ${error instanceof Error ? error.message : String(error)}`, path: agyPath, capabilities: {} };
    }
  }
  const ready = antigravity.ready === true;
  return {
    checked_at: new Date().toISOString(), node: process.version, platform: `${os.type()} ${os.release()}`,
    runtimes: { codex: { on_path: Boolean(await which("codex")) }, antigravity, herdr: { installed: Boolean(await which("herdr")), path: await which("herdr") } },
    worker_mode: ready ? "available" : "commander-only",
    next_action: ready ? "Workers may be used for bounded clerical tasks only." : "Install or repair Antigravity CLI, then rerun doctor.",
  };
}

export async function main(argv: string[]): Promise<number> {
  const [command, ...rest] = argv;
  if (!command || command === "--help" || command === "-h") {
    emit({ usage: "study-herd <doctor|index|scope|validate-scope|validate-worker|validate-task|record-attempt|progress>", deprecated: "Use agy-control MCP tools when available" });
    return command ? 0 : 1;
  }
  const args = parseArguments(rest);
  switch (command) {
    case "doctor":
      emit(await doctor());
      return 0;
    case "index": {
      const manifestPath = args.positionals[0];
      if (!manifestPath) throw new Error("A YAML source manifest is required");
      const index = await buildSourceIndex(manifestPath);
      const outputValue = args.flags.get("output");
      const destination = typeof outputValue === "string" ? outputValue : path.join(path.dirname(manifestPath), ".generated", "source-index.json");
      await writeJson(destination, index);
      emit({ status: "ok", output: destination, summary: summarizeSourceIndex(index) });
      return 0;
    }
    case "scope": {
      const indexPath = args.positionals[0];
      if (!indexPath) throw new Error("A source-index JSON file is required");
      const pages = parsePages(required(args.flags, "pages"));
      const scope = buildScope(await readJsonObject(indexPath) as any, required(args.flags, "source-id"), pages[0], pages[1], strings(args.flags, "topic"), strings(args.flags, "forbidden-topic"));
      const outputValue = args.flags.get("output");
      const destination = typeof outputValue === "string" ? outputValue : path.join(path.dirname(indexPath), `scope-${scope.source_id}.json`);
      await writeJson(destination, scope);
      emit({ status: "ok", output: destination, scope });
      return 0;
    }
    case "validate-scope": {
      const scopePath = args.positionals[0];
      if (!scopePath) throw new Error("A scope JSON file is required");
      const scope = await readJsonObject(scopePath);
      const sourceIndex = await readJsonObject(required(args.flags, "source-index"));
      const violations = validateScopeContract(scope, sourceIndex as any);
      const draftFile = args.flags.get("draft-file");
      if (typeof draftFile === "string") violations.push(...validateDraftTopics(scope, await fs.readFile(draftFile, "utf8")));
      emit({ status: violations.length ? "rejected" : "ok", violations });
      return violations.length ? 2 : 0;
    }
    case "validate-worker": {
      const resultPath = args.positionals[0];
      if (!resultPath) throw new Error("A worker-result JSON file is required");
      const validation = validateWorkerResultObject(await readJsonObject(resultPath));
      const expectedPagesValue = args.flags.get("expected-pages");
      const semantic = validateWorkerSemantics(validation, {
        expected_source_id: typeof args.flags.get("expected-source-id") === "string" ? args.flags.get("expected-source-id") as string : undefined,
        expected_pages: typeof expectedPagesValue === "string" ? parsePages(expectedPagesValue) : undefined,
        expected_role: typeof args.flags.get("expected-role") === "string" ? args.flags.get("expected-role") as string : undefined,
      });
      emit(semantic.valid ? { status: "ok", valid: true, errors: [] } : { status: "rejected", valid: false, errors: semantic.errors });
      return semantic.valid ? 0 : 2;
    }
    case "validate-task": {
      const taskPath = args.positionals[0];
      if (!taskPath) throw new Error("A task JSON file is required");
      const validation = validateTaskObject(await readJsonObject(taskPath));
      emit(validation.valid ? { status: "ok", valid: true, errors: [] } : { status: "rejected", valid: false, errors: validation.errors });
      return validation.valid ? 0 : 2;
    }
    case "run-worker": {
      const taskPath = args.positionals[0];
      if (!taskPath) throw new Error("A worker task JSON file is required");
      const runner = new AntigravityClerkRunner();
      const result = await runner.run(taskPath, {
        work_dir: required(args.flags, "work-dir"),
        timeout_seconds: Number(args.flags.get("timeout-seconds") || 300),
        max_retries: Number(args.flags.get("max-retries") ?? 1),
      });
      emit({ status: "ok", result });
      return 0;
    }
    case "record-attempt": {
      const conceptsPath = required(args.flags, "concepts");
      const attemptsPath = required(args.flags, "attempts");
      const conceptId = required(args.flags, "concept-id");
      // Validate the concept id against the map BEFORE any learner state is written.
      const concepts = await loadConcepts(conceptsPath);
      if (!concepts.has(conceptId)) throw new Error(`Unknown concept id: ${conceptId}`);
      const attempt = await appendAttempt(attemptsPath, {
        concept_id: conceptId,
        correct: args.flags.get("correct") === true,
        difficulty: required(args.flags, "difficulty") as any,
        context_signature: required(args.flags, "context"),
        reasoning_quality: required(args.flags, "reasoning") as any,
        occurred_at: typeof args.flags.get("occurred-at") === "string" ? args.flags.get("occurred-at") as string : undefined,
      });
      const progress = await deriveProgress(conceptsPath, attemptsPath);
      const progressOutput = args.flags.get("progress-output");
      if (typeof progressOutput === "string") await writeJson(progressOutput, progress);
      emit({ status: "ok", attempt, progress });
      return 0;
    }
    case "progress": {
      const conceptsPath = required(args.flags, "concepts");
      const attemptsPath = required(args.flags, "attempts");
      const progress = await deriveProgress(conceptsPath, attemptsPath);
      const output = args.flags.get("output");
      if (typeof output === "string") await writeJson(output, progress);
      emit({ status: "ok", progress });
      return 0;
    }
    default:
      throw new Error(`Unknown command: ${command}`);
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  void main(process.argv.slice(2)).then((code) => {
    process.exitCode = code;
  }).catch((error: unknown) => {
    if (error instanceof ScopeError) return fail(error.message);
    return fail(error instanceof Error ? error.message : String(error));
  });
}
