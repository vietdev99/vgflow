---
name: vg:_shared:unreachable-triage
description: UNREACHABLE Triage (Shared Reference) — auto-classify each UNREACHABLE goal into cross-phase / bug-this-phase / scope-amend with evidence, write UNREACHABLE-TRIAGE.md, hard-gate accept on bug-this-phase
---

# UNREACHABLE Triage — Shared Helper

## v1.14.0+ Actionable triage (nâng cấp từ descriptive-only)

Trước v1.14: triage CHỈ phân loại + ghi file, user phải tự đọc + quyết.  
Từ v1.14 (2026-04-18): triage sinh `action_required` + `action_params` cho mỗi verdict, review Phase 3 autonomous thực thi không hỏi user trừ trường hợp destructive.

| Verdict | Nghĩa | Hành động tự động (review Phase 3) |
|---|---|---|
| `cross-phase:{X.Y}` — có tag `depends_on_phase: X.Y` ở scope | Goal thuộc phase khác, scope đã khai tag | `mark_deferred` — update GOAL-COVERAGE-MATRIX status=DEFERRED; ghi `.vg/CROSS-PHASE-DEPS.md` |
| `cross-phase-pending:{X.Y}` — cross-phase detect nhưng KHÔNG có tag scope | Phase khác owns goal nhưng scope chưa khai | `prompt_scope_tag` — mark goal BLOCKED; prompt user `/vg:amend {phase}` thêm `depends_on_phase: X.Y`; user offline → PENDING_USER_REVIEW queue |
| `bug-this-phase` | Phase này declare goal trong SPECS/CONTEXT nhưng UI không reach | `spawn_fix_agent` — spawn Sonnet fix agent inline với goal context; max 3 iterations per goal; fail → escalate |
| `scope-amend:additive` — goal thêm note/constraint/narrower scope | Amendment không xoá gì, chỉ bổ sung | `auto_apply_amendment` — sinh CONTEXT.md diff additive, auto-apply + log vào AUTO-AMENDMENT-LOG.md |
| `scope-amend:destructive` — cần drop goal / swap endpoint | Amendment thay đổi semantics | `draft_amendment_ask` — sinh diff + AskUserQuestion; user offline → mark goal `PENDING_AMENDMENT`, skip + continue review |

**Cổng accept (v1.14.0+):**
- `cross-phase:{X.Y}` (có tag) → ACCEPT OK (goal DEFERRED, tracked ở CROSS-PHASE-DEPS.md)
- `cross-phase-pending` → BLOCK accept until tag added or phase completes
- `bug-this-phase` → BLOCK accept until fix applied + re-verify
- `scope-amend:additive` → AUTO-RESOLVED (no block after auto-apply)
- `scope-amend:destructive` → BLOCK accept until user confirms amendment

**Lý do tách additive vs destructive:**  
Autonomous principle (spec section 2.5) — additive change không revert được người dùng sau (chỉ thêm data), safe auto-apply. Destructive change (drop goal) không revert được mà có thể hỏng downstream — phải user confirm.

---

## v1.13 legacy verdict table (giữ cho reference)

A goal is `UNREACHABLE` because the runtime probe could not reach the UI surface that would prove it. That happens for one of three reasons:

