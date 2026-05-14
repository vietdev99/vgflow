**Review mode:** Direct. L3 Team default.

### Finding 1: Test-Spec Codegen Is Pseudo-Agent Only
**Q**: 2  
**File:line**: [commands/vg/test-spec.md:432](D:/Workspace/Messi/Code/vgflow-repo/commands/vg/test-spec.md:432), [commands/vg/test-spec.md:451](D:/Workspace/Messi/Code/vgflow-repo/commands/vg/test-spec.md:451)  
**Purpose**: spawn `vg-test-codegen`, write Playwright specs and `CODEGEN-MANIFEST.json`.  
**Actual**: markdown shows `Agent(...)` text, then marks `4_codegen`; no executable spawn, no manifest validation.  
**Gap**: agent call can be narrated, marker still fires.  
**Severity**: critical  
**Fix**: replace pseudo-call with real provider dispatch plus required output check: spec count, manifest schema, per-goal/lens coverage.

### Finding 2: Test-Spec Can Mark PASS After Failed Run-Complete
**Q**: 6  
**File:line**: [commands/vg/test-spec.md:521](D:/Workspace/Messi/Code/vgflow-repo/commands/vg/test-spec.md:521), [commands/vg/test-spec.md:538](D:/Workspace/Messi/Code/vgflow-repo/commands/vg/test-spec.md:538)  
**Purpose**: complete only after deep specs and codegen artifacts exist.  
**Actual**: writes `verdict=PASS`, emits `test_spec.completed`, then runs `run-complete --outcome PASS ... || true`.  
**Gap**: runtime contract failure can be swallowed while user sees complete.  
**Severity**: critical  
**Fix**: remove `|| true`; set PASS only after `run-complete` returns 0.

### Finding 3: Deep Test-Spec Generation Is Static Scaffold
**Q**: 4  
**File:line**: [scripts/generate-deep-test-specs.py:421](D:/Workspace/Messi/Code/vgflow-repo/scripts/generate-deep-test-specs.py:421), [scripts/test_spec_ai_expander.py:426](D:/Workspace/Messi/Code/vgflow-repo/scripts/test_spec_ai_expander.py:426), [scripts/validators/verify-deep-test-specs.py:198](D:/Workspace/Messi/Code/vgflow-repo/scripts/validators/verify-deep-test-specs.py:198)  
**Purpose**: produce semantic lifecycle contracts.  
**Actual**: regex scans surfaces, writes baseline artifacts and localizer prompt; validator checks files and emitted goals only.  
**Gap**: omitted goals are not compared against full `TEST-GOALS`; localizer prompt is prepared, not executed.  
**Severity**: high  
**Fix**: add full goal parity gate: every automatable goal must be emitted, skipped with reason, or block.

### Finding 4: Review Browser Discovery Has Pseudo-Agent Spawn Proof
**Q**: 5  
**File:line**: [commands/vg/_shared/review/api-and-discovery.md:787](D:/Workspace/Messi/Code/vgflow-repo/commands/vg/_shared/review/api-and-discovery.md:787), [commands/vg/_shared/review/api-and-discovery.md:1128](D:/Workspace/Messi/Code/vgflow-repo/commands/vg/_shared/review/api-and-discovery.md:1128), [commands/vg/review.md:65](D:/Workspace/Messi/Code/vgflow-repo/commands/vg/review.md:65)  
**Purpose**: tour every view with navigator plus scanner agents.  
**Actual**: docs describe `Agent(...)`; telemetry fires before spawn; contract only requires `scan-*.json` glob count >= 1.  
**Gap**: “12 views toured” not proven by per-view browser trace, screenshots, or scan count matching assignments.  
**Severity**: critical  
**Fix**: require `nav-discovery.actual_views` count equals scan artifact count, each with browser action trace and current-run provenance.

