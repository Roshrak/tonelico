---
name: dossier-archiving-organizer
description: "Audit, search, merge, and organize scanned document files."
version: 1.0.0
author: Trong (aesc), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [archive, dossier, search, rename, inventory]
---

# Dossier Archiving & Transcript Organizer

## When to Use
- Searching across all historical OCR transcripts in `~/scanned result/`.
- Auditing `~/work files` and `~/original file/` or merging multiple page scans into a single company dossier.

## Tools & MCP Integration
- `mcp_doc_scanner_mcp_doc_list_scanned_results`: Lists transcripts by date and company.
- `mcp_doc_scanner_mcp_doc_search_scanned_results`: Regex search across all scanned transcripts.
- `mcp_doc_scanner_mcp_doc_merge_text_transcripts`: Merges multiple transcripts into one consolidated file.
- `mcp_doc_scanner_mcp_doc_batch_rename_by_metadata`: Previews or applies standardized `<Date>_<Company>_<Name>` naming.

## Procedure
1. List or search transcripts using `doc_list_scanned_results` or `doc_search_scanned_results`.
2. Preview any batch rename with `apply=False` before setting `apply=True`.
3. Merge related transcripts with `doc_merge_text_transcripts` when assembling a complete customs or legal filing.

## Verification
- Confirm target files exist and checksums/byte sizes match with `doc_summarize_metadata`.