| Verdict | What it means | Action |
|---------|---------------|--------|
| **`cross-phase:{X.Y}`** | Another phase legitimately owns this view/route — current phase only depends on it | Resolve with citation. Allow accept (current phase isn't responsible for building it). If owning phase is not yet `accepted`, mark `cross-phase-pending:{X.Y}` and BLOCK accept until owning phase ships. |
| **`bug-this-phase`** | This phase's SPECS/CONTEXT mentions the route/component, but it isn't reachable in the running app | **BUG.** Block accept. Force a fix task in the next `/vg:build {phase} --gaps-only` cycle. |
| **`scope-amend`** | No phase claims it AND current SPECS doesn't mention the keywords | Goal was over-scoped or feature was de-scoped. Force `/vg:amend {phase}` to remove the goal OR `/vg:add-phase` to create a new phase that owns it. |

UNREACHABLE without a triage verdict = silent debt. Hard gate at `/vg:accept` rejects any phase shipping with `bug-this-phase` or `cross-phase-pending` outstanding.

## API

```bash
# Call from /vg:review step 4e (after GOAL-COVERAGE-MATRIX.md is written, before crossai_review)
# Inputs:
#   $PHASE_DIR   — current phase planning dir
#   $PHASE_NUMBER — e.g. "07.10.1"
# Outputs:
#   $PHASE_DIR/UNREACHABLE-TRIAGE.md (always written if any UNREACHABLE exists)
#   $PHASE_DIR/.unreachable-triage.json (machine-readable for accept gate)

triage_unreachable_goals() {
  local phase_dir="$1"
  local phase_number="$2"
  local matrix="${phase_dir}/GOAL-COVERAGE-MATRIX.md"
  local out_md="${phase_dir}/UNREACHABLE-TRIAGE.md"
  local out_json="${phase_dir}/.unreachable-triage.json"
  local planning_root
  planning_root="$(cd "${phase_dir}/../.." 2>/dev/null && pwd)"

  [ -f "$matrix" ] || { echo "(no GOAL-COVERAGE-MATRIX.md — skip triage)"; return 0; }

  ${PYTHON_BIN:-python3} - "$matrix" "$phase_dir" "$phase_number" "$planning_root" "$out_md" "$out_json" <<'PY'
import json, re, sys, os, subprocess
from pathlib import Path

matrix_path  = Path(sys.argv[1])
phase_dir    = Path(sys.argv[2])
phase_number = sys.argv[3]
planning_root= Path(sys.argv[4])
out_md       = Path(sys.argv[5])
out_json     = Path(sys.argv[6])

# 1) Extract UNREACHABLE goals from coverage matrix
matrix = matrix_path.read_text(encoding="utf-8", errors="ignore")
unreachables = []
for line in matrix.splitlines():
    if "UNREACHABLE" not in line.upper():
        continue
    m = re.search(r'(G-\d+)', line)
    if not m:
        continue
    gid = m.group(1)
    # Title is hard to extract reliably — pull from TEST-GOALS.md instead
    unreachables.append({"id": gid, "matrix_line": line.strip()})

if not unreachables:
    out_json.write_text(json.dumps({"unreachables": [], "verdicts": {}}, indent=2), encoding="utf-8")
    print("0 UNREACHABLE goals — no triage needed")
    sys.exit(0)

# 2) Load TEST-GOALS.md for full goal context (title, description, expected_view, route hints)
tg_path = phase_dir / "TEST-GOALS.md"
tg_text = tg_path.read_text(encoding="utf-8", errors="ignore") if tg_path.exists() else ""
# Goal blocks are typically: ### G-XX: Title  ...followed by description until next ###
goal_blocks = {}
for m in re.finditer(r'^#+\s*(G-\d+)[:\s\-]+([^\n]+)\n([\s\S]*?)(?=^#+\s*G-\d+|\Z)', tg_text, re.M):
    body = m.group(3).strip()
    # v1.14.0+ — extract scope-declared tags from goal body
    # Tag format (lines inside goal block): `depends_on_phase: 7.12` or `verification_strategy: manual`
    depends_on = None
    verify_strategy = None
    dm = re.search(r'^\s*depends_on_phase\s*:\s*([0-9]+(?:\.[0-9]+)*)\s*$', body, re.M | re.I)
    if dm:
        depends_on = dm.group(1)
    vm = re.search(r'^\s*verification_strategy\s*:\s*(manual|fixture|faketime|automated)\s*$', body, re.M | re.I)
    if vm:
        verify_strategy = vm.group(1).lower()
    goal_blocks[m.group(1)] = {
        "title":   m.group(2).strip(),
        "body":    body,
        "depends_on_phase":       depends_on,
        "verification_strategy":  verify_strategy,
    }

# 3) Load SPECS.md + CONTEXT.md for current phase to detect "should be in this phase"
specs_text = ""
ctx_text   = ""
for fname in ("SPECS.md", "CONTEXT.md"):
    p = phase_dir / fname
    if p.exists():
        if fname == "SPECS.md":
            specs_text = p.read_text(encoding="utf-8", errors="ignore")
        else:
            ctx_text = p.read_text(encoding="utf-8", errors="ignore")
self_spec = (specs_text + "\n" + ctx_text).lower()

# 4) Build cross-phase index — scan ALL other phases
def phase_status(phase_dir_other: Path) -> str:
    """Read PIPELINE-STATE.json or fall back to artifact presence to determine phase lifecycle."""
    state_path = phase_dir_other / "PIPELINE-STATE.json"
    if state_path.exists():
        try:
            s = json.loads(state_path.read_text(encoding="utf-8"))
            return str(s.get("status", "unknown"))
        except Exception:
            pass
    if (phase_dir_other / "UAT.md").exists():
        return "accepted"
    if (phase_dir_other / "RUNTIME-MAP.json").exists():
        return "reviewed"
    return "unknown"

phases_root = planning_root / "phases"
other_phases = []
if phases_root.exists():
    for p in sorted(phases_root.iterdir()):
        if not p.is_dir():
            continue
        if p == phase_dir:
            continue
        # Phase id is the directory name prefix, e.g. "07.10.1-..." -> "07.10.1"
        pid = p.name.split("-", 1)[0]
        other_phases.append({
            "id": pid,
            "dir": p,
            "status": phase_status(p)
        })

def keywords_for(goal_id: str) -> list[str]:
    """Extract distinctive tokens from a goal — route paths, PascalCase symbols, quoted phrases."""
    block = goal_blocks.get(goal_id, {})
    text = (block.get("title", "") + "\n" + block.get("body", "")).strip()
    if not text:
        # Fallback: matrix line is all we have
        text = next((u["matrix_line"] for u in unreachables if u["id"] == goal_id), "")
    kws = set()
    # Route paths: /foo, /foo/bar, /:id segments stripped
    for m in re.finditer(r'(?<![\w/])(/[a-z][a-z0-9\-_/]+)', text):
        path = re.sub(r'/:[\w]+', '', m.group(1)).rstrip('/')
        if len(path) > 2 and path.count('/') >= 1:
            kws.add(path.lower())
    # PascalCase / camelCase symbols (likely component names): MyComponent, useFoo
    for m in re.finditer(r'\b([A-Z][a-z]+(?:[A-Z][a-z]+){1,4})\b', text):
        kws.add(m.group(1))
    # Quoted phrases (often UI labels)
    for m in re.finditer(r'["`\']([^"`\'\n]{4,40})["`\']', text):
        kws.add(m.group(1).lower())
    return [k for k in kws if k]

