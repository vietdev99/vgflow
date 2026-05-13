# Batch 14 — Holistic audit priority fixes (F1+F2+F3+F4+F6+F11+F12) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Close 3 HIGH + 4 MEDIUM findings from `docs/plans/2026-05-13-holistic-audit-codex-fallback.md`. Lift smoothness verdict from NEEDS-WORK → PASS for blueprint→build + overall idea→ship autonomous.

- **F1 (HIGH)**: `/vg:complete-milestone` security audit is print-only — never executes.
- **F2 (HIGH)**: `/vg:complete-milestone` no `run-start` + no markers → Stop hook bypassed.
- **F12 (HIGH)**: `/vg:roam` post-roam reflector event name mismatch (`phase.roam_completed` checked, `roam.session.completed` emitted).
- **F3 (MEDIUM)**: 2 PostToolUse hook scripts orphaned (Agent + AskUserQuestion).
- **F4 (MEDIUM)**: `AskUserQuestion:` inside bash block in design-scaffold + design-reverse.
- **F6 (MEDIUM)**: `/vg:debug` SlashCommand not in allowed-tools.
- **F11 (MEDIUM)**: scope-review early-exit doesn't bump baseline timestamp.

**Tech Stack:** Python + bash.

**Working directory:** `main`.

---

## Conventions

- Mirror byte-identical to `.claude/`
- Regression sweep: `python -m pytest tests/ -q --tb=no -k "complete_milestone or roam or debug or design_scaffold or scope_review or hook or f1 or f2 or f3 or f4 or f6 or f11 or f12"`
- Single `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` per commit

---

## Task 1: F1+F2 — complete-milestone hook + run-start + security audit invoke

**Files:**
- Modify: `commands/vg/complete-milestone.md` (add run-start, must_touch_markers, real security audit invocation)
- Mirror: `.claude/commands/vg/complete-milestone.md` (+ codex mirror)
- Test: `tests/test_f1_f2_complete_milestone_hook.py`

**Step 1: Failing test**

```python
"""tests/test_f1_f2_complete_milestone_hook.py — F1+F2 milestone hook + audit."""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
CM = REPO / "commands" / "vg" / "complete-milestone.md"


def _read(p): return p.read_text(encoding="utf-8")


def test_complete_milestone_calls_run_start():
    body = _read(CM)
    assert "vg-orchestrator run-start" in body or "run_start" in body, (
        "F2: complete-milestone must call vg-orchestrator run-start so Stop "
        "hook sees an active run and can verify contract"
    )


def test_complete_milestone_has_must_touch_markers():
    body = _read(CM)
    assert "must_touch_markers" in body, (
        "F2: complete-milestone frontmatter runtime_contract must declare "
        "must_touch_markers for each step so Stop hook enforces completion"
    )
    # At minimum expect security_audit marker
    assert "security_audit" in body or "2_gate_check" in body, (
        "F2: must_touch_markers list must include the security audit + gate steps"
    )


def test_security_audit_actually_invokes():
    body = _read(CM)
    sec_block_idx = body.find("security_audit")
    if sec_block_idx < 0:
        sec_block_idx = body.find("/vg:security-audit-milestone")
    assert sec_block_idx > 0
    # Look for actual invocation: subprocess.run, or shell command, or SlashCommand directive
    block = body[sec_block_idx:sec_block_idx + 2000]
    assert ("subprocess" in block or
            "generate-strix-advisory" in block or
            "SlashCommand: /vg:security-audit" in block or
            "scripts/run-security-audit.sh" in block), (
        "F1: security audit must actually invoke (subprocess/script/SlashCommand), "
        "not just print 'Run: /vg:security-audit-milestone'"
    )
```

**Step 2: Run** → 3 fail.

**Step 3: Implement**

In `commands/vg/complete-milestone.md`:

1. Add to frontmatter `runtime_contract`:
   ```yaml
   must_touch_markers:
     - 0_args
     - 1_telemetry_started
     - 2_gate_check
     - 3_security_audit
     - 4_milestone_summary
     - 5_archive_phases
     - 6_finalize_state
     - 7_atomic_commit
   ```

2. Add `run-start` call at the start of step `1_telemetry_started`:
   ```bash
   "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator run-start vg:complete-milestone \
     "milestone-level" "${ARGUMENTS}" || true
   ```

