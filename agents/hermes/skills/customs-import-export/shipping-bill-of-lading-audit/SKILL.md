---
name: shipping-bill-of-lading-audit
description: "Audit Ocean Bill of Lading (MBL/HBL) and Air Waybills."
version: 1.0.0
author: Trong (aesc), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [bill-of-lading, bl, awb, shipping, manifest]
---

# Bill of Lading (B/L) & E-Manifest Auditor

## When to Use
- Auditing Master B/L (MBL), House B/L (HBL), Sea Waybill, Surrendered/Telex Release B/L, or Air Waybill (MAWB/HAWB).
- Checking container/seal numbers, Freight Prepaid vs Collect, Shipper/Consignee/Notify Party, and VNSW e-Manifest submission accuracy.

## Tools & MCP Integration
- `mcp_customs_legal_mcp_customs_parse_bill_of_lading`: Extracts B/L number, 11-char ISO container numbers, gross weight, CBM, and freight terms.
- `mcp_customs_legal_mcp_customs_cross_check_shipping_docs`: Audits B/L against Commercial Invoice, Packing List, and C/O.

## Procedure
1. Parse the B/L text using `customs_parse_bill_of_lading`.
2. Cross-check container numbers, package counts, and gross weight against the Packing List via `customs_cross_check_shipping_docs`.
3. Verify endorsement requirements before D/O pickup.

## Verification
- All container numbers, weights, packages, and freight terms are verified against sibling shipping documents.
