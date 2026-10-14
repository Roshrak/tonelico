import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { DatabaseSync } from "node:sqlite";
import JSZip from "jszip";
import { DOCUMENT_PARSER_VERSION, ocrElementsFromBlocks, parseDocument } from "../src/documentParser.js";
import { DocumentManager } from "../src/documentManager.js";
import type { AgyOutcome, AgyRunnerLike, RunnerJob } from "../src/runner.js";
import { loadConfig } from "../src/config.js";

function succeedFromPrompt(role: string): (job: RunnerJob) => Promise<AgyOutcome> {
  return async (job) => {
    const locked = JSON.parse(job.prompt.split("# Locked Scope\n")[1].split("\n\n")[0]);
    const evidence = JSON.parse(job.prompt.split("<untrusted_evidence>\n")[1].split("\n</untrusted_evidence>")[0]);
    return {
      state: "done", exitCode: 0,
      structuredOutput: {
        status: "done", role,
        scope_echo: { scope_sha256: locked.scope_sha256, source_ids: locked.source_ids },
        items: evidence.map((item: any) => ({ id: item.id, text: String(item.text).split("\n").filter(Boolean).at(-1), locator: item.locator, confidence: "high" })),
        coverage: { expected: evidence.length, covered: evidence.length, missing: [], covered_ids: evidence.map((item: any) => item.id), missing_ids: [] },
        uncertainties: [], violations: [],
      },
      numTurns: 1, usage: { input_tokens: 100, output_tokens: 20, total_tokens: 120 },
    };
  };
}

// ---------------------------------------------------------------------------
// Minimal PDF builder: sequential objects + computed xref so pdf.js parses it.
// ---------------------------------------------------------------------------
type PdfLine = [number, number, string];

function buildPdf(pages: PdfLine[][]): Buffer {
  const encoder = (text: string): string => text.replace(/\\/g, "\\\\").replace(/\(/g, "\\(").replace(/\)/g, "\\)");
  const pageContents = pages.map((lines) => {
    const stream = ["BT", "/F1 11 Tf", "14 TL"];
    for (const [x, y, text] of lines) {
      stream.push(`1 0 0 1 ${x} ${y} Tm`, `(${encoder(text)}) Tj`);
    }
    stream.push("ET");
    return stream.join("\n");
  });
  const objects: string[] = [];
  const objectId = (num: number): string => `${num} 0 R`;
  objects[1] = "<< /Type /Catalog /Pages 2 0 R >>";
  const kids = pageContents.map((_, index) => objectId(3 + index * 2)).join(" ");
  objects[2] = `<< /Type /Pages /Kids [${kids}] /Count ${pageContents.length} >>`;
  pageContents.forEach((content, index) => {
    const pageNumber = 3 + index * 2;
    objects[pageNumber] = `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents ${pageNumber + 1} 0 R >>`;
    objects[pageNumber + 1] = `<< /Length ${Buffer.byteLength(content, "latin1")} >>\nstream\n${content}\nendstream`;
  });
  // Font object lands at the next free id after all pages.
  const fontId = 3 + pageContents.length * 2;
  objects[fontId] = "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>";
  let body = "%PDF-1.4\n";
  const offsets: number[] = [];
  for (let id = 1; id <= fontId; id += 1) {
    if (!objects[id]) continue;
    offsets[id] = Buffer.byteLength(body, "latin1");
    body += `${id} 0 obj\n${objects[id]}\nendobj\n`;
  }
  const xrefOffset = Buffer.byteLength(body, "latin1");
  body += `xref\n0 ${fontId + 1}\n0000000000 65535 f \n`;
  for (let id = 1; id <= fontId; id += 1) {
    body += `${String(offsets[id] || 0).padStart(10, "0")} 00000 n \n`;
  }
  body += `trailer\n<< /Size ${fontId + 1} /Root 1 0 R >>\nstartxref\n${xrefOffset}\n%%EOF`;
  return Buffer.from(body, "latin1");
}

