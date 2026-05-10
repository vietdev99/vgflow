# shellcheck shell=bash
# Matrix Merger — bash function library (v2.64.1 hotfix)
#
# v2.64.1 (Issue #148 HIGH — review FALSE-PASS):
#   Added 3-layer split format support. Pre-fix: parser only understood
#   legacy `## Goal G-XX:` heading blocks in flat TEST-GOALS.md, returning
#   TOTAL=0 when phases used the new index-table or per-goal split files,
#   which produced silent FALSE-PASS in the review gate.
#   Post-fix: 3-tier fallback — flat headings → index-table rows → split
#   files — taking max non-zero count.
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
#       → stdout: "PASS|BLOCK|INTERMEDIATE|TEST_PENDING" + counts in $MERGE_*
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
#     TEST_PENDING) echo "🧪 Gate: runtime clear, test coverage pending" ;;
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

# ─── Load TEST-GOALS (v2.64.1 — 3-layer split format support) ─────
# Issue #148 HIGH: pre-fix only flat-heading parser ran. New phases use
# 3-layer pattern → flat had no headings → TOTAL=0 → silent FALSE-PASS.
# Strategy: try each parse method, take whichever finds the most goals
# (and log which method won via stderr for diagnostics).
tg_text = Path(test_goals_path).read_text(encoding='utf-8', errors='ignore')

