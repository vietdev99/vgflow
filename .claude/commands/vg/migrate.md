---
name: vg:migrate
description: Convert legacy GSD phase artifacts to VG format
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
  - Agent
  - AskUserQuestion
mutates_repo: true
runtime_contract:
  must_emit_telemetry:
    - event_type: "migrate.started"
    - event_type: "migrate.completed"
---

<rules>
1. **Non-destructive** — never delete GSD originals. Move to `.gsd-backup/` within phase dir.
2. **MERGE, DO NOT OVERWRITE (tightened 2026-04-17)** — any existing artifact with user-authored content must be merged, not replaced. Agent writes to `{file}.staged` (not target). Before promoting staging → target, run preservation gates:
   - **ID preservation**: every `D-XX` (decisions) / `G-XX` (goals) / `Task N` / endpoint path in original MUST exist in staging. Missing = agent dropped content → ABORT, original untouched.
   - **Body preservation**: each element's body text must be ≥ 80% similar to original (`difflib.SequenceMatcher`). Lower ratio = agent rewrote prose → ABORT.
   - **On fail**: staging kept at `{file}.staged` for user inspection; backup at `.gsd-backup/{file}.{original-ext}`.
   Applies to: CONTEXT.md (step 4), API-CONTRACTS.md (step 5), TEST-GOALS.md (step 6), PLAN.md (step 7).
3. **Idempotent** — running migrate twice on same phase produces same result. Skip already-converted artifacts.
4. **Config-driven** — all format decisions from vg.config.md (contract_format, scan_patterns, etc.)
5. **No hardcoded project values** — endpoint paths, file locations, domain names all from config or code scan.
6. **Profile enforcement** — `(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "migrate" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/migrate.done"` at end.
</rules>

<objective>
Convert a phase that was planned/built using GSD workflows into VG-native format.
Ensures all VG pipeline steps (review, test, accept) can run on the migrated phase.

When to use:
- Project previously used GSD, now switching to VG
- Phase has CONTEXT.md (GSD format) but no API-CONTRACTS.md or TEST-GOALS.md
- Phase has old-style PLAN.md without VG task attributes
- `/vg:next` shows phase as `legacy_gsd` type
</objective>

<process>

**Config:** Read .claude/commands/vg/_shared/config-loader.md first.

### Preflight section (extracted v2.72.0 T1)

Read `_shared/migrate/preflight.md` and follow it exactly.
Includes 3 steps: 1_parse_args, 2_detect_artifacts, 3_backup_originals.

### Enrich section (extracted v2.72.0 T2)

Read `_shared/migrate/enrich.md` and follow it exactly.
Includes 2 steps: 4_enrich_context, 5_generate_contracts.

### Goals + plans (extracted v2.72.0 T3)

Read `_shared/migrate/goals-plans.md` and follow it exactly.
Includes 3 steps: 6_generate_goals, 6_5_link_plan_goals, 7_attribute_plans.

<step name="8_write_pipeline_state">
## Initialize VG Pipeline State

```bash
# Write PIPELINE-STATE.json if not exists
PIPELINE_STATE="${PHASE_DIR}/PIPELINE-STATE.json"
if [ ! -f "$PIPELINE_STATE" ]; then
  ${PYTHON_BIN} -c "
import json
from datetime import datetime
state = {
  'status': 'migrated',
  'pipeline_step': 'review',
  'migrated_from': 'gsd',
  'migrated_at': datetime.now().isoformat(),
  'updated_at': datetime.now().isoformat(),
  'artifacts': {
    'context': 'enriched',
    'contracts': 'generated' if not skip_contracts else 'skipped',
    'goals': 'generated' if not skip_goals else 'skipped',
    'plans': 'attributed' if plan_format == 'gsd-plain' else 'already_vg',
  }
}
with open('${PIPELINE_STATE}', 'w') as f:
  json.dump(state, f, indent=2)
print('PIPELINE-STATE.json written')
"
fi

# Update .recon-state.json for /vg:next routing
${PYTHON_BIN} .claude/scripts/phase-recon.py \
  --phase-dir "${PHASE_DIR}" --profile "${PROFILE}" --quiet 2>/dev/null || true
```
</step>

<step name="8b_backfill_infra">
## Backfill Project-Level Infra Registers (2026-04-17)

