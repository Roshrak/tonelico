---
name: vietnam-customs-vnaccs
description: "Prepare and audit Vietnam Customs VNACCS/VCIS declarations."
version: 1.0.0
author: Trong (aesc), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [customs, vnaccs, vcis, declaration, import-export]
---

# Vietnam Customs VNACCS/VCIS Declaration Auditor

## When to Use
- Preparing or auditing a Vietnam Customs electronic declaration (Tờ khai hải quan điện tử VNACCS/VCIS - IDA/IIA/EDA/EIA).
- Selecting the correct declaration type code (Mã loại hình: A11, A12, A41, E11, E21, E31, B11, G11, H11) and predicting Green/Yellow/Red lane routing.

## Tools & MCP Integration
- `mcp_customs_legal_mcp_customs_vnaccs_declaration_check`: Validates VNACCS code, predicts channel (Luồng Xanh/Vàng/Đỏ), and lists mandatory V5 e-dossier attachments.
- `mcp_customs_legal_mcp_customs_cross_check_shipping_docs`: Cross-checks Invoice, Packing List, B/L, and C/O before declaration transmission.

## Procedure
1. Identify the transaction purpose (commercial consumption `A11`, manufacturing `A12`, export processing `E21`, SXXK `E31`, commercial export `B11`).
2. Run `mcp_customs_legal_mcp_customs_vnaccs_declaration_check`.
3. Cross-check all shipping documents with `customs_cross_check_shipping_docs` so zero weight, package, or consignee mismatches trigger a post-clearance amendment.

## Verification
- Declaration type code, lane requirements, and mandatory V5 attachments are explicitly listed and verified.