def search_phase_for_keywords(phase_dir_other: Path, kws: list[str]) -> list[dict]:
    """Search the other phase's planning artifacts for any goal keyword. Return hit list with file+evidence."""
    hits = []
    if not kws:
        return hits
    candidates = [
        "GOAL-COVERAGE-MATRIX.md", "RUNTIME-MAP.md", "RUNTIME-MAP.json",
        "SUMMARY.md", "TEST-GOALS.md", "SPECS.md", "PLAN.md", "CONTEXT.md", "API-CONTRACTS.md"
    ]
    for fname in candidates:
        p = phase_dir_other / fname
        if not p.exists():
            continue
        try:
            content = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        content_lc = content.lower()
        for kw in kws:
            kw_lc = kw.lower()
            if kw_lc in content_lc:
                # Find line for citation
                for lineno, line in enumerate(content.splitlines(), 1):
                    if kw_lc in line.lower():
                        hits.append({
                            "file": str(p.relative_to(planning_root.parent)) if planning_root.parent in p.parents else str(p),
                            "line": lineno,
                            "keyword": kw,
                            "snippet": line.strip()[:120]
                        })
                        break
                break  # one kw hit per file is enough
    return hits

def runtime_verifies(phase_dir_other: Path, kws: list[str]) -> bool:
    """Stronger evidence: phase's RUNTIME-MAP.json actually contains a view matching one of the keywords (proves reachability, not just claim)."""
    rm_path = phase_dir_other / "RUNTIME-MAP.json"
    if not rm_path.exists() or not kws:
        return False
    try:
        rm = json.loads(rm_path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return False
    rm_str = json.dumps(rm).lower()
    return any(kw.lower() in rm_str for kw in kws)

# 5) Triage each UNREACHABLE
verdicts = {}
for u in unreachables:
    gid = u["id"]
    kws = keywords_for(gid)
    block = goal_blocks.get(gid, {})

    # v1.14.0+ — Scope tag short-circuit (autonomous-first)
    block = goal_blocks.get(gid, {})
    scope_depends_on = block.get("depends_on_phase")
    scope_verify_strategy = block.get("verification_strategy")

    if scope_verify_strategy in ("manual", "fixture", "faketime"):
        # User đã khai ở scope — goal verify bằng cách khác (không phải browser replay)
        verdicts[gid] = {
            "verdict": f"scope-declared-{scope_verify_strategy}",
            "blocks_accept": False,
            "title": block.get("title", "(no title)"),
            "keywords": [],
            "cross_hits": [],
            "matrix_line": u["matrix_line"],
            "action_required": "mark_manual",
            "action_params": {"strategy": scope_verify_strategy},
        }
        continue

    if scope_depends_on:
        # User đã khai ở scope — goal thuộc phase khác (DEFERRED)
        verdicts[gid] = {
            "verdict": f"cross-phase:{scope_depends_on}",
            "blocks_accept": False,
            "title": block.get("title", "(no title)"),
            "keywords": [],
            "cross_hits": [],
            "matrix_line": u["matrix_line"],
            "action_required": "mark_deferred",
            "action_params": {"target_phase": scope_depends_on},
        }
        continue

    # 5a) Search every other phase
    cross_hits = []
    for op in other_phases:
        hits = search_phase_for_keywords(op["dir"], kws)
        if hits:
            cross_hits.append({
                "phase": op["id"],
                "status": op["status"],
                "verified_in_runtime": runtime_verifies(op["dir"], kws),
                "evidence": hits[:3]  # cap to 3 for readability
            })

    # 5b) Decide verdict
    if cross_hits:
        # Prefer runtime-verified phase, then accepted, then reviewed, then any
        cross_hits.sort(key=lambda c: (
            not c["verified_in_runtime"],
            c["status"] != "accepted",
            c["status"] != "reviewed",
            c["phase"]
        ))
        owner = cross_hits[0]
        if owner["status"] == "accepted" and owner["verified_in_runtime"]:
            verdict = f"cross-phase:{owner['phase']}"
            blocks_accept = False
        else:
            verdict = f"cross-phase-pending:{owner['phase']}"
            blocks_accept = True  # owning phase hasn't shipped yet — current phase can't claim done
        evidence = cross_hits
    else:
        # No other phase claims it
        # Check if current phase's SPECS/CONTEXT mentions any keyword
        owns = any(kw.lower() in self_spec for kw in kws) if kws else False
        if owns:
            verdict = "bug-this-phase"
            blocks_accept = True
        else:
            verdict = "scope-amend"
            blocks_accept = True  # decision required before accept
        evidence = []

    # v1.14.0+ action_required mapping (review Phase 3 auto-thực thi)
    if verdict.startswith("cross-phase-pending:"):
        action_required = "prompt_scope_tag"
        action_params = {"target_phase": verdict.split(":", 1)[1], "reason": "cross-phase detected but scope không khai depends_on_phase"}
    elif verdict.startswith("cross-phase:"):
        # Legacy verdict (no scope tag) — trong v1.14.0 đã short-circuit ở trên,
        # nhưng giữ fallback cho phases migrate chưa gắn tag
        action_required = "mark_deferred"
        action_params = {"target_phase": verdict.split(":", 1)[1]}
    elif verdict == "bug-this-phase":
        action_required = "spawn_fix_agent"
        action_params = {"keywords": list(kws), "evidence_from_self_spec": True}
    elif verdict == "scope-amend":
        # Classify additive vs destructive — heuristic đơn giản
        # additive: phrase chỉ đang nói về "thêm constraint/note" không xoá goal khỏi scope
        # destructive: không khớp phase khác + không có trong SPECS → drop goal
        action_required = "draft_amendment_ask"  # destructive default — user phải confirm drop
        action_params = {"amendment_type": "destructive", "reason": "goal không còn thuộc phase scope"}
    else:
        action_required = None
        action_params = {}

    verdicts[gid] = {
        "verdict": verdict,
        "blocks_accept": blocks_accept,
        "title": block.get("title", "(no title)"),
        "keywords": kws,
        "cross_hits": evidence,
        "matrix_line": u["matrix_line"],
        "action_required": action_required,
        "action_params": action_params,
    }

# 6) Write JSON for downstream gate
out_json.write_text(
    json.dumps({"unreachables": [u["id"] for u in unreachables], "verdicts": verdicts}, indent=2),
    encoding="utf-8"
)

# 7) Write human-readable triage report
lines = [
    f"# UNREACHABLE Triage — Phase {phase_number}",
    "",
    f"**Total UNREACHABLE goals:** {len(unreachables)}",
    "",
    "Each UNREACHABLE goal must resolve to one of three verdicts before this phase can be accepted:",
    "",
    "- `cross-phase:{X.Y}` — another (already-accepted) phase owns this; current phase has no fix obligation",
    "- `cross-phase-pending:{X.Y}` — owning phase exists but isn't accepted yet; current phase BLOCKED until it ships",
    "- `bug-this-phase` — current phase claims this in SPECS/CONTEXT but UI is unreachable; **BUG**, must fix",
    "- `scope-amend` — no phase claims this; needs `/vg:amend` (remove goal) or `/vg:add-phase` (new owner)",
    "",
    "---",
    ""
]

# Group by verdict
groups = {"cross-phase": [], "cross-phase-pending": [], "bug-this-phase": [], "scope-amend": []}
for gid, v in verdicts.items():
    key = "cross-phase" if v["verdict"].startswith("cross-phase:") else \
          "cross-phase-pending" if v["verdict"].startswith("cross-phase-pending:") else \
          v["verdict"]
    groups[key].append((gid, v))

# bug-this-phase first (loudest)
for grp_key, header, icon in [
    ("bug-this-phase",        "## Bug in this phase (BLOCK accept)",                "🐛"),
    ("cross-phase-pending",   "## Cross-phase, owner not yet accepted (BLOCK accept)", "⏸"),
    ("scope-amend",           "## Scope amendment required (BLOCK accept)",         "📝"),
    ("cross-phase",           "## Cross-phase, owner accepted (resolved)",          "✅"),
]:
    items = groups[grp_key]
    if not items:
        continue
    lines.append(header)
    lines.append("")
    for gid, v in items:
        lines.append(f"### {icon} {gid} — {v['verdict']}")
        lines.append(f"- **Title:** {v['title']}")
        if v["keywords"]:
            lines.append(f"- **Keywords searched:** `{', '.join(v['keywords'][:8])}`")
        if v["cross_hits"]:
            lines.append("- **Evidence in other phases:**")
            for hit in v["cross_hits"]:
                rt = " (runtime-verified)" if hit["verified_in_runtime"] else ""
                lines.append(f"  - Phase {hit['phase']} [{hit['status']}]{rt}")
                for ev in hit["evidence"]:
                    lines.append(f"    - `{ev['file']}:{ev['line']}` — {ev['snippet']}")
        if grp_key == "bug-this-phase":
            lines.append(f"- **Required fix:** `/vg:build {phase_number} --gaps-only` (will pick up via TEST-GOALS gap)")
        elif grp_key == "scope-amend":
            lines.append(f"- **Required action:** `/vg:amend {phase_number}` to remove or re-scope goal, OR `/vg:add-phase` to create owning phase")
        elif grp_key == "cross-phase-pending":
            owner_phase = v["verdict"].split(":", 1)[1]
            lines.append(f"- **Required action:** wait for Phase {owner_phase} to reach `accepted`, OR move goal out of this phase via `/vg:amend`")
        lines.append("")

# Counts summary at top — replace placeholder
n_bug      = len(groups["bug-this-phase"])
n_pending  = len(groups["cross-phase-pending"])
n_amend    = len(groups["scope-amend"])
n_resolved = len(groups["cross-phase"])
blocking   = n_bug + n_pending + n_amend
lines.insert(4, f"- **Blocking accept:** {blocking} (bug={n_bug} · pending={n_pending} · amend={n_amend})")
lines.insert(5, f"- **Resolved (cross-phase):** {n_resolved}")
lines.insert(6, "")

out_md.write_text("\n".join(lines), encoding="utf-8")

# 8) Summary to stdout for narration
print(f"UNREACHABLE triage: {len(unreachables)} goals → bug={n_bug} pending={n_pending} amend={n_amend} resolved={n_resolved}")
if blocking > 0:
    print(f"⛔ {blocking} goals BLOCK accept — see UNREACHABLE-TRIAGE.md")
else:
    print(f"✅ All UNREACHABLE goals resolved as cross-phase")
PY
}