Runs ONCE per project (idempotent). If project has multiple phases being migrated, this step auto-skips after first run. Use `--force-infra` to re-run.

VG infra features (debt/telemetry/security/visual/graphify) depend on registers that don't exist in legacy projects. Scan historical artifacts to backfill.

**Skip if already done:**
```bash
INFRA_MARKER=".planning/.infra-backfill.done"
if [ -f "$INFRA_MARKER" ] && [[ ! "$FLAGS" =~ --force-infra ]]; then
  echo "Infra already backfilled (${INFRA_MARKER}). Use --force-infra to re-run."
else
```

**8b.1 — Debt register backfill** (if `CONFIG_DEBT_REGISTER_PATH` config present):
```bash
if [ -n "${CONFIG_DEBT_REGISTER_PATH}" ] && [ ! -f "${CONFIG_DEBT_REGISTER_PATH}" ]; then
  ${PYTHON_BIN} - "${CONFIG_DEBT_REGISTER_PATH}" <<'PY'
import os, re, sys, glob
from datetime import datetime, timezone
from pathlib import Path
register = Path(sys.argv[1])
register.parent.mkdir(parents=True, exist_ok=True)

patterns = {
  "--allow-missing-commits": "critical", "--override-reason": "critical",
  "--override-regressions": "critical", "--force-accept-with-debt": "critical",
  "--allow-no-tests": "high", "--skip-design-check": "high",
  "--allow-intermediate": "high", "--skip-context-rebuild": "high",
  "--skip-crossai": "medium", "--skip-research": "medium", "--allow-deferred": "medium",
}

rows, count = [], 0
for phase_dir in sorted(glob.glob(".planning/phases/*/")):
  phase = Path(phase_dir).name.split("-")[0] if "-" in Path(phase_dir).name else Path(phase_dir).name
  for fname in ("build-state.log", "SANDBOX-TEST.md", "UAT.md"):
    fpath = Path(phase_dir) / fname
    if not fpath.exists(): continue
    try: text = fpath.read_text(encoding='utf-8', errors='ignore')
    except Exception: continue
    mtime = datetime.fromtimestamp(fpath.stat().st_mtime, tz=timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z')
    for pat, sev in patterns.items():
      for line in text.splitlines():
        if pat in line:
          count += 1
          reason = (line.strip()[:100]).replace("|","\\|")
          rows.append(f"| DEBT-HIST-{count:03d} | {sev} | {phase} | historical-{fname} | `{pat}` | {reason} | {mtime} | RESOLVED | (backfill) |")
          break  # one match per file per pattern

with open(register, 'w', encoding='utf-8') as f:
  f.write("# Override Debt Register\n\nAuto-maintained by VG workflow. Backfilled from historical artifacts.\n\n## Entries\n\n")
  f.write("| ID | Severity | Phase | Step | Flag | Reason | Logged (UTC) | Status | Resolved |\n")
  f.write("|----|----------|-------|------|------|--------|--------------|--------|----------|\n")
  f.write("\n".join(rows) + "\n")
print(f"  Debt backfill: {count} historical entries")
PY
else
  echo "  Debt register exists or not configured — skip"
fi
```

