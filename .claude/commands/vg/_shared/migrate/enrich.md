<step name="4_enrich_context">
## Convert CONTEXT.md: GSD flat → VG enriched

**Skip if:** CONTEXT_FORMAT already "vg-enriched" AND not --force.

**GSD flat format** (decisions only):
```
## D-01: Use MongoDB for storage
MongoDB chosen for flexibility...

## D-02: REST API with Fastify
Standard REST endpoints...
```

**VG enriched format** (decisions + structured sub-sections):
```
## D-01: Use MongoDB for storage
MongoDB chosen for flexibility...

**Endpoints:** none (infrastructure decision)
**UI Components:** none
**Test Scenarios:**
- Database connection established on startup
- Collections created with correct indexes
```

**Conversion process — spawn agent (model=sonnet for quality):**

```
Agent(model="sonnet", description="Enrich CONTEXT.md for phase ${PHASE_NUMBER}"):
  prompt: |
    Convert this GSD-format CONTEXT.md to VG enriched format.
    
    RULES:
    1. Keep ALL existing decision text EXACTLY as-is (do not rewrite prose)
    2. ADD 3 sub-sections after each decision: Endpoints, UI Components, Test Scenarios
    3. Derive sub-sections from decision text + code scan:
       - Endpoints: grep code for routes/handlers matching this decision's domain
       - UI Components: grep code for pages/components matching this decision
       - Test Scenarios: infer 2-3 testable scenarios from decision text
    4. If decision is pure infra/config (no API/UI): write "none" for Endpoints/UI
    5. Do NOT invent endpoints that don't exist in code — only document what's built
    
    Code patterns to scan:
      API routes: ${config.code_patterns.api_routes}
      Web pages: ${config.code_patterns.web_pages}
    
    <context_md>
    @${PHASE_DIR}/CONTEXT.md
    </context_md>
    
    <code_scan_hints>
    Grep existing endpoints in codebase related to this phase's domain.
    </code_scan_hints>
    
    Output: write enriched CONTEXT.md to ${PHASE_DIR}/CONTEXT.md.enriched (STAGING — NOT overwriting CONTEXT.md yet)
```

**⛔ CRITICAL: Agent writes to STAGING file, not CONTEXT.md directly.** Validation below must pass before promoting staging → CONTEXT.md.

**Post-conversion validation (tightened 2026-04-17 — decision preservation gate):**

