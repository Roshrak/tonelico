import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { CapacityController } from "../src/capacityController.js";
import { loadConfig } from "../src/config.js";

test("capacity waiters can be cancelled before they start work", async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "agy-capacity-"));
  const controller = new CapacityController(loadConfig({
    root,
    globalConcurrency: 1,
    concurrency: { fast: 1, reasoning: 1, expert: 1 },
  }));
  const release = await controller.acquire("fast", 5);
  let cancelled = false;
  const waiting = controller.acquire("fast", 5, () => cancelled);
  cancelled = true;
  await assert.rejects(waiting, /cancelled/);
  await release();
  const releaseAfterCancellation = await controller.acquire("fast", 5);
  await releaseAfterCancellation();
});