**8b.2 — Security register consolidation** (if `CONFIG_SECURITY_REGISTER_PATH` config present):
```bash
if [ -n "${CONFIG_SECURITY_REGISTER_PATH}" ] && [ ! -f "${CONFIG_SECURITY_REGISTER_PATH}" ]; then
  ${PYTHON_BIN} - "${CONFIG_SECURITY_REGISTER_PATH}" <<'PY'
import os, re, sys, glob
from datetime import datetime, timezone
from pathlib import Path
register = Path(sys.argv[1])
register.parent.mkdir(parents=True, exist_ok=True)

sev_map = {"critical":"critical","high":"high","medium":"medium","low":"low","info":"info"}
status_map = {"open":"OPEN","mitigated":"MITIGATED","resolved":"MITIGATED","fixed":"MITIGATED","in_progress":"IN_PROGRESS"}
threats, count = [], 0

for sec_file in sorted(glob.glob(".planning/phases/*/SECURITY*.md")) + sorted(glob.glob(".planning/phases/*/security.md")):
  phase = Path(sec_file).parent.name.split("-")[0] if "-" in Path(sec_file).parent.name else Path(sec_file).parent.name
  text = open(sec_file, encoding='utf-8', errors='ignore').read()
  blocks = re.split(r'^##\s+(?:Finding|Issue|Threat)[\s:]', text, flags=re.M|re.I)[1:]
  for blk in blocks:
    lines = blk.splitlines()
    title = (lines[0].strip().lstrip(':').strip() if lines else "untitled")[:100]
    sev, status, evidence, tax = "medium", "OPEN", "-", "custom"
    for line in lines:
      l = line.lower().strip()
      m = re.search(r'severity:\s*(\w+)', l);   sev = sev_map.get(m.group(1), sev) if m else sev
      m = re.search(r'status:\s*(\w+)', l);     status = status_map.get(m.group(1), status.upper()) if m else status
      m = re.search(r'evidence:\s*(.+)', line, re.I); evidence = m.group(1).strip()[:80] if m else evidence
      if l.startswith("taxonomy:") or l.startswith("stride:") or l.startswith("owasp:"):
        tax = line.split(":",1)[1].strip()[:40] if ":" in line else tax
    count += 1
    ts = datetime.fromtimestamp(Path(sec_file).stat().st_mtime, tz=timezone.utc).date().isoformat()
    threats.append((f"SEC-{count:03d}", sev, phase, tax, title, status, evidence, ts))

milestone = os.environ.get("MILESTONE_ID", "legacy")
with open(register, 'w', encoding='utf-8') as f:
  f.write(f"# Security Register (Milestone: {milestone})\n\nCumulative threat ledger. Backfilled from per-phase SECURITY.md files.\n\n## Threats\n\n")
  f.write("| ID | Severity | Phase(s) | Taxonomy | Title | Mitigation Status | Evidence | Created | Last Updated |\n")
  f.write("|----|----------|----------|----------|-------|-------------------|----------|---------|--------------|\n")
  for t in threats: f.write("| " + " | ".join(t[:7]) + f" | {t[7]} | {t[7]} |\n")
  f.write("\n## Composite Threats (auto-correlated)\n\n| Composite ID | Component SEC-IDs | Phases | Combined Severity | Rule |\n|-------------|-------------------|--------|-------------------|------|\n")
  f.write(f"\n## Decay Log\n- {datetime.now(timezone.utc).date().isoformat()} Backfilled {count} threats via /vg:migrate\n")
  f.write(f"\n## Audit Trail\n- {datetime.now(timezone.utc).date().isoformat()} /vg:migrate infra backfill: +{count} threats\n")
print(f"  Security backfill: {count} threats from legacy SECURITY.md files")
PY
else
  echo "  Security register exists or not configured — skip"
fi
```

**8b.3 — Telemetry init + git-log phase reconstruction**:
```bash
if [ -n "${CONFIG_TELEMETRY_PATH}" ] && [ ! -f "${CONFIG_TELEMETRY_PATH}" ]; then
  mkdir -p "$(dirname "${CONFIG_TELEMETRY_PATH}")"
  TS=$(date -u +%FT%TZ); SHA=$(git rev-parse --short HEAD 2>/dev/null || echo unknown)
  echo "{\"ts\":\"${TS}\",\"event\":\"bootstrap\",\"phase\":\"\",\"step\":\"migrate\",\"session_id\":\"migrate\",\"git_sha\":\"${SHA}\",\"meta\":{\"reason\":\"vg:migrate infra backfill\"}}" > "${CONFIG_TELEMETRY_PATH}"

  # Reconstruct phase timings from git log commits (feat(X.Y-NN): pattern)
  ${PYTHON_BIN} - "${CONFIG_TELEMETRY_PATH}" <<'PY'
import subprocess, json, re, sys
from datetime import datetime
from pathlib import Path
path = Path(sys.argv[1])
r = subprocess.run(["git","log","--pretty=format:%H|%cI|%s","--reverse"], capture_output=True, text=True)
first, last = {}, {}
for line in r.stdout.splitlines():
  parts = line.split("|",2)
  if len(parts) != 3: continue
  sha, ts, msg = parts
  m = re.match(r'^(feat|fix|chore|docs|test|refactor)\((\d+(?:\.\d+)*)-\d+\):', msg)
  if not m: continue
  phase = m.group(2)
  first.setdefault(phase, (sha, ts))
  last[phase] = (sha, ts)
with open(path, 'a', encoding='utf-8') as f:
  for phase in sorted(first):
    s_sha, s_ts = first[phase]; e_sha, e_ts = last[phase]
    dur = int((datetime.fromisoformat(e_ts) - datetime.fromisoformat(s_ts)).total_seconds())
    f.write(json.dumps({"ts":e_ts,"event":"phase_complete_backfill","phase":phase,"step":"bootstrap-from-git","session_id":"migrate","git_sha":e_sha[:8],"meta":{"duration_s":dur,"source":"git-log"}}) + "\n")
print(f"  Telemetry init + {len(first)} phase timing events reconstructed from git log")
PY
else
  echo "  Telemetry already initialized or not configured — skip"
fi
```

