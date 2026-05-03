# vg-accept-uat-builder — input/output contract (delegation appendix, NOT a step)

<HARD-GATE>
This file is a **non-step appendix** — it carries the input/output
contract consumed by `overview.md` and the `vg-accept-uat-builder`
SKILL.md. It owns NO step marker, emits NO step-active event, and runs
NO bash on its own. Step lifecycle (step-active → spawn → mark-step) is
performed entirely by `overview.md` against the `4_build_uat_checklist`
marker.

Read order: `overview.md` first (lifecycle), then this delegation
contract (capsule + JSON shape). Do NOT execute any step bash from this
file.
</HARD-GATE>

Generate `${PHASE_DIR}/uat-checklist.md` (markdown table per section) from
8 VG artifacts. Return JSON summary so the main agent can render section
counts without re-reading the file.

## Input capsule (build prompt from these)

Required env from main agent:
- `PHASE_NUMBER` — e.g. `7.6`
- `PHASE_DIR` — e.g. `.vg/phases/07.6-…/`
- `PLANNING_DIR` — e.g. `.vg/`
- `PROFILE` — `web-fullstack` / `mobile-rn` / etc. (drives Section F omit)
- `VG_TMP` — scratch dir
- `PYTHON_BIN` — `python3`
- `REPO_ROOT` — repo root

Artifact sources (delegated subagent reads):

| Section | Source | Load mode | Notes |
|---|---|---|---|
| A    | `${PHASE_DIR}/CONTEXT.md`                        | KEEP-FLAT | Match `P{phase}.D-XX` (new) or `D-XX` (legacy) |
| A.1  | `${PLANNING_DIR}/FOUNDATION.md` (if cited)        | KEEP-FLAT | Scan phase artifacts for `F-XX`, then look up in FOUNDATION |
| B    | `vg-load --phase ${PHASE_NUMBER} --artifact goals --list` + per-goal expand | **vg-load split** | Phase F Task 30 absorption — NOT flat TEST-GOALS.md |
| B    | `${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md`            | KEEP-FLAT | Lookup per-goal status (READY/BLOCKED/UNREACHABLE/PARTIAL) |
| B.1  | `${PHASE_DIR}/CRUD-SURFACES.md`                   | KEEP-FLAT | Single doc, JSON inside fenced block |
| C    | `${PHASE_DIR}/.ripple.json` (preferred)           | KEEP-FLAT | Or `RIPPLE-ANALYSIS.md` fallback |
| D    | `vg-load --phase ${PHASE_NUMBER} --artifact plan --list` + per-task expand | **vg-load split** | Extract `<design-ref>` from Layer-1 task files |
| D    | `${PHASE_DIR}/discover/*.png` (mobile-* profile)  | filesystem | Simulator screenshots from `phase2_mobile_discovery` |
| E    | `${PHASE_DIR}/SUMMARY*.md`                        | KEEP-FLAT | Summary glob |
| F    | `${PHASE_DIR}/build-state.log` (mobile-*)         | KEEP-FLAT | Latest `mobile-gate-N` per id |
| F    | `${PHASE_DIR}/mobile-security/report.md`          | KEEP-FLAT | Severity counts (CRITICAL/HIGH/MEDIUM/LOW) |

## Workflow inside subagent

1. Read input capsule (env vars set by main agent in prompt).
2. For each section A-F (suppress F when PROFILE not mobile-*):
   - Run section's parser (Python via `${PYTHON_BIN}` heredoc allowed).
   - Collect `[{id, summary, source_file, source_line}]`.
3. Render `${PHASE_DIR}/uat-checklist.md`:
   ```markdown
   # UAT Checklist — Phase {PHASE_NUMBER}
   
   Generated: {ISO-8601 UTC}
   Total items: {N}
   
   ## Section A — Decisions ({count})
   | ID | Title | Source |
   |---|---|---|
   | P{phase}.D-01 | … | CONTEXT.md:42 |
   …
   
   ## Section A.1 — Foundation cites ({count})
   …
   ```
4. Return JSON to main agent (see overview.md output validation).

## Allowed tools (subagent FRONTMATTER)

`tools: [Read, Write, Bash, Grep]`

(NO `Task` / `Agent` — subagent must NOT spawn other subagents. Single-task
build only.)

## Forbidden inside subagent

- DO NOT cat flat `TEST-GOALS.md` — use `vg-load` split (Phase F Task 30).
- DO NOT cat flat `PLAN.md` — use `vg-load` per-task to extract `<design-ref>`.
- DO NOT spawn other subagents.
- DO NOT call AskUserQuestion (interactive happens in main agent at STEP 5).
- DO NOT modify any file other than `${PHASE_DIR}/uat-checklist.md` and
  `${VG_TMP}/uat-*.txt` scratch files.
- DO NOT write `${PHASE_DIR}/.step-markers/*` — main agent does that after
  output validation passes.

## Failure modes (return error JSON, no partial files)

```json
{ "error": "missing_artifact", "field": "CRUD-SURFACES.md", "phase": "${PHASE_NUMBER}" }
{ "error": "vg_load_failed", "artifact": "goals", "stderr": "…" }
{ "error": "json_parse_failed", "field": "CRUD-SURFACES.md", "detail": "…" }
{ "error": "section_empty", "section": "B", "reason": "no goals matched" }
```

Main agent surfaces these via 3-line block + retry option.

## Example main-agent prompt to subagent

```
Build the UAT checklist for phase {PHASE_NUMBER}.

Inputs:
- PHASE_NUMBER={PHASE_NUMBER}
- PHASE_DIR={PHASE_DIR}
- PLANNING_DIR={PLANNING_DIR}
- PROFILE={PROFILE}
- VG_TMP={VG_TMP}
- REPO_ROOT={REPO_ROOT}

Read your SKILL.md for the full per-section bash. Use vg-load (not flat
reads) for goals (Section B) and design-refs (Section D). Suppress
Section F unless PROFILE matches mobile-*.

Write `${PHASE_DIR}/uat-checklist.md` and return the JSON contract from
your SKILL §Output.
```