```bash
STAGING="${PHASE_DIR}/CONTEXT.md.enriched"
ORIGINAL="${PHASE_DIR}/.gsd-backup/CONTEXT.md.gsd"

if [ ! -f "$STAGING" ]; then
  echo "⛔ Agent did not write staging file ${STAGING}. Aborting."
  exit 1
fi

if [ ! -f "$ORIGINAL" ]; then
  echo "⛔ Backup missing at ${ORIGINAL} — step 3 did not run? Aborting."
  exit 1
fi

# ─── Gate 1: Every D-XX in ORIGINAL must exist in STAGING ───────────
${PYTHON_BIN:-python3} - "$ORIGINAL" "$STAGING" <<'PY' || exit 1
import re, sys
orig_path, stage_path = sys.argv[1], sys.argv[2]
orig = open(orig_path, encoding='utf-8').read()
stage = open(stage_path, encoding='utf-8').read()

# Extract decision IDs (D-01, D-02, etc.) — flexible matching for ## or ### prefix
def ids(text):
    return set(re.findall(r'(?mi)^#+\s*(D-\d+)\s*:', text))

orig_ids = ids(orig)
stage_ids = ids(stage)

missing = sorted(orig_ids - stage_ids, key=lambda x: int(x.split('-')[1]))
extra = sorted(stage_ids - orig_ids, key=lambda x: int(x.split('-')[1]))

if missing:
    print(f"⛔ DECISIONS LOST: agent dropped {len(missing)} decision(s) from original:")
    for d in missing:
        print(f"    {d}")
    print(f"\n    Original had {len(orig_ids)} decisions: {sorted(orig_ids)}")
    print(f"    Staging has  {len(stage_ids)} decisions: {sorted(stage_ids)}")
    print("")
    print(f"    Staging file kept at: {stage_path} for inspection")
    print(f"    Original preserved:    {orig_path}")
    print(f"    CONTEXT.md NOT modified. Re-run with different agent prompt or manual migration.")
    sys.exit(1)

if extra:
    print(f"⚠ WARNING: staging has {len(extra)} decision(s) not in original: {extra}")
    print(f"  Agent may have invented decisions. Review staging before accepting.")
    # Not fatal but loud

print(f"✓ All {len(orig_ids)} decisions preserved: {sorted(orig_ids)}")
PY

# ─── Gate 2: Decision BODY preserved (fuzzy — must not be rewritten) ─
${PYTHON_BIN:-python3} - "$ORIGINAL" "$STAGING" <<'PY' || exit 1
import re, sys, difflib
orig = open(sys.argv[1], encoding='utf-8').read()
stage = open(sys.argv[2], encoding='utf-8').read()

def extract_bodies(text):
    """Return dict D-XX -> body text (between header and next header / sub-section)."""
    bodies = {}
    # Split by decision headers
    chunks = re.split(r'(?mi)^(#+\s*D-\d+\s*:[^\n]*)', text)
    # chunks: [preamble, header1, body1, header2, body2, ...]
    i = 1
    while i < len(chunks):
        header = chunks[i]
        body = chunks[i+1] if i+1 < len(chunks) else ""
        m = re.search(r'(D-\d+)', header)
        if m:
            did = m.group(1)
            # Strip VG sub-sections (**Endpoints:**, **UI Components:**, **Test Scenarios:**)
            body_clean = re.split(r'(?m)^\*\*(?:Endpoints|UI Components|Test Scenarios):\*\*', body)[0]
            bodies[did] = body_clean.strip()
        i += 2
    return bodies

orig_bodies = extract_bodies(orig)
stage_bodies = extract_bodies(stage)

drift_threshold = 0.80  # similarity ratio; < threshold = body was rewritten
rewrites = []
for did, orig_body in orig_bodies.items():
    stage_body = stage_bodies.get(did, "")
    if not orig_body.strip() and not stage_body.strip():
        continue
    ratio = difflib.SequenceMatcher(None, orig_body, stage_body).ratio()
    if ratio < drift_threshold:
        rewrites.append((did, ratio, orig_body[:100], stage_body[:100]))

if rewrites:
    print(f"⛔ DECISION BODY REWRITTEN: agent rewrote prose for {len(rewrites)} decision(s):")
    for did, ratio, orig_snip, stage_snip in rewrites:
        print(f"    {did}: similarity={ratio:.0%}")
        print(f"      ORIGINAL: {orig_snip!r}")
        print(f"      STAGING:  {stage_snip!r}")
    print("")
    print(f"    Rule #1 violated: 'Keep ALL existing decision text EXACTLY as-is'.")
    print(f"    CONTEXT.md NOT modified. Staging preserved for review: $STAGING")
    sys.exit(1)

print(f"✓ All decision bodies preserved (>= 80% similarity)")
PY

# ─── Gate 3: Sub-section coverage check (3 sub-sections required, v1.14.4+) ───
DECISIONS=$(grep -cE "^#+\s*D-[0-9]+" "$STAGING")
ENDPOINTS=$(grep -c "^\*\*Endpoints:\*\*" "$STAGING")
UI_COMPS=$(grep -c "^\*\*UI Components:\*\*" "$STAGING")
TEST_SCENS=$(grep -c "^\*\*Test Scenarios:\*\*" "$STAGING")

COVERAGE_FAIL=0
if [ "$DECISIONS" != "$ENDPOINTS" ]; then
  echo "⛔ Gate 3 FAIL: ${DECISIONS} decisions but ${ENDPOINTS} **Endpoints:** sub-sections"
  COVERAGE_FAIL=$((COVERAGE_FAIL + 1))
fi
if [ "$DECISIONS" != "$UI_COMPS" ]; then
  echo "⛔ Gate 3 FAIL: ${DECISIONS} decisions but ${UI_COMPS} **UI Components:** sub-sections"
  COVERAGE_FAIL=$((COVERAGE_FAIL + 1))
fi
if [ "$DECISIONS" != "$TEST_SCENS" ]; then
  echo "⛔ Gate 3 FAIL: ${DECISIONS} decisions but ${TEST_SCENS} **Test Scenarios:** sub-sections"
  echo "   Blueprint step 2a CONTEXT format validation will block downstream."
  COVERAGE_FAIL=$((COVERAGE_FAIL + 1))
fi

if [ "$COVERAGE_FAIL" -gt 0 ]; then
  echo "⛔ ${COVERAGE_FAIL} sub-section coverage gate(s) failed. Staging at $STAGING — re-run agent."
  exit 1
fi
echo "✓ Gate 3: all ${DECISIONS} decisions có 3 sub-sections (Endpoints/UI/Test Scenarios)"

# ─── All gates passed: promote staging → CONTEXT.md atomically ───
echo ""
echo "✓ Migration gates passed. Promoting staging → CONTEXT.md"
mv "$STAGING" "${PHASE_DIR}/CONTEXT.md"

# ⛔ Hallucination check (tightened 2026-04-17): enriched CONTEXT may hallucinate endpoints.
# For every endpoint mentioned in Endpoints sections, grep actual API route files
# to confirm it exists. Missing endpoints → fail (rewrite required).
API_ROUTES_GLOB="${config.code_patterns.api_routes:-apps/api/src/modules/**/*.routes.ts}"

HALLUCINATED=0
while IFS= read -r ep; do
  # Extract VERB + path, e.g., "POST /api/sites"
  METHOD=$(echo "$ep" | grep -oE "^(GET|POST|PUT|PATCH|DELETE)")
  PATH_PART=$(echo "$ep" | grep -oE '/[a-zA-Z0-9/_:{}.-]+')
  [ -z "$METHOD" ] || [ -z "$PATH_PART" ] && continue

  # Search for route registration — various frameworks
  if ! grep -rEq "(\.|@)(${METHOD,,}|route|Route).*['\"\`]${PATH_PART}['\"\`]" $API_ROUTES_GLOB 2>/dev/null \
     && ! grep -rEq "method.*['\"\`]${METHOD}['\"\`].*path.*['\"\`]${PATH_PART}['\"\`]" $API_ROUTES_GLOB 2>/dev/null; then
    echo "⚠ HALLUCINATED endpoint: ${METHOD} ${PATH_PART} — not found in ${API_ROUTES_GLOB}"
    HALLUCINATED=$((HALLUCINATED + 1))
  fi
done < <(grep -oE "(GET|POST|PUT|PATCH|DELETE)\s+/[a-zA-Z0-9/_:{}.-]+" "${PHASE_DIR}/CONTEXT.md" | sort -u)

if [ "$HALLUCINATED" -gt 0 ]; then
  TOTAL_EPS=$(grep -oE "(GET|POST|PUT|PATCH|DELETE)\s+/" "${PHASE_DIR}/CONTEXT.md" | wc -l | tr -d ' ')
  RATIO=$((HALLUCINATED * 100 / (TOTAL_EPS + 1)))
  echo "Hallucination ratio: ${HALLUCINATED}/${TOTAL_EPS} (${RATIO}%)"
  if [ "$RATIO" -gt 10 ]; then
    echo "⛔ Hallucination ratio > 10% — enrichment agent likely invented endpoints."
    echo "   Fix: rewrite CONTEXT.md manually OR ensure code has the referenced routes first."
    if [[ ! "$ARGUMENTS" =~ --allow-hallucinated-eps ]]; then
      exit 1
    fi
  fi
fi
```
</step>

