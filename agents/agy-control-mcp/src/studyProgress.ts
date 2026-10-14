import fs from "node:fs/promises";
import path from "node:path";

export interface ConceptRecord { id?: unknown; label?: unknown; tier?: unknown }
export interface AttemptRecord {
  attempt_id?: string;
  session_id?: string;
  subject_id?: string;
  concept_id: string;
  correct: boolean;
  difficulty: "recall" | "mechanism" | "clinical" | "multi-step";
  context_signature: string;
  reasoning_quality: "weak" | "partial" | "sound";
  occurred_at: string;
}

function stableAttempt(attempt: AttemptRecord): string {
  return JSON.stringify(attempt, Object.keys(attempt).sort());
}

async function withAttemptFileLock<T>(attemptsPath: string, operation: () => Promise<T>): Promise<T> {
  const lockPath = `${attemptsPath}.lock`;
  const deadline = Date.now() + 5000;
  await fs.mkdir(path.dirname(attemptsPath), { recursive: true });
  while (true) {
    try {
      await fs.mkdir(lockPath);
      break;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
      const stats = await fs.stat(lockPath).catch(() => undefined);
      if (stats && Date.now() - stats.mtimeMs > 30_000) {
        await fs.rm(lockPath, { recursive: true, force: true }).catch(() => undefined);
        continue;
      }
      if (Date.now() >= deadline) throw new Error("Timed out waiting to append learner attempt");
      await new Promise((resolve) => setTimeout(resolve, 25));
    }
  }
  try {
    return await operation();
  } finally {
    await fs.rm(lockPath, { recursive: true, force: true });
  }
}

function parseTimestamp(value: string): number {
  if (/[zZ]$|[+-]\d{2}:\d{2}$/.test(value)) {
    const milliseconds = Date.parse(value);
    if (!Number.isFinite(milliseconds)) throw new Error(`Invalid attempt timestamp: ${value}`);
    return milliseconds;
  }
  throw new Error(`Attempt timestamp must include a timezone offset: ${value}`);
}

export async function loadConcepts(conceptsPath: string): Promise<Map<string, ConceptRecord & { id: string }>> {
  const raw = JSON.parse(await fs.readFile(conceptsPath, "utf8")) as unknown;
  const values = raw && typeof raw === "object" && Array.isArray((raw as { concepts?: unknown }).concepts)
    ? (raw as { concepts: unknown[] }).concepts
    : Array.isArray(raw) ? raw : null;
  if (!values?.length) throw new Error("Concept map must contain a non-empty concepts array");
  const concepts = new Map<string, ConceptRecord & { id: string }>();
  for (const item of values) {
    const conceptId = item && typeof item === "object" ? (item as ConceptRecord).id : undefined;
    if (!item || typeof item !== "object" || typeof conceptId !== "string" || !conceptId.trim()) {
      throw new Error("Every concept needs a non-empty id");
    }
    const concept = item as ConceptRecord & { id: string };
    if (concepts.has(concept.id)) throw new Error(`Duplicate concept id: ${concept.id}`);
    concepts.set(concept.id, concept);
  }
  return concepts;
}

export async function readAttempts(attemptsPath: string): Promise<AttemptRecord[]> {
  const text = await fs.readFile(attemptsPath, "utf8").catch((error: NodeJS.ErrnoException) => {
    if (error.code === "ENOENT") return "";
    throw error;
  });
  const attempts: AttemptRecord[] = [];
  for (const [index, line] of text.split(/\r?\n/).entries()) {
    if (!line.trim()) continue;
    let payload: unknown;
    try { payload = JSON.parse(line); }
    catch (error) { throw new Error(`Invalid JSONL on line ${index + 1}: ${error instanceof Error ? error.message : String(error)}`); }
    const attempt = payload as AttemptRecord;
    if (!payload || typeof payload !== "object" || typeof attempt.concept_id !== "string") throw new Error(`Attempt line ${index + 1} must identify a concept`);
    attempts.push(attempt);
  }
  return attempts;
}