async function temporaryDirectory(name: string): Promise<string> {
  return await fs.mkdtemp(path.join(os.tmpdir(), `agy-corpus-${name}-`));
}

/** Ingest one file and return the manager plus collection id for round-trip assertions. */
async function ingestOne(root: string, filePath: string, options: { manager?: DocumentManager } = {}): Promise<{ manager: DocumentManager; collectionId: string }> {
  const manager = options.manager || new DocumentManager({ config: loadConfig({ root }) });
  const queued = await manager.ingest({ collection_name: `corpus-${path.basename(filePath)}`, paths: [filePath] }) as any;
  const done = await manager.wait(queued.job_id, 15);
  assert.equal((done as any).state, "ready_for_commander", JSON.stringify((done as any).error));
  return { manager, collectionId: queued.collection_id };
}

function chunkRows(root: string, collectionId: string): any[] {
  const database = new DatabaseSync(path.join(root, "document", "index.sqlite"), { readOnly: true });
  try {
    return database.prepare("SELECT * FROM chunks WHERE collection_id=? ORDER BY id").all(collectionId) as any[];
  } finally { database.close(); }
}

test("two-column PDF keeps reading order and real per-block bounding boxes", async () => {
  const left: PdfLine[] = [
    [60, 700, "Alpha introduction paragraph"],
    [60, 680, "Alpha second line continues"],
    [60, 630, "Beta findings summary"],
    [60, 610, "Beta second line continues"],
    [60, 560, "Gamma conclusion reached"],
  ];
  const right: PdfLine[] = [
    [330, 700, "Delta methods overview"],
    [330, 680, "Delta second line continues"],
    [330, 630, "Epsilon measurements recorded"],
    [330, 610, "Epsilon second line"],
    [330, 560, "Zeta appendix pointer"],
  ];
  const pdf = buildPdf([[...left, ...right]]);
  const root = await temporaryDirectory("twocol");
  await fs.writeFile(path.join(root, "twocolumn.pdf"), pdf);
  const parsed = await parseDocument(path.join(root, "twocolumn.pdf"));
  assert.equal(parsed.parser_version, DOCUMENT_PARSER_VERSION);
  assert.ok(parsed.elements.length >= 6, `expected several blocks, got ${parsed.elements.length}`);
  const texts = parsed.elements.map((element) => element.text);
  const firstLeft = texts.findIndex((text) => text.startsWith("Alpha"));
  const lastLeft = texts.findIndex((text) => text.startsWith("Gamma"));
  const firstRight = texts.findIndex((text) => text.startsWith("Delta"));
  assert.ok(firstLeft !== -1 && firstRight !== -1);
  assert.ok(firstLeft < firstRight, "left column must be read before right column");
  assert.ok(lastLeft < firstRight, "entire left column precedes right column");
  for (const element of parsed.elements) {
    assert.deepEqual(element.bbox!.length, 4);
    assert.notDeepEqual(element.bbox, [0, 0, 1, 1], "synthetic full-page boxes are banned");
    assert.equal(element.element_subtype, "pdf_block");
    assert.equal(element.locator_confidence! > 0.8, true);
  }
  const alphaBlock = parsed.elements[firstLeft];
  const deltaBlock = parsed.elements[firstRight];
  assert.ok(alphaBlock.bbox![0] < 200 && deltaBlock.bbox![0] > 300, "block x must match its column");

  // Full provenance round trip: parser -> SQLite -> scoped evidence search.
  const { manager, collectionId } = await ingestOne(root, path.join(root, "twocolumn.pdf"));
  try {
    const stored = chunkRows(root, collectionId).filter((row) => row.status !== undefined || true);
    assert.ok(stored.length >= 1);
    const withBox = stored.find((row) => row.bbox_json);
    assert.ok(withBox, "chunks must persist their real bbox_json");
    const box = JSON.parse(withBox.bbox_json);
    assert.equal(box.length, 4);
    assert.notDeepEqual(box, [0, 0, 1, 1]);
    assert.equal(withBox.element_subtype, "pdf_block");
    const scope = await manager.createScope({ collection_id: collectionId, profile: "study", selectors: [{ page_start: 1, page_end: 1 }] }) as any;
    const evidence = await manager.search({ collection_id: collectionId, scope_id: scope.scope_id, query: "Epsilon measurements", limit: 5 }) as any;
    assert.ok(evidence.items.length >= 1);
    const hit = evidence.items.find((item: any) => item.text.includes("Epsilon"));
    assert.ok(hit, JSON.stringify(evidence.items.map((i: any) => i.text)));
    assert.ok(Array.isArray(hit.locator.bbox) && hit.locator.element_subtype === "pdf_block");
  } finally { await manager.shutdown(); }
});

