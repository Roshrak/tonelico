---
name: import-duty-vat-calculator
description: "Calculate CIF customs value, Import Duty, SCT, and VAT."
version: 1.0.0
author: Trong (aesc), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [duty, vat, tax, cif, customs-valuation]
---

# Import Duty, SCT & VAT Landed Cost Calculator

## When to Use
- Calculating Vietnam Customs taxable value (Trị giá tính thuế CIF), Import Duty (Thuế NK), Special Consumption Tax (Thuế TTĐB), and Import VAT (Thuế GTGT hàng NK).

## Tools & MCP Integration
- `mcp_customs_legal_mcp_customs_calculate_import_duty`: Computes exact CIF VND value, Import Duty, SCT, Import VAT, and total landed cost.
- `mcp_customs_legal_mcp_customs_incoterms_calculator`: Converts EXW/FOB prices to CIF taxable value.

## Procedure
1. Determine whether the invoice price is EXW/FCA/FOB (add international freight + insurance to reach CIF) or already CIF/CIP.
2. Call `mcp_customs_legal_mcp_customs_calculate_import_duty` with invoice value, freight, insurance, customs exchange rate, duty %, SCT %, and VAT %.
3. Present the step-by-step tax breakdown in VND.

## Verification
- All tax figures in VND match the deterministic output of `customs_calculate_import_duty`.
