import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { appendAttempt, deriveProgress } from "../src/studyProgress.js";

async function temporaryDirectory(): Promise<string> {
  return await fs.mkdtemp(path.join(os.tmpdir(), "agy-study-"));
}

test("mastery requires correct transfer across contexts and time", async () => {
  const directory = await temporaryDirectory();
  const conceptsPath = path.join(directory, "concepts.json");
  const attemptsPath = path.join(directory, "attempts.jsonl");
  await fs.writeFile(conceptsPath, JSON.stringify({ concepts: [{ id: "ras", label: "RAS", tier: "A" }] }), "utf8");
  assert.equal((await deriveProgress(conceptsPath, attemptsPath)).concepts[0].status, "unseen");
  await appendAttempt(attemptsPath, { concept_id: "ras", correct: false, difficulty: "recall", context_signature: "definition-v1", reasoning_quality: "weak", occurred_at: "2026-08-01T00:00:00+00:00" });
  assert.equal((await deriveProgress(conceptsPath, attemptsPath)).concepts[0].status, "fragile");
  await appendAttempt(attemptsPath, { concept_id: "ras", correct: true, difficulty: "mechanism", context_signature: "mechanism-v1", reasoning_quality: "sound", occurred_at: "2026-08-02T00:00:00+00:00" });
  await appendAttempt(attemptsPath, { concept_id: "ras", correct: true, difficulty: "clinical", context_signature: "clinical-v1", reasoning_quality: "sound", occurred_at: "2026-08-03T00:00:00+07:00" });
  await appendAttempt(attemptsPath, { concept_id: "ras", correct: true, difficulty: "multi-step", context_signature: "clinical-v2", reasoning_quality: "sound", occurred_at: "2026-08-04T00:00:00+07:00" });
  assert.equal((await deriveProgress(conceptsPath, attemptsPath)).concepts[0].status, "mastered");
});

test("timestamps require timezone and last attempt uses time order", async () => {
  const directory = await temporaryDirectory();
  const conceptsPath = path.join(directory, "concepts.json");
  const attemptsPath = path.join(directory, "attempts.jsonl");
  await fs.writeFile(conceptsPath, JSON.stringify({ concepts: [{ id: "ras" }] }), "utf8");
  await assert.rejects(() => appendAttempt(attemptsPath, { concept_id: "ras", correct: true, difficulty: "clinical", context_signature: "case", reasoning_quality: "sound", occurred_at: "2026-08-20T10:00:00" }), /timezone offset/);
  await appendAttempt(attemptsPath, { concept_id: "ras", correct: true, difficulty: "clinical", context_signature: "newer", reasoning_quality: "sound", occurred_at: "2026-08-20T10:00:00+07:00" });
  await appendAttempt(attemptsPath, { concept_id: "ras", correct: true, difficulty: "recall", context_signature: "backdated", reasoning_quality: "partial", occurred_at: "2026-08-19T10:00:00+07:00" });
  assert.equal((await deriveProgress(conceptsPath, attemptsPath)).concepts[0].last_attempt_at, "2026-08-20T10:00:00+07:00");
});

test("concept maps reject duplicates and unknown attempts", async () => {
  const directory = await temporaryDirectory();
  const duplicatePath = path.join(directory, "duplicate.json");
  const conceptsPath = path.join(directory, "concepts.json");
  const attemptsPath = path.join(directory, "attempts.jsonl");
  await fs.writeFile(duplicatePath, JSON.stringify({ concepts: [{ id: "ras" }, { id: "ras" }] }), "utf8");
  await fs.writeFile(conceptsPath, JSON.stringify({ concepts: [{ id: "ras" }] }), "utf8");
  await appendAttempt(attemptsPath, { concept_id: "typo-concept", correct: true, difficulty: "clinical", context_signature: "case", reasoning_quality: "sound" });
  await assert.rejects(() => deriveProgress(duplicatePath, attemptsPath), /Duplicate concept id/);
  await assert.rejects(() => deriveProgress(conceptsPath, attemptsPath), /unknown concept: typo-concept/);
});
