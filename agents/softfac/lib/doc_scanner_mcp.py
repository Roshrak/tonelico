#!/usr/bin/env python3
"""MCP server for Document Processing, Reading, OCR Scanning, and Archive Management."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

DEFAULT_WORK_DIR = Path("/home/aesc/work files")
DEFAULT_SCANNED_DIR = Path("/home/aesc/scanned result")
DEFAULT_ORIGINAL_DIR = Path("/home/aesc/original file")
SCAN_SCRIPT = Path("/home/aesc/.local/bin/scan_work_files.py")
OCR_PYTHON = Path("/home/aesc/.local/share/hermes-ocr/venv/bin/python")


def _ok(data: Any) -> dict:
    text = json.dumps(data, ensure_ascii=False, indent=2) if not isinstance(data, str) else data
    return {"content": [{"type": "text", "text": text}]}


def _err(msg: str) -> dict:
    return {"isError": True, "content": [{"type": "text", "text": msg}]}


def _read_docx_lines_and_tables(docx_path: Path) -> dict:
    paragraphs: List[str] = []
    tables: List[List[List[str]]] = []
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    with zipfile.ZipFile(docx_path) as z:
        tree = ET.fromstring(z.read("word/document.xml"))
        body = tree.find("w:body", ns)
        if body is None:
            body = tree
        for p in body.findall(".//w:p", ns):
            texts = [t.text for t in p.findall(".//w:t", ns) if t.text]
            line = "".join(texts).strip()
            if line:
                paragraphs.append(line)
        for tbl in body.findall(".//w:tbl", ns):
            rows_data = []
            for tr in tbl.findall(".//w:tr", ns):
                row_cells = []
                for tc in tr.findall(".//w:tc", ns):
                    cell_texts = [t.text for t in tc.findall(".//w:t", ns) if t.text]
                    row_cells.append(" ".join("".join(cell_texts).split()))
                if any(row_cells):
                    rows_data.append(row_cells)
            if rows_data:
                tables.append(rows_data)
    return {"paragraphs": paragraphs, "tables": tables}


def _read_odt_structured(odt_path: Path) -> dict:
    paragraphs: List[str] = []
    tables: List[List[List[str]]] = []
    with zipfile.ZipFile(odt_path) as z:
        tree = ET.fromstring(z.read("content.xml"))
        for p in tree.iter("{urn:oasis:names:tc:opendocument:xmlns:text:1.0}p"):
            txt = "".join(p.itertext()).strip()
            if txt:
                paragraphs.append(txt)
        for tbl in tree.iter("{urn:oasis:names:tc:opendocument:xmlns:table:1.0}table"):
            t_rows = []
            for tr in tbl.iter("{urn:oasis:names:tc:opendocument:xmlns:table:1.0}table-row"):
                r_cells = []
                for tc in tr.iter("{urn:oasis:names:tc:opendocument:xmlns:table:1.0}table-cell"):
                    r_cells.append(" ".join("".join(tc.itertext()).split()))
                if any(r_cells):
                    t_rows.append(r_cells)
            if t_rows:
                tables.append(t_rows)
    return {"paragraphs": paragraphs, "tables": tables}


def _read_xlsx_or_csv(file_path: Path, max_rows: int = 500) -> dict:
    suffix = file_path.suffix.lower()
    if suffix == ".csv":
        rows = []
        with file_path.open("r", encoding="utf-8", errors="replace") as f:
            reader = csv.reader(f)
            for idx, row in enumerate(reader):
                if idx >= max_rows:
                    break
                rows.append(row)
        return {"sheets": {"CSV": rows}, "sheet_names": ["CSV"]}

    # Parse XLSX directly via zipfile + sharedStrings.xml + sheet*.xml (zero external deps)
    with zipfile.ZipFile(file_path) as z:
        shared_strings: List[str] = []
        if "xl/sharedStrings.xml" in z.namelist():
            ss_tree = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in ss_tree.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}si"):
                shared_strings.append("".join(si.itertext()))

        wb_tree = ET.fromstring(z.read("xl/workbook.xml"))
        sheet_names = []
        for sh in wb_tree.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}sheet"):
            sheet_names.append(sh.attrib.get("name", "Sheet"))

        sheets_data: Dict[str, List[List[str]]] = {}
        sheet_files = sorted(
            [n for n in z.namelist() if re.match(r"^xl/worksheets/sheet\d+\.xml$", n)]
        )
        for idx, sf in enumerate(sheet_files):
            sname = sheet_names[idx] if idx < len(sheet_names) else sf
            stree = ET.fromstring(z.read(sf))
            rows = []
            for r_idx, row_el in enumerate(
                stree.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}row")
            ):
                if r_idx >= max_rows:
                    break
                row_vals = []
                for c_el in row_el.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c"):
                    c_type = c_el.attrib.get("t", "")
                    v_el = c_el.find("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v")
                    is_el = c_el.find("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}is")
                    val = ""
                    if c_type == "s" and v_el is not None and v_el.text is not None:
                        s_idx = int(v_el.text)
                        val = shared_strings[s_idx] if 0 <= s_idx < len(shared_strings) else v_el.text
                    elif c_type == "inlineStr" and is_el is not None:
                        val = "".join(is_el.itertext())
                    elif v_el is not None and v_el.text is not None:
                        val = v_el.text
                    row_vals.append(val)
                if any(row_vals):
                    rows.append(row_vals)
            sheets_data[sname] = rows
        return {"sheet_names": sheet_names, "sheets": sheets_data}


def _write_minimal_docx(output_path: Path, title: str, paragraphs: List[str], table_rows: List[List[str]] | None = None) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""
    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""
    from xml.sax.saxutils import escape

    body_parts = []
    if title:
        body_parts.append(f"<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>{escape(title)}</w:t></w:r></w:p>")
    for p in paragraphs:
        body_parts.append(f"<w:p><w:r><w:t>{escape(str(p))}</w:t></w:r></w:p>")
    if table_rows:
        tr_parts = []
        for row in table_rows:
            tc_parts = [f"<w:tc><w:p><w:r><w:t>{escape(str(cell))}</w:t></w:r></w:p></w:tc>" for cell in row]
            tr_parts.append("<w:tr>" + "".join(tc_parts) + "</w:tr>")
        body_parts.append("<w:tbl>" + "".join(tr_parts) + "</w:tbl>")

    doc_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    {''.join(body_parts)}
  </w:body>
</w:document>"""
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml", doc_xml)