<step name="5_generate_contracts">
## Generate API-CONTRACTS.md (if missing)

**Skip if:** API-CONTRACTS.md exists AND not --force. Also skip if --skip-contracts.

This reuses the existing blueprint contract generation logic, but targeted at an already-built phase.

**Key difference from blueprint:** blueprint generates contracts BEFORE code. Migrate generates contracts FROM existing code (reverse-engineering).

```
Agent(model="sonnet", description="Generate API-CONTRACTS.md from built code"):
  prompt: |
    Read skill: .claude/skills/api-contract/SKILL.md — Mode: Generate.
    
    Generate API-CONTRACTS.md for phase ${PHASE_NUMBER}.
    This phase was ALREADY BUILT — extract contracts from existing code, don't invent.
    
    Inputs:
    1. CONTEXT.md enriched decisions (Endpoints sub-sections)
    2. Actual route handler code at: ${config.code_patterns.api_routes}
    3. Contract format: ${config.contract_format.type}
    
    Process:
    1. Read CONTEXT.md → list endpoints mentioned in Endpoints sub-sections
    2. For each endpoint, grep actual route handler in codebase
    3. Extract: method, path, request schema (from validation), response shape, auth middleware, error codes
    4. Generate 4-block contract per endpoint (auth, schema, errors, sample)
    5. If code uses Zod: extract schema directly from code (don't reinvent)
    6. If code uses bare validation: create Zod schema matching the validation logic
    
    CRITICAL: This is REVERSE-ENGINEERING from code, not forward-design.
    Every field, every status code, every auth guard MUST match what's actually in the code.
    
    Output: write to ${PHASE_DIR}/API-CONTRACTS.md.staged (STAGING — not final).
```

**Preservation gate (tightened 2026-04-17):**

If `API-CONTRACTS.md` already exists (`--force` case), backup first then diff:

```bash
STAGING="${PHASE_DIR}/API-CONTRACTS.md.staged"
TARGET="${PHASE_DIR}/API-CONTRACTS.md"

[ -f "$STAGING" ] || { echo "⛔ Agent did not write staging ${STAGING}"; exit 1; }

# If overwriting existing file, backup + verify endpoint preservation
if [ -f "$TARGET" ]; then
  cp "$TARGET" "${PHASE_DIR}/.gsd-backup/API-CONTRACTS.md.pre-migrate"
  ${PYTHON_BIN:-python3} - "$TARGET" "$STAGING" <<'PY' || exit 1
import re, sys
orig = open(sys.argv[1], encoding='utf-8').read()
new = open(sys.argv[2], encoding='utf-8').read()
def paths(t): return set(re.findall(r'(?m)^[#\s]*(GET|POST|PUT|PATCH|DELETE)\s+(/[^\s`]+)', t))
orig_eps, new_eps = paths(orig), paths(new)
missing = orig_eps - new_eps
if missing:
    print(f"⛔ CONTRACTS LOST: {len(missing)} endpoint(s) in existing file not in new:")
    for m, p in sorted(missing): print(f"    {m} {p}")
    print(f"    Existing API-CONTRACTS.md preserved. Staging kept at {sys.argv[2]}")
    sys.exit(1)
print(f"✓ All {len(orig_eps)} existing endpoints preserved (+{len(new_eps - orig_eps)} new)")
PY
fi

mv "$STAGING" "$TARGET"
echo "✓ API-CONTRACTS.md written"
```
</step>
