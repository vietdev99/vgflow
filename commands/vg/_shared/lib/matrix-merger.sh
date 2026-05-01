# shellcheck shell=bash
# Matrix Merger — bash function library (v1.9.2.4)
#
# Problem this solves:
#   v1.9.2.3 added surface probe execution in Phase 4a (writes
#   .surface-probe-results.json with per-goal status). But Phase 4b/4d
#   "integration" was documented as prose only — no runnable bash to:
#     1. Merge RUNTIME-MAP.goal_sequences (UI goals scanned via browser) +
#        .surface-probe-results.json (backend goals probed) into unified
#        per-goal status.
#     2. Compute weighted gate (critical=100%, important=80%, nice-to-have=50%).
#     3. Write GOAL-COVERAGE-MATRIX.md with summary + priority breakdown +
#        goal details table + gate verdict.
#
# Result: even after v1.9.2.3 probes ran, backend goals fell back to
# NOT_SCANNED because Phase 4b read RUNTIME-MAP only, ignoring probe results.
#
# Design:
#   - Pure function: merge_goal_status → build final status per goal from
#     all sources, respecting precedence (browser > probe > code_exists > UNREACHABLE).
#   - Write MATRIX: canonical GOAL-COVERAGE-MATRIX.md in standard format.
#   - Return gate verdict so caller can decide PASS/BLOCK.
#
# Exposed functions:
#   - merge_and_write_matrix PHASE_DIR TEST_GOALS RUNTIME_MAP PROBE_RESULTS OUTPUT_MD
#       → stdout: "PASS|BLOCK|INTERMEDIATE" + counts in $MERGE_*
#       → writes OUTPUT_MD
#
# Usage in review.md Phase 4b + 4d:
#   source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/matrix-merger.sh"
#   VERDICT=$(merge_and_write_matrix "$PHASE_DIR" \
#     "$PHASE_DIR/TEST-GOALS.md" \
#     "$PHASE_DIR/RUNTIME-MAP.json" \
#     "$PHASE_DIR/.surface-probe-results.json" \
#     "$PHASE_DIR/GOAL-COVERAGE-MATRIX.md")
#   case "$VERDICT" in
#     PASS) echo "✓ Gate PASS" ;;
#     BLOCK) echo "⛔ Gate BLOCK" ;;
#     INTERMEDIATE) echo "⚠ Gate: intermediate goals present" ;;
#   esac

