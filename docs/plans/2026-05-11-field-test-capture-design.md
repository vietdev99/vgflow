# /vg:field-test — user-driven field test capture design

**Date:** 2026-05-11
**Revision:** v2 (post-Codex review)
**Status:** design v2 supersedes v1; v1 had 10 critical findings concentrated in privacy + concurrency + scope
**Brainstorm session:** Q1-Q7 answered; v2 addresses Codex GPT-5.5 audit findings

## Goal

Add a new VGFlow skill `/vg:field-test` that lets the human operator manually roam the deployed app in a browser while AI silently captures multi-source observability data (browser console + network + user behaviour + per-view notes + correlated API server logs). On Stop, AI auto-analyzes the bundle and writes findings into `KNOWN-ISSUES.json` so downstream `/vg:review` and `/vg:test` consume them.

Distinct from existing `/vg:roam`:
- `/vg:roam` = AI-driven; spawns executors that auto-replay lenses against discovered surfaces.
- `/vg:field-test` = USER-driven; human exploration with passive AI recording. Field test, not auto-replay.

## v1 scope cuts (per Codex review §8 + §10)

Dead config + half-built features removed from v1; deferred to v2:

| Feature | Reason | Defer to |
|---|---|---|
| `quick` + `deep` presets | No preset-driven branching anywhere; pure dead enum | v2 |
| `--resume=<sid>` flag | Declared 3 places, implemented 0 (overlay re-inject + tail PID rewire missing) | v2 |
| Mirror to `dev-phases/<N>/field-test/<sid>/` | Commit-or-ignore policy unresolved; dev-phases is committed → leaks bundles | v2 (with explicit audit-trail toggle) |
| `--non-interactive` flag | User-driven skill has no useful non-interactive mode | drop entirely |
| Crash recovery / aborted-bundle acceptance test | No detector implemented for crash path | v2 |
| Voice annotation, visual timeline, DOM mutation observer, WS capture, blur-faces, multi-tab | Already deferred in v1; reconfirm | v2+ |

v1 ships: single preset (`standard`), phase-less + `--phase=N` tagging (no mirror), 1 session/project, redact-at-capture, BLOCK on browser crash with raw bundle preserved (no aborted-flag bundle).

## Architecture

3-tier, but the orchestrator's sync mechanism is tightened:

```
AI Orchestrator (skill body)
   ↓ inject overlay JS
   ↑ browser_evaluate poll: state.marks.length + state.status (NOT console messages)
   ↑ browser_console_messages (offset-tracked) for Start/Stop edge events only
Browser (MCP playwright1)
   floating overlay top-right: Start / Stop / Mark+Note
   continuous capture buffers (console+network+nav+clicks) ring-buffered
   on Mark click: modal textarea → submit → window.__VG_FT_STATE.marks.push(entry)
                                          + console.log('[VG_FT] mark') as notification only
Per-source API log tails (config-driven; type=file or type=command)
   each tail → python3 -c <inline-script> ← redact at capture time
            → .vg/field-test/<sid>/api-<n>.log with ISO timestamps (Python-generated, portable)
```

**Sync redesign (Codex review §1 + §3):**

The v1 console-as-bus was broken — `browser_console_messages` is a snapshot reader that replays the full buffer every call. Same `[VG_FT] mark` message would fire N times.

v2 uses two distinct mechanisms:
- **State polling for marks**: AI runs `browser_evaluate(() => ({len: __VG_FT_STATE.marks.length, status: __VG_FT_STATE.status}))` every 2s. Compares `len` against last-seen `len_consumed`. New marks = `[len_consumed .. len)` slice, fetched via single `browser_evaluate(() => __VG_FT_STATE.marks.slice(N))`. Deterministic, no string parsing, no replay.
- **Console messages for edge events only**: Used solely for `[VG_FT] start` / `[VG_FT] stop` boundary detection (idempotent — orchestrator state tracks "did we see start yet"). Console messages also harvested into raw stream at Stop for retention, with offset tracking.

