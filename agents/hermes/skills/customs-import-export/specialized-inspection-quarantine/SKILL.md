---
name: specialized-inspection-quarantine
description: "Manage Plant/Animal Quarantine and Quality Inspection."
version: 1.0.0
author: Trong (aesc), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [quarantine, phytosanitary, vnsw, quality-inspection, customs]
---

# Specialized Inspection & Quarantine (Kiểm tra chuyên ngành)

## When to Use
- Handling Plant Quarantine (Kiểm dịch thực vật), Animal Quarantine (Kiểm dịch động vật), or Quality/CR Inspection on the Vietnam National Single Window (`https://vnsw.gov.vn`).
- Checking Decree 69/2018/NĐ-CP prohibited imports and line-ministry permits.

## Tools & MCP Integration
- `mcp_customs_legal_mcp_customs_specialized_inspection_lookup`: Looks up agency, circular, and VNSW procedure by commodity type.
- `mcp_customs_legal_mcp_customs_hs_code_lookup`: Checks HS-level specialized inspection requirements.
- `mcp_browser_automation_mcp_browser_customs_portal_links`: Provides direct VNSW and Customs portal URLs.

## Procedure
1. Look up the commodity's HS code and specialized inspection rules via `customs_hs_code_lookup` and `customs_specialized_inspection_lookup`.
2. Verify whether Phytosanitary Certificate from the exporting country is required prior to arrival.
3. List the exact VNSW registration steps and sampling/inspection agency.

## Verification
- Managing agency, legal circular, and VNSW dossier requirements are clearly stated.