### Finding 5: Runtime Map Merge Is Prose, Not Deterministic Execution
**Q**: 4  
**File:line**: [commands/vg/_shared/review/lens-and-findings.md:260](D:/Workspace/Messi/Code/vgflow-repo/commands/vg/_shared/review/lens-and-findings.md:260), [commands/vg/_shared/review/lens-and-findings.md:373](D:/Workspace/Messi/Code/vgflow-repo/commands/vg/_shared/review/lens-and-findings.md:373), [commands/vg/_shared/review/close.md:93](D:/Workspace/Messi/Code/vgflow-repo/commands/vg/_shared/review/close.md:93)  
**Purpose**: build `RUNTIME-MAP.json` from observed browser scans.  
**Actual**: merge/build steps are instructions, not a script; close says “Use Glob”; contract min size is 80 bytes.  
**Gap**: small fabricated JSON can satisfy shape while view/goal evidence is absent.  
**Severity**: critical  
**Fix**: add `merge-runtime-map.py` plus schema/provenance validator requiring per-view scan hash, action count, selector count, goal sequence evidence.

### Finding 6: Blocking Gates Are Prompt-Only In Review Close
**Q**: 7  
**File:line**: [scripts/lib/blocking-gate-prompt.sh:16](D:/Workspace/Messi/Code/vgflow-repo/scripts/lib/blocking-gate-prompt.sh:16), [commands/vg/_shared/review/close.md:490](D:/Workspace/Messi/Code/vgflow-repo/commands/vg/_shared/review/close.md:490), [commands/vg/_shared/review/close.md:691](D:/Workspace/Messi/Code/vgflow-repo/commands/vg/_shared/review/close.md:691)  
**Purpose**: block on matrix/evidence/provenance/mutation failures.  
**Actual**: `blocking_gate_prompt_emit` prints JSON and returns 0; callers do not resolve choice or exit.  
**Gap**: failed gates can fall through to `run-complete`.  
**Severity**: critical  
**Fix**: caller must branch on prompt result; default non-resolution must `exit 1`.

### Finding 7: Matrix INTENT Step Is Marker-Only
**Q**: 6  
**File:line**: [commands/vg/_shared/review/matrix-intent.md:31](D:/Workspace/Messi/Code/vgflow-repo/commands/vg/_shared/review/matrix-intent.md:31), [commands/vg/_shared/review/matrix-intent.md:47](D:/Workspace/Messi/Code/vgflow-repo/commands/vg/_shared/review/matrix-intent.md:47)  
**Purpose**: write `MATRIX-INTENT.json` with READY/BLOCKED/NOT_SCANNED.  
**Actual**: only executable line is `mark-step`.  
**Gap**: matrix can be claimed without artifact.  
**Severity**: high  
**Fix**: add real generator and put `MATRIX-INTENT.json` in `must_write`.

### Finding 8: Lens Probe Has Explicit Skip And Soft Failure Paths
**Q**: 7  
**File:line**: [commands/vg/_shared/review/lens-and-findings.md:23](D:/Workspace/Messi/Code/vgflow-repo/commands/vg/_shared/review/lens-and-findings.md:23), [commands/vg/_shared/review/lens-and-findings.md:151](D:/Workspace/Messi/Code/vgflow-repo/commands/vg/_shared/review/lens-and-findings.md:151), [commands/vg/_shared/review/lens-and-findings.md:196](D:/Workspace/Messi/Code/vgflow-repo/commands/vg/_shared/review/lens-and-findings.md:196)  
**Purpose**: run recursive lens probes and enforce coverage.  
**Actual**: eligibility fail writes `.recursive-probe-skipped.yaml`; skip bypasses coverage; coverage failure emits prompt only.  
**Gap**: “12 lens probes” can reduce to no probes plus skip marker.  
**Severity**: high  
**Fix**: require explicit override debt for skip; coverage failure must block unless resolved.

