---
name: certificate-of-origin-compliance
description: "Validate C/O Forms D, E, AK, EUR.1, CPTPP for tariff relief."
version: 1.0.0
author: Trong (aesc), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [co, certificate-of-origin, form-d, form-e, eur1, customs]
---

# Certificate of Origin (C/O) Compliance Auditor

## When to Use
- Checking Certificate of Origin (C/O Form D, Form E, Form AK, Form AJ, Form VJ, EUR.1, REX, CPTPP) validity so Vietnam Customs accepts preferential tariff rates.
- Auditing Third-Party Invoicing, Issued Retroactively, Back-to-Back C/O, and Origin Criteria (`WO`, `PE`, `RVC 40%`, `CTC`/`CTH`/`CTSH`).

## Tools & MCP Integration
- `mcp_customs_legal_mcp_customs_validate_co_form`: Audits C/O form type, origin criterion, issue vs shipment dates, retroactive flag, and third-party invoicing rules.
- `mcp_customs_legal_mcp_customs_cross_check_shipping_docs`: Checks C/O against B/L and Commercial Invoice.

## Procedure
1. Run `mcp_customs_legal_mcp_customs_validate_co_form` with the C/O fields.
2. Check Box 1 (Exporter), Box 2 (Consignee), Box 7 (Description, 6-digit HS code, Third-Party company name), Box 8 (Origin criterion), Box 10 (Invoice No. & Date), Box 11/12 (Signatures/Stamps), and Box 13 (Ticked flags).
3. Verify direct consignment (B/L through-transport or Non-Manipulation Certificate if transshipped).

## Verification
- Every box requirement and retroactive/third-party tick flag is verified before claiming FTA duty rates.
