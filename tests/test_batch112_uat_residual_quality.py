"""B112 v4.72.0 — residual UAT quality (copy + brand voice + UX naturalness).

Closes the residual ~5% UAT bug class that pure automation cannot fully
catch alone — copy quality, brand voice, UX flow naturalness. Validator
runs rule-based linters + emits CROSSAI-UX-REVIEW.md scaffold for
operator to feed to codex/gemini.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = REPO_ROOT / "scripts" / "validators" / "verify-uat-residual-quality.py"
MIRROR = REPO_ROOT / ".claude" / "scripts" / "validators" / "verify-uat-residual-quality.py"


def _run(phase_dir: Path, repo_root: Path, *extra) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(VALIDATOR),
         "--phase-dir", str(phase_dir),
         "--repo-root", str(repo_root),
         *extra],
        capture_output=True, text=True,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        encoding="utf-8", errors="replace",
    )


def _seed(tmp_path: Path, fe_files: dict = None, glossary: dict | None = None,
          lifecycle: dict | None = None) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    if fe_files:
        for rel, body in fe_files.items():
            f = repo / "apps" / "admin" / "src" / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(body, encoding="utf-8")
    if glossary is not None:
        (repo / ".glossary.json").write_text(json.dumps(glossary), encoding="utf-8")
    phase = repo / ".vg" / "phases" / "p1"
    phase.mkdir(parents=True)
    if lifecycle is not None:
        (phase / "LIFECYCLE-SPECS.json").write_text(json.dumps(lifecycle), encoding="utf-8")
    return phase, repo


# ---------------------------------------------------------------------------
# Copy quality
# ---------------------------------------------------------------------------

def test_b112_placeholder_leak_detected(tmp_path: Path) -> None:
    phase, repo = _seed(tmp_path, fe_files={
        "Hello.tsx": "export const X = <div>TODO: replace this</div>;",
    })
    proc = _run(phase, repo)
    out = json.loads(proc.stdout)
    assert any(
        f["kind"] == "placeholder_leak" and f["evidence"].upper() == "TODO"
        for f in out["findings"]["copy_quality"]
    )


def test_b112_lorem_ipsum_detected(tmp_path: Path) -> None:
    phase, repo = _seed(tmp_path, fe_files={
        "About.tsx": 'const t = "Lorem ipsum dolor sit amet";',
    })
    proc = _run(phase, repo)
    out = json.loads(proc.stdout)
    assert any(
        f["kind"] == "placeholder_leak"
        for f in out["findings"]["copy_quality"]
    )


def test_b112_untranslated_key_detected(tmp_path: Path) -> None:
    phase, repo = _seed(tmp_path, fe_files={
        "Bad.tsx": 'const t = <span>{{user_label}}: John</span>;',
    })
    proc = _run(phase, repo)
    out = json.loads(proc.stdout)
    assert any(
        f["kind"] == "untranslated_key"
        for f in out["findings"]["copy_quality"]
    )


def test_b112_clean_fe_no_findings(tmp_path: Path) -> None:
    phase, repo = _seed(tmp_path, fe_files={
        "Clean.tsx": 'export const X = <span>Welcome back</span>;',
    })
    proc = _run(phase, repo, "--no-crossai")
    out = json.loads(proc.stdout)
    assert out["totals"]["copy_quality"] == 0


# ---------------------------------------------------------------------------
# Brand voice
# ---------------------------------------------------------------------------

def test_b112_glossary_alias_drift_flagged(tmp_path: Path) -> None:
    phase, repo = _seed(tmp_path,
        fe_files={
            "TopUpPage.tsx": 'const label = "Top-up your balance";',
        },
        glossary={
            "terms": [
                {"canonical": "Topup", "aliases": ["TopUp", "Top-up", "top up"]},
            ],
        },
    )
    proc = _run(phase, repo)
    out = json.loads(proc.stdout)
    findings = out["findings"]["brand_voice"]
    assert any(
        f["kind"] == "brand_voice_drift" and f["alias_found"] == "Top-up"
        for f in findings
    )


def test_b112_glossary_allowed_entry_not_flagged(tmp_path: Path) -> None:
    phase, repo = _seed(tmp_path,
        fe_files={
            "TopUpPage.tsx": 'const label = "Top-up your balance";',
        },
        glossary={
            "terms": [
                {"canonical": "Topup", "aliases": ["Top-up"], "allowed": True},
            ],
        },
    )
    proc = _run(phase, repo)
    out = json.loads(proc.stdout)
    assert out["totals"]["brand_voice"] == 0


def test_b112_no_glossary_no_brand_findings(tmp_path: Path) -> None:
    phase, repo = _seed(tmp_path, fe_files={
        "X.tsx": "const t = 'Welcome';",
    })
    proc = _run(phase, repo)
    out = json.loads(proc.stdout)
    assert out["glossary_loaded"] is False
    assert out["totals"]["brand_voice"] == 0


# ---------------------------------------------------------------------------
# UX naturalness
# ---------------------------------------------------------------------------

def test_b112_ux_density_flagged_when_over_threshold(tmp_path: Path) -> None:
    lifecycle = {
        "goals": {
            "G-001": {
                "title": "x",
                "steps": [
                    {"stage": "create",
                     "action": "click submit, fill name, click next, fill address, "
                               "click confirm, fill code, click verify, click save, "
                               "navigate to summary"},
                ],
            }
        }
    }
    phase, repo = _seed(tmp_path, lifecycle=lifecycle)
    proc = _run(phase, repo, "--ux-action-threshold", "5")
    out = json.loads(proc.stdout)
    assert any(
        f["kind"] == "ux_flow_density"
        for f in out["findings"]["ux_naturalness"]
    )


def test_b112_ux_density_passes_under_threshold(tmp_path: Path) -> None:
    lifecycle = {
        "goals": {
            "G-001": {
                "title": "x",
                "steps": [
                    {"stage": "create", "action": "click submit, fill name"},
                ],
            }
        }
    }
    phase, repo = _seed(tmp_path, lifecycle=lifecycle)
    proc = _run(phase, repo, "--ux-action-threshold", "5")
    out = json.loads(proc.stdout)
    assert out["totals"]["ux_naturalness"] == 0


# ---------------------------------------------------------------------------
# CrossAI review scaffold
# ---------------------------------------------------------------------------

def test_b112_crossai_review_emitted(tmp_path: Path) -> None:
    lifecycle = {
        "goals": {
            "G-001": {
                "title": "Approve topup",
                "steps": [
                    {"stage": "create", "action": "do thing"},
                ],
            }
        }
    }
    phase, repo = _seed(tmp_path, lifecycle=lifecycle)
    proc = _run(phase, repo)
    out = json.loads(proc.stdout)
    assert out["crossai_review_path"]
    p = Path(out["crossai_review_path"])
    assert p.is_file()
    body = p.read_text(encoding="utf-8")
    assert "CrossAI UX naturalness review" in body
    assert "G-001: Approve topup" in body


def test_b112_no_crossai_flag_skips_emit(tmp_path: Path) -> None:
    lifecycle = {"goals": {"G-001": {"title": "x", "steps": []}}}
    phase, repo = _seed(tmp_path, lifecycle=lifecycle)
    proc = _run(phase, repo, "--no-crossai")
    out = json.loads(proc.stdout)
    assert out["crossai_review_path"] is None


# ---------------------------------------------------------------------------
# Severity gate
# ---------------------------------------------------------------------------

def test_b112_warn_severity_exits_zero(tmp_path: Path) -> None:
    phase, repo = _seed(tmp_path, fe_files={
        "X.tsx": "const t = 'TODO';",
    })
    proc = _run(phase, repo, "--severity", "warn")
    assert proc.returncode == 0


def test_b112_block_severity_exits_one(tmp_path: Path) -> None:
    phase, repo = _seed(tmp_path, fe_files={
        "X.tsx": "const t = 'TODO';",
    })
    proc = _run(phase, repo, "--severity", "block")
    assert proc.returncode == 1


# ---------------------------------------------------------------------------
# Registry + mirror
# ---------------------------------------------------------------------------

def test_b112_registry_entry() -> None:
    body = (REPO_ROOT / "scripts" / "validators" / "registry.yaml").read_text(encoding="utf-8")
    assert "id: uat-residual-quality" in body
    assert "added_in: v4.72.0" in body


def test_b112_validator_mirror() -> None:
    assert VALIDATOR.read_bytes() == MIRROR.read_bytes()


def test_b112_registry_mirror() -> None:
    a = (REPO_ROOT / "scripts" / "validators" / "registry.yaml").read_bytes()
    b = (REPO_ROOT / ".claude" / "scripts" / "validators" / "registry.yaml").read_bytes()
    assert a == b
