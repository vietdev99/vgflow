# Scope artifact write (STEP 4 — `2_artifact_generation`)

> Atomic group commit: writes CONTEXT.md (Layer 3 flat) + CONTEXT/D-NN.md per decision (Layer 1) + CONTEXT/index.md (Layer 2) + DISCUSSION-LOG.md (append-only).

## §1. Build CONTEXT.md.staged

Write to `${PHASE_DIR}/CONTEXT.md.staged`:

```markdown
# Phase {N} — {Name} — CONTEXT

Generated: {ISO date}
Source: /vg:scope structured discussion (5 rounds + Deep Probe)

## Decisions

**Namespace:** IDs are `P{phase}.D-XX` where `{phase}` = `${PHASE_NUMBER}`. Substitute actual phase number.

### P${PHASE_NUMBER}.D-01: {decision title}
**Category:** business | technical
**Decision:** {what was decided}
**Rationale:** {why}
**Quote source:** DISCUSSION-LOG.md#round-{N}
**Endpoints:**
- POST /api/v1/{resource} (auth: {role}, purpose: {description})
**UI Components:**
- {ComponentName}: {description}
**Test Scenarios:**
- TS-01: {user does X} → {expected result}
  verification_strategy: automated|manual|fixture|faketime
**Constraints:** {if any, else omit line}

### P${PHASE_NUMBER}.D-02: ...
...

## Acknowledged tradeoffs
{from challenger choose=Acknowledge}

## Acknowledged gaps
{from expander choose=Acknowledge}

## Open questions
{from challenger/expander choose=Defer}

## Summary
- Total decisions: {N}
- Endpoints noted: {N}
- UI components noted: {N}
- Test scenarios noted: {N}

## Deferred Ideas
{ideas explicitly out of scope, or "None"}
```

**Rules:**
- Decisions numbered sequentially `P{phase}.D-01`, `D-02`, … (phase prefix MANDATORY)
- Every decision with **Endpoints:** MUST have ≥ 1 test scenario referencing it
- Endpoint format: `METHOD /path (auth: role, purpose: description)`
- UI component format: `ComponentName: description`
- TS format: `TS-XX: action → expected result`
- Omit empty sub-sections

## §2. Namespace validator gate (HARD BLOCK)

```bash
source .claude/commands/vg/_shared/lib/namespace-validator.sh

STAGED="${PHASE_DIR}/CONTEXT.md.staged"
if ! validate_d_xx_namespace "$STAGED" "phase:${PHASE_NUMBER}"; then
  echo ""
  echo "⛔ Scope gate chặn: CONTEXT.md.staged còn chứa bare D-XX."
  echo "   Sửa bare D-XX thành P${PHASE_NUMBER}.D-XX trong file .staged, rồi chạy lại /vg:scope ${PHASE_NUMBER}."
  exit 1
fi
```

## §3. Promote staged → CONTEXT.md (Layer 3 flat)

```bash
mv "$STAGED" "${PHASE_DIR}/CONTEXT.md"
```

## §4. Per-decision split (Layer 1) + index (Layer 2) — UX baseline R1

```bash
mkdir -p "${PHASE_DIR}/CONTEXT"

"${PYTHON_BIN:-python3}" - "${PHASE_DIR}/CONTEXT.md" "${PHASE_DIR}/CONTEXT" <<'PY'
import re, sys, pathlib

flat = pathlib.Path(sys.argv[1]).read_text(encoding='utf-8')
out_dir = pathlib.Path(sys.argv[2])
out_dir.mkdir(exist_ok=True)

# Match `### P{phase}.D-NN: title` OR legacy `### D-NN: title`
pattern = re.compile(r'^### (?:P[0-9.]+\.)?(D-\d+)(:?\s.*)?$', re.M)
matches = list(pattern.finditer(flat))

if not matches:
    print("⚠ no D-XX headings found in CONTEXT.md — split skipped", file=sys.stderr)
    sys.exit(0)

index_lines = ["# CONTEXT decisions index", ""]
for i, m in enumerate(matches):
    decision_id = m.group(1)
    end = matches[i+1].start() if i+1 < len(matches) else len(flat)
    body = flat[m.start():end].rstrip() + "\n"
    out_file = out_dir / f"{decision_id}.md"
    out_file.write_text(body, encoding='utf-8')
    title_line = (m.group(2) or "").lstrip(": ").strip().splitlines()[0] if m.group(2) else ""
    suffix = f" — {title_line}" if title_line else ""
    index_lines.append(f"- [{decision_id}]({decision_id}.md){suffix}")

(out_dir / "index.md").write_text("\n".join(index_lines) + "\n", encoding='utf-8')
print(f"✓ split {len(matches)} decisions → CONTEXT/D-*.md + index.md")
PY
```

## §5. DISCUSSION-LOG.md (APPEND-ONLY)

If file exists, read content, then append new session block (preserve previous sessions verbatim). Otherwise create.

Append:

```markdown
# Discussion Log — Phase {N}

## Session {ISO date} — {Initial Scope | Re-scope | Update}

### Round 1: Domain & Business
**Q:** {AI's question/analysis — abbreviated}
**A:** {user's response — full text}
**Locked:** D-01, D-02, D-03

### Round 2: Technical Approach
**Q:** ...
**A:** ...
**Locked:** D-04, D-05

### Round 3: API Design
### Round 4: UI/UX
### Round 5: Test Scenarios
### Loop: Deep Probe
{deep probe Q&A pairs}
```

```bash
# AI writes via Write/Edit tool — do NOT use shell heredoc that risks overwrite of existing append-only file
# Pseudocode:
#   if exists DISCUSSION-LOG.md:
#       read existing → preserve verbatim
#       append "## Session ..." block
#   else:
#       create with header + this session block
```

## §6. Schema validation gate (HARD BLOCK on drift)

```bash
mkdir -p "${PHASE_DIR}/.tmp" 2>/dev/null
"${PYTHON_BIN:-python3}" .claude/scripts/validators/verify-artifact-schema.py \
  --phase "${PHASE_NUMBER}" --artifact context \
  > "${PHASE_DIR}/.tmp/artifact-schema-context.json" 2>&1
SCHEMA_RC=$?
if [ "${SCHEMA_RC}" != "0" ]; then
  echo "⛔ CONTEXT.md schema violation — see ${PHASE_DIR}/.tmp/artifact-schema-context.json"
  cat "${PHASE_DIR}/.tmp/artifact-schema-context.json"
  exit 2
fi
```

## §7. Mark step + emit event

```bash
vg-orchestrator mark-step scope 2_artifact_generation
DEC_COUNT=$(grep -cE '^### (P[0-9.]+\.)?D-' "${PHASE_DIR}/CONTEXT.md")
vg-orchestrator emit-event scope.artifact_written \
  --payload "{\"decisions\":${DEC_COUNT}}" >/dev/null 2>&1 || true
```

## Advance

Read `_shared/scope/completeness-validation.md` next.
