# scope crossai (STEP 6)

> Wraps `4_crossai_review` + `4_5_bootstrap_reflection` + `4_6_test_strategy` step markers.

<HARD-GATE>
3 sub-steps in order: §1-§3b (CrossAI review), §4 (bootstrap reflection),
§5 (TEST-STRATEGY draft). Each MUST fire `step-active <marker>` before
its bash and `mark-step` after.

Skipping CrossAI (`--skip-crossai`) is enforced by `crossai-skip-guard.sh`
helper which logs `crossai.skipped` event + appends `--skip-crossai`
override-debt. The helper is the sole entry-point for the user_flag skip
audit-trail (do NOT call `vg-orchestrator override --flag --skip-crossai`
manually here — duplicate emission).

Subagent type for vg-reflector spawn is `general-purpose` (Important #4
fix) — no `agents/vg-reflector/SKILL.md` exists; `general-purpose` reads
the prompt template inline.
</HARD-GATE>

## §1. CrossAI skip enforcement (HARD-GATE — v2.5.2.9+)

```bash
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator step-active 4_crossai_review

source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/crossai-skip-guard.sh" 2>/dev/null || {
  echo "⚠ crossai-skip-guard.sh missing — không enforce được skip audit trail" >&2
}

SKIP_CAUSE=$(crossai_detect_skip_cause "${ARGUMENTS:-}" ".claude/vg.config.md" 2>/dev/null || echo "")

if [ -n "$SKIP_CAUSE" ]; then
  REASON_TEXT="scope CrossAI skip cho phase ${PHASE_NUMBER} (args=${ARGUMENTS:-none}). Override reason: ${OVERRIDE_REASON:-MISSING}"
  if ! crossai_skip_enforce "vg:scope" "$PHASE_NUMBER" "scope.4_crossai_review" "$SKIP_CAUSE" "$REASON_TEXT"; then
    echo "⛔ Guard chặn skip — exit. Chạy lại không có --skip-crossai hoặc đổi reason." >&2
    exit 1
  fi
  vg-orchestrator mark-step scope 4_crossai_review 2>/dev/null || true
  mkdir -p "${PHASE_DIR}/.step-markers" 2>/dev/null
  touch "${PHASE_DIR}/.step-markers/4_crossai_review.done"
  # Skip allowed → jump to §4 reflection
fi
```

If no skip → proceed to §2.

## §2. CrossAI scope review

```bash
echo "▸ CrossAI scope review starting — phase ${PHASE_NUMBER}"
echo "  AI thứ 2 sẽ review SPECS + CONTEXT decisions để bắt drift/contradiction."
echo "  Kết quả → ${PHASE_DIR}/crossai/result-*.xml + event crossai.verdict."
```

Prepare context file at `${VG_TMP}/vg-crossai-${PHASE_NUMBER}-scope-review.md`:

```markdown
# CrossAI Scope Review — Phase {PHASE_NUMBER}

Review the discussion output. Find gaps between SPECS requirements and CONTEXT decisions.

## Checklist
1. Every SPECS in-scope item has a corresponding CONTEXT decision
2. No CONTEXT decision contradicts a SPECS constraint
3. Success criteria achievable given decisions
4. No critical ambiguity unresolved
5. Out-of-scope items not accidentally addressed (scope creep)
6. Endpoint notes complete (method, auth, purpose)
7. Test scenarios cover happy path AND edge cases for every endpoint

## Verdict Rules
- pass: coverage ≥ 90%, no critical, score ≥ 7
- flag: coverage ≥ 70%, no critical, score ≥ 5
- block: coverage < 70%, OR any critical, OR score < 5

## Artifacts
---
[SPECS.md full content]
---
[CONTEXT.md full content]
---
```

Set `$CONTEXT_FILE`, `$OUTPUT_DIR="${PHASE_DIR}/crossai"`, `$LABEL="scope-review"`. Read and follow `.claude/commands/vg/_shared/crossai-invoke.md`.

## §3. Handle CrossAI findings

- **Minor:** log only.
- **Major/Critical:** present table:

  ```
  | # | Finding | Severity | CLI Source | Action |
  |---|---------|----------|------------|--------|
  | 1 | {issue} | major | Codex+Gemini | Re-discuss / Note / Ignore |
  ```

  For each major/critical:

  ```
  AskUserQuestion:
    header: "CrossAI Finding"
    question: "{finding description}"
    options:
      - "Re-discuss — open additional round to address this"
      - "Note — acknowledge and add to CONTEXT.md ## Deferred Ideas"
      - "Ignore — false positive, skip"
  ```

  - "Re-discuss" → open free-form round focused on finding → re-run STEP 5 validation on updated CONTEXT.md
  - "Note" → append to CONTEXT.md `## Deferred Ideas`
  - "Ignore" → log in DISCUSSION-LOG.md as "CrossAI finding ignored: {reason}"

## §3b. Cross-AI output contract gate (Phase 16 D-05)

