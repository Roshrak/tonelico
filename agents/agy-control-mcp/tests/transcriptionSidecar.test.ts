import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { PhoWhisperTranscriptionSidecar } from "../src/transcriptionSidecar.js";

test("PhoWhisper sidecar reports local readiness without loading a model", async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "agy-phowhisper-"));
  const model = path.join(root, "model");
  await fs.mkdir(model);
  for (const name of ["config.json", "model.bin", "preprocessor_config.json", "tokenizer.json"]) await fs.writeFile(path.join(model, name), "ok");
  const sidecar = new PhoWhisperTranscriptionSidecar({ applicationHome: root, pythonPath: path.join(root, "python.exe"), modelDirectory: model });
  assert.equal(sidecar.supports("lecture.mp3"), true);
  assert.equal(sidecar.supports("lecture.mp4"), true);
  assert.equal(sidecar.supports("notes.pdf"), false);
  assert.equal(sidecar.activeCount(), 0);
  const availability = await sidecar.availability();
  assert.equal(availability.model_files_complete, true);
  assert.equal(availability.protocol_version, 1);
});
