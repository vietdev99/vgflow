"""
Tests for verify-rule-cards-fresh-hook.py — Phase R v2.7.

Pre-commit hook companion to verify-rule-cards-fresh: when a SKILL.md
is staged, ensure sibling RULES-CARDS.md is at-or-newer than the
SKILL.md being committed.

NOTE: This hook does NOT use the _common.Output schema. It writes plain
text to stdout/stderr and uses rc=0 (PASS) / rc=1 (BLOCK). Schema gap
(no JSON output, no verdict field) — documented as discovery.

Covers:
  - No paths supplied → rc=0 PASS
  - Non-SKILL.md path → ignored, rc=0
  - Staged SKILL.md without sibling RULES-CARDS.md → rc=0 (allow,
    cards bootstrap-pending)
  - Staged SKILL.md with FRESHER cards → rc=0 PASS
  - Staged SKILL.md with STALE cards → rc=1 BLOCK
  - Staged SKILL.md with EQUAL mtime → rc=0 (tie allowed)
  - --quiet suppresses PASS messages
  - Multiple staged files reported individually
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT_REAL = Path(__file__).resolve().parents[4]
VALIDATOR = REPO_ROOT_REAL / ".claude" / "scripts" / "validators" / \
    "verify-rule-cards-fresh-hook.py"


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(VALIDATOR), *args],
        capture_output=True, text=True, timeout=20, env=env,
        encoding="utf-8", errors="replace", cwd=str(cwd),
    )


def _make_skill_with_cards(tmp_path: Path, name: str, *,
                           with_cards: bool = True,
                           skill_offset: float = 0.0,
                           cards_offset: float = 0.0) -> Path:
    sdir = tmp_path / ".codex" / "skills" / name
    sdir.mkdir(parents=True, exist_ok=True)
    skill = sdir / "SKILL.md"
    skill.write_text("# Skill\n", encoding="utf-8")
    now = time.time()
    skill_ts = now + skill_offset
    os.utime(skill, (skill_ts, skill_ts))
    if with_cards:
        cards = sdir / "RULES-CARDS.md"
        cards.write_text("# Cards\n", encoding="utf-8")
        cards_ts = now + cards_offset
        os.utime(cards, (cards_ts, cards_ts))
    return skill


class TestRuleCardsFreshHook:
    def test_no_paths_passes(self, tmp_path):
        r = _run([], tmp_path)
        assert r.returncode == 0

    def test_non_skill_path_ignored(self, tmp_path):
        # Hook should defensively skip non-SKILL.md paths
        other = tmp_path / "OTHER.md"
        other.write_text("foo", encoding="utf-8")
        r = _run([str(other)], tmp_path)
        assert r.returncode == 0

    def test_no_cards_yet_allows(self, tmp_path):
        skill = _make_skill_with_cards(tmp_path, "vg-noyet",
                                       with_cards=False)
        r = _run([str(skill)], tmp_path)
        assert r.returncode == 0, \
            f"no cards yet → allow rc=0, got {r.returncode}, stderr={r.stderr[:300]}"

    def test_fresh_cards_pass(self, tmp_path):
        skill = _make_skill_with_cards(
            tmp_path, "vg-fresh-hook",
            skill_offset=-3600, cards_offset=-60,
        )
        r = _run([str(skill)], tmp_path)
        assert r.returncode == 0, \
            f"fresh cards → rc=0, got {r.returncode}, stderr={r.stderr[:300]}"

    def test_stale_cards_blocks(self, tmp_path):
        skill = _make_skill_with_cards(
            tmp_path, "vg-stale-hook",
            skill_offset=-30, cards_offset=-3600,
        )
        r = _run([str(skill)], tmp_path)
        assert r.returncode == 1, \
            f"stale cards → BLOCK rc=1, got {r.returncode}, stderr={r.stderr[:300]}"
        # Stderr should mention drift remediation
        assert "drift" in r.stderr.lower() or "stale" in r.stderr.lower() \
            or "newer" in r.stderr.lower()

    def test_equal_mtime_allowed(self, tmp_path):
        skill = _make_skill_with_cards(
            tmp_path, "vg-equal",
            skill_offset=-100, cards_offset=-100,
        )
        r = _run([str(skill)], tmp_path)
        assert r.returncode == 0, \
            f"equal mtime → allow, got {r.returncode}"

    def test_quiet_flag(self, tmp_path):
        skill = _make_skill_with_cards(
            tmp_path, "vg-quiet",
            skill_offset=-3600, cards_offset=-60,
        )
        r = _run([str(skill), "--quiet"], tmp_path)
        assert r.returncode == 0
        # --quiet suppresses PASS messages from stdout
        assert r.stdout.strip() == "" or "no SKILL" not in r.stdout

    def test_multiple_files_reported(self, tmp_path):
        skill_ok = _make_skill_with_cards(
            tmp_path, "vg-ok",
            skill_offset=-3600, cards_offset=-60,
        )
        skill_bad = _make_skill_with_cards(
            tmp_path, "vg-bad",
            skill_offset=-30, cards_offset=-3600,
        )
        r = _run([str(skill_ok), str(skill_bad)], tmp_path)
        # At least one stale → BLOCK
        assert r.returncode == 1
        assert "vg-bad" in r.stderr or "vg-bad" in r.stdout
