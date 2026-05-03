"""
VG Bootstrap — Test suite for learn-tier-classify.py + learn-dedupe.py
Phase H v2.5 (2026-04-23)

12 test cases:

Tier classify:
1.  High conf (0.95) + critical impact → tier A
2.  Mid conf (0.7) + important → tier B
3.  Low conf (0.4) + important → tier C
4.  High conf + nice impact → tier C (impact caps it)
5.  reject_count >= 2 → RETIRED regardless of conf
6.  Missing confidence field → default 0.5 → tier C
7.  --candidate L-042 single-item mode outputs one JSON object
8.  --all emits JSONL (one JSON per line)
9.  Config override tier_a_threshold_confidence=0.7 → tier A at conf=0.72

Dedupe:
10. Two candidates: "Playwright required" + "Playwright needed for UI"
    — similarity ~0.6, below default 0.8 → NOT merged (separate groups)
11. Two candidates with identical titles → merged with --apply
12. Single unique title → no merge (group size 1)
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
TIER_SCRIPT = REPO_ROOT / ".claude" / "scripts" / "learn-tier-classify.py"
DEDUPE_SCRIPT = REPO_ROOT / ".claude" / "scripts" / "learn-dedupe.py"


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _run(script: Path, args: list[str], repo: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(repo)
    return subprocess.run(
        [sys.executable, str(script)] + args,
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )


def _make_candidates_md(candidates: list[dict]) -> str:
    """Build CANDIDATES.md content from a list of dicts."""
    blocks = []
    for c in candidates:
        lines = ["```yaml"]
        for k, v in c.items():
            if isinstance(v, str):
                lines.append(f'{k}: "{v}"')
            elif isinstance(v, (int, float, bool)):
                lines.append(f"{k}: {str(v).lower() if isinstance(v, bool) else v}")
            else:
                lines.append(f"{k}: {v}")
        lines.append("```")
        blocks.append("\n".join(lines))
    header = "# Bootstrap Candidates\n\n## Candidates\n\n<!-- AI-generated candidates will be appended below this line -->\n\n"
    return header + "\n\n".join(blocks) + "\n"


def _make_repo(tmp_path: Path,
               candidates: list[dict],
               rejected_entries: list[dict] | None = None,
               config_bootstrap: str | None = None) -> Path:
    """Set up a minimal VG repo fixture under tmp_path."""
    bootstrap_dir = tmp_path / ".vg" / "bootstrap"
    bootstrap_dir.mkdir(parents=True, exist_ok=True)

    # Write CANDIDATES.md
    (bootstrap_dir / "CANDIDATES.md").write_text(
        _make_candidates_md(candidates), encoding="utf-8"
    )

    # Write REJECTED.md
    rejected_text = "# Bootstrap Rejected\n\n## Rejections\n\n"
    if rejected_entries:
        for r in rejected_entries:
            lines = [""]
            for k, v in r.items():
                lines.append(f"  {k}: {v!r}")
            rejected_text += "- id: " + r.get("id", "REJ-XXX") + "\n"
            for k, v in r.items():
                if k != "id":
                    rejected_text += f"  {k}: {v!r}\n"
    else:
        rejected_text += "(no rejections yet)\n"
    (bootstrap_dir / "REJECTED.md").write_text(rejected_text, encoding="utf-8")

    # Write ACCEPTED.md (empty)
    (bootstrap_dir / "ACCEPTED.md").write_text(
        "# Bootstrap Accepted\n\n## Promotions\n\n", encoding="utf-8"
    )

    # Write vg.config.md
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    config_text = "# vg.config.md\n\n"
    if config_bootstrap:
        config_text += f"bootstrap:\n{textwrap.indent(config_bootstrap, '  ')}\n"
    (claude_dir / "vg.config.md").write_text(config_text, encoding="utf-8")

    return tmp_path


def _parse_jsonl(output: str) -> list[dict]:
    """Parse JSONL output (one JSON object per line)."""
    results = []
    for line in output.splitlines():
        line = line.strip()
        if line and line.startswith("{"):
            results.append(json.loads(line))
    return results


# ─── Tier classify tests ──────────────────────────────────────────────────────

def test_high_conf_critical_impact_is_tier_a(tmp_path):
    """High conf (0.95) + critical impact → tier A."""
    repo = _make_repo(tmp_path, [
        {"id": "L-001", "title": "Critical rule", "confidence": 0.95, "impact": "critical"}
    ])
    r = _run(TIER_SCRIPT, ["--all"], repo)
    assert r.returncode == 0, f"Unexpected error:\n{r.stderr}"
    items = _parse_jsonl(r.stdout)
    assert len(items) == 1
    assert items[0]["id"] == "L-001"
    assert items[0]["tier"] == "A"


def test_mid_conf_important_is_tier_b(tmp_path):
    """Mid conf (0.7) + important → tier B."""
    repo = _make_repo(tmp_path, [
        {"id": "L-002", "title": "Important rule", "confidence": 0.7, "impact": "important"}
    ])
    r = _run(TIER_SCRIPT, ["--all"], repo)
    assert r.returncode == 0
    items = _parse_jsonl(r.stdout)
    assert items[0]["tier"] == "B"


def test_low_conf_important_is_tier_c(tmp_path):
    """Low conf (0.4) + important → tier C."""
    repo = _make_repo(tmp_path, [
        {"id": "L-003", "title": "Low conf rule", "confidence": 0.4, "impact": "important"}
    ])
    r = _run(TIER_SCRIPT, ["--all"], repo)
    assert r.returncode == 0
    items = _parse_jsonl(r.stdout)
    assert items[0]["tier"] == "C"


def test_high_conf_nice_impact_is_tier_c(tmp_path):
    """High conf (0.9) + nice impact → tier C (impact caps it below B)."""
    repo = _make_repo(tmp_path, [
        {"id": "L-004", "title": "Nice-to-have rule", "confidence": 0.9, "impact": "nice"}
    ])
    r = _run(TIER_SCRIPT, ["--all"], repo)
    assert r.returncode == 0
    items = _parse_jsonl(r.stdout)
    assert items[0]["tier"] == "C", f"Expected C but got {items[0]['tier']} — nice impact must cap tier"


def test_reject_count_gte_2_is_retired(tmp_path):
    """reject_count >= 2 → RETIRED regardless of high conf."""
    # Simulate 2 rejections by ID match
    repo = _make_repo(
        tmp_path,
        candidates=[
            {"id": "L-005", "title": "Repeating rule", "confidence": 0.95, "impact": "critical"}
        ],
        rejected_entries=[
            {"id": "L-005", "rejected_at": "2026-04-01T00:00:00Z", "reason": "not relevant"},
            {"id": "L-005", "rejected_at": "2026-04-02T00:00:00Z", "reason": "still not relevant"},
        ]
    )
    # --all should NOT emit RETIRED by default
    r = _run(TIER_SCRIPT, ["--all"], repo)
    assert r.returncode == 0
    items = _parse_jsonl(r.stdout)
    # Should be filtered out in --all (no RETIRED unless --include-retired)
    assert all(i["id"] != "L-005" for i in items), "RETIRED candidates must be hidden from --all by default"

    # With --include-retired it should appear
    r2 = _run(TIER_SCRIPT, ["--all", "--include-retired"], repo)
    assert r2.returncode == 0
    items2 = _parse_jsonl(r2.stdout)
    retired = [i for i in items2 if i["id"] == "L-005"]
    assert retired, "Expected L-005 in --include-retired output"
    assert retired[0]["tier"] == "RETIRED"


def test_missing_confidence_defaults_to_05_tier_c(tmp_path):
    """Missing confidence field → default 0.5 → tier C."""
    repo = _make_repo(tmp_path, [
        {"id": "L-006", "title": "No confidence field", "impact": "important"}
        # No confidence key
    ])
    r = _run(TIER_SCRIPT, ["--all"], repo)
    assert r.returncode == 0
    items = _parse_jsonl(r.stdout)
    assert len(items) == 1
    assert items[0]["confidence"] == 0.5
    assert items[0]["tier"] == "C"


def test_single_candidate_mode_json_object(tmp_path):
    """--candidate L-042 outputs one JSON object (not JSONL)."""
    repo = _make_repo(tmp_path, [
        {"id": "L-042", "title": "Target rule", "confidence": 0.75, "impact": "critical"}
    ])
    r = _run(TIER_SCRIPT, ["--candidate", "L-042"], repo)
    assert r.returncode == 0, f"stderr:\n{r.stderr}"
    # Should be one valid JSON object — not JSONL
    output = r.stdout.strip()
    obj = json.loads(output)  # raises if not valid JSON
    assert obj["id"] == "L-042"
    assert "tier" in obj
    assert "confidence" in obj
    assert "impact" in obj


def test_all_emits_jsonl_one_per_line(tmp_path):
    """--all emits JSONL — one valid JSON object per line."""
    repo = _make_repo(tmp_path, [
        {"id": "L-010", "title": "Rule A", "confidence": 0.8, "impact": "critical"},
        {"id": "L-011", "title": "Rule B", "confidence": 0.65, "impact": "important"},
        {"id": "L-012", "title": "Rule C", "confidence": 0.3, "impact": "nice"},
    ])
    r = _run(TIER_SCRIPT, ["--all"], repo)
    assert r.returncode == 0
    lines = [l for l in r.stdout.splitlines() if l.strip()]
    assert len(lines) == 3, f"Expected 3 JSONL lines, got {len(lines)}"
    for line in lines:
        obj = json.loads(line)  # must be valid JSON
        assert "id" in obj
        assert "tier" in obj


def test_config_override_tier_a_threshold(tmp_path):
    """Config bootstrap.tier_a_threshold_confidence=0.7 → tier A at conf=0.72 + critical."""
    repo = _make_repo(
        tmp_path,
        candidates=[
            {"id": "L-020", "title": "Lower threshold rule", "confidence": 0.72, "impact": "critical"}
        ],
        config_bootstrap="tier_a_threshold_confidence: 0.7\ntier_b_threshold_confidence: 0.5\n"
    )
    r = _run(TIER_SCRIPT, ["--all"], repo)
    assert r.returncode == 0, f"stderr:\n{r.stderr}"
    items = _parse_jsonl(r.stdout)
    assert len(items) == 1
    assert items[0]["tier"] == "A", (
        f"Expected tier A with lowered threshold 0.7, conf=0.72, got {items[0]['tier']}"
    )


# ─── Dedupe tests ──────────────────────────────────────────────────────────────

def test_low_similarity_not_merged_by_default(tmp_path):
    """'Playwright required' vs 'Playwright needed for UI' — similarity ~0.6 < 0.8 → NOT merged."""
    repo = _make_repo(tmp_path, [
        {"id": "L-030", "title": "Playwright required", "confidence": 0.8, "impact": "important"},
        {"id": "L-031", "title": "Playwright needed for UI", "confidence": 0.7, "impact": "important"},
    ])
    # Verify similarity is below default threshold (0.8)
    import difflib
    sim = difflib.SequenceMatcher(
        None,
        "playwright required",
        "playwright needed for ui"
    ).ratio()
    assert sim < 0.8, f"Similarity {sim:.3f} unexpectedly >= 0.8 — test assumption broken"

    # Dry-run dedupe with default threshold 0.8
    r = _run(DEDUPE_SCRIPT, ["--emit", "json"], repo)
    assert r.returncode == 0, f"stderr:\n{r.stderr}"
    out = json.loads(r.stdout)
    # Both candidates should be in separate groups (merge_count=0)
    assert out["merge_count"] == 0, (
        f"Expected 0 merges at threshold=0.8 (similarity={sim:.3f}), got {out['merge_count']}"
    )


def test_identical_titles_merged_with_apply(tmp_path):
    """Two candidates with identical titles → merged with --apply, dedupe_source added."""
    repo = _make_repo(tmp_path, [
        {"id": "L-040", "title": "Exact same rule", "confidence": 0.8, "impact": "important"},
        {"id": "L-041", "title": "Exact same rule", "confidence": 0.7, "impact": "important"},
    ])
    candidates_path = repo / ".vg" / "bootstrap" / "CANDIDATES.md"

    # Dry-run first: should show 1 merge group
    r = _run(DEDUPE_SCRIPT, ["--emit", "json"], repo)
    assert r.returncode == 0
    out = json.loads(r.stdout)
    assert out["merge_count"] == 1, f"Expected 1 merge group, got {out['merge_count']}"

    # Apply
    r2 = _run(DEDUPE_SCRIPT, ["--apply"], repo)
    assert r2.returncode == 0, f"Apply failed:\n{r2.stderr}"

    # Read back and verify:
    new_text = candidates_path.read_text(encoding="utf-8")
    # L-040 should survive, L-041 should be merged in
    assert "L-040" in new_text, "Primary candidate L-040 should survive"
    assert "L-041" not in new_text or "dedupe_source" in new_text, (
        "L-041 should be removed or referenced via dedupe_source"
    )
    assert "dedupe_source" in new_text, "dedupe_source field should be present in merged block"


def test_unique_title_no_merge(tmp_path):
    """Single unique title → group size 1, no merges."""
    repo = _make_repo(tmp_path, [
        {"id": "L-050", "title": "Completely unique rule about XYZ monitoring", "confidence": 0.8, "impact": "important"},
    ])
    r = _run(DEDUPE_SCRIPT, ["--emit", "json"], repo)
    assert r.returncode == 0
    out = json.loads(r.stdout)
    assert out["total_candidates"] == 1
    assert out["merge_count"] == 0
    groups = out["groups"]
    assert len(groups) == 1
    assert groups[0]["size"] == 1
    assert not groups[0]["will_merge"]


# ─── Edge case: empty bootstrap dir ──────────────────────────────────────────

def test_empty_candidates_no_crash(tmp_path):
    """Empty CANDIDATES.md → no crash, emits nothing for --all."""
    # Build empty candidates
    repo = _make_repo(tmp_path, [])  # no candidates

    r = _run(TIER_SCRIPT, ["--all"], repo)
    assert r.returncode == 0, f"Crashed on empty candidates:\n{r.stderr}"
    items = _parse_jsonl(r.stdout)
    assert items == [], "Should emit nothing for empty candidates"

    r2 = _run(DEDUPE_SCRIPT, ["--emit", "json"], repo)
    assert r2.returncode == 0, f"Dedupe crashed on empty candidates:\n{r2.stderr}"
    out = json.loads(r2.stdout)
    assert out["merge_count"] == 0