# Hard gate for /vg:accept — call BEFORE the UAT questionnaire is presented
unreachable_triage_accept_gate() {
  local phase_dir="$1"
  local phase_number="$2"
  local triage_json="${phase_dir}/.unreachable-triage.json"

  # No triage file → no UNREACHABLE goals existed → pass
  [ -f "$triage_json" ] || return 0

  ${PYTHON_BIN:-python3} - "$triage_json" "$phase_number" <<'PY'
import json, sys
from pathlib import Path
data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
phase = sys.argv[2]
blocking = []
for gid, v in data.get("verdicts", {}).items():
    if v.get("blocks_accept"):
        blocking.append((gid, v["verdict"], v["title"]))
if not blocking:
    sys.exit(0)
print("")
print(f"⛔ /vg:accept BLOCKED — {len(blocking)} UNREACHABLE goals need resolution before phase {phase} can ship:")
print("")
for gid, verdict, title in blocking:
    print(f"  • {gid} [{verdict}] — {title[:80]}")
print("")
print(f"See {Path(sys.argv[1]).parent}/UNREACHABLE-TRIAGE.md for evidence + required actions.")
print("")
print("Fix paths by verdict:")
print(f"  bug-this-phase       → /vg:build {phase} --gaps-only")
print(f"  cross-phase-pending  → wait for owning phase to reach 'accepted', OR /vg:amend {phase}")
print(f"  scope-amend          → /vg:amend {phase}  (remove goal or move to new phase)")
print("")
print("Override (creates debt — logged to override-debt register):")
print(f"  /vg:accept {phase} --allow-unreachable --reason='<why shipping with known gaps>'")
sys.exit(1)
PY
}
```

## Integration

### In `/vg:review` step `gate_evaluation` (immediately after 4d writes GOAL-COVERAGE-MATRIX.md)

```bash
<step name="unreachable_triage">
session_mark_step "4f-unreachable-triage"
echo ""
echo "🔍 UNREACHABLE triage — classifying unresolved goals..."
triage_unreachable_goals "$PHASE_DIR" "$PHASE_NUMBER"
# Output: UNREACHABLE-TRIAGE.md + .unreachable-triage.json
# Does NOT block review exit — block happens at /vg:accept
</step>
```

Add `UNREACHABLE-TRIAGE.md` and `.unreachable-triage.json` to `git add` in `write_artifacts`.

### In `/vg:accept` (before Section A questionnaire)

```bash
<step name="unreachable_gate">
unreachable_triage_accept_gate "$PHASE_DIR" "$PHASE_NUMBER"
# Exits 1 if blocking UNREACHABLE goals remain — accept aborts
# Override: --allow-unreachable + reason
</step>
```

If `--allow-unreachable` flag passed, log to override-debt register (via `_shared/override-debt.md`) instead of blocking.

## Override semantics (override-debt integration)

```bash
# Inside /vg:accept after gate, if --allow-unreachable:
if [[ "$ARGUMENTS" =~ --allow-unreachable ]]; then
  reason=$(echo "$ARGUMENTS" | grep -oE -- "--reason='[^']+'" | sed "s/--reason='//; s/'$//")
  [ -z "$reason" ] && { echo "⛔ --allow-unreachable requires --reason='...'"; exit 1; }
  override_debt_record "unreachable-accept" "$PHASE_NUMBER" "$reason"
  echo "⚠ Accept proceeding with UNREACHABLE debt — logged to override-debt register"
