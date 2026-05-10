<step name="6_generate_goals">
## Generate TEST-GOALS.md (if missing)

**Skip if:** TEST-GOALS.md exists AND not --force. Also skip if --skip-goals.

Reuses blueprint step 2b5 logic but from enriched CONTEXT.md.

```
Agent(model="sonnet", description="Generate TEST-GOALS.md from enriched CONTEXT"):
  prompt: |
    Generate TEST-GOALS.md for phase ${PHASE_NUMBER}.
    
    Inputs:
    1. CONTEXT.md enriched decisions (Test Scenarios sub-sections)
    2. API-CONTRACTS.md (if generated in step 5)
    3. Built code (verify goals are testable against actual implementation)
    
    Rules:
    1. Every decision with Test Scenarios → at least 1 goal
    2. Every endpoint in API-CONTRACTS.md → at least 1 goal
    3. Goals describe WHAT to verify, not HOW
    4. Priority assignment:
       - Auth/payment/security → critical
       - Data mutation (POST/PUT/DELETE) → important (min)
       - Read-only (GET) → important
       - Cosmetic/display → nice-to-have
    5. Each goal MUST have: success criteria, mutation evidence, dependencies
    6. Add `infra_deps` field if goal requires services not in this phase:
       ```
       **Infra deps:** [clickhouse, kafka, pixel-server, redis]
       ```
       Goals with unmet infra_deps auto-classify as INFRA_PENDING in review Phase 4.
    
    Output format: follow TEST-GOALS.md template from blueprint step 2b5.
    Write to: ${PHASE_DIR}/TEST-GOALS.md.staged (STAGING — not final).
    
    7. **MANDATORY for mutation goals (Rule 3b — blueprint enforcement):**
       Every goal có non-empty **Mutation evidence:** PHẢI có **Persistence check:** block:
       ```
       **Persistence check:**
       - Pre-submit: read <field/row/state> value
       - Action: <what user does>
       - Post-submit wait: API 2xx + toast
       - Refresh: page.reload() OR navigate away + back
       - Re-read: <where to re-read>
       - Assert: <field> = <new value> AND != <pre value>
       ```
       Skip Persistence check chỉ khi: read-only goal (no mutation), final-step wizard, file upload.
    
    8. **Surface classification REQUIRED** — mỗi goal có dòng `**Surface:** ui|api|data|integration|time-driven|custom`
       (review/test pipeline cần để pick runner — backend phase tránh deadlock browser scan)
```

**Preservation gate (tightened 2026-04-17):**

