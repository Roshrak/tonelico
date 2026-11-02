---
name: ocr-batch-scanner
description: "Batch OCR scan work files and sort transcripts by company."
version: 1.0.0
author: Trong (aesc), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [ocr, paddleocr, scanner, documents, batch]
---

# OCR Batch Scanner & Company Sorter

## When to Use
- User says "scan my file" or asks to batch-scan documents in `~/work files`.
- Sorting scanned PDFs, DOCX, ODT, or images into `~/scanned result/<YYYY-MM-DD>/<Company Name>/` and archiving originals into `~/original file/<YYYY-MM-DD>/`.

## Tools & MCP Integration
- `mcp_doc_scanner_mcp_doc_scan_work_files`: Runs `~/.local/bin/scan_work_files.py` on demand.
- `mcp_doc_scanner_mcp_doc_ocr_file`: Runs PaddleOCR (`PP-OCRv6`) on a single image or PDF.
- `mcp_doc_scanner_mcp_doc_list_scanned_results`: Lists generated `*_ocr.txt` transcripts.
- `mcp_doc_scanner_mcp_doc_archive_inventory`: Audits pending, scanned, and archived files.

## Procedure
1. Check `~/work files` inventory with `mcp_doc_scanner_mcp_doc_archive_inventory`.
2. Execute `mcp_doc_scanner_mcp_doc_scan_work_files` (or `~/.local/bin/scan_work_files.py` via `terminal`).
3. Verify generated transcripts under `~/scanned result/<YYYY-MM-DD>/` and moved originals under `~/original file/<YYYY-MM-DD>/`.
4. Confirm the OCR process exited cleanly to free 100% of RAM/VRAM.

## Verification
- Every file from `~/work files` is moved to `~/original file/<YYYY-MM-DD>/` and has a non-empty `*_ocr.txt` transcript in `~/scanned result/<YYYY-MM-DD>/<Company>/`.
