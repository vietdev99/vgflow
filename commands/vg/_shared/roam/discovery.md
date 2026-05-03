# roam discovery (STEP 3)

<HARD-GATE>
`1_discover_surfaces` MUST consume PLAN.md via `vg-load --index` (or
`--task NN` for drill-down) and load CRUD-SURFACES.md when present. Flat-
reading PLAN.md (`cat ${PHASE_DIR}/PLAN.md`) wastes context and silently
misses surfaces on large phases. Step 1 entry refuses to proceed unless
the 0aa + 0a HARD GATE markers exist (or `--non-interactive` set).
</HARD-GATE>

Two sub-steps:

1. `1_discover_surfaces` — find CRUD-bearing surfaces from phase artifacts
2. `2_compose_briefs` — generate `INSTRUCTION-{surface}-{lens}.md` per
   surface × lens × per-model dir (Cartesian)

## Why vg-load --index, not flat read?

Original step 1 read PLAN.md flat. On large phases PLAN.md is 8K+ lines —
the AI skims and misses surfaces. Phase F Task 30 (R3.5 absorbs vg:roam
portion) replaces the single L600 PLAN.md flat read with `vg-load --index`
that returns just the per-task index. Per-task expand happens only when a
specific CRUD surface needs drill-down.

CONTEXT.md and RUNTIME-MAP.md are KEEP-FLAT — small single docs (CONTEXT)
or already filtered JSON (RUNTIME-MAP from /vg:review).

---

<step name="1_discover_surfaces">
## Step 1 — Discover surfaces (commander)

Read PLAN.md (via vg-load --index), CONTEXT.md (flat), RUNTIME-MAP.md
(flat — JSON). Identify CRUD-bearing surfaces. Annotate each with URL,
role, entity, expected operations.

