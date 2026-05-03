"""
Phase C v2.5 (2026-04-23) — executor context isolation tests.

Validates:
  1. verify-context-refs.py validator behavior (full/scoped modes)
  2. build.md step 8c has DECISION_CONTEXT block + scoped injection logic
  3. blueprint.md 2a_plan has <context-refs> instruction for planner
  4. vg-executor-rules.md references <decision_context> block
  5. verify-context-refs registered in orchestrator vg:blueprint validators
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
VALIDATOR = REPO_ROOT / ".claude" / "scripts" / "validators" / "verify-context-refs.py"
BUILD_MD  = REPO_ROOT / ".claude" / "commands" / "vg" / "build.md"
BLUEPRINT_MD = REPO_ROOT / ".claude" / "commands" / "vg" / "blueprint.md"
EXECUTOR_RULES = REPO_ROOT / ".claude" / "commands" / "vg" / "_shared" / "vg-executor-rules.md"


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _setup(tmp_path: Path, plan_md: str,
           context_md: str | None = None,
           config_mode: str = "scoped") -> Path:
    phase_dir = tmp_path / ".vg" / "phases" / "09-test"
    phase_dir.mkdir(parents=True)
    (phase_dir / "PLAN.md").write_text(plan_md, encoding="utf-8")
    if context_md is not None:
        (phase_dir / "CONTEXT.md").write_text(context_md, encoding="utf-8")

    # Write vg.config.md with specified mode
    cfg = tmp_path / ".claude" / "vg.config.md"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(
        f"---\nprofile: web-fullstack\n"
        f"context_injection:\n  mode: \"{config_mode}\"\n  phase_cutover: 14\n"
        f"  scoped_fallback_on_missing: true\n",
        encoding="utf-8",
    )

    # Copy narration files
    src = REPO_ROOT / ".claude" / "commands" / "vg" / "_shared"
    dst = tmp_path / ".claude" / "commands" / "vg" / "_shared"
    dst.mkdir(parents=True, exist_ok=True)
    for name in ("narration-strings.yaml", "narration-strings-validators.yaml"):
        s = src / name
        if s.exists():
            (dst / name).write_text(s.read_text(encoding="utf-8"), encoding="utf-8")

    return tmp_path


def _run(repo: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(repo)
    return subprocess.run(
        [sys.executable, str(VALIDATOR), "--phase", "9"],
        cwd=repo, capture_output=True, text=True, timeout=20, env=env,
    )


def _parse(stdout: str) -> dict:
    for line in reversed(stdout.splitlines()):
        s = line.strip()
        if s.startswith("{"):
            return json.loads(s)
    raise AssertionError(f"no JSON:\n{stdout}")


# ─── Test: full mode skips check ──────────────────────────────────────────────

def test_full_mode_passes_without_refs(tmp_path):
    """mode=full → PASS immediately regardless of task contents."""
    plan = "## Task 01\nDo something\n"
    repo = _setup(tmp_path, plan, config_mode="full")
    r = _run(repo)
    out = _parse(r.stdout)
    assert r.returncode == 0
    assert out["verdict"] == "PASS"


# ─── Test: scoped mode with complete refs ────────────────────────────────────

def test_scoped_mode_with_refs_passes(tmp_path):
    """scoped mode + all tasks have <context-refs> → PASS."""
    plan = """\
## Task 01: Create site
<context-refs>P9.D-01,P9.D-02</context-refs>
<file-path>apps/api/src/modules/sites/routes.ts</file-path>
Implement POST /api/v1/sites endpoint.

## Task 02: Create route handler
<context-refs>P9.D-01</context-refs>
<file-path>apps/api/src/modules/sites/handler.ts</file-path>
Handler logic.
"""
    context = """\
### P9.D-01: Use Fastify route registration
Decision: use fastify.route() pattern.

### P9.D-02: MongoDB native driver
Decision: no Mongoose, use native driver.
"""
    repo = _setup(tmp_path, plan, context)
    r = _run(repo)
    out = _parse(r.stdout)
    assert r.returncode == 0


# ─── Test: scoped mode missing refs warns (not blocks) ───────────────────────

def test_scoped_mode_missing_refs_warns(tmp_path):
    """scoped mode + task missing <context-refs> → WARN (rc=0, verdict=WARN)."""
    plan = """\
