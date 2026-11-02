---
name: web-table-invoice-scraper
description: "Extract HTML tables, links, forms, and files from pages."
version: 1.0.0
author: Trong (aesc), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [scraping, html-tables, download, csv, forms]
---

# Web Table, Form & File Extractor

## When to Use
- Extracting HTML `<table>` data (tariff schedules, exchange rates, shipping schedules, price lists) or downloading documents into `~/work files` or `~/Downloads`.

## Tools & MCP Integration
- `mcp_browser_automation_mcp_browser_extract_html_tables`: Parses all HTML tables from a URL or local file into structured 2D arrays.
- `mcp_browser_automation_mcp_browser_extract_links_and_forms`: Lists all `<a href>` links and `<input>` fields.
- `mcp_browser_automation_mcp_browser_download_file`: Downloads a file and verifies its byte size and SHA-256 hash.
- `mcp_doc_scanner_mcp_doc_write_xlsx_table`: Saves extracted tables to CSV/Excel.

## Procedure
1. Call `browser_extract_html_tables` on the target URL or saved HTML file.
2. Convert the extracted table into CSV/XLSX via `doc_write_xlsx_table` if spreadsheet output is needed.
3. For file downloads, use `browser_download_file` and verify the returned SHA-256 digest.

## Verification
- Extracted row/column counts and downloaded file SHA-256 hashes are verified.
