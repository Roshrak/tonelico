type PdfLine = [number, number, string];

/** Minimal single/multi-page PDF builder (sequential objects + computed xref) for fixtures. */
export function buildPdf(pages: PdfLine[][]): Buffer {
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
  objects[1] = "<< /Type /Catalog /Pages 2 0 R >>";
  const kids = pageContents.map((_, index) => `${3 + index * 2} 0 R`).join(" ");
  objects[2] = `<< /Type /Pages /Kids [${kids}] /Count ${pageContents.length} >>`;
  pageContents.forEach((content, index) => {
    const pageNumber = 3 + index * 2;
    objects[pageNumber] = `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents ${pageNumber + 1} 0 R >>`;
    objects[pageNumber + 1] = `<< /Length ${Buffer.byteLength(content, "latin1")} >>\nstream\n${content}\nendstream`;
  });
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
  for (let id = 1; id <= fontId; id += 1) body += `${String(offsets[id] || 0).padStart(10, "0")} 00000 n \n`;
  body += `trailer\n<< /Size ${fontId + 1} /Root 1 0 R >>\nstartxref\n${xrefOffset}\n%%EOF`;
  return Buffer.from(body, "latin1");
}