```bash
STAGING="${PHASE_DIR}/TEST-GOALS.md.staged"
TARGET="${PHASE_DIR}/TEST-GOALS.md"

[ -f "$STAGING" ] || { echo "⛔ Agent did not write staging ${STAGING}"; exit 1; }

# If overwriting existing file (--force), preserve G-XX IDs + bodies
if [ -f "$TARGET" ]; then
  cp "$TARGET" "${PHASE_DIR}/.gsd-backup/TEST-GOALS.md.pre-migrate"
  ${PYTHON_BIN:-python3} - "$TARGET" "$STAGING" <<'PY' || exit 1
import re, sys, difflib
orig = open(sys.argv[1], encoding='utf-8').read()
new = open(sys.argv[2], encoding='utf-8').read()

def extract(text):
    """Return dict G-XX -> body (between header and next ## or end)."""
    bodies = {}
    for m in re.finditer(r'(?mi)^#+\s*Goal\s+(G-\d+)[^\n]*\n(.*?)(?=^#+\s*Goal\s+G-|\Z)', text, re.S):
        bodies[m.group(1)] = m.group(2).strip()
    # Fallback: simpler pattern "## G-XX"
    if not bodies:
        for m in re.finditer(r'(?mi)^#+\s*(G-\d+)\b[^\n]*\n(.*?)(?=^#+\s*G-|\Z)', text, re.S):
            bodies[m.group(1)] = m.group(2).strip()
    return bodies

orig_g = extract(orig)
new_g = extract(new)

missing = sorted(set(orig_g) - set(new_g), key=lambda x: int(x.split('-')[1]))
if missing:
    print(f"⛔ GOALS LOST: {len(missing)} goal(s) in existing file not in new: {missing}")
    print(f"    Existing TEST-GOALS.md preserved. Staging kept at {sys.argv[2]}")
    sys.exit(1)

# Body preservation check — each G-XX body >= 80% similar
rewrites = []
for gid, orig_body in orig_g.items():
    new_body = new_g.get(gid, "")
    if not orig_body and not new_body: continue
    ratio = difflib.SequenceMatcher(None, orig_body, new_body).ratio()
    if ratio < 0.80:
        rewrites.append((gid, ratio))
if rewrites:
    print(f"⛔ GOAL BODY REWRITTEN: {len(rewrites)} goal(s) with < 80% similarity:")
    for gid, r in rewrites: print(f"    {gid}: {r:.0%}")
    print(f"    Staging kept at {sys.argv[2]}")
    sys.exit(1)

print(f"✓ All {len(orig_g)} existing goals preserved (+{len(set(new_g)-set(orig_g))} new)")
PY
fi

# ─── Persistence check gate (Rule 3b enforcement, v1.14.4+) ───
PYTHONIOENCODING=utf-8 ${PYTHON_BIN:-python3} - "$STAGING" <<'PY' || exit 1
import re, sys
from pathlib import Path

text = Path(sys.argv[1]).read_text(encoding='utf-8')

# Parse per-goal sections — support 2-4 hash levels + optional "Goal" prefix
goal_pat = re.compile(r'(^#{2,4}\s+(?:Goal\s+)?G-\d+[^\n]*)\n(.*?)(?=^#{2,4}\s+(?:Goal\s+)?G-\d+|\Z)', re.M | re.S)

mutation_missing_persist = []
no_surface = []
mutation_count = 0
persist_count = 0

for m in goal_pat.finditer(text):
    header = m.group(1).strip()
    body = m.group(2)
    gid_m = re.search(r'G-\d+', header)
    gid = gid_m.group(0) if gid_m else '?'

    # Mutation evidence non-empty
    mut = re.search(r'\*\*Mutation evidence:\*\*\s*(.+?)(?=\n\s*\n|\n\*\*|\Z)', body, re.S)
    has_mut = False
    if mut:
        v = mut.group(1).strip()
        if v and not re.match(r'^(N/A|none|—|-|_|read-?only)\s*$', v, re.I):
            has_mut = True
            mutation_count += 1

    has_persist = bool(re.search(r'\*\*Persistence check:\*\*', body))
    if has_persist: persist_count += 1
    if has_mut and not has_persist:
        mutation_missing_persist.append(gid)

    # Surface classification
    if not re.search(r'\*\*Surface:\*\*\s*(ui|api|data|integration|time-driven|custom)', body, re.I):
        no_surface.append(gid)

errors = 0
if mutation_missing_persist:
    print(f"⛔ Rule 3b: {len(mutation_missing_persist)} mutation goals missing Persistence check:")
    for g in mutation_missing_persist[:10]:
        print(f"   - {g}")
    errors += 1

if no_surface:
    print(f"⛔ Surface classification missing: {len(no_surface)} goals")
    for g in no_surface[:10]:
        print(f"   - {g}")
    print("   Add: **Surface:** ui|api|data|integration|time-driven|custom")
    errors += 1

if errors:
    print(f"\nStaging at $STAGING — re-run agent or manual fix")
    sys.exit(1)

print(f"✓ Rule 3b: {mutation_count} mutation goals, {persist_count} với Persistence check, surface classified")
PY

mv "$STAGING" "$TARGET"
echo "✓ TEST-GOALS.md written + Rule 3b enforced"
```
</step>

<step name="6_5_link_plan_goals">
## Step 6.5 — Bidirectional PLAN ↔ TEST-GOALS linkage (v1.14.4+)

Mirror blueprint step 2b5 post-gen linkage. Without this, build executor không know which goal a task implements → breaks `<goals-covered>` citation.

