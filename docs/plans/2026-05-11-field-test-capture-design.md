# /vg:field-test — user-driven field test capture design

**Date:** 2026-05-11
**Status:** design approved, awaiting implementation plan
**Brainstorm session:** Q1-Q7 answered, 5 design sections validated

## Goal

Add a new VGFlow skill `/vg:field-test` that lets the human operator manually roam the deployed app in a browser while AI silently captures multi-source observability data (browser console + network + user behaviour + per-view notes + correlated API server logs). On Stop, AI auto-analyzes the bundle and writes findings into `KNOWN-ISSUES.json` so downstream `/vg:review` and `/vg:test` consume them.

Distinct from existing `/vg:roam`:
- `/vg:roam` = AI-driven; spawns executors that auto-replay lenses against discovered surfaces.
- `/vg:field-test` = USER-driven; human exploration with passive AI recording. Field test, not auto-replay.

## Architecture

3-tier:

```
AI Orchestrator (skill body)
   ↓ inject overlay JS                    ↑ poll [VG_FT] console markers
Browser (MCP playwright1)
   floating overlay top-right: Start / Stop / Mark+Note / preset selector
   continuous capture buffers (console+network+nav+clicks) ring-buffered
   on Mark click: modal textarea → submit → console.log('[VG_FT] mark <json>')
   ↑ wall-clock correlate
Per-source API log tails (config-driven; type=file or type=command)
   each tail → .vg/field-test/<sid>/api-<n>.log with ISO timestamps
```

**Storage:** `.vg/field-test/<sid>/` (gitignored). Mirror to `dev-phases/<N>/field-test/<sid>/` when `--phase=N` flag passed.

**Session id:** `ft-<ts>` phase-less default, `ft-p<N>-<ts>` when bound.

## Components

| File | Role |
|---|---|
| `commands/vg/field-test.md` | Skill entry (frontmatter + step sequence + runtime_contract). allowed-tools includes all `mcp__playwright1__*`. Steps 0_preflight → 7_analyze. Mirror to `.claude/`. |
| `scripts/field-test/overlay.js` | Self-contained IIFE injected via `browser_evaluate`. Renders floating panel + handles Start/Stop/Mark, monkeypatches console/fetch/XHR/history. Emits `console.log('[VG_FT] ...')` markers. Namespaced `__VG_FT_*`. |
| `scripts/field-test/tail-source.sh` | Per-source tail wrapper. `--type file --target <path>` runs `tail -F`; `--type command --target "cmd"` runs `eval cmd`. Prepends ISO ts. Traps SIGTERM. |
| `scripts/field-test/build-bundle.py` | Stop-time bundle assembler. Loads streams, applies redaction regex, correlates each Mark with ±N-second windows across all sources, writes `manifest.json` + per-Mark `marks.jsonl`. |
| `agents/vg-field-test-analyzer/SKILL.md` | Subagent. Reads bundle → writes `FIELD-REPORT.md` + appends `.vg/KNOWN-ISSUES.json`. Severity heuristic deterministic; narrative LLM-driven. |
| `schemas/field-test-session.v1.json` | JSON Schema for session.json + marks.jsonl. Validates required fields. |
| `vg.config.md` field_test block | api_log_sources, default_preset, default_redaction, default_base_url, mark_window_sec, screenshot_quality, session_max_size_mb, max_session_hours. |

**MARKER_TO_AUTO_EVENT extension** (`scripts/vg-orchestrator/__main__.py`): add `("field-test", "complete") → "field_test.session_completed"`.

## Data flow

T0 user → `/vg:field-test [--phase=N] [--preset=quick|standard|deep] [--redact=<regex>] [--non-interactive]`.

| Step | Marker | Detail |
|---|---|---|
| 0 | `0_preflight` | Verify MCP playwright1, base_url resolvable, sources configured (or AskUserQuestion to configure inline) |
| 1 | `1_resolve_config` | 3-question AskUserQuestion: preset, redaction regex, sources confirm. Write `session.json`. |
| 2 | `2_launch_browser` | `mcp__playwright1__browser_navigate(base_url)` |
| 3 | `3_inject_overlay` | Read `overlay.js`, `browser_evaluate(it)`. State `window.__VG_FT_STATE = {status:'idle', marks:[]}` |
| 4 | `4_wait_start` | Poll `browser_console_messages` 2s/iter for `[VG_FT] start`. On hit: spawn N tail processes, write PIDs to session.json, emit `field_test.session_started` |
| 5 | `5_capture_loop` | Poll loop. On `[VG_FT] mark <n>`: `browser_evaluate` reads `state.marks[n]`, take_screenshot, browser_snapshot, read recent console+network, append `marks.jsonl` entry, emit `field_test.mark_recorded` |
| 6 | `6_stop_finalize` | On `[VG_FT] stop` OR timeout/size cap: kill tails (TERM → 9 fallback), run `build-bundle.py`, write manifest, emit `field_test.session_stopped` |
| 7 | `7_analyze` | Spawn `vg-field-test-analyzer` subagent. Bundle → `FIELD-REPORT.md` + `KNOWN-ISSUES.json` appended. Emit `field_test.analysis_completed`. Mirror to `dev-phases/<N>/field-test/<sid>/` if phase-bound. |
| 8 | `complete` | Auto-emit `field_test.session_completed` via MARKER_TO_AUTO_EVENT (v3.6.0 path) |

