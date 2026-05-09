"""v2.66.0 Task 2 (#150) — Codex CLI invoke template must include --skip-git-repo-check.

Codex v0.118.0+ rejects isolated cwd without this flag. The build-crossai-loop
script already includes it; the shared invoke template must too for parity.
"""
from pathlib import Path


REPO_ROOT = Path(__file__).parent.parent


def test_codex_template_has_skip_git_repo_check():
    """commands/vg/_shared/crossai-invoke.md codex template line must include flag."""
    body = (REPO_ROOT / "commands" / "vg" / "_shared" / "crossai-invoke.md").read_text(encoding="utf-8")
    codex_lines = [l for l in body.splitlines() if "codex exec" in l]
    assert codex_lines, "codex exec template not found in invoke spec"
    for line in codex_lines:
        assert "--skip-git-repo-check" in line, (
            f"Codex template missing --skip-git-repo-check: {line!r}"
        )


def test_codex_template_mirror_has_skip_git_repo_check():
    """.claude mirror must match — byte-identity rule."""
    body = (REPO_ROOT / ".claude" / "commands" / "vg" / "_shared" / "crossai-invoke.md").read_text(encoding="utf-8")
    codex_lines = [l for l in body.splitlines() if "codex exec" in l]
    assert codex_lines, "codex exec template not found in mirrored invoke spec"
    for line in codex_lines:
        assert "--skip-git-repo-check" in line, (
            f"Mirror codex template missing --skip-git-repo-check: {line!r}"
        )


def test_build_crossai_loop_keeps_flag():
    """vg-build-crossai-loop.py already has flag — regression guard (parity baseline)."""
    body = (REPO_ROOT / "scripts" / "vg-build-crossai-loop.py").read_text(encoding="utf-8")
    assert "--skip-git-repo-check" in body, (
        "vg-build-crossai-loop.py must keep --skip-git-repo-check (parity baseline for #150)"
    )
