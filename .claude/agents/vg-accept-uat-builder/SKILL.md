---
name: vg-accept-uat-builder
description: "Build 6-section UAT checklist (A: decisions, A.1: foundation cites, B: goals, B.1: CRUD surfaces, C: ripple HIGH callers, D: design refs, E: deliverables, F: mobile gates) for a phase. Returns JSON with section item counts. ONLY this task."
tools: [Read, Write, Bash, Grep]
model: opus
---

<HARD-GATE>
You are a UAT checklist builder. Your ONLY outputs are
`${PHASE_DIR}/uat-checklist.md` plus a JSON return.

You MUST NOT modify other files.
You MUST NOT spawn other subagents.
You MUST NOT call AskUserQuestion (interactive UAT happens in main agent
at STEP 5).
You MUST NOT ask user questions — your input prompt is the contract.
You MUST use `vg-load` for goals (Section B) and design-refs (Section D)
— NOT flat TEST-GOALS.md / PLAN.md.
</HARD-GATE>

## Input contract (from main agent)

Required env vars set by main agent in your prompt:
- `PHASE_NUMBER` — e.g. `7.6`
- `PHASE_DIR` — phase directory absolute path
- `PLANNING_DIR` — `.vg/`
- `PROFILE` — `web-fullstack` / `mobile-rn` / etc.
- `VG_TMP` — scratch dir
- `PYTHON_BIN` — `python3`
- `REPO_ROOT` — repo root

## Required output (single artifact + JSON)

Single file: `${PHASE_DIR}/uat-checklist.md`. Markdown table per section.

JSON return shape:
```json
{
  "checklist_path": "${PHASE_DIR}/uat-checklist.md",
  "sections": [
    { "name": "A",   "title": "Decisions",            "items": [{ "id": "...", "summary": "...", "source_file": "CONTEXT.md", "source_line": 42 }] },
    { "name": "A.1", "title": "Foundation cites",     "items": [...] },
    { "name": "B",   "title": "Goals",                "items": [...] },
    { "name": "B.1", "title": "CRUD surfaces",        "items": [...] },
    { "name": "C",   "title": "Ripple HIGH callers",  "items": [...] },
    { "name": "D",   "title": "Design refs",          "items": [...] },
    { "name": "E",   "title": "Deliverables",         "items": [...] },
    { "name": "F",   "title": "Mobile gates",         "items": [...] }
  ],
  "total_items": <int>,
  "verdict_inputs": { "test_verdict": "PASSED|GAPS_FOUND|FAILED", "ripple_skipped": false }
}
```

## Per-section workflow (executed sequentially)

### Section A — Decisions (CONTEXT.md, KEEP-FLAT)

Match `P{phase}.D-XX` (new namespace) or `D-XX` (legacy). Mark legacy bare
`D-XX` with `(legacy — run migrate-d-xx-namespace.py)` suffix.

```bash
${PYTHON_BIN} - <<'PY' > "${VG_TMP}/uat-decisions.txt"
import re, os
from pathlib import Path
text = Path(os.environ["PHASE_DIR"], "CONTEXT.md").read_text(encoding="utf-8")
for m in re.finditer(r'^##?#?\s*(P[0-9.]+\.D-\d+|D-\d+)[:\s-]+([^\n]+)', text, re.MULTILINE):
    did = m.group(1)
    title = m.group(2).strip().rstrip('*').strip()[:100]
    suffix = "\t(legacy — run migrate-d-xx-namespace.py)" if re.match(r'^D-\d+$', did) else ""
    print(f"{did}\t{title}{suffix}")
PY
```

### Section A.1 — Foundation cites (FOUNDATION.md, KEEP-FLAT, conditional)

Scan all phase artifacts for `F-XX` references. If found, look up titles in
`${PLANNING_DIR}/FOUNDATION.md`. If no F-XX cites, emit empty section.

