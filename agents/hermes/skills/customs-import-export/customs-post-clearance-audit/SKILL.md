---
name: customs-post-clearance-audit
description: "Prepare dossiers for Customs Valuation and KTSTQ audit."
version: 1.0.0
author: Trong (aesc), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [post-clearance-audit, ktstq, customs-valuation, dossier]
---

# Customs Valuation & Post-Clearance Audit (Kiểm tra sau thông quan)

## When to Use
- Preparing a complete import/export legal file for Customs Valuation Consultation (Tham vấn giá), Tax Refund/Exemption Settlement (Báo cáo quyết toán E21/E31), or Post-Clearance Audit (Kiểm tra sau thông quan - KTSTQ).

## Tools & MCP Integration
- `mcp_customs_legal_mcp_customs_dossier_checklist`: Generates the full statutory checklist for the shipment mode and commodity.
- `mcp_customs_legal_mcp_customs_cross_check_shipping_docs`: Detects any discrepancy across Invoice, Packing List, B/L, and C/O.
- `mcp_doc_scanner_mcp_doc_merge_text_transcripts`: Consolidates all scanned dossier documents into one audit packet.

## Procedure
1. Generate the statutory checklist via `customs_dossier_checklist`.
2. Run `customs_cross_check_shipping_docs` to verify 100% alignment across the declaration, contract, invoice, packing list, B/L, C/O, and bank payment swift.
3. Consolidate OCR transcripts and archive records using `doc-scanner-mcp`.

## Verification
- Every required statutory document is accounted for and cross-checked with zero unresolved discrepancies.