merge_and_write_matrix() {
  local phase_dir="$1"
  local test_goals="$2"
  local runtime_map="$3"
  local probe_results="$4"
  local output_md="$5"

  # Fallback to phase_dir-relative paths
  [ -z "$test_goals" ]      && test_goals="${phase_dir}/TEST-GOALS.md"
  [ -z "$runtime_map" ]     && runtime_map="${phase_dir}/RUNTIME-MAP.json"
  [ -z "$probe_results" ]   && probe_results="${phase_dir}/.surface-probe-results.json"
  [ -z "$output_md" ]       && output_md="${phase_dir}/GOAL-COVERAGE-MATRIX.md"

  if [ ! -f "$test_goals" ]; then
    echo "merge_and_write_matrix: TEST-GOALS missing at $test_goals" >&2
    return 1
  fi

  # Infer phase number from phase_dir basename (e.g. "07.12-conversion-tracking-pixel/" → "07.12")
  local phase_num
  phase_num=$(basename "$phase_dir" | sed -E 's/^([0-9.]+).*/\1/')

  ${PYTHON_BIN:-python3} - "$phase_dir" "$test_goals" "$runtime_map" "$probe_results" "$output_md" "$phase_num" <<'PY'
import json, os, re, sys
from datetime import datetime, timezone
from pathlib import Path

phase_dir, test_goals_path, runtime_map_path, probe_path, out_path, phase_num = sys.argv[1:7]

# ─── Load TEST-GOALS ──────────────────────────────────────────────
tg_text = Path(test_goals_path).read_text(encoding='utf-8', errors='ignore')
goals = []
# Split by goal blocks first — lets us capture multi-field metadata per goal
# (Mutation evidence + Persistence check are paragraph-level fields that the
# single-line regex above cannot match reliably).
for blk_m in re.finditer(
    r'^## Goal (G-[\w]+): *(.+?)$'
    r'(?P<body>(?:(?!^## Goal ).)*)',
    tg_text, re.M | re.S
):
    gid, title, body = blk_m.group(1), blk_m.group(2).strip(), blk_m.group('body') or ''
    def _field(name, blk=body):
        mm = re.search(rf'^\*\*{re.escape(name)}:\*\*\s*(.+?)(?:\n\*\*|\n##|\Z)', blk, re.M | re.S)
        return (mm.group(1).strip() if mm else '')
    prio = re.search(r'^\*\*Priority:\*\*\s*(\w[\w-]*)', body, re.M)
    surface = re.search(r'^\*\*Surface:\*\*\s*(\w[\w-]*)', body, re.M)
    infra = re.search(r'^\*\*Infra deps:\*\*\s*\[([^\]]+)\]', body, re.M)
    goals.append({
        'id': gid,
        'title': title[:80],
        'priority': (prio.group(1) if prio else 'important').lower(),
        'surface': (surface.group(1) if surface else 'ui').lower(),
        'infra_deps': [x.strip() for x in (infra.group(1) if infra else '').split(',') if x.strip()],
        'mutation_evidence': _field('Mutation evidence'),
        'persistence_check': _field('Persistence check'),
        'status': 'NOT_SCANNED',
        'evidence': '',
    })

# ─── Load RUNTIME-MAP (browser scan results) ──────────────────────
rm_seqs = {}
if Path(runtime_map_path).exists():
    try:
        rm = json.loads(Path(runtime_map_path).read_text(encoding='utf-8'))
        rm_seqs = rm.get('goal_sequences', {}) or {}
    except Exception as e:
        print(f'⚠ RUNTIME-MAP read error: {e}', file=sys.stderr)

MUTATION_METHODS = {'POST', 'PUT', 'PATCH', 'DELETE'}
EMPTY_FIELD_VALUES = {'', 'none', 'n/a', 'na', 'null', '-', '[]', '{}'}

def _meaningful(value):
    compact = re.sub(r'\s+', ' ', str(value or '').strip()).lower()
    return compact not in EMPTY_FIELD_VALUES and not compact.startswith(('none:', 'n/a:', 'na:'))

def _walk(value):
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)

def _network_entries(seq):
    entries = []
    for node in _walk(seq or {}):
        if not isinstance(node, dict):
            continue
        network = node.get('network')
        if isinstance(network, list):
            entries.extend(x for x in network if isinstance(x, dict))
        elif isinstance(network, dict):
            entries.append(network)
    return entries

def _status_ok(value):
    try:
        code = int(value)
    except (TypeError, ValueError):
        return False
    return 200 <= code < 400

def _has_mutation_step(seq):
    for entry in _network_entries(seq):
        method = str(entry.get('method') or entry.get('verb') or '').upper()
        if method in MUTATION_METHODS and _status_ok(entry.get('status', entry.get('status_code'))):
            return True
    return False

def _has_persistence_proof(seq):
    for node in _walk(seq or {}):
        if not isinstance(node, dict):
            continue
        probe = node.get('persistence_probe')
        if isinstance(probe, dict):
            if probe.get('persisted') is True:
                return True
            if probe.get('skipped') and str(probe.get('reason') or probe.get('skipped')).strip():
                return True
        if node.get('persisted') is True and (
            'persistence' in str(node.get('type', '')).lower()
            or 'reload' in json.dumps(node, ensure_ascii=False).lower()
        ):
            return True
    return False

# ─── Load surface probe results ───────────────────────────────────
probe_results = {}
if Path(probe_path).exists():
    try:
        pr = json.loads(Path(probe_path).read_text(encoding='utf-8'))
        probe_results = pr.get('results', {}) or {}
    except Exception as e:
        print(f'⚠ probe results read error: {e}', file=sys.stderr)

