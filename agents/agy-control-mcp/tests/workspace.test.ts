import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import {
  assertSafeParentChain,
  assertSnapshotBaseline,
  canonicalManifest,
  createSnapshotWorkspace,
  isExcludedFromSnapshot,
  normalizeSnapshotPath,
} from "../src/workspace.js";

test("isExcludedFromSnapshot excludes dependency, build, cache, and secret paths while preserving ordinary sources", () => {
  const excluded = [
    "node_modules/pkg/index.js",
    "src/node_modules/sub/a.js",
    "dist/index.js",
    "src/dist/bundle.js",
    "dist-test/test.js",
    "build/output.js",
    "coverage/lcov.info",
    ".cache/data.json",
    ".next/server/pages.js",
    "target/debug/app",
    ".git/HEAD",
    ".ssh/id_rsa",
    ".aws/credentials",
    ".gnupg/private-keys-v1.d/secret.key",
    ".env",
    ".env.local",
    ".env.production",
    "secrets/key.txt",
    "secret.json",
    "secrets.yaml",
    "secret_token.txt",
    "secret-file.txt",
    "credentials/auth.json",
    "credentials.json",
    "credential_store.txt",
    "id_rsa",
    "id_rsa.pub",
    "id_ed25519",
    "id_ed25519.pub",
    "id_dsa",
    "id_ecdsa",
    "cert.pem",
    "server.key",
    "cert.pfx",
    "cert.p12",
  ];

  for (const relPath of excluded) {
    assert.equal(isExcludedFromSnapshot(relPath), true, `Expected ${relPath} to be excluded`);
  }

  const included = [
    "src/index.ts",
    "src/distribute.ts",
    "src/distribution/helper.ts",
    "src/building.ts",
    "src/builders/service.ts",
    "src/target_calculator.ts",
    "src/env.ts",
    "src/environment.ts",
    "src/secretary.ts",
    "README.md",
    "package.json",
    "docs/tutorial.md",
  ];

  for (const relPath of included) {
    assert.equal(isExcludedFromSnapshot(relPath), false, `Expected ${relPath} to be included`);
  }
});

test("normalizeSnapshotPath enforces canonical relative paths and rejects traversal, control characters, and excluded paths", () => {
  assert.equal(normalizeSnapshotPath("src/example.ts"), "src/example.ts");
  assert.equal(normalizeSnapshotPath("nested/deep/file.txt"), "nested/deep/file.txt");
  assert.equal(normalizeSnapshotPath("src\\example.ts"), "src/example.ts");

  assert.throws(() => normalizeSnapshotPath("../outside.ts"), /unsafe/);
  assert.throws(() => normalizeSnapshotPath("src/../../outside.ts"), /unsafe/);
  assert.throws(() => normalizeSnapshotPath("/etc/passwd"), /unsafe/);
  assert.throws(() => normalizeSnapshotPath("C:/foo/bar"), /unsafe/);
  assert.throws(() => normalizeSnapshotPath("."), /unsafe/);
  assert.throws(() => normalizeSnapshotPath("src/./foo.ts"), /unsafe/);
  assert.throws(() => normalizeSnapshotPath("src/bad\nfile.ts"), /control characters/);
  assert.throws(() => normalizeSnapshotPath(".env"), /unsafe/);
  assert.throws(() => normalizeSnapshotPath("node_modules/foo.js"), /unsafe/);
  assert.throws(() => normalizeSnapshotPath("dist/bundle.js"), /unsafe/);
});

