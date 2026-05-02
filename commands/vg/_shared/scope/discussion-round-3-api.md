# Round 3 — API Design

> Locks endpoint notes embedded in existing decisions (category=technical/api).
> Per-answer challenger + per-round expander: see `discussion-overview.md` §A and §B.

## Conversational preamble (R9 rule)

> "Vòng 3 (API Design — hợp đồng request/response giữa frontend và backend) chốt **hình dạng endpoint**: đường dẫn (path), method (GET/POST/PUT/DELETE), ai được gọi (auth role — vai trò xác thực), và input/output shape. Sau vòng này, blueprint sẽ tự sinh code Zod schema từ những gì bạn chốt ở đây, nên bây giờ càng cụ thể càng tốt.
>
> Nếu có endpoint chỉ test được khi phase khác đã xong (vd: conversion event cần pixel server ship trước), note cột 'phụ thuộc phase nào' để review sau không mark FAILED oan."

## AskUserQuestion

```
header: "Round 3 — API Design"
question: |
  Từ các quyết định vòng 1-2, tôi đề xuất các endpoint sau:

  | # | Endpoint | Method | Ai gọi được (auth) | Mục đích | Từ quyết định | Phụ thuộc phase nào? |
  |---|----------|--------|--------------------|----------|---------------|----------------------|
  | 1 | /api/v1/{tên resource} | POST | {role} | {mô tả ngắn} | D-{XX} | _(không / X.Y)_ |
  | 2 | /api/v1/{tên resource} | GET  | {role} | {mô tả ngắn} | D-{XX} | _(không / X.Y)_ |

  Ví dụ đã điền:
  | 1 | /api/v1/deals | POST | dsp-partner | tạo deal mới từ DSP bidder | D-03 | không |
  | 2 | /api/v1/deals/:id/state | PUT | ssp-admin | publisher approve/reject deal | D-04 | không |

  **Request/response shape (hình dạng dữ liệu):**
  - POST /api/v1/deals: body `{ publisherId, creativeSpec, floorCpm }` → 201 `{ id, state: 'pending' }`
  - PUT /api/v1/deals/:id/state: body `{ state: 'approved' | 'rejected', reason? }` → 200 `{ id, state, updatedAt }`

  **Cột "Phụ thuộc phase nào"** — endpoint chỉ verify được khi phase khác ship (vd: conversion event endpoint phụ thuộc pixel server từ phase 7.12), điền số phase target. Goal gắn tag này sẽ được mark DEFERRED ở review.

  Câu trả lời: "ok" hoặc chỉnh endpoint cụ thể.
(open text)
```

## Endpoint lock format (embedded in existing decisions)

```
**Endpoints:**
- POST /api/v1/conversion-events (auth: advertiser, purpose: record conversion)
  depends_on_phase: 7.12   # chỉ verify được khi pixel server ship
```

## Per-answer challenger + per-round expander

Apply patterns from `discussion-overview.md` §A and §B.
- `ROUND=3`, `ROUND_TOPIC="API Design"`

## Advance

After R3 challenger + expander complete:
Read `_shared/scope/discussion-round-4-ui.md`.