**Storage:** `.vg/field-test/<sid>/` (gitignored). v1 has no `dev-phases/<N>/` mirror.

**Session id:** `ft-<ts>` phase-less default, `ft-p<N>-<ts>` when bound (phase is only a tag; no separate dir).

## Components

| File | Role |
|---|---|
| `commands/vg/field-test.md` | Skill entry. Frontmatter + 9-step sequence + runtime_contract. Mirror to `.claude/`. |
| `scripts/field-test/overlay.js` | Self-contained IIFE. Renders panel, monkeypatches console/fetch/XHR/history/clicks. Pushes mark entries to `window.__VG_FT_STATE.marks[]` (canonical). Console.log markers are notifications only. Namespaced `__VG_FT_*`. |
| `scripts/field-test/tail-source.sh` | Per-source tail wrapper. Pipes through `scripts/field-test/redact-stream.py` (capture-time redaction) before writing to disk. Uses Python ISO timestamp (no `date %3N` portability bug). Traps SIGTERM. |
| `scripts/field-test/redact-stream.py` | Line-oriented stdin→stdout redactor. Loads regex from `--pattern <regex>`. Applied at tail capture time AND inside build-bundle.py for windowed correlation. Single source of truth for redaction. |
| `scripts/field-test/build-bundle.py` | Stop-time bundle assembler. Loads streams, correlates ±N-sec windows per Mark, runs each window line through `redact-stream.py` (idempotent), writes `manifest.json` + per-Mark `marks.jsonl`. |
| `agents/vg-field-test-analyzer/SKILL.md` | Subagent. Wraps `analyze.py` deterministic core, adds LLM narrative on HIGH/MEDIUM marks. |
| `scripts/field-test/analyze.py` | Deterministic severity heuristic + KNOWN-ISSUES append (robust to corrupt prior JSON: backup + warn, do NOT silently wipe). |
| `schemas/field-test-session.v1.json` | JSON Schema for session.json + marks.jsonl. Validates required fields. |
| `vg.config.md` field_test block | api_log_sources, redaction (single value), default_base_url, mark_window_sec, screenshot_quality, session_max_size_mb, max_session_hours. NO preset field — v1 only ships `standard`. |

**MARKER_TO_AUTO_EVENT extension** (`scripts/vg-orchestrator/__main__.py`): `("field-test", "complete") → "field_test.session_completed"`.

## Data flow

T0 user → `/vg:field-test [--phase=N] [--redact=<regex>] [--base-url=<url>]`.

| Step | Marker | Detail |
|---|---|---|
| 0 | `0_preflight` | Verify MCP playwright1, base_url resolvable, sources configured. **Atomic lock**: `mkdir .vg/field-test/.active` (fails iff exists). If lock present, BLOCK with manual-cleanup hint. |
| 1 | `1_resolve_config` | 2-question AskUserQuestion: redaction regex confirm, sources confirm. Write `session.json`. |
| 2 | `2_launch_browser` | `mcp__playwright1__browser_navigate(base_url)` |
| 3 | `3_inject_overlay` | Read `overlay.js`, call `mcp__playwright1__browser_evaluate({ function: "() => { OVERLAY_JS_CONTENTS }" })`. Verify by `browser_evaluate(() => typeof window.__VG_FT_INIT === 'function')`. **Concrete call shape documented in skill body, not hand-waved.** |
| 4 | `4_wait_start` | Poll `browser_console_messages` with offset tracking for `[VG_FT] start` edge. On hit: spawn N tail processes (each piped through `redact-stream.py`), write PIDs to session.json, emit `field_test.session_started`. |
| 5 | `5_capture_loop` | Poll every 2s: `browser_evaluate(() => ({len: __VG_FT_STATE.marks.length, status: __VG_FT_STATE.status}))`. If `len > last_consumed`: fetch slice `[last_consumed..len)`, for each new mark: `browser_take_screenshot --filename <session>/marks/<n>.png`, `browser_snapshot --filename <session>/marks/<n>.snapshot.yml`, append raw entry to `marks.raw.jsonl`, emit `field_test.mark_recorded`. Throttle 5s if iter >1.5s. Hard cap on size + wall-clock (enforced by `check-quota.py` called each iter). |
| 6 | `6_stop_finalize` | On `[VG_FT] stop` OR timeout/size cap: dump remaining overlay buffers via `browser_evaluate(() => __VG_FT_STATE.buffer)`, kill tails (TERM → 5s grace → KILL), run `build-bundle.py`, write manifest, emit `field_test.session_stopped`. |
| 7 | `7_analyze` | Spawn `vg-field-test-analyzer` subagent. Subagent runs `analyze.py` then augments report. Emit `field_test.analysis_completed`. |
| 8 | `complete` | Auto-emit `field_test.session_completed` via MARKER_TO_AUTO_EVENT. Remove lock directory. |

