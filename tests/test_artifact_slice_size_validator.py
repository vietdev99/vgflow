"""Task 43 — verify per-slice ≤5K-token BLOCK validator.

Pin: oversized slice (>5K tokens) BLOCKs at default. --allow-oversized-slice
+ --override-reason escapes BLOCK with override-debt entry. Index files
have stricter ≤1K-token budget.

Tiktoken is MANDATORY (Codex round-2 Amendment C); ImportError on missing
package is a deliberate loud-fail.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
VALIDATOR = REPO / "scripts/validators/verify-artifact-slice-size.py"


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["python3", str(VALIDATOR), *args],
        cwd=cwd, capture_output=True, text=True,
    )


def test_small_slice_passes(tmp_path: Path) -> None:
    phase = tmp_path / "phase"
    plan = phase / "PLAN"
    plan.mkdir(parents=True)
    (plan / "task-01.md").write_text("# Task 01\nSmall content.\n", encoding="utf-8")
    (plan / "index.md").write_text("# index\n- task-01\n", encoding="utf-8")

    result = _run(["--phase-dir", str(phase)], REPO)
    assert result.returncode == 0, f"got: {result.stdout}\n{result.stderr}"


def test_oversized_per_unit_slice_blocks(tmp_path: Path) -> None:
    phase = tmp_path / "phase"
    plan = phase / "PLAN"
    plan.mkdir(parents=True)
    # ~30K chars ≈ 6-15K tokens depending on tokenizer + content; exceeds 5K limit
    big = ("Very long English content. " * 1500)
    (plan / "task-99.md").write_text(big, encoding="utf-8")
    (plan / "index.md").write_text("# index\n- task-99\n", encoding="utf-8")

    result = _run(["--phase-dir", str(phase)], REPO)
    assert result.returncode != 0
    assert "task-99" in result.stdout + result.stderr
    assert "5000" in result.stdout + result.stderr or "5K" in result.stdout + result.stderr


def test_oversized_index_file_blocks(tmp_path: Path) -> None:
    phase = tmp_path / "phase"
    plan = phase / "PLAN"
    plan.mkdir(parents=True)
    (plan / "task-01.md").write_text("# small\n", encoding="utf-8")
    # Index files have stricter 1K-token limit
    big_index = ("Lorem ipsum dolor sit amet. " * 600)
    (plan / "index.md").write_text(big_index, encoding="utf-8")

    result = _run(["--phase-dir", str(phase)], REPO)
    assert result.returncode != 0
    assert "index.md" in result.stdout + result.stderr


def test_allow_oversized_with_override_reason(tmp_path: Path) -> None:
    phase = tmp_path / "phase"
    plan = phase / "PLAN"
    plan.mkdir(parents=True)
    big = ("Very long content. " * 1500)
    (plan / "task-99.md").write_text(big, encoding="utf-8")
    (plan / "index.md").write_text("# small\n", encoding="utf-8")
    debt_path = tmp_path / "override-debt.json"

    result = _run(
        [
            "--phase-dir", str(phase),
            "--allow-oversized-slice",
            "--override-reason", "PV3 4.1 legacy slice — Task 43 grace window",
            "--override-debt-path", str(debt_path),
        ],
        REPO,
    )
    assert result.returncode == 0, result.stderr
    assert debt_path.exists()
    debt = json.loads(debt_path.read_text(encoding="utf-8"))
    assert debt["scope"] == "artifact-slice-oversized"
    assert debt["reason"]


def test_vietnamese_text_uses_tiktoken_not_char_heuristic(tmp_path: Path) -> None:
    """Vietnamese diacritics: 2 chars/token. Heuristic (4 chars/token) would underestimate.

    A 12K-char Vietnamese block is ~6K tokens (real) but only 3K via heuristic.
    The validator MUST flag this as oversized."""
    phase = tmp_path / "phase"
    api = phase / "API-CONTRACTS"
    api.mkdir(parents=True)
    # Vietnamese phrase repeated; ~12K chars
    vn = "Sếp đang dogfood quy trình duyệt nội dung mỗi ngày. " * 230
    (api / "post-api-content.md").write_text(vn, encoding="utf-8")
    (api / "index.md").write_text("# api index\n", encoding="utf-8")

    result = _run(["--phase-dir", str(phase)], REPO)
    # Vietnamese tokenizes denser; 12K chars ≈ 6K tokens — should BLOCK
    assert result.returncode != 0, "Vietnamese 12K chars must BLOCK at ≤5K tokens"


def test_tiktoken_import_loud_fail_when_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """If tiktoken is uninstalled, validator MUST exit with ImportError-derived BLOCK.

    Test by spawning python with PYTHONPATH that hides tiktoken (via --hide-tiktoken stub flag).
    """
    phase = tmp_path / "phase"
    (phase / "PLAN").mkdir(parents=True)
    (phase / "PLAN" / "task-01.md").write_text("# small\n", encoding="utf-8")
    (phase / "PLAN" / "index.md").write_text("# small\n", encoding="utf-8")

    # Run with a hidden-tiktoken environment by inserting a fake tiktoken module that raises.
    fake_pkg = tmp_path / "fake_pkg"
    (fake_pkg / "tiktoken").mkdir(parents=True)
    (fake_pkg / "tiktoken" / "__init__.py").write_text(
        "raise ImportError('tiktoken simulated missing')\n", encoding="utf-8"
    )
    env = {"PYTHONPATH": str(fake_pkg), "PATH": __import__("os").environ.get("PATH", "")}
    result = subprocess.run(
        ["python3", str(VALIDATOR), "--phase-dir", str(phase)],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "tiktoken" in combined.lower()
    assert "pip install tiktoken" in combined or "install tiktoken" in combined.lower()
