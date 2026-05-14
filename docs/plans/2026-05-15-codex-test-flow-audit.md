**Project Positioning:** L3 Team default.

Legend: `Y` real/enforced. `P` partial. `N` scaffold/missing.

| Marker | Status | Bash Invoke? | Artifact Gate Before Mark? | Exit-On-Fail? |
|---|---:|---|---|---|
| `00_gate_integrity_precheck` | REAL_BASH | Y: `t8_gate_check`, `run-start` | P: conflict file/script checks | Y |
| `00_session_lifecycle` | PARTIAL | P: `session_start`, `emit-tasklist.py \|\| true` | N | N |
| `0_parse_and_validate` | PARTIAL | Y: several validators | P: no hard `[ -f RUNTIME-MAP/GOALS/API-CONTRACTS ]` despite prose | Y |
| `0c_telemetry_suggestions` | PARTIAL | P: advisory `telemetry-suggest.py \|\| echo ""` | N | N |
| `create_task_tracker` | PARTIAL | Y: `vg-orchestrator tasklist-projected` | N: no evidence-file check before mark | Y |
| `0_state_update` | PARTIAL | P: writes `PIPELINE-STATE.json` | N | N |
| `5a_deploy` | REAL_BASH | Y: deploy-contract load + build/restart/health | P: deploy contract required | Y |
| `5a_mobile_deploy` | SCAFFOLD | N: functions referenced, not sourced; comment says orchestrator extracts markdown | P: helper exists only | P |
| `5b_runtime_contract_verify` | PARTIAL | P: endpoint enumeration + optional idempotency; curl/jq compare is prose | P: `vg-load` nonempty only | P |
| `5c_smoke` | SCAFFOLD | N: browser smoke is prose; Bash only marks | N | N |
| `5c_flow` | SCAFFOLD | N: `flow-runner` invocation is prose | P: `FLOW-SPEC` absence logic only | P |
| `5c_mobile_flow` | PARTIAL | Y: Maestro wrapper loop | N: no flows = mark + `exit 0` | N |
| `5c_goal_verification` | SCAFFOLD | N: Agent prompt; default trust-review skips READY replay | P: input files checked, evidence not hard-gated | P |
| `5c_fix` | PARTIAL | P: severity gate real; actual fixes/reverify prose | P: `.test-fix-plans.json` only | P |
| `5c_auto_escalate` | PARTIAL | P: counter real; review/build/test loop prose | N | N |
| `5e_regression` | PARTIAL | Y: Playwright command exists | P: spec existence yes, results no | P: missing specs yes, test fail not explicit |
| `5f_security_audit` | PARTIAL | Y: validators/grep/curl snippets | N | N: tier failures set vars, then mark PASS default |
| `5f_mobile_security_audit` | PARTIAL | Y: grep scans + report | N | N: critical/high no `exit 1` |
| `5g_performance_check` | PARTIAL | Y: curl/static checks | N | N: advisory only |
| `5h_security_dynamic` | REAL_BASH | Y: DAST runner + report validator | P | Y for validator findings |
| `step5_fix_loop` | SCAFFOLD | N: algorithm/prose; no concrete loop runner | N | N |
| `step7_matrix_verdict` | PARTIAL | Y: RCRURD + validators + matrix gate | P | Y, but no marker in shared file |
| `write_report` | SCAFFOLD | N: computes verdict, shows markdown template, never writes report | N | P |
| `bootstrap_reflection` | SCAFFOLD | N: `Agent(...)` prose only | N: no `REFLECTION.md` gate | N |
| `complete` | PARTIAL | Y: cleanup/state/gates/run-complete | P: marker gate broken by filter | Y |

Counts: `REAL_BASH=3`, `PARTIAL=15`, `SCAFFOLD=7`.

