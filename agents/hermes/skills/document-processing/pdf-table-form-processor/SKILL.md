---
name: pdf-table-form-processor
description: "Read, OCR, extract tables, and generate DOCX/CSV from PDFs."
version: 1.0.0
author: Trong (aesc), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [pdf, tables, forms, pypdfium2, docx]
---

# PDF Table & Form Processor

## When to Use
- Inspecting PDFs to determine if they have an embedded text layer or require PaddleOCR.
- Extracting multi-page tables from PDFs into structured JSON, CSV/XLSX, or Word `.docx` reports.

## Tools & MCP Integration
- `mcp_doc_scanner_mcp_doc_read_pdf_text`: Reads PDF text pages and auto-falls back to PaddleOCR when `ocr_if_empty=True`.
- `mcp_doc_scanner_mcp_doc_write_docx_report`: Writes structured `.docx` reports with tables.
- `mcp_doc_scanner_mcp_doc_write_xlsx_table`: Writes tabular data to `.csv` with UTF-8 BOM.

## Procedure
1. Call `mcp_doc_scanner_mcp_doc_read_pdf_text` with `ocr_if_empty=True`.
2. Parse tabular rows and key-value fields with `mcp_doc_scanner_mcp_doc_extract_tables_from_text`.
3. Export the structured output into `.docx` or `.csv` using `doc_write_docx_report` or `doc_write_xlsx_table`.

## Verification
- Output file exists on disk, is non-empty, and preserves all page data from the source PDF.