## Task 01: Create site
<file-path>apps/api/src/modules/sites/routes.ts</file-path>
Implement POST /api/v1/sites endpoint.
"""
    repo = _setup(tmp_path, plan)
    r = _run(repo)
    out = _parse(r.stdout)
    assert r.returncode == 0, "Missing refs must WARN not BLOCK"
    assert out["verdict"] == "WARN"
    assert any(e["type"] == "context_refs_missing" for e in out["evidence"])


# ─── Test: stale refs warns ───────────────────────────────────────────────────

def test_scoped_mode_stale_refs_warns(tmp_path):
    """<context-refs> cites D-99 not in CONTEXT.md → WARN."""
    plan = """\
## Task 01: Create site
<context-refs>P9.D-99</context-refs>
<file-path>apps/api/src/modules/sites/routes.ts</file-path>
Implement endpoint.
"""
    context = "### P9.D-01: Use Fastify\nDecision: fastify.\n"
    repo = _setup(tmp_path, plan, context)
    r = _run(repo)
    out = _parse(r.stdout)
    assert r.returncode == 0
    assert any(e["type"] == "context_refs_stale" for e in out["evidence"])


# ─── Test: no PLAN.md → skip (PASS) ──────────────────────────────────────────

def test_no_plan_skips(tmp_path):
    """No PLAN.md in phase dir → PASS (skip, nothing to check)."""
    phase_dir = tmp_path / ".vg" / "phases" / "09-test"
    phase_dir.mkdir(parents=True)
    cfg = tmp_path / ".claude" / "vg.config.md"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text('---\nprofile: web-fullstack\ncontext_injection:\n  mode: "scoped"\n', encoding="utf-8")
    src = REPO_ROOT / ".claude" / "commands" / "vg" / "_shared"
    dst = tmp_path / ".claude" / "commands" / "vg" / "_shared"
    dst.mkdir(parents=True, exist_ok=True)
    for name in ("narration-strings.yaml", "narration-strings-validators.yaml"):
        s = src / name
        if s.exists():
            (dst / name).write_text(s.read_text(encoding="utf-8"), encoding="utf-8")
    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(tmp_path)
    r = subprocess.run(
        [sys.executable, str(VALIDATOR), "--phase", "9"],
        cwd=tmp_path, capture_output=True, text=True, timeout=10, env=env,
    )
    assert r.returncode == 0


# ─── Test: multiple tasks mixed refs ──────────────────────────────────────────

def test_mixed_tasks_partial_refs_warns(tmp_path):
    """2 tasks: task 1 has refs, task 2 doesn't → WARN (missing count = 1)."""
    plan = """\
## Task 01: Create site
<context-refs>P9.D-01</context-refs>
<file-path>routes.ts</file-path>
With refs.

## Task 02: Create handler
<file-path>handler.ts</file-path>
No refs.
"""
    context = "### P9.D-01: Fastify\nDecision.\n"
    repo = _setup(tmp_path, plan, context)
    r = _run(repo)
    out = _parse(r.stdout)
    assert r.returncode == 0
    ev = [e for e in out["evidence"] if e["type"] == "context_refs_missing"]
    assert ev, "Should warn about missing refs"
    assert "Task 02" in ev[0]["actual"] or "02" in ev[0]["actual"]


# ─── Integration: build.md has DECISION_CONTEXT + scoped injection ────────────

