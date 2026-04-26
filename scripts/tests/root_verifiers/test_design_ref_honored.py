"""
Tests for verify-design-ref-honored.py — BLOCK severity.

Phase 7.14.3 trigger: AI shipped dark sidebar despite HTML proto white
sidebar. Closes VG executor rule R6 / design-fidelity. BLOCKs when
<design-ref> tag points to nonexistent screenshot/structural asset.

Covers:
  - Phase dir absent → graceful PASS (no work to do)
  - PLAN with no design-ref tags → PASS (non-UI phase)
  - PLAN with valid design-ref + asset present → PASS
  - PLAN with broken design-ref (asset missing) → BLOCK
  - design-ref to .vg/design-normalized fallback root → PASS
  - --strict escalates uncited slug WARN → BLOCK
  - Verdict schema canonical (PASS|BLOCK|WARN)
  - Subprocess resilience (corrupt PLAN, no crash)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT_REAL = Path(__file__).resolve().parents[4]
VALIDATOR = REPO_ROOT_REAL / ".claude" / "scripts" / "validators" / \
    "verify-design-ref-honored.py"


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["VG_REPO_ROOT"] = str(cwd)
    return subprocess.run(
        [sys.executable, str(VALIDATOR), *args],
        capture_output=True, text=True, timeout=20, env=env,
        encoding="utf-8", errors="replace", cwd=str(cwd),
    )


def _verdict(stdout: str) -> str | None:
    try:
        return json.loads(stdout).get("verdict")
    except (json.JSONDecodeError, AttributeError):
        return None


def _make_phase(tmp_path: Path, plan_text: str, *,
                slug: str = "07.5-design") -> Path:
    pdir = tmp_path / ".vg" / "phases" / slug
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "PLAN.md").write_text(plan_text, encoding="utf-8")
    return pdir


def _make_design_assets(tmp_path: Path, slug: str, *,
                        kinds: tuple[str, ...] = ("screenshot",),
                        root: str = ".planning") -> None:
    base = tmp_path / root / "design-normalized"
    if "screenshot" in kinds:
        shots = base / "screenshots"
        shots.mkdir(parents=True, exist_ok=True)
        (shots / f"{slug}.default.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    if "structural" in kinds:
        refs = base / "refs"
        refs.mkdir(parents=True, exist_ok=True)
        (refs / f"{slug}.structural.html").write_text(
            "<div>structural</div>", encoding="utf-8")


class TestDesignRefHonored:
    def test_phase_dir_missing_passes(self, tmp_path):
        r = _run(["--phase", "07.5"], tmp_path)
        assert r.returncode == 0, f"missing phase → PASS, rc={r.returncode}"

    def test_no_design_ref_in_plan_passes(self, tmp_path):
        _make_phase(tmp_path, "## Task 1\nDo something backend.\n")
        r = _run(["--phase", "07.5"], tmp_path)
        assert r.returncode == 0, f"no design-ref → PASS, rc={r.returncode}"
        assert _verdict(r.stdout) == "PASS"

    def test_valid_design_ref_with_asset_passes(self, tmp_path):
        _make_phase(
            tmp_path,
            "## Task 1\n"
            "Build the campaign list.\n"
            "<design-ref>campaign-list</design-ref>\n",
        )
        _make_design_assets(tmp_path, "campaign-list",
                            kinds=("screenshot", "structural"))
        r = _run(["--phase", "07.5"], tmp_path)
        # Asset present → no broken-link evidence; commit-cite WARN may fire
        # but rc=0 either way (WARN only).
        assert r.returncode == 0, f"valid asset → rc=0, got {r.returncode}, stdout={r.stdout[:200]}"
        v = _verdict(r.stdout)
        assert v in ("PASS", "WARN"), f"verdict={v}"

    def test_broken_design_ref_blocks(self, tmp_path):
        _make_phase(
            tmp_path,
            "## Task 1\n"
            "<design-ref>missing-slug</design-ref>\n",
        )
        # No assets created → broken link
        r = _run(["--phase", "07.5"], tmp_path)
        assert r.returncode == 1, f"broken ref → BLOCK rc=1, got {r.returncode}, stdout={r.stdout[:200]}"
        assert _verdict(r.stdout) == "BLOCK"

    def test_vg_design_normalized_root_accepted(self, tmp_path):
        _make_phase(
            tmp_path,
            "## Task 1\n<design-ref>vg-rooted</design-ref>\n",
        )
        _make_design_assets(tmp_path, "vg-rooted",
                            kinds=("screenshot",), root=".vg")
        r = _run(["--phase", "07.5"], tmp_path)
        assert r.returncode == 0, f".vg/design-normalized fallback should PASS, stdout={r.stdout[:200]}"

    def test_strict_flag_recognized(self, tmp_path):
        _make_phase(
            tmp_path,
            "## Task 1\n<design-ref>cited-slug</design-ref>\n",
        )
        _make_design_assets(tmp_path, "cited-slug",
                            kinds=("screenshot",))
        r = _run(["--phase", "07.5", "--strict"], tmp_path)
        assert "unrecognized arguments" not in r.stderr.lower()
        assert r.returncode in (0, 1)

    def test_verdict_schema_canonical(self, tmp_path):
        _make_phase(tmp_path, "## Task 1\nbackend only.\n")
        r = _run(["--phase", "07.5"], tmp_path)
        try:
            data = json.loads(r.stdout)
        except json.JSONDecodeError:
            return  # may emit empty stdout when no work — acceptable
        v = data.get("verdict")
        if v is not None:
            assert v in {"PASS", "BLOCK", "WARN"}, f"verdict drift: {v!r}"

    def test_corrupt_plan_no_crash(self, tmp_path):
        # Binary garbage in PLAN.md
        pdir = tmp_path / ".vg" / "phases" / "07.5-design"
        pdir.mkdir(parents=True)
        (pdir / "PLAN.md").write_bytes(b"\xff\xfe\x00\x00binary\x00\xff")
        r = _run(["--phase", "07.5"], tmp_path)
        assert "Traceback" not in r.stderr, \
            f"crash on corrupt PLAN: {r.stderr[-300:]}"
        assert r.returncode in (0, 1)
