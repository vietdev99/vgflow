<step name="1_parse_args">
Parse `$ARGUMENTS`: phase number (required, OR `--self-test`), optional flags:
- `--dry-run` — show what would be converted, don't write files
- `--force` — re-convert even if VG artifacts already exist (backup existing first)
- `--skip-contracts` — skip API-CONTRACTS.md generation (manual later)
- `--skip-goals` — skip TEST-GOALS.md generation (manual later)
- `--allow-semantic-gaps` — bypass step 9 VG semantic gates. Logs override-debt. NOT recommended.
- `--allow-hallucinated-eps` — bypass step 4 hallucination check. Logs override-debt.
- `--self-test` — run gate logic on shipped fixture `<vgflow>/fixtures/migrate/legacy-sample/expected/`, diff vs golden report. Deterministic, no AI spawn. Use to verify gate logic correctness after editing migrate.md.

### Self-test mode (deterministic, no AI)

If `--self-test` flag passed, run gate validator against shipped fixture, diff vs golden report, exit. Skip all other steps.

```bash
if [[ "$ARGUMENTS" =~ --self-test ]]; then
  # Locate fixture (relative to vgflow-repo install or .claude/commands/ in project)
  FIXTURE_DIR=""
  for candidate in \
    "${REPO_ROOT}/fixtures/migrate/legacy-sample" \
    "${REPO_ROOT}/.claude/fixtures/migrate/legacy-sample" \
    "$(dirname "${0}")/../../fixtures/migrate/legacy-sample"; do
    [ -d "$candidate" ] && FIXTURE_DIR="$candidate" && break
  done

  if [ -z "$FIXTURE_DIR" ]; then
    echo "⛔ Self-test: fixture not found in any expected location."
    echo "   Looked in: \${REPO_ROOT}/fixtures/, .claude/fixtures/, sibling to migrate.md"
    exit 1
  fi

  echo "Self-test: fixture at $FIXTURE_DIR"
  VERIFY_SCRIPT="${REPO_ROOT}/.claude/scripts/verify-migrate-output.py"
  [ -f "$VERIFY_SCRIPT" ] || VERIFY_SCRIPT="${REPO_ROOT}/scripts/verify-migrate-output.py"
  [ -f "$VERIFY_SCRIPT" ] || { echo "⛔ verify-migrate-output.py missing"; exit 1; }

  ACTUAL=$(${PYTHON_BIN:-python3} "$VERIFY_SCRIPT" "${FIXTURE_DIR}/expected/" 2>&1)
  ACTUAL_RC=$?
  EXPECTED_FILE="${FIXTURE_DIR}/expected/validation-report.txt"

  if [ "$ACTUAL_RC" != "0" ]; then
    echo "⛔ Self-test FAIL: validator exit ${ACTUAL_RC} on golden fixture"
    echo "$ACTUAL"
    if type -t emit_telemetry_v2 >/dev/null 2>&1; then
      emit_telemetry_v2 "migrate_self_test_fail" "self-test" "migrate.1" "validator_fail" "FAIL" "{\"rc\":${ACTUAL_RC}}"
    fi
    exit 1
  fi

  # Diff actual vs golden (CRLF-tolerant for Windows)
  DIFF_OUT=$(echo "$ACTUAL" | diff --strip-trailing-cr "$EXPECTED_FILE" - 2>&1)
  if [ -z "$DIFF_OUT" ]; then
    echo "✓ Self-test PASS: gate logic produces golden output"
    if type -t emit_telemetry_v2 >/dev/null 2>&1; then
      emit_telemetry_v2 "migrate_self_test_pass" "self-test" "migrate.1" "fixture_match" "PASS" "{}"
    fi
    exit 0
  else
    echo "⛔ Self-test FAIL: actual output differs from golden:"
    echo "$DIFF_OUT"
    echo ""
    echo "Either: (a) gate logic regressed — fix verify-migrate-output.py"
    echo "        (b) intentional change — update fixtures/migrate/legacy-sample/expected/validation-report.txt"
    if type -t emit_telemetry_v2 >/dev/null 2>&1; then
      emit_telemetry_v2 "migrate_self_test_fail" "self-test" "migrate.1" "golden_diff" "FAIL" "{}"
    fi
    exit 1
  fi
fi
```
</step>

<step name="2_detect_artifacts">
## Artifact Inventory