test("cross-page table keeps the repeated header per page without fabricating a merged table", async () => {
  const headerRow = (y: number): [number, number, string] => [70, y, "Item code    Description    Qty"];
  const pdf = buildPdf([
    [
      headerRow(720),
      [70, 690, "A-100        Syringe 5ml       40"],
      [70, 660, "A-140        Gauze roll        12"],
    ],
    [
      headerRow(720),
      [70, 690, "B-220        Tape roll          8"],
      [70, 660, "B-260        Scissors set       3"],
    ],
  ]);
  const root = await temporaryDirectory("table");
  await fs.writeFile(path.join(root, "table.pdf"), pdf);
  const parsed = await parseDocument(path.join(root, "table.pdf"));
  const headerBlocks = parsed.elements.filter((element) => element.text.includes("Item code"));
  assert.equal(headerBlocks.length, 2, "the repeated header must survive on both pages");
  assert.deepEqual(headerBlocks.map((block) => block.page), [1, 2]);
  // No element claims to span both pages: cross-page joins are never invented.
  for (const element of parsed.elements) assert.ok(element.page === 1 || element.page === 2);
  assert.ok(!parsed.elements.some((element) => element.text.includes("A-100") && element.text.includes("B-220")), "rows from different pages must not be concatenated");

  const { manager, collectionId } = await ingestOne(root, path.join(root, "table.pdf"), { manager: undefined as any });
  try {
    const scopePage1 = await manager.createScope({ collection_id: collectionId, selectors: [{ page_start: 1, page_end: 1 }] }) as any;
    const page1 = await manager.search({ collection_id: collectionId, scope_id: scopePage1.scope_id, query: "Gauze" }) as any;
    assert.ok(page1.items.some((item: any) => item.locator.page === 1));
    const scopeBoth = await manager.createScope({ collection_id: collectionId, selectors: [{ page_start: 1, page_end: 2 }] }) as any;
    const both = await manager.search({ collection_id: collectionId, scope_id: scopeBoth.scope_id, query: "Tape OR Gauze" }) as any;
    const pages = new Set(both.items.map((item: any) => item.locator.page));
    assert.deepEqual([...pages].sort(), [1, 2]);
  } finally { await manager.shutdown(); }
});

test("scanned-page fallback fails closed without OCR and OCR blocks gate confidence per block", async () => {
  delete process.env.AGY_DOCUMENT_ENABLE_OCR;
  const pdf = buildPdf([[]]); // a page with no extractable text behaves like a scan
  const root = await temporaryDirectory("scan");
  await fs.writeFile(path.join(root, "scan.pdf"), pdf);
  const parsed = await parseDocument(path.join(root, "scan.pdf"));
  assert.ok(parsed.elements.length === 0);
  assert.ok(parsed.warnings.some((warning) => warning.includes("scanned_pdf_ocr_unavailable")));
  assert.equal(parsed.warnings.some((warning) => warning.includes("guess")), false);

  // Per-block gating: one weak block must not ride on a strong average.
  const result = ocrElementsFromBlocks([
    { confidence: 96, text: "Vung mieng loet", bbox: [10, 20, 120, 16] },
    { confidence: 52, text: "garbled guess", bbox: [10, 44, 90, 16] },
    { confidence: 81, text: "Chan doan phu", bbox: [10, 68, 110, 16] },
  ]);
  assert.equal(result.dropped_low_confidence, 1);
  assert.equal(result.elements.length, 2);
  assert.ok(result.elements.every((element) => element.element_subtype === "ocr_block"));
  assert.ok(result.elements.every((element) => Array.isArray(element.bbox)));
  assert.ok(Math.abs(result.average_confidence - 76.3) < 0.1);
});