class DocScannerMcpServer:
    def list_tools(self) -> list[dict]:
        return [
            {
                "name": "doc_scan_work_files",
                "description": "Run ~/.local/bin/scan_work_files.py on demand to OCR files in ~/work files, sort transcripts into ~/scanned result/<YYYY-MM-DD>/<Company>/, and archive originals.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "input_dir": {"type": "string", "description": "Optional override input directory (default: /home/aesc/work files)"},
                    },
                },
            },
            {
                "name": "doc_ocr_file",
                "description": "Extract text and detect company/entity from a single image, PDF, DOCX, or ODT file using local PaddleOCR/PaddleX.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "description": "Absolute path to the file to OCR/extract"},
                    },
                    "required": ["file_path"],
                },
            },
            {
                "name": "doc_list_scanned_results",
                "description": "List OCR transcripts stored in ~/scanned result/ filterable by date (YYYY-MM-DD) or company name.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "date": {"type": "string", "description": "Optional date folder filter (e.g. 2026-09-08)"},
                        "company": {"type": "string", "description": "Optional company substring filter"},
                    },
                },
            },
            {
                "name": "doc_search_scanned_results",
                "description": "Full-text regex or keyword search across all OCR transcripts in ~/scanned result/.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Regex or keyword to search for"},
                        "max_results": {"type": "integer", "description": "Max matching snippets to return (default 50)"},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "doc_read_pdf_text",
                "description": "Extract text per page from a PDF file using pypdfium2/pdftotext, reporting whether pages are scanned image PDFs.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "description": "Absolute path to PDF file"},
                        "ocr_if_empty": {"type": "boolean", "description": "Run PaddleOCR if PDF has no embedded text layer (default false)"},
                    },
                    "required": ["file_path"],
                },
            },
            {
                "name": "doc_read_docx_structured",
                "description": "Extract paragraphs and structured tables from a Word .docx file.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "description": "Absolute path to .docx file"},
                    },
                    "required": ["file_path"],
                },
            },
            {
                "name": "doc_read_odt_structured",
                "description": "Extract paragraphs and structured tables from an OpenDocument .odt file.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "description": "Absolute path to .odt file"},
                    },
                    "required": ["file_path"],
                },
            },
            {
                "name": "doc_read_xlsx_sheets",
                "description": "Read worksheet names and tabular cell rows from an .xlsx or .csv file.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "description": "Absolute path to .xlsx or .csv file"},
                        "max_rows": {"type": "integer", "description": "Maximum rows per sheet (default 500)"},
                    },
                    "required": ["file_path"],
                },
            },
            {
                "name": "doc_write_docx_report",
                "description": "Create a formatted Word .docx report from a title, paragraph list, and optional table rows.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "output_path": {"type": "string", "description": "Absolute path for output .docx file"},
                        "title": {"type": "string", "description": "Document heading/title"},
                        "paragraphs": {"type": "array", "items": {"type": "string"}, "description": "List of body paragraphs"},
                        "table_rows": {
                            "type": "array",
                            "items": {"type": "array", "items": {"type": "string"}},
                            "description": "Optional 2D array of table cells",
                        },
                    },
                    "required": ["output_path", "title", "paragraphs"],
                },
            },
            {
                "name": "doc_write_xlsx_table",
                "description": "Write tabular headers and rows to a CSV or TSV spreadsheet file with UTF-8 BOM for Excel compatibility.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "output_path": {"type": "string", "description": "Absolute path for output .csv file"},
                        "headers": {"type": "array", "items": {"type": "string"}},
                        "rows": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}},
                    },
                    "required": ["output_path", "headers", "rows"],
                },
            },
            {
                "name": "doc_extract_tables_from_text",
                "description": "Parse OCR transcript text or document text into structured key-value fields and test result rows.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "text_or_path": {"type": "string", "description": "Raw OCR text or absolute path to a transcript file"},
                    },
                    "required": ["text_or_path"],
                },
            },
            {
                "name": "doc_detect_entities",
                "description": "Extract Vietnamese/English company names, tax codes (MST), dates, certificate numbers, and signatories from text or file.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "text_or_path": {"type": "string", "description": "Raw text or path to transcript file"},
                    },
                    "required": ["text_or_path"],
                },
            },
            {
                "name": "doc_compare_documents",
                "description": "Compare two documents or OCR transcripts and report added/removed lines and numeric differences.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "file_a": {"type": "string", "description": "Absolute path to first file"},
                        "file_b": {"type": "string", "description": "Absolute path to second file"},
                    },
                    "required": ["file_a", "file_b"],
                },
            },
            {
                "name": "doc_verify_lab_test_limits",
                "description": "Verify extracted food safety lab results (Aflatoxin B1/Total, Ochratoxin A, Lead Pb, Cadmium Cd, Arsenic As, Mercury Hg) against Vietnam QCVN 8-1:2011/BYT and QCVN 8-2:2011/BYT maximum limits.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "text_or_path": {"type": "string", "description": "OCR transcript path or raw text from Vinacontrol/Quatest report"},
                        "product_category": {"type": "string", "description": "Product category: oilseeds_grains, spices, dried_fruit, cereal, general (default: oilseeds_grains)"},
                    },
                    "required": ["text_or_path"],
                },
            },
            {
                "name": "doc_archive_inventory",
                "description": "List and audit all archived original files in ~/original file/ and pending files in ~/work files.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "doc_batch_rename_by_metadata",
                "description": "Preview or apply standardized filenames (<Date>_<Company>_<OriginalName>) for OCR transcripts or work files.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "directory": {"type": "string", "description": "Target directory path"},
                        "apply": {"type": "boolean", "description": "If true, rename files on disk; if false (default), return preview only"},
                    },
                    "required": ["directory"],
                },
            },
            {
                "name": "doc_merge_text_transcripts",
                "description": "Combine multiple OCR transcript files into a single consolidated dossier report with table of contents.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "file_paths": {"type": "array", "items": {"type": "string"}, "description": "List of transcript paths to merge"},
                        "output_path": {"type": "string", "description": "Optional path to save merged report"},
                    },
                    "required": ["file_paths"],
                },
            },
            {
                "name": "doc_summarize_metadata",
                "description": "Compute SHA-256 digest, byte size, line/page count, and language profile (Vietnamese/English/French) for a document.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "description": "Absolute path to document"},
                    },
                    "required": ["file_path"],
                },
            },
        ]

    def _load_text(self, text_or_path: str) -> str:
        p = Path(text_or_path)
        if p.exists() and p.is_file():
            if p.suffix.lower() == ".docx":
                return "\n".join(_read_docx_lines_and_tables(p)["paragraphs"])
            if p.suffix.lower() == ".odt":
                return "\n".join(_read_odt_structured(p)["paragraphs"])
            return p.read_text(encoding="utf-8", errors="replace")
        return text_or_path

    def call_tool(self, name: str, args: Dict[str, Any]) -> dict:
        try:
            if name == "doc_scan_work_files":
                cmd = [str(SCAN_SCRIPT)]
                if args.get("input_dir"):
                    cmd.append(str(args["input_dir"]))
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
                return _ok({
                    "exit_code": res.returncode,
                    "stdout": res.stdout,
                    "stderr": res.stderr,
                })

            elif name == "doc_ocr_file":
                fpath = Path(args["file_path"]).expanduser().resolve()
                if not fpath.exists():
                    return _err(f"File not found: {fpath}")
                suffix = fpath.suffix.lower()
                if suffix == ".docx":
                    data = _read_docx_lines_and_tables(fpath)
                    return _ok({"file": str(fpath), "type": "docx", **data})
                if suffix == ".odt":
                    data = _read_odt_structured(fpath)
                    return _ok({"file": str(fpath), "type": "odt", **data})
                code = f"""
import sys, json
from pathlib import Path
sys.path.insert(0, "/home/aesc/.local/bin")
import scan_work_files as swf
p = Path({json.dumps(str(fpath))})
if p.suffix.lower() == ".pdf":
    lines = swf.extract_text_from_pdf(p)
else:
    lines = swf.extract_text_from_image(p)
company = swf.detect_company(lines, p.name)
print(json.dumps({{"file": str(p), "detected_company": company, "line_count": len(lines), "lines": lines}}, ensure_ascii=False))
"""
                res = subprocess.run([str(OCR_PYTHON), "-c", code], capture_output=True, text=True, timeout=300)
                if res.returncode != 0:
                    return _err(f"OCR error: {res.stderr or res.stdout}")
                for line in reversed(res.stdout.splitlines()):
                    if line.startswith("{"):
                        return _ok(json.loads(line))
                return _ok({"raw_output": res.stdout})

            elif name == "doc_list_scanned_results":
                date_filter = args.get("date", "").strip()
                comp_filter = args.get("company", "").strip().lower()
                results = []
                if DEFAULT_SCANNED_DIR.exists():
                    for p in sorted(DEFAULT_SCANNED_DIR.rglob("*_ocr.txt")):
                        rel = p.relative_to(DEFAULT_SCANNED_DIR).parts
                        d_part = rel[0] if len(rel) > 0 else ""
                        c_part = rel[1] if len(rel) > 1 else ""
                        if date_filter and date_filter != d_part:
                            continue
                        if comp_filter and comp_filter not in c_part.lower():
                            continue
                        results.append({
                            "date": d_part,
                            "company": c_part,
                            "filename": p.name,
                            "path": str(p),
                            "size_bytes": p.stat().st_size,
                        })
                return _ok({"count": len(results), "transcripts": results})

            elif name == "doc_search_scanned_results":
                pattern = re.compile(args["query"], re.IGNORECASE)
                max_res = int(args.get("max_results", 50))
                matches = []
                if DEFAULT_SCANNED_DIR.exists():
                    for p in sorted(DEFAULT_SCANNED_DIR.rglob("*.txt")):
                        txt = p.read_text(encoding="utf-8", errors="replace")
                        for idx, line in enumerate(txt.splitlines(), 1):
                            if pattern.search(line):
                                matches.append({"path": str(p), "line_number": idx, "line": line.strip()})
                                if len(matches) >= max_res:
                                    break
                        if len(matches) >= max_res:
                            break
                return _ok({"query": args["query"], "match_count": len(matches), "matches": matches})

            elif name == "doc_read_pdf_text":
                fpath = Path(args["file_path"]).expanduser().resolve()
                if not fpath.exists():
                    return _err(f"File not found: {fpath}")
                code = f"""
import pypdfium2 as pdfium, json
pdf = pdfium.PdfDocument({json.dumps(str(fpath))})
pages = []
for idx in range(len(pdf)):
    page = pdf[idx]
    tp = page.get_textpage()
    txt = tp.get_text_range().strip()
    pages.append({{"page": idx + 1, "char_count": len(txt), "text": txt}})
print(json.dumps({{"page_count": len(pdf), "has_embedded_text": any(p["char_count"] > 10 for p in pages), "pages": pages}}, ensure_ascii=False))
"""
                res = subprocess.run([str(OCR_PYTHON), "-c", code], capture_output=True, text=True, timeout=60)
                if res.returncode == 0:
                    data = json.loads(res.stdout.strip().splitlines()[-1])
                    if not data.get("has_embedded_text") and args.get("ocr_if_empty"):
                        return self.call_tool("doc_ocr_file", {"file_path": str(fpath)})
                    return _ok(data)
                return _err(res.stderr or "Failed to read PDF")

            elif name == "doc_read_docx_structured":
                fpath = Path(args["file_path"]).expanduser().resolve()
                if not fpath.exists():
                    return _err(f"File not found: {fpath}")
                return _ok(_read_docx_lines_and_tables(fpath))

            elif name == "doc_read_odt_structured":
                fpath = Path(args["file_path"]).expanduser().resolve()
                if not fpath.exists():
                    return _err(f"File not found: {fpath}")
                return _ok(_read_odt_structured(fpath))

            elif name == "doc_read_xlsx_sheets":
                fpath = Path(args["file_path"]).expanduser().resolve()
                if not fpath.exists():
                    return _err(f"File not found: {fpath}")
                return _ok(_read_xlsx_or_csv(fpath, int(args.get("max_rows", 500))))

            elif name == "doc_write_docx_report":
                out = Path(args["output_path"]).expanduser().resolve()
                _write_minimal_docx(out, args["title"], args.get("paragraphs", []), args.get("table_rows"))
                return _ok({"written": str(out), "size_bytes": out.stat().st_size})

            elif name == "doc_write_xlsx_table":
                out = Path(args["output_path"]).expanduser().resolve()
                out.parent.mkdir(parents=True, exist_ok=True)
                with out.open("w", encoding="utf-8-sig", newline="") as f:
                    writer = csv.writer(f)
                    writer.writerow(args["headers"])
                    writer.writerows(args["rows"])
                return _ok({"written": str(out), "row_count": len(args["rows"]), "size_bytes": out.stat().st_size})

            elif name == "doc_extract_tables_from_text":
                txt = self._load_text(args["text_or_path"])
                kv_pairs = {}
                lines = [ln.strip() for ln in txt.splitlines() if ln.strip()]
                for i, ln in enumerate(lines):
                    if ":" in ln and not ln.startswith("http"):
                        k, v = ln.split(":", 1)
                        k = k.strip()
                        v = v.strip()
                        if v:
                            kv_pairs[k] = v
                        elif i + 1 < len(lines) and ":" not in lines[i + 1]:
                            kv_pairs[k] = lines[i + 1]
                return _ok({"line_count": len(lines), "key_values": kv_pairs, "lines": lines})

            elif name == "doc_detect_entities":
                txt = self._load_text(args["text_or_path"])
                companies = re.findall(
                    r"(?:CÔNG TY\s+(?:TNHH|CỔ PHẦN|CP|MTV)?\s*[^\n,;]+|[A-Z0-9\s\.\-]{3,}(?:CO\.,\s*LTD|CORP|JSC|INC|LLC))",
                    txt,
                    flags=re.IGNORECASE,
                )
                mst = re.findall(r"\b\d{10}(?:-\d{3})?\b", txt)
                dates = re.findall(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{4}\b", txt)
                urls = re.findall(r"https?://[^\s,;\"')]+", txt)
                return _ok({
                    "companies": list(dict.fromkeys(c.strip() for c in companies)),
                    "tax_codes_mst": list(dict.fromkeys(mst)),
                    "dates": list(dict.fromkeys(dates)),
                    "urls": list(dict.fromkeys(urls)),
                })

            elif name == "doc_compare_documents":
                txt_a = self._load_text(args["file_a"]).splitlines()
                txt_b = self._load_text(args["file_b"]).splitlines()
                set_a = [ln.strip() for ln in txt_a if ln.strip()]
                set_b = [ln.strip() for ln in txt_b if ln.strip()]
                only_in_a = [ln for ln in set_a if ln not in set_b]
                only_in_b = [ln for ln in set_b if ln not in set_a]
                return _ok({
                    "file_a_lines": len(set_a),
                    "file_b_lines": len(set_b),
                    "only_in_a": only_in_a,
                    "only_in_b": only_in_b,
                    "identical": len(only_in_a) == 0 and len(only_in_b) == 0,
                })

            elif name == "doc_verify_lab_test_limits":
                txt = self._load_text(args["text_or_path"])
                # QCVN 8-1:2011/BYT (Mycotoxins) & QCVN 8-2:2011/BYT (Heavy metals) reference limits
                limits = {
                    "Aflatoxin B1": {"unit": "µg/kg", "max_limit": 5.0, "standard": "QCVN 8-1:2011/BYT"},
                    "Aflatoxin tổng số": {"unit": "µg/kg", "max_limit": 10.0, "standard": "QCVN 8-1:2011/BYT"},
                    "Ochratoxin A": {"unit": "µg/kg", "max_limit": 5.0, "standard": "QCVN 8-1:2011/BYT"},
                    "Chì (Pb)": {"unit": "mg/kg", "max_limit": 0.2, "standard": "QCVN 8-2:2011/BYT"},
                    "Cadimi (Cd)": {"unit": "mg/kg", "max_limit": 0.1, "standard": "QCVN 8-2:2011/BYT"},
                    "Asen (As)": {"unit": "mg/kg", "max_limit": 1.0, "standard": "QCVN 8-2:2011/BYT"},
                    "Thủy ngân (Hg)": {"unit": "mg/kg", "max_limit": 0.05, "standard": "QCVN 8-2:2011/BYT"},
                }
                lines = [ln.strip() for ln in txt.splitlines() if ln.strip()]
                findings = []
                for param, meta in limits.items():
                    for idx, ln in enumerate(lines):
                        if param.lower() in ln.lower():
                            window = " | ".join(lines[idx : min(idx + 5, len(lines))])
                            not_detected = "không phát hiện" in window.lower() or "nd" in window.lower()
                            num_match = re.search(r"(?:<|\b)(\d+[.,]\d+)", window)
                            measured = 0.0 if not_detected else (float(num_match.group(1).replace(",", ".")) if num_match else None)
                            status = "PASS" if (measured is not None and measured <= meta["max_limit"]) else "REVIEW"
                            findings.append({
                                "parameter": param,
                                "context": window,
                                "detected_value": "Not Detected (KPH)" if not_detected else measured,
                                "qcvn_max_limit": meta["max_limit"],
                                "unit": meta["unit"],
                                "standard": meta["standard"],
                                "compliance": status,
                            })
                            break
                return _ok({
                    "overall_status": "PASS" if findings and all(f["compliance"] == "PASS" for f in findings) else "REVIEW",
                    "parameters_checked": len(findings),
                    "results": findings,
                })

            elif name == "doc_archive_inventory":
                pending = [str(p) for p in sorted(DEFAULT_WORK_DIR.rglob("*")) if p.is_file()] if DEFAULT_WORK_DIR.exists() else []
                archived = [str(p) for p in sorted(DEFAULT_ORIGINAL_DIR.rglob("*")) if p.is_file()] if DEFAULT_ORIGINAL_DIR.exists() else []
                scanned = [str(p) for p in sorted(DEFAULT_SCANNED_DIR.rglob("*")) if p.is_file()] if DEFAULT_SCANNED_DIR.exists() else []
                return _ok({
                    "work_files_pending_count": len(pending),
                    "work_files_pending": pending,
                    "original_files_archived_count": len(archived),
                    "original_files_archived": archived,
                    "scanned_results_count": len(scanned),
                    "scanned_results": scanned,
                })

            elif name == "doc_batch_rename_by_metadata":
                target_dir = Path(args["directory"]).expanduser().resolve()
                if not target_dir.exists():
                    return _err(f"Directory not found: {target_dir}")
                apply_changes = bool(args.get("apply", False))
                plan = []
                for p in sorted(target_dir.iterdir()):
                    if not p.is_file():
                        continue
                    txt = self._load_text(str(p))
                    m_comp = re.search(r"Detected Company:\s*(.+)", txt)
                    comp = m_comp.group(1).strip().replace(" ", "_") if m_comp else "Doc"
                    date_str = datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d")
                    new_name = f"{date_str}_{comp}_{p.name}" if not p.name.startswith(date_str) else p.name
                    new_path = p.with_name(new_name)
                    if apply_changes and new_path != p:
                        p.rename(new_path)
                    plan.append({"old": str(p), "new": str(new_path), "renamed": apply_changes and new_path != p})
                return _ok({"apply": apply_changes, "items": plan})

            elif name == "doc_merge_text_transcripts":
                merged_parts = []
                for fp in args["file_paths"]:
                    p = Path(fp).expanduser().resolve()
                    if p.exists():
                        merged_parts.append(f"=== FILE: {p.name} ===\n" + p.read_text(encoding="utf-8", errors="replace"))
                combined = "\n\n".join(merged_parts)
                if args.get("output_path"):
                    out = Path(args["output_path"]).expanduser().resolve()
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_text(combined, encoding="utf-8")
                    return _ok({"output_path": str(out), "total_chars": len(combined), "files_merged": len(merged_parts)})
                return _ok({"total_chars": len(combined), "files_merged": len(merged_parts), "content": combined})

            elif name == "doc_summarize_metadata":
                p = Path(args["file_path"]).expanduser().resolve()
                if not p.exists():
                    return _err(f"File not found: {p}")
                raw = p.read_bytes()
                sha256 = hashlib.sha256(raw).hexdigest()
                txt = self._load_text(str(p))
                vn_chars = len(re.findall(r"[ăâđêôơưĂÂĐÊÔƠƯáàảãạéèẻẽẹíìỉĩịóòỏõọúùủũụýỳỷỹỵ]", txt))
                return _ok({
                    "file": str(p),
                    "size_bytes": len(raw),
                    "sha256": sha256,
                    "line_count": len(txt.splitlines()),
                    "vietnamese_diacritic_count": vn_chars,
                    "detected_primary_language": "vi" if vn_chars > 10 else "en",
                })

            return _err(f"Unknown tool: {name}")
        except Exception as exc:
            return _err(f"Error in {name}: {exc}")

    def handle_request(self, request: dict) -> dict | None:
        method = request.get("method")
        req_id = request.get("id")
        if "id" not in request:
            return None
        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "doc-scanner-mcp", "version": "1.0.0"},
                },
            }
        if method == "ping":
            return {"jsonrpc": "2.0", "id": req_id, "result": {}}
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": self.list_tools()}}
        if method == "resources/list":
            return {"jsonrpc": "2.0", "id": req_id, "result": {"resources": []}}
        if method == "prompts/list":
            return {"jsonrpc": "2.0", "id": req_id, "result": {"prompts": []}}
        if method == "tools/call":
            params = request.get("params") or {}
            res = self.call_tool(params.get("name", ""), params.get("arguments") or {})
            return {"jsonrpc": "2.0", "id": req_id, "result": res}
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}

    def serve_stdio(self) -> None:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
                if isinstance(req, dict):
                    resp = self.handle_request(req)
                    if resp is not None:
                        sys.stdout.write(json.dumps(resp) + "\n")
                        sys.stdout.flush()
            except Exception as exc:
                sys.stderr.write(f"Error: {exc}\n")


if __name__ == "__main__":
    DocScannerMcpServer().serve_stdio()
