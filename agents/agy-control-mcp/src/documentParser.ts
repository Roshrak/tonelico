import fs from "node:fs/promises";
import { existsSync } from "node:fs";
import JSZip from "jszip";
import mammoth from "mammoth";
import path from "node:path";
import { extractTextItems, getDocumentProxy, renderPageAsImage } from "unpdf";
import type { ParsedDocument, ParsedElement } from "./documentTypes.js";

export const DOCUMENT_PARSER_VERSION = "light-structured-v5-block-bbox";
export const LOCATOR_SCHEMA_VERSION = "locator-schema-v3";
export const SUPPORTED_DOCUMENT_EXTENSIONS = new Set([".pdf", ".docx", ".pptx", ".xlsx", ".md", ".markdown", ".txt", ".bmp", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"]);
export const IMAGE_OCR_EXTENSIONS = new Set([".bmp", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"]);
export const OCR_BLOCK_CONFIDENCE_THRESHOLD = 70;

export type Aborter = AbortSignal | undefined;

function decodeXmlEntities(value: string): string {
  return value
    .replace(/&#x([0-9a-f]+);/gi, (_, code: string) => String.fromCodePoint(Number.parseInt(code, 16)))
    .replace(/&#(\d+);/g, (_, code: string) => String.fromCodePoint(Number.parseInt(code, 10)))
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, "\"")
    .replace(/&apos;/g, "'")
    .replace(/&amp;/g, "&");
}

function xmlTextMatches(xml: string, tag: string): string[] {
  return [...xml.matchAll(new RegExp(`<${tag}[^>]*>([\\s\\S]*?)</${tag}>`, "gu"))]
    .map((match) => decodeXmlEntities(match[1]?.replace(/<[^>]*>/g, "") || "").replace(/\s+/g, " ").trim())
    .filter(Boolean);
}

function normalizeText(text: string): string {
  return text.replace(/\r\n?/g, "\n").replace(/[ \t]+\n/g, "\n").replace(/\n{3,}/g, "\n\n").trim();
}

interface PdfTextItem { str: string; x: number; y: number; width: number; height: number }
interface PdfBlock { text: string; x: number; y: number; width: number; height: number }

/** Cluster PDF text items into reading-order blocks (two-column aware) with real per-block bounding boxes. */
export function layoutPdfBlocks(items: PdfTextItem[]): PdfBlock[] {
  const meaningful = items.filter((item) => item.str.trim());
  const rows = new Map<number, PdfTextItem[]>();
  for (const item of meaningful) {
    const key = Math.round(item.y / Math.max(item.height || 8, 8)) * Math.max(item.height || 8, 8);
    rows.set(key, [...rows.get(key) || [], item]);
  }
  // Split each visual row into horizontal segments so text sharing one baseline across a wide
  // gutter (two-column layouts) lands in separate lines instead of one merged pseudo-line.
  const materialized: Array<{ x: number; x2: number; y: number; height: number; text: string }> = [];
  for (const [key, rowItems] of rows) {
    const ordered = [...rowItems].sort((left, right) => left.x - right.x);
    const height = Math.max(...ordered.map((item) => item.height || 8));
    let segment: PdfTextItem[] = [];
    const flushSegment = (): void => {
      if (!segment.length) return;
      materialized.push({
        x: segment[0]!.x,
        x2: Math.max(...segment.map((item) => item.x + (item.width || 0))),
        y: ordered[0]!.y,
        height,
        text: segment.map((item) => item.str.trim()).filter(Boolean).join(" ").replace(/\s+/g, " ").trim(),
      });
      segment = [];
    };
    for (const item of ordered) {
      if (segment.length) {
        const previous = segment[segment.length - 1]!;
        const gap = item.x - (previous.x + (previous.width || 0));
        if (gap > Math.max(24, height * 2)) flushSegment();
      }
      segment.push(item);
    }
    flushSegment();
    void key;
  }
  const usable = materialized.filter((line) => line.text);
  if (!usable.length) return [];
  const minX = Math.min(...usable.map((line) => line.x));
  const maxX = Math.max(...usable.map((line) => line.x2));
  const midpoint = (minX + maxX) / 2;
  const left = usable.filter((line) => line.x < midpoint && line.x2 <= midpoint);
  const right = usable.filter((line) => !left.includes(line));
  const twoColumns = left.length >= 3 && right.length >= 3;
  const columns = twoColumns
    ? [left.sort((a, b) => b.y - a.y || a.x - b.x), right.sort((a, b) => b.y - a.y || a.x - b.x)]
    : [usable.sort((a, b) => b.y - a.y || a.x - b.x)];
  const blocks: PdfBlock[] = [];
  for (const column of columns) {
    let current: (typeof column)[number] | undefined;
    const flushCurrent = (): void => {
      if (!current) return;
      blocks.push({ text: normalizeText(current.text), x: current.x, y: current.y, width: current.x2 - current.x, height: current.height });
      current = undefined;
    };
    for (const line of column) {
      const verticalGap = current ? Math.abs(current.y - line.y) : Number.POSITIVE_INFINITY;
      const horizontalOverlap = current ? line.x < current.x2 && current.x < line.x2 : false;
      if (current && verticalGap <= Math.max(current.height, line.height) * 1.8 && horizontalOverlap) {
        current.text = `${current.text} ${line.text}`.trim();
        current.x = Math.min(current.x, line.x);
        current.x2 = Math.max(current.x2, line.x2);
        current.y = Math.max(current.y, line.y);
        current.height = Math.max(current.height, line.height);
      } else {
        flushCurrent();
        current = { ...line };
      }
    }
    flushCurrent();
  }
  return blocks.filter((block) => block.text);
}

async function parsePdf(buffer: Buffer, signal?: Aborter): Promise<ParsedDocument> {
  const pdf = await getDocumentProxy(new Uint8Array(buffer));
  const result = await extractTextItems(pdf);
  const elements: ParsedElement[] = [];
  let ordinal = 0;
  const warnings: string[] = [];
  for (const [index, items] of result.items.entries()) {
    signal?.throwIfAborted?.();
    const pageBlocks = layoutPdfBlocks(items as PdfTextItem[]);
    if (!pageBlocks.length && /^(1|true|yes)$/i.test(process.env.AGY_DOCUMENT_ENABLE_OCR || "")) {
      try {
        const image = Buffer.from(await renderPageAsImage(pdf, index + 1, { scale: 2 }));
        const parsed = await parseImageOcr(image);
        for (const element of parsed.elements) elements.push({ ...element, ordinal: ++ordinal, page: index + 1 });
        warnings.push(...parsed.warnings.map((warning) => `page_${index + 1}:${warning}`));
      } catch (error) {
        warnings.push(`page_${index + 1}:scanned_pdf_ocr_unavailable:${error instanceof Error ? error.message : String(error)}`);
      }
      continue;
    }
    if (!pageBlocks.length) {
      warnings.push(`page_${index + 1}:scanned_pdf_ocr_unavailable`);
      continue;
    }
    for (const block of pageBlocks) {
      ordinal += 1;
      elements.push({
        ordinal,
        element_type: "text",
        text: block.text,
        page: index + 1,
        // Real PDF-coordinate bounding box derived from actual text items — never a synthetic [0,0,1,1].
        bbox: [
          Math.round(block.x * 100) / 100,
          Math.round(block.y * 100) / 100,
          Math.round(block.width * 100) / 100,
          Math.round(block.height * 100) / 100,
        ],
        locator_confidence: 0.9,
        element_subtype: "pdf_block",
        confidence: "medium",
      });
    }
  }
  return { parser_version: DOCUMENT_PARSER_VERSION, extraction_method: "unpdf-layout-blocks", elements, warnings };
}

async function parseDocx(buffer: Buffer): Promise<ParsedDocument> {
  const zip = await JSZip.loadAsync(buffer);
  const documentXml = await zip.file("word/document.xml")?.async("string");
  if (!documentXml) throw new Error("DOCX is missing word/document.xml");
  const elements: ParsedElement[] = [];
  let ordinal = 0;
  const addParagraph = (xml: string, section: string, subtype?: string): void => {
    const text = normalizeText(xmlTextMatches(xml, "w:t").join(""));
    if (!text) return;
    ordinal += 1;
    const style = xml.match(/<w:pStyle[^>]*w:val="([^"]+)"/u)?.[1];
    elements.push({
      ordinal, element_type: "section", text,
      section: style ? `${section}/${style}` : section,
      element_subtype: subtype || (style ? `paragraph_style:${style}` : undefined),
      locator_confidence: 0.95, confidence: "high",
    });
  };
  const body = documentXml.match(/<w:body[^>]*>([\s\S]*?)<w:sectPr[\s\S]*?<\/w:body>/u)?.[1] || documentXml;
  let tableNumber = 0;
  for (const block of body.matchAll(/<(w:p|w:tbl)\b[^>]*>[\s\S]*?<\/\1>/gu)) {
    const tag = block[1];
    const xml = block[0];
    if (tag === "w:p") {
      addParagraph(xml, "body");
      continue;
    }
    tableNumber += 1;
    let rowNumber = 0;
    for (const row of xml.matchAll(/<w:tr\b[^>]*>([\s\S]*?)<\/w:tr>/gu)) {
      rowNumber += 1;
      const cells: string[] = [];
      for (const cell of row[1].matchAll(/<w:tc\b[^>]*>([\s\S]*?)<\/w:tc>/gu)) {
        const spanMatch = cell[1].match(/<w:gridSpan[^>]*w:val="(\d+)"/u);
        const continuation = /<w:vMerge\b[^>]*\/>|<w:vMerge[^>]*>\s*<\/w:vMerge>/u.test(cell[1]);
        const value = normalizeText(xmlTextMatches(cell[1], "w:t").join(""));
        const span = spanMatch ? Number(spanMatch[1]) : 1;
        cells.push(continuation ? `${value}[vmerge-cont]` : span > 1 ? `${value}[merged x${span}]` : value);
      }
      if (!cells.some(Boolean)) continue;
      ordinal += 1;
      const lastColumn = String.fromCharCode(64 + Math.min(26, cells.reduce((total, cell) => total + (Number(cell.match(/\[merged x(\d+)\]/)?.[1]) || 1), 0)));
      elements.push({ ordinal, element_type: "table", text: cells.join("\t"), section: `table:${tableNumber}`, cell_range: `Table${tableNumber}!A${rowNumber}:${lastColumn}${rowNumber}`, element_subtype: "table_row", locator_confidence: 0.95, confidence: "high" });
    }
  }
  for (const part of ["header", "footer"]) {
    const files = Object.keys(zip.files).filter((name) => new RegExp(`^word/${part}\\d+\\.xml$`, "u").test(name)).sort();
    for (const [index, filename] of files.entries()) {
      const xml = await zip.file(filename)?.async("string");
      if (xml) addParagraph(xml, `${part}:${index + 1}`, part);
    }
  }
  if (!elements.length) {
    const { value } = await mammoth.extractRawText({ buffer });
    if (normalizeText(value)) elements.push({ ordinal: 1, element_type: "text", text: normalizeText(value), section: "fallback", confidence: "medium" });
  }
  return { parser_version: DOCUMENT_PARSER_VERSION, extraction_method: "ooxml-docx-structure", elements, warnings: [] };
}

async function parsePptx(buffer: Buffer): Promise<ParsedDocument> {
  const zip = await JSZip.loadAsync(buffer);
  const slideFiles = Object.keys(zip.files).filter((name) => /^ppt\/slides\/slide\d+\.xml$/.test(name))
    .sort((left, right) => Number(left.match(/(\d+)/)?.[1] || 0) - Number(right.match(/(\d+)/)?.[1] || 0));
  const elements: ParsedElement[] = [];
  for (const [index, filename] of slideFiles.entries()) {
    const xml = await zip.file(filename)?.async("string");
    if (!xml) continue;
    const slideNumber = index + 1;
    const body = xmlTextMatches(xml, "a:t").join("\n");
    const relationshipFilename = `ppt/slides/_rels/slide${slideNumber}.xml.rels`;
    const relationships = await zip.file(relationshipFilename)?.async("string") || "";
    const notesTarget = relationships.match(/<Relationship[^>]*Type="[^"]*\/notesSlide"[^>]*Target="([^"]+)"/u)?.[1];
    const notesFilename = notesTarget ? path.posix.normalize(path.posix.join("ppt/slides", notesTarget)) : undefined;
    const notes = notesFilename ? await zip.file(notesFilename)?.async("string") : undefined;
    const noteLines = notes ? xmlTextMatches(notes, "a:t").join("\n") : "";
    const text = normalizeText(noteLines ? `${body}\n\n[speaker_notes]\n${noteLines}` : body);
    if (text) elements.push({
      ordinal: slideNumber, element_type: "slide", text, slide: slideNumber,
      element_subtype: noteLines ? "speaker_notes" : "slide_body", locator_confidence: 0.95, confidence: "high",
    });
  }
  return { parser_version: DOCUMENT_PARSER_VERSION, extraction_method: "ooxml-slide-text", elements, warnings: [] };
}

async function parseXlsx(buffer: Buffer): Promise<ParsedDocument> {
  const zip = await JSZip.loadAsync(buffer);
  const sharedStringsXml = await zip.file("xl/sharedStrings.xml")?.async("string") || "";
  const sharedStrings = [...sharedStringsXml.matchAll(/<si(?:\s[^>]*)?>([\s\S]*?)<\/si>/gu)].map((match) =>
    xmlTextMatches(match[1] || "", "t").join("")
  );
  const workbookXml = await zip.file("xl/workbook.xml")?.async("string") || "";
  const workbookRels = await zip.file("xl/_rels/workbook.xml.rels")?.async("string") || "";
  const relationshipTargets = new Map([...workbookRels.matchAll(/<Relationship[^>]*Id="([^"]+)"[^>]*Target="([^"]+)"/gu)].map((match) => [match[1]!, `xl/${match[2]!.replace(/^\//, "")}`]));
  const sheets = [...workbookXml.matchAll(/<sheet[^>]*name="([^"]+)"[^>]*r:id="([^"]+)"[^>]*\/?>(?:<\/sheet>)?/gu)]
    .map((match) => ({ name: decodeXmlEntities(match[1]!), file: path.posix.normalize(relationshipTargets.get(match[2]!) || "") }))
    .filter((sheet) => Boolean(sheet.file));
  const worksheetFiles = sheets.length ? sheets : Object.keys(zip.files).filter((name) => /^xl\/worksheets\/sheet\d+\.xml$/u.test(name)).sort().map((file) => ({ name: path.basename(file, ".xml"), file }));
  const elements: ParsedElement[] = [];
  let ordinal = 0;
  for (const sheet of worksheetFiles) {
    const sheetName = sheet.name;
    const xml = await zip.file(sheet.file)?.async("string");
    if (!xml) continue;
    const mergedRanges = [...xml.matchAll(/<mergeCell[^>]*ref="([^"]+)"/gu)].map((match) => match[1]!);
    for (const rowMatch of xml.matchAll(/<row[^>]*>([\s\S]*?)<\/row>/gu)) {
      const cells: string[] = [];
      let firstReference = "";
      let lastReference = "";
      for (const cellMatch of (rowMatch[1] || "").matchAll(/<c([^>]*)>([\s\S]*?)<\/c>/gu)) {
        const reference = cellMatch[1]?.match(/r="([A-Z]+\d+)"/)?.[1] || "";
        const attributes = cellMatch[1] || "";
        const inlineMatch = cellMatch[2]?.match(/<is(?:\s[^>]*)?>([\s\S]*?)<\/is>/);
        const rawValue = inlineMatch ? "" : cellMatch[2]?.match(/<v(?:\s[^>]*)?>([\s\S]*?)<\/v>/)?.[1] || "";
        const value = inlineMatch
          ? decodeXmlEntities(xmlTextMatches(inlineMatch[1] || "", "t").join(""))
          : /t="s"/.test(attributes) ? sharedStrings[Number(rawValue)] || "" : decodeXmlEntities(rawValue);
        const formula = cellMatch[2]?.match(/<f(?:\s[^>]*)?>([\s\S]*?)<\/f>/)?.[1];
        if (value.trim() || formula) {
          firstReference ||= reference;
          lastReference = reference || lastReference;
          cells.push(`${reference}=${formula ? `FORMULA:${decodeXmlEntities(formula)};CACHED:${value.trim() || "<missing>"}` : value.trim()}`);
        }
      }
      if (cells.length) {
        ordinal += 1;
        const rowNumber = firstReference.match(/\d+$/)?.[0] || "?";
        const cellRange = `${sheetName}!${firstReference}:${lastReference || firstReference}`;
        const merged = mergedRanges.filter((range) => range.includes(rowNumber));
        elements.push({ ordinal, element_type: "sheet", text: cells.join("\t"), sheet: sheetName, cell_range: cellRange, section: merged.length ? `merged:${merged.join(",")}` : undefined, element_subtype: merged.length ? "merged_row" : "sheet_row", locator_confidence: 0.95, confidence: "high" });
      }
    }
  }
  return { parser_version: DOCUMENT_PARSER_VERSION, extraction_method: "ooxml-workbook-structure", elements, warnings: [] };
}

function parsePlainText(buffer: Buffer, extension: string): ParsedDocument {
  const text = normalizeText(buffer.toString("utf8"));
  const headingPattern = /^(#{1,6})\s+(.+?)\s*$/;
  const lines = text.split("\n");
  const elements: ParsedElement[] = [];
  let currentSection = extension === ".md" || extension === ".markdown" ? undefined : "document";
  let startLine = 1;
  let sectionLines: string[] = [];
  const flush = (): void => {
    const content = normalizeText(sectionLines.join("\n"));
    if (!content) return;
    elements.push({
      ordinal: elements.length + 1,
      element_type: currentSection === "document" ? "text" : "section",
      text: content,
      section: currentSection,
      line_start: startLine,
      line_end: startLine + sectionLines.length - 1,
      locator_confidence: 1,
      element_subtype: currentSection === "document" ? "plain_text" : "heading_section",
      confidence: "high",
    });
  };
  for (const [index, line] of lines.entries()) {
    const heading = extension === ".md" || extension === ".markdown" ? line.match(headingPattern) : null;
    if (heading) {
      flush();
      currentSection = heading[2] || `Heading ${elements.length + 1}`;
      startLine = index + 1;
      sectionLines = [line];
    } else {
      if (!sectionLines.length) startLine = index + 1;
      sectionLines.push(line);
    }
  }
  flush();
  return { parser_version: DOCUMENT_PARSER_VERSION, extraction_method: "utf8-structure", elements, warnings: [] };
}

export async function parseDocument(filePath: string, signal?: Aborter): Promise<ParsedDocument> {
  const extension = path.extname(filePath).toLowerCase();
  if (!SUPPORTED_DOCUMENT_EXTENSIONS.has(extension)) throw new Error(`Unsupported document extension ${extension}; supported: ${[...SUPPORTED_DOCUMENT_EXTENSIONS].sort().join(", ")}. OCR/audio/video require an explicitly enabled sidecar.`);
  const buffer = await fs.readFile(filePath, { signal });
  if (IMAGE_OCR_EXTENSIONS.has(extension)) return await parseImageOcr(filePath);
  if (extension === ".pdf") return await parsePdf(buffer, signal);
  if (extension === ".docx") return await parseDocx(buffer);
  if (extension === ".pptx") return await parsePptx(buffer);
  if (extension === ".xlsx") return await parseXlsx(buffer);
  return parsePlainText(buffer, extension);
}

interface OcrBlockLike { confidence?: unknown; text?: unknown; bbox?: unknown }

/**
 * Convert raw OCR blocks into provenance-rich line/block elements.
 * Blocks below the confidence threshold are dropped outright — never guessed — and every kept
 * block carries its own real bounding box plus numeric locator confidence. The average-confidence
 * shortcut is intentionally NOT used: a single low-confidence block must not pass on the
 * strength of its neighbours.
 */
export function ocrElementsFromBlocks(blocks: OcrBlockLike[], options: { threshold?: number } = {}): { elements: ParsedElement[]; dropped_low_confidence: number; average_confidence: number } {
  const threshold = options.threshold ?? OCR_BLOCK_CONFIDENCE_THRESHOLD;
  const kept: ParsedElement[] = [];
  let dropped = 0;
  let confidenceSum = 0;
  for (const [index, block] of blocks.entries()) {
    const confidence = Number(block.confidence ?? 0);
    const text = String(block.text ?? "").trim();
    confidenceSum += confidence;
    if (!text || confidence < threshold) {
      dropped += 1;
      continue;
    }
    const rawBbox = Array.isArray(block.bbox) ? block.bbox.map((value) => Number(value)) : [];
    const bbox = rawBbox.length === 4 && rawBbox.every((value) => Number.isFinite(value))
      ? [Math.round(rawBbox[0]! * 100) / 100, Math.round(rawBbox[1]! * 100) / 100, Math.round(rawBbox[2]! * 100) / 100, Math.round(rawBbox[3]! * 100) / 100] as [number, number, number, number]
      : undefined;
    kept.push({
      ordinal: index + 1,
      element_type: "text",
      text,
      section: "OCR",
      bbox,
      locator_confidence: Math.min(1, Math.max(0, confidence / 100)),
      element_subtype: "ocr_block",
      line_start: index + 1,
      line_end: index + 1,
      confidence: confidence >= 85 ? "high" : "medium",
    });
  }
  const average = blocks.length ? confidenceSum / blocks.length : 0;
  return { elements: kept, dropped_low_confidence: dropped, average_confidence: Math.round(average * 10) / 10 };
}

async function parseImageOcr(filePath: string | Buffer): Promise<ParsedDocument> {
  if (!/^(1|true|yes)$/i.test(process.env.AGY_DOCUMENT_ENABLE_OCR || "")) {
    throw new Error("Image OCR is disabled; set AGY_DOCUMENT_ENABLE_OCR=1 to enable explicit local OCR");
  }
  const langPath = process.env.AGY_TESSERACT_LANG_PATH;
  if (!langPath) throw new Error("AGY_TESSERACT_LANG_PATH is required for offline vie+eng OCR");
  const languages = ["vie", "eng"];
  const available = languages.every((language) =>
    ["", ".gz"].some((suffix) => existsSync(path.join(langPath, `${language}.traineddata${suffix}`)))
  );
  if (!available) throw new Error(`Offline OCR language data incomplete in ${langPath}; vie and eng traineddata are required`);
  const { createWorker } = await import("tesseract.js");
  const worker = await createWorker("vie+eng", 1, { gzip: false, langPath });
  try {
    const result = await worker.recognize(filePath as any);
    const rawBlocks = (result.data as unknown as { blocks?: Array<{ confidence?: unknown; text?: unknown; bbox?: unknown }> }).blocks || [{
      confidence: result.data.confidence,
      text: result.data.text,
      bbox: undefined,
    }];
    // Per-block gating: every block below 70% is discarded even when the page average looks fine.
    const { elements, dropped_low_confidence, average_confidence } = ocrElementsFromBlocks(rawBlocks);
    if (!elements.length) {
      throw new Error(`OCR produced no block at or above ${OCR_BLOCK_CONFIDENCE_THRESHOLD}% confidence (average ${average_confidence.toFixed(1)}%); low-confidence text will not be guessed`);
    }
    return {
      parser_version: DOCUMENT_PARSER_VERSION,
      extraction_method: `tesseract-vie-eng-blocks-${average_confidence.toFixed(0)}pct`,
      elements,
      warnings: [`ocr_average_confidence=${average_confidence.toFixed(1)}%`, `ocr_dropped_low_confidence_blocks=${dropped_low_confidence}`],
    };
  } finally {
    await worker.terminate();
  }
}

export interface ChunkInput {
  collection_id: string;
  source_id: string;
  source_sha256: string;
  source_kind: string;
  extraction_method: string;
  elements: ParsedElement[];
}

export interface OutputChunk extends ChunkInput {
  element_ordinal: number;
  chunk_ordinal: number;
  text: string;
  locator: Omit<import("./documentTypes.js").SourceLocator, "source_id" | "source_sha256">;
  estimated_tokens: number;
}

export function chunkParsedDocument(input: ChunkInput, maxCharacters = 1400): OutputChunk[] {
  const chunks: OutputChunk[] = [];
  for (const element of input.elements) {
    const paragraphs = element.text.split(/\n\s*\n/).map((item) => item.trim()).filter(Boolean);
    let current = "";
    let part = 0;
    const emit = (): void => {
      const text = current.trim();
      if (!text) return;
      chunks.push({
        ...input,
        element_ordinal: element.ordinal,
        chunk_ordinal: chunks.length,
        text,
        locator: {
          page: element.page,
          slide: element.slide,
          section: element.section,
          sheet: element.sheet,
          cell_range: element.cell_range,
          line_start: element.line_start,
          line_end: element.line_end,
          start_ms: element.start_ms,
          end_ms: element.end_ms,
          bbox: element.bbox,
          locator_confidence: element.locator_confidence,
          element_subtype: element.element_subtype,
        },
        estimated_tokens: Math.ceil(Buffer.byteLength(text, "utf8") / 3),
      });
      current = "";
      part += 1;
    };
    for (const paragraph of paragraphs) {
      if (paragraph.length > maxCharacters) {
        emit();
        for (let offset = 0; offset < paragraph.length; offset += maxCharacters) {
          current = paragraph.slice(offset, offset + maxCharacters);
          emit();
        }
        continue;
      }
      if (current && current.length + paragraph.length + 2 > maxCharacters) emit();
      current = current ? `${current}\n\n${paragraph}` : paragraph;
    }
    emit();
  }
  return chunks;
}
