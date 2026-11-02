---
name: incoterms-2020-freight-audit
description: "Audit Incoterms 2020 rules, freight charges, and DEM/DET."
version: 1.0.0
author: Trong (aesc), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [incoterms, freight, fob, cif, ddp, demurrage]
---

# Incoterms 2020, Freight Surcharge & DEM/DET Auditor

## When to Use
- Determining buyer vs seller cost, risk transfer point, and customs clearance responsibility across all 11 Incoterms® 2020 rules.
- Calculating container capacity (20GP/40GP/40HQ) and Demurrage/Detention (DEM/DET) charges.

## Tools & MCP Integration
- `mcp_customs_legal_mcp_customs_incoterms_calculator`: Returns cost/risk matrix and EXW->FOB->CIF->DDP price ladder.
- `mcp_customs_legal_mcp_customs_container_load_planner`: Computes 20GP/40GP/40HQ container count and FCL vs LCL recommendation.
- `mcp_customs_legal_mcp_customs_demurrage_detention_calc`: Computes free-time expiry and overdue DEM/DET charges.

## Procedure
1. Run `customs_incoterms_calculator` for the contract's Incoterm.
2. If container sizing is needed, run `customs_container_load_planner` with total CBM and Gross Weight.
3. If evaluating port delays, run `customs_demurrage_detention_calc` with total days and free days.

## Verification
- Risk transfer point, cost division, and container/DEM-DET figures are grounded in tool output.
