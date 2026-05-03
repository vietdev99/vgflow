# Phase Reconnaissance (Shared Reference)

Referenced by phase.md (step 1.5), next.md (detect step), build.md (step 0.5 gate).

## Purpose

Before routing to any pipeline step, inventory all files in `${PHASE_DIR}/`,
classify them (V6 canonical / V5 numbered / legacy GSD / rot / orphan),
detect pipeline position, and present migration + archive options.

**Prevents destructive re-run** of phases that have legacy artifacts.

## Prerequisites

Config-loader must be loaded first (provides `$PYTHON_BIN`, `$PHASE_DIR`, `$PROFILE`).

## Step R1: Run recon script

```bash
RECON_STATE="${PHASE_DIR}/.recon-state.json"

# --fresh when caller passes --recon-fresh; otherwise uses cache if fingerprint matches
${PYTHON_BIN} .claude/scripts/phase-recon.py \
  --phase-dir "${PHASE_DIR}" \
  --profile "${PROFILE}" \
  ${RECON_FRESH:+--fresh}

# Capture outputs
PHASE_TYPE=$(${PYTHON_BIN} -c "
import json; s=json.load(open('${PHASE_DIR}/.recon-state.json', encoding='utf-8'))
print(s['phase_type'])
")
RECOMMENDED_STEP=$(${PYTHON_BIN} -c "
import json; s=json.load(open('${PHASE_DIR}/.recon-state.json', encoding='utf-8'))
print(s['recommended_action']['step'])
")
HAS_PRE_ACTION=$(${PYTHON_BIN} -c "
import json; s=json.load(open('${PHASE_DIR}/.recon-state.json', encoding='utf-8'))
print('yes' if s['recommended_action'].get('pre_action') else 'no')
")
```

## Step R2: Show report (always)

Read and display `${PHASE_DIR}/.recon-report.md` — human-friendly table with
pipeline position, bucket counts, migration candidates, rot items, and recommendation.

## Step R3: Route based on phase_type

### If `PHASE_TYPE ∈ {v6_native}` AND `HAS_PRE_ACTION = no`

Phase is clean V6. Skip migration menu — proceed directly to `RECOMMENDED_STEP`.
```
Phase ${PHASE_NUMBER} is V6-native — no legacy artifacts detected.
Routing to: /vg:${RECOMMENDED_STEP} ${PHASE_NUMBER}
```

### If `PHASE_TYPE ∈ {legacy_gsd, v5_iterative, hybrid}` OR `HAS_PRE_ACTION = yes`

Legacy or mixed state detected. Present interactive migration menu.

#### Step R3a: Count actionable items

```bash
${PYTHON_BIN} -c "
import json
s = json.load(open('${PHASE_DIR}/.recon-state.json', encoding='utf-8'))
mig_rec = [m for m in s.get('migration_candidates', []) if m['priority']=='recommended']
mig_conflict = [m for m in s.get('migration_candidates', []) if m['priority']=='conflict']
rot = s.get('rot_to_archive', [])
consol = s.get('consolidation_candidate')
has_consol = consol and consol.get('priority') == 'recommended'
print(f'MIGRATIONS_RECOMMENDED={len(mig_rec)}')
print(f'MIGRATIONS_CONFLICT={len(mig_conflict)}')
print(f'ROT_ITEMS={len(rot)}')
print(f'HAS_CONSOLIDATION={\"yes\" if has_consol else \"no\"}')" | while IFS='=' read k v; do eval "$k=$v"; done
```

#### Step R3b: Present menu

```
AskUserQuestion:
  "Phase ${PHASE_NUMBER} detected as: ${PHASE_TYPE}

   Actionable:
     ${MIGRATIONS_RECOMMENDED} migrations (recommended — legacy → V6 draft)
     ${MIGRATIONS_CONFLICT} migrations (conflict — target exists, archive source instead)
     ${HAS_CONSOLIDATION} plan/summary consolidation (numbered → single file)
     ${ROT_ITEMS} rot items to archive (versioned/stale files)

   Options:
     [1] Apply all recommended (consolidate + migrate + archive rot) — THEN re-recon + route
     [2] Review each item individually (sub-menu per migration/rot)
     [3] Skip migration — proceed to ${RECOMMENDED_STEP} with current state
     [4] Abort (do nothing)

   Details: cat ${PHASE_DIR}/.recon-report.md"
```

#### Step R3c: Execute chosen option

**Option [1] — Apply all:**
```bash
${PYTHON_BIN} .claude/scripts/phase-migrate.py \
  --phase-dir "${PHASE_DIR}" \
  --consolidate --apply-all-recommended --archive-all-rot

# Re-recon (state invalidated by migrate)
${PYTHON_BIN} .claude/scripts/phase-recon.py \
  --phase-dir "${PHASE_DIR}" --profile "${PROFILE}" --fresh

# Re-read recommended step (may have changed after migration)
RECOMMENDED_STEP=$(${PYTHON_BIN} -c "
import json; s=json.load(open('${PHASE_DIR}/.recon-state.json', encoding='utf-8'))
print(s['recommended_action']['step'])
")
```

**Option [2] — Per-item review:**

Present each migration candidate:
```
For each M in migration_candidates where priority=recommended:
  AskUserQuestion:
    "Migration ${M.id}: ${M.source} → ${M.target} (${M.type})
     [a] Apply
     [s] Skip
     [d] Archive source only (keep target as-is)"

  If apply → ${PYTHON_BIN} phase-migrate.py --phase-dir ... --apply ${M.id}
  If archive → ${PYTHON_BIN} phase-migrate.py --phase-dir ... --archive-source ${M.source}
```

Then consolidation:
```
If HAS_CONSOLIDATION:
  AskUserQuestion:
    "Consolidate N numbered PLANs + M numbered SUMMARYs into single files?
     [a] Apply consolidation
     [s] Skip"
  If apply → ${PYTHON_BIN} phase-migrate.py --phase-dir ... --consolidate
```

Then rot:
```
AskUserQuestion:
  "Archive ${ROT_ITEMS} rot items (versioned duplicates + stale scans)?
   [a] Archive all
   [s] Skip
   [r] Review each"
```

After all: re-recon + update `RECOMMENDED_STEP`.

**Option [3] — Skip:**
```
Proceed with current state. May hit BLOCK gates downstream if V6 artifacts missing.
```

**Option [4] — Abort:**
```
exit 0 (no routing)
```

## Step R4: Return routing decision

Set `$START_STEP` for the caller:
```bash
START_STEP="${RECOMMENDED_STEP}"
```

The caller (phase.md / next.md) uses `$START_STEP` to invoke the appropriate `/vg:{step}` command.

## Cache behavior

- `.recon-state.json` cached with dir fingerprint
- Re-scan when: `--recon-fresh`, fingerprint mismatch (file added/removed/modified), missing state
- After migration: state auto-invalidated (migrate script deletes `.recon-state.json`)

## Files touched

- **Read:** all files in `${PHASE_DIR}/`
- **Write:** `${PHASE_DIR}/.recon-state.json`, `${PHASE_DIR}/.recon-report.md`
- **Write (migration only):** new V6 draft files, moves to `${PHASE_DIR}/.archive/{timestamp}/`
- **Never delete:** everything archived, never rm'd