```bash
FOUNDATION_FILE="${PLANNING_DIR}/FOUNDATION.md"
if [ -f "$FOUNDATION_FILE" ]; then
  ${PYTHON_BIN} - <<'PY' > "${VG_TMP}/uat-foundation.txt"
import re, os
from pathlib import Path
phase_dir = Path(os.environ["PHASE_DIR"])
foundation = Path(os.environ["PLANNING_DIR"], "FOUNDATION.md")
cited = set()
for md in phase_dir.rglob("*.md"):
    try:
        for m in re.finditer(r'\bF-(\d+)\b', md.read_text(encoding="utf-8", errors="ignore")):
            cited.add(f"F-{m.group(1)}")
    except Exception:
        pass
if cited and foundation.exists():
    text = foundation.read_text(encoding="utf-8")
    for fid in sorted(cited):
        m = re.search(rf'^##?#?\s*{re.escape(fid)}[:\s-]+([^\n]+)', text, re.MULTILINE)
        title = m.group(1).strip().rstrip('*').strip()[:100] if m else "(stale cite — not in FOUNDATION.md)"
        print(f"{fid}\t{title}")
PY
fi
```

### Section B — Goals (vg-load split + GOAL-COVERAGE-MATRIX, CRITICAL: NO flat TEST-GOALS.md)

Use `vg-load --phase ${PHASE_NUMBER} --artifact goals --list` to enumerate
goals (Layer 1 split per Phase F Task 30). For each goal, expand via
`vg-load --phase ${PHASE_NUMBER} --artifact goals --goal G-NN`. Look up
status in `GOAL-COVERAGE-MATRIX.md` (KEEP-FLAT, single doc).

```bash
# Step 1 — list goals via vg-load (--list emits filenames like "G-01.md")
GOALS_LIST_RAW=$(bash "${REPO_ROOT}/.claude/scripts/vg-load.sh" \
  --phase "${PHASE_NUMBER}" --artifact goals --list 2>/dev/null)

# Normalize filenames → bare goal IDs (strip path + .md, drop index/non-G rows)
GOALS_LIST=$(echo "$GOALS_LIST_RAW" | sed -E 's|^.*/||; s|\.md$||' | grep -E '^G-[0-9]+$' || true)

# Step 2 — expand each + look up coverage status
COVERAGE="${PHASE_DIR}/GOAL-COVERAGE-MATRIX.md"
> "${VG_TMP}/uat-goals.txt"
while IFS= read -r gid; do
  [ -z "$gid" ] && continue
  TITLE=$(bash "${REPO_ROOT}/.claude/scripts/vg-load.sh" \
    --phase "${PHASE_NUMBER}" --artifact goals --goal "$gid" 2>/dev/null | \
    grep -m1 -oE '^# G-[0-9]+:?\s*.*' | sed -E 's/^# G-[0-9]+:?\s*//' | head -c 100)
  STATUS="UNKNOWN"
  if [ -f "$COVERAGE" ]; then
    LINE=$(grep -F "$gid" "$COVERAGE" 2>/dev/null | head -1)
    for tag in READY BLOCKED UNREACHABLE PARTIAL; do
      echo "$LINE" | grep -qi "$tag" && { STATUS="$tag"; break; }
    done
  fi
  echo -e "${gid}\t${STATUS}\t${TITLE}" >> "${VG_TMP}/uat-goals.txt"
done <<< "$GOALS_LIST"
```

### Section B.1 — CRUD surfaces (CRUD-SURFACES.md, KEEP-FLAT) + RCRURDR lifecycle items (R8-D)

Parse JSON inside fenced block. Each resource → row with operations,
platforms, checkpoints.

```bash
${PYTHON_BIN} - <<'PY' > "${VG_TMP}/uat-crud-surfaces.txt"
import json, re, os
from pathlib import Path
path = Path(os.environ["PHASE_DIR"], "CRUD-SURFACES.md")
if not path.exists():
    raise SystemExit(0)
text = path.read_text(encoding="utf-8", errors="replace")
m = re.search(r"```(?:json|crud-surface)\s*(\{.*?\})\s*```", text, re.DOTALL)
raw = m.group(1) if m else text.strip()
try:
    data = json.loads(raw)
except Exception as exc:
    print(f"INVALID\tparse-error\t{exc}")
    raise SystemExit(0)
for r in data.get("resources", []):
    if not isinstance(r, dict): continue
    name = r.get("name", "<unnamed>")
    ops = ",".join(r.get("operations", []))
    platforms = r.get("platforms", {}) if isinstance(r.get("platforms"), dict) else {}
    overlays = ",".join(sorted(platforms.keys()))
    cp = []
    if "web" in platforms:     cp.extend(["web:list/form/delete", "web:url-state", "web:a11y-states"])
    if "mobile" in platforms:  cp.extend(["mobile:deep-link", "mobile:tap-target", "mobile:offline/network"])
    if "backend" in platforms: cp.extend(["backend:query-contract", "backend:authz/csrf", "backend:abuse/perf"])
    base = r.get("base", {}) if isinstance(r.get("base"), dict) else {}
    if base: cp.extend(["base:business-flow", "base:security", "base:delete-policy"])
    print(f"{name}\t{ops}\t{overlays}\t{', '.join(dict.fromkeys(cp))}")
PY
```

