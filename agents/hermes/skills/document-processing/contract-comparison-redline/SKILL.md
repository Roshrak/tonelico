---
name: contract-comparison-redline
description: "Diff two document or contract versions and report changes."
version: 1.0.0
author: Trong (aesc), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [diff, redline, contract, comparison, docx]
---

# Contract & Document Redline Comparison

## When to Use
- Comparing two versions of a contract, invoice, certificate, or OCR transcript to identify added, removed, or altered clauses and numbers.

## Tools & MCP Integration
- `mcp_doc_scanner_mcp_doc_compare_documents`: Compares two files (`.docx`, `.odt`, `.txt`, OCR transcripts) and lists exact line additions and removals.
- `mcp_doc_scanner_mcp_doc_read_docx_structured`: Reads paragraphs and tables from Word documents.

## Procedure
1. Run `mcp_doc_scanner_mcp_doc_compare_documents` on `file_a` and `file_b`.
2. Categorize differences into: (a) Financial/Numeric changes, (b) Dates/Deadlines, (c) Legal obligations/Liability, and (d) Formatting/Typos.
3. Present a clear side-by-side redline summary.

## Verification
- Every added and removed line between the two files is accounted for in the diff report.
