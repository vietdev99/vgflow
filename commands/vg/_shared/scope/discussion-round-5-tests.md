# Round 5 — Test Scenarios

> Locks TS-XX test scenario notes + verification_strategy embedded in existing decisions.
> Per-answer challenger + per-round expander: see `discussion-overview.md` §A and §B.

## Conversational preamble (R9 rule)

> "Vòng 5 (Test Scenarios — kịch bản kiểm thử) là vòng cuối: chốt **khi nào phase này coi là DONE thật**. Mỗi scenario mô tả một hành động cụ thể user làm + kết quả mong đợi. Review sau sẽ check từng cái chạy được chưa — nên càng quan sát được (observable) càng dễ verify.
>
> Quan trọng: đánh dấu scenario nào **automated** (Playwright tự verify được) vs **manual** (cần người thật bấm trong UAT — vd: CAPTCHA, payment UI thật, SMS OTP). Nếu label sai (manual mà gắn automated), review sẽ mark PASSED oan → bug lọt production."

## AskUserQuestion

```
header: "Round 5 — Kịch bản kiểm thử"
question: |
  AI đề xuất scenarios từ decision + endpoint + component đã chốt. Bạn review + chỉnh.

  **Happy path:**

  | ID | Kịch bản | Endpoint | Status + Output | Từ quyết định | Cách verify |
  |----|----------|----------|-----------------|---------------|-------------|
  | TS-01 | {user gõ gì, bấm gì, thấy gì} | POST /api/... | 201 + {field} | D-{XX} | automated |
  | TS-02 | {user mở trang, xem gì} | GET /api/... | 200 + {list} | D-{XX} | automated |

  Ví dụ:
  | TS-01 | DSP partner bấm "Create Deal", nhập publisher ID + floor CPM + creative, Submit | POST /api/v1/deals | 201 + `{ id, state: 'pending' }` | D-03 | automated |
  | TS-02 | SSP Admin vào trang Deals, thấy deal vừa tạo ở đầu bảng badge "Pending" | GET /api/v1/deals | 200 + list chứa deal | D-04 | automated |

  **Edge case:**

  | ID | Kịch bản | Expect | Cách verify |
  |----|----------|--------|-------------|
  | TS-{N} | {sai gì} | {error code + message} | automated |

  Ví dụ:
  | TS-05 | floor CPM = -1 | 400 + `{ error: 'floorCpm must be ≥ 0' }` | automated |
  | TS-06 | publisher ID không tồn tại | 404 + `{ error: 'publisher not found' }` | automated |

  **Mutation evidence:**

  | Hành động | Verify ở đâu |
  |-----------|--------------|
  | Create deal | List + DB collection `deals` + state "pending" |
  | Approve deal | Badge "Pending"→"Approved" + DB state + updatedAt |
  | Reject deal | Badge "Rejected" + reason field saved |

  **Verification strategy (bắt buộc per scenario):**
  - `automated` — Playwright verify được
  - `manual` — người phải click (CAPTCHA, OTP, Stripe iframe)
  - `fixture` — cần test fixture/seed
  - `faketime` — phải tua thời gian (TTL, cronjob, renewal)

  Scenario non-`automated` sẽ mark MANUAL ở review → codegen sinh `.skip()` skeleton → user điền ở /vg:accept. Ngăn giả PASSED cho scenario cần human/infra.

  Confirm, edit, hoặc thêm scenario?
(open text)
```

## TS-XX lock format (embedded in existing decisions)

```
**Test Scenarios:**
- TS-01: user adds credit card → stored, charge works → 200 + receipt
  verification_strategy: manual   # Stripe Elements iframe
- TS-02: subscription auto-renew sau 30 ngày → next billing cycle
  verification_strategy: faketime # cần tua 30 ngày
```

## Per-answer challenger + per-round expander

Apply patterns from `discussion-overview.md` §A and §B.
- `ROUND=5`, `ROUND_TOPIC="Test Scenarios"`

## Advance

After R5 challenger + expander complete:
Read `_shared/scope/discussion-deep-probe.md`.
