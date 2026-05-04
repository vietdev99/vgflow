# Config gate — STEP 2 (decomposed mega-gate)

<HARD-GATE>
Original `0a_env_model_mode_gate` was 355 lines with 9 sub-prompts inline.
Decomposed into 5 sequential sub-steps. Each sub-step has its own marker,
its own `mark_step` call, and emits step-active + step-mark events.
Anti-forge guard refuses launch if all 3 axes (env/model/mode) empty after
sub-step 5. Interactive UX preserved — AskUserQuestion stays in main agent
(this is decomposition, not subagent extraction).
</HARD-GATE>

## Why decomposed?

Audit FAIL #10: a single 355-line step with 9 inline AskUserQuestion sub-prompts
is too large for clean step-marker tracking. Hooks emit one `step-active` event
for `0a_env_model_mode_gate`, then the AI plows through 9 conditional sub-prompts
with no granular evidence. If any sub-prompt is silently skipped, downstream gates
cannot tell which one. Decomposed: one marker per sub-prompt, each ≤150 lines.

## Sequence

Read these refs in order. Each sub-step writes its own marker via `mark_step`
and either emits a telemetry event or persists state for the next sub-step:

1. Read `backfill-env.md` (`0a_backfill_env_pref`) — one-time backfill of
   `preferred_env_for` into DEPLOY-STATE.json for legacy phases.
2. Read `detect-platform.md` (`0a_detect_platform_tools`) — heuristic platform
   detection (web/mobile-native/desktop/api-only) + tool availability matrix.
3. Read `enrich-env.md` (`0a_enrich_env_options`) — run `enrich-env-question.py`
   to decorate env options with deploy state evidence.
4. Read `confirm-env-model-mode.md` (`0a_confirm_env_model_mode`) —
   AskUserQuestion 3-question batch (env + model + mode) with pre-fills.
5. Read `persist-config.md` (`0a_persist_config`) — resolve answers, validate,
   write ROAM-CONFIG.json + `.tmp/0a-confirmed.marker`, emit
   `roam.config_confirmed` telemetry event.

## Skip conditions for the gate as a whole

Skip ALL 5 sub-steps when:

- `${ARGUMENTS}` contains `--non-interactive`, OR
- `VG_NON_INTERACTIVE=1`, OR
- `${ARGUMENTS}` contains ALL THREE: `--target-env=<v>` (or `--local`/`--sandbox`/`--staging`/`--prod`), `--model=<v>`, AND `--mode=<v>`

In skip mode the AI must:

1. Resolve env/model/mode from CLI flags (or hardcoded defaults `local/codex/spawn`).
2. Run `persist-config.md` directly to write ROAM-CONFIG.json + marker.
3. Emit `mark_step` for ALL 5 sub-step markers (with `--reason "skipped via --non-interactive"`).
4. Skip events for `roam.config_confirmed` only if also `--non-interactive` (per
   `runtime_contract.must_emit_telemetry.required_unless_flag`).

## Resume mode behavior (v2.42.10)

This gate ALWAYS fires regardless of `$ROAM_RESUME_MODE`. Prior runs (resume /
aggregate-only) populate `ROAM_PRIOR_ENV/MODEL/MODE` (set in 0aa) which are
surfaced as Recommended pre-fills in `confirm-env-model-mode.md`. User must
still confirm. Removing this prompt under resume was the v2.42.6-9 footgun:
users wanted to switch env/model/mode mid-stream but resume locked them in
silently.

When pre-fills exist, the AI MUST tag the matching option's label with
`" (Recommended — prior run)"`. Order options so the prior choice appears first.
