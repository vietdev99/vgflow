# Round 1 — Domain & Business

> Locks `P${PHASE_NUMBER}.D-XX` decisions for category=business.
> Per-answer challenger + per-round expander patterns: see `discussion-overview.md` §A and §B.

## Pre-analysis (AI does first)

Read SPECS.md goal + in-scope items. Pre-analyze:
- What user stories does this phase serve?
- Which roles are involved?
- What business rules apply?

Hold draft answers in memory; present to user via AskUserQuestion below (recommend-first pattern).

## Conversational preamble (R9 rule — Vietnamese, người-language)

> "Vòng 1 (Domain & Business — bối cảnh nghiệp vụ) chốt **ai làm gì trong phase này và tại sao**: user story (kịch bản người dùng), role (vai trò — advertiser/publisher/admin/dsp-partner), và business rule (quy tắc nghiệp vụ — vd: chỉ publisher mới approve được inventory của chính họ). Đây là nền tảng cho 4 vòng còn lại — nếu sai ở đây, kỹ thuật + API + UI + test đều lệch theo.
>
> Tôi đã đọc SPECS.md và phân tích sơ bộ. Bạn review, chỉnh chỗ nào AI đoán sai, hoặc bổ sung context nếu thiếu."

## AskUserQuestion

```
header: "Round 1 — Bối cảnh nghiệp vụ"
question: |
  Dựa trên SPECS.md, đây là hiểu biết của tôi:

  **Mục tiêu phase:** {extracted goal}

  **User stories (kịch bản người dùng — ai muốn làm gì):**
  - US-1: {story}
  - US-2: {story}

  Ví dụ đã điền:
  - US-1: DSP partner muốn tạo deal mới với publisher để chạy campaign direct (không qua auction)
  - US-2: SSP admin muốn review + approve/reject deal trước khi nó active

  **Roles (vai trò — ai có quyền làm):** {roles}
  Ví dụ: dsp-partner (tạo deal), ssp-admin (approve/reject), publisher (xem deal về inventory của mình)

  **Business rule (quy tắc nghiệp vụ — luật bắt buộc):** {rules}
  Ví dụ:
  - Deal mới luôn start ở state 'pending', chỉ ssp-admin đổi sang 'approved'/'rejected'
  - Publisher chỉ thấy deal về inventory của chính họ, không thấy deal khác

  Câu trả lời: "ok" hoặc chỉnh cụ thể ("role X nên thêm quyền Y", "business rule Z chưa đầy đủ vì...").
(open text)
```

**If `--auto` mode:** AI picks recommended answers based on SPECS.md + codebase context. Log `[AUTO]` in DISCUSSION-LOG.md.

## Per-answer challenger (after EACH user answer)

Apply pattern from `discussion-overview.md` §A:
- `ROUND=1`, `ROUND_TOPIC="Domain & Business"`
- Wrapper builds prompt → `Agent(subagent_type="general-purpose", model="opus", ...)`
- Process verdict (Address / Acknowledge / Defer)

## Decision lock

Lock decisions as:
```
### P${PHASE_NUMBER}.D-XX: <title>
**Category:** business
**Decision:** <text>
**Rationale:** <why>
**Quote source:** DISCUSSION-LOG.md#round-1
```

## Per-round expander (END of round, BEFORE R2)

Apply pattern from `discussion-overview.md` §B with `ROUND=1`, `ROUND_TOPIC="Domain & Business"`. Process critical_missing / nice_to_have (Address critical / Acknowledge / Defer).

## Advance

After R1 challenger + expander complete, advance to R2:
Read `_shared/scope/discussion-round-2-technical.md`.
