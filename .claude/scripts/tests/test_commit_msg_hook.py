"""
B7.1 — commit-msg hook tests.

Validates that `commit-attribution.py --staged-only --msg-file <file>`
blocks phantom D-XX/G-XX citations + malformed subjects AT COMMIT TIME
(not 30-60min later at run-complete).

Before B7.1: phantom citation slips into git history → commit-attribution
runs at /vg:build run-complete → BLOCKS → but commit already immutable.
After B7.1: commit-msg hook runs validator synchronously before git writes
the commit → rc=1 aborts the write → history stays clean.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
VALIDATOR = REPO_ROOT / ".claude" / "scripts" / "validators" / "commit-attribution.py"


def _git_available() -> bool:
    try:
        r = subprocess.run(["git", "--version"], capture_output=True, timeout=3)
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


pytestmark = pytest.mark.skipif(
    not _git_available(),
    reason="git not available for commit-msg hook tests",
)


def _setup_repo(tmp_path: Path) -> tuple[Path, Path]:
    """Initialize a mini git repo with .vg/phases/07.6-test-phase/ containing
    CONTEXT.md (with D-01 and D-02) and TEST-GOALS.md (with G-01 and G-02).

    Returns (repo_root, phase_dir).
    """
    subprocess.run(["git", "init", "-q", "-b", "main"],
                   cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@vg.local"],
                   cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "VG Test"],
                   cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"],
                   cwd=tmp_path, check=True)

    phase_dir = tmp_path / ".vg" / "phases" / "07.6-test-phase"
    phase_dir.mkdir(parents=True)
    (phase_dir / "CONTEXT.md").write_text(
        "# Phase 7.6 context\n\n"
        "### D-01: First decision\n\n"
        "Reason: ...\n\n"
        "### D-02: Second decision\n\n"
        "Reason: ...\n",
        encoding="utf-8",
    )
    (phase_dir / "TEST-GOALS.md").write_text(
        "# Phase 7.6 test goals\n\n"
        "### G-01: First goal\n\n"
        "### G-02: Second goal\n",
        encoding="utf-8",
    )

    # Code file — triggers code-path citation requirement
    code_dir = tmp_path / "apps" / "api" / "src"
    code_dir.mkdir(parents=True)
    (code_dir / "routes.ts").write_text("export const x = 1;\n", encoding="utf-8")

    # Doc file — planning-only, no citation required
    (tmp_path / "README.md").write_text("# repo\n", encoding="utf-8")

    return tmp_path, phase_dir


def _run_validator(repo: Path, msg: str, *, tmp_path: Path) -> subprocess.CompletedProcess:
    msg_file = tmp_path / "COMMIT_EDITMSG"
    msg_file.write_text(msg, encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(VALIDATOR),
         "--staged-only", "--msg-file", str(msg_file)],
        cwd=repo, capture_output=True, text=True, timeout=30,
    )


def _stage(repo: Path, *paths: str) -> None:
    subprocess.run(["git", "add", "--"] + list(paths),
                   cwd=repo, check=True, capture_output=True)


# ─────────────────────────────────────────────────────────────────────────

def test_valid_d_xx_passes(tmp_path):
    """Commit with real D-01 citation → PASS (rc=0)."""
    repo, _ = _setup_repo(tmp_path)
    _stage(repo, "apps/api/src/routes.ts")

    r = _run_validator(
        repo,
        "feat(7.6-01): add routes handler\n\nPer CONTEXT.md D-01\n",
        tmp_path=tmp_path,
    )
    assert r.returncode == 0, f"expected PASS, got rc={r.returncode}\nstdout={r.stdout}\nstderr={r.stderr}"


def test_phantom_d_xx_blocks(tmp_path):
    """Commit cites D-99 (doesn't exist) → BLOCK (rc=1)."""
    repo, _ = _setup_repo(tmp_path)
    _stage(repo, "apps/api/src/routes.ts")

    r = _run_validator(
        repo,
        "feat(7.6-01): add routes handler\n\nPer CONTEXT.md D-99\n",
        tmp_path=tmp_path,
    )
    assert r.returncode == 1, f"expected BLOCK, got rc={r.returncode}\nstdout={r.stdout}"
    assert "phantom_citation" in r.stdout


def test_phantom_g_xx_blocks(tmp_path):
    """Commit claims to cover G-42 (doesn't exist) → BLOCK."""
    repo, _ = _setup_repo(tmp_path)
    _stage(repo, "apps/api/src/routes.ts")

    r = _run_validator(
        repo,
        "feat(7.6-02): add handler\n\nCovers goal: G-42\n",
        tmp_path=tmp_path,
    )
    assert r.returncode == 1
    assert "phantom_citation" in r.stdout


def test_no_goal_impact_passes(tmp_path):
    """Explicit `no-goal-impact` → PASS."""
    repo, _ = _setup_repo(tmp_path)
    _stage(repo, "apps/api/src/routes.ts")

    r = _run_validator(
        repo,
        "chore(7.6-03): bump deps\n\nno-goal-impact\n",
        tmp_path=tmp_path,
    )
    assert r.returncode == 0, f"rc={r.returncode} stdout={r.stdout}"


def test_docs_only_commit_no_citation_needed(tmp_path):
    """Commit touching only README.md → no citation required → PASS."""
    repo, _ = _setup_repo(tmp_path)
    _stage(repo, "README.md")

    r = _run_validator(
        repo,
        "docs(7.6-04): update README\n\nExplain setup steps.\n",
        tmp_path=tmp_path,
    )
    assert r.returncode == 0, f"rc={r.returncode} stdout={r.stdout}"


def test_malformed_subject_blocks(tmp_path):
    """Subject without `feat(X.Y-NN):` pattern → BLOCK."""
    repo, _ = _setup_repo(tmp_path)
    _stage(repo, "apps/api/src/routes.ts")

    r = _run_validator(
        repo,
        "added new handler\n\nSome body\n",
        tmp_path=tmp_path,
    )
    assert r.returncode == 1
    assert "subject_format_violation" in r.stdout


def test_body_with_no_verify_blocks(tmp_path):
    """Body mentioning `--no-verify` → BLOCK (bypass red flag)."""
    repo, _ = _setup_repo(tmp_path)
    _stage(repo, "apps/api/src/routes.ts")

    r = _run_validator(
        repo,
        "feat(7.6-05): fix tests\n\n"
        "Per CONTEXT.md D-01\n"
        "Had to use --no-verify due to broken pre-commit.\n",
        tmp_path=tmp_path,
    )
    assert r.returncode == 1
    assert "bypass_red_flag" in r.stdout


def test_body_describing_no_verify_without_intent_passes(tmp_path):
    """Describing --no-verify as a feature/flag (not bypass intent) → PASS.
    Smartened BYPASS_RE requires action verb proximity to trigger block."""
    repo, _ = _setup_repo(tmp_path)
    _stage(repo, "apps/api/src/routes.ts")

    r = _run_validator(
        repo,
        "feat(7.6-08): document --no-verify behavior\n\n"
        "Per CONTEXT.md D-01\n\n"
        "The hook respects --no-verify per git convention.\n",
        tmp_path=tmp_path,
    )
    assert r.returncode == 0, f"rc={r.returncode} stdout={r.stdout}"


def test_code_commit_missing_citation_blocks(tmp_path):
    """Code change without any citation → BLOCK."""
    repo, _ = _setup_repo(tmp_path)
    _stage(repo, "apps/api/src/routes.ts")

    r = _run_validator(
        repo,
        "feat(7.6-06): add handler\n\nSome random body, no citation.\n",
        tmp_path=tmp_path,
    )
    assert r.returncode == 1
    assert "missing_citation" in r.stdout


def test_block_emits_human_readable_stderr(tmp_path):
    """v2.5.2.6: when hook BLOCKs, stderr must carry human-readable guidance
    (distilled from Evidence.message + fix_hint) in addition to JSON on
    stdout. Users reading `git commit` output see the guidance."""
    repo, _ = _setup_repo(tmp_path)
    _stage(repo, "apps/api/src/routes.ts")

    r = _run_validator(
        repo,
        "feat(7.6-06): add handler\n\nSome random body, no citation.\n",
        tmp_path=tmp_path,
    )
    assert r.returncode == 1
    # stdout still has canonical JSON for orchestrator
    assert "missing_citation" in r.stdout
    assert "verdict" in r.stdout
    # stderr now has multi-line human guidance
    assert "Commit blocked" in r.stderr
    assert "missing_citation" in r.stderr  # evidence type surfaced
    assert "Retry:" in r.stderr
    assert "git commit --amend" in r.stderr  # retry instruction present
    # NOTE: Evidence.message + fix_hint content flow through `t()` i18n,
    # which reads narration-strings-validators.yaml relative to
    # VG_REPO_ROOT. In this test VG_REPO_ROOT → tmp git repo (isolated,
    # no yaml) so `t()` falls back to key literal. In prod (real repo),
    # users see the localized fix_hint which enumerates citation patterns.
    # Hardcoded framing (above) is what we verify is always present.


def test_pass_does_not_emit_stderr_guidance(tmp_path):
    """v2.5.2.6: PASS verdict → stderr stays clean (don't spam on success)."""
    repo, _ = _setup_repo(tmp_path)
    _stage(repo, "apps/api/src/routes.ts")

    r = _run_validator(
        repo,
        "feat(7.6-06): add handler\n\nPer API-CONTRACTS.md\n",
        tmp_path=tmp_path,
    )
    assert r.returncode == 0
    # No guidance block printed on success
    assert "Commit blocked" not in r.stderr


def test_empty_message_blocks(tmp_path):
    """Empty commit message → BLOCK."""
    repo, _ = _setup_repo(tmp_path)
    _stage(repo, "apps/api/src/routes.ts")

    r = _run_validator(
        repo,
        "",
        tmp_path=tmp_path,
    )
    assert r.returncode == 1
    assert "empty_message" in r.stdout


def test_valid_api_contracts_citation_passes(tmp_path):
    """`Per API-CONTRACTS.md` citation → PASS (no specific D-XX check)."""
    repo, _ = _setup_repo(tmp_path)
    _stage(repo, "apps/api/src/routes.ts")

    r = _run_validator(
        repo,
        "feat(7.6-07): add endpoint\n\nPer API-CONTRACTS.md\n",
        tmp_path=tmp_path,
    )
    assert r.returncode == 0


def test_brand_new_phase_without_context_still_runs(tmp_path):
    """Phase directory exists but no artifacts yet — phantom check skipped,
    but citation requirement still holds. Generic citation passes."""
    subprocess.run(["git", "init", "-q", "-b", "main"],
                   cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@x"],
                   cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"],
                   cwd=tmp_path, check=True)

    # Code file with no phase dir existing at all
    code_dir = tmp_path / "apps" / "api" / "src"
    code_dir.mkdir(parents=True)
    (code_dir / "x.ts").write_text("const x = 1;\n", encoding="utf-8")
    subprocess.run(["git", "add", "apps/api/src/x.ts"],
                   cwd=tmp_path, check=True, capture_output=True)

    # Cite D-05 for a phase that doesn't exist on disk
    msg_file = tmp_path / "COMMIT_EDITMSG"
    msg_file.write_text(
        "feat(99.1-01): bootstrap\n\nPer CONTEXT.md D-05\n",
        encoding="utf-8",
    )
    r = subprocess.run(
        [sys.executable, str(VALIDATOR),
         "--staged-only", "--msg-file", str(msg_file)],
        cwd=tmp_path, capture_output=True, text=True, timeout=30,
    )
    # Phase dir not resolvable → phantom check skipped → PASS
    assert r.returncode == 0, f"expected PASS for unresolvable phase, got rc={r.returncode}\n{r.stdout}"


def test_args_error_when_msg_file_missing(tmp_path):
    """--staged-only without --msg-file → BLOCK with clear error."""
    r = subprocess.run(
        [sys.executable, str(VALIDATOR), "--staged-only"],
        cwd=tmp_path, capture_output=True, text=True, timeout=10,
    )
    assert r.returncode == 1
    assert "args_error" in r.stdout


def test_meta_scope_vg_passes(tmp_path):
    """`chore(vg): ...` with no code change → PASS (meta commit, no phase)."""
    repo, _ = _setup_repo(tmp_path)
    _stage(repo, "README.md")

    r = _run_validator(
        repo,
        "chore(vg): bump harness version\n\nNo-impact meta change.\n",
        tmp_path=tmp_path,
    )
    assert r.returncode == 0, f"rc={r.returncode} stdout={r.stdout}"


def test_meta_scope_with_phantom_citation_ignored(tmp_path):
    """`chore(vg): ...` + phantom D-99 → PASS.
    Meta commits skip phantom detection (no phase attribution)."""
    repo, _ = _setup_repo(tmp_path)
    _stage(repo, "README.md")

    r = _run_validator(
        repo,
        "chore(vg): bump version\n\nPer CONTEXT.md D-99 (ignored for meta)\n",
        tmp_path=tmp_path,
    )
    assert r.returncode == 0


def test_meta_scope_touching_code_still_needs_citation(tmp_path):
    """`chore(infra): ...` touching apps/api/src without citation → BLOCK.
    Code-touching rule applies to meta commits too."""
    repo, _ = _setup_repo(tmp_path)
    _stage(repo, "apps/api/src/routes.ts")

    r = _run_validator(
        repo,
        "chore(infra): tweak routes\n\nNo citation here.\n",
        tmp_path=tmp_path,
    )
    assert r.returncode == 1
    assert "missing_citation" in r.stdout


def test_legacy_phase_mode_still_works(tmp_path):
    """Back-compat: --phase N mode (no --staged-only) unchanged."""
    repo, _ = _setup_repo(tmp_path)
    # No commits yet — validator should emit WARN (0 commits) and exit 0
    r = subprocess.run(
        [sys.executable, str(VALIDATOR), "--phase", "7.6"],
        cwd=repo, capture_output=True, text=True, timeout=10,
    )
    assert r.returncode == 0
    assert '"verdict": "WARN"' in r.stdout or '"verdict": "PASS"' in r.stdout
