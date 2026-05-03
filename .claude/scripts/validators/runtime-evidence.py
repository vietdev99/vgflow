#!/usr/bin/env python3
"""
runtime-evidence validator — forces runtime verification over AI "code evidence".

Blocks AI rationalization: "code exists + unit tests pass → goal READY".
Real enforcement: if Playwright spec exists for phase, it MUST have run.

Dispatch rules:
1. Find all Playwright specs under apps/web/e2e/*.spec.ts referencing phase
   by filename (e.g. `auth-domain-isolation.spec.ts` for phase 14 auth).
   Heuristic: filename tokens intersect phase slug tokens.
2. For each spec found, check `apps/web/playwright-report/` or
   `apps/web/test-results/` for run evidence newer than phase's blueprint
   commit (proves test ran AFTER code was written).
3. Missing execution evidence → BLOCK with explicit list of specs + setup hint.
4. Also check GOAL-COVERAGE-MATRIX.md for goals marked READY but no runtime
   proof — downgrade to CODE_ONLY_EVIDENCE, BLOCK if critical priority.

Overridable via --allow-unexecuted-specs flag at /vg:review or /vg:test,
which logs to OVERRIDE-DEBT and forces re-verification at /vg:accept.

Output: standard validator JSON
{"validator": "runtime-evidence",
 "verdict": "PASS|WARN|BLOCK",
 "evidence": [{"type": "...", "message": "...", "file": "..."}]}
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
PHASES_DIR = REPO_ROOT / ".vg" / "phases"


def find_phase_dir(phase: str) -> Path | None:
    if not PHASES_DIR.exists():
        return None
    for c in PHASES_DIR.glob(f"{phase}-*"):
        return c
    for c in PHASES_DIR.glob(f"{phase.zfill(2)}-*"):
        return c
    return None


def phase_slug_tokens(phase_dir: Path) -> set[str]:
    """Extract significant tokens from phase dir name for spec matching."""
    name = phase_dir.name
    # Remove leading digits + dashes: "14-per-domain-auth-isolation" → "per-domain-auth-isolation"
    cleaned = re.sub(r"^\d+[.\d]*-", "", name)
    # Tokens: split by -
    tokens = set(cleaned.split("-"))
    # Remove stopwords
    tokens -= {"", "and", "or", "the", "a", "for", "with"}
    return tokens


def find_phase_specs(phase_dir: Path) -> list[Path]:
    """Find Playwright specs likely related to this phase."""
    e2e_dir = REPO_ROOT / "apps" / "web" / "e2e"
    if not e2e_dir.exists():
        return []
    phase_tokens = phase_slug_tokens(phase_dir)
    specs = []
    for spec in e2e_dir.rglob("*.spec.ts"):
        # Match if ≥2 tokens overlap (avoid false positives on common words)
        spec_tokens = set(spec.stem.split("-"))
        overlap = phase_tokens & spec_tokens
        if len(overlap) >= 2:
            specs.append(spec)
    return specs


def check_playwright_run_evidence(spec: Path, since_mtime: float) -> tuple[bool, str]:
    """Check if spec was executed AFTER code existed.
    Looks for test-results/ or playwright-report/ updated post `since_mtime`."""
    web_dir = REPO_ROOT / "apps" / "web"
    candidates = [
        web_dir / "playwright-report",
        web_dir / "test-results",
    ]
    for d in candidates:
        if not d.exists():
            continue
        # Any file in dir newer than since_mtime?
        for f in d.rglob("*"):
            if f.is_file() and f.stat().st_mtime > since_mtime:
                return True, str(f.relative_to(REPO_ROOT))
    return False, ""


def find_per_spec_failures(specs: list[Path]) -> list[dict]:
    """OHOK-6 (Gemini P1): parse test-results/ for per-spec failure folders.

    Playwright writes one folder per failing test to `apps/web/test-results/`,
    named `<spec-basename>-<test-title-slug>-<browser>/`. Global `.last-run.json`
    only tracks the LATEST run — if user runs failing phase-14 tests then a
    trivial passing smoke, status becomes 'passed' and global check lets the
    phase-14 failure slip through. Per-folder scan catches this "Pass-by-Proxy"
    bypass: if ANY failure folder references phase specs, BLOCK regardless
    of last-run status.

    Returns list of {spec, failure_folder, mtime} for each phase-relevant failure.
    """
    test_results = REPO_ROOT / "apps" / "web" / "test-results"
    if not test_results.exists():
        return []
    # Build spec basename → spec path lookup.
    # Path.stem of `foo.spec.ts` = `foo.spec` (only strips LAST ext), but
    # Playwright folder names start with basename WITHOUT `.spec`. Strip
    # trailing `.spec` so match prefix is correct.
    def _basename(p: Path) -> str:
        s = p.stem
        if s.endswith(".spec"):
            s = s[:-5]
        elif s.endswith(".test"):
            s = s[:-5]
        return s
    spec_bases = {_basename(s): s for s in specs}  # "auth-domain-isolation" → Path
    failures: list[dict] = []
    for entry in test_results.iterdir():
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        # Folder name: <spec-basename>-<slug>-<browser>
        # Match by prefix — longest matching spec basename wins (avoid
        # "auth" matching "auth-domain-isolation" when both specs exist)
        matched_spec = None
        longest_match = 0
        for base, path in spec_bases.items():
            # Spec basename could contain dashes; folder name may truncate
            # to ~50 chars. Try prefix match on basename or shortened form.
            if entry.name.startswith(base + "-") and len(base) > longest_match:
                matched_spec = path
                longest_match = len(base)
        if matched_spec:
            try:
                mtime = entry.stat().st_mtime
            except OSError:
                mtime = 0
            failures.append({
                "spec": str(matched_spec.relative_to(REPO_ROOT)),
                "failure_folder": str(entry.relative_to(REPO_ROOT)),
                "mtime": mtime,
            })
    return failures


def read_playwright_last_run_status() -> tuple[str | None, list[str], str]:
    """Parse apps/web/test-results/.last-run.json for actual test outcome.

    Returns (status, failed_test_ids, report_path):
      - status: "passed" | "failed" | "interrupted" | None (no file)
      - failed_test_ids: list of failed test IDs (truncated to 10 in evidence)
      - report_path: relative path to the .last-run.json (for evidence)

    Playwright writes this on every `pnpm playwright test` exit. If AI ran
    tests but half failed, `status: "failed"` regardless of how many passed.
    Phase 14 OHOK v2 dogfood: status=failed with 4 failing tests but
    runtime-evidence validator PASSED because it only checked mtime existence.
    """
    last_run = REPO_ROOT / "apps" / "web" / "test-results" / ".last-run.json"
    if not last_run.exists():
        return None, [], ""
    try:
        data = json.loads(last_run.read_text(encoding="utf-8"))
    except Exception:
        return None, [], str(last_run.relative_to(REPO_ROOT))
    status = data.get("status")
    failed = data.get("failedTests") or []
    return status, failed, str(last_run.relative_to(REPO_ROOT))


def parse_goal_coverage_matrix(phase_dir: Path) -> list[dict]:
    """Parse GOAL-COVERAGE-MATRIX.md for goals + their status."""
    matrix = phase_dir / "GOAL-COVERAGE-MATRIX.md"
    if not matrix.exists():
        return []
    text = matrix.read_text(encoding="utf-8", errors="replace")
    # Heuristic: goal rows look like "| G-XX | priority | ... | status | ..."
    goals = []
    for line in text.splitlines():
        m = re.match(r"^\|\s*(G-\d+)\s*\|\s*(\w+)\s*\|.*?\|\s*(\w+)\s*\|", line)
        if m:
            goals.append({
                "id": m.group(1),
                "priority": m.group(2),
                "status": m.group(3),
            })
    return goals


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    ap.add_argument("--allow-unexecuted-specs", action="store_true",
                    help="override: log debt + continue")
    args = ap.parse_args()

    phase_dir = find_phase_dir(args.phase)
    if not phase_dir:
        print(json.dumps({
            "validator": "runtime-evidence",
            "verdict": "WARN",
            "evidence": [{"type": "missing_file",
                          "message": f"phase dir for {args.phase} not found"}]
        }))
        return 0

    specs = find_phase_specs(phase_dir)
    evidence = []
    verdict = "PASS"

    # CHECK -1 (OHOK-6, 2026-04-22 round 2): per-spec failure folders.
    # Must run BEFORE global status check because AI can run failing phase
    # specs, then run a trivial passing spec to flip `.last-run.json` to
    # "passed" (Pass-by-Proxy bypass). Per-spec scan catches this.
    per_spec_failures = find_per_spec_failures(specs) if specs else []
    if per_spec_failures:
        verdict = "BLOCK"
        sample = per_spec_failures[:8]
        evidence.append({
            "type": "per_spec_failure_folder",
            "message": (
                f"{len(per_spec_failures)} failure folder(s) in test-results/ "
                f"reference phase specs (regardless of global .last-run.json). "
                f"Pass-by-Proxy bypass blocked: even if latest run was a smoke "
                f"that passed, these folders prove phase specs failed."
            ),
            "evidence": [{
                "spec": f["spec"],
                "folder": f["failure_folder"],
            } for f in sample],
            "hint": (
                "Fix failing tests + delete test-results/* to clear stale evidence: "
                "`cd apps/web && rm -rf test-results/ && pnpm playwright test`"
            ),
        })

    # CHECK 0 (OHOK-3, 2026-04-22): actual Playwright outcome from global state.
    # Phase 14 incident: status=failed 4/5 tests but validator PASS.
    # OHOK-6: also guard against deletion fallthrough — if .last-run.json
    # is missing but specs exist, require explicit evidence.
    last_status, failed_tests, last_run_path = read_playwright_last_run_status()
    if last_status is None and specs:
        # OHOK-6 (Gemini P1): deletion fallthrough guard. Missing
        # .last-run.json + existing specs = no ground truth = BLOCK.
        # Previously fell through to weak mtime check.
        verdict = "BLOCK"
        evidence.append({
            "type": "missing_last_run_json",
            "message": (
                "apps/web/test-results/.last-run.json is missing but "
                f"{len(specs)} phase spec(s) exist. Cannot verify execution "
                "state. Deletion of .last-run.json is a bypass vector — "
                "explicit run required."
            ),
            "hint": "cd apps/web && pnpm playwright test",
        })
    elif last_status == "failed":
        verdict = "BLOCK"
        failed_sample = failed_tests[:10]
        evidence.append({
            "type": "playwright_failed",
            "message": (
                f"Playwright .last-run.json reports status='failed' with "
                f"{len(failed_tests)} failing test(s). Tests MUST pass before "
                f"runtime-evidence gate approves."
            ),
            "file": last_run_path,
            "failed_tests": failed_sample,
            "hint": (
                "Fix failing tests, then re-run: cd apps/web && pnpm playwright test. "
                "Override via /vg:review --allow-unexecuted-specs requires --override-reason."
            ),
        })
    elif last_status == "interrupted":
        verdict = "BLOCK"
        evidence.append({
            "type": "playwright_interrupted",
            "message": (
                "Playwright .last-run.json reports status='interrupted' "
                "(test run killed mid-flight). Cannot trust partial results."
            ),
            "file": last_run_path,
            "hint": "Re-run full suite: cd apps/web && pnpm playwright test",
        })
    elif last_status == "passed":
        evidence.append({
            "type": "playwright_passed",
            "message": "Playwright .last-run.json reports status='passed'",
            "file": last_run_path,
        })

    if not specs:
        # No specs found for phase. Warn only — might be backend-only phase
        # with legitimate no-UI goals. Let matrix coverage gate handle it.
        evidence.append({
            "type": "info",
            "message": f"no Playwright specs found matching phase slug "
                       f"tokens: {sorted(phase_slug_tokens(phase_dir))}"
        })
    else:
        # Reference point: phase's SPECS.md mtime (blueprint time)
        specs_md = phase_dir / "SPECS.md"
        since_mtime = specs_md.stat().st_mtime if specs_md.exists() else 0

        unexecuted = []
        for spec in specs:
            ran, report = check_playwright_run_evidence(spec, since_mtime)
            if ran:
                evidence.append({
                    "type": "execution_proof",
                    "message": f"{spec.name} executed, report at {report}",
                    "file": str(spec.relative_to(REPO_ROOT)),
                })
            else:
                unexecuted.append(spec)
                evidence.append({
                    "type": "unexecuted_spec",
                    "message": f"{spec.name} exists but no playwright-report/"
                               f" or test-results/ entry newer than SPECS.md. "
                               f"Setup: cd apps/web && pnpm playwright test "
                               f"{spec.relative_to(REPO_ROOT/'apps/web')}",
                    "file": str(spec.relative_to(REPO_ROOT)),
                })

        if unexecuted and not args.allow_unexecuted_specs:
            verdict = "BLOCK"

    # Check GOAL-COVERAGE-MATRIX for goals marked READY without runtime proof
    goals = parse_goal_coverage_matrix(phase_dir)
    code_only_critical = []
    for g in goals:
        # If goal marked READY but no Playwright ran → suspect "code evidence"
        # rationalization. Critical goals need runtime proof.
        if g["status"].upper() == "READY" and g["priority"].lower() == "critical":
            if specs and verdict == "BLOCK":
                code_only_critical.append(g["id"])

    if code_only_critical:
        evidence.append({
            "type": "code_only_critical_goals",
            "message": f"Critical goals marked READY without runtime proof: "
                       f"{', '.join(code_only_critical)}. Run Playwright specs "
                       f"or mark as deferred|manual with reason.",
        })

    print(json.dumps({
        "validator": "runtime-evidence",
        "verdict": verdict,
        "evidence": evidence,
        "duration_ms": 0,
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