fi
```

## Why each verdict has the action it does

- **`cross-phase:{X.Y}` (no block)**: another phase already proved this works in its RUNTIME-MAP. Current phase legitimately depends on it. No fix obligation here — just citation.
- **`cross-phase-pending:{X.Y}` (block)**: even if SPEC says "X.Y will build this", we cannot ship phase saying goal is met when the proof doesn't exist yet. Wait, or move goal.
- **`bug-this-phase` (block)**: SPECS says this phase builds it. UI doesn't reach it. Definition of a regression / missed task. `/vg:build --gaps-only` re-runs planner on the gap.
- **`scope-amend` (block)**: planning artifact disagrees with reality. Either the goal shouldn't exist (remove via `/vg:amend`) or it needs a real owner (new phase via `/vg:add-phase`). Silent acceptance = fictional roadmap.

## Success criteria

- Every `/vg:review` run that produces UNREACHABLE goals writes `UNREACHABLE-TRIAGE.md` with one verdict per goal
- Each verdict cites concrete evidence (file:line for cross-phase, keyword set for self-spec match)
- `/vg:accept` cannot pass with `bug-this-phase` / `cross-phase-pending` / `scope-amend` outstanding (unless `--allow-unreachable` + reason)
- Cross-phase verification reads target phase's RUNTIME-MAP.json (proof of reachability), not just claims in PLAN.md
- Override path goes through override-debt register, surfaces in `/vg:telemetry` and milestone audit