# ─── Merge logic: compute status per goal ─────────────────────────
for g in goals:
    gid = g['id']

    # UI goals: consult RUNTIME-MAP first
    if g['surface'] in ('ui', 'ui-mobile'):
        seq = rm_seqs.get(gid)
        if seq:
            result = seq.get('result', 'unknown')
            if result == 'passed':
                g['status'] = 'READY'
                g['evidence'] = f"browser: {len(seq.get('steps',[]))} steps"
            elif result == 'failed':
                g['status'] = 'BLOCKED'
                g['evidence'] = f"browser failed: {seq.get('failure_reason','?')[:80]}"
            else:
                g['status'] = 'FAILED'
                g['evidence'] = f"browser result unknown"
        else:
            # No browser seq — remains NOT_SCANNED (browser phase pending or skipped)
            g['status'] = 'NOT_SCANNED'
            g['evidence'] = 'browser phase did not record goal_sequence'

        # Layer 4 gate: mutation goals require real runtime mutation evidence.
        # If goal has **Mutation evidence:** non-empty AND status was READY
        # via browser seq, verify that the sequence observed a successful
        # POST/PUT/PATCH/DELETE and that persistence was checked. A list-page
        # assertion or "row visible" snapshot is not CRUD evidence.
        if g['status'] == 'READY' and _meaningful(g.get('mutation_evidence')):
            if not _has_mutation_step(seq):
                g['status'] = 'BLOCKED'
                g['evidence'] = (
                    "shallow CRUD evidence: goal_sequence passed without a successful "
                    "POST/PUT/PATCH/DELETE observation; list-only review cannot satisfy "
                    "Mutation evidence"
                )
            elif not _has_persistence_proof(seq):
                g['status'] = 'BLOCKED'
                g['evidence'] = (
                    "ghost-save risk: mutation observed but no persistence_probe.persisted=true; "
                    "Layer 4 verify (refresh + re-read + diff) missing"
                )
        continue

    # Backend goals: consult probe results
    probe = probe_results.get(gid)
    if probe:
        g['status'] = probe.get('status', 'NOT_SCANNED')
        g['evidence'] = probe.get('evidence', '')
        # SKIPPED from probe → treat as NOT_SCANNED (criteria unparseable)
        if g['status'] == 'SKIPPED':
            g['status'] = 'NOT_SCANNED'
            g['evidence'] = f"probe skipped: {probe.get('evidence','?')}"
    else:
        # No probe run for this goal — NOT_SCANNED
        g['status'] = 'NOT_SCANNED'
        g['evidence'] = 'no probe result; surface probe phase may not have run'

# ─── Aggregate counts ────────────────────────────────────────────
total_by_status = {'READY': 0, 'BLOCKED': 0, 'NOT_SCANNED': 0, 'UNREACHABLE': 0, 'INFRA_PENDING': 0, 'FAILED': 0}
by_priority = {
    'critical':     {'total': 0, 'ready': 0, 'blocked': 0, 'other': 0, 'threshold': 100},
    'important':    {'total': 0, 'ready': 0, 'blocked': 0, 'other': 0, 'threshold': 80},
    'nice-to-have': {'total': 0, 'ready': 0, 'blocked': 0, 'other': 0, 'threshold': 50},
}
for g in goals:
    status = g['status'] if g['status'] in total_by_status else 'NOT_SCANNED'
    total_by_status[status] += 1
    prio = g['priority'] if g['priority'] in by_priority else 'important'
    by_priority[prio]['total'] += 1
    if status == 'READY':
        by_priority[prio]['ready'] += 1
    elif status == 'BLOCKED':
        by_priority[prio]['blocked'] += 1
    else:
        by_priority[prio]['other'] += 1

# ─── Gate verdict ────────────────────────────────────────────────
# 4 conclusion statuses: READY, BLOCKED, UNREACHABLE, INFRA_PENDING
# 2 intermediate: NOT_SCANNED, FAILED → force INTERMEDIATE verdict
intermediate = total_by_status['NOT_SCANNED'] + total_by_status['FAILED']

verdict = 'PASS'
if intermediate > 0:
    verdict = 'INTERMEDIATE'
else:
    # Compute weighted gate
    for prio, info in by_priority.items():
        if info['total'] == 0: continue
        pct = 100 * info['ready'] / info['total']
        if pct < info['threshold']:
            verdict = 'BLOCK'
            info['failed_gate'] = True