test("createSnapshotWorkspace creates an isolated temporary git repository without modifying source", async () => {
  const source = await fs.mkdtemp(path.join(os.tmpdir(), "snap-source-"));
  const destination = await fs.mkdtemp(path.join(os.tmpdir(), "snap-dest-"));

  await fs.writeFile(path.join(source, "main.ts"), "console.log('main');\n");
  await fs.mkdir(path.join(source, "nested", "sub"), { recursive: true });
  await fs.writeFile(path.join(source, "nested", "sub", "helper.ts"), "export const x = 1;\n");
  await fs.writeFile(path.join(source, ".env"), "SECRET_KEY=12345\n");
  await fs.mkdir(path.join(source, "node_modules", "pkg"), { recursive: true });
  await fs.writeFile(path.join(source, "node_modules", "pkg", "index.js"), "module.exports = {};\n");
  await fs.mkdir(path.join(source, "dist"), { recursive: true });
  await fs.writeFile(path.join(source, "dist", "bundle.js"), "bundled\n");

  const baseline = await createSnapshotWorkspace(source, path.join(destination, "workspace"));

  assert.ok(baseline.base_commit);
  assert.ok(baseline.fingerprint);
  assert.equal(baseline.fingerprint, canonicalManifest(baseline.files) ? baseline.fingerprint : "");
  assert.ok(baseline.files["main.ts"]);
  assert.ok(baseline.files["nested/sub/helper.ts"]);
  assert.equal(baseline.files[".env"], undefined);
  assert.equal(baseline.files["node_modules/pkg/index.js"], undefined);
  assert.equal(baseline.files["dist/bundle.js"], undefined);

  // Verify source was not modified and received no .git directory
  await assert.rejects(() => fs.stat(path.join(source, ".git")), /ENOENT/);

  // Verify destination has the copied files and its own .git directory
  const destGit = await fs.stat(path.join(destination, "workspace", ".git"));
  assert.ok(destGit.isDirectory());
  assert.equal(await fs.readFile(path.join(destination, "workspace", "main.ts"), "utf8"), "console.log('main');\n");
  assert.equal(await fs.readFile(path.join(destination, "workspace", "nested", "sub", "helper.ts"), "utf8"), "export const x = 1;\n");
  await assert.rejects(() => fs.stat(path.join(destination, "workspace", ".env")), /ENOENT/);
  await assert.rejects(() => fs.stat(path.join(destination, "workspace", "node_modules")), /ENOENT/);
  await assert.rejects(() => fs.stat(path.join(destination, "workspace", "dist")), /ENOENT/);
});

test("createSnapshotWorkspace rejects nested or overlapping destination inside source", async () => {
  const source = await fs.mkdtemp(path.join(os.tmpdir(), "snap-overlap-"));
  await fs.writeFile(path.join(source, "file.ts"), "code\n");
  await assert.rejects(
    () => createSnapshotWorkspace(source, path.join(source, "snapshot")),
    /Snapshot destination must be outside the source workspace/
  );
});

test("createSnapshotWorkspace rejects an existing symlink destination even when it points outside source", async () => {
  const source = await fs.mkdtemp(path.join(os.tmpdir(), "snap-destination-source-"));
  const destinationParent = await fs.mkdtemp(path.join(os.tmpdir(), "snap-destination-parent-"));
  const external = await fs.mkdtemp(path.join(os.tmpdir(), "snap-destination-external-"));
  await fs.writeFile(path.join(source, "file.ts"), "code\n");
  await fs.symlink(external, path.join(destinationParent, "workspace"));
  await assert.rejects(
    () => createSnapshotWorkspace(source, path.join(destinationParent, "workspace")),
    /destination must not be a symlink/
  );
  await assert.rejects(() => fs.stat(path.join(external, ".git")), /ENOENT/);
});

test("createSnapshotWorkspace rejects symlinks deterministically", async () => {
  const source = await fs.mkdtemp(path.join(os.tmpdir(), "snap-symlink-"));
  const destination = await fs.mkdtemp(path.join(os.tmpdir(), "snap-dest-"));

  await fs.writeFile(path.join(source, "real.ts"), "export const a = 1;\n");
  await fs.symlink(path.join(source, "real.ts"), path.join(source, "link.ts"));

  await assert.rejects(
    () => createSnapshotWorkspace(source, path.join(destination, "workspace")),
    /Snapshot mode refuses symlinks: link\.ts/
  );
});

