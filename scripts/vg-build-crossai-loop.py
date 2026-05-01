#!/usr/bin/env python3
"""
vg-build-crossai-loop.py — OHOK-7 MANDATORY post-build verification iteration.

Pattern: after /vg:build wave execution, the build skill MUST invoke this
script up to 5 times. Each call runs ONE iteration. Opus (main Claude) is
the orchestrator deciding between iterations.

Per iteration:
1. Pack review brief from 4 source-of-truth artifacts:
   - API-CONTRACTS.md (every endpoint/schema defined)
   - TEST-GOALS.md (every priority=critical goal must be covered)
   - CONTEXT.md (every D-XX decision must be honored by code)
   - PLAN.md (every task must have a matching commit)
   + git diff since phase's first commit (the actual built code)

2. Spawn Codex + Gemini CLI in parallel with identical verification prompt:
   "Was this build complete against contracts/goals/decisions/plan?"
   NOT generic code review — specifically contract-completion check.

3. Parse both verdicts → structured findings (severity, category, file, hint)

4. Emit events.db events:
   - build.crossai_iteration_started (at start)
   - build.crossai_iteration_complete (at end, with outcome)

5. Write findings-iter{N}.json to phase/crossai-build-verify/ directory.

Caller (main Claude) reads findings + decides:
- Exit 0 (both CLIs PASS, no BLOCK): emit build.crossai_loop_complete, done
- Exit 1 (any BLOCK finding): dispatch Sonnet Task subagent to fix + re-invoke
  at iteration N+1
- Exit 2 (CLI infra failure): retry or escalate to user

After max 5 iterations without clean → skill prompts user:
  (a) continue another 5 → emit user_override_continue
  (b) defer to /vg:review → emit build.crossai_loop_user_override
  (c) skip + HARD debt → emit build.crossai_loop_user_override + log OVERRIDE

Validator build-crossai-required.py enforces at /vg:build run-complete:
BLOCK if neither build.crossai_loop_complete nor exhausted/user_override
event exists. No way to skip via "promise" — must have events.db evidence.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
PHASES_DIR = REPO_ROOT / ".vg" / "phases"
ORCHESTRATOR = REPO_ROOT / ".claude" / "scripts" / "vg-orchestrator"

# Budget per CLI call (seconds). CrossAI CLIs take 1-5 min typically; cap at 10.
CLI_TIMEOUT_SEC = 600


def find_phase_dir(phase: str) -> Path | None:
    """Mirror of orchestrator/validators phase resolver (decimal zero-pad safe)."""
    if not PHASES_DIR.exists():
        return None
    candidates = list(PHASES_DIR.glob(f"{phase}-*"))
    if candidates:
        return candidates[0]
    bare = PHASES_DIR / phase
    if bare.is_dir():
        return bare
    if "." in phase:
        major, _, rest = phase.partition(".")
    else:
        major, rest = phase, ""
    if major.isdigit() and len(major) < 2:
        normalized = f"{major.zfill(2)}.{rest}" if rest else major.zfill(2)
        candidates = list(PHASES_DIR.glob(f"{normalized}-*"))
        if candidates:
            return candidates[0]
        bare_norm = PHASES_DIR / normalized
        if bare_norm.is_dir():
            return bare_norm
    return None


def _git(*args: str) -> str:
    """Run git, return stdout or empty on failure."""
    try:
        r = subprocess.run(
            ["git", *args], capture_output=True,
            encoding="utf-8", errors="replace",
            timeout=20, cwd=REPO_ROOT,
        )
        if r.returncode != 0:
            return ""
        return r.stdout or ""
    except Exception:
        return ""


def phase_first_commit(phase_num: str) -> str:
    """Find first commit SHA that matches phase tag subject."""
    # Phase variants: "7.8" and "07.8" etc.
    variants = [phase_num]
    if "." in phase_num:
        base, sub = phase_num.split(".", 1)
        if len(base) == 1:
            variants.append(f"0{base}.{sub}")
    elif len(phase_num) == 1:
        variants.append(f"0{phase_num}")
    pattern = "|".join(f"\\({v}[-.0-9]*-[0-9]+\\):" for v in variants)
    out = _git(
        "log", "--no-merges", "-E", f"--grep={pattern}",
        "--reverse", "--format=%H",
    )
    lines = [l.strip() for l in out.splitlines() if l.strip()]
    return lines[0] if lines else ""


def pack_review_brief(phase_dir: Path, phase_num: str, iteration: int,
                       max_iter: int) -> str:
    """Build a CrossAI prompt focused on contract/goal/decision/plan completion."""
    def read(name: str, cap: int = 8000) -> str:
        p = phase_dir / name
        if not p.exists():
            return f"(file {name} MISSING — this itself is a gap to flag)"
        txt = p.read_text(encoding="utf-8", errors="replace")
        return txt if len(txt) <= cap else txt[:cap] + f"\n\n[truncated; full file is {len(txt)} chars]"

    contracts = read("API-CONTRACTS.md", 8000)
    goals = read("TEST-GOALS.md", 8000)
    context = read("CONTEXT.md", 6000)
    plan = read("PLAN.md", 4000)

    first_sha = phase_first_commit(phase_num)
    if first_sha:
        diff = _git("diff", f"{first_sha}^..HEAD", "--stat")
        diff_detail = _git("diff", f"{first_sha}^..HEAD")
        if len(diff_detail) > 20000:
            diff_detail = diff_detail[:20000] + "\n\n[diff truncated — " \
                          f"full {len(diff_detail)} chars]"
    else:
        diff = "(no phase-tagged commits found — this itself is a gap)"
        diff_detail = ""

    commits = _git(
        "log", "--no-merges",
        "-E", f"--grep=\\({phase_num}[-.0-9]*-[0-9]+\\):",
        "--format=%h %s",
    )

    brief = f"""# OHOK-7 Build Verification — Phase {phase_num} iteration {iteration}/{max_iter}