class TestBuildMdContextInjection:
    def test_decision_context_var_declared(self):
        """DECISION_CONTEXT variable must be declared in step 8c."""
        text = BUILD_MD.read_text(encoding="utf-8")
        assert "DECISION_CONTEXT" in text, (
            "build.md step 8c missing DECISION_CONTEXT variable"
        )

    def test_scoped_mode_branch_present(self):
        """CTX_INJECT_MODE=scoped branch must be present."""
        text = BUILD_MD.read_text(encoding="utf-8")
        assert "CTX_INJECT_MODE" in text
        assert '"scoped"' in text or "'scoped'" in text

    def test_context_refs_extraction_present(self):
        """Build.md must extract <context-refs> from task file."""
        text = BUILD_MD.read_text(encoding="utf-8")
        assert "context-refs" in text, (
            "build.md step 8c missing <context-refs> extraction"
        )

    def test_fallback_on_missing_refs(self):
        """scoped_fallback_on_missing: true → inject full CONTEXT when refs absent."""
        text = BUILD_MD.read_text(encoding="utf-8")
        assert "scoped_fallback_on_missing" in text or "fallback" in text.lower()

    def test_decision_context_injected_into_executor_prompt(self):
        """<decision_context> block must appear in executor Agent() prompt."""
        text = BUILD_MD.read_text(encoding="utf-8")
        assert "<decision_context>" in text
        assert "DECISION_CONTEXT" in text
        # Must be in the Agent() prompt section
        agent_section = text[text.find("Agent(subagent_type"):]
        assert "<decision_context>" in agent_section[:3000], (
            "<decision_context> must be inside executor Agent() prompt"
        )

    def test_phase_cutover_auto_upgrade(self):
        """Phases >= phase_cutover must auto-upgrade to scoped mode."""
        text = BUILD_MD.read_text(encoding="utf-8")
        assert "phase_cutover" in text or "CTX_CUTOVER" in text


# ─── Integration: blueprint.md planner instruction for context-refs ───────────

class TestBlueprintContextRefsInstruction:
    def test_context_refs_instruction_in_2a(self):
        """blueprint.md step 2a must instruct planner to emit <context-refs>."""
        text = BLUEPRINT_MD.read_text(encoding="utf-8")
        assert "<context-refs>" in text, (
            "blueprint.md step 2a missing <context-refs> planner instruction"
        )

    def test_example_format_present(self):
        """Must show example format P{phase}.D-XX."""
        text = BLUEPRINT_MD.read_text(encoding="utf-8")
        # Check for example with P7.14.D-02 or P{phase}.D-XX pattern
        assert re.search(r"P\{?phase\}?\.D-\d+|P7\.\d+\.D-\d+", text), (
            "blueprint.md missing example of P{phase}.D-XX context-ref format"
        )

    def test_max_refs_per_task_guidance(self):
        """Planner must be told max refs per task to prevent over-citing."""
        text = BLUEPRINT_MD.read_text(encoding="utf-8")
        assert "maximum" in text.lower() or "max" in text.lower(), (
            "blueprint.md missing max-refs-per-task guidance"
        )


# ─── Integration: vg-executor-rules.md clarifies decision_context ─────────────

class TestExecutorRulesDecisionContext:
    def test_decision_context_step_listed(self):
        """Executor flow must list <decision_context> as step 1."""
        text = EXECUTOR_RULES.read_text(encoding="utf-8")
        assert "<decision_context>" in text, (
            "vg-executor-rules.md missing <decision_context> in execution flow"
        )

    def test_decision_context_rule_present(self):
        """Executor rules must clarify not to open CONTEXT.md directly."""
        text = EXECUTOR_RULES.read_text(encoding="utf-8")
        assert "Do NOT open" in text or "not open" in text.lower() or \
               "bypass" in text, (
            "executor-rules missing instruction to not read CONTEXT.md directly"
        )

    def test_scoped_injection_note_present(self):
        """Executor rules must explain scoped vs full injection."""
        text = EXECUTOR_RULES.read_text(encoding="utf-8")
        assert "scoped" in text.lower()
        assert "full" in text.lower()


# ─── Integration: orchestrator has verify-context-refs in blueprint ────────────

def test_registered_in_blueprint_validators():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "vg_orchestrator_main",
        REPO_ROOT / ".claude" / "scripts" / "vg-orchestrator" / "__main__.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["vg_orchestrator_main"] = mod
    try:
        spec.loader.exec_module(mod)
    except SystemExit:
        pass
    assert "verify-context-refs" in mod.COMMAND_VALIDATORS.get("vg:blueprint", []), (
        "verify-context-refs not registered in vg:blueprint validators"
    )


def test_validator_script_exists():
    assert VALIDATOR.exists(), f"verify-context-refs.py not found: {VALIDATOR}"