def _parse_flat_blocks(text):
    """Layer 3 / legacy: `## Goal G-XX:` heading blocks with full metadata."""
    out = []
    goal_heading = r'^## (?:Goal )?(G-[\w]+): *(.+?)$'
    next_goal_heading = r'^## (?:Goal )?G-[\w]+:'
    for blk_m in re.finditer(
        goal_heading + r'(?P<body>(?:(?!' + next_goal_heading + r').)*)',
        text, re.M | re.S
    ):
        gid, title, body = blk_m.group(1), blk_m.group(2).strip(), blk_m.group('body') or ''
        def _field(name, blk=body):
            mm = re.search(rf'^\*\*{re.escape(name)}:\*\*\s*(.+?)(?:\n\*\*|\n##|\Z)', blk, re.M | re.S)
            return (mm.group(1).strip() if mm else '')
        prio = re.search(r'^\*\*Priority:\*\*\s*(\w[\w-]*)', body, re.M)
        surface = re.search(r'^\*\*Surface:\*\*\s*(\w[\w-]*)', body, re.M)
        infra = re.search(r'^\*\*Infra deps:\*\*\s*\[([^\]]+)\]', body, re.M)
        out.append({
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
    return out


def _parse_index_table(text):
    """Layer 2: `| G-NN | <surface> | <priority> | <file> |` table rows."""
    out = []
    # Match: `| G-01 | <surface> | <priority> | <file> |` — at least the G-NN id col + 1 more col.
    row_re = re.compile(r'^\|\s*(G-[\w]+)\s*\|([^\n]*)\|\s*$', re.M)
    for m in row_re.finditer(text):
        gid = m.group(1)
        rest = [c.strip() for c in m.group(2).split('|')]
        # Common formats:
        #   G-01 | login | P0 | G-01.md
        #   G-01 | login | critical | G-01.md
        #   G-01 | <title> | ui | important
        surface = ''
        priority = ''
        if len(rest) >= 2:
            surface = rest[0].lower()
            prio_raw = rest[1].lower()
            # Normalize P0/P1/P2/P3 to severity words.
            prio_map = {'p0': 'critical', 'p1': 'critical', 'p2': 'important', 'p3': 'nice-to-have'}
            priority = prio_map.get(prio_raw, prio_raw)
        out.append({
            'id': gid,
            'title': gid,
            'priority': priority or 'important',
            'surface': surface or 'ui',
            'infra_deps': [],
            'mutation_evidence': '',
            'persistence_check': '',
            'status': 'NOT_SCANNED',
            'evidence': '',
        })
    return out


def _parse_split_files(phase_dir_path):
    """Layer 1: walk TEST-GOALS/G-*.md per-goal files."""
    out = []
    tg_dir = Path(phase_dir_path) / 'TEST-GOALS'
    if not tg_dir.is_dir():
        return out
    for fp in sorted(tg_dir.glob('G-*.md')):
        try:
            txt = fp.read_text(encoding='utf-8', errors='ignore')
        except OSError:
            continue
        # First H1: `# G-NN: <title>` or `# G-NN <title>`
        head = re.search(r'^#\s+(G-[\w]+)[:\s]', txt, re.M)
        gid = head.group(1) if head else fp.stem
        prio = re.search(r'^\*\*Priority:\*\*\s*(\w[\w-]*)', txt, re.M)
        surface = re.search(r'^\*\*Surface:\*\*\s*(\w[\w-]*)', txt, re.M)
        out.append({
            'id': gid,
            'title': gid,
            'priority': (prio.group(1).lower() if prio else 'important'),
            'surface': (surface.group(1).lower() if surface else 'ui'),
            'infra_deps': [],
            'mutation_evidence': '',
            'persistence_check': '',
            'status': 'NOT_SCANNED',
            'evidence': '',
        })
    return out


# Run all 3 parsers, take whichever finds the most goals.
flat_goals = _parse_flat_blocks(tg_text)
# Index-table parse: prefer TEST-GOALS/index.md, else flat file (which may
# itself contain a table when the flat file is just a TOC).
index_text = ''
index_path = Path(phase_dir) / 'TEST-GOALS' / 'index.md'
if index_path.is_file():
    index_text = index_path.read_text(encoding='utf-8', errors='ignore')
table_goals = _parse_index_table(index_text or tg_text)
split_goals = _parse_split_files(phase_dir)

# Pick winner: max count, but de-dup by id if multiple sources tie.
candidates = [
    ('flat-blocks', flat_goals),
    ('index-table', table_goals),
    ('split-files', split_goals),
]
candidates.sort(key=lambda kv: len(kv[1]), reverse=True)
method, goals = candidates[0]
if not goals:
    goals = []
print(f"⓵ matrix-merger: parsed {len(goals)} goals via '{method}' "
      f"(flat={len(flat_goals)}, table={len(table_goals)}, split={len(split_goals)})",
      file=sys.stderr)

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

TEST_PENDING_PATTERNS = (
    'not exercised',
    'not observed',
    'not proven',
    'not prove',
    'did not prove',
    'proof missing',
    'lifecycle',
    'multi-step',
    'mutation evidence',
    'realtime evidence',
    'without a successful post/put/patch/delete',
    'no persistence_probe',
    'persistence proof',
    'needs dedicated browser session',
    'acceptance-grade proof',
)

RUNTIME_BLOCKER_PATTERNS = (
    'api error',
    ' 400',
    ' 401',
    ' 403',
    ' 404',
    ' 409',
    ' 422',
    ' 500',
    ' 502',
    ' 503',
    'exception',
    'crash',
    'cannot render',
    'failed to render',
    'route missing',
    'not found',
    'redirected to login',
    'auth failed',
    'nan',
    'raw i18n',
    'placeholder',
)

def _is_test_pending_evidence(text):
    compact = re.sub(r'\s+', ' ', str(text or '').strip()).lower()
    if not compact:
        return False
    if any(pattern in compact for pattern in RUNTIME_BLOCKER_PATTERNS):
        return False
    return any(pattern in compact for pattern in TEST_PENDING_PATTERNS)

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
                reason = str(seq.get('failure_reason', '?'))
                g['status'] = 'TEST_PENDING' if _is_test_pending_evidence(reason) else 'BLOCKED'
                g['evidence'] = f"browser failed: {reason[:80]}"
            elif result == 'partial':
                reason = str(seq.get('failure_reason', '?'))
                g['status'] = 'TEST_PENDING' if _is_test_pending_evidence(reason) else 'BLOCKED'
                g['evidence'] = f"browser partial: {reason[:80]}"
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
                g['status'] = 'TEST_PENDING'
                g['evidence'] = (
                    "shallow CRUD evidence: goal_sequence passed without a successful "
                    "POST/PUT/PATCH/DELETE observation; list-only review cannot satisfy "
                    "Mutation evidence"
                )
            elif not _has_persistence_proof(seq):
                g['status'] = 'TEST_PENDING'
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
total_by_status = {'READY': 0, 'BLOCKED': 0, 'TEST_PENDING': 0, 'NOT_SCANNED': 0, 'UNREACHABLE': 0, 'INFRA_PENDING': 0, 'FAILED': 0}
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
# 1 coverage-pending status: TEST_PENDING → may advance to /vg:test
# 2 intermediate: NOT_SCANNED, FAILED → force INTERMEDIATE verdict
intermediate = total_by_status['NOT_SCANNED'] + total_by_status['FAILED']

verdict = 'PASS'
if not goals:
    verdict = 'BLOCK'
elif intermediate > 0:
    verdict = 'INTERMEDIATE'
elif total_by_status['BLOCKED'] > 0 or total_by_status['UNREACHABLE'] > 0:
    # Issue #139: hard block when any conclusive BLOCKED/UNREACHABLE remains.
    # Spec (vg-review SKILL.md 100% gate) requires BLOCK regardless of weighted
    # priority threshold — pre-fix: weighted gate masked BLOCKED < threshold pct
    # and emitted PASS. Now blocks first.
    verdict = 'BLOCK'
elif total_by_status['TEST_PENDING'] > 0:
    verdict = 'TEST_PENDING'
else:
    # Compute weighted gate (only if 0 BLOCKED + 0 UNREACHABLE)
    for prio, info in by_priority.items():
        if info['total'] == 0: continue
        pct = 100 * info['ready'] / info['total']
        if pct < info['threshold']:
            verdict = 'TEST_PENDING' if info['other'] > 0 and total_by_status['TEST_PENDING'] > 0 else 'BLOCK'
            info['failed_gate'] = True

# ─── Write GOAL-COVERAGE-MATRIX.md ───────────────────────────────
lines = [
    f'# Goal Coverage Matrix — Phase {phase_num}',
    '',
    f'**Generated:** {datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}  ',
    f'**Source:** RUNTIME-MAP.json (UI goals) + .surface-probe-results.json (backend goals)  ',
    f'**Merger:** _shared/lib/matrix-merger.sh v2.64.1',
    '',
    '## Summary',
    '',
    f'- **Total goals:** {len(goals)}',
    f'- **READY:** {total_by_status["READY"]}',
    f'- **BLOCKED:** {total_by_status["BLOCKED"]}',
    f'- **TEST_PENDING:** {total_by_status["TEST_PENDING"]} (test coverage pending)',
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
    if pct >= info['threshold']:
        status_icon = '✅ PASS'
    elif info['blocked'] == 0 and total_by_status['TEST_PENDING'] > 0:
        status_icon = '🧪 TEST_PENDING'
    else:
        status_icon = '⛔ BLOCK'
    lines.append(f'| {prio} | {info["ready"]} | {info["blocked"]} | {info["other"]} | {info["total"]} | {info["threshold"]}% | {pct:.1f}% | {status_icon} |')

lines += ['', '## Goal Details', '', '| Goal | Priority | Surface | Status | Evidence |', '|------|----------|---------|--------|----------|']
for g in goals:
    ev = g['evidence'].replace('|', r'\|')[:100]
    lines.append(f'| {g["id"]} | {g["priority"]} | {g["surface"]} | {g["status"]} | {ev} |')

# Gate verdict section
gate_icon = {'PASS': '✅', 'BLOCK': '⛔', 'INTERMEDIATE': '⚠️', 'TEST_PENDING': '🧪'}[verdict]
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
    if not goals:
        lines += [
            'No goals parsed from TEST-GOALS.md. Coverage gate cannot pass with total=0.',
            'Fix goal headings or parser support, then rerun Phase 4.',
        ]
    else:
        failed = [p for p, i in by_priority.items() if i.get('failed_gate')]
        lines += [
            f'Gate threshold not met for: {", ".join(failed)}',
            'Fix blockers or escalate to /vg:accept with debt entry.',
        ]
else:
    if verdict == 'TEST_PENDING':
        lines += [
            f'Review runtime blockers clear. {total_by_status["TEST_PENDING"]} goals still need lifecycle/test evidence.',
            'Proceed to /vg:test; do not loop back to /vg:review unless test finds a concrete runtime/code blocker.',
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
print(f"TEST_PENDING={total_by_status['TEST_PENDING']}")
print(f"NOT_SCANNED={total_by_status['NOT_SCANNED']}")
print(f"UNREACHABLE={total_by_status['UNREACHABLE']}")
print(f"INFRA_PENDING={total_by_status['INFRA_PENDING']}")
print(f"FAILED={total_by_status['FAILED']}")
print(f"INTERMEDIATE={intermediate}")
PY
}