## Your task

Determine whether the build is COMPLETE against the four source-of-truth
artifacts below. This is NOT a generic code review. Check specifically:

1. **Every endpoint/schema in API-CONTRACTS.md** has a matching handler +
   types + validation in the code diff. Missing endpoint → BLOCK finding.
2. **Every goal with priority=critical in TEST-GOALS.md** has real test
   coverage (NOT just unit; runtime/E2E for UI goals). Uncovered → BLOCK.
3. **Every decision D-XX in CONTEXT.md** is honored by code patterns. E.g.
   if D-09 says "CORS allowlist explicit", check cors.ts actually does that.
   Decision violated → BLOCK.
4. **Every task in PLAN.md** has a matching `feat({phase_num}-NN):` commit. Task
   not committed (or committed without the right files touched) → BLOCK.

Style issues, optimization suggestions, refactoring opinions → MEDIUM/LOW
severity, NOT BLOCK. BLOCK is reserved for literal contract gaps.

## Artifacts (source of truth)

### API-CONTRACTS.md
```
{contracts}
```

### TEST-GOALS.md
```
{goals}
```

### CONTEXT.md (decisions)
```
{context}
```

### PLAN.md (tasks)
```
{plan}
```

## Build state (what was actually done)

### Commits in this phase
```
{commits if commits else '(no commits found — build clearly not done)'}
```

### Diff stat
```
{diff}
```

### Diff detail (truncated)
```
{diff_detail}
```

## Required response format

Respond with a single fenced XML block. Do NOT read other files. Base your
verdict only on the artifacts + diff above.

```xml
<crossai-build-verdict>
  <verdict>PASS | FLAG | BLOCK</verdict>
  <summary>1-2 sentence top-level statement</summary>
  <findings>
    <finding>
      <severity>BLOCK | HIGH | MEDIUM | LOW</severity>
      <category>contract_gap | goal_uncovered | decision_violated | task_not_committed | other</category>
      <artifact_ref>D-09 | G-07 | POST /api/... | Task 14-05 | ...</artifact_ref>
      <message>Specific actionable description</message>
      <file>path/to/file.ts:42 (if applicable)</file>
      <fix_hint>Concrete change to make</fix_hint>
    </finding>
  </findings>
</crossai-build-verdict>
```

