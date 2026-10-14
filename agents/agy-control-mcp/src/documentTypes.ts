export type DocumentProfile = "general" | "study" | "clinical_record";
export type DataPolicy = "standard" | "local_only";
export type DocumentRole =
  | "ocr-cleanup"
  | "transcript-cleanup"
  | "locator-map"
  | "table-normalize"
  | "field-extract"
  | "exam-transcribe"
  | "cross-source-align"
  | "contradiction-map"
  | "coverage-check";

export type DocumentConfidence = "high" | "medium" | "low";
export type SourceAuthority = "exam_axis" | "lecture_emphasis" | "prerequisite" | "recurrence_only" | "derived_reference" | "general";

export interface SourceLocator {
  source_id: string;
  source_sha256: string;
  page?: number;
  slide?: number;
  section?: string;
  sheet?: string;
  cell_range?: string;
  line_start?: number;
  line_end?: number;
  start_ms?: number;
  end_ms?: number;
  bbox?: [number, number, number, number];
  /** Numeric confidence for the positional locator itself (0..1); absent when not derivable. */
  locator_confidence?: number;
  /** Finer provenance classification such as ocr_line, ocr_block, speaker_notes, table_row. */
  element_subtype?: string;
}

export interface EvidenceItem {
  id: string;
  text: string;
  locator: SourceLocator;
  confidence: DocumentConfidence;
  source_kind: string;
  authority?: SourceAuthority;
  extraction_method: string;
  score?: number;
  estimated_tokens: number;
  lexical_rank?: number;
  dense_rank?: number;
}

export interface EvidenceBundleV1 {
  schema_version: "1";
  bundle_id?: string;
  collection_id: string;
  collection_revision: string;
  scope_id?: string;
  scope_sha256?: string;
  scope_key?: string;
  retrieval_mode?: "semantic" | "ordered_scope" | "cross_source";
  query: string;
  items: EvidenceItem[];
  coverage: {
    expected?: number;
    covered: number;
    missing: string[];
    kind?: "source";
    requested_source_ids?: string[];
    covered_source_ids?: string[];
  };
  uncertainties: string[];
  estimated_tokens: number;
}

export interface ParsedElement {
  ordinal: number;
  element_type: "page" | "section" | "slide" | "sheet" | "table" | "transcript" | "text";
  text: string;
  page?: number;
  slide?: number;
  section?: string;
  sheet?: string;
  cell_range?: string;
  line_start?: number;
  line_end?: number;
  start_ms?: number;
  end_ms?: number;
  bbox?: [number, number, number, number];
  locator_confidence?: number;
  element_subtype?: string;
  confidence: DocumentConfidence;
}

export interface ParsedDocument {
  parser_version: string;
  extraction_method: string;
  elements: ParsedElement[];
  warnings: string[];
}

export interface DocumentSourceRecord {
  source_id: string;
  collection_id: string;
  path: string;
  sha256: string;
  size_bytes: number;
  status: "indexed" | "unsupported" | "unreadable";
  source_kind: string;
  parser_version: string;
  extraction_method: string;
  warnings: string[];
}

export interface ScopeSelector {
  source_id?: string;
  page_start?: number;
  page_end?: number;
  slides?: [number, number];
  sheets?: string[];
  sections?: string[];
  time_range_ms?: [number, number];
}

export interface ScopeContract {
  scope_id: string;
  collection_id: string;
  collection_revision: string;
  profile: DocumentProfile;
  selectors: ScopeSelector[];
  source_ids: string[];
  source_hashes: Record<string, string>;
  forbidden_topics: string[];
  parser_version: string;
  chunking_version: string;
  locator_schema_version: string;
  scope_key?: string;
  scope_sha256: string;
  created_at: string;
}

export type DocumentRunState =
  | "queued"
  | "running"
  | "ready_for_commander"
  | "partial"
  | "blocked"
  | "failed"
  | "cancelled"
  | "interrupted"
  | "discarded";
