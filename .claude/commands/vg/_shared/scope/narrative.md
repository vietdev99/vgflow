# scope narrative (STEP 4.5 — NON-AUTHORITATIVE, NON-GATED)

> NO marker. NO must_write contract. NO telemetry contract.
> Best-effort generation of `${PHASE_DIR}/NARRATIVE.md` — a human-language
> phase story for COMPREHENSION only. If anything here fails, scope still
> completes. This step intentionally does NOT call `step-active` /
> `mark-step` so it never appears in `scope.md` runtime_contract and never
> retroactively invalidates contract-pins of already-scoped phases.

<WHY-NO-GATE>
Adding a must_touch_marker to scope.md would retro-break every phase scoped
before this change unless contract-pins shield them perfectly (they don't:
pre-pin phases, corrupt pins, validators reading live skill body). So this
step is plain instruction text. Read `docs/plans/2026-06-04-narrative-stage.md`
for the full rationale (D-2).
</WHY-NO-GATE>

## §0. Purpose

`CONTEXT.md` says WHAT was decided. It does not say what the phase DOES as a
human story. Generate `NARRATIVE.md` so the operator recognizes the phase
flow BEFORE `/vg:blueprint` turns it into a plan. NARRATIVE.md is
**non-authoritative** — blueprint never reads its body as planning input
(only the `status` frontmatter for a soft warning).

## §1. Skip conditions (cheap exits — non-feature profiles, re-scope)

```bash
# Non-feature profiles have no CONTEXT.md → nothing to narrate.
if [ ! -f "${PHASE_DIR}/CONTEXT.md" ]; then
  echo "ℹ narrative: no CONTEXT.md (non-feature profile) — skip."
  NARRATIVE_SKIP=1
fi

# Re-derive auto/non-interactive from ARGUMENTS (preflight parses but does
# not export them).
NARRATIVE_AUTO=false
[[ "${ARGUMENTS}" =~ --auto ]] && NARRATIVE_AUTO=true
[[ "${ARGUMENTS}" =~ --non-interactive ]] && NARRATIVE_AUTO=true

# Config opt-out (rapid-prototyping phases).
NARRATIVE_ENABLED=$(vg_config_get scope.narrative.enabled true 2>/dev/null || echo true)
if [ "$NARRATIVE_ENABLED" != "true" ]; then
  echo "ℹ narrative: scope.narrative.enabled=false — skip."
  NARRATIVE_SKIP=1
fi
```

If `NARRATIVE_SKIP=1`, jump straight to STEP 5 (completeness-validation).
Do NOT write the file, do NOT emit telemetry.

## §2. Generate NARRATIVE.md — IMPERATIVE WRITE (AI runtime)

Read `${PHASE_DIR}/CONTEXT.md` and `${PHASE_DIR}/DISCUSSION-LOG.md`. From them,
write `${PHASE_DIR}/NARRATIVE.md` in the operator's language
(`language.primary`, default Vietnamese — follow `_shared/language-policy.md`).

**Source of truth for the prose = DISCUSSION-LOG.md user answers + CONTEXT.md
decisions.** Do NOT invent flows the user never described. If a D-XX has no
clear business-flow story in DISCUSSION-LOG, describe only what the decision
literally states — do not embellish.

Issue a real `Write` tool call with this shape:

```markdown
---
status: unreviewed
authoritative: false
source: CONTEXT.md
generated_at: {ISO8601}
reviewed_at:
review_note:
---

# Phase {N} — {Name} — Câu chuyện nghiệp vụ

> Mô tả phase bằng ngôn ngữ con người. KHÔNG phải nguồn cho blueprint —
> chỉ để bạn xác nhận hiểu đúng trước khi sang bước lập kế hoạch.

## Ai dùng (Actors)
- {Actor}: {vai trò + làm gì trong phase này}

## Luồng nghiệp vụ (Business flows)
### Luồng 1: {tên luồng}
{Kể chuyện theo bước: ai làm gì → hệ thống phản ứng ra sao → kết quả.
Gắn (D-XX) khi câu liên quan tới 1 quyết định.}

## Hành vi mong đợi (Behaviors)
- Khi {điều kiện} → hệ thống {hành vi}. (D-XX)

## Ngoài phạm vi (Out of scope)
- {Lấy từ "Deferred Ideas" / "Open questions" của CONTEXT.md, hoặc "Không có"}
```

