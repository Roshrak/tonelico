---
name: food-safety-decree15-compliance
description: "Process Vietnam Decree 15/2018 food safety declarations."
version: 1.0.0
author: Trong (aesc), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [decree-15, food-safety, attp, self-declaration, vinacontrol]
---

# Vietnam Decree 15/2018/NĐ-CP Food Safety Compliance

## When to Use
- Preparing Food Safety Self-Declaration (Bản tự công bố sản phẩm - Mẫu số 01) or Registration of Product Declaration under Decree 15/2018/NĐ-CP.
- Determining State Inspection for Imported Food (Kiểm tra nhà nước về ATTP: Giảm / Thông thường / Chặt) and managing Ministry (Bộ Y tế, Bộ NN&PTNT, Bộ Công Thương).

## Tools & MCP Integration
- `mcp_customs_legal_mcp_customs_food_safety_decree15`: Determines declaration type, managing Ministry, and inspection mode.
- `mcp_customs_legal_mcp_customs_generate_self_declaration`: Generates a ready-to-file Mẫu số 01 Self-Declaration document from company and Vinacontrol/Quatest test certificate data.
- `mcp_doc_scanner_mcp_doc_verify_lab_test_limits`: Verifies the underlying lab test report against QCVN 8-1 and 8-2.

## Procedure
1. Verify the lab test report passes all QCVN mycotoxin and heavy metal limits using `doc_verify_lab_test_limits`.
2. Call `customs_food_safety_decree15` to confirm whether Self-Declaration or Registration applies and which Ministry has jurisdiction.
3. Generate the complete Self-Declaration text or file via `customs_generate_self_declaration`.

## Verification
- Generated Self-Declaration cites the exact lab certificate number, testing center, and applicable QCVN standards.