### Finding 9: CRUD Findings Lane Skips Then Marks Done
**Q**: 7  
**File:line**: [commands/vg/_shared/review/lens-and-findings.md:666](D:/Workspace/Messi/Code/vgflow-repo/commands/vg/_shared/review/lens-and-findings.md:666), [commands/vg/_shared/review/lens-and-findings.md:723](D:/Workspace/Messi/Code/vgflow-repo/commands/vg/_shared/review/lens-and-findings.md:723), [commands/vg/_shared/review/lens-and-findings.md:757](D:/Workspace/Messi/Code/vgflow-repo/commands/vg/_shared/review/lens-and-findings.md:757)  
**Purpose**: run CRUD round trips, derive findings, challenge weak passes.  
**Actual**: missing `CRUD-SURFACES`, no kit, auth/bootstrap failure, or no run artifacts all continue; markers still written.  
**Gap**: few findings can mean few probes ran, not clean app.  
**Severity**: high  
**Fix**: distinguish `SKIPPED`, `NO_SURFACE`, `FAILED`, `PASS`; block or debt-log skipped CRUD-capable phases.

### Finding 10: Claimed Scan Counts Are Static, Not Runtime Proof
**Q**: 3  
**File:line**: [commands/vg/_shared/review/code-scan.md:300](D:/Workspace/Messi/Code/vgflow-repo/commands/vg/_shared/review/code-scan.md:300), [commands/vg/_shared/review/code-scan.md:315](D:/Workspace/Messi/Code/vgflow-repo/commands/vg/_shared/review/code-scan.md:315), [commands/vg/_shared/review/api-and-discovery.md:711](D:/Workspace/Messi/Code/vgflow-repo/commands/vg/_shared/review/api-and-discovery.md:711)  
**Purpose**: scan routes/models/services and registered routes.  
**Actual**: phase is advertised as `<10 sec`; supplement scanners are “queued”; route registrations are grep/config-driven.  
**Gap**: “25 routes / 21 models / 36 services / 65 registrations” likely inventory counts, not visited runtime evidence.  
**Severity**: medium  
**Fix**: label static inventory separately; require visited/observed counts from runtime traces.

## Summary Table

| # | Lane | Severity | Shortcut |
|---|---|---|---|
| 1 | test-spec | critical | pseudo codegen agent |
| 2 | test-spec | critical | PASS despite failed contract |
| 3 | test-spec | high | scaffold/validator lacks goal parity |
| 4 | review | critical | weak browser tour proof |
| 5 | review | critical | runtime-map prose merge |
| 6 | review | critical | blocking gates non-blocking |
| 7 | review | high | matrix intent marker-only |
| 8 | review | high | lens skip bypass |
| 9 | review | high | CRUD/findings skip then done |
| 10 | review | medium | static counts presented as depth |

## Where 11m 35s Went

Best estimate: mostly static scans, cached/reused proof, markdown-guided marker steps, maybe some parallel browser work. 11m35s is plausible for route/model/service grep plus API precheck plus shallow/parallel scans. It is not strong evidence that 12 browser views and 12 lens probes actually ran.

Numbers like 25 routes, 21 models, 36 services, 65 registrations likely came from static inventory and route registration grep. “12 views toured” needs `nav-discovery.json`, 12 matching `scan-*.json`, per-view browser traces, and current-run provenance. Current contract does not require that.

Only 2 findings is consistent with Phase 2d/2e skip paths: no `runs/*.json` means findings derivation skips.

## Top 5 Priority Recommendations

1. Make `test-spec` codegen real: executable spawn, manifest schema, spec count, no marker until outputs verified.
2. Remove every `|| true` around `run-complete` and blocking validators.
3. Add hard per-view browser evidence contract: assignment count equals scan count, action trace exists, provenance current run.
4. Replace prompt-only blockers with enforced decision handling: unresolved prompt exits nonzero.
5. Wire `verify-runtime-map-coverage.py` into `vg:review`; block empty `views[].elements` and missing `goal_sequences`.

## Smoothness Verdict

Review lane: **NEEDS-WORK**. Too many paths can mark success with weak or missing runtime evidence.

Test-spec lane: **NEEDS-WORK**. Deep-spec scaffold exists, but codegen lane is not reliably executed or gated.