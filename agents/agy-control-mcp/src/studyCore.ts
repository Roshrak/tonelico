import { createHash } from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { extractText } from "unpdf";
import { parse as parseYaml } from "yaml";

export interface ManifestSource {
  id?: unknown;
  kind?: unknown;
  path?: unknown;
  include?: unknown;
  reason?: unknown;
}

export type SourceStatus = "indexed" | "missing" | "unreadable";

export interface SourceHeading { line: number; level: number; text: string }

export interface SourceRecord {
  id: string;
  kind: string;
  path: string;
  status: SourceStatus;
  size_bytes?: number;
  sha256?: string;
  line_count?: number;
  headings?: SourceHeading[];
  preview?: string;
  page_count?: number;
  page_previews?: string[];
  parser_warnings?: string[];
  error?: string;
}

export interface SourceIndex {
  generated_at: string;
  subject: string;
  manifest: string;
  included_sources: SourceRecord[];
  excluded_sources: Array<{ id: string; kind: string; path: string | null; reason: string }>;
}

export function normalizeWhitespace(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

export function firstNonEmptyLine(text: string, maxLength = 240): string {
  return text.split(/\r?\n/).map((line) => normalizeWhitespace(line)).find(Boolean)?.slice(0, maxLength) || "";
}

export function loadManifestSync(value: unknown, manifestPath = "<memory>"): { subject: string; sources: Record<string, unknown>[] } {
  if (!value || typeof value !== "object") throw new Error("Manifest must be a YAML mapping");
  const manifest = value as { subject?: unknown; sources?: unknown };
  if (typeof manifest.subject !== "string" || !manifest.subject.trim()) throw new Error("Manifest must contain a non-empty subject");
  if (!Array.isArray(manifest.sources) || !manifest.sources.length) throw new Error("Manifest must contain at least one source");
  const ids = new Set<string>();
  const sources: Record<string, unknown>[] = [];
  for (const item of manifest.sources) {
    if (!item || typeof item !== "object") throw new Error("Every source must be a mapping");
    const source = item as Record<string, unknown>;
    if (typeof source.id !== "string" || !source.id.trim()) throw new Error("Every source must have a non-empty id");
    if (ids.has(source.id)) throw new Error(`Duplicate source id: ${source.id}`);
    ids.add(source.id);
    if (source.include !== false && typeof source.path !== "string") throw new Error(`Included source ${source.id} needs a path`);
    sources.push(source);
  }
  void manifestPath;
  return { subject: manifest.subject, sources };
}

export async function loadManifest(manifestPath: string): Promise<{ subject: string; sources: Record<string, unknown>[] }> {
  const raw = parseYaml(await fs.readFile(manifestPath, "utf8"));
  return loadManifestSync(raw, manifestPath);
}

async function hashFile(filePath: string): Promise<{ hash: string; size: number }> {
  const content = await fs.readFile(filePath);
  return { hash: createHash("sha256").update(content).digest("hex"), size: content.byteLength };
}

function markdownMetadata(text: string): Pick<SourceRecord, "line_count" | "headings" | "preview"> {
  const lines = text.split(/\r?\n/);
  const headings = lines.flatMap((line, index): SourceHeading[] => {
    const match = /^(#{1,6})\s+(.+?)\s*$/.exec(line);
    return match ? [{ line: index + 1, level: match[1].length, text: match[2] }] : [];
  });
  return { line_count: lines.length, headings, preview: firstNonEmptyLine(text) };
}

export async function indexSource(source: Record<string, unknown>): Promise<SourceRecord> {
  const filePath = String(source.path);
  const resolved = path.resolve(filePath);
  const record: SourceRecord = { id: String(source.id), kind: String(source.kind || "unclassified"), path: resolved, status: "indexed" };
  const stat = await fs.stat(resolved).catch(() => undefined);
  if (!stat?.isFile()) return { ...record, status: "missing" };
  const digest = await hashFile(resolved);
  record.size_bytes = digest.size;
  record.sha256 = digest.hash;
  try {
    if (resolved.toLowerCase().endsWith(".pdf")) {
      const parsed = await extractText(new Uint8Array(await fs.readFile(resolved)), { mergePages: false });
      const pages = Array.isArray(parsed.text) ? parsed.text : [String(parsed.text || "")];
      record.page_count = pages.length;
      record.page_previews = pages.map((page) => firstNonEmptyLine(page));
    } else if ([".md", ".markdown", ".txt"].includes(path.extname(resolved).toLowerCase())) {
      const text = (await fs.readFile(resolved, "utf8")).replace(/\r\n?/g, "\n");
      Object.assign(record, markdownMetadata(text));
    } else {
      record.preview = "Metadata only; this format is not parsed in V1.";
    }
  } catch (error) {
    record.status = "unreadable";
    record.error = `${error instanceof Error ? error.name : "Error"}: ${error instanceof Error ? error.message : String(error)}`;
  }
  return record;
}

export async function buildSourceIndex(manifestPath: string): Promise<SourceIndex> {
  const resolvedManifest = path.resolve(manifestPath);
  const manifest = await loadManifest(resolvedManifest);
  const included: SourceRecord[] = [];
  const excluded: SourceIndex["excluded_sources"] = [];
  for (const source of manifest.sources) {
    if (source.include === false) {
      excluded.push({
        id: String(source.id), kind: String(source.kind || "unclassified"),
        path: typeof source.path === "string" ? source.path : null,
        reason: String(source.reason || "Excluded by manifest"),
      });
    } else included.push(await indexSource(source));
  }
  return { generated_at: new Date().toISOString(), subject: manifest.subject, manifest: resolvedManifest, included_sources: included, excluded_sources: excluded };
}

export function summarizeSourceIndex(index: SourceIndex): Record<string, unknown> {
  const statuses: Record<string, number> = {};
  let parserWarningCount = 0;
  for (const source of index.included_sources) {
    statuses[source.status] = (statuses[source.status] || 0) + 1;
    parserWarningCount += source.parser_warnings?.length || 0;
  }
  return { subject: index.subject, included_count: index.included_sources.length, excluded_count: index.excluded_sources.length, statuses, parser_warning_count: parserWarningCount };
}

export class ScopeError extends Error {}

function findSource(index: SourceIndex | { included_sources: SourceRecord[] }, sourceId: string): SourceRecord {
  const source = index.included_sources.find((item) => item.id === sourceId);
  if (!source) throw new ScopeError(`Source ID not found in index: ${sourceId}`);
  return source;
}

export interface LegacyScopeContract {
  created_at: string;
  source_id: string;
  source_path: string;
  source_sha256: string;
  page_start: number;
  page_end: number;
  page_count: number;
  first_page_preview: string;
  last_page_preview: string;
  topics: string[];
  forbidden_topics: string[];
}

export function buildScope(index: SourceIndex | { included_sources: SourceRecord[] }, sourceId: string, pageStart: number, pageEnd: number, topics: string[] = [], forbiddenTopics: string[] = []): LegacyScopeContract {
  const source = findSource(index, sourceId);
  if (source.status !== "indexed") throw new ScopeError(`Source ${sourceId} is ${source.status}, not indexed`);
  if (!Number.isInteger(source.page_count)) throw new ScopeError(`Source ${sourceId} has no PDF page count`);
  if (!Number.isInteger(pageStart) || !Number.isInteger(pageEnd) || pageStart < 1 || pageEnd < pageStart || pageEnd > source.page_count!) {
    throw new ScopeError(`Invalid page range ${pageStart}:${pageEnd}; source has ${source.page_count}`);
  }
  if (!source.sha256) throw new ScopeError(`Source ${sourceId} has no content hash`);
  const previews = source.page_previews || [];
  return {
    created_at: new Date().toISOString(), source_id: sourceId, source_path: source.path, source_sha256: source.sha256,
    page_start: pageStart, page_end: pageEnd, page_count: source.page_count!,
    first_page_preview: previews[pageStart - 1] || "", last_page_preview: previews[pageEnd - 1] || "",
    topics, forbidden_topics: forbiddenTopics,
  };
}

export function validateScopeContract(scope: Record<string, unknown>, index: SourceIndex | { included_sources: SourceRecord[] }): string[] {
  const required = ["source_id", "source_sha256", "page_start", "page_end", "page_count"];
  const missing = required.filter((field) => !(field in scope));
  if (missing.length) return [`Scope missing required field(s): ${missing.sort().join(", ")}`];
  let source: SourceRecord;
  try { source = findSource(index, String(scope.source_id)); }
  catch (error) { return [error instanceof Error ? error.message : String(error)]; }
  const violations: string[] = [];
  if (source.status !== "indexed") violations.push(`Source status is ${source.status}`);
  if (scope.page_count !== source.page_count) violations.push("Scope page count does not match the current source index");
  if (scope.source_sha256 !== source.sha256) violations.push("Scope source hash does not match the current source index");
  const start = scope.page_start;
  const end = scope.page_end;
  if (!Number.isInteger(start) || !Number.isInteger(end)) violations.push("Scope pages must be integers");
  else if (!Number.isInteger(source.page_count) || Number(start) < 1 || Number(end) < Number(start) || Number(end) > Number(source.page_count)) violations.push("Scope page range is invalid for the current source");
  return violations;
}

export function validateDraftTopics(scope: { forbidden_topics?: unknown }, draft: string): string[] {
  const folded = draft.toLowerCase();
  return Array.isArray(scope.forbidden_topics)
    ? scope.forbidden_topics.filter((topic): topic is string => typeof topic === "string").filter((topic) => folded.includes(topic.toLowerCase())).map((topic) => `Draft mentions forbidden topic: ${topic}`)
    : [];
}
