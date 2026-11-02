---
name: international-trade-contract-law
description: "Audit international sales contracts under VN Law and CISG."
version: 1.0.0
author: Trong (aesc), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [contract, legal, cisg, viac, commercial-law]
---

# International Trade & Commercial Contract Legal Auditor

## When to Use
- Drafting or reviewing International Sales Contracts (Hợp đồng ngoại thương), Domestic Purchase Contracts, or Distribution/Service Agreements.
- Checking compliance with Vietnam Commercial Law 2005 (Luật Thương mại 2005), Civil Code 2015, CISG (Vienna Convention 1980), and VIAC arbitration clauses.

## Tools & MCP Integration
- `mcp_customs_legal_mcp_legal_contract_clause_audit`: Audits contract text for mandatory clauses and flags legal risks.
- `mcp_customs_legal_mcp_legal_check_vietnam_mst`: Validates party tax codes (Mã số thuế).
- `mcp_doc_scanner_mcp_doc_compare_documents`: Redlines contract revisions.

## Procedure
1. Run `mcp_customs_legal_mcp_legal_contract_clause_audit` on the contract text or file.
2. Check that contractual penalty clauses (Phạt vi phạm) respect the 8% cap under Article 301 of Vietnam Commercial Law 2005.
3. Verify quality inspection clauses specify an accredited independent body (Vinacontrol / SGS / Quatest) and clear claim deadlines.
4. Ensure Dispute Resolution names a specific arbitration center (e.g. VIAC) and governing law.

## Verification
- Report all present clauses, missing clauses, and specific statutory limits under Vietnamese law and CISG.
