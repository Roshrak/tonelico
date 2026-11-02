---
name: hs-code-tariff-classification
description: "Classify goods by HS Code and lookup Vietnam tariff rates."
version: 1.0.0
author: Trong (aesc), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [hs-code, tariff, customs, mfn, fta]
---

# HS Code & Vietnam Import-Export Tariff Classification

## When to Use
- Classifying commodities into 8-digit Vietnam HS codes (Biểu thuế xuất nhập khẩu) applying WCO General Rules of Interpretation (GRI 1–6).
- Comparing MFN duty rates against FTA preferential rates (ATIGA Form D, ACFTA Form E, EVFTA EUR.1, CPTPP, AKFTA Form AK) and Import VAT (8% / 10%).

## Tools & MCP Integration
- `mcp_customs_legal_mcp_customs_hs_code_lookup`: Searches HS codes, descriptions (VN/EN), MFN/FTA tariff rates, VAT, and specialized inspection flags.
- `mcp_customs_legal_mcp_customs_calculate_import_duty`: Computes exact duty and VAT in VND.

## Procedure
1. Query `mcp_customs_legal_mcp_customs_hs_code_lookup` with the HS prefix or commodity keyword.
2. Apply GRI 1 and GRI 3/6 (material composition, processing state such as raw vs roasted).
3. Compare MFN rate vs FTA rates and note whether a C/O is cost-effective.

## Verification
- Report the 8-digit HS code, Vietnamese & English description, MFN rate, applicable FTA rates, VAT rate, and any specialized inspection requirement.