**Per-Mark bundle JSON** (validates against `field-test-session.v1.json`):
- core: n, ts, url, nav_chain[], referrer, user_note, screenshot, snapshot, viewport, click_target, console_window[], network_window[], api_log_correlated{source: [lines]}
- preset extras: perf (LCP/FCP/CLS/TTFB) | a11y_violations[] | auth_state | storage_diff | form_values (Deep only, PII risk)

**Polling backpressure:** 2s base, throttle to 5s when round >1.5s. Hard cap session at `field_test.max_session_hours` (default 4h).

**Crash recovery:** session.json written before any I/O. `vg:field-test --resume=<sid>` re-injects overlay, reuses tails state, continues poll.

## Error handling

Pre-start failures fail loud with diagnostic + repair hint. Mid-session failures degrade gracefully (tail dies → respawn 3x then continue without; overlay state wiped on reload → auto re-inject; bad mark JSON → skip + log to `errors.jsonl`; disk fills → force-stop pipeline). Stop/analysis failures preserve raw bundle (BLOCK only when analyzer non-zero — user can manually triage).

Concurrency: 1 active session per project via `.vg/field-test/.active` lock; subsequent invocations refuse with `--resume` hint.

Privacy: default redaction regex `password|token|secret|api[_-]?key|email|phone` applied to all log streams + form values. Screenshots NOT redacted by default (opt-in future). `.gitignore` ensures `.vg/field-test/` not committed. Bundle manifest records `redaction_applied` for audit.

Telemetry events (hash-chained via vg-orchestrator emit-event):
```
field_test.session_started     {sid, phase, preset, sources_count}
field_test.mark_recorded       {sid, n, url, has_note}
field_test.session_stopped     {sid, mark_count, duration_sec, bundle_size_mb}
field_test.session_aborted     {sid, reason}
field_test.overlay_reinjected  {sid, count}
field_test.analysis_completed  {sid, findings_count, severity_breakdown}
field_test.session_completed   (auto via MARKER_TO_AUTO_EVENT)
```

## Testing strategy

~25-30 tests. ~6 Linux-only functional. Rest cross-platform content.

| Bucket | Examples |
|---|---|
| Skill structure | Frontmatter parse, runtime_contract markers + must_emit_telemetry, allowed-tools includes mcp__playwright1__* |
| Config schema | `field_test` block validates; missing api_log_sources → AskUserQuestion |
| Overlay JS | `node --check` syntax pass; smoke for `__VG_FT_INIT` symbol |
| Session schema | jsonschema draft-07 happy + invalid cases |
| Bundle correlation | Seed streams with known ts, assert correlated window matches expected ±cutoff |
| Redaction | Default pattern strips known fields; bad regex falls back |
| Mirror byte-identity | canonical / .claude mirror for skill md + scripts |
| Tail-source.sh | File mode + command mode + SIGTERM cleanly (Linux) |
| Bundle pipeline | Synthetic bundle → manifest + correlated marks (Linux) |
| Browser integration | Behind `VG_RUN_BROWSER_TESTS=1`. Overlay render + Start/Stop markers + Mark flow + reload re-inject (Linux/Mac with headless playwright) |
| Analyzer | Fixture bundle → FIELD-REPORT.md + KNOWN-ISSUES schema |
| Severity heuristic | 5xx in window → HIGH; 4xx → MEDIUM; visual-only note → LOW; unhandled exception → HIGH |
| Static lint | Overlay no eval/no cross-origin fetch; telemetry names match contract |

## Open / deferred

- Voice annotation (SpeechRecognition) — deferred to v2 (out of MVP scope).
- Auto-screenshot interval (visual timeline) — deferred; opt-in heavy disk.
- DOM mutation observer — deferred.
- WebSocket frame capture — deferred.
- `--blur-faces` for screenshots — deferred.
- Multi-tab session — deferred (single tab v1).

## Acceptance criteria

1. User can run `/vg:field-test` (no args) → AI launches browser w/ overlay; user clicks Start, roams, Marks views with notes, clicks Stop.
2. After Stop, `.vg/field-test/<sid>/FIELD-REPORT.md` exists with per-Mark sections + timeline + suspect file hints.
3. `.vg/KNOWN-ISSUES.json` has 1 new entry per Mark with severity + url + note + evidence paths.
4. `field_test.session_started`, `mark_recorded` (× N marks), `session_stopped`, `analysis_completed`, `session_completed` events chain-verified in `.vg/events.db`.
5. `--phase=N` mirrors bundle to `dev-phases/N/field-test/<sid>/`.
6. Default redaction applied (verified by grep of bundle for `password=` / `token=` returning zero matches against test fixture containing those).
7. Concurrent invocation while session active → BLOCK with `--resume` hint.
8. Browser crash mid-session → bundle still produced from captured-so-far data with `aborted=true` flag.

## Next

Invoke `superpowers:writing-plans` to break this design into bite-sized executable tasks.