```bash
if [[ "${ARGUMENTS:-}" =~ --crossai ]]; then
  CO_VAL="${REPO_ROOT}/.claude/scripts/validators/verify-crossai-output.py"
  if [ -x "$CO_VAL" ]; then
    ${PYTHON_BIN:-python3} "$CO_VAL" --phase "${PHASE_NUMBER}" \
        > "${VG_TMP:-${PHASE_DIR}/.vg-tmp}/crossai-output.json" 2>&1 || true
    CO_V=$(${PYTHON_BIN:-python3} -c "import json,sys; print(json.load(open(sys.argv[1])).get('verdict','SKIP'))" \
          "${VG_TMP:-${PHASE_DIR}/.vg-tmp}/crossai-output.json" 2>/dev/null)
    case "$CO_V" in
      PASS|WARN) echo "✓ P16 crossai-output: $CO_V" ;;
      BLOCK)
        echo "⛔ P16 crossai-output: BLOCK — see ${VG_TMP}/crossai-output.json" >&2
        echo "   Cross-AI inlined > 30 prose lines into a task body without <context-refs> ID, OR cross_ai_enriched flag missing in CONTEXT.md frontmatter." >&2
        echo "   Override: --skip-crossai-output (logs override-debt)" >&2
        if [[ ! "${ARGUMENTS:-}" =~ --skip-crossai-output ]]; then exit 1; fi
        ;;
      *) echo "ℹ P16 crossai-output: $CO_V" ;;
    esac
  fi
fi

vg-orchestrator mark-step scope 4_crossai_review
```

## §4. Bootstrap reflection (`4_5_bootstrap_reflection`)

Skip silently if `.vg/bootstrap/` absent. Otherwise:

```bash
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator step-active 4_5_bootstrap_reflection

if [ -d ".vg/bootstrap" ]; then
  REFLECT_STEP="scope"
  REFLECT_TS=$(date -u +%Y%m%dT%H%M%SZ)
  REFLECT_OUT="${PHASE_DIR}/reflection-${REFLECT_STEP}-${REFLECT_TS}.yaml"
  echo "📝 Running end-of-scope reflection..."

  bash scripts/vg-narrate-spawn.sh vg-reflector spawning "scope reflection (Haiku)"
fi
```

Then in AI runtime (only if `.vg/bootstrap/` exists):

`Agent(subagent_type="general-purpose", model="haiku", prompt=<see below>)`

> Important #4 fix: previous version used `subagent_type="vg-reflector"` but
> no `agents/vg-reflector/SKILL.md` exists (only `.claude/skills/vg-reflector/SKILL.md`,
> which is a Skill template — not a Claude subagent type). The Agent tool
> only resolves registered subagent types; an unknown type errors out. Use
> `general-purpose` and inline the reflector prompt from the skill template.

Build the prompt by reading `.claude/skills/vg-reflector/SKILL.md` (the
authoritative reflector workflow) and `commands/vg/_shared/reflection-trigger.md`
(the spawn template). Pass step="scope", phase="${PHASE_NUMBER}",
output="${REFLECT_OUT}". The subagent reads events.db + artifacts +
DISCUSSION-LOG.md (NEVER the AI transcript — echo-chamber risk) and writes
candidate L-IDs to `${REFLECT_OUT}`.

On return:

```bash
bash scripts/vg-narrate-spawn.sh vg-reflector returned "<N candidates drafted>"
```

If the spawn fails (subagent error / timeout):

```bash
bash scripts/vg-narrate-spawn.sh vg-reflector failed "reflection skipped — see stderr"
```

If `REFLECT_OUT` has candidates, show interactive y/n/e/s prompt — `y` → delegate to `/vg:learn --promote L-{id}`.

See `commands/vg/_shared/reflection-trigger.md` for full spawn template + interactive flow.

```bash
vg-orchestrator mark-step scope 4_5_bootstrap_reflection 2>/dev/null || true
```

## §5. TEST-STRATEGY draft (`4_6_test_strategy`)

```bash
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator step-active 4_6_test_strategy

TESTER_PRO_CLI="${REPO_ROOT}/.claude/scripts/tester-pro-cli.py"
[ -f "$TESTER_PRO_CLI" ] || TESTER_PRO_CLI="${REPO_ROOT}/scripts/tester-pro-cli.py"
if [ -f "$TESTER_PRO_CLI" ]; then
  "${PYTHON_BIN:-python3}" "$TESTER_PRO_CLI" \
    strategy generate --phase "${PHASE_NUMBER}" 2>&1 | sed 's/^/  D17: /' || true
fi
vg-orchestrator mark-step scope 4_6_test_strategy 2>/dev/null || true
```

> **Tại sao ở scope, không phải blueprint**: TEST-STRATEGY là *contract* /vg:blueprint dùng để validate (D18 test_type coverage gate). Phải tồn tại trước blueprint, nếu không blueprint không có gì để bind goal classification vào. Sinh dạng draft để user chỉnh trước khi blueprint chạy.

`--force` flag overwrites existing TEST-STRATEGY.md (default: preserve).

## Advance

Read `_shared/scope/close.md` next.