```bash
PLAN_GLOB="${PHASE_DIR}/PLAN*.md"
GOALS_FILE="${PHASE_DIR}/TEST-GOALS.md"

if [ ! -f "$GOALS_FILE" ]; then
  echo "⚠ Skip linkage: TEST-GOALS.md missing (--skip-goals?)"
else
  PYTHONIOENCODING=utf-8 ${PYTHON_BIN:-python3} - "$PHASE_DIR" <<'PY'
import re, sys, glob
from pathlib import Path

phase_dir = Path(sys.argv[1])
goals_file = phase_dir / "TEST-GOALS.md"
plan_files = sorted(glob.glob(str(phase_dir / "PLAN*.md")))
if not plan_files:
    print("⚠ No PLAN*.md files — skip linkage")
    sys.exit(0)

# Extract goal endpoints + IDs from TEST-GOALS
goals_text = goals_file.read_text(encoding='utf-8')
goal_ep_map = {}
for m in re.finditer(r'(?ms)^#{2,3}\s+(?:Goal\s+)?(G-\d+)[^\n]*\n(.+?)(?=^#{2,3}\s+(?:Goal\s+)?G-\d+|\Z)', goals_text):
    gid = m.group(1)
    body = m.group(2)
    eps = set()
    for ep_m in re.finditer(r'\b(GET|POST|PUT|PATCH|DELETE)\s+(/\S+)', body):
        eps.add((ep_m.group(1), ep_m.group(2)))
    goal_ep_map[gid] = eps

# Annotate each plan task with <goals-covered>
linked_tasks = 0
orphan_tasks = 0
for plan_path in plan_files:
    p = Path(plan_path)
    text = p.read_text(encoding='utf-8')
    orig = text

    # Per-task: find endpoints mentioned, match to goals
    def annotate(task_match):
        nonlocal linked_tasks, orphan_tasks
        task_block = task_match.group(0)
        # Skip if already has <goals-covered>
        if re.search(r'<goals-covered>', task_block):
            return task_block
        task_eps = set()
        for ep_m in re.finditer(r'\b(GET|POST|PUT|PATCH|DELETE)\s+(/\S+)', task_block):
            task_eps.add((ep_m.group(1), ep_m.group(2)))
        matched = sorted({gid for gid, eps in goal_ep_map.items() if eps & task_eps})
        if matched:
            covered = f"<goals-covered>{', '.join(matched)}</goals-covered>"
            linked_tasks += 1
        else:
            covered = "<goals-covered>no-goal-impact</goals-covered>"
            orphan_tasks += 1
        # Insert after task header
        return re.sub(r'(^#{2,3}\s+Task\s+\d+[^\n]*\n)', r'\1' + covered + '\n', task_block, count=1, flags=re.M)

    text = re.sub(
        r'(?ms)^#{2,3}\s+Task\s+\d+.+?(?=^#{2,3}\s+Task\s+\d+|^#{2}\s+Wave|\Z)',
        annotate,
        text
    )
    if text != orig:
        p.write_text(text, encoding='utf-8')

print(f"✓ Linkage: {linked_tasks} tasks linked to goals, {orphan_tasks} marked no-goal-impact")
PY
fi

(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER:-unknown}" "6_5_link_plan_goals" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/6_5_link_plan_goals.done"
```
</step>

<step name="7_attribute_plans">
## Attribute PLAN.md tasks (if GSD-plain format)

**Skip if:** PLAN_FORMAT already "vg-attributed" AND not --force.

Add VG task attributes to existing GSD plan tasks WITHOUT rewriting task content.

```
Agent(model="sonnet", description="Add VG attributes to PLAN.md tasks"):
  prompt: |
    Add VG task attributes to existing PLAN.md tasks for phase ${PHASE_NUMBER}.
    
    DO NOT rewrite task descriptions. ONLY ADD attributes.
    
    For each task (## Task N or ### Task N):
    1. Add <file-path> — grep codebase for the file this task actually created/modified
       (check git log for phase commits if available)
    2. Add <contract-ref> — if task touches API endpoint, reference API-CONTRACTS.md section
    3. Add <goals-covered> — map task to G-XX from TEST-GOALS.md
    4. Add <design-ref> — if task builds UI page and design assets exist
    
    Read:
    - ${PHASE_DIR}/PLAN*.md (tasks to attribute)
    - ${PHASE_DIR}/API-CONTRACTS.md (for contract-ref mapping)
    - ${PHASE_DIR}/TEST-GOALS.md (for goals-covered mapping)
    
    Output: write to ${PHASE_DIR}/PLAN.md.staged per source file (STAGING — not final overwrite).
```