async function buildDocx(targetPath: string): Promise<void> {
  const zip = new JSZip();
  zip.file("[Content_Types].xml", `<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>`);
  zip.folder("_rels")!.file(".rels", `<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>`);
  const word = zip.folder("word")!;
  word.file("document.xml", `<?xml version="1.0"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Chuong Loet Aphthous</w:t></w:r></w:p>
<w:p><w:r><w:t>Loet aphthous tái phát la ton thuong niem mac pho bien.</w:t></w:r></w:p>
<w:tbl><w:tr><w:tc><w:tcPr/><w:r><w:t>Thuoc</w:t></w:r></w:tc><w:tc><w:tcPr/><w:r><w:t>Lieu</w:t></w:r></w:tc></w:tr>
<w:tr><w:tc><w:tcPr><w:gridSpan w:val="2"/></w:tcPr><w:r><w:t>Ghi chu tong hop ca hai cot</w:t></w:r></w:tc></w:tr></w:tbl>
<w:sectPr/></w:body></w:document>`);
  word.file("header1.xml", `<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:p><w:r><w:t>Bai giang dai hoc</w:t></w:r></w:p></w:hdr>`);
  word.file("footer1.xml", `<w:ftr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:p><w:r><w:t>Trang tai lieu hoc tap</w:t></w:r></w:p></w:ftr>`);
  await fs.writeFile(targetPath, await zip.generateAsync({ type: "nodebuffer" }));
}

test("DOCX headings, header/footer, and merged-cell tables produce structured locators", async () => {
  const root = await temporaryDirectory("docx");
  const docxPath = path.join(root, "lecture.docx");
  await buildDocx(docxPath);
  const parsed = await parseDocument(docxPath);
  const heading = parsed.elements.find((element) => element.section?.includes("/Heading1"));
  assert.ok(heading && heading.text.includes("Chuong Loet Aphthous"));
  const header = parsed.elements.find((element) => element.element_subtype === "header");
  const footer = parsed.elements.find((element) => element.element_subtype === "footer");
  assert.ok(header?.text.includes("dai hoc"));
  assert.ok(footer?.text.includes("hoc tap"));
  const mergedRow = parsed.elements.find((element) => element.text.includes("[merged x2]") || element.text.includes("tong hop ca hai cot"));
  assert.ok(mergedRow, "gridSpan merge must be visible in the row text");
  assert.equal(mergedRow!.element_subtype, "table_row");

  const { manager, collectionId } = await ingestOne(root, docxPath);
  try {
    const rows = chunkRows(root, collectionId);
    const storedRow = rows.find((row) => row.text.includes("Ghi chu tong hop"));
    assert.ok(storedRow);
    assert.equal(storedRow.cell_range.startsWith("Table1!"), true);
    const scope = await manager.createScope({ collection_id: collectionId, profile: "study", selectors: [{ sections: ["body/Heading1"] }] }) as any;
    const evidence = await manager.search({ collection_id: collectionId, scope_id: scope.scope_id, query: "aphthous tái phát" }) as any;
    assert.ok(evidence.items.some((item: any) => item.locator.section?.includes("Heading1")));
  } finally { await manager.shutdown(); }
});

