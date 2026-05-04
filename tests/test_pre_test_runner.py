"""Pre-test runner — Tier 1 (static) + Tier 2 (local unit/integration)."""
from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GATE = REPO / "scripts" / "validators" / "verify-pre-test-tier-1-2.py"


def test_debug_leftover_grep_blocks(tmp_path: Path) -> None:
    """A file containing console.log + TODO:remove must trigger BLOCK."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "Page.tsx").write_text(textwrap.dedent("""
        export function Page() {
          console.log('debug me');  // TODO:remove
          return <div/>;
        }
    """).strip(), encoding="utf-8")
    out = tmp_path / "report.json"
    result = subprocess.run([
        "python3", str(GATE),
        "--source-root", str(tmp_path / "src"),
        "--phase", "test-1.0",
        "--report-out", str(out),
        "--skip-typecheck", "--skip-lint", "--skip-tests", "--skip-secret-scan",
    ], capture_output=True, text=True, check=False)
    assert result.returncode == 1, result.stderr
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["tier_1"]["debug_leftover"]["status"] == "BLOCK"
    assert any("console.log" in e["snippet"] for e in report["tier_1"]["debug_leftover"]["evidence"])


def test_clean_source_passes_grep(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "Page.tsx").write_text(
        "export function Page() { return <div>hello</div>; }\n", encoding="utf-8",
    )
    out = tmp_path / "report.json"
    result = subprocess.run([
        "python3", str(GATE),
        "--source-root", str(tmp_path / "src"),
        "--phase", "test-1.0",
        "--report-out", str(out),
        "--skip-typecheck", "--skip-lint", "--skip-tests", "--skip-secret-scan",
    ], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["tier_1"]["debug_leftover"]["status"] == "PASS"


def test_skip_flags_honored(tmp_path: Path) -> None:
    """All --skip-* flags result in tier_1/tier_2 being marked SKIPPED, not run."""
    (tmp_path / "src").mkdir()
    out = tmp_path / "report.json"
    result = subprocess.run([
        "python3", str(GATE),
        "--source-root", str(tmp_path / "src"),
        "--phase", "test-1.0",
        "--report-out", str(out),
        "--skip-typecheck", "--skip-lint", "--skip-tests", "--skip-debug-grep",
        "--skip-secret-scan",
    ], capture_output=True, text=True, check=False)
    assert result.returncode == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["tier_1"]["typecheck"]["status"] == "SKIPPED"
    assert report["tier_2"]["status"] == "SKIPPED"


def test_missing_typecheck_with_env_baseline_declared_blocks(tmp_path: Path) -> None:
    """ENV-BASELINE declares typecheck → missing tool at runtime = BLOCK."""
    (tmp_path / "src").mkdir()
    eb = tmp_path / "ENV-BASELINE.md"
    eb.write_text(textwrap.dedent("""
        # Environment Baseline

        **Profile:** web-fullstack

        ## Recommended tech stack
        | Layer | Tool | Version | Rationale |
        |---|---|---|---|
        | Type check | tsc strict | – | x |

        ## Environment matrix
        | Env | Purpose | Hosting | Run | Deploy | DB | Secrets | Auto |
        |---|---|---|---|---|---|---|---|
        | dev | local | localhost | dev | none | sqlite | env | – |
        | sandbox | x | y | z | rsync | pg | vault | yes |
        | staging | x | y | z | git | pg | vercel | manual |
        | prod | x | y | z | git | pg | vercel | approval |

        ## Decisions (E-XX namespace)
        ### E-01: x
        **Reasoning:** y
        **Reverse cost:** LOW
        **Sources cited:** https://x
    """).strip(), encoding="utf-8")

    out = tmp_path / "report.json"
    result = subprocess.run([
        "python3", str(GATE),
        "--source-root", str(tmp_path / "src"),
        "--phase", "test-1.0",
        "--env-baseline", str(eb),
        "--report-out", str(out),
        "--repo-root", str(tmp_path),
        "--skip-lint", "--skip-tests", "--skip-debug-grep", "--skip-secret-scan",
    ], capture_output=True, text=True, check=False)
    assert result.returncode == 1, "expected BLOCK on missing-expected-typecheck"
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["tier_1"]["typecheck"]["status"] == "BLOCK"
    assert report["tier_1"]["typecheck"].get("promoted_from") == "SKIPPED"


def test_secret_scan_finds_aws_key(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "config.ts").write_text(
        'const k = "AKIAIOSFODNN7EXAMPLE";  // example pattern\n', encoding="utf-8",
    )
    out = tmp_path / "report.json"
    result = subprocess.run([
        "python3", str(GATE),
        "--source-root", str(tmp_path / "src"),
        "--phase", "test-1.0",
        "--report-out", str(out),
        "--skip-typecheck", "--skip-lint", "--skip-tests", "--skip-debug-grep",
    ], capture_output=True, text=True, check=False)
    assert result.returncode == 1
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["tier_1"]["secret_scan"]["status"] == "BLOCK"
    assert all("AKIA" not in e.get("snippet", "") for e in report["tier_1"]["secret_scan"]["evidence"])