**Per-Mark bundle JSON** (validates against `field-test-session.v1.json`):
- core: n, ts, url, nav_chain[], referrer, user_note, screenshot_path, snapshot_path, viewport, click_target, console_window[], network_window[], api_log_correlated{source: [lines]}
- v1 does NOT include preset extras (perf/a11y/auth/storage). Deferred to v2 when presets ship.

**Backpressure + caps:**
- Poll base 2s, throttle 5s when iter >1.5s.
- Per-iter quota check: `du -s .vg/field-test/<sid>/` ≤ `session_max_size_mb`; wall-clock ≤ `max_session_hours`. Exceed → force Stop with reason in session.json.
- Atomic lock: `mkdir .vg/field-test/.active` (POSIX O_EXCL semantics). v1 documents Windows behavior: `os.mkdir` raises `FileExistsError` on existing dir → BLOCK; cleanup helper script `scripts/field-test/release-lock.py` for stuck-lock recovery.

**No crash recovery in v1.** Browser crash mid-session → orchestrator BLOCK with raw bundle path. Operator can manually run `build-bundle.py` + `analyze.py` on the raw streams; FIELD-REPORT.md still produced. Lock auto-released on orchestrator exit via `trap EXIT` in skill bash blocks.

## Error handling

Pre-start failures fail loud with diagnostic + repair hint.

Mid-session failures degrade per documented matrix (unchanged from v1 §3):
- Tail dies → respawn 3× with 1s backoff (**implemented in v2 task 7 step 5**, not deferred), then log `tail.dead` + continue without that source.
- Overlay state wiped on reload → re-inject **with marker-acknowledgment**: orchestrator counts marks seen pre-reload; post-reload `last_consumed` reset to 0 ONLY for marks emitted after reload (new `state.reload_epoch` field in overlay JS distinguishes).
- Bad mark JSON → skip + log to `errors.jsonl`, continue.
- Disk fills (size cap exceeded) → force Stop pipeline.
- Browser closed → orchestrator detects via `browser_evaluate` exception, BLOCK, leave lock + raw streams for manual triage.

Stop / analysis failures preserve raw bundle:
- `build-bundle.py` exception → write `bundle.partial=true` flag, raise BLOCK with raw path. Analyzer skipped.
- Analyzer non-zero → FIELD-REPORT.md not produced; BLOCK with raw bundle path so user can run analyze manually.
- **KNOWN-ISSUES.json corruption**: analyze.py NEVER silently wipes. On `json.JSONDecodeError`, write `KNOWN-ISSUES.corrupt-<ts>.json.bak`, emit `analyzer.known_issues_corrupted` event, abort append with diagnostic.

Concurrency: 1 session/project via atomic `mkdir .vg/field-test/.active`. No `--resume` in v1.

Privacy:
- **Redact at capture time** for API tail (every line through `redact-stream.py` before disk).
- **Redact at build time** for browser-side streams (in-memory until Stop, then redacted as part of bundle assembly).
- Default regex covers what v2 design promised but v1 dropped:
  ```
  password|token|secret|api[_-]?key|email|phone|bearer\s+[A-Za-z0-9._\-]+|authorization:\s*\S+
  ```
