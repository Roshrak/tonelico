import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";
import test from "node:test";

/**
 * The parity manifest is only a checklist when its Node side points at REAL regressions.
 * This test enforces that every mapping references an actual `parity:PXX` regression in the
 * Study parity suite — a manifest full of names with no backing tests now fails here.
 */
test("Study Herd parity manifest maps every legacy Python regression to a real Node regression ID", async () => {
  const filename = path.resolve("resources", "study-herd", "study-parity-manifest.json");
  const manifest = JSON.parse(await fs.readFile(filename, "utf8")) as {
    mappings: Array<{ python_test: string; node_contract: string; node_regression_id?: string }>;
  };

  assert.equal(manifest.mappings.length, 40);
  assert.equal(new Set(manifest.mappings.map((mapping) => mapping.python_test)).size, 40);
  assert.ok(manifest.mappings.every((mapping) => mapping.python_test.startsWith("test_") && mapping.node_contract.length > 0));

  // Every mapping must carry a node_regression_id and that ID must exist as a tagged regression.
  const paritySuitePath = path.resolve("tests", "studyParity.test.ts");
  const suiteSource = await fs.readFile(paritySuitePath, "utf8");
  const declaredIds = new Set([...suiteSource.matchAll(/parity:(P\d{2})/g)].map((match) => match[1]));

  for (const mapping of manifest.mappings) {
    const id = mapping.node_regression_id;
    assert.ok(id && /^P\d{2}$/.test(id), `${mapping.python_test} must declare a node_regression_id`);
    assert.ok(declaredIds.has(id), `${mapping.python_test} points at ${id}, which has no parity:P${id.slice(1)} regression in ${path.basename(paritySuitePath)}`);
  }

  // The suite itself must stay a real 40+ regression block, not a stub.
  assert.ok(declaredIds.size >= 40, `expected at least 40 distinct parity regressions, found ${declaredIds.size}`);
});