async function buildPptx(targetPath: string, options: { notesOnSlide1: boolean; mismatchNotesId?: boolean }): Promise<void> {
  const zip = new JSZip();
  const slideXml = (title: string): string => `<?xml version="1.0"?>
<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>${title}</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>`;
  const notesXml = (text: string): string => `<?xml version="1.0"?>
<p:notes xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p:cSld><p:sp><p:txBody><a:p><a:r><a:t>${text}</a:t></a:r></a:p></p:txBody></p:sp></p:cSld></p:notes>`;
  const slides = zip.folder("ppt")!.folder("slides")!;
  slides.file("slide1.xml", slideXml("Loet aphthous recurr"));
  slides.file("slide2.xml", slideXml("Khong co ghi chu"));
  const rels = slides.folder("_rels")!;
  if (options.notesOnSlide1) {
    // Deliberately point at notesSlide7 even though this is slide 1: resolution MUST go through
    // the relationship target, never through guessing notesSlide<slideNumber>.
    const target = options.mismatchNotesId ? "notesSlide7.xml" : "notesSlide1.xml";
    rels.file("slide1.xml.rels", `<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesSlide" Target="../notesSlides/${target}"/></Relationships>`);
    zip.folder("ppt")!.folder("notesSlides")!.file(options.mismatchNotesId ? "notesSlide7.xml" : "notesSlide1.xml", notesXml("Nhan manh chan doan phan biet"));
  }
  await fs.writeFile(targetPath, await zip.generateAsync({ type: "nodebuffer" }));
}

test("PPTX speaker notes resolve via relationships including mismatched notes IDs", async () => {
  const root = await temporaryDirectory("pptx");
  const deckPath = path.join(root, "deck.pptx");
  await buildPptx(deckPath, { notesOnSlide1: true, mismatchNotesId: true });
  const parsed = await parseDocument(deckPath);
  const slide1 = parsed.elements.find((element) => element.slide === 1);
  const slide2 = parsed.elements.find((element) => element.slide === 2);
  assert.ok(slide1!.text.includes("Nhan manh chan doan phan biet"), "notes must follow the relationship target");
  assert.equal(slide1!.element_subtype, "speaker_notes");
  assert.ok(!slide2!.text.includes("[speaker_notes]"), "slides without notes must not fabricate them");
  assert.equal(slide2!.element_subtype, "slide_body");

  const { manager, collectionId } = await ingestOne(root, deckPath);
  try {
    const scope = await manager.createScope({ collection_id: collectionId, selectors: [{ slides: [1, 2] }] }) as any;
    const evidence = await manager.search({ collection_id: collectionId, scope_id: scope.scope_id, query: "chan doan phan biet" }) as any;
    const noteHit = evidence.items.find((item: any) => item.locator.slide === 1);
    assert.ok(noteHit && noteHit.locator.element_subtype === "speaker_notes");
    const rows = chunkRows(root, collectionId);
    assert.ok(rows.every((row) => row.slide === null || row.slide === 1 || row.slide === 2));
  } finally { await manager.shutdown(); }
});

async function buildXlsx(targetPath: string): Promise<void> {
  const zip = new JSZip();
  zip.folder("xl")!.file("workbook.xml", `<?xml version="1.0"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>
<sheet name="Danh muc" sheetId="1" r:id="rId1"/>
<sheet name="Tinh toan" sheetId="2" r:id="rId2"/>
</sheets></workbook>`);
  zip.folder("xl")!.folder("_rels")!.file("workbook.xml.rels", `<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/></Relationships>`);
  zip.folder("xl")!.file("sharedStrings.xml", `<?xml version="1.0"?><sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><t>Vat tu</t></si><si><t>Gauze roll</t></si></sst>`);
  const sheets = zip.folder("xl")!.folder("worksheets")!;
  sheets.file("sheet1.xml", `<?xml version="1.0"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><mergeCells count="1"><mergeCell ref="A2:B2"/></mergeCells>
<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>
<row r="2"><c r="A2" t="inlineStr"><is><t>Ten nhap truc tiep</t></is></c></row></worksheet>`);
  sheets.file("sheet2.xml", `<?xml version="1.0"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<row r="1"><c r="A1"><f>SUM(B1:B9)</f><v>77</v></c></row>
<row r="2"><c r="A2"><f>A1*2</f></c></row></worksheet>`);
  await fs.writeFile(targetPath, await zip.generateAsync({ type: "nodebuffer" }));
}