```bash
vg-orchestrator step-active 1_discover_surfaces

# v2.42.9 HARD GATE — refuse step 1 entry unless prior interactive prompts
# fired this run. Closes silent-skip path: AI cannot bypass 0aa+0a question
# batches and proceed to discover/compose/spawn. Bypass requires explicit
# --non-interactive (logged as override-debt by harness via runtime_contract).
RUN_MARK_DIR="${ROAM_DIR}/.tmp"
if [[ ! "$ARGUMENTS" =~ --non-interactive ]]; then
  for marker in 0aa-confirmed.marker 0a-confirmed.marker; do
    f="${RUN_MARK_DIR}/${marker}"
    if [ ! -f "$f" ]; then
      # 0aa marker may legitimately be missing on first run (no prior state →
      # 0aa skipped its 4-option prompt). Allow only if EXISTING_CONFIG was
      # absent at 0aa entry AND no legacy artifacts triggered HAS_RUN_BEFORE.
      if [ "$marker" = "0aa-confirmed.marker" ] && [ "${HAS_RUN_BEFORE:-false}" = "false" ]; then
        continue
      fi
      echo "⛔ HARD GATE BREACH (v2.42.9): step 1 entered without ${marker}"
      echo "   Prior interactive gate (0aa or 0a) did NOT fire its AskUserQuestion this run."
      echo "   AI must invoke AskUserQuestion per skill spec — silent skip not permitted."
      echo "   Override (NOT recommended, debt-logged): re-run with --non-interactive + explicit"
      echo "   flags (--target-env=X --model=Y --mode=Z) to skip prompts intentionally."
      "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
        "roam.gate_breach" --actor "orchestrator" --outcome "FAIL" \
        --payload "{\"phase\":\"${PHASE_NUMBER}\",\"missing_marker\":\"${marker}\"}" 2>/dev/null || true
      exit 1
    fi
    AGE=$(( $(date +%s) - $(awk -F'|' '{print $1}' "$f" 2>/dev/null || echo 0) ))
    if [ "$AGE" -gt 1800 ]; then
      echo "⛔ HARD GATE BREACH: ${marker} stale (${AGE}s old)"
      echo "   Marker must be written THIS run, not reused from prior session."
      echo "   Delete ${RUN_MARK_DIR}/ and re-invoke /vg:roam to refire prompts."
      exit 1
    fi
  done
  if [ -z "${ROAM_ENV:-}" ] || [ -z "${ROAM_MODEL:-}" ] || [ -z "${ROAM_MODE:-}" ]; then
    echo "⛔ HARD GATE BREACH: marker present but ROAM_ENV/MODEL/MODE empty"
    echo "   env='${ROAM_ENV:-}' model='${ROAM_MODEL:-}' mode='${ROAM_MODE:-}'"
    echo "   Step 0a did not actually resolve the 3-question batch."
    exit 1
  fi
fi

# Resume guard: skip when aggregate-only mode, OR when resuming + SURFACES.md exists
if [ "${ROAM_RESUME_MODE:-fresh}" = "aggregate-only" ]; then
  echo "▸ aggregate-only mode — skipping step 1 (discover_surfaces)"
  SURFACE_COUNT=$(grep -c "^| S[0-9]" "${ROAM_DIR}/SURFACES.md" 2>/dev/null || echo 0)
elif [ "${ROAM_RESUME_MODE:-fresh}" = "resume" ] && [ -f "${ROAM_DIR}/SURFACES.md" ] && [[ ! "$ARGUMENTS" =~ --refresh-surfaces ]]; then
  SURFACE_COUNT=$(grep -c "^| S[0-9]" "${ROAM_DIR}/SURFACES.md" 2>/dev/null || echo 0)
  echo "▸ resume mode — reusing existing SURFACES.md (${SURFACE_COUNT} surfaces). Pass --refresh-surfaces to re-discover."
else
  # vg-load --index: returns per-task PLAN.md index (NOT flat 8K-line read).
  # roam-discover-surfaces.py reads CONTEXT.md flat (small) + RUNTIME-MAP.md
  # flat (JSON), and uses --index for PLAN.md scan.
  "${PYTHON_BIN:-python3}" .claude/scripts/roam-discover-surfaces.py \
    --phase-dir "${PHASE_DIR}" \
    --use-vg-load-index \
    --output "${ROAM_DIR}/SURFACES.md"

  SURFACE_COUNT=$(grep -c "^| S[0-9]" "${ROAM_DIR}/SURFACES.md" 2>/dev/null || echo 0)
  echo "▸ Discovered ${SURFACE_COUNT} surface(s)"
fi

# Cost cap check
MAX_SURFACES=${VG_MAX_SURFACES:-50}
if [[ "$ARGUMENTS" =~ --max-surfaces=([0-9]+) ]]; then MAX_SURFACES="${BASH_REMATCH[1]}"; fi
if [ "$SURFACE_COUNT" -gt "$MAX_SURFACES" ]; then
  echo "⚠ Surface count ${SURFACE_COUNT} exceeds cap ${MAX_SURFACES}. Trimming to top ${MAX_SURFACES} by entity priority."
fi

(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER}" "1_discover_surfaces" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/1_discover_surfaces.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step roam 1_discover_surfaces 2>/dev/null || true
```

**DO NOT** `cat ${PHASE_DIR}/PLAN.md` or `Read ${PHASE_DIR}/PLAN.md` flat —
8K+ lines on large phases mean the AI skims and misses surfaces. Always go
through `vg-load --phase ${PHASE_NUMBER} --artifact plan --index`.
</step>

---

<step name="2_compose_briefs">
## Step 2 — Compose per-surface task briefs (commander)

For each surface × selected lens × per-model dir, generate
`INSTRUCTION-{surface}-{lens}.md` with verbatim HARD RULES + RCRURD
sequence + env-injected URL/credentials + cwd convention.

