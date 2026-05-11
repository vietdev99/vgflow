# shellcheck shell=bash
# Matrix Merger — bash function library (v2.65.1 lifecycle-contract hotfix)
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

phase_path = Path(phase_dir)

def _read_json_object(path):
    p = Path(path)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding='utf-8'))
    except Exception as exc:
        print(f'⚠ {p.name} read error: {exc}', file=sys.stderr)
        return {}
    return data if isinstance(data, dict) else {}

def _normalize_priority(value, default='important'):
    raw = str(value or default or 'important').strip().lower()
    mapping = {
        'p0': 'critical',
        'p1': 'critical',
        'p2': 'important',
        'p3': 'nice-to-have',
        'nice': 'nice-to-have',
        'nice_to_have': 'nice-to-have',
        'nice-to-have': 'nice-to-have',
    }
    return mapping.get(raw, raw or default)

PRIORITY_VALUES = {'critical', 'high', 'important', 'medium', 'low', 'nice-to-have'}

lifecycle = _read_json_object(phase_path / 'LIFECYCLE-SPECS.json')
lifecycle_goals = lifecycle.get('goals') if isinstance(lifecycle.get('goals'), dict) else {}
fixture_dag_artifact = _read_json_object(phase_path / 'TEST-FIXTURE-DAG.json')
execution_artifact = _read_json_object(phase_path / 'TEST-EXECUTION-PLAN.json')
execution_goals = execution_artifact.get('goals') if isinstance(execution_artifact.get('goals'), dict) else {}
deep_specs_present = (phase_path / 'DEEP-TEST-SPECS.md').exists()

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
            'priority': _normalize_priority(prio.group(1) if prio else 'important'),
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
        #   G-01 | <title> | mutation | high | refs
        surface = ''
        priority = 'important'
        for cell in rest:
            candidate = _normalize_priority(cell)
            if candidate in PRIORITY_VALUES:
                priority = candidate
                break
        for cell in rest:
            candidate = str(cell or '').strip().lower()
            if candidate in {'ui', 'ui-mobile', 'api', 'cli', 'library'}:
                surface = candidate
                break
        out.append({
            'id': gid,
            'title': gid,
            'priority': _normalize_priority(priority or 'important'),
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
            'priority': _normalize_priority(prio.group(1) if prio else 'important'),
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
table_by_id = {g.get('id'): g for g in table_goals if g.get('id')}
for g in goals:
    table_goal = table_by_id.get(g.get('id'))
    if not table_goal:
        continue
    table_priority = table_goal.get('priority')
    if table_priority in PRIORITY_VALUES:
        g['priority'] = table_priority
    table_surface = table_goal.get('surface')
    if table_surface in {'ui', 'ui-mobile', 'api', 'cli', 'library'} and (
        not g.get('surface') or g.get('surface') == 'ui'
    ):
        g['surface'] = table_surface
print(f"⓵ matrix-merger: parsed {len(goals)} goals via '{method}' "
      f"(flat={len(flat_goals)}, table={len(table_goals)}, split={len(split_goals)})",
      file=sys.stderr)

def _goal_plan(gid, spec):
    plan = {}
    artifact_plan = execution_goals.get(gid)
    if isinstance(artifact_plan, dict):
        plan.update(artifact_plan)
    spec_plan = spec.get('execution_plan') if isinstance(spec, dict) else {}
    if isinstance(spec_plan, dict):
        plan.update(spec_plan)
    return plan

def _surface_from_lifecycle(spec, fallback='ui', plan=None):
    surface = str((spec or {}).get('surface') or fallback or '').lower()
    plan = plan if isinstance(plan, dict) else _goal_plan('', spec if isinstance(spec, dict) else {})
    family = str(plan.get('family') or '').lower()
    if family == 'web':
        return 'ui-mobile' if 'mobile' in surface else 'ui'
    if family == 'mobile':
        return 'ui-mobile'
    if family == 'backend':
        return 'api'
    if family == 'cli':
        return 'cli'
    if family == 'library':
        return 'library'
    if surface in ('', 'unknown'):
        return fallback or 'ui'
    return surface

# Lifecycle-only goals are still review goals: test-spec can discover a
# side-effecting contract that legacy TEST-GOALS parsing missed. Include them
# so review verdict provenance covers the full post-build lifecycle contract.
seen_goal_ids = {g.get('id') for g in goals}
for gid, spec in lifecycle_goals.items():
    if not isinstance(spec, dict) or gid in seen_goal_ids:
        continue
    plan = _goal_plan(gid, spec)
    goals.append({
        'id': gid,
        'title': str(spec.get('title') or gid)[:80],
        'priority': _normalize_priority(spec.get('priority') or 'important'),
        'surface': _surface_from_lifecycle(spec, 'ui', plan),
        'infra_deps': [],
        'mutation_evidence': (spec.get('source_assertions') or {}).get('mutation_evidence', ''),
        'persistence_check': (spec.get('source_assertions') or {}).get('persistence_check', ''),
        'status': 'NOT_SCANNED',
        'evidence': '',
    })
    seen_goal_ids.add(gid)

for g in goals:
    gid = g['id']
    spec = lifecycle_goals.get(gid)
    if isinstance(spec, dict):
        plan = _goal_plan(gid, spec)
        if plan:
            spec = dict(spec)
            spec['execution_plan'] = plan
        g['lifecycle_contract'] = spec
        g['lifecycle_plan'] = plan
        # For non-web phase profiles, do not leave old TEST-GOALS surface
        # guesses (e.g. "login") in control. The post-build test-spec plan is
        # the profile-aware source of runner family.
        family = str(plan.get('family') or '').lower()
        if family in {'mobile', 'backend', 'cli', 'library'}:
            g['surface'] = _surface_from_lifecycle(spec, g.get('surface') or 'ui', plan)
    else:
        g['lifecycle_contract'] = None
        g['lifecycle_plan'] = {}

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

REQUIRED_LIFECYCLE_STAGES = (
    'read_before',
    'create',
    'read_after_create',
    'update',
    'read_after_update',
    'delete',
    'read_after_delete',
)

SIDE_EFFECT_GOAL_TYPES = {
    'mutation',
    'multi-actor',
    'multi_actor',
    'workflow',
    'crud',
    'rcrurd',
    'rcrurdr',
}

RUNNER_NATIVE_FAMILIES = {'backend', 'cli', 'library', 'mobile'}

def _goal_needs_lifecycle_contract(goal):
    spec = goal.get('lifecycle_contract')
    if not isinstance(spec, dict):
        return False
    goal_type = str(spec.get('goal_type') or '').strip().lower().replace(' ', '_')
    if goal_type in SIDE_EFFECT_GOAL_TYPES:
        return True
    # LIFECYCLE-SPECS.json is emitted only for side-effecting/multi-actor
    # goals by default. If it declares full RCRURDR steps, treat it as a
    # lifecycle contract even when old TEST-GOALS omitted goal_type.
    stages = [
        str(step.get('stage') or '')
        for step in spec.get('steps') or []
        if isinstance(step, dict)
    ]
    return bool(stages or spec.get('fixture_dag') or spec.get('actors'))

def _execution_family(goal):
    plan = goal.get('lifecycle_plan')
    if isinstance(plan, dict):
        return str(plan.get('family') or '').strip().lower()
    return ''

def _execution_runner(goal):
    plan = goal.get('lifecycle_plan')
    if isinstance(plan, dict):
        return str(plan.get('runner') or '').strip()
    return ''

def _declared_lifecycle_stages(goal):
    spec = goal.get('lifecycle_contract')
    if not isinstance(spec, dict):
        return []
    stages = []
    for step in spec.get('steps') or []:
        if not isinstance(step, dict):
            continue
        stage = str(step.get('stage') or '').strip()
        if stage:
            stages.append(stage)
    return stages

def _observed_lifecycle_stages(seq):
    stages = set()
    for node in _walk(seq or {}):
        if not isinstance(node, dict):
            continue
        for key in ('stage', 'lifecycle_stage', 'rcrurd_stage', 'rcrurdr_stage'):
            value = node.get(key)
            if isinstance(value, str) and value.strip():
                stages.add(value.strip())
        for key in ('stages', 'lifecycle_stages', 'covered_stages'):
            values = node.get(key)
            if isinstance(values, list):
                stages.update(str(item).strip() for item in values if str(item).strip())
    return stages

def _lifecycle_missing_runtime_stages(goal, seq):
    declared = _declared_lifecycle_stages(goal)
    if not declared:
        return []
    observed = _observed_lifecycle_stages(seq)
    if not observed:
        return declared
    return [stage for stage in declared if stage not in observed]

def _lifecycle_fixture_count(goal):
    spec = goal.get('lifecycle_contract')
    if not isinstance(spec, dict):
        return 0
    fixtures = spec.get('fixture_dag')
    return len(fixtures) if isinstance(fixtures, list) else 0

def _lifecycle_pending_evidence(goal, prefix='lifecycle contract pending'):
    stages = _declared_lifecycle_stages(goal)
    runner = _execution_runner(goal) or 'profile runner'
    family = _execution_family(goal) or 'profile'
    fixture_count = _lifecycle_fixture_count(goal)
    stage_hint = ', '.join(stages[:3])
    if len(stages) > 3:
        stage_hint += ', ...'
    if not stage_hint:
        stage_hint = 'RCRURDR stages'
    return (
        f"{prefix}: runner={runner} family={family}; "
        f"{len(stages)} stages ({stage_hint}), {fixture_count} fixtures need /vg:test proof"
    )

def _runtime_test_pending_evidence(goal, seq):
    pending = seq.get('pending_evidence') if isinstance(seq, dict) else None
    if isinstance(pending, list) and pending:
        pending_hint = ', '.join(str(item) for item in pending[:4])
    elif isinstance(pending, str) and pending.strip():
        pending_hint = pending.strip()
    else:
        pending_hint = 'lifecycle/test evidence'
    if _goal_needs_lifecycle_contract(goal):
        return _lifecycle_pending_evidence(
            goal,
            f'runtime clean; pending evidence={pending_hint}',
        )
    note = ''
    review_evidence = seq.get('review_evidence') if isinstance(seq, dict) else None
    if isinstance(review_evidence, dict):
        note = str(review_evidence.get('note') or '').strip()
    return (f'runtime clean; pending evidence={pending_hint}; {note}').strip('; ')[:300]

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
    seq = rm_seqs.get(gid)
    if seq:
        result = str(seq.get('result', 'unknown')).strip().lower().replace('-', '_')
        if result in ('test_pending', 'pending', 'coverage_pending'):
            g['status'] = 'TEST_PENDING'
            g['evidence'] = _runtime_test_pending_evidence(g, seq)
            continue
        if result in ('failed', 'blocked', 'error') and g['surface'] not in ('ui', 'ui-mobile'):
            reason = str(seq.get('failure_reason') or seq.get('error') or result)
            g['status'] = 'TEST_PENDING' if _is_test_pending_evidence(reason) else 'BLOCKED'
            g['evidence'] = f"runtime {result}: {reason[:80]}"
            continue

    # UI goals: consult RUNTIME-MAP first
    if g['surface'] in ('ui', 'ui-mobile'):
        if seq:
            result = str(seq.get('result', 'unknown')).strip().lower().replace('-', '_')
            if result in ('passed', 'pass', 'ready', 'ok'):
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
            if _goal_needs_lifecycle_contract(g) and _execution_family(g) in RUNNER_NATIVE_FAMILIES:
                g['status'] = 'TEST_PENDING'
                g['evidence'] = _lifecycle_pending_evidence(
                    g,
                    'runner-native lifecycle proof pending',
                )
            else:
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
        if g['status'] == 'READY' and _goal_needs_lifecycle_contract(g):
            missing_stages = _lifecycle_missing_runtime_stages(g, seq)
            if missing_stages:
                g['status'] = 'TEST_PENDING'
                g['evidence'] = (
                    _lifecycle_pending_evidence(g)
                    + f"; runtime missing stages: {', '.join(missing_stages[:4])}"
                )[:300]
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
        if g['status'] == 'READY' and _goal_needs_lifecycle_contract(g):
            g['status'] = 'TEST_PENDING'
            g['evidence'] = _lifecycle_pending_evidence(
                g,
                'surface probe ready; lifecycle proof pending',
            )
    else:
        # No probe run for this goal. For runner-native lifecycle contracts,
        # review records runtime-clean/test-pending instead of forcing browser
        # semantics onto CLI/mobile/backend/library phases.
        if _goal_needs_lifecycle_contract(g) and _execution_family(g) in RUNNER_NATIVE_FAMILIES:
            g['status'] = 'TEST_PENDING'
            g['evidence'] = _lifecycle_pending_evidence(
                g,
                'runner-native lifecycle proof pending',
            )
        else:
            g['status'] = 'NOT_SCANNED'
            g['evidence'] = 'no probe result; surface probe phase may not have run'

# ─── Aggregate counts ────────────────────────────────────────────
total_by_status = {'READY': 0, 'BLOCKED': 0, 'TEST_PENDING': 0, 'NOT_SCANNED': 0, 'UNREACHABLE': 0, 'INFRA_PENDING': 0, 'FAILED': 0}
by_priority = {
    'critical':     {'total': 0, 'ready': 0, 'blocked': 0, 'other': 0, 'threshold': 100},
    'high':         {'total': 0, 'ready': 0, 'blocked': 0, 'other': 0, 'threshold': 80},
    'important':    {'total': 0, 'ready': 0, 'blocked': 0, 'other': 0, 'threshold': 80},
    'medium':       {'total': 0, 'ready': 0, 'blocked': 0, 'other': 0, 'threshold': 50},
    'low':          {'total': 0, 'ready': 0, 'blocked': 0, 'other': 0, 'threshold': 50},
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
    f'**Source:** RUNTIME-MAP.json (UI goals) + .surface-probe-results.json (backend goals) + LIFECYCLE-SPECS.json/TEST-FIXTURE-DAG.json/TEST-EXECUTION-PLAN.json (post-build lifecycle contract)  ',
    f'**Merger:** _shared/lib/matrix-merger.sh v2.65.1',
    f'**Lifecycle contracts consumed:** {len(lifecycle_goals)} goal(s); fixture nodes={len(fixture_dag_artifact.get("nodes") or []) if isinstance(fixture_dag_artifact.get("nodes"), list) else 0}; deep_specs_present={str(deep_specs_present).lower()}  ',
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
for prio in ('critical', 'high', 'important', 'medium', 'low', 'nice-to-have'):
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
            'Proceed to /vg:test; generated tests must consume LIFECYCLE-SPECS.json, TEST-FIXTURE-DAG.json, and TEST-EXECUTION-PLAN.json.',
            'Do not loop back to /vg:review unless test finds a concrete runtime/code blocker.',
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
print(f"LIFECYCLE_CONTRACTS={len(lifecycle_goals)}")
PY
}
