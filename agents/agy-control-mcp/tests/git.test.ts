import assert from "node:assert/strict";
import test from "node:test";
import { applySnapshotPatch, matchesScope, normalizeScopePath, patchPaths, runTestCommand } from "../src/git.js";

test("directory glob scope does not match a sibling with the same prefix", () => {
  assert.equal(matchesScope("src/example.ts", ["src/**"]), true);
  assert.equal(matchesScope("src/nested/example.ts", ["src/**"]), true);
  assert.equal(matchesScope("src2/example.ts", ["src/**"]), false);
});

test("scope paths reject control characters", () => {
  assert.throws(() => normalizeScopePath("src/ok.ts\n../escape.ts"), /control characters/);
});

test("runTestCommand fails closed when test output exceeds its bound", async () => {
  const result = await runTestCommand(`${process.execPath} -e "process.stdout.write('x'.repeat(20000))"`, process.cwd(), 5, 1024);
  assert.equal(result.passed, false);
  assert.equal(result.exitCode, null);
});

test("runTestCommand cannot write the original project from an isolated workspace", async () => {
  if (process.platform.startsWith("win")) return;
  const fs = await import("node:fs/promises");
  const os = await import("node:os");
  const path = await import("node:path");
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "agy-test-sandbox-"));
  const original = path.join(root, "original");
  const isolated = path.join(root, "isolated");
  await fs.mkdir(original);
  await fs.mkdir(isolated);
  const escaped = path.join(original, "escaped.txt");
  const command = `${process.execPath} -e 'require("node:fs").writeFileSync(${JSON.stringify(escaped)}, "must not write")'`;
  const result = await runTestCommand(command, isolated, 5, 1024);
  assert.equal(result.passed, false);
  await assert.rejects(() => fs.stat(escaped), /ENOENT/);
});

test("patch path validation rejects traversal, sensitive metadata, and duplicate diff blocks", () => {
  assert.deepEqual(patchPaths(`diff --git "a/src/hello world.ts" "b/src/hello world.ts"\n--- "a/src/hello world.ts"\n+++ "b/src/hello world.ts"\n@@ -1 +1 @@\n-old\n+new\n`), ["src/hello world.ts"]);
  for (const header of [
    "diff --git a/../outside b/../outside",
    "diff --git a/.git/config b/.git/config",
    "diff --git a/.aws/credentials b/.aws/credentials",
    "diff --git a//tmp/out b//tmp/out",
  ]) assert.throws(() => patchPaths(`${header}\n--- /dev/null\n+++ b/../outside\n`), /unsafe|duplicate/);
  assert.throws(() => patchPaths("diff --git a/safe.txt b/safe.txt\n--- /dev/null\n+++ b/../outside\n@@ -0,0 +1 @@\n+x\n"), /unsafe|does not match/);
  const one = "diff --git a/file.txt b/file.txt\n--- a/file.txt\n+++ b/file.txt\n@@ -1 +1 @@\n-a\n+b\n";
  assert.throws(() => patchPaths(`${one}${one}`), /duplicate path/);
});

test("applySnapshotPatch applies modifications, additions, and deletions to a non-Git directory without creating .git", async () => {
  const fs = await import("node:fs/promises");
  const os = await import("node:os");
  const path = await import("node:path");
  const { applySnapshotPatch } = await import("../src/git.js");

  const dir = await fs.mkdtemp(path.join(os.tmpdir(), "git-test-snap-"));
  await fs.writeFile(path.join(dir, "file1.txt"), "hello\n");
  await fs.mkdir(path.join(dir, "nested"), { recursive: true });
  await fs.writeFile(path.join(dir, "nested", "file2.txt"), "world\n");

  const patch = `diff --git a/file1.txt b/file1.txt
index 0000000..1111111 100644
--- a/file1.txt
+++ b/file1.txt
@@ -1 +1 @@
-hello
+hello modified
diff --git a/nested/file2.txt b/nested/file2.txt
deleted file mode 100644
index 0000000..0000000
--- a/nested/file2.txt
+++ /dev/null
@@ -1 +0,0 @@
-world
diff --git a/newdir/file3.txt b/newdir/file3.txt
new file mode 100644
index 0000000..2222222
--- /dev/null
+++ b/newdir/file3.txt
@@ -0,0 +1 @@
+new file content
`;

  await applySnapshotPatch(dir, patch);

  assert.equal(await fs.readFile(path.join(dir, "file1.txt"), "utf8"), "hello modified\n");
  await assert.rejects(() => fs.stat(path.join(dir, "nested", "file2.txt")), /ENOENT/);
  assert.equal(await fs.readFile(path.join(dir, "newdir", "file3.txt"), "utf8"), "new file content\n");

  // Confirm no .git was created
  await assert.rejects(() => fs.stat(path.join(dir, ".git")), /ENOENT/);
});