Scan `${PHASE_DIR}/` and classify every file:

```bash
echo "=== Phase ${PHASE_NUMBER} Artifact Inventory ==="

# GSD-era artifacts (may need conversion)
GSD_ARTIFACTS=()
VG_ARTIFACTS=()
MISSING_VG=()

# Check each expected file
for f in RESEARCH.md CONTEXT.md PLAN.md SUMMARY*.md DISCUSSION-LOG.md; do
  if ls "${PHASE_DIR}"/$f 2>/dev/null; then
    GSD_ARTIFACTS+=("$f")
  fi
done

# Check VG-native artifacts
for f in API-CONTRACTS.md TEST-GOALS.md FLOW-SPEC.md PIPELINE-STATE.json; do
  if [ -f "${PHASE_DIR}/$f" ]; then
    VG_ARTIFACTS+=("$f")
  else
    MISSING_VG+=("$f")
  fi
done

# Check CONTEXT.md format (enriched vs flat)
if [ -f "${PHASE_DIR}/CONTEXT.md" ]; then
  # VG enriched format has sub-sections per decision: Endpoints:, UI Components:, Test Scenarios:
  ENRICHED=$(grep -c "Endpoints:\|UI Components:\|Test Scenarios:" "${PHASE_DIR}/CONTEXT.md" 2>/dev/null || echo 0)
  if [ "$ENRICHED" -gt 0 ]; then
    CONTEXT_FORMAT="vg-enriched"
  else
    CONTEXT_FORMAT="gsd-flat"
  fi
fi

# Check PLAN.md format (VG attributes vs GSD plain)
if ls "${PHASE_DIR}"/PLAN*.md 2>/dev/null; then
  VG_ATTRS=$(grep -c "<file-path>\|<contract-ref>\|<goals-covered>" "${PHASE_DIR}"/PLAN*.md 2>/dev/null || echo 0)
  if [ "$VG_ATTRS" -gt 0 ]; then
    PLAN_FORMAT="vg-attributed"
  else
    PLAN_FORMAT="gsd-plain"
  fi
fi
```

**Display inventory:**

```
Phase {N} — Artifact Inventory
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
GSD artifacts found:     {list}
VG artifacts found:      {list}
VG artifacts missing:    {list}

CONTEXT.md format:       {gsd-flat | vg-enriched | missing}
PLAN.md format:          {gsd-plain | vg-attributed | missing}

Migration needed:
  [ ] CONTEXT.md enrichment    {yes/no — yes if gsd-flat}
  [ ] PLAN.md attribution      {yes/no — yes if gsd-plain}
  [ ] API-CONTRACTS.md         {generate/exists/skip}
  [ ] TEST-GOALS.md            {generate/exists/skip}
```

If ALL artifacts already VG-native → print "Phase already VG-native. Nothing to migrate." → STOP.
If `--dry-run` → print migration plan → STOP.
</step>

<step name="3_backup_originals">
## Backup GSD Originals

```bash
BACKUP_DIR="${PHASE_DIR}/.gsd-backup"
mkdir -p "$BACKUP_DIR"

# Backup files that will be converted (not all files)
if [ "$CONTEXT_FORMAT" = "gsd-flat" ]; then
  cp "${PHASE_DIR}/CONTEXT.md" "$BACKUP_DIR/CONTEXT.md.gsd"
  echo "Backed up: CONTEXT.md → .gsd-backup/CONTEXT.md.gsd"
fi

if [ "$PLAN_FORMAT" = "gsd-plain" ]; then
  for plan in "${PHASE_DIR}"/PLAN*.md; do
    PLAN_NAME=$(basename "$plan")
    cp "$plan" "$BACKUP_DIR/${PLAN_NAME}.gsd"
    echo "Backed up: ${PLAN_NAME} → .gsd-backup/${PLAN_NAME}.gsd"
  done
fi

# If --force and VG artifacts exist, backup those too
if [[ "$FLAGS" =~ --force ]]; then
  for f in API-CONTRACTS.md TEST-GOALS.md; do
    if [ -f "${PHASE_DIR}/$f" ]; then
      cp "${PHASE_DIR}/$f" "$BACKUP_DIR/${f}.prev"
      echo "Backed up: ${f} → .gsd-backup/${f}.prev"
    fi
  done
fi
```
</step>
