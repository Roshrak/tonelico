---
name: vietnamese-document-ocr
description: "Extract and clean Vietnamese/bilingual OCR text & entities."
version: 1.0.0
author: Trong (aesc), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [ocr, vietnamese, diacritics, entities, bilingual]
---

# Vietnamese & Bilingual Document OCR Processor

## When to Use
- Reading scanned Vietnamese administrative, legal, academic, or commercial documents where red stamps or scan noise affect diacritics.
- Extracting structured entities (Công ty, Mã số thuế, Số quyết định, Ngày ký, Người ký) from OCR transcripts.

## Tools & MCP Integration
- `mcp_doc_scanner_mcp_doc_ocr_file`: Runs PaddleOCR on images/PDFs.
- `mcp_doc_scanner_mcp_doc_detect_entities`: Extracts Vietnamese/English company names, 10/13-digit MST tax codes, dates, and URLs.
- `mcp_doc_scanner_mcp_doc_extract_tables_from_text`: Converts OCR lines into key-value pairs.
- `vision_analyze`: Inspects cropped regions (signatures, seals) when text OCR is ambiguous.

## Procedure
1. Run `mcp_doc_scanner_mcp_doc_ocr_file` or read existing transcript from `~/scanned result/`.
2. Extract entities and key-value fields with `mcp_doc_scanner_mcp_doc_detect_entities` and `mcp_doc_scanner_mcp_doc_extract_tables_from_text`.
3. Cross-check numeric values, dates, and certificate numbers directly against the source image/PDF using `vision_analyze` if any line has missing diacritics.

## Verification
- All company names, tax codes, certificate numbers, and dates match the raw document evidence with zero fabricated fields.