**New Gaps**
1. Profile marker gate effectively checks only `step5_fix_loop,step7_matrix_verdict`. `filter-steps.py` uses `<step>` tags if any exist, and only two exist in test shared files. Runtime contract fallback never runs. Evidence: [filter-steps.py](D:/Workspace/Messi/Code/vgflow-repo/.claude/scripts/filter-steps.py:254), [fix-loop-and-verdict.md](D:/Workspace/Messi/Code/vgflow-repo/commands/vg/_shared/test/fix-loop-and-verdict.md:1).
2. `write_report` does not write `${PHASE_DIR}/SANDBOX-TEST.md`; it only shows template then `git add` + marks. Evidence: [close.md](D:/Workspace/Messi/Code/vgflow-repo/commands/vg/_shared/test/close.md:148), [close.md](D:/Workspace/Messi/Code/vgflow-repo/commands/vg/_shared/test/close.md:214).
3. `5b_runtime_contract_verify` never implements endpoint curl/jq schema compare. Text says “For each endpoint”, but Bash stops after enumeration. Evidence: [runtime.md](D:/Workspace/Messi/Code/vgflow-repo/commands/vg/_shared/test/runtime.md:55), [runtime.md](D:/Workspace/Messi/Code/vgflow-repo/commands/vg/_shared/test/runtime.md:74).
4. `5c_goal_verification` default path is trust-review, not per-goal replay. READY goals can become `PASSED` from review evidence, with Agent prose enforcing behavior. Evidence: [overview.md](D:/Workspace/Messi/Code/vgflow-repo/commands/vg/_shared/test/goal-verification/overview.md:80), [delegation.md](D:/Workspace/Messi/Code/vgflow-repo/commands/vg/_shared/test/goal-verification/delegation.md:76).
5. `step5_fix_loop` lacks actual user-confirm/failure-driven loop and lacks mark-step in shared file. Evidence: [fix-loop-and-verdict.md](D:/Workspace/Messi/Code/vgflow-repo/commands/vg/_shared/test/fix-loop-and-verdict.md:21), [test.md](D:/Workspace/Messi/Code/vgflow-repo/commands/vg/test.md:321).
6. `5f_security_audit` can find Tier 0/security failures but still mark PASS by default. Evidence: [regression-security.md](D:/Workspace/Messi/Code/vgflow-repo/commands/vg/_shared/test/regression-security.md:306), [regression-security.md](D:/Workspace/Messi/Code/vgflow-repo/commands/vg/_shared/test/regression-security.md:431).
7. `5e_regression` runs Playwright but does not explicitly fail/ledger from Playwright rc before marking PASS. Evidence: [regression-security.md](D:/Workspace/Messi/Code/vgflow-repo/commands/vg/_shared/test/regression-security.md:179), [regression-security.md](D:/Workspace/Messi/Code/vgflow-repo/commands/vg/_shared/test/regression-security.md:255).
8. `5c_smoke` is pure scaffold. Evidence: [runtime.md](D:/Workspace/Messi/Code/vgflow-repo/commands/vg/_shared/test/runtime.md:248), [runtime.md](D:/Workspace/Messi/Code/vgflow-repo/commands/vg/_shared/test/runtime.md:267).
9. `5c_flow` does not invoke `flow-runner`; it only describes it. Evidence: [runtime.md](D:/Workspace/Messi/Code/vgflow-repo/commands/vg/_shared/test/runtime.md:350), [runtime.md](D:/Workspace/Messi/Code/vgflow-repo/commands/vg/_shared/test/runtime.md:380).
10. `bootstrap_reflection` is Agent prose, skips can exit before marker, and output not gated. Evidence: [close.md](D:/Workspace/Messi/Code/vgflow-repo/commands/vg/_shared/test/close.md:253), [close.md](D:/Workspace/Messi/Code/vgflow-repo/commands/vg/_shared/test/close.md:286).

**Worst Risks**
1. Marker gate blind spot: most missing steps pass unnoticed.
2. Report missing: runtime contract `must_write` depends on Stop hook, not step.
3. Runtime contract verify does not verify contract.
4. Goal replay skipped by default trust-review.
5. Fix loop mostly prose; failing tests do not force repair.
6. Security audit marks despite hard findings.
7. Regression can mark after failed Playwright.
8. Smoke/flow browser checks scaffolded.
9. Mobile/security/perf failures mostly advisory.
10. Reflection marker/output weak; skip path exits early.