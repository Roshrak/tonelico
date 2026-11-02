---
name: lab-test-certificate-analysis
description: "Analyze Vinacontrol/Quatest lab certificates against QCVN."
version: 1.0.0
author: Trong (aesc), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [vinacontrol, quatest, qcvn, food-safety, coa, lab-test]
---

# Lab Test Certificate (COA) & QCVN Compliance Analyzer

## When to Use
- Auditing laboratory test reports (Phiếu kết quả thử nghiệm) from Vinacontrol, Quatest, SGS, Eurofins, or CASE.
- Checking mycotoxins (Aflatoxin B1, Aflatoxin tổng số, Ochratoxin A) and heavy metals (Pb, Cd, As, Hg) against Vietnam National Technical Regulations (`QCVN 8-1:2011/BYT`, `QCVN 8-2:2011/BYT`).

## Tools & MCP Integration
- `mcp_doc_scanner_mcp_doc_verify_lab_test_limits`: Automatically parses Vinacontrol/Quatest transcripts and compares each analyte against QCVN limits.
- `mcp_customs_legal_mcp_customs_generate_self_declaration`: Generates a Decree 15/2018/NĐ-CP Food Safety Self-Declaration citing the lab certificate.

## Procedure
1. Read the OCR transcript or DOCX/PDF lab certificate using `mcp_doc_scanner_mcp_doc_verify_lab_test_limits`.
2. Verify LOD and LOQ values for "Không phát hiện" (Not Detected) items.
3. Confirm each heavy metal and mycotoxin result is below the maximum limit in `QCVN 8-1:2011/BYT` and `QCVN 8-2:2011/BYT`.
4. Output a structured compliance table with Parameter, Unit, Result, Test Method, QCVN Limit, and PASS/FAIL status.

## Verification
- Every analyte in the lab report is accounted for with its exact measured value or LOD and verified against the applicable QCVN standard.