**Preservation gate (tightened 2026-04-17):**

Agent wrote to staging files (one per PLAN*.md source). Verify task preservation before promoting to target.

```bash
# Process each PLAN*.md that has a staging file
for PLAN_FILE in "${PHASE_DIR}"/PLAN*.md; do
  [ -f "$PLAN_FILE" ] || continue
  BASENAME=$(basename "$PLAN_FILE")
  STAGING="${PHASE_DIR}/${BASENAME}.staged"

  [ -f "$STAGING" ] || { echo "⚠ No staging for ${BASENAME} — agent skipped?"; continue; }

  BACKUP="${PHASE_DIR}/.gsd-backup/${BASENAME}.gsd"
  ORIG="${BACKUP:-$PLAN_FILE}"
  [ -f "$ORIG" ] || ORIG="$PLAN_FILE"

  ${PYTHON_BIN:-python3} - "$ORIG" "$STAGING" <<'PY' || exit 1
import re, sys, difflib
orig = open(sys.argv[1], encoding='utf-8').read()
stage = open(sys.argv[2], encoding='utf-8').read()

def tasks(text):
    """Return dict 'Task N' -> body (between header and next ## Task or end)."""
    bodies = {}
    # Match "## Task N" or "### Task N" — capture title + body
    for m in re.finditer(r'(?mi)^#+\s*Task\s+(\d+)([^\n]*)\n(.*?)(?=^#+\s*Task\s+\d+|\Z)', text, re.S):
        num = m.group(1)
        title = m.group(2).strip()
        body = m.group(3)
        # Strip VG attribute blocks (<file-path>, <contract-ref>, <goals-covered>, <design-ref>)
        body_clean = re.sub(r'<(?:file-path|contract-ref|goals-covered|design-ref|api-endpoint|edits-\w+)>.*?</\1>', '', body, flags=re.S)
        body_clean = re.sub(r'<(?:file-path|contract-ref|goals-covered|design-ref|api-endpoint|edits-\w+)[^/>]*/>', '', body_clean)
        bodies[num] = {'title': title, 'body': body_clean.strip()}
    return bodies

orig_t = tasks(orig)
stage_t = tasks(stage)

# Gate A: every task in original must exist in staging
missing = sorted(set(orig_t) - set(stage_t), key=int)
if missing:
    print(f"⛔ TASKS LOST: {len(missing)} task(s) in original not in staging: Task {missing}")
    print(f"    Staging kept at {sys.argv[2]}. PLAN.md NOT modified.")
    sys.exit(1)

# Gate B: title + body preservation >= 80% similar (attribute-stripped)
rewrites = []
for tnum, orig_data in orig_t.items():
    stage_data = stage_t.get(tnum, {})
    # Title comparison
    if orig_data['title'] and stage_data.get('title'):
        title_ratio = difflib.SequenceMatcher(None, orig_data['title'], stage_data['title']).ratio()
    else:
        title_ratio = 1.0
    # Body comparison (after stripping VG attrs)
    body_ratio = difflib.SequenceMatcher(None, orig_data['body'], stage_data.get('body', '')).ratio() if (orig_data['body'] or stage_data.get('body')) else 1.0
    if title_ratio < 0.85 or body_ratio < 0.80:
        rewrites.append((tnum, title_ratio, body_ratio))

if rewrites:
    print(f"⛔ TASK CONTENT REWRITTEN: {len(rewrites)} task(s) diverged beyond threshold:")
    for tnum, tr, br in rewrites:
        print(f"    Task {tnum}: title_similarity={tr:.0%} body_similarity={br:.0%}")
    print(f"    Rule violated: 'DO NOT rewrite task descriptions. ONLY ADD attributes.'")
    print(f"    Staging kept at {sys.argv[2]}. PLAN.md NOT modified.")
    sys.exit(1)

print(f"✓ {sys.argv[2]}: all {len(orig_t)} tasks preserved (titles + bodies)")
PY

  # Gates passed — promote staging to final
  mv "$STAGING" "$PLAN_FILE"
  echo "✓ Attributed: ${BASENAME}"
done
```
</step>
