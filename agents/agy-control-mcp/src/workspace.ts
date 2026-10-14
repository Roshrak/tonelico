import { createHash } from "node:crypto";
import { constants as fsConstants } from "node:fs";
import fs, { type FileHandle } from "node:fs/promises";
import path from "node:path";
import { currentHead } from "./git.js";
import { execCommand } from "./processUtils.js";

export interface SnapshotFile {
  sha256: string;
  size: number;
  mode: number;
}

export interface SnapshotBaseline {
  files: Record<string, SnapshotFile>;
  directories: string[];
  fingerprint: string;
  base_commit: string;
}

const MAX_FILES = 20_000;
const MAX_BYTES = 512 * 1024 * 1024;
const MAX_DEPTH = 128;

const EXCLUDED_DIR_NAMES = new Set([
  ".git",
  ".ssh",
  ".aws",
  ".gnupg",
  "node_modules",
  "dist",
  "dist-test",
  "build",
  "coverage",
  ".cache",
  ".next",
  "target",
]);

function digest(value: string | Buffer): string {
  return createHash("sha256").update(value).digest("hex");
}

async function boundedFileDigest(filePath: string): Promise<{ sha256: string; size: number; mode: number }> {
  const noFollow = fsConstants.O_NOFOLLOW || 0;
  const handle = await fs.open(filePath, fsConstants.O_RDONLY | noFollow);
  try {
    const stats = await handle.stat();
    if (!stats.isFile() || stats.nlink > 1) throw new Error("Snapshot baseline target is not a safe regular file");
    const hash = createHash("sha256");
    let size = 0;
    for await (const chunk of handle.createReadStream({ autoClose: false, highWaterMark: 1024 * 1024 })) {
      const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
      size += buffer.byteLength;
      if (size > MAX_BYTES) throw new Error(`Snapshot baseline file exceeds the ${MAX_BYTES} byte limit`);
      hash.update(buffer);
    }
    return { sha256: hash.digest("hex"), size, mode: stats.mode & 0o777 };
  } finally {
    await handle.close();
  }
}

