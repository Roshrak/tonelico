import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { loadConfig } from "../src/config.js";
import { DocumentManager } from "../src/documentManager.js";

test("study sessions retain compact scoped state and idempotent concept-validated attempts", async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "agy-study-session-"));
  const studyHome = path.join(root, "study-herd");
  const subjectDirectory = path.join(studyHome, "subjects", "demo");
  const sourcePath = path.join(root, "slide.md");
  await fs.mkdir(subjectDirectory, { recursive: true });
  await fs.writeFile(sourcePath, "# Slide 1\n\nScoped evidence for adaptive study.\n", "utf8");
  await fs.writeFile(path.join(subjectDirectory, "subject.yaml"), "subject: demo\ndisplay_name: Demo\nlanguage: vi\nexam_policy:\n  slides_are_exam_axis: true\nlearning_defaults:\n  application_question_per_topic: true\n", "utf8");
  await fs.writeFile(path.join(subjectDirectory, "concept-map.json"), JSON.stringify({ concepts: [{ id: "c1", label: "Concept one" }] }), "utf8");
  const manager = new DocumentManager({ config: loadConfig({ root, studyHerdHome: studyHome }) });
  try {
    const ingest = await manager.ingest({ collection_name: "demo", paths: [sourcePath] }) as any;
    const indexed = await manager.wait(ingest.job_id, 10) as any;
    assert.equal(indexed.state, "ready_for_commander");
    const scope = await manager.createScope({
      collection_id: ingest.collection_id,
      profile: "study",
      selectors: [{ source_id: "slide.md", sections: ["Slide 1"] }],
      forbidden_topics: ["outside scope"],
    });
    const started = await manager.startStudySession({
      subject_id: "demo",
      collection_id: ingest.collection_id,
      scope_id: scope.scope_id,
      mode: "quiz-adaptive",
      commander_model: "gpt-5.6-terra",
      active_concept_ids: ["c1"],
    }) as any;
    assert.equal(started.subject_policy.exam_policy.slides_are_exam_axis, true);
    const preflight = await manager.preflightStudySession({ session_id: started.session_id, draft: "This goes outside scope." }) as any;
    assert.equal(preflight.valid, false);
    assert.deepEqual(preflight.forbidden_topics_found, ["outside scope"]);
    assert.equal(preflight.subject_policy.learning_defaults.application_question_per_topic, true);
    const first = await manager.recordStudyAttempt({
      attempt_id: "attempt-1",
      session_id: started.session_id,
      concept_id: "c1",
      correct: true,
      difficulty: "clinical",
      context_signature: "case-v1",
      reasoning_quality: "sound",
      occurred_at: "2026-08-31T00:00:00Z",
    }) as any;
    const duplicate = await manager.recordStudyAttempt({
      attempt_id: "attempt-1",
      session_id: started.session_id,
      concept_id: "c1",
      correct: true,
      difficulty: "clinical",
      context_signature: "case-v1",
      reasoning_quality: "sound",
    }) as any;
    assert.equal(first.duplicate, false);
    assert.equal(duplicate.duplicate, true);
    const mirrored = (await fs.readFile(first.attempts_path, "utf8")).trim().split(/\r?\n/).map((line) => JSON.parse(line));
    assert.equal(mirrored.length, 1);
    assert.equal(mirrored[0].attempt_id, "attempt-1");
    await assert.rejects(() => manager.recordStudyAttempt({
      attempt_id: "attempt-1",
      session_id: started.session_id,
      concept_id: "c1",
      correct: false,
      difficulty: "clinical",
      context_signature: "case-v1",
      reasoning_quality: "sound",
      occurred_at: "2026-08-31T00:00:00Z",
    }), /already used with different content/);
    await assert.rejects(() => manager.recordStudyAttempt({
      session_id: started.session_id,
      concept_id: "c1",
      correct: true,
      difficulty: "clinical",
      context_signature: "case-v2",
      reasoning_quality: "sound",
      occurred_at: "2026-08-31T00:00:00",
    }), /timezone offset/);
    const resumed = await manager.resumeStudySession(started.session_id) as any;
    assert.equal(resumed.mode, "quiz-adaptive");
    assert.equal(resumed.attempt_count, 1);
    await assert.rejects(() => manager.recordStudyAttempt({
      session_id: started.session_id,
      concept_id: "unknown",
      correct: true,
      difficulty: "clinical",
      context_signature: "case-v2",
      reasoning_quality: "sound",
    }), /Unknown concept/);
  } finally {
    await manager.shutdown();
  }
});