```bash
vg-orchestrator step-active 2_compose_briefs

# Resume guard: skip when aggregate-only, OR resume + briefs already exist.
# v2.42.13 (B3 fix) — every branch falls through to the SAME single marker
# emit at the bottom. Prior split-marker shape silently dropped the marker
# when SKIP_COMPOSE=1 was set inside the elif and EXISTING_BRIEF_COUNT
# satisfied the resume condition.
if [ "${ROAM_RESUME_MODE:-fresh}" = "aggregate-only" ]; then
  echo "▸ aggregate-only mode — skipping step 2 (compose_briefs)"
  BRIEF_COUNT=$(find "${ROAM_MODEL_DIRS[@]}" -maxdepth 1 -name "INSTRUCTION-*.md" 2>/dev/null | wc -l | tr -d ' ')
  SKIP_COMPOSE=1
elif [ "${ROAM_RESUME_MODE:-fresh}" = "resume" ] && [[ ! "$ARGUMENTS" =~ --refresh-briefs ]]; then
  EXISTING_BRIEF_COUNT=$(find "${ROAM_MODEL_DIRS[@]}" -maxdepth 1 -name "INSTRUCTION-*.md" 2>/dev/null | wc -l | tr -d ' ')
  if [ "$EXISTING_BRIEF_COUNT" -ge "$SURFACE_COUNT" ]; then
    echo "▸ resume mode — reusing existing INSTRUCTION-*.md (${EXISTING_BRIEF_COUNT} briefs across ${#ROAM_MODEL_DIRS[@]} model dir(s)). Pass --refresh-briefs to regenerate."
    BRIEF_COUNT=$EXISTING_BRIEF_COUNT
    SKIP_COMPOSE=1
  fi
fi

if [ "${SKIP_COMPOSE:-0}" != "1" ]; then

LENS_LIST="${VG_LENS:-auto}"
if [[ "$ARGUMENTS" =~ --lens=([a-z,-]+) ]]; then LENS_LIST="${BASH_REMATCH[1]}"; fi

# Resolve env-specific creds via Python helper. Anchor on `credentials:` block —
# vg.config.md has multiple `local:` sections (environments.local, services.local,
# credentials.local) that must not be confused.
${PYTHON_BIN:-python3} -c "
import json, re, sys, pathlib
text = open('.claude/vg.config.md', encoding='utf-8').read()
env = '${ROAM_ENV}'
roles = []
cm = re.search(r'^credentials:\s*\$', text, re.M)
if cm:
    after = text[cm.end():cm.end()+10000]
    lm = re.search(rf'^\s+{re.escape(env)}:\s*\$', after, re.M)
    if lm:
        section = after[lm.end():lm.end()+5000]
        for rm in re.finditer(r'-\s*role:\s*\"([^\"]+)\"\s*\n\s*domain:\s*\"([^\"]+)\"\s*\n\s*email:\s*\"([^\"]+)\"\s*\n\s*password:\s*\"([^\"]+)\"', section):
            roles.append({'role': rm.group(1), 'domain': rm.group(2), 'email': rm.group(3), 'password': rm.group(4)})
            if len(roles) >= 5: break
pathlib.Path('${ROAM_DIR}/.env-creds.json').write_text(json.dumps({'env': env, 'roles': roles}, indent=2))
print(f'[roam] extracted {len(roles)} role(s) for env={env}', file=sys.stderr)
"

# Compose briefs into EACH per-model dir (council = 2 dirs, single = 1)
for MODEL_DIR in "${ROAM_MODEL_DIRS[@]}"; do
  MODEL_NAME=$(basename "$MODEL_DIR")
  ${PYTHON_BIN:-python3} .claude/scripts/roam-compose-brief.py \
    --phase-dir "${PHASE_DIR}" \
    --surfaces "${ROAM_DIR}/SURFACES.md" \
    --lenses "${LENS_LIST}" \
    --output-dir "${MODEL_DIR}" \
    --env "${ROAM_ENV}" \
    --target-url "${ROAM_TARGET_URL}" \
    --creds-json "${ROAM_DIR}/.env-creds.json" \
    --model "${MODEL_NAME}" \
    --cwd-convention "\${PHASE_DIR}/roam/${MODEL_NAME}" \
    --include-security "$([[ "$ARGUMENTS" =~ --include-security ]] && echo true || echo false)"
done

BRIEF_COUNT=$(find "${ROAM_MODEL_DIRS[@]}" -maxdepth 1 -name "INSTRUCTION-*.md" 2>/dev/null | wc -l | tr -d ' ')
echo "▸ Composed ${BRIEF_COUNT} brief(s) across ${#ROAM_MODEL_DIRS[@]} model dir(s)"

fi  # end SKIP_COMPOSE guard

# Single idempotent marker emit — fires on EVERY path (compose, resume-reuse,
# aggregate-only). Prior shape had separate emits per branch and missed the
# resume-reuse path entirely.
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER}" "2_compose_briefs" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/2_compose_briefs.done"
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator mark-step roam 2_compose_briefs 2>/dev/null || true
```

**Conformance contract (per `<rules>` in roam.md):** every brief MUST inject
`vg:_shared:scanner-report-contract` (banned vocab + report schema). Briefs
without the contract block REJECTED at compose time by `roam-compose-brief.py`.

**Lens auto-pick** by phase profile + entity types (Q9 default). Manual
override via `--lens=`. Security lens skipped by default — enable via
`--include-security` for double-coverage.
</step>
