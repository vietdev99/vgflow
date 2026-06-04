# Narrative Stage — Human-Language Phase Story (scope → blueprint)

Date: 2026-06-04
Status: implemented
Version target: v4.73.1

## Problem

`CONTEXT.md` answers "what was decided" (machine-readable: `P{N}.D-XX`,
endpoints, TS-XX). It does NOT answer "what does this phase DO, told as a
human story" — actors, business flows, behaviors. A user reading
`P5.D-03: POST /api/orders (auth: staff)` cannot immediately see "staff
creates an order → order waits for approval → manager approves → stock
decrements".

This is a comprehension gap, not a traceability gap. The
decisions-trace gate (scope close §4) already catches sentence-level drift
(AI paraphrased one D-XX wrong vs the user's DISCUSSION-LOG answer). The
narrative catches FLOW-level misunderstanding (AI scoped the whole business
flow wrong) — and surfaces it BEFORE blueprint turns it into a plan, saving
the entire downstream pipeline.

## Design decisions (Claude + Codex consensus)

### D-1: Generate inside `/vg:scope`, NOT a standalone `/vg:narrate`

- Context is hot right after artifact-write (CONTEXT.md + DISCUSSION-LOG.md
  just written). Cheapest generation point.
- A standalone command is "lowest contract risk" (Codex) but has the highest
  adoption risk: users never run it → idea dies. Fold-into-scope wins.

### D-2: NO new `must_touch_marker` / `must_write` / `must_emit_telemetry` on scope.md

**This is the critical risk Codex flagged that the first placement draft
missed.** Adding a `must_touch_marker` to `scope.md` retroactively breaks
EVERY phase scoped before the change — unless contract-pins shield them
perfectly. Pins do NOT cover:
- phases scoped before contract-pin support landed,
- corrupt/missing pins,
- in-progress scopes created before this update,
- any validator path still reading live `scope.md` instead of the pin.

So the narrative step is **best-effort, non-blocking**: it runs as a plain
reference step (STEP 4.5) with NO marker, NO must_write entry, NO telemetry
contract entry. If generation fails, scope still completes. Stop hook never
sees it. Contract-pins of old phases are untouched.

### D-3: NARRATIVE.md is NON-AUTHORITATIVE — comprehension only

Hard red line (Codex): the moment `/vg:blueprint` consumes `NARRATIVE.md`
as planning source material, this becomes a second source of truth that
drifts from CONTEXT.md → REJECT. Its job is NOT traceability, NOT contract,
NOT planning input. Its only job: "before blueprint plans this, does the
user recognize the phase story?"

Frontmatter `authoritative: false` makes this machine-checkable. Blueprint
reads only the `status` field for a warning — never the body.

### D-4: Warn (not block) at blueprint preflight; auto-mode writes `unreviewed`

- A hard confirm-gate inside scope would stall `--auto-chain`. Rejected.
- `--auto` / `--non-interactive`: generate with `status: unreviewed`, emit
  best-effort telemetry, continue. No prompt.
- Interactive: show the narrative, user nods (`reviewed`) / edits (`edited`)
  / skips (`skipped` + reason). The AskUserQuestion is OPTIONAL — if the
  AI cannot prompt (auto), it just writes `unreviewed`.
- `/vg:blueprint` preflight 2_verify_prerequisites: if NARRATIVE.md missing
  or `status: unreviewed`, print a yellow warning and CONTINUE. Never block.

### D-5: Edit loop never re-runs the 5 discussion rounds

- User edits the narrative prose → regenerate ONLY `NARRATIVE.md`.
- ONLY if the user says the narrative exposed a real scope error do we touch
  the affected `D-XX` in CONTEXT.md and re-run completeness/decisions-trace.
  Regenerating the narrative does not re-run rounds 1-5.

## Artifact schema — NARRATIVE.md

Path: `${PHASE_DIR}/NARRATIVE.md`

```markdown
---
status: unreviewed        # unreviewed | reviewed | edited | skipped
authoritative: false      # ALWAYS false — comprehension artifact, never planning source
source: CONTEXT.md
generated_at: <ISO8601>
reviewed_at:              # set when status flips to reviewed/edited
review_note:              # optional one-line; required string if status=skipped
---

# Phase {N} — {Name} — Câu chuyện nghiệp vụ

> Mô tả phase bằng ngôn ngữ con người. KHÔNG phải nguồn cho blueprint —
> chỉ để bạn xác nhận hiểu đúng trước khi sang bước lập kế hoạch.

## Ai dùng (Actors)
- {Actor}: {vai trò, làm gì trong phase này}

## Luồng nghiệp vụ (Business flows)
### Luồng 1: {tên luồng}
{Kể chuyện: ai làm gì → hệ thống phản ứng ra sao → kết quả. Tham chiếu
D-XX trong ngoặc khi liên quan, ví dụ "(D-03)".}

## Hành vi mong đợi (Behaviors)
- Khi {điều kiện} → hệ thống {hành vi}. (D-XX)

## Ngoài phạm vi (Out of scope)
- {Cái phase này KHÔNG làm — lấy từ Deferred Ideas / Out-of-scope của CONTEXT}
```

Body language = `language.primary` (default `vi`). D-XX references in parens
are navigation hints, not contract bindings.

## Telemetry (best-effort, NOT in runtime_contract)

Emitted with `2>/dev/null || true` — never gates a run:
- `narrative.generated` — payload `{phase, decisions_count, flows_count}`
- `narrative.reviewed` / `narrative.edited` / `narrative.skipped`
- `blueprint.started_with_unreviewed_narrative` — at blueprint warn

## Anti-skip (friction, not gate)

- Always generated for new scopes (best-effort).
- `status` visible in `PIPELINE-STATE.json` → `narrative_review.status`.
- `/vg:blueprint` preflight prints yellow warning on `unreviewed`/missing.
- (Future) `/vg:health` + milestone-summary count unreviewed/skipped as
  yellow debt. NOT implemented in this batch — listed for follow-up.

## Files touched

| File | Change | Marker? |
|---|---|---|
| `commands/vg/_shared/scope/narrative.md` | NEW — generation logic | none |
| `commands/vg/scope.md` | STEP 4.5 ref (after artifact-write) | NO contract change |
| `commands/vg/_shared/scope/close.md` | git-add NARRATIVE.md (conditional) | none |
| `commands/vg/_shared/blueprint/preflight.md` | warn block in 2_verify_prerequisites | none |

PIPELINE-STATE write happens inside narrative.md (plain field, no schema gate).

## Out of scope (this batch)

- `/vg:health` narrative-debt surfacing.
- milestone-summary narrative count.
- NARRATIVE.md schema validator (intentionally none — non-authoritative).