**8b.4 — Graphify rebuild marker** (assume current graph is fresh, so first `/vg:map` after migrate doesn't force full rebuild):
```bash
GRAPH_MARKER="${CONFIG_PATHS_PLANNING_DIR:-.planning}/.graphify-last-rebuild"
if [ ! -f "$GRAPH_MARKER" ] && [ -f .claude/scripts/graphify-incremental.py ]; then
  ${PYTHON_BIN} .claude/scripts/graphify-incremental.py mark --marker "$GRAPH_MARKER" 2>/dev/null && \
    echo "  Graphify marker initialized"
fi
```

**8b.5 — Visual baseline auto-promote** (only if `visual_regression.enabled`):
```bash
if [ "${CONFIG_VISUAL_REGRESSION_ENABLED:-false}" = "true" ] && [ -d "${CONFIG_VISUAL_REGRESSION_CURRENT_DIR}" ] && [ ! -d "${CONFIG_VISUAL_REGRESSION_BASELINE_DIR}" ]; then
  for sd in "${CONFIG_VISUAL_REGRESSION_CURRENT_DIR}"/*/; do
    [ -d "$sd" ] || continue
    phase=$(basename "$sd")
    ${PYTHON_BIN} .claude/scripts/visual-diff.py promote --from "$sd" --to "${CONFIG_VISUAL_REGRESSION_BASELINE_DIR}/${phase}" 2>/dev/null
  done
  echo "  Visual baseline promoted from existing screenshots"
fi
```

**Mark infra backfill done:**
```bash
mkdir -p .planning
touch "$INFRA_MARKER"
fi  # end "already done" skip guard
```
</step>

<step name="9_validate_and_report">
## Validation + Report

**Completeness checks:**

```bash
echo "=== Migration Validation ==="

PASS=0
WARN=0
FAIL=0

# Check CONTEXT.md enriched
if grep -q "^\*\*Endpoints:\*\*" "${PHASE_DIR}/CONTEXT.md" 2>/dev/null; then
  echo "  [PASS] CONTEXT.md enriched"
  ((PASS++))
else
  echo "  [FAIL] CONTEXT.md not enriched"
  ((FAIL++))
fi

# Check API-CONTRACTS.md
if [ -f "${PHASE_DIR}/API-CONTRACTS.md" ]; then
  BLOCKS=$(grep -c '```typescript\|```yaml\|```python' "${PHASE_DIR}/API-CONTRACTS.md" 2>/dev/null || echo 0)
  if [ "$BLOCKS" -gt 0 ]; then
    echo "  [PASS] API-CONTRACTS.md with ${BLOCKS} code blocks"
    ((PASS++))
  else
    echo "  [WARN] API-CONTRACTS.md exists but no code blocks"
    ((WARN++))
  fi
else
  if [[ "$FLAGS" =~ --skip-contracts ]]; then
    echo "  [SKIP] API-CONTRACTS.md (--skip-contracts)"
  else
    echo "  [FAIL] API-CONTRACTS.md missing"
    ((FAIL++))
  fi
fi

# Check TEST-GOALS.md
if [ -f "${PHASE_DIR}/TEST-GOALS.md" ]; then
  GOALS=$(grep -c "^## Goal G-" "${PHASE_DIR}/TEST-GOALS.md" 2>/dev/null || echo 0)
  echo "  [PASS] TEST-GOALS.md with ${GOALS} goals"
  ((PASS++))
else
  if [[ "$FLAGS" =~ --skip-goals ]]; then
    echo "  [SKIP] TEST-GOALS.md (--skip-goals)"
  else
    echo "  [FAIL] TEST-GOALS.md missing"
    ((FAIL++))
  fi
fi

# Check PLAN.md attributed
if ls "${PHASE_DIR}"/PLAN*.md 2>/dev/null; then
  ATTRS=$(grep -c "<file-path>" "${PHASE_DIR}"/PLAN*.md 2>/dev/null || echo 0)
  TASKS=$(grep -c "^##\{1,2\} Task" "${PHASE_DIR}"/PLAN*.md 2>/dev/null || echo 0)
  if [ "$ATTRS" -gt 0 ]; then
    echo "  [PASS] PLAN.md attributed (${ATTRS}/${TASKS} tasks have file-path)"
    ((PASS++))
  else
    echo "  [WARN] PLAN.md exists but no VG attributes"
    ((WARN++))
  fi
fi

# Check backups exist
BACKUPS=$(ls "${PHASE_DIR}/.gsd-backup/" 2>/dev/null | wc -l)
echo "  [INFO] ${BACKUPS} backup file(s) in .gsd-backup/"

# === VG semantic gates (v1.14.4+ — real downstream verify) ===
echo ""
echo "=== VG Semantic Gates (mirror downstream blueprint/build/test requirements) ==="

# Gate A: CONTEXT — 3 sub-sections per decision
if [ -f "${PHASE_DIR}/CONTEXT.md" ]; then
  D=$(grep -cE "^#+\s*D-[0-9]+" "${PHASE_DIR}/CONTEXT.md")
  E=$(grep -c "^\*\*Endpoints:\*\*" "${PHASE_DIR}/CONTEXT.md")
  U=$(grep -c "^\*\*UI Components:\*\*" "${PHASE_DIR}/CONTEXT.md")
  T=$(grep -c "^\*\*Test Scenarios:\*\*" "${PHASE_DIR}/CONTEXT.md")
  if [ "$D" = "$E" ] && [ "$D" = "$U" ] && [ "$D" = "$T" ] && [ "$D" -gt 0 ]; then
    echo "  [PASS] CONTEXT semantic: ${D} decisions × 3 sub-sections all match"
    ((PASS++))
  else
    echo "  [FAIL] CONTEXT semantic: D=${D} E=${E} U=${U} T=${T} (must all match)"
    ((FAIL++))
  fi
fi

# Gate B: TEST-GOALS — Persistence check coverage cho mutation goals
if [ -f "${PHASE_DIR}/TEST-GOALS.md" ]; then
  PERSIST_GAP=$(${PYTHON_BIN:-python3} - "${PHASE_DIR}/TEST-GOALS.md" <<'PY'
import re, sys
text = open(sys.argv[1], encoding='utf-8').read()
gp = re.compile(r'(?ms)^#{2,4}\s+(?:Goal\s+)?(G-\d+).+?(?=^#{2,4}\s+(?:Goal\s+)?G-\d+|\Z)')
gap = 0
for m in gp.finditer(text):
    body = m.group(0)
    mut = re.search(r'\*\*Mutation evidence:\*\*\s*(.+?)(?=\n\s*\n|\n\*\*|\Z)', body, re.S)
    if mut:
        v = mut.group(1).strip()
        has_mut = bool(v) and not re.match(r'^(N/A|none|—|_|read-?only|—\s*$|-\s*$)\s*$', v, re.I)
        has_persist = bool(re.search(r'\*\*Persistence check:\*\*', body))
        if has_mut and not has_persist:
            gap += 1
print(gap)
PY
)
  if [ "${PERSIST_GAP:-0}" -eq 0 ]; then
    echo "  [PASS] TEST-GOALS Rule 3b: all mutation goals có Persistence check"
    ((PASS++))
  else
    echo "  [FAIL] TEST-GOALS Rule 3b: ${PERSIST_GAP} mutation goals missing Persistence check"
    ((FAIL++))
  fi

  # Gate C: Surface classification coverage
  TOTAL_G=$(grep -cE "^#{2,4}\s+(Goal\s+)?G-[0-9]+" "${PHASE_DIR}/TEST-GOALS.md")
  WITH_SURFACE=$(grep -cE "^\*\*Surface:\*\*\s+(ui|api|data|integration|time-driven|custom)" "${PHASE_DIR}/TEST-GOALS.md")
  if [ "$WITH_SURFACE" -eq "$TOTAL_G" ] && [ "$TOTAL_G" -gt 0 ]; then
    echo "  [PASS] Surface classification: ${WITH_SURFACE}/${TOTAL_G} goals classified"
    ((PASS++))
  else
    echo "  [FAIL] Surface classification: ${WITH_SURFACE}/${TOTAL_G} goals classified"
    ((FAIL++))
  fi
fi

# Gate D: PLAN ↔ TEST-GOALS bidirectional linkage
if ls "${PHASE_DIR}"/PLAN*.md >/dev/null 2>&1 && [ -f "${PHASE_DIR}/TEST-GOALS.md" ]; then
  TASKS=$(grep -cE "^#{2,3}\s+Task\s+[0-9]+" "${PHASE_DIR}"/PLAN*.md | awk -F: '{s+=$2} END{print s}')
  WITH_GOALS=$(grep -c "<goals-covered>" "${PHASE_DIR}"/PLAN*.md | awk -F: '{s+=$2} END{print s}')
  if [ "${WITH_GOALS:-0}" -ge "${TASKS:-1}" ]; then
    echo "  [PASS] Plan-Goal linkage: ${WITH_GOALS}/${TASKS} tasks có <goals-covered>"
    ((PASS++))
  else
    echo "  [WARN] Plan-Goal linkage incomplete: ${WITH_GOALS}/${TASKS}"
    ((WARN++))
  fi
fi

echo ""
echo "Result: ${PASS} pass, ${WARN} warn, ${FAIL} fail"

# Final gate — fail nếu bất kỳ semantic gate FAIL
if [ "$FAIL" -gt 0 ]; then
  echo ""
  echo "⛔ VG semantic gates failed (${FAIL} fails). Phase NOT ready for /vg:blueprint."
  echo "   Re-run: /vg:migrate ${PHASE_NUMBER} --force"
  echo "   Or fix manually: edit CONTEXT.md/TEST-GOALS.md, then re-run validation"
  if type -t emit_telemetry_v2 >/dev/null 2>&1; then
    emit_telemetry_v2 "migrate_semantic_fail" "${PHASE_NUMBER}" "migrate.9" "validation" "FAIL" \
      "{\"fails\":${FAIL},\"warns\":${WARN}}"
  fi
  if [[ ! "$ARGUMENTS" =~ --allow-semantic-gaps ]]; then
    exit 1
  fi
  if type -t log_override_debt >/dev/null 2>&1; then
    log_override_debt "migrate-semantic-gaps" "${PHASE_NUMBER}" "${FAIL} VG semantic gates failed" "$PHASE_DIR"
  fi
  echo "⚠ --allow-semantic-gaps set — proceeding, logged to debt"
fi

if type -t emit_telemetry_v2 >/dev/null 2>&1; then
  emit_telemetry_v2 "migrate_semantic_pass" "${PHASE_NUMBER}" "migrate.9" "validation" "PASS" \
    "{\"pass\":${PASS},\"warn\":${WARN}}"
fi
```

**Display migration report:**

```
━━━ Migration Complete — Phase {N} ━━━

Converted:
  CONTEXT.md:        gsd-flat → vg-enriched ({N} decisions enriched)
  PLAN.md:           gsd-plain → vg-attributed ({N}/{M} tasks attributed)
  API-CONTRACTS.md:  generated ({N} endpoints, {M} code blocks)
  TEST-GOALS.md:     generated ({N} goals: {c} critical, {i} important, {n} nice-to-have)

Backups:             .gsd-backup/ ({N} files)
Pipeline state:      migrated → ready for /vg:review

Next steps:
  1. Review generated artifacts: API-CONTRACTS.md and TEST-GOALS.md
  2. Run: /vg:review {phase}
  3. Or: /vg:next (auto-detects review as next step)
```

Final action: `(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "migrate" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/migrate.done"`
</step>

</process>

<success_criteria>
- GSD originals backed up to .gsd-backup/
- CONTEXT.md enriched with Endpoints/UI/Test sub-sections per decision
- API-CONTRACTS.md generated from existing code (if not --skip-contracts)
- TEST-GOALS.md generated with goals + infra_deps field (if not --skip-goals)
- PLAN.md tasks attributed with VG task attributes
- PIPELINE-STATE.json written with migrated status
- Validation passes with 0 FAIL items
- Phase routable by /vg:next (shows as review-ready)
</success_criteria>