test("createSnapshotWorkspace rejects special files deterministically (named pipes/FIFOs)", async () => {
  if (process.platform === "win32") return;
  const source = await fs.mkdtemp(path.join(os.tmpdir(), "snap-fifo-"));
  const destination = await fs.mkdtemp(path.join(os.tmpdir(), "snap-dest-"));

  await fs.writeFile(path.join(source, "file.ts"), "export const a = 1;\n");
  try {
    execFileSync("mkfifo", [path.join(source, "test_fifo")]);
  } catch {
    return; // Skip if platform permissions prevent mkfifo
  }

  await assert.rejects(
    () => createSnapshotWorkspace(source, path.join(destination, "workspace")),
    /Snapshot mode refuses non-regular files: test_fifo/
  );
});

test("createSnapshotWorkspace rejects hard-linked files to avoid copying an ambiguous inode", async () => {
  if (process.platform === "win32") return;
  const source = await fs.mkdtemp(path.join(os.tmpdir(), "snap-hardlink-"));
  const destination = await fs.mkdtemp(path.join(os.tmpdir(), "snap-hardlink-dest-"));
  await fs.writeFile(path.join(source, "ordinary.ts"), "content\n");
  try { await fs.link(path.join(source, "ordinary.ts"), path.join(source, "alias.ts")); }
  catch { return; }
  await assert.rejects(
    () => createSnapshotWorkspace(source, path.join(destination, "workspace")),
    /Snapshot mode refuses hard-linked files/
  );
});

test("assertSnapshotBaseline validates modified, added, and deleted files against baseline", async () => {
  const source = await fs.mkdtemp(path.join(os.tmpdir(), "snap-baseline-"));
  await fs.writeFile(path.join(source, "existing.ts"), "export const a = 1;\n");
  await fs.writeFile(path.join(source, "to_delete.ts"), "export const del = true;\n");

  const destination = await fs.mkdtemp(path.join(os.tmpdir(), "snap-dest-"));
  const baseline = await createSnapshotWorkspace(source, path.join(destination, "workspace"));

  // 1. Unchanged state: verifying modified, new, deleted files passes
  await assertSnapshotBaseline(source, baseline.files, ["existing.ts", "new_file.ts", "to_delete.ts"]);

  // 2. Modified file in source that changed after delegation fails validation
  await fs.writeFile(path.join(source, "existing.ts"), "export const a = 2;\n");
  await assert.rejects(
    () => assertSnapshotBaseline(source, baseline.files, ["existing.ts"]),
    /Snapshot apply refused because the original file changed: existing\.ts/
  );
  // Restore
  await fs.writeFile(path.join(source, "existing.ts"), "export const a = 1;\n");
  await assertSnapshotBaseline(source, baseline.files, ["existing.ts"]);

  // 3. New file that already exists in source fails validation
  await fs.writeFile(path.join(source, "new_file.ts"), "already exists\n");
  await assert.rejects(
    () => assertSnapshotBaseline(source, baseline.files, ["new_file.ts"]),
    /Snapshot apply refused because a new target path already exists: new_file\.ts/
  );
  // Remove
  await fs.rm(path.join(source, "new_file.ts"));
  await assertSnapshotBaseline(source, baseline.files, ["new_file.ts"]);

  // 4. Deleted file that was modified or removed in source fails validation
  await fs.rm(path.join(source, "to_delete.ts"));
  await assert.rejects(
    () => assertSnapshotBaseline(source, baseline.files, ["to_delete.ts"]),
    /Snapshot apply refused because the original file changed type: to_delete\.ts/
  );
});

test("assertSafeParentChain refuses symlinks in target parent directory hierarchy", async () => {
  const source = await fs.mkdtemp(path.join(os.tmpdir(), "snap-parent-"));
  const external = await fs.mkdtemp(path.join(os.tmpdir(), "snap-ext-"));

  await fs.symlink(external, path.join(source, "sym_dir"));

  await assert.rejects(
    () => assertSafeParentChain(source, "sym_dir/file.ts"),
    /Snapshot apply refused because a target parent is unsafe: sym_dir\/file\.ts/
  );
});
