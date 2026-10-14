---
name: softfac-builder-prompting
description: Use when prompting Builder agents for direct execution.
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [windows]
metadata:
  hermes:
    tags: [softfac, builder, agy, prompting, direct-execution]
---

# SoftFac Builder Prompting Discipline

## Core Imperative
TUYỆT ĐỐI CẤM prompt cho Builder (AGY / Aider / Gemini CLI) lập kế hoạch, phân tích 2 bước, hoặc thảo luận cách làm.
Mọi prompt gửi cho Builder PHẢI là **MỆNH LỆNH THI CÔNG TRỰC TIẾP (Direct Execution Directive)**.

## Key Rules
1. **Single-turn Direct Action**: Builder phải đọc file, sửa code, patch schema, và chạy test ngay lập tức trong lượt thực thi.
2. **Prohibit Multi-phase / Planning Output**: Không yêu cầu "hãy lên kế hoạch trước", không yêu cầu "phân tích checklist rồi đợi phản hồi". Yêu cầu rõ: *"Execute all changes directly right now. Do not write a plan. Do not split into analysis turns. Inspect, patch, run tests, and exit cleanly."*
3. **No Commit Directive**: Luôn nhắc lại trong prompt: *"You MUST NOT execute git commit. Only Hermes Orchestrator commits."*