test("applySnapshotPatch rejects invalid patch without touching existing files", async () => {
  const fs = await import("node:fs/promises");
  const os = await import("node:os");
  const path = await import("node:path");
  const { applySnapshotPatch } = await import("../src/git.js");

  const dir = await fs.mkdtemp(path.join(os.tmpdir(), "git-test-snap-invalid-"));
  await fs.writeFile(path.join(dir, "file1.txt"), "hello original\n");

  const badPatch = `diff --git a/file1.txt b/file1.txt
index 0000000..1111111 100644
--- a/file1.txt
+++ b/file1.txt
@@ -1 +1 @@
-mismatched content
+hello modified
`;

  await assert.rejects(() => applySnapshotPatch(dir, badPatch), /Git command failed/);
  assert.equal(await fs.readFile(path.join(dir, "file1.txt"), "utf8"), "hello original\n");
});

test("applySnapshotPatch rejects symlinked parents and sensitive paths before mutation", async () => {
  const fs = await import("node:fs/promises");
  const os = await import("node:os");
  const path = await import("node:path");
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), "git-test-snap-boundary-"));
  const external = await fs.mkdtemp(path.join(os.tmpdir(), "git-test-snap-external-"));
  await fs.symlink(external, path.join(dir, "escape"));
  const patch = `diff --git a/escape/out.txt b/escape/out.txt
new file mode 100644
--- /dev/null
+++ b/escape/out.txt
@@ -0,0 +1 @@
+must not escape
`;
  await assert.rejects(() => applySnapshotPatch(dir, patch), /unsafe|parent/);
  await assert.rejects(() => fs.stat(path.join(external, "out.txt")), /ENOENT/);
  const secretPatch = `diff --git a/.aws/credentials b/.aws/credentials
new file mode 100644
--- /dev/null
+++ b/.aws/credentials
@@ -0,0 +1 @@
+secret
`;
  await assert.rejects(() => applySnapshotPatch(dir, secretPatch), /unsafe/);
});

test("applySnapshotPatch rejects symlink and submodule modes before mutation", async () => {
  const fs = await import("node:fs/promises");
  const os = await import("node:os");
  const path = await import("node:path");
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), "git-test-snap-modes-"));
  for (const mode of ["120000", "160000"]) {
    const patch = `diff --git a/mode-${mode} b/mode-${mode}\nnew file mode ${mode}\n--- /dev/null\n+++ b/mode-${mode}\n@@ -0,0 +1 @@\n+unsafe\n`;
    await assert.rejects(() => applySnapshotPatch(dir, patch), /symlinks or submodules/);
    await assert.rejects(() => fs.stat(path.join(dir, `mode-${mode}`)), /ENOENT/);
  }
});

test("applySnapshotPatch preflights every file before changing any file", async () => {
  const fs = await import("node:fs/promises");
  const os = await import("node:os");
  const path = await import("node:path");
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), "git-test-snap-atomic-"));
  await fs.writeFile(path.join(dir, "first.txt"), "first\n");
  const patch = `diff --git a/first.txt b/first.txt
--- a/first.txt
+++ b/first.txt
@@ -1 +1 @@
-first
+changed
diff --git a/missing.txt b/missing.txt
--- a/missing.txt
+++ b/missing.txt
@@ -1 +1 @@
-missing
+still missing
`;
  await assert.rejects(() => applySnapshotPatch(dir, patch), /Git command failed/);
  assert.equal(await fs.readFile(path.join(dir, "first.txt"), "utf8"), "first\n");
});