#### R8-D — RCRURDR lifecycle attestation items (closed-loop accept layer)

Codex audit (2026-05-05) found accept layer MISSING on RCRURDR closed-loop:
generic "Verified working in runtime?" question per goal does NOT attest the
specific Read→Create→Read→Update→Read→Delete→Read mutation cycle.

For each TEST-GOAL with `lifecycle: rcrurdr` (or `goal_class: crud-roundtrip`),
emit a `RCRURD-<goal_id>` item into Section B.1 with the full 7-phase question.
These items are CRITICAL — failed attestation BLOCKs quorum gate (STEP 6).

Detection sources (in priority order):
1. Per-phase RCRURD-INVARIANTS/G-NN.yaml (Task 37 split — preferred)
2. Inline ```yaml-rcrurd fence in TEST-GOALS/G-NN.md (Task 39 — fallback,
   uses `scripts/lib/rcrurd_invariant.py extract_from_test_goal_md`)

```bash
${PYTHON_BIN} - <<'PY' > "${VG_TMP}/uat-rcrurd-items.txt"
import os, re, sys
from pathlib import Path

# Add scripts/ to path so we can import rcrurd_invariant
repo_root = Path(os.environ.get("REPO_ROOT", "."))
sys.path.insert(0, str(repo_root / "scripts"))
try:
    from lib.rcrurd_invariant import parse_yaml, extract_from_test_goal_md, RCRURDInvariantError
except Exception:
    # Helper unavailable — emit no rcrurd items (back-compat: harness silent,
    # no items generated, no theatre).
    sys.exit(0)

phase_dir = Path(os.environ["PHASE_DIR"])

# Source 1 — per-phase RCRURD-INVARIANTS/G-NN.yaml (Task 37 split)
inv_dir = phase_dir / "RCRURD-INVARIANTS"
seen: dict[str, str] = {}  # gid -> lifecycle
if inv_dir.is_dir():
    for yf in sorted(inv_dir.glob("G-*.yaml")):
        gid = yf.stem  # "G-04"
        try:
            inv = parse_yaml(yf.read_text(encoding="utf-8"))
        except RCRURDInvariantError:
            continue
        if inv.lifecycle == "rcrurdr":
            seen[gid] = "rcrurdr"

# Source 2 — inline yaml-rcrurd fence in TEST-GOALS/G-NN.md (Task 39 fallback)
goals_dir = phase_dir / "TEST-GOALS"
if goals_dir.is_dir():
    for gf in sorted(goals_dir.glob("G-*.md")):
        gid = gf.stem
        if gid in seen:
            continue
        try:
            inv = extract_from_test_goal_md(gf.read_text(encoding="utf-8"))
        except RCRURDInvariantError:
            continue
        if inv is not None and inv.lifecycle == "rcrurdr":
            seen[gid] = "rcrurdr"

# Look up goal title from existing uat-goals.txt (Section B output) so we
# can write a human-readable question prompt.
goals_txt = Path(os.environ["VG_TMP"], "uat-goals.txt")
title_by_id: dict[str, str] = {}
if goals_txt.exists():
    for line in goals_txt.read_text(encoding="utf-8", errors="ignore").splitlines():
        parts = line.split("\t")
        if len(parts) >= 3 and parts[0].startswith("G-"):
            title_by_id[parts[0]] = parts[2]

for gid in sorted(seen):
    title = title_by_id.get(gid, "(no title)")
    # tab-separated: rcrurd_item_id, source_goal, title, source_file
    print(f"RCRURD-{gid}\t{gid}\t{title}\tRCRURD-INVARIANTS/{gid}.yaml or TEST-GOALS/{gid}.md")
