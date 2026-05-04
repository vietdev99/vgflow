"""
Tests for verify-learn-promotion.py — Phase P v2.5.2.

Behavioral check: Tier-A promoted rules in CANDIDATES.md must reach
the FIRST run after promotion timestamp. Catches paperwork-only
promotion (CANDIDATES → LEARN-RULES write without prompt injection).

NOTE: Like verify-bootstrap-carryforward, no top-level `verdict` in
JSON output — uses `failures` array. Schema gap noted.

Covers:
  - No CANDIDATES.md → rc=0 PASS (nothing to verify)
  - No promotions in lookback → rc=0 PASS
  - Promotion present but no runs after → rc=0 (warn-only, can't verify)
  - Promotion + run after + rule in prompts → rc=0 PASS, propagated
  - Promotion + run after + rule MISSING from prompts → rc=1 fail
  - Old promotion outside lookback window → ignored
  - Custom --candidates-file path supported
  - Subprocess resilience (malformed promotion timestamp)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT_REAL = Path(__file__).resolve().parents[4]
VALIDATOR = REPO_ROOT_REAL / ".claude" / "scripts" / "validators" / \
    "verify-learn-promotion.py"


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["VG_REPO_ROOT"] = str(cwd)
    return subprocess.run(
        [sys.executable, str(VALIDATOR), *args],
        capture_output=True, text=True, timeout=20, env=env,
        encoding="utf-8", errors="replace", cwd=str(cwd),
    )


def _now_iso(offset_hours: int = 0) -> str:
    return (
        datetime.now(timezone.utc) + timedelta(hours=offset_hours)
    ).isoformat()


def _write_candidates(tmp_path: Path,
                      promotions: list[tuple[str, str, str, str]]) -> None:
    """promotions = list of (id, tier, promoted_iso, rule_text)"""
    p = tmp_path / ".vg" / "bootstrap" / "CANDIDATES.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    body = []
    for rid, tier, promoted, text in promotions:
        body.append(f"## {rid} — Promoted rule {rid}")
        body.append(f"**Tier:** {tier}")
        body.append(f"**Promoted:** {promoted}")
        body.append(f"**Rule:** {text}")
        body.append("")
    p.write_text("\n".join(body), encoding="utf-8")


def _write_run(tmp_path: Path, run_id: str,
               prompts: list[str], age_hours: float = -0.5) -> None:
    """Create a run with executor-prompts manifest, mtime offset by age_hours."""
    pdir = tmp_path / ".vg" / "runs" / run_id / "executor-prompts"
    pdir.mkdir(parents=True, exist_ok=True)
    entries = []
    for i, txt in enumerate(prompts):
        fname = f"task-{i}.prompt.txt"
        (pdir / fname).write_text(txt, encoding="utf-8")
        entries.append({"task_seq": i, "file": fname})
    (pdir / "manifest.json").write_text(
        json.dumps({"entries": entries}),
        encoding="utf-8",
    )
    # Set mtime to AFTER the promotion timestamp by offsetting from now
    target = datetime.now(timezone.utc) + timedelta(hours=age_hours)
    epoch = target.timestamp()
    os.utime(pdir, (epoch, epoch))


class TestLearnPromotion:
    def test_no_candidates_passes(self, tmp_path):
        r = _run(["--json"], tmp_path)
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data["promotions_checked"] == 0

    def test_no_promotions_in_lookback_passes(self, tmp_path):
        # Promotion 30 days ago, lookback default 7 days
        old_iso = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        _write_candidates(tmp_path, [
            ("L-001", "A", old_iso, "Long enough rule body for anchor matching to work"),
        ])
        r = _run(["--lookback-days", "7", "--json"], tmp_path)
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data["promotions_checked"] == 0

    def test_promotion_no_runs_after_passes(self, tmp_path):
        # Promotion 1 hour from now (future) — no runs after
        future_iso = _now_iso(offset_hours=1)
        _write_candidates(tmp_path, [
            ("L-002", "A", future_iso, "Rule body sufficiently long for anchor matching"),
        ])
        r = _run(["--json"], tmp_path)
        assert r.returncode == 0  # warn-only when no runs to verify against

    def test_promotion_propagated_passes(self, tmp_path):
        rule_text = "Always include reload-after-mutation step in every test for ghost-save"
        # Promoted 2h ago
        promo_iso = _now_iso(offset_hours=-2)
        _write_candidates(tmp_path, [
            ("L-003", "A", promo_iso, rule_text),
        ])
        # Run created 1h ago (after promotion), prompt contains rule
        _write_run(tmp_path, "run-prop", [
            f"Executor prompt with: {rule_text}. Continue.",
        ], age_hours=-1.0)
        r = _run(["--json"], tmp_path)
        assert r.returncode == 0, \
            f"propagated → rc=0, got {r.returncode}, stdout={r.stdout[:300]}"
        data = json.loads(r.stdout)
        assert data["promotions_checked"] == 1
        assert len(data["failures"]) == 0

    def test_promotion_not_propagated_fails(self, tmp_path):
        rule_text = "Mandatory test instrumentation rule that must be in every prompt body"
        promo_iso = _now_iso(offset_hours=-2)
        _write_candidates(tmp_path, [
            ("L-004", "A", promo_iso, rule_text),
        ])
        _write_run(tmp_path, "run-miss", [
            "Plain prompt without any rule injection at all.",
        ], age_hours=-1.0)
        r = _run(["--json"], tmp_path)
        assert r.returncode == 1, \
            f"not propagated → rc=1, got {r.returncode}, stdout={r.stdout[:300]}"
        data = json.loads(r.stdout)
        assert len(data["failures"]) >= 1

    def test_old_promotion_outside_lookback_ignored(self, tmp_path):
        # Same as no_promotions_in_lookback but with explicit smaller window
        promo_iso = (
            datetime.now(timezone.utc) - timedelta(days=14)
        ).isoformat()
        _write_candidates(tmp_path, [
            ("L-005", "A", promo_iso, "Body long enough for anchor matching scheme rules"),
        ])
        r = _run(["--lookback-days", "1", "--json"], tmp_path)
        assert r.returncode == 0

    def test_custom_candidates_file(self, tmp_path):
        custom = tmp_path / "custom" / "MY-CANDIDATES.md"
        custom.parent.mkdir(parents=True)
        custom.write_text("", encoding="utf-8")
        r = _run([
            "--candidates-file", str(custom.relative_to(tmp_path)),
            "--json",
        ], tmp_path)
        assert r.returncode == 0
        # Should not crash because file exists but is empty

    def test_malformed_timestamp_no_crash(self, tmp_path):
        _write_candidates(tmp_path, [
            ("L-006", "A", "not-a-date", "Body long enough for anchor matching scheme rules"),
        ])
        r = _run(["--json"], tmp_path)
        assert "Traceback" not in r.stderr, \
            f"crash on bad timestamp: {r.stderr[-300:]}"
        assert r.returncode == 0
