---
name: vg-field-test-analyzer
description: Analyzer subagent for /vg:field-test session bundles. Wraps the deterministic analyze.py severity heuristic with optional LLM narrative on HIGH/MEDIUM marks.
---

# vg-field-test-analyzer

This subagent is spawned at Step 7 (`7_analyze`) of `/vg:field-test`. It runs the deterministic Python analyzer first, then optionally augments the FIELD-REPORT.md with a narrative summary on HIGH/MEDIUM marks.

## Workflow

1. Read `${SESSION_DIR}/manifest.json` and `${SESSION_DIR}/marks.jsonl`.
2. Run `python3 scripts/field-test/analyze.py --session-dir ${SESSION_DIR} --known-issues .vg/KNOWN-ISSUES.json`.
3. Emit `field_test.analysis_completed` telemetry.
4. (Optional, future) For each HIGH/MEDIUM mark, generate a one-paragraph narrative summary tying console errors + network responses + user_note to the suspected root cause. Append to FIELD-REPORT.md under a `## Narrative` section.

## Severity heuristic (deterministic, no LLM)

Priority order; FIRST match wins:

- HIGH — any network status in [500..599] OR console line matches `Uncaught` / `Traceback` / `TypeError` / `ReferenceError` (case-insensitive) OR JSON-formatted console entry with `"level":"error"`.
- MEDIUM — any network status in [400..499].
- LOW — otherwise (visual-only feedback).

## Outputs

- `${SESSION_DIR}/FIELD-REPORT.md` — per-Mark sections + severity overview.
- `.vg/KNOWN-ISSUES.json` — appended entries, deduped by (source=field-test, sid, n).

## Corruption guard

If `KNOWN-ISSUES.json` is unparseable, the analyzer writes `KNOWN-ISSUES.corrupt-<ts>.json.bak` and refuses to append. Operator must triage manually.