PY
```

The per-item question rendered by STEP 5 (interactive UAT) for each row:

```
Goal {goal_id} ({title}): Did you verify the FULL Read→Create→Read→Update→
Read→Delete→Read cycle?
  - Read empty (initial state)?
  - Create succeeds?
  - Read shows new entity?
  - Update mutates entity?
  - Read confirms update?
  - Delete succeeds?
  - Read empty after delete?

[p] Pass — full 7-phase cycle verified end-to-end
[f] Fail — at least one phase broken (BLOCKs quorum)
[s] Skip — cannot test in UAT (e.g. admin-only delete; logs override-debt)
```

Items emit into the JSON `sections[]` array under `name: "B.1"`, with a
distinguishing prefix `RCRURD-` on `id` so the quorum gate (STEP 6) can
locate them via `id.startswith("RCRURD-")`.

### Section C — Ripple HIGH callers (.ripple.json or RIPPLE-ANALYSIS.md, KEEP-FLAT)

```bash
RIPPLE_JSON="${PHASE_DIR}/.ripple.json"
RIPPLE_MD="${PHASE_DIR}/RIPPLE-ANALYSIS.md"
if [ -f "$RIPPLE_JSON" ]; then
  ${PYTHON_BIN} - <<'PY' > "${VG_TMP}/uat-ripples.txt"
import json, os
from pathlib import Path
d = json.loads(Path(os.environ["PHASE_DIR"], ".ripple.json").read_text(encoding="utf-8"))
count = 0
for r in d.get("ripples", []):
    for c in r.get("callers", []):
        print(f"{c['file']}:{c.get('line','?')}\t{c.get('symbol','?')}\t{r['changed_file']}")
        count += 1
print(f"# TOTAL_CALLERS={count}", flush=True)
PY
elif [ -f "$RIPPLE_MD" ]; then
  if grep -qi "SKIPPED\|unavailable\|not available\|stub" "$RIPPLE_MD" 2>/dev/null; then
    echo "# RIPPLE_SKIPPED=true" > "${VG_TMP}/uat-ripples.txt"
  else
    : > "${VG_TMP}/uat-ripples.txt"
  fi
else
  : > "${VG_TMP}/uat-ripples.txt"
fi
```

### Section D — Design refs (vg-load PLAN split, mobile screenshots from filesystem)

Use `vg-load --phase ${PHASE_NUMBER} --artifact plan --list` to enumerate
tasks (Layer 1 split). For each task, expand via vg-load and grep
`<design-ref>...</design-ref>` (NOT flat PLAN.md).

```bash
# Use vg-load for per-task expansion
> "${VG_TMP}/uat-designs.txt"
# --list emits filenames like "task-04.md" — strip path + .md + "task-" prefix
TASK_LIST_RAW=$(bash "${REPO_ROOT}/.claude/scripts/vg-load.sh" \
  --phase "${PHASE_NUMBER}" --artifact plan --list 2>/dev/null)
TASK_LIST=$(echo "$TASK_LIST_RAW" | sed -E 's|^.*/||; s|\.md$||; s|^task-||' | grep -E '^[0-9]+$' || true)
while IFS= read -r tid; do
  [ -z "$tid" ] && continue
  bash "${REPO_ROOT}/.claude/scripts/vg-load.sh" \
    --phase "${PHASE_NUMBER}" --artifact plan --task "$tid" 2>/dev/null | \
    grep -oE '<design-ref>[^<]+</design-ref>' | \
    sed -E 's/<design-ref>([^<]+)<\/design-ref>/\1/' >> "${VG_TMP}/uat-designs.txt"
done <<< "$TASK_LIST"
sort -u "${VG_TMP}/uat-designs.txt" -o "${VG_TMP}/uat-designs.txt"

# Mobile-only: collect simulator/emulator screenshots from filesystem
: > "${VG_TMP}/uat-mobile-screenshots.txt"
case "$PROFILE" in
  mobile-*)
    [ -d "${PHASE_DIR}/discover" ] && \
      find "${PHASE_DIR}/discover" -maxdepth 2 -type f \
        \( -name '*.png' -o -name '*.jpg' -o -name '*.jpeg' \) 2>/dev/null \
        | sort > "${VG_TMP}/uat-mobile-screenshots.txt"
    ;;
