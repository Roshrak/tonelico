---
name: invoice-packing-list-extractor
description: "Extract line items and weights from Invoices/Packing Lists."
version: 1.0.0
author: Trong (aesc), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [invoice, packing-list, extraction, customs, xlsx]
---

# Commercial Invoice & Packing List Extractor

## When to Use
- Parsing Commercial Invoices and Packing Lists from PDF, DOCX, XLSX, or OCR transcripts into structured tables.
- Reconciling unit prices, extended line totals, Net Weight (N.W.), Gross Weight (G.W.), CBM volume, and carton counts.

## Tools & MCP Integration
- `mcp_customs_legal_mcp_customs_parse_commercial_invoice`: Extracts invoice number, Incoterm, currency, and totals.
- `mcp_customs_legal_mcp_customs_parse_packing_list`: Extracts net weight, gross weight, CBM, and package count.
- `mcp_customs_legal_mcp_customs_cross_check_shipping_docs`: Audits Invoice vs Packing List vs B/L consistency.
- `mcp_doc_scanner_mcp_doc_write_xlsx_table`: Exports extracted line items to Excel-compatible CSV/XLSX.

## Procedure
1. Extract text/tables from the Invoice and Packing List via `doc-scanner-mcp`.
2. Parse structured fields using `customs_parse_commercial_invoice` and `customs_parse_packing_list`.
3. Verify arithmetic: `sum(quantity * unit_price) == total_invoice_value` and `net_weight_kg <= gross_weight_kg`.
4. Export clean tabular output via `doc_write_xlsx_table` when requested.

## Verification
- Arithmetic totals and weight comparisons are verified mathematically before reporting.