3. Replace the security audit print-only block (around lines 92-113) with actual invocation. Pick approach (a): direct script call:
   ```bash
   STRIX="${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/generate-strix-advisory.py"
   [ -f "$STRIX" ] || STRIX="${REPO_ROOT:-.}/scripts/generate-strix-advisory.py"
   if [ -f "$STRIX" ]; then
     "${PYTHON_BIN:-python3}" "$STRIX" --milestone-gate ${AUDIT_ARGS:-} || true
   fi
   ```

4. Each `<step>` block must end with `touch ${PHASE_DIR}/.step-markers/<step_id>.done` (or use existing `mark_step` helper).

**Step 4-6:** pass + mirror + commit.

```bash
git add commands/vg/complete-milestone.md \
        .claude/commands/vg/complete-milestone.md \
        codex-skills/vg-complete-milestone/SKILL.md \
        tests/test_f1_f2_complete_milestone_hook.py
git commit -m "fix(milestone): F1+F2 — complete-milestone Stop hook + real security audit (Batch 14)

Holistic audit Findings 1+2 (HIGH): /vg:complete-milestone had:
- F1: security audit step was print-only (Python one-liner emits 'delegating'
  echo, never actually invokes the audit script).
- F2: no vg-orchestrator run-start + no must_touch_markers → Stop hook
  exited immediately. Milestone close ran with zero contract enforcement.

Fix:
- Frontmatter runtime_contract gains must_touch_markers for all 8 steps
  (0_args through 7_atomic_commit).
- Step 1_telemetry_started invokes vg-orchestrator run-start so Stop hook
  sees an active run.
- Step 3_security_audit actually invokes generate-strix-advisory.py
  --milestone-gate (real script call, not echo).
- Each step touches its marker via mark_step helper.

Tests: tests/test_f1_f2_complete_milestone_hook.py.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: F12 — roam post-roam reflector event match

**Files:**
- Modify: `commands/vg/_shared/roam/close.md` (also emit `phase.roam_completed`)
- Mirror
- Test: `tests/test_f12_roam_reflector_event.py`

**Step 1: Failing test**

```python
"""tests/test_f12_roam_reflector_event.py — F12 roam reflector event match."""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
ROAM_CLOSE = REPO / "commands" / "vg" / "_shared" / "roam" / "close.md"
ROAM_MD = REPO / "commands" / "vg" / "roam.md"


def _read(p): return p.read_text(encoding="utf-8")


def test_roam_close_emits_phase_roam_completed():
    body = _read(ROAM_CLOSE)
    assert "phase.roam_completed" in body, (
        "F12: roam/close.md must emit phase.roam_completed event so the "
        "reflector trigger in roam.md actually fires"
    )


def test_reflector_trigger_event_name_matches():
    """Either both files agree on phase.roam_completed, OR roam.md checks
    roam.session.completed instead."""
    close_body = _read(ROAM_CLOSE)
    md_body = _read(ROAM_MD)
    # roam.md trigger condition references some event name
    if "phase.roam_completed" in md_body:
        # close.md must emit phase.roam_completed
        assert "phase.roam_completed" in close_body, (
            "F12: roam.md reflector checks phase.roam_completed but "
            "roam/close.md doesn't emit it — meta-memory feedback loop dead"
        )
    elif "roam.session.completed" in md_body:
        assert "roam.session.completed" in close_body
```

**Step 2-6:** RED → implement → GREEN → mirror → commit.

In `commands/vg/_shared/roam/close.md`, after the existing `roam.session.completed` emit, add:

```bash
# F12 Batch 14: also emit phase.roam_completed so reflector trigger in roam.md
# (which checks $EVENT_TYPE = "phase.roam_completed") actually fires.
"${PYTHON_BIN:-python3}" "${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/vg-orchestrator" emit-event \
  "phase.roam_completed" \
  --actor "roam" \
  --outcome "INFO" \
  --metadata "{\"phase\":\"${PHASE_NUMBER:-unknown}\"}" \
  >/dev/null 2>&1 || true
```

```bash
git commit -m "fix(roam): F12 — emit phase.roam_completed so reflector trigger fires (Batch 14)

Holistic audit Finding 12 (HIGH): roam.md line 252-253 checks
\$EVENT_TYPE = 'phase.roam_completed' before spawning vg-reflector subagent.
But close.md only emits 'roam.session.completed'. Event name mismatch =
reflector never spawns = meta-memory's highest-signal feedback loop
(roam findings → lesson candidates) is dead code.