esac
```

### Section E — Deliverables summary (SUMMARY*.md glob, KEEP-FLAT)

```bash
${PYTHON_BIN} - <<'PY' > "${VG_TMP}/uat-summary.txt"
import re, os
from pathlib import Path
for s in sorted(Path(os.environ["PHASE_DIR"]).glob("*SUMMARY*.md")):
    text = s.read_text(encoding="utf-8")
    for m in re.finditer(r'^##?\s*(Task\s+\d+|Deliverable\s*\d+)[:\s-]+([^\n]+)', text, re.MULTILINE):
        title = m.group(2).strip().rstrip('*').strip()[:100]
        print(f"{s.name}\t{m.group(1)}\t{title}")
PY
```

### Section F — Mobile gates (mobile-* PROFILE only)

```bash
: > "${VG_TMP}/uat-mobile-gates.txt"
: > "${VG_TMP}/uat-mobile-security.txt"
case "$PROFILE" in
  mobile-*)
    export BUILD_LOG="${PHASE_DIR}/build-state.log"
    if [ -f "$BUILD_LOG" ]; then
      ${PYTHON_BIN} - <<'PY' > "${VG_TMP}/uat-mobile-gates.txt"
import re, os
log = open(os.environ["BUILD_LOG"], encoding="utf-8").read()
latest = {}
for m in re.finditer(r'mobile-gate-(\d+):\s*([a-z_]+)\s+status=(\w+)(?:\s+reason=([^\s]+))?\s*(?:ts=(\S+))?', log):
    gid, name, status, reason, ts = m.group(1), m.group(2), m.group(3), m.group(4) or '', m.group(5) or ''
    latest[gid] = (name, status, reason, ts)
for gid in sorted(latest, key=int):
    name, status, reason, ts = latest[gid]
    print(f"G{gid}\t{name}\t{status}\t{reason}\t{ts}")
PY
    fi
    SEC="${PHASE_DIR}/mobile-security/report.md"
    [ -f "$SEC" ] && grep -E "^(CRITICAL|HIGH|MEDIUM|LOW)\|" "$SEC" \
      > "${VG_TMP}/uat-mobile-security.txt" 2>/dev/null || true
    ;;
esac
```

## Final assembly — write `${PHASE_DIR}/uat-checklist.md`

Render markdown with one `## Section X — Title (count)` heading per
non-empty section, followed by a 3-column table (`| ID | Summary |
Source |`). Suppress Section F entirely when PROFILE not mobile-*.

Section B.1 must merge BOTH artefact streams:
1. CRUD-SURFACES rows from `${VG_TMP}/uat-crud-surfaces.txt`
2. R8-D RCRURDR attestation rows from `${VG_TMP}/uat-rcrurd-items.txt`
   — IDs prefixed `RCRURD-G-NN`, marked `critical: true` so quorum gate
   blocks failed attestation regardless of other passes.

Then read each `${VG_TMP}/uat-*.txt`, build the JSON `sections[]` array
with proper `{id, summary, source_file, source_line}` items, and emit
the JSON return to stdout. RCRURD-* items in B.1 carry an extra
`critical: true` field + `kind: "rcrurdr-attestation"` so STEP 5
interactive prompt and STEP 6 quorum gate know to special-case them.

## Failure modes (return error JSON, no partial files)

```json
{ "error": "missing_artifact", "field": "CRUD-SURFACES.md", "phase": "${PHASE_NUMBER}" }
{ "error": "vg_load_failed", "artifact": "goals", "stderr": "…" }
{ "error": "json_parse_failed", "field": "CRUD-SURFACES.md", "detail": "…" }
{ "error": "section_empty", "section": "B", "reason": "no goals matched" }
```

Do NOT write partial output on error.

## Why split (architecture rationale)

`commands/vg/accept.md` had this 291-line build inline. Empirical 96.5%
skip rate on inline heavy steps. Subagent extraction forces the work into
a fresh-context worker that cannot rationalize past it. Main agent only
reads the slim `overview.md` (≤120 lines) — context budget preserved for
interactive UAT (STEP 5) which requires full main-agent attention.
