# scope discussion-round-2-technical (STEP 2 / Round 2)

> Locks `P${PHASE_NUMBER}.D-XX` decisions for category=technical (+ `P${PHASE_NUMBER}.D-surfaces` if multi-surface, `P${PHASE_NUMBER}.D-utilities` if NEW helpers).
> Per-answer challenger + per-round expander: see `discussion-overview.md` §A and §B.

<HARD-GATE>
Round 2 of 5 inside STEP 2. Multi-surface gate (§1) MUST run first if
config.surfaces is declared. Per-answer challenger + per-round expander
mandatory. Do NOT mark `1_deep_discussion` here — owner is
`discussion-deep-probe.md`.
</HARD-GATE>

## §1. Multi-surface gate (FIRST — only if config.surfaces declared)

```bash
if grep -qE "^surfaces:" .claude/vg.config.md; then
  AVAILABLE_SURFACES=$(${PYTHON_BIN} -c "
import re
cfg = open('.claude/vg.config.md', encoding='utf-8').read()
m = re.search(r'^surfaces:\n((?:  [^\n]+\n)+)', cfg, re.M)
if m:
    for line in m.group(1).split('\n'):
        sm = re.match(r'^  (\w[\w-]*):', line)
        if sm: print(sm.group(1))
")
  echo "Multi-surface project. Surfaces declared: $AVAILABLE_SURFACES"
  # → AskUserQuestion (multi-select) which surfaces this phase touches
fi
```

```
AskUserQuestion:
  header: "Surfaces touched"
  question: "Phase này touch surfaces nào? (multi-select)"
  multiSelect: true
  options: [<from config.surfaces keys>]
```

Lock `P${PHASE_NUMBER}.D-surfaces: [<list>]` decision.

**Primary role lookup** — if phase touches `web` surface, read `config.surfaces.web.design` → set `SURFACE_ROLE` for Round 4 DESIGN.md resolve.

## §2. Surface gap auto-detect (after R2 recommendation, before lock)

```bash
source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/surface-gap-detector.sh"

if surface_gap_detector_is_enabled ".claude/vg.config.md"; then
  GAPS_JSON=$(detect_surface_gaps "$R2_RECOMMENDATION_TEXT" ".claude/vg.config.md")
  MISSING_COUNT=$(echo "$GAPS_JSON" | ${PYTHON_BIN} -c "import json,sys; print(len(json.loads(sys.stdin.read()).get('missing_surfaces',[])))")

  if [ "$MISSING_COUNT" -gt 0 ]; then
    echo "━━━ Surface Gap Detected ━━━"
    format_gap_narrative "$GAPS_JSON"
    # AskUserQuestion: Add surfaces / Acknowledge / Skip
    # If user accepts: lock P${PHASE_NUMBER}.D-XX (config-amendment) — applied in blueprint preflight
  fi
fi
```

Prevents "phase scope mentions Rust but RTB surface never declared → downstream surface-aware checks skip silently".

## §3. Pre-analysis (AI does first)

Read `config.code_patterns` paths. Identify:
- Which services/modules need changes?
- Database collections/schema shape?
- External deps (new npm/cargo packages)?
- **Utility needs (v1.14.2+):** scan planned functionality for helper needs (money/date/number/string/async). Cross-reference `PROJECT.md` → `## Shared Utility Contract` exports. Classify each helper as **REUSE** (already exists) / **EXTEND** (add param) / **NEW** (must add to `packages/utils` FIRST).

## §4. Conversational preamble (R9 rule)

Trước bảng, narrate 2-3 câu giải thích context + mục tiêu:

> "Vòng 2 (Technical Approach — cách làm kỹ thuật) chốt **ai làm gì** trong code base: module nào cần sửa, cần table mới trong database không, và helper (hàm tiện ích dùng chung) nào phải thêm vào `packages/utils` trước khi business logic đụng tới. Lý do gộp vào vòng này: phase sau không sửa kiến trúc được, nên ta phải thấy đúng hình dạng code ngay bây giờ.
>
> Tôi đã quét codebase và thấy [tóm tắt 1-2 câu hiện trạng]. Đề xuất của tôi bên dưới. Bạn đọc, chỉnh chỗ nào AI đoán sai, hoặc nói 'ok' nếu ổn."

## §5. AskUserQuestion

```
header: "Round 2 — Cách làm kỹ thuật"
question: |
  **Kiến trúc (architecture — cấu trúc các module phối hợp):**

  | Module | Hiện trạng | Đề xuất |
  |--------|-----------|---------|
  | {module tên thật} | {đã có / làm mới / cần mở rộng} | {sửa gì cụ thể — 1 dòng} |

  Ví dụ đã điền:
  | `apps/api/src/modules/deals` | đã có (CRUD cơ bản) | thêm endpoint bulk-update state, sửa index mongo `deals_by_publisher_state` |

  **Database (storage layer):** {collection/table mới + index cần thiết}
  **External deps (thư viện bên ngoài):** {npm/cargo packages mới, nếu có}

  **Shared utilities (helper dùng chung — tránh duplicate):**

  | Helper cần | Đã có trong `packages/utils`? | Hành động |
  |-----------|------------------------------|-----------|
  | formatCurrency | ✓ có rồi | REUSE (dùng lại) |
  | formatDealState | ✗ chưa có | NEW — thêm vào `packages/utils/src/deals.ts` TRƯỚC khi task business dùng |

  Câu trả lời: "ok" hoặc chỉnh cụ thể.
(open text)
```

## §6. NEW utilities enforcement

If user confirms NEW helpers, scope MUST lock `P${PHASE_NUMBER}.D-utilities`:

```
**Utilities added:**
- formatDealState(state: DealState): string → packages/utils/src/deals.ts (NEW)
- formatCurrency → REUSE existing
```

Forces blueprint to generate Task 0 (extend utils) BEFORE business tasks. Plan-checker rejects PLAN where task N uses helper not yet added by task M < N.

## §7. Per-answer challenger + per-round expander

Apply patterns from `discussion-overview.md` §A (after each answer) and §B (after all answers, before R3).
- `ROUND=2`, `ROUND_TOPIC="Technical Approach"`

## §8. Decision lock

Lock decisions as `P${PHASE_NUMBER}.D-XX` (category=technical), plus `D-surfaces` and `D-utilities` if applicable.

## Advance

After R2 challenger + expander complete:
Read `_shared/scope/discussion-round-3-api.md`.
