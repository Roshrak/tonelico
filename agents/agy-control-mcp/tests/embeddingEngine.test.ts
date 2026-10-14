import assert from "node:assert/strict";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { EMBEDDING_DIMENSIONS, EMBEDDING_MAX_TOKENS, EmbeddingEngine } from "../src/embeddingEngine.js";

function norm(vector: Float32Array): number {
  return Math.sqrt(vector.reduce((total, value) => total + value * value, 0));
}

test("local E5 model verifies checksums and produces normalized batched Vietnamese vectors", async (context) => {
  const engine = new EmbeddingEngine();
  if (!engine.availability().enabled) {
    context.skip("local E5 model is intentionally optional and was not installed");
    return;
  }
  const passages = await engine.embedPassages(["Loét aphthous tái phát ở niêm mạc miệng.", "Tổn thương không liên quan Parkinson."]);
  const query = await engine.embedQuery("loét miệng tái phát");
  assert.equal(passages.length, 2);
  assert.equal(query.length, EMBEDDING_DIMENSIONS);
  assert.ok(passages.every((vector) => vector.length === EMBEDDING_DIMENSIONS));
  assert.ok(Math.abs(norm(query) - 1) < 0.0001);
  assert.ok(await engine.countTokens("một đoạn tiếng Việt ngắn") < EMBEDDING_MAX_TOKENS);
});

test("embedding engine fails closed when the local model is absent", async () => {
  const engine = new EmbeddingEngine(path.join(os.tmpdir(), "agy-control-missing-embedding-model"));
  const availability = engine.availability();
  assert.equal(availability.enabled, false);
  assert.deepEqual(await engine.embedPassages([]), []);
  await assert.rejects(() => engine.countTokens("test"), /Embedding model is incomplete/);
  await assert.rejects(() => engine.embedQuery("test"), /Embedding model is incomplete/);
});