- Match modes built into `redact-stream.py`:
  - `<key>=<value>` (URL query / cli arg form)
  - `<key>: <value>` / `<key>:<value>` (header form)
  - `"<key>": "<value>"` (JSON body form)
  - bare `Bearer <token>` (Authorization header value form)
- Tests for each form, plus a `Bearer eyJhbGc...` regression case.
- Screenshots NOT redacted by default. **HARD-GATE banner** at session start warns user: *"Screenshots are NOT redacted. Do not navigate to credential/payment pages during this session unless you are testing them intentionally."*
- `.gitignore` ensures `.vg/field-test/` not committed. v1 has no `dev-phases/<N>/` mirror so no committed bundle risk.
- Bundle manifest records `redaction_applied` regex + `redaction_locations: [capture, build]` for audit.

**Telemetry contract reconciliation (Codex review §6):**

Skill `runtime_contract.must_emit_telemetry` declares the MINIMUM set the verifier enforces. Plan must reconcile to one of:

Option A (chosen for v2): declare all guaranteed events, mark optional ones with `required_unless_flag`.

```yaml
must_emit_telemetry:
  - event_type: "field_test.session_started"            # ALWAYS
  - event_type: "field_test.session_stopped"            # ALWAYS
  - event_type: "field_test.analysis_completed"         # ALWAYS
  - event_type: "field_test.mark_recorded"
    required_unless_flag: "--allow-zero-marks"          # only if any mark recorded
```

`session_aborted` and `overlay_reinjected` are best-effort (not contract-required, but emitted when conditions trigger).

`session_completed` is auto-emitted via MARKER_TO_AUTO_EVENT (Codex parity v3.6.0 path) — already covered by orchestrator-side event; not duplicated in skill contract.

## Testing strategy

~30 tests. Real behavioral tests, not substring tautologies.

| Bucket | Examples |
|---|---|
| Skill structure | Frontmatter parse, runtime_contract markers + must_emit_telemetry match plan/data flow, allowed-tools includes mcp__playwright1__* |
| Config schema | `field_test` block validates; missing api_log_sources → AskUserQuestion (NOT crash) |
| Overlay JS | `node --check` syntax. Functional smoke (jsdom OR puppeteer behind `VG_RUN_BROWSER_TESTS`): inject overlay → click Start programmatically → assert `window.__VG_FT_STATE.status === 'recording'` → simulate Mark → assert `__VG_FT_STATE.marks.length === 1`. |
| Session schema | jsonschema draft-07 happy + invalid cases (missing sid, bad ts, bad sources type). |
| **Redaction** | Each match-mode tested separately: `<key>=<value>`, `<key>: <value>`, JSON body `{"<key>": "<value>"}`, bare `Bearer <jwt>`, `Authorization: Bearer xxx`. Plus a fallback test where bad user regex raises `re.error` → falls back to default. Plus an idempotency test: redact(redact(x)) == redact(x). |
| Bundle correlation | Seed streams with known ts, assert correlated window matches expected ±cutoff. Edge cases: empty stream, only-LATER-than-mark, only-EARLIER-than-mark, naive (non-Z) timestamp lines (assert filtered + warning logged, NOT silent drop). |
| Mirror byte-identity | canonical / .claude mirror for skill md + all scripts. |
| Tail-source.sh | File mode + command mode + SIGTERM cleanly (Linux + macOS — `date` portability covered by Python wrapper). Plus redact-stream pipe verification (write `password=abc` to source, assert `[REDACTED]` appears in out file before bundle build). |
| Bundle pipeline | Synthetic bundle → manifest + correlated marks (Linux). Plus 0-marks session test. Plus partial-write recovery test (truncate `marks.raw.jsonl` mid-line, builder must report `bundle.partial=true` not crash). |
| Analyzer | Fixture bundle → FIELD-REPORT.md + KNOWN-ISSUES schema. Plus KNOWN-ISSUES corruption test (analyzer must NOT wipe). Plus dedupe test (re-run on same session → idempotent). |
| Severity heuristic | 5xx → HIGH; 4xx → MEDIUM; visual-only → LOW; unhandled exception → HIGH. Plus mixed (5xx + 4xx → HIGH dominates). |
| Atomic lock | `mkdir` race test: 2 concurrent invocations → exactly 1 wins, second BLOCKs with specific exit code. |
| Quota enforcement | Seed session dir to exceed `session_max_size_mb` → quota check forces Stop with reason persisted. |
| Static lint | Overlay no eval/no cross-origin fetch; telemetry names match contract; redaction regex compiles. |

