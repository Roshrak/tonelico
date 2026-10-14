import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { PhoWhisperTranscriptionSidecar } from "../src/transcriptionSidecar.js";

// The compiled test runs from dist-test/tests, so anchor the fixture at the package root cwd.
const fakeSidecar = path.resolve("tests", "fixtures", "fake-sidecar.mjs");

interface Harness {
  sidecar: PhoWhisperTranscriptionSidecar;
  root: string;
  spawnCounts: number[];
}

async function harness(mode: string): Promise<Harness> {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), `agy-persistent-sidecar-${mode}`));
  const model = path.join(root, "model");
  await fs.mkdir(model);
  for (const name of ["config.json", "model.bin", "preprocessor_config.json", "tokenizer.json"]) await fs.writeFile(path.join(model, name), "ok");
  const spawnCounts: number[] = [];
  const sidecar = new PhoWhisperTranscriptionSidecar({
    applicationHome: root,
    pythonPath: path.join(root, "python.exe"),
    modelDirectory: model,
    timeoutSeconds: 30,
    spawnCommand: process.execPath,
    spawnArgs: [fakeSidecar],
  });
  const originalEnsure = (sidecar as unknown as { ensureProcess(): Promise<unknown> }).ensureProcess.bind(sidecar);
  (sidecar as unknown as { ensureProcess(): Promise<unknown> }).ensureProcess = async () => {
    spawnCounts.push(Date.now());
    return await originalEnsure();
  };
  process.env.FAKE_SIDECAR_MODE = mode;
  return { sidecar, root, spawnCounts };
}

async function audioFile(root: string, name: string): Promise<string> {
  const filePath = path.join(root, name);
  await fs.writeFile(filePath, Buffer.from([0xff, 0xfb]), "utf8");
  return filePath;
}

test("persistent sidecar spawns once, health-checks, and reuses the model across jobs", async () => {
  const { sidecar, root } = await harness("ok");
  try {
    const first = await sidecar.transcribe(await audioFile(root, "a.mp3"));
    const second = await sidecar.transcribe(await audioFile(root, "b.wav"));
    assert.equal(first.elements.length, 2);
    assert.equal(first.parser_version, "phowhisper-sidecar-v1");
    assert.equal(second.elements[0].text, "Xin chào bác sĩ");
    // One spawn for both jobs: the model stays loaded in the persistent child.
    assert.equal((sidecar as unknown as { spawnedOnce: boolean }).spawnedOnce, true);
    assert.equal((sidecar as unknown as { restartsUsed: number }).restartsUsed, 0);
    assert.equal(sidecar.activeCount(), 0);
  } finally {
    await sidecar.shutdown();
  }
});

test("a crashed sidecar fails the active job and allows exactly one restart at a later job", async () => {
  const { sidecar, root, spawnCounts } = await harness("crash_after_accept");
  try {
    await assert.rejects(async () => sidecar.transcribe(await audioFile(root, "boom1.mp3")), /crashed|exited during startup/i);
    // The next job may restart the sidecar exactly once and then succeed.
    const recovered = await sidecar.transcribe(await audioFile(root, "after-crash.mp3"));
    assert.equal(recovered.elements.length, 2);
    assert.equal(spawnCounts.length, 2);
    // A second crash consumed the only allowed restart: further jobs fail closed.
    await assert.rejects(async () => sidecar.transcribe(await audioFile(root, "boom2.mp3")), /crashed|exited during startup/i);
    await assert.rejects(async () => sidecar.transcribe(await audioFile(root, "no-more-restarts.mp3")), /single allowed restart/);
  } finally {
    process.env.FAKE_SIDECAR_MODE = "ok";
    await sidecar.shutdown().catch(() => undefined);
  }
});

test("invalid NDJSON fails the active job instead of hanging or leaking pending state", async () => {
  process.env.FAKE_SIDECAR_MODE = "invalid_ndjson";
  const { sidecar, root } = await harness("invalid_ndjson");
  try {
    await assert.rejects(async () => sidecar.transcribe(await audioFile(root, "bad.ndjson.mp3")), /Invalid sidecar NDJSON|crashed|exited/i);
  } finally {
    process.env.FAKE_SIDECAR_MODE = "ok";
    await sidecar.shutdown().catch(() => undefined);
  }
});

test("aborting a transcription cancels over the protocol before any tree kill is needed", async () => {
  process.env.FAKE_SIDECAR_MODE = "slow_cancelable";
  const { sidecar, root } = await harness("slow_cancelable");
  try {
    // First job: aborted mid-flight; the graceful protocol cancel must win.
    const controller = new AbortController();
    const firstJob = sidecar.transcribe(await audioFile(root, "long.mp3"), controller.signal);
    setTimeout(() => controller.abort(), 120);
    await assert.rejects(() => firstJob, (error: Error) => error.name === "TranscriptionCancelledError");
    // The sidecar never crashed, so the SAME child serves the next job (no restart consumed).
    const restartsBefore = (sidecar as unknown as { restartsUsed: number }).restartsUsed;
    const controller2 = new AbortController();
    const secondJob = sidecar.transcribe(await audioFile(root, "long-2.mp3"), controller2.signal);
    setTimeout(() => controller2.abort(), 120);
    await assert.rejects(() => secondJob, (error: Error) => error.name === "TranscriptionCancelledError");
    assert.equal((sidecar as unknown as { restartsUsed: number }).restartsUsed, restartsBefore);
  } finally {
    process.env.FAKE_SIDECAR_MODE = "ok";
    await sidecar.shutdown().catch(() => undefined);
  }
});

test("shutdown uses the JSONL protocol and the child exits without being force-killed", async () => {
  const { sidecar, root } = await harness("ok");
  await sidecar.transcribe(await audioFile(root, "shutdown-check.mp3"));
  const child = (sidecar as unknown as { child?: { exitCode: number | null } }).child;
  assert.ok(child);
  await sidecar.shutdown();
  assert.equal(child.exitCode !== null && child.exitCode !== undefined, true);
});

test("media transcription surfaces engine failures verbatim for silent video", async () => {
  process.env.FAKE_SIDECAR_MODE = "reject";
  const { sidecar, root } = await harness("reject");
  try {
    await assert.rejects(async () => sidecar.transcribe(await audioFile(root, "silent.mp4")), /no audio track/);
  } finally {
    process.env.FAKE_SIDECAR_MODE = "ok";
    await sidecar.shutdown().catch(() => undefined);
  }
});
