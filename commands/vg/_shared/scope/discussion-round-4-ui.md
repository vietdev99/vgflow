# Round 4 — UI/UX

> Locks UI component notes embedded in existing decisions.
> Profile-aware skip for backend-only / cli-tool / library profiles.
> Per-answer challenger + per-round expander: see `discussion-overview.md` §A and §B.

## §1. Profile-aware skip (FIRST)

```bash
case "${PROFILE}" in
  web-backend-only|cli-tool|library)
    echo "↷ R4 UI/UX skipped — profile=${PROFILE} has no UI surface"
    vg-orchestrator emit-event scope.r4_skipped --payload "{\"profile\":\"${PROFILE}\"}" 2>/dev/null || true
    # Skip directly to R5
    return 0
    ;;
esac
```

## §2. Design System integration

```bash
source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/design-system.sh"
DESIGN_CONTEXT=""
if design_system_enabled; then
  DESIGN_RESOLVED=$(design_system_resolve "$PHASE_DIR" "${SURFACE_ROLE:-}")
  if [ -n "$DESIGN_RESOLVED" ]; then
    echo "✓ DESIGN.md resolved: $DESIGN_RESOLVED"
    DESIGN_CONTEXT=$(design_system_inject_context "$PHASE_DIR" "${SURFACE_ROLE:-}")
  else
    echo "⚠ No DESIGN.md resolved (role=${SURFACE_ROLE:-<none>}) — Round 4 will offer 4 options"
  fi
fi
```

**If `$DESIGN_CONTEXT` set:** Round 4 Q includes "Dùng design này làm base? Hay customize cho phase?" — pages/components must respect color/typography/spacing from DESIGN.md.

**If `$DESIGN_CONTEXT` empty:** Offer 4 options:
1. **Pick from 58 brands** — `/vg:design-system --browse` → user picks → auto `/vg:design-system --import <brand> --role=<role>`
2. **Import existing** — paste DESIGN.md or URL → save to `${PLANNING_DIR}/design/[<role>/]DESIGN.md`
3. **Create from scratch** — `/vg:design-system --create --role=<role>` guided
4. **Skip (not recommended)** — flag "design-debt" in CONTEXT.md

## §3. Conversational preamble (R9 rule)

> "Vòng 4 (UI/UX — giao diện người dùng) chốt **những trang và component** frontend cần build, dựa trên endpoint đã có ở vòng 3. Một endpoint POST /api/v1/deals thường cần 1 form tạo + 1 bảng list + 1 modal chi tiết — vòng này ta quyết định cụ thể trang nào, layout sao, trong dashboard nào (advertiser / publisher / admin).
>
> Nếu có design asset (Figma link, screenshot, Pencil mockup) thì load bây giờ — build sau sẽ reference trực tiếp thay vì đoán mò."

## §4. AskUserQuestion

```
header: "Round 4 — UI/UX"
question: |
  **Trang/view cần thiết:**

  | Trang | Dashboard | Component chính | Map sang endpoint |
  |-------|-----------|-----------------|-------------------|
  | {tên trang} | {advertiser/publisher/admin} | {component list} | GET/POST /api/... |

  Ví dụ đã điền:
  | Deals list | SSP Admin | DataTable, StatusBadge, FilterBar | GET /api/v1/deals |
  | Deal detail | SSP Admin | DealForm, ApprovalActions | GET /api/v1/deals/:id, PUT /api/v1/deals/:id/state |

  **Key component (mới build, không tính tái dùng):**
  - `DealForm`: form tạo deal với validate floor CPM + creative spec
  - `ApprovalActions`: 2 nút Approve/Reject + modal nhập lý do nếu Reject

  **Design reference (mockup tham khảo):**
  - Nếu có ảnh/Figma link: paste hoặc reference `${PHASE_DIR}/design-*.png`
  - Nếu chưa có: tôi suggest layout dựa trên component cùng dashboard

  Câu trả lời: "ok" hoặc chỉnh.
(open text)
```

## §5. UI component lock format (embedded in existing decisions)

```
**UI Components:**
- DealForm — form tạo deal, validate floor CPM (apps/web/src/features/deals/DealForm.tsx)
- ApprovalActions — Approve/Reject buttons + reason modal
**Pages:** Deals list (SSP Admin), Deal detail (SSP Admin)
```

## §6. Per-answer challenger + per-round expander

Apply patterns from `discussion-overview.md` §A and §B.
- `ROUND=4`, `ROUND_TOPIC="UI/UX"`

## Advance

After R4 challenger + expander complete (or profile-skip):
Read `_shared/scope/discussion-round-5-tests.md`.