export function isExcludedFromSnapshot(relativePath: string): boolean {
  const normalized = relativePath.replaceAll("\\", "/").replace(/^\.\//, "").trim();
  const segments = normalized.split("/").filter(Boolean);
  if (segments.length === 0) return false;

  for (let i = 0; i < segments.length; i++) {
    const segment = segments[i];
    const isLast = i === segments.length - 1;

    if (EXCLUDED_DIR_NAMES.has(segment.toLowerCase())) {
      return true;
    }

    if (/^\.env(?:\..+)?$/i.test(segment)) {
      return true;
    }

    if (/^secrets?(?:[._-].*)?$/i.test(segment)) {
      return true;
    }

    if (/^credentials?(?:[._-].*)?$/i.test(segment)) {
      return true;
    }

    if (isLast) {
      if (/^id_(?:rsa|ed25519|dsa|ecdsa)(?:\.pub)?$/i.test(segment)) {
        return true;
      }
      if (/\.(?:pem|key|pfx|p12)$/i.test(segment)) {
        return true;
      }
    }
  }

  return false;
}

export function canonicalManifest(files: Record<string, SnapshotFile>, directories: string[] = []): string {
  const sortedFiles = Object.fromEntries(Object.entries(files).sort(([left], [right]) => left.localeCompare(right)));
  return JSON.stringify({ directories: [...directories].sort(), files: sortedFiles });
}

export function normalizeSnapshotPath(relativePath: string): string {
  const normalized = relativePath.replaceAll("\\", "/").trim();
  if (/[\u0000-\u001f\u007f]/.test(normalized)) {
    throw new Error(`Snapshot patch path contains control characters: ${relativePath}`);
  }
  if (
    !normalized ||
    normalized === "." ||
    normalized !== path.posix.normalize(normalized) ||
    path.posix.isAbsolute(normalized) ||
    /^[A-Za-z]:\//.test(normalized) ||
    normalized.split("/").includes("..") ||
    normalized.split("/").includes(".") ||
    isExcludedFromSnapshot(normalized)
  ) {
    throw new Error(`Snapshot patch path is unsafe: ${relativePath}`);
  }
  return normalized;
}

export async function assertSafeParentChain(sourceRoot: string, relativePath: string): Promise<void> {
  let current = sourceRoot;
  const segments = path.posix.dirname(relativePath).split("/");
  for (const segment of segments) {
    if (segment === "." || segment === "") continue;
    current = path.join(current, segment);
    const stats = await fs.lstat(current).catch((error: NodeJS.ErrnoException) => {
      if (error.code === "ENOENT") return undefined;
      throw error;
    });
    if (!stats) return;
    if (!stats.isDirectory() || stats.isSymbolicLink()) throw new Error(`Snapshot apply refused because a target parent is unsafe: ${relativePath}`);
  }
}

function isWithin(candidate: string, root: string): boolean {
  const relative = path.relative(root, candidate);
  return relative === "" || (!relative.startsWith("..") && !path.isAbsolute(relative));
}

async function assertSourcePath(sourceRoot: string, sourcePath: string, relativePath: string): Promise<void> {
  const resolved = await fs.realpath(sourcePath);
  if (!isWithin(resolved, sourceRoot)) throw new Error(`Snapshot source path escapes the source workspace: ${relativePath}`);
}

interface SnapshotCopy {
  files: Record<string, SnapshotFile>;
  directories: string[];
}

async function copyDirectory(sourceRoot: string, destinationRoot: string): Promise<SnapshotCopy> {
  const files: Record<string, SnapshotFile> = {};
  const directories = new Set<string>();
  let totalBytes = 0;

  const copy = async (sourceDirectory: string, relativeDirectory: string): Promise<void> => {
    await assertSourcePath(sourceRoot, sourceDirectory, relativeDirectory || ".");
    const entries = await fs.readdir(sourceDirectory, { withFileTypes: true });
    entries.sort((left, right) => left.name.localeCompare(right.name));
    for (const entry of entries) {
      const relativePath = relativeDirectory ? path.posix.join(relativeDirectory, entry.name) : entry.name;
      if (isExcludedFromSnapshot(relativePath)) continue;
      const sourcePath = path.join(sourceDirectory, entry.name);
      const destinationPath = path.join(destinationRoot, relativePath);
      const stats = await fs.lstat(sourcePath);
      if (stats.isSymbolicLink()) throw new Error(`Snapshot mode refuses symlinks: ${relativePath}`);
      if (stats.isDirectory()) {
        if (relativePath.split("/").length > MAX_DEPTH) throw new Error(`Snapshot mode exceeds the ${MAX_DEPTH} directory depth limit`);
        await assertSourcePath(sourceRoot, sourcePath, relativePath);
        directories.add(relativePath);
        await fs.mkdir(destinationPath, { recursive: true, mode: 0o700 });
        await copy(sourcePath, relativePath);
        continue;
      }
      if (!stats.isFile()) throw new Error(`Snapshot mode refuses non-regular files: ${relativePath}`);
      if (stats.nlink > 1) throw new Error(`Snapshot mode refuses hard-linked files: ${relativePath}`);
      if (Object.keys(files).length >= MAX_FILES) throw new Error(`Snapshot mode exceeds the ${MAX_FILES} file limit`);
      await fs.mkdir(path.dirname(destinationPath), { recursive: true, mode: 0o700 });
      await assertSourcePath(sourceRoot, sourcePath, relativePath);
      const noFollow = (fsConstants.O_NOFOLLOW || 0);
      const handle = await fs.open(sourcePath, fsConstants.O_RDONLY | noFollow);
      let destinationHandle: FileHandle | undefined;
      let copiedBytes = 0;
      const hash = createHash("sha256");
      try {
        const openedStats = await handle.stat();
        if (!openedStats.isFile()) throw new Error(`Snapshot mode refuses a file replaced by a non-regular file: ${relativePath}`);
        if (openedStats.nlink > 1) throw new Error(`Snapshot mode refuses a file replaced by a hard link: ${relativePath}`);
        destinationHandle = await fs.open(destinationPath, fsConstants.O_WRONLY | fsConstants.O_CREAT | fsConstants.O_EXCL | noFollow, openedStats.mode & 0o600);
        for await (const chunk of handle.createReadStream({ autoClose: false, highWaterMark: 1024 * 1024 })) {
          const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
          copiedBytes += buffer.byteLength;
          totalBytes += buffer.byteLength;
          if (totalBytes > MAX_BYTES) throw new Error(`Snapshot mode exceeds the ${MAX_BYTES} byte limit`);
          hash.update(buffer);
          await destinationHandle.write(buffer);
        }
        await destinationHandle.chmod(openedStats.mode & 0o700);
        files[relativePath] = { sha256: hash.digest("hex"), size: copiedBytes, mode: openedStats.mode & 0o777 };
      } finally {
        await destinationHandle?.close().catch(() => undefined);
        await handle.close();
        if (!files[relativePath]) await fs.unlink(destinationPath).catch(() => undefined);
      }
    }
  };

  await copy(sourceRoot, "");
  return { files, directories: [...directories].sort() };
}

export async function createSnapshotWorkspace(sourceRoot: string, destinationRoot: string): Promise<SnapshotBaseline> {
  const source = await fs.realpath(sourceRoot);
  const requestedDestination = path.resolve(destinationRoot);
  if (requestedDestination === source || requestedDestination.startsWith(`${source}${path.sep}`)) throw new Error("Snapshot destination must be outside the source workspace");
  if (source === requestedDestination || source.startsWith(`${requestedDestination}${path.sep}`)) throw new Error("Snapshot destination must not contain the source workspace");
  const sourceStats = await fs.lstat(source);
  if (!sourceStats.isDirectory()) throw new Error("Snapshot source must be a directory");
  await fs.mkdir(path.dirname(requestedDestination), { recursive: true, mode: 0o700 });
  const destinationParent = await fs.realpath(path.dirname(requestedDestination));
  const existingDestination = await fs.lstat(requestedDestination).catch((error: NodeJS.ErrnoException) => {
    if (error.code === "ENOENT") return undefined;
    throw error;
  });
  if (existingDestination?.isSymbolicLink()) throw new Error("Snapshot destination must not be a symlink");
  if (existingDestination) throw new Error("Snapshot destination must not already exist");
  const destination = path.join(destinationParent, path.basename(requestedDestination));
  if (destination === source || destination.startsWith(`${source}${path.sep}`)) throw new Error("Snapshot destination must be outside the source workspace");
  if (source === destination || source.startsWith(`${destination}${path.sep}`)) throw new Error("Snapshot destination must not contain the source workspace");
  await fs.mkdir(destination, { mode: 0o700 });
  const copied = await copyDirectory(source, destination);
  if (!Object.keys(copied.files).length) throw new Error("Snapshot mode found no safe regular files in the workspace");
  await execCommand("git", ["init", "-q"], { cwd: destination, timeout: 30_000 });
  await execCommand("git", ["add", "--all"], { cwd: destination, timeout: 30_000 });
  await execCommand("git", ["-c", "user.name=AGY Control Snapshot", "-c", "user.email=agy-control@localhost", "commit", "-qm", "AGY Control snapshot baseline"], { cwd: destination, timeout: 30_000 });
  return { files: copied.files, directories: copied.directories, fingerprint: digest(canonicalManifest(copied.files, copied.directories)), base_commit: await currentHead(destination) };
}

export async function assertSnapshotBaseline(sourceRoot: string, baseline: Record<string, SnapshotFile>, changedPaths: string[], baselineDirectories?: string[]): Promise<void> {
  const source = await fs.realpath(sourceRoot);
  for (const relativePath of changedPaths) {
    const normalizedPath = normalizeSnapshotPath(relativePath);
    const expected = baseline[normalizedPath];
    if (baselineDirectories) {
      const parentSegments = normalizedPath.split("/").slice(0, -1);
      for (let index = 1; index <= parentSegments.length; index += 1) {
        const parentPath = parentSegments.slice(0, index).join("/");
        const parent = await fs.lstat(path.join(source, ...parentPath.split("/"))).catch((error: NodeJS.ErrnoException) => {
          if (error.code === "ENOENT") return undefined;
          throw error;
        });
        const existed = baselineDirectories.includes(parentPath);
        if (existed && (!parent || !parent.isDirectory() || parent.isSymbolicLink())) throw new Error(`Snapshot apply refused because the original directory changed: ${parentPath}`);
        if (!existed && parent) throw new Error(`Snapshot apply refused because a new target parent already exists: ${parentPath}`);
      }
    }
    await assertSafeParentChain(source, normalizedPath);
    const sourcePath = path.join(source, ...normalizedPath.split("/"));
    const stats = await fs.lstat(sourcePath).catch((error: NodeJS.ErrnoException) => {
      if (error.code === "ENOENT") return undefined;
      throw error;
    });
    if (!expected) {
      if (stats) throw new Error(`Snapshot apply refused because a new target path already exists: ${normalizedPath}`);
      continue;
    }
    if (!stats || !stats.isFile() || stats.isSymbolicLink() || stats.nlink > 1) throw new Error(`Snapshot apply refused because the original file changed type: ${normalizedPath}`);
    const actual = await boundedFileDigest(sourcePath);
    if (actual.sha256 !== expected.sha256 || actual.size !== expected.size || actual.mode !== expected.mode) throw new Error(`Snapshot apply refused because the original file changed: ${normalizedPath}`);
  }
}