Fix: close.md additionally emits phase.roam_completed alongside the
existing roam.session.completed. One-line fix that unlocks the entire
meta-memory feedback path for users with inject-as-advice mode enabled.

Tests: tests/test_f12_roam_reflector_event.py.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: F3 — Wire orphaned PostToolUse hooks

**Files:**
- Modify: `.claude/settings.json` (add 2 PostToolUse entries) — wait, this is user's settings file. Check if there's a template.
- Actually: Check `scripts/hooks/install-hooks.sh` which generates settings.json. Modify the installer + add to settings template.
- Mirror equivalents in templates
- Test: `tests/test_f3_posttooluse_hooks_wired.py`

**Step 1: Failing test**

```python
"""tests/test_f3_posttooluse_hooks_wired.py — F3 PostToolUse orphans wired."""
from __future__ import annotations
import json
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
INSTALL_HOOKS = REPO / "scripts" / "hooks" / "install-hooks.sh"


def test_install_hooks_wires_agent_post_hook():
    body = INSTALL_HOOKS.read_text(encoding="utf-8")
    assert "vg-post-tool-use-agent" in body, (
        "F3: install-hooks.sh must wire vg-post-tool-use-agent.sh for "
        "PostToolUse on Agent matcher (Issue #140 git intent-to-add mitigation)"
    )


def test_install_hooks_wires_askuserquestion_post_hook():
    body = INSTALL_HOOKS.read_text(encoding="utf-8")
    assert "vg-post-tool-use-askuserquestion" in body or "askuserquestion" in body.lower(), (
        "F3: install-hooks.sh must wire vg-post-tool-use-askuserquestion.sh "
        "for PostToolUse on AskUserQuestion matcher (TaskUpdate reminder)"
    )
```

**Step 2-6:** RED → implement → GREEN → mirror → commit.

Modify `scripts/hooks/install-hooks.sh` to add the 2 hook entries when generating settings.json. The pattern should match existing TodoWrite|TaskCreate|TaskUpdate wiring.

```bash
git commit -m "fix(hooks): F3 — wire orphaned PostToolUse hooks (Batch 14)

Holistic audit Finding 3 (MEDIUM): vg-post-tool-use-agent.sh (Issue #140
git add -N intent-to-add + L2 post-wave reminder) and
vg-post-tool-use-askuserquestion.sh (TaskUpdate reminder) exist as
meaningful scripts but neither was registered in settings.json
PostToolUse. Both were dead code.

Fix: install-hooks.sh now generates PostToolUse entries for Agent +
AskUserQuestion matchers alongside the existing TodoWrite|TaskCreate|
TaskUpdate entry. Both hooks now fire as designed.

Tests: tests/test_f3_posttooluse_hooks_wired.py.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: F4 — Fix AskUserQuestion bash syntax in design-scaffold + design-reverse

**Files:**
- Modify: `commands/vg/design-scaffold.md` (line ~73)
- Modify: `commands/vg/design-reverse.md` (line ~46)
- Mirrors
- Test: `tests/test_f4_design_askuser_syntax.py`

**Step 1: Failing test**

```python
"""tests/test_f4_design_askuser_syntax.py — F4 AskUserQuestion bash syntax."""
from __future__ import annotations
import re
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]

CASES = [
    REPO / "commands" / "vg" / "design-scaffold.md",
    REPO / "commands" / "vg" / "design-reverse.md",
]


def _bash_blocks(text):
    """Yield each ```bash ... ``` block contents."""
    return re.findall(r"```bash\n(.*?)\n```", text, flags=re.S)


def test_askuserquestion_not_inside_bash_block():
    failures = []
    for path in CASES:
        body = path.read_text(encoding="utf-8")
        for i, block in enumerate(_bash_blocks(body)):
            if "AskUserQuestion:" in block:
                failures.append(f"{path.name} bash block #{i+1}: AskUserQuestion: directive present")
    assert not failures, (
        "F4: AskUserQuestion: tool-call directive must NOT appear inside ```bash blocks "
        "(invalid bash syntax). Move to plain prose or non-bash code fence:\n  " +
        "\n  ".join(failures)
    )
```

**Step 2-6:** RED → implement → GREEN → mirror → commit.

Locate the `AskUserQuestion:` lines inside ```bash blocks in both files. Wrap them by closing the bash fence, putting `AskUserQuestion:` in prose or plain (no language) fence, then re-opening bash for the remainder.

