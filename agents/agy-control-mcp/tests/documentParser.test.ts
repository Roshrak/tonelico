import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import JSZip from "jszip";
import { parseDocument } from "../src/documentParser.js";

async function temporaryDirectory(): Promise<string> {
  return await fs.mkdtemp(path.join(os.tmpdir(), "agy-parser-"));
}

function minimalPdf(text: string): Buffer {
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
    `<< /Length ${`BT /F1 12 Tf 72 720 Td (${text}) Tj ET`.length} >>\nstream\nBT /F1 12 Tf 72 720 Td (${text}) Tj ET\nendstream`,
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
  ];
  let body = "%PDF-1.4\n";
  const offsets = [0];
  objects.forEach((object, index) => {
    offsets.push(Buffer.byteLength(body, "ascii"));
    body += `${index + 1} 0 obj\n${object}\nendobj\n`;
  });
  const xref = Buffer.byteLength(body, "ascii");
  body += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  for (const offset of offsets.slice(1)) body += `${String(offset).padStart(10, "0")} 00000 n \n`;
  body += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return Buffer.from(body, "ascii");
}

test("parser preserves PDF page provenance", async () => {
  const directory = await temporaryDirectory();
  const filename = path.join(directory, "page.pdf");
  await fs.writeFile(filename, minimalPdf("Aphthous RAS"));
  const parsed = await parseDocument(filename);
  assert.equal(parsed.elements[0]?.page, 1);
  assert.match(parsed.elements[0]?.text || "", /Aphthous RAS/);
});

test("parser preserves DOCX tables and headers", async () => {
  const directory = await temporaryDirectory();
  const filename = path.join(directory, "record.docx");
  const zip = new JSZip();
  zip.file("word/document.xml", `<w:document xmlns:w="w"><w:body><w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Bệnh án</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>Họ tên</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Đã ẩn danh</w:t></w:r></w:p></w:tc></w:tr></w:tbl><w:sectPr/></w:body></w:document>`);
  zip.file("word/header1.xml", `<w:hdr xmlns:w="w"><w:p><w:r><w:t>Header bệnh án</w:t></w:r></w:p></w:hdr>`);
  await fs.writeFile(filename, await zip.generateAsync({ type: "nodebuffer" }));
  const parsed = await parseDocument(filename);
  assert.ok(parsed.elements.some((item) => item.section?.includes("Heading1")));
  assert.ok(parsed.elements.some((item) => item.cell_range === "Table1!A1:B1"));
  assert.ok(parsed.elements.some((item) => item.section === "header:1"));
});

test("parser resolves PPTX notes relationships and XLSX true cell locators", async () => {
  const directory = await temporaryDirectory();
  const pptx = new JSZip();
  pptx.file("ppt/slides/slide1.xml", `<p:sld xmlns:a="a"><a:t>Slide RAS</a:t></p:sld>`);
  pptx.file("ppt/slides/_rels/slide1.xml.rels", `<Relationships><Relationship Id="rId7" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesSlide" Target="../notesSlides/notesSlide9.xml"/></Relationships>`);
  pptx.file("ppt/notesSlides/notesSlide9.xml", `<p:notes xmlns:a="a"><a:t>Ghi chú cơ chế</a:t></p:notes>`);
  const pptxPath = path.join(directory, "slides.pptx");
  await fs.writeFile(pptxPath, await pptx.generateAsync({ type: "nodebuffer" }));
  const pptxParsed = await parseDocument(pptxPath);
  assert.match(pptxParsed.elements[0]?.text || "", /Ghi chú cơ chế/);

  const xlsx = new JSZip();
  xlsx.file("xl/workbook.xml", `<workbook xmlns:r="r"><sheets><sheet name="Điều trị" sheetId="1" r:id="rId2"/></sheets></workbook>`);
  xlsx.file("xl/_rels/workbook.xml.rels", `<Relationships><Relationship Id="rId2" Target="worksheets/sheet1.xml"/></Relationships>`);
  xlsx.file("xl/worksheets/sheet1.xml", `<worksheet><mergeCells><mergeCell ref="A1:B1"/></mergeCells><sheetData><row r="1"><c r="A1"><v>2</v></c><c r="B1"><f>SUM(A1:A1)</f><v>2</v></c></row></sheetData></worksheet>`);
  const xlsxPath = path.join(directory, "table.xlsx");
  await fs.writeFile(xlsxPath, await xlsx.generateAsync({ type: "nodebuffer" }));
  const xlsxParsed = await parseDocument(xlsxPath);
  assert.equal(xlsxParsed.elements[0]?.cell_range, "Điều trị!A1:B1");
  assert.match(xlsxParsed.elements[0]?.text || "", /FORMULA:SUM/);
});