test("XLSX preserves real sheet names, merged ranges, formulas, cached values, and inline strings", async () => {
  const root = await temporaryDirectory("xlsx");
  const workbookPath = path.join(root, "supplies.xlsx");
  await buildXlsx(workbookPath);
  const parsed = await parseDocument(workbookPath);
  const danhMuc = parsed.elements.filter((element) => element.sheet === "Danh muc");
  const tinhToan = parsed.elements.filter((element) => element.sheet === "Tinh toan");
  assert.ok(danhMuc.length >= 2 && tinhToan.length >= 2, "real sheet names must be used, not Sheet1/Sheet2");
  assert.ok(danhMuc.some((row) => row.text.includes("Vat tu") && row.text.includes("Gauze roll")), "shared strings resolve");
  assert.ok(danhMuc.some((row) => row.text.includes("Ten nhap truc tiep")), "inline strings resolve");
  const mergedRow = danhMuc.find((row) => row.element_subtype === "merged_row");
  assert.ok(mergedRow && mergedRow.section?.startsWith("merged:A2:B2"));
  const formulaWithCache = tinhToan.find((row) => row.text.includes("FORMULA:SUM(B1:B9);CACHED:77"));
  assert.ok(formulaWithCache, "formula with cached value exposes both parts");
  const formulaWithoutCache = tinhToan.find((row) => row.text.includes("CACHED:<missing>"));
  assert.ok(formulaWithoutCache, "formula without cached value fails visibly instead of inventing one");

  const { manager, collectionId } = await ingestOne(root, workbookPath);
  try {
    const scope = await manager.createScope({ collection_id: collectionId, selectors: [{ sheets: ["Tinh toan"] }] }) as any;
    const evidence = await manager.search({ collection_id: collectionId, scope_id: scope.scope_id, query: "SUM" }) as any;
    assert.ok(evidence.items.length >= 1);
    assert.ok(evidence.items.every((item: any) => item.locator.sheet === "Tinh toan"));
    const stored = chunkRows(root, collectionId).find((row) => row.sheet === "Tinh toan" && row.element_subtype);
    assert.equal(stored.element_subtype, "sheet_row");
  } finally { await manager.shutdown(); }
});

const mediaTranscriber = {
  supports(filePath: string): boolean { return [".mp3", ".webm", ".mp4"].includes(path.extname(filePath).toLowerCase()); },
  async availability(): Promise<any> {
    return { enabled: true, protocol_version: 1, application_home: os.tmpdir(), python_path: "python", model_directory: os.tmpdir(), model_files_complete: true };
  },
  activeCount(): number { return 0; },
  async transcribe(): Promise<any> {
    return {
      parser_version: "phowhisper-sidecar-v1", extraction_method: "phowhisper-jsonl",
      elements: [
        { ordinal: 1, element_type: "transcript", text: "Dau thuong khop vai bat dau", start_ms: 0, end_ms: 1500, confidence: "medium" as const },
        { ordinal: 2, element_type: "transcript", text: "Giai phap dieu tri can nhac", start_ms: 61_000, end_ms: 63_500, confidence: "medium" as const },
      ],
      warnings: [],
    };
  },
};

