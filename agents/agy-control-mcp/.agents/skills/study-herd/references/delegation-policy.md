# Delegation policy

## Allowed worker jobs

- Build a source inventory or page/heading map.
- Extract text from a supplied page slice.
- Normalize OCR/transcript text while preserving source order.
- Attach candidate locators to supplied claims.
- Compare a draft against a supplied coverage checklist.
- Transcribe an exam stem and answer options without deciding the answer.

## Forbidden worker jobs

- Final teaching or summary.
- Clinical interpretation, current-guideline review, or prescribing logic.
- Final answer keys, distractor quality judgment, learner grading, or mastery.
- Editing sources, state, or final output.

## Worker contract

Give the worker only a self-contained input bundle under `.study-work/<run>/`. Never run more than two workers concurrently. The runner embeds at most 200,000 characters from the locked bundle and does not grant worker tool access. Require `worker-result.schema.json`. It must echo its source, page scope, and role; expose uncertainties; and attach a page, line, or section locator to every item. One retry is allowed. A missing executable, timeout, malformed JSON, absent locator, incomplete `done` result, or range violation means the commander continues without the worker.

Use `gemini-3.7-flash-high` by default for clerical workers. `gemini-3.7-flash-low` and `gemini-3.7-flash-medium` are forbidden: reject an explicit override instead of silently downgrading or rewriting it. Never promote a worker into the commander role. Keep `worker-result.json` separate from `worker-run.json`, which records conversation, duration, attempt count, selected model, and token usage for auditing.

Do not spawn a worker for one short concept, a few slide lines, or a task the selected commander can inspect directly. AGY has substantial fixed context overhead even for tiny inputs; reserve it for bulk extraction, independent source partitions, exam transcription, or coverage checks where the saved commander context justifies the cost.