```bash
git commit -m "fix(design): F4 — AskUserQuestion not inside bash block (Batch 14)

Holistic audit Finding 4 (MEDIUM): design-scaffold.md:73 and
design-reverse.md:46 placed 'AskUserQuestion:' tool-call directive
inside a ```bash``` fenced block. Bash parser sees this as invalid
syntax (or no-op label) — AI may or may not recognize it as a tool
call depending on instruction interpretation. Unpredictable.

Fix: close the ```bash fence before the directive, place the
AskUserQuestion: prompt in plain text (or plain ``` fence), re-open
```bash for subsequent shell commands.

Tests: tests/test_f4_design_askuser_syntax.py.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: F6 — Add SlashCommand to debug allowed-tools

**Files:**
- Modify: `commands/vg/debug.md` (frontmatter allowed-tools)
- Mirror
- Test: `tests/test_f6_debug_allowed_tools.py`

**Step 1: Failing test**

```python
"""tests/test_f6_debug_allowed_tools.py — F6 debug SlashCommand allowed."""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
DEBUG = REPO / "commands" / "vg" / "debug.md"


def test_debug_allowed_tools_includes_slashcommand():
    body = DEBUG.read_text(encoding="utf-8")
    # Find allowed-tools line in frontmatter
    fm_end = body.find("\n---\n", 4)
    fm = body[:fm_end] if fm_end > 0 else body[:2000]
    assert "SlashCommand" in fm, (
        "F6: debug.md frontmatter allowed-tools must include SlashCommand "
        "so the spec-gap auto-route to /vg:amend can actually execute"
    )
```

**Step 2-6:** RED → implement → GREEN → mirror → commit.

In `commands/vg/debug.md` frontmatter `allowed-tools` line, add `SlashCommand`.

```bash
git commit -m "fix(debug): F6 — SlashCommand in debug allowed-tools (Batch 14)

Holistic audit Finding 6 (MEDIUM): debug.md spec-gap branch instructs
the AI to auto-trigger '/vg:amend \${PHASE_NUMBER}' via SlashCommand:
directive when classification = spec gap. But SlashCommand is missing
from debug.md frontmatter allowed-tools. AI tool-call hits permission
deny — spec-gap routing silently fails.

Fix: add SlashCommand to debug.md allowed-tools list alongside existing
Task entry.

Tests: tests/test_f6_debug_allowed_tools.py.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: F11 — scope-review baseline timestamp bump on early-exit

**Files:**
- Modify: `commands/vg/_shared/scope-review/preflight.md` (lines ~167-178)
- Mirror
- Test: `tests/test_f11_scope_review_baseline_bump.py`

**Step 1: Failing test**

```python
"""tests/test_f11_scope_review_baseline_bump.py — F11 baseline ts bump."""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
PREFLIGHT = REPO / "commands" / "vg" / "_shared" / "scope-review" / "preflight.md"


def test_early_exit_bumps_baseline_ts():
    body = PREFLIGHT.read_text(encoding="utf-8")
    # Find the early-exit block
    early_idx = body.find('CHANGED_COUNT" = "0"')
    if early_idx < 0:
        early_idx = body.find("No phases changed since")
    assert early_idx > 0
    block = body[early_idx:early_idx + 1500]
    # Must write baseline ts before exit
    assert ("baseline" in block.lower() and ("ts" in block or "timestamp" in block.lower()) and
            "write" in block.lower() or "json.dump" in block or "p.write_text" in block), (
        "F11: scope-review early-exit must write updated baseline timestamp "
        "before exit 0. Currently exits without bump → stale 'last checked' "
        "displayed on subsequent runs."
    )
```

**Step 2-6:** RED → implement → GREEN → mirror → commit per plan exact snippet.

```bash
git commit -m "fix(scope-review): F11 — bump baseline ts on early-exit (Batch 14)

Holistic audit Finding 11 (MEDIUM): scope-review early-exit comment
promises 'Still refresh baseline timestamp, then exit' but code exits
before write. Multi-run no-change scenarios drift baseline ts further
into past, causing confusion about whether scope-review is being checked.

Fix: insert baseline ts write before exit 0 in the early-exit block.

Tests: tests/test_f11_scope_review_baseline_bump.py.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Regression sweep + release v4.17.0

Bump VERSION 4.16.0 → 4.17.0. CHANGELOG per 7 findings. Tag v4.17.0. Push. Re-sync ~/.vgflow.

End of Batch 14 plan. Estimated 3-4 hours.