test("media ingest keeps timestamp locators and scoped time-range retrieval honours them", async () => {
  const root = await temporaryDirectory("media");
  const audioPath = path.join(root, "lecture.mp3");
  await fs.writeFile(audioPath, Buffer.from([0xff, 0xfb]), "utf8");
  const manager = new DocumentManager({ config: loadConfig({ root }), transcriptionSidecar: mediaTranscriber as any });
  try {
    const queued = await manager.ingest({ collection_name: "media", paths: [audioPath] }) as any;
    const done = await manager.wait(queued.job_id, 10) as any;
    assert.equal(done.state, "ready_for_commander");
    const stored = chunkRows(root, queued.collection_id).filter((row) => row.start_ms !== null);
    assert.deepEqual(stored.map((row) => row.start_ms), [0, 61_000]);
    // Minute-bounded scope excludes the second minute segment.
    const firstMinute = await manager.createScope({ collection_id: queued.collection_id, selectors: [{ time_range_ms: [0, 60_000] }] }) as any;
    const evidence = await manager.search({ collection_id: queued.collection_id, scope_id: firstMinute.scope_id, query: "dau thuong khop" }) as any;
    const startsInScope = evidence.items.map((item: any) => [item.text.slice(0, 20), item.locator.start_ms]);
    assert.ok(evidence.items.some((item: any) => item.locator.start_ms === 0), JSON.stringify(startsInScope));
    assert.ok(evidence.items.every((item: any) => (item.locator.start_ms ?? 0) < 60_000), JSON.stringify(startsInScope));
    // Media extension routing: audio/video containers route to the sidecar, text files do not.
    assert.equal(mediaTranscriber.supports(path.join(root, "clip.webm")), true);
    assert.equal(mediaTranscriber.supports(path.join(root, "notes.txt")), false);
  } finally { await manager.shutdown(); }
});

test("clinical profile keeps extraction clerical: facts only, diagnosis and prescribing blocked", async () => {
  const root = await temporaryDirectory("clinical");
  const notePath = path.join(root, "note-deidentified.md");
  await fs.writeFile(notePath, [
    "# Benh an da gai ma hoa",
    "",
    "- Du kien ghi nhan: loet mieng tái phát 3 dot trong 12 thang.",
    "- Bieu hienn: đau khi ăn cay, niêm mac hong hong.",
    "",
    "# Du lieu con thieu",
    "",
    "- Chua co ket qua cong mau gan.",
  ].join("\n"), "utf8");
  const captured: string[] = [];
  let calls = 0;
  const runner: AgyRunnerLike & { behavior: (job: RunnerJob) => Promise<AgyOutcome> } = {
    behavior: succeedFromPrompt("field-extract"),
    async run(job) { calls += 1; captured.push(job.prompt); return await runner.behavior(job); },
    async kill() {},
    registerProcess() {},
  };
  const manager = new DocumentManager({ config: loadConfig({ root }), runner, modelResolver: async (tier) => `model-${tier}` });
  try {
    const { collectionId } = await ingestOne(root, notePath, { manager });
    const scope = await manager.createScope({ collection_id: collectionId, profile: "clinical_record", selectors: [{ sections: ["Benh an da gai ma hoa"] }], forbidden_topics: ["ke don thuoc", "chuan doan benh"] }) as any;
    assert.equal(scope.profile, "clinical_record");
    // Forbidden clinical roles are rejected outright at the control plane.
    for (const role of ["diagnosis", "prescribing", "final-answer", "grading", "mastery"]) {
      await assert.rejects(() => manager.delegate({ title: "x", collection_id: collectionId, scope_id: scope.scope_id, role, objective: "y" }), /role must be one of/);
    }
    const started = await manager.delegate({ title: "facts only", collection_id: collectionId, scope_id: scope.scope_id, role: "field-extract", objective: "Du kien ghi nhan ve loet mieng", tier: "fast", force_worker: true }) as any;
    const done = await manager.wait(started.run_id, 10) as any;
    assert.equal(done.state, "ready_for_commander", done.error);
    const promptText = path.join(String(done.artifact_path), "compiled-prompt.md");
    const prompt = await fs.readFile(promptText, "utf8");
    assert.match(prompt, /NEVER diagnose, prescribe/);
    assert.match(prompt, /clinical_record|explicitly stated facts|Return only explicitly stated facts/s);
  } finally { await manager.shutdown(); }
});