**Rules:**
- One `### Luồng N` per distinct business flow. Group related D-XX into one
  flow story rather than one-paragraph-per-decision.
- `(D-XX)` references are navigation hints ONLY — not contract bindings.
- Body in config language. D-XX tokens stay as-is.
- If `NARRATIVE_AUTO=true`, status stays `unreviewed` and you SKIP §3 (no
  prompt). Continue to §4.

## §3. Confirm (INTERACTIVE ONLY — optional, never blocks)

Skip this section entirely when `NARRATIVE_AUTO=true`.

Show the operator a 3-5 line summary of the narrative (actors + flow names),
then `AskUserQuestion` (language = config):

- **Đúng rồi** → set frontmatter `status: reviewed`, `reviewed_at: {now}`.
- **Cần sửa câu chữ** → operator describes the fix; regenerate ONLY
  NARRATIVE.md body (DO NOT re-run discussion rounds), set `status: edited`,
  `reviewed_at: {now}`, `review_note: {what changed}`.
- **Lộ sai sót scope thật** → this is the rare case. Tell the operator they
  should re-scope the affected decision: suggest
  `/vg:scope {N} --deepen=D-XX`. Set `status: edited`, `review_note` = the
  scope concern. Do NOT silently rewrite CONTEXT.md here — scope decisions
  belong to the discussion rounds, not this step.
- **Bỏ qua** → set `status: skipped`, `review_note` = required reason string.

The AskUserQuestion is OPTIONAL: if you cannot prompt (any non-interactive
context), leave `status: unreviewed` and move on. Never block.

## §4. PIPELINE-STATE + best-effort telemetry (NEVER gates)

```bash
if [ "${NARRATIVE_SKIP:-0}" != "1" ] && [ -f "${PHASE_DIR}/NARRATIVE.md" ]; then
  # Plain PIPELINE-STATE field — NOT a schema-validated contract entry.
  "${PYTHON_BIN:-python3}" - <<PY 2>/dev/null || true
import json, re
from pathlib import Path
p = Path("${PHASE_DIR}/PIPELINE-STATE.json")
state = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
nf = Path("${PHASE_DIR}/NARRATIVE.md").read_text(encoding="utf-8")
m = re.search(r'^status:\s*(\w+)', nf, re.M)
status = m.group(1) if m else "unreviewed"
state["narrative_review"] = {"status": status, "artifact": "NARRATIVE.md"}
p.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
PY

  NARR_STATUS=$(grep -m1 -E '^status:' "${PHASE_DIR}/NARRATIVE.md" | awk '{print $2}')
  DEC_CNT=$(grep -cE '^### (P[0-9.]+\.)?D-' "${PHASE_DIR}/CONTEXT.md" 2>/dev/null || echo 0)
  FLOW_CNT=$(grep -cE '^### Luồng' "${PHASE_DIR}/NARRATIVE.md" 2>/dev/null || echo 0)

  # Best-effort telemetry — 2>/dev/null || true so it can NEVER gate the run.
  vg-orchestrator emit-event narrative.generated \
    --payload "{\"phase\":\"${PHASE_NUMBER}\",\"decisions\":${DEC_CNT},\"flows\":${FLOW_CNT},\"status\":\"${NARR_STATUS:-unreviewed}\"}" \
    >/dev/null 2>&1 || true

  case "${NARR_STATUS}" in
    reviewed) vg-orchestrator emit-event narrative.reviewed --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true ;;
    edited)   vg-orchestrator emit-event narrative.edited   --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true ;;
    skipped)  vg-orchestrator emit-event narrative.skipped  --payload "{\"phase\":\"${PHASE_NUMBER}\"}" >/dev/null 2>&1 || true ;;
  esac

  echo "✓ NARRATIVE.md (${NARR_STATUS:-unreviewed}, ${FLOW_CNT} luồng) — non-authoritative, để bạn xác nhận hiểu đúng phase."
fi
```

## Advance

Read `_shared/scope/completeness-validation.md` next (STEP 5).
NARRATIVE.md gets committed in STEP 7 close (added to the atomic git-add).