# ─── Write GOAL-COVERAGE-MATRIX.md ───────────────────────────────
lines = [
    f'# Goal Coverage Matrix — Phase {phase_num}',
    '',
    f'**Generated:** {datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}  ',
    f'**Source:** RUNTIME-MAP.json (UI goals) + .surface-probe-results.json (backend goals)  ',
    f'**Merger:** _shared/lib/matrix-merger.sh v1.9.2.4',
    '',
    '## Summary',
    '',
    f'- **Total goals:** {len(goals)}',
    f'- **READY:** {total_by_status["READY"]}',
    f'- **BLOCKED:** {total_by_status["BLOCKED"]}',
    f'- **NOT_SCANNED:** {total_by_status["NOT_SCANNED"]} (intermediate)',
    f'- **UNREACHABLE:** {total_by_status["UNREACHABLE"]}',
    f'- **INFRA_PENDING:** {total_by_status["INFRA_PENDING"]}',
    f'- **FAILED:** {total_by_status["FAILED"]} (intermediate)',
    '',
    '## By Priority',
    '',
    '| Priority | Ready | Blocked | Other | Total | Threshold | Pass % | Status |',
    '|----------|-------|---------|-------|-------|-----------|--------|--------|',
]
for prio in ('critical', 'important', 'nice-to-have'):
    info = by_priority[prio]
    if info['total'] == 0:
        lines.append(f'| {prio} | 0 | 0 | 0 | 0 | {info["threshold"]}% | n/a | — |')
        continue
    pct = 100 * info['ready'] / info['total']
    status_icon = '✅ PASS' if pct >= info['threshold'] else '⛔ BLOCK'
    lines.append(f'| {prio} | {info["ready"]} | {info["blocked"]} | {info["other"]} | {info["total"]} | {info["threshold"]}% | {pct:.1f}% | {status_icon} |')

lines += ['', '## Goal Details', '', '| Goal | Priority | Surface | Status | Evidence |', '|------|----------|---------|--------|----------|']
for g in goals:
    ev = g['evidence'].replace('|', r'\|')[:100]
    lines.append(f'| {g["id"]} | {g["priority"]} | {g["surface"]} | {g["status"]} | {ev} |')

# Gate verdict section
gate_icon = {'PASS': '✅', 'BLOCK': '⛔', 'INTERMEDIATE': '⚠️'}[verdict]
lines += ['', f'## Gate: {gate_icon} **{verdict}**', '']
if verdict == 'INTERMEDIATE':
    lines += [
        f'{intermediate} intermediate goals (NOT_SCANNED + FAILED) prevent conclusion.',
        'Resolve via:',
        '- UI NOT_SCANNED → run browser phase (`/vg:review` without `--skip-discovery`)',
        '- Backend NOT_SCANNED (probe SKIPPED) → improve TEST-GOALS criteria for parseability',
        '- Backend BLOCKED → verify handler/migration exists, update probe patterns if false-neg',
        '- Override (log debt): `/vg:review {phase} --allow-intermediate`',
    ]
elif verdict == 'BLOCK':
    failed = [p for p, i in by_priority.items() if i.get('failed_gate')]
    lines += [
        f'Gate threshold not met for: {", ".join(failed)}',
        'Fix blockers or escalate to /vg:accept with debt entry.',
    ]
else:
    lines += [f'All priority thresholds met. {total_by_status["READY"]}/{len(goals)} READY — proceed to /vg:test.']

lines.append('')
Path(out_path).write_text('\n'.join(lines) + '\n', encoding='utf-8')

# ─── Export counters for caller via env ──────────────────────────
# Print machine-readable summary on stdout
print(f"VERDICT={verdict}")
print(f"TOTAL={len(goals)}")
print(f"READY={total_by_status['READY']}")
print(f"BLOCKED={total_by_status['BLOCKED']}")
print(f"NOT_SCANNED={total_by_status['NOT_SCANNED']}")
print(f"UNREACHABLE={total_by_status['UNREACHABLE']}")
print(f"INFRA_PENDING={total_by_status['INFRA_PENDING']}")
print(f"FAILED={total_by_status['FAILED']}")
print(f"INTERMEDIATE={intermediate}")
PY
}