**Removed from v1 (Codex review §2)**: substring-only assertions that pass against any string containing the literal. Every test asserts behavior or structure, not lexical presence alone.

## Open / deferred (unchanged from v1)

- Voice annotation (SpeechRecognition).
- Auto-screenshot interval (visual timeline).
- DOM mutation observer.
- WebSocket frame capture.
- `--blur-faces` for screenshots.
- Multi-tab session.

**Newly deferred per v2 scope cuts:**
- `quick` / `deep` presets.
- `--resume=<sid>` flag.
- `dev-phases/<N>/field-test/<sid>/` mirror.
- Crash-recovery aborted-bundle flow.
- `--non-interactive` flag (dropped — not deferred).

## Acceptance criteria

1. User can run `/vg:field-test` (no args) → AI launches browser w/ overlay; user clicks Start, roams, Marks views with notes, clicks Stop.
2. After Stop, `.vg/field-test/<sid>/FIELD-REPORT.md` exists with per-Mark sections + timeline + suspect file hints.
3. `.vg/KNOWN-ISSUES.json` has 1 new entry per Mark with severity + url + note + evidence paths. Re-running analyzer on same session → idempotent (no duplicates).
4. `field_test.session_started`, `mark_recorded` (× N marks, if any), `session_stopped`, `analysis_completed`, `session_completed` events chain-verified in `.vg/events.db`.
5. `--phase=N` tags `session.json.phase=<N>` and `KNOWN-ISSUES` entries include `phase=<N>`. NO file mirror.
6. Default redaction applied at capture time for API tail + at build time for browser streams. Verification: bundle grep for `password=` / `token=` / `Bearer eyJ` returns zero matches against test fixture containing those forms.
7. Concurrent invocation while session active → BLOCK with manual-cleanup hint (rm `.vg/field-test/.active` after confirming no live session).
8. Browser crash mid-session → orchestrator BLOCK with raw bundle path. v1 does NOT auto-produce FIELD-REPORT from crash; that's manual triage.
9. **HARD-GATE banner** displayed at session start warning that screenshots are not redacted.
10. Atomic lock: 2 concurrent `/vg:field-test` invocations → exactly 1 wins.

## Risk register (post-Codex review)

| Risk | Mitigation in v1 | Residual |
|---|---|---|
| Poll loop duplicates marks | State polling via `browser_evaluate` instead of console replay; offset tracking | None for marks; small for Start/Stop edges (idempotent state check) |
| Raw API log disk exposure | Redact at capture time via pipe | Console/network/clicks/nav in browser memory until Stop — gone if browser killed mid-session |
| Regex misses real-world creds | Multi-form regex + idempotent re-application at build | Custom user creds (CSRF tokens, app-specific) not covered; user can override redact pattern |
| Lock TOCTOU | `mkdir` atomic primitive | Manual cleanup if orchestrator crashed without releasing |
| Cross-platform `date %3N` | Python timestamp wrapper | None |
| Screenshot leaks credentials | HARD-GATE banner + user education | User must respect banner; no technical enforcement in v1 |
| KNOWN-ISSUES corruption silent | Backup-on-decode-error + abort append + emit telemetry | Operator must triage corrupt file manually |

## Next

Invoke `superpowers:writing-plans` to break v2 design into bite-sized executable tasks with TDD discipline tightened per Codex review §2.