export async function appendAttempt(attemptsPath: string, input: Omit<AttemptRecord, "occurred_at"> & { occurred_at?: string }): Promise<AttemptRecord> {
  if (!["recall", "mechanism", "clinical", "multi-step"].includes(input.difficulty)) throw new Error(`Unsupported difficulty: ${input.difficulty}`);
  if (!["weak", "partial", "sound"].includes(input.reasoning_quality)) throw new Error(`Unsupported reasoning quality: ${input.reasoning_quality}`);
  if (input.occurred_at) parseTimestamp(input.occurred_at);
  return await withAttemptFileLock(attemptsPath, async () => {
    if (input.attempt_id) {
      const existing = (await readAttempts(attemptsPath)).find((attempt) => attempt.attempt_id === input.attempt_id);
      if (existing) {
        const candidate: AttemptRecord = { ...input, occurred_at: input.occurred_at || existing.occurred_at };
        if (stableAttempt(existing) !== stableAttempt(candidate)) throw new Error(`attempt_id ${input.attempt_id} was already used with different content`);
        return existing;
      }
    }
    const timestamp = input.occurred_at || new Date().toISOString();
    parseTimestamp(timestamp);
    const attempt: AttemptRecord = { ...input, occurred_at: timestamp };
    await fs.appendFile(attemptsPath, `${stableAttempt(attempt)}\n`, "utf8");
    return attempt;
  });
}

function statusForAttempts(attempts: AttemptRecord[]): "unseen" | "fragile" | "learning" | "working" | "secure" | "mastered" {
  if (!attempts.length) return "unseen";
  const ordered = [...attempts].sort((left, right) => parseTimestamp(left.occurred_at) - parseTimestamp(right.occurred_at));
  const latest = ordered.at(-1);
  const correct = ordered.filter((attempt) => attempt.correct === true);
  if (!latest?.correct) return "fragile";
  const contexts = new Set(correct.map((attempt) => String(attempt.context_signature || "")));
  const hasClinical = correct.some((attempt) => ["clinical", "multi-step"].includes(attempt.difficulty));
  const hasSoundReasoning = correct.some((attempt) => attempt.reasoning_quality === "sound");
  if (correct.length >= 3 && contexts.size >= 2 && hasClinical && hasSoundReasoning && parseTimestamp(correct[0].occurred_at) + 24 * 60 * 60 * 1000 <= parseTimestamp(correct.at(-1)!.occurred_at)) return "mastered";
  if (correct.length >= 2 && contexts.size >= 2 && hasClinical && hasSoundReasoning) return "secure";
  return "working";
}

export async function deriveProgress(conceptsPath: string, attemptsPath: string): Promise<{ generated_at: string; concepts: Record<string, unknown>[] }> {
  const concepts = await loadConcepts(conceptsPath);
  const grouped = new Map<string, AttemptRecord[]>();
  for (const attempt of await readAttempts(attemptsPath)) {
    if (!concepts.has(attempt.concept_id)) throw new Error(`Attempt references unknown concept: ${attempt.concept_id}`);
    const existing = grouped.get(attempt.concept_id) || [];
    existing.push(attempt);
    grouped.set(attempt.concept_id, existing);
  }
  return {
    generated_at: new Date().toISOString(),
    concepts: [...concepts.values()].map((concept) => {
      const attempts = grouped.get(concept.id) || [];
      const latest = [...attempts].sort((left, right) => parseTimestamp(left.occurred_at) - parseTimestamp(right.occurred_at)).at(-1);
      return {
        id: concept.id,
        label: typeof concept.label === "string" ? concept.label : concept.id,
        tier: typeof concept.tier === "string" ? concept.tier : "unclassified",
        status: statusForAttempts(attempts),
        attempt_count: attempts.length,
        last_attempt_at: latest?.occurred_at,
      };
    }),
  };
}