Only mark `<verdict>BLOCK</verdict>` if ≥1 BLOCK-severity finding exists.
FLAG for HIGH findings. PASS if no HIGH+ findings.
"""
    return brief


def invoke_codex(brief_text: str, output_path: Path) -> int:
    """Codex CLI — same pattern as prior CrossAI rounds."""
    import shutil
    codex_bin = shutil.which("codex") or "codex"
    codex_model = os.environ.get("VG_CODEX_MODEL_ADVERSARIAL")
    # Pass brief via stdin to avoid Windows CreateProcess argv limit (~32KB)
    cmd = [
        codex_bin, "exec",
        "--config", "approval_policy=never",
        "--config", "sandbox_mode=read-only",
        "--skip-git-repo-check",
        "-",
    ]
    if codex_model:
        cmd[-1:-1] = ["--model", codex_model]
    try:
        r = subprocess.run(
            cmd, input=brief_text, capture_output=True,
            encoding="utf-8", errors="replace",
            timeout=CLI_TIMEOUT_SEC,
        )
        output_path.write_text(
            (r.stdout or "") + "\n===STDERR===\n" + (r.stderr or ""),
            encoding="utf-8",
        )
        return r.returncode
    except subprocess.TimeoutExpired:
        output_path.write_text("TIMEOUT after {CLI_TIMEOUT_SEC}s", encoding="utf-8")
        return 124
    except FileNotFoundError:
        output_path.write_text("codex CLI not installed", encoding="utf-8")
        return 127
    except Exception as e:
        output_path.write_text(f"ERROR: {e}", encoding="utf-8")
        return 1


def invoke_gemini(brief_text: str, output_path: Path) -> int:
    """Gemini CLI — read prompt from stdin to avoid Windows argv limit."""
    import shutil
    gemini_bin = shutil.which("gemini") or "gemini"
    # Gemini -p reads from stdin when given "-"; fall back to file redirect via stdin
    cmd = [
        gemini_bin,
        "--model", "gemini-3-pro-preview",
    ]
    try:
        r = subprocess.run(
            cmd, input=brief_text, capture_output=True,
            encoding="utf-8", errors="replace",
            timeout=CLI_TIMEOUT_SEC,
        )
        output_path.write_text(
            (r.stdout or "") + "\n===STDERR===\n" + (r.stderr or ""),
            encoding="utf-8",
        )
        return r.returncode
    except subprocess.TimeoutExpired:
        output_path.write_text("TIMEOUT", encoding="utf-8")
        return 124
    except FileNotFoundError:
        output_path.write_text("gemini CLI not installed", encoding="utf-8")
        return 127
    except Exception as e:
        output_path.write_text(f"ERROR: {e}", encoding="utf-8")
        return 1


_VERDICT_RE = re.compile(r"<crossai-build-verdict>(.*?)</crossai-build-verdict>",
                          re.DOTALL | re.IGNORECASE)
_FINDING_RE = re.compile(r"<finding>(.*?)</finding>", re.DOTALL | re.IGNORECASE)
_FIELD_RE = re.compile(r"<(\w+)>(.*?)</\1>", re.DOTALL)


def parse_verdict(text: str) -> dict | None:
    """Extract the XML verdict block. Returns None if not found."""
    m = _VERDICT_RE.search(text)
    if not m:
        return None
    block = m.group(1)
    verdict_match = re.search(r"<verdict>\s*(\w+)", block, re.IGNORECASE)
    verdict = verdict_match.group(1).upper() if verdict_match else "UNKNOWN"
    findings: list[dict] = []
    for fm in _FINDING_RE.finditer(block):
        fblock = fm.group(1)
        fields: dict[str, str] = {}
        for sub in _FIELD_RE.finditer(fblock):
            fields[sub.group(1).lower()] = sub.group(2).strip()
        if fields:
            findings.append(fields)
    return {"verdict": verdict, "findings": findings, "raw_block": block[:4000]}


class EmitError(Exception):
    """Raised when event emission fails. Caller should treat as INFRA_FAILURE
    and exit 2 — silently swallowing would mean validator later thinks the
    iteration never ran."""


def _resolve_active_run(phase: str) -> tuple[str | None, str]:
    """Resolve (run_id, command) for the current /vg:build run.

    Resolution order (issue #39 — chicken-and-egg fix):
      1. Per-session active-run file (.vg/active-runs/{session_id}.json)
         when CLAUDE_SESSION_ID env is set — v2.28.0 multi-tenant authority.
      2. Legacy snapshot (.vg/current-run.json) for pre-v2.28.0 installs
         and as a one-session fallback.
      3. SQLite runs table — most recent vg:build row for THIS phase that
         hasn't been completed_at yet. This handles the chicken-and-egg
         trap where run-abort cleared current-run.json mid-CrossAI-loop:
         the runs row still exists, the CLI work succeeded, only the
         post-completion event-emit lost the run_id.
      4. None → caller raises EmitError with the recovery hint.
    """
    # 1. Per-session
    sid = os.environ.get("CLAUDE_SESSION_ID") or os.environ.get("CLAUDE_CODE_SESSION_ID")
    if sid:
        safe = "".join(c for c in sid if c.isalnum() or c in "-_") or "unknown"
        per_session = REPO_ROOT / ".vg" / "active-runs" / f"{safe}.json"
        if per_session.exists():
            try:
                run = json.loads(per_session.read_text(encoding="utf-8"))
                rid = run.get("run_id")
                if rid:
                    return rid, run.get("command", "vg:build")
            except Exception:
                pass

    # 2. Legacy snapshot
    legacy = REPO_ROOT / ".vg" / "current-run.json"
    if legacy.exists():
        try:
            run = json.loads(legacy.read_text(encoding="utf-8"))
            rid = run.get("run_id")
            if rid:
                return rid, run.get("command", "vg:build")
        except Exception:
            pass

    # 3. DB fallback — most recent open vg:build run for this phase
    try:
        import sqlite3
        db_path = REPO_ROOT / ".vg" / "events.db"
        if db_path.exists():
            conn = sqlite3.connect(str(db_path), timeout=2.0)
            try:
                row = conn.execute(
                    "SELECT run_id, command FROM runs "
                    "WHERE command LIKE 'vg:build%' AND phase = ? "
                    "AND completed_at IS NULL "
                    "ORDER BY started_at DESC LIMIT 1",
                    (phase,),
                ).fetchone()
                if row:
                    return row[0], row[1]
            finally:
                conn.close()
    except Exception:
        pass

    return None, "vg:build"


def emit_event(event_type: str, phase: str, payload: dict) -> None:
    """OHOK-8: bypass the emit-event CLI (which blocks reserved `build.crossai_*`
    after round-3 forgery mitigation). Import db module directly so only this
    script — not user CLI — can land these events. Preserves hash chain because
    db.append_event serializes via SQLite BEGIN IMMEDIATE + busy_timeout.

    Issue #39 (2026-04-29): no longer fail closed when current-run.json is
    missing/empty mid-loop. Now resolves run_id via _resolve_active_run()
    which falls back to the events.db runs table — recovers from
    chicken-and-egg traps (run-abort or run-repair clearing current-run.json
    while CrossAI's expensive Codex+Gemini calls were already in flight).
    """
    run_id, command = _resolve_active_run(phase)
    if not run_id:
        raise EmitError(
            f"cannot resolve active run for {event_type}: no per-session "
            f"state, no current-run.json, no open vg:build row in events.db. "
            f"Manual recovery: vg-orchestrator run-repair --force OR "
            f"run-start a fresh vg:build {phase} run before retrying."
        )

    # Import db lazily — adds orchestrator/ to sys.path once
    if str(ORCHESTRATOR) not in sys.path:
        sys.path.insert(0, str(ORCHESTRATOR))
    try:
        import db  # type: ignore[import-not-found]
    except Exception as e:
        raise EmitError(f"cannot import db module: {e}") from e
    try:
        db.append_event(
            run_id=run_id,
            event_type=event_type,
            phase=phase,
            command=command,
            actor="orchestrator",
            outcome="INFO",
            payload=payload,
        )
    except Exception as e:
        # FOREIGN KEY failure here usually means run-start wasn't called or
        # the runs row was deleted. Loud fail — validator BLOCKs downstream
        # anyway, better surface root cause now.
        raise EmitError(
            f"db.append_event failed for {event_type!r} "
            f"(run_id={run_id[:12]!r}): {e}"
        ) from e


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    ap.add_argument("--iteration", type=int, required=True)
    ap.add_argument("--max-iterations", type=int, default=5)
    args = ap.parse_args()

    phase_dir = find_phase_dir(args.phase)
    if not phase_dir:
        sys.stderr.write(f"⛔ phase {args.phase} not found\n")
        return 2

    review_dir = phase_dir / "crossai-build-verify"
    review_dir.mkdir(parents=True, exist_ok=True)

    # Kick off iteration
    emit_event(
        "build.crossai_iteration_started",
        phase=args.phase,
        payload={"iteration": args.iteration,
                 "max_iterations": args.max_iterations},
    )

    # Pack brief
    brief = pack_review_brief(phase_dir, args.phase, args.iteration,
                               args.max_iterations)
    brief_path = review_dir / f"BRIEF-iter{args.iteration}.md"
    brief_path.write_text(brief, encoding="utf-8")

    codex_out = review_dir / f"codex-iter{args.iteration}.md"
    gemini_out = review_dir / f"gemini-iter{args.iteration}.md"

    sys.stderr.write(f"▸ Iteration {args.iteration}: spawning Codex + Gemini "
                     f"(timeout {CLI_TIMEOUT_SEC}s each, parallel)...\n")

    with ThreadPoolExecutor(max_workers=2) as pool:
        f_codex = pool.submit(invoke_codex, brief, codex_out)
        f_gemini = pool.submit(invoke_gemini, brief, gemini_out)
        codex_rc = f_codex.result()
        gemini_rc = f_gemini.result()

    # OHOK-8 round-3 P0.3: fail CLOSED on any CLI infra failure or parse
    # failure. Previously if both CLIs returned rc 0 but emitted unparsable
    # output, both verdicts became PARSE_FAIL and outcome CLEAN → false pass.
    # Now: any rc != 0 or unparsable output ⇒ exit 2 (infra), not exit 0.
    if codex_rc != 0:
        sys.stderr.write(
            f"⛔ Codex CLI failed rc={codex_rc} — cannot verify build. "
            f"Treat as INFRA_FAILURE, do not declare CLEAN.\n"
        )
        emit_event(
            "build.crossai_iteration_complete",
            phase=args.phase,
            payload={"iteration": args.iteration,
                     "outcome": "CLI_INFRA_FAILURE",
                     "codex_rc": codex_rc, "gemini_rc": gemini_rc,
                     "reason": "codex_nonzero"},
        )
        return 2
    if gemini_rc != 0:
        sys.stderr.write(
            f"⛔ Gemini CLI failed rc={gemini_rc} — cannot verify build. "
            f"Treat as INFRA_FAILURE, do not declare CLEAN.\n"
        )
        emit_event(
            "build.crossai_iteration_complete",
            phase=args.phase,
            payload={"iteration": args.iteration,
                     "outcome": "CLI_INFRA_FAILURE",
                     "codex_rc": codex_rc, "gemini_rc": gemini_rc,
                     "reason": "gemini_nonzero"},
        )
        return 2

    codex_verdict = parse_verdict(codex_out.read_text(encoding="utf-8",
                                                       errors="replace"))
    gemini_verdict = parse_verdict(gemini_out.read_text(encoding="utf-8",
                                                         errors="replace"))

    if not codex_verdict:
        sys.stderr.write(
            "⛔ Codex output not parseable (no <crossai-build-verdict> XML "
            "block). Cannot verify — treat as INFRA_FAILURE not CLEAN.\n"
        )
        emit_event(
            "build.crossai_iteration_complete",
            phase=args.phase,
            payload={"iteration": args.iteration,
                     "outcome": "PARSE_FAILURE",
                     "reason": "codex_unparsable"},
        )
        return 2
    if not gemini_verdict:
        sys.stderr.write(
            "⛔ Gemini output not parseable (no <crossai-build-verdict> XML "
            "block). Cannot verify — treat as INFRA_FAILURE not CLEAN.\n"
        )
        emit_event(
            "build.crossai_iteration_complete",
            phase=args.phase,
            payload={"iteration": args.iteration,
                     "outcome": "PARSE_FAILURE",
                     "reason": "gemini_unparsable"},
        )
        return 2

    # Extract BLOCK findings from both
    block_findings: list[dict] = []
    all_findings: list[dict] = []
    for name, v in [("codex", codex_verdict), ("gemini", gemini_verdict)]:
        for f in v.get("findings", []):
            f["_source"] = name
            all_findings.append(f)
            if (f.get("severity", "").upper() == "BLOCK"):
                block_findings.append(f)

    has_blocks = (len(block_findings) > 0) or \
                 (codex_verdict["verdict"] == "BLOCK") or \
                 (gemini_verdict["verdict"] == "BLOCK")

    consolidated = {
        "phase": args.phase,
        "iteration": args.iteration,
        "max_iterations": args.max_iterations,
        "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
        "codex": {
            "rc": codex_rc,
            "verdict": codex_verdict["verdict"] if codex_verdict else "PARSE_FAIL",
            "finding_count": len(codex_verdict["findings"]) if codex_verdict else 0,
        },
        "gemini": {
            "rc": gemini_rc,
            "verdict": gemini_verdict["verdict"] if gemini_verdict else "PARSE_FAIL",
            "finding_count": len(gemini_verdict["findings"]) if gemini_verdict else 0,
        },
        "all_findings": all_findings,
        "block_findings": block_findings,
        "has_blocks": has_blocks,
    }
    findings_path = review_dir / f"findings-iter{args.iteration}.json"
    findings_path.write_text(json.dumps(consolidated, indent=2, default=str),
                              encoding="utf-8")

    outcome = "BLOCKS_FOUND" if has_blocks else "CLEAN"
    emit_event(
        "build.crossai_iteration_complete",
        phase=args.phase,
        payload={"iteration": args.iteration,
                 "outcome": outcome,
                 "codex_verdict": consolidated["codex"]["verdict"],
                 "gemini_verdict": consolidated["gemini"]["verdict"],
                 "block_count": len(block_findings),
                 "findings_path": str(findings_path.relative_to(REPO_ROOT))},
    )

    # OHOK-8 round 3: on CLEAN exit, emit loop_complete directly from this
    # script — skill bash cannot do it anymore (reserved event via CLI blocked).
    # Centralizing here also guarantees loop_complete only fires when the
    # iteration actually reached CLEAN.
    if not has_blocks:
        emit_event(
            "build.crossai_loop_complete",
            phase=args.phase,
            payload={"iterations_completed": args.iteration,
                     "max_iterations": args.max_iterations,
                     "early_exit": args.iteration < args.max_iterations,
                     "codex_verdict": consolidated["codex"]["verdict"],
                     "gemini_verdict": consolidated["gemini"]["verdict"]},
        )

    print(json.dumps({
        "iteration": args.iteration,
        "outcome": outcome,
        "block_count": len(block_findings),
        "findings_file": str(findings_path.relative_to(REPO_ROOT)),
        "codex_verdict": consolidated["codex"]["verdict"],
        "gemini_verdict": consolidated["gemini"]["verdict"],
    }))

    return 1 if has_blocks else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except EmitError as e:
        # OHOK-8: emit failure = INFRA_FAILURE. Caller sees exit 2 and knows
        # to investigate. Validator later BLOCKs on missing events anyway —
        # this just surfaces the real cause earlier.
        sys.stderr.write(
            f"⛔ vg-build-crossai-loop.py INFRA_FAILURE (emit): {e}\n"
            f"   Iteration events may be missing — validator will BLOCK at\n"
            f"   run-complete. Investigate .vg/events.db + run-start state,\n"
            f"   then re-invoke this script.\n"
        )
        sys.exit(2)
