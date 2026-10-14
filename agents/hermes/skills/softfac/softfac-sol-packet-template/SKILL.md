---
name: softfac-sol-packet-template
description: Template chuẩn soạn review packet cho Sol Reviewer.
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [windows]
metadata:
  hermes:
    tags: [softfac, sol, template, packet, audit]
---

# Template Soạn Review Packet Cho Sol Reviewer

Khi soạn packet thẩm định gửi Sol, áp dụng cấu trúc chuẩn mực sau:

```markdown
# Neutral Review Packet for Sol Reviewer: <Milestone> (<Title>)

**Status:** READY FOR INDEPENDENT REVIEW | DRAFT — NOT SUBMITTABLE
**Review Target Commit:** `<full_commit_sha>` (short: `<short_sha>`)
**Git Tree SHA:** `<tree_sha>`
**Parent Commit:** `<parent_sha>`
**Working Tree State:** Clean / Dirty (`git status --porcelain`)
**Evaluated Candidate Code Base Commit:** `<candidate_sha>`
**Evaluated Source Tree Hash:** `<source_tree_hash>`
**Attestation & Verification Commit:** `<attestation_commit_sha>`

---

## 1. Specification (Verbatim Acceptance Requirements from Astra Master Plan)
> <Quote verbatim requirements here>

---

## 2. Provenance & Working Tree Context
- Repository Root: <path>
- Candidate Commit: <commit>
- Tree Object: <tree>
- Provenance Scheme: git_source_tree_and_base_commit
- Working Tree State: <clean / dirty status>

---

## 3. Evidence Index & Remediation Status
| Finding ID | Requirement / Issue | Evidence Source & Path | Evidence Class | Candidate Binding | Status / Remaining Gap |
| :--- | :--- | :--- | :--- | :--- | :--- |
| <ID> | <Requirement> | <Path> | <requirement / builder claim / simulation / independently observed / missing> | <commit> | <Claimed fixed / supported / unverified> |

---

## 4. Acceptance Gates Summary
- <Gate 1 .. N>

---

## 5. Test Suite Verification Logs (Independently Run by Orchestrator)
1. Core Tests: <log & exit code>
2. Python Discovery Suite: <log & exit code>
3. Invariant Checks: <log & exit code>
4. Oracle Controls: <log & exit code>

---

## 6. Review Contract & JSON Response Schema for Sol
```json
{
  "verdict": "APPROVED" | "REVISE",
  "reviewer": "gpt-6-sol",
  "commit": "<short_sha>",
  "milestones": ["<Milestone>"],
  "summary": "string",
  "findings_evaluation": [
    {
      "finding_id": "string",
      "status": "APPROVED" | "REOPENED",
      "notes": "string"
    }
  ],
  "remaining_findings": []
}
```
```
