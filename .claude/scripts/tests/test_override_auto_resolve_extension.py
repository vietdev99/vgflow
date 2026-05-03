"""
Tests for v2.7 Phase M — override_auto_resolve_clean_run extension to 5
new gate_ids (allow-orthogonal-hotfix, allow-no-bugref, allow-empty-hotfix,
allow-empty-bugfix, allow-unresolved-overrides).

Each test exercises the helper directly via bash and verifies:
1. The matching OPEN debt entry transitions to RESOLVED.
2. The Resolved-By-Event column is populated.
3. The change is visible in the rewritten register file.

Tests are scoped via VG_REPO_ROOT so they don't touch the real
.vg/OVERRIDE-DEBT.md. Each test creates a synthetic register, sources
the helper, runs the resolution call, and asserts file state.

Phase C compat (rule-retire) is preserved by leaving --target rule-retire
branch untouched in the helper; not exercised here (covered by Phase C
tests). Backward compat for the 3 v2.6.1 gate_ids is also unchanged.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
HELPER = REPO_ROOT / ".claude" / "commands" / "vg" / "_shared" / "lib" / \
    "override-debt.sh"

# Five gate_ids added in Phase M.
GATE_IDS = [
    "allow-orthogonal-hotfix",
    "allow-no-bugref",
    "allow-empty-hotfix",
    "allow-empty-bugfix",
    "allow-unresolved-overrides",
]


def _bash_available() -> bool:
    """Probe whether bash is callable; tests skip if not."""
    bash = shutil.which("bash")
    if not bash:
        return False
    try:
        r = subprocess.run([bash, "-c", "echo ok"],
                           capture_output=True, text=True, timeout=10)
        return r.returncode == 0 and "ok" in r.stdout
    except (OSError, subprocess.SubprocessError):
        return False


BASH_AVAILABLE = _bash_available()
pytestmark = pytest.mark.skipif(
    not BASH_AVAILABLE,
    reason="bash not available — Phase M helper requires bash subprocess",
)


def _make_register(tmp_path: Path, gate_id: str,
                   debt_id: str = "DEBT-20260420000000-1",
                   phase: str = "7.0") -> Path:
    """Create a synthetic OVERRIDE-DEBT.md with one OPEN entry for gate_id."""
    register = tmp_path / "OVERRIDE-DEBT.md"
    register.write_text(
        "# Override Debt Register\n\n"
        "## Entries\n\n"
        "| ID | Severity | Phase | Step | Flag | Reason | Logged (UTC) | "
        "Status | Gate ID | Resolved-By-Event | Legacy |\n"
        "|----|----------|-------|------|------|--------|--------------|"
        "--------|---------|-------------------|--------|\n"
        f"| {debt_id} | medium | {phase} | review | `--{gate_id}` | "
        f"test reason | 2026-04-20T00:00:00Z | OPEN | {gate_id} |  | "
        "false |\n",
        encoding="utf-8",
    )
    return register


def _resolve(register: Path, gate_id: str, current_phase: str,
             event_id: str) -> subprocess.CompletedProcess:
    """Source helper + run override_auto_resolve_clean_run via bash."""
    # Use bare command names so bash can resolve via PATH; full Windows
    # paths with spaces break unquoted ${PYTHON_BIN} expansion in the
    # helper's python heredoc. PATH lookup is deterministic enough for
    # CI + dev — both Linux and Windows ship `python` on PATH.
    py = "python" if shutil.which("python") else "python3"
    bash = shutil.which("bash") or "bash"
    cmd = (
        f'export CONFIG_DEBT_REGISTER_PATH="{register}";'
        f'export PYTHON_BIN="{py}";'
        f'source "{HELPER}";'
        f'override_auto_resolve_clean_run "{gate_id}" "{current_phase}" '
        f'"{event_id}"'
    )
    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(REPO_ROOT)
    return subprocess.run(
        [bash, "-c", cmd],
        capture_output=True, text=True, timeout=30, env=env,
        encoding="utf-8", errors="replace",
    )


def _read_status_for(register: Path, debt_id: str) -> tuple[str, str]:
    """Return (status, resolved_by_event) for a given debt row."""
    text = register.read_text(encoding="utf-8")
    for line in text.splitlines():
        if debt_id in line:
            cols = [c.strip() for c in line.split("|")]
            # | ID | Sev | Phase | Step | Flag | Reason | TS | Status | Gate | RBE | Legacy |
            # split() yields leading & trailing empty cols around pipes
            if len(cols) >= 11:
                return cols[8], cols[10]
    return "MISSING", ""


class TestOverrideAutoResolveExtensionPhaseM:
    """One test per gate_id — exercises the helper end-to-end."""

    def test_allow_orthogonal_hotfix_resolves(self, tmp_path):
        """allow-orthogonal-hotfix → resolves when next-phase review PASSes
        on same component (no hotfix flag)."""
        register = _make_register(tmp_path, "allow-orthogonal-hotfix",
                                  debt_id="DEBT-20260420010000-1",
                                  phase="7.0")
        r = _resolve(register, "allow-orthogonal-hotfix",
                     current_phase="7.1",
                     event_id="review-clean-7.1-test-1")
        assert r.returncode == 0, f"helper rc={r.returncode}\n{r.stderr}"
        status, rbe = _read_status_for(register, "DEBT-20260420010000-1")
        assert status == "RESOLVED", \
            f"expected RESOLVED, got {status}\nstderr: {r.stderr}"
        assert rbe == "review-clean-7.1-test-1", \
            f"expected event id, got '{rbe}'"

    def test_allow_no_bugref_resolves(self, tmp_path):
        """allow-no-bugref → resolves when subsequent commit has bugref
        on same component (review pass on next phase)."""
        register = _make_register(tmp_path, "allow-no-bugref",
                                  debt_id="DEBT-20260420020000-2",
                                  phase="7.0")
        r = _resolve(register, "allow-no-bugref",
                     current_phase="7.1",
                     event_id="review-clean-7.1-test-2")
        assert r.returncode == 0, f"helper rc={r.returncode}\n{r.stderr}"
        status, rbe = _read_status_for(register, "DEBT-20260420020000-2")
        assert status == "RESOLVED", \
            f"expected RESOLVED, got {status}\nstderr: {r.stderr}"
        assert rbe == "review-clean-7.1-test-2"

    def test_allow_empty_hotfix_resolves(self, tmp_path):
        """allow-empty-hotfix → resolves when subsequent commit has
        non-empty hotfix message."""
        register = _make_register(tmp_path, "allow-empty-hotfix",
                                  debt_id="DEBT-20260420030000-3",
                                  phase="7.0")
        r = _resolve(register, "allow-empty-hotfix",
                     current_phase="7.1",
                     event_id="review-clean-7.1-test-3")
        assert r.returncode == 0, f"helper rc={r.returncode}\n{r.stderr}"
        status, rbe = _read_status_for(register, "DEBT-20260420030000-3")
        assert status == "RESOLVED", \
            f"expected RESOLVED, got {status}\nstderr: {r.stderr}"
        assert rbe == "review-clean-7.1-test-3"

    def test_allow_empty_bugfix_resolves(self, tmp_path):
        """allow-empty-bugfix → resolves when subsequent commit has
        non-empty bugfix message."""
        register = _make_register(tmp_path, "allow-empty-bugfix",
                                  debt_id="DEBT-20260420040000-4",
                                  phase="7.0")
        r = _resolve(register, "allow-empty-bugfix",
                     current_phase="7.1",
                     event_id="review-clean-7.1-test-4")
        assert r.returncode == 0, f"helper rc={r.returncode}\n{r.stderr}"
        status, rbe = _read_status_for(register, "DEBT-20260420040000-4")
        assert status == "RESOLVED", \
            f"expected RESOLVED, got {status}\nstderr: {r.stderr}"
        assert rbe == "review-clean-7.1-test-4"

    def test_allow_unresolved_overrides_resolves(self, tmp_path):
        """allow-unresolved-overrides → resolves when next phase exits
        with 0 unresolved overrides."""
        register = _make_register(tmp_path, "allow-unresolved-overrides",
                                  debt_id="DEBT-20260420050000-5",
                                  phase="7.0")
        r = _resolve(register, "allow-unresolved-overrides",
                     current_phase="7.1",
                     event_id="review-clean-7.1-test-5")
        assert r.returncode == 0, f"helper rc={r.returncode}\n{r.stderr}"
        status, rbe = _read_status_for(register, "DEBT-20260420050000-5")
        assert status == "RESOLVED", \
            f"expected RESOLVED, got {status}\nstderr: {r.stderr}"
        assert rbe == "review-clean-7.1-test-5"


class TestPhaseMGuards:
    """Backward-compat + edge-case guards."""

    def test_same_phase_does_not_resolve(self, tmp_path):
        """If current_phase == debt entry phase, helper must NOT resolve
        (the phase that logged the override is also the one being checked)."""
        register = _make_register(tmp_path, "allow-orthogonal-hotfix",
                                  debt_id="DEBT-20260420060000-6",
                                  phase="7.0")
        r = _resolve(register, "allow-orthogonal-hotfix",
                     current_phase="7.0",  # SAME as debt entry phase
                     event_id="review-clean-7.0-noop")
        assert r.returncode == 0
        status, rbe = _read_status_for(register, "DEBT-20260420060000-6")
        # Should remain OPEN — same-phase guard prevents auto-resolution
        assert status == "OPEN", \
            f"same-phase guard failed: status={status}, rbe={rbe}"

    def test_phase_c_rule_retire_branch_still_works(self, tmp_path):
        """Phase C `--target rule-retire` branch must continue to function
        unchanged — backward compat smoke."""
        candidates = tmp_path / "CANDIDATES.md"
        candidates.write_text(
            "```yaml\nid: L-099\ntitle: Test rule\n```\n",
            encoding="utf-8",
        )
        # Bare command name so bash resolves via PATH (full Windows paths
        # with spaces break unquoted ${PYTHON_BIN} expansion in helper).
        py = "python" if shutil.which("python") else "python3"
        bash = shutil.which("bash") or "bash"
        cmd = (
            f'export CONFIG_BOOTSTRAP_CANDIDATES_PATH="{candidates}";'
            f'export PYTHON_BIN="{py}";'
            f'source "{HELPER}";'
            f'override_auto_resolve_clean_run --target rule-retire L-099 '
            f'"winner=L-100 phase-m-compat-test"'
        )
        env = os.environ.copy()
        env["VG_REPO_ROOT"] = str(REPO_ROOT)
        r = subprocess.run(
            [bash, "-c", cmd],
            capture_output=True, text=True, timeout=30, env=env,
            encoding="utf-8", errors="replace",
        )
        assert r.returncode == 0, f"rule-retire smoke rc={r.returncode}\n{r.stderr}"
        body = candidates.read_text(encoding="utf-8")
        assert "RETIRED_BY_CONFLICT" in body, \
            f"rule-retire failed to mark candidate: {body}"
        assert "L-100" in body, "winner ID not recorded"
