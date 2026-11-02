---
name: diploma-naric-verification
description: "Process foreign diplomas and Vietnam NARIC recognition."
version: 1.0.0
author: Trong (aesc), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [diploma, naric, education, legalization, recognition]
---

# Foreign Diploma & Vietnam NARIC Recognition Processor

## When to Use
- Processing foreign university degrees (e.g. Normandie Business School, joint French/Vietnamese programs) and Certificate of Recognition (Giấy công nhận văn bằng) issued by Cục Quản lý Chất lượng - Bộ GD&ĐT.
- Checking Vietnam National Qualifications Framework (Khung trình độ quốc gia Việt Nam - Bậc 6/7/8) equivalence and `naric.edu.vn` verification links.

## Tools & MCP Integration
- `mcp_customs_legal_mcp_legal_diploma_recognition_check`: Checks Circular 13/2021/TT-BGDĐT recognition rules and NQF level mapping.
- `mcp_browser_automation_mcp_browser_naric_diploma_lookup`: Returns lookup metadata and portal URL (`https://naric.edu.vn/front/tra-cuu-van-bang`).
- `mcp_doc_scanner_mcp_doc_ocr_file`: Extracts text from scanned diplomas and recognition certificates.

## Procedure
1. Extract holder name, date of birth, issuing institution, country, degree level, training mode, and certificate number from the scan.
2. Run `legal_diploma_recognition_check` and `browser_naric_diploma_lookup`.
3. Verify the online lookup URL and certificate registration number.

## Verification
- All personal and academic fields match the OCR transcript and official NARIC structure.
