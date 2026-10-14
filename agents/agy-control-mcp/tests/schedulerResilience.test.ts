import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { CapacityController, CapacityWaitTimeout } from "../src/capacityController.js";
import { loadConfig } from "../src/config.js";
import { PhoWhisperTranscriptionSidecar } from "../src/transcriptionSidecar.js";

test("a slot whose owner process has exited is reclaimed immediately", async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "agy-stale-slot-"));
  const config = loadConfig({ root, globalConcurrency: 1, concurrency: { fast: 1, reasoning: 1, expert: 1 } });
  const stale = path.join(config.lockRoot, "global", "0");
  await fs.mkdir(stale, { recursive: true });
  await fs.writeFile(path.join(stale, "owner.json"), JSON.stringify({ pid: 2147483646, created_at: new Date().toISOString() }));
  const controller = new CapacityController(config);
  const started = Date.now();
  const release = await controller.acquire("fast", 5);
  assert.ok(Date.now() - started < 2_000, "dead-owner slot must not block for the full wait window");
  await release();
});

test("a live owner's slot is still respected", async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "agy-live-slot-"));
  const config = loadConfig({ root, globalConcurrency: 1, concurrency: { fast: 1, reasoning: 1, expert: 1 } });
  const live = path.join(config.lockRoot, "global", "0");
  await fs.mkdir(live, { recursive: true });
  await fs.writeFile(path.join(live, "owner.json"), JSON.stringify({ pid: process.pid, created_at: new Date().toISOString() }));
  const controller = new CapacityController(config);
  await assert.rejects(controller.acquire("fast", 1), CapacityWaitTimeout);
});

test("PhoWhisper is reported as not configured instead of pointing at a Windows-only default", async () => {
  const previous = process.env.PHOWHISPER_APP_HOME;
  delete process.env.PHOWHISPER_APP_HOME;
  try {
    const sidecar = new PhoWhisperTranscriptionSidecar({});
    const availability = await sidecar.availability();
    assert.equal(availability.enabled, false);
    assert.match(String(availability.reason), /PHOWHISPER_APP_HOME/);
    assert.doesNotMatch(availability.application_home, /HH18|C:\\/);
    await assert.rejects(sidecar.transcribe(path.join(os.tmpdir(), "missing.mp3")), /not configured|PHOWHISPER_APP_HOME/);
  } finally {
    if (previous === undefined) delete process.env.PHOWHISPER_APP_HOME; else process.env.PHOWHISPER_APP_HOME = previous;
  }
});
