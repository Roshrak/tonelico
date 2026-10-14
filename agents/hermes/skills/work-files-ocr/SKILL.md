---
name: work-files-ocr
description: "Use when user requests to scan documents, process work files, or sort scanned papers by company."
version: 1.0.0
author: Antigravity & Hermes
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [ocr, scanner, paddleocr, documents, pdf, docx, sorting]
---

# Work Files OCR & Company Sorting Protocol

## Trigger
- User explicitly says "scan my file" (or contains "scan my file") in their message.
- NEVER run on bare "scan" or other commands.
- NEVER run as a background service, daemon, or watcher.

## Action
Run the dedicated scanning and sorting tool on demand:
```bash
~/.local/bin/scan_work_files.py
```

## Workflow & Folders
1. Input folder: `~/work files` (images, PDFs, DOCX, ODT).
2. OCR engine: Local PaddleOCR/PaddleX (PP-OCRv6 + UVDoc).
3. Text analysis: Detects company / customer / issuer / organization names.
4. Original files archive: `~/original file/<YYYY-MM-DD>/`
   - Scanned original files are moved here sorted by date.
5. Scanned results folder: `~/scanned result/<YYYY-MM-DD>/<Company Name>/`
   - Generates `<filename>_ocr.txt` transcripts with full extracted text and metadata sorted by date and company.
6. Resource cleanup: Exits immediately upon completion, freeing 100% of RAM/VRAM.
