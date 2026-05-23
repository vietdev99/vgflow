#!/usr/bin/env python3
"""verify-fe-form-submit-coverage.py — B106 v4.70.0.

Purpose
-------
Close the FE form-submission coverage gap between `/vg:test` PASS and
human UAT. Pre-B106, mutation goals could ship green-tests yet still hit
4xx silently, miss success-toast, fail navigation — top 50% of UAT bugs.

This validator scans generated Playwright specs against the lifecycle
spec's `network_assertion` + `success_assertion` metadata (B106 generator
injects). Each mutation goal's spec MUST contain:
  - `page.waitForResponse` OR `page.on('response')` AND
  - A status check that asserts < 400 OR validates the error toast path AND
  - For goals with `success_assertion`: locator-visibility assertion OR
    `page.waitForURL` / `page.waitForNavigation`

Where the metadata is missing on the spec side, the validator BLOCKs
(severity=warn initially, flip to block once dogfood validates).

Inputs
------
  --phase <id>                Resolve phase dir from .vg/phases/
  --phase-dir <path>          Absolute phase dir (bypasses resolution)
  --severity warn|block       warn = exit 0 on findings; block = exit 1

Exit codes
----------
  0 - PASS (or WARN under --severity warn)
  1 - FAIL (under --severity block)
  2 - Internal error
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


# Patterns to detect coverage in spec text
_NETWORK_CAPTURE_RE = re.compile(
    r"\b(page\.waitForResponse|page\.on\(['\"]response['\"]|"
    r"page\.waitForRequest|context\.on\(['\"]response['\"])",
)
_STATUS_LT_400_RE = re.compile(
    r"(\.status\(\)\s*<\s*400|toBeLessThan\(400\)|toBe(?:Less|)\(2\d\d\)|"
    r"expect\([^)]*status[^)]*\)\.toBeLessThan)",
    re.IGNORECASE,
)
_ERROR_TOAST_RE = re.compile(
    r"(\[role=['\"]alert['\"]|data-testid=['\"][^'\"]*error[^'\"]*['\"]|"
    r"\.error[-_]?(?:banner|toast|message)|class\*=['\"]Error)",
    re.IGNORECASE,
)
_SUCCESS_FEEDBACK_RE = re.compile(
    r"(\[role=['\"]status['\"]|data-testid=['\"][^'\"]*success[^'\"]*['\"]|"
    r"\.success[-_]?(?:banner|toast|message)|class\*=['\"]Success|"
    r"toBeVisible|isVisible)",
    re.IGNORECASE,
)
_NAVIGATION_RE = re.compile(
    r"(page\.waitForURL|page\.waitForNavigation|expect\(page\)\.toHaveURL)",
)


def _find_phase_dir(phase: str | None, phase_dir_arg: str | None) -> Path | None:
    if phase_dir_arg:
        p = Path(phase_dir_arg).resolve()
        return p if p.is_dir() else None
    if not phase:
        return None
    phases_dir = Path.cwd() / ".vg" / "phases"
    if not phases_dir.is_dir():
        return None
    for cand in sorted(phases_dir.iterdir()):
        if not cand.is_dir():
            continue
        n = cand.name
        if n == phase or n.startswith(f"{phase}-") or n == phase.zfill(2):
            return cand
    return None


def _load_lifecycle_specs(phase_dir: Path) -> list[dict]:
    """Return mutation goals (those carrying B106 assertion metadata).

    B106 ships with the lifecycle generator emitting the per-goal specs
    under the `goals` key (scripts/generate-lifecycle-specs.py:2030).
    Earlier versions and external test fixtures sometimes used `specs`.
    Both are accepted so the validator doesn't silently audit zero goals
    when the root key changes — Codex postmortem 2026-05-23 caught this
    JSON-root mismatch class.
    """
    spec_path = phase_dir / "LIFECYCLE-SPECS.json"
    if not spec_path.is_file():
        return []
    try:
        payload = json.loads(spec_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    # Accept either root key. Canonical = "goals" (per generator). Tolerate
    # legacy/test "specs" to avoid silent zero-audit on stale phases.
    goal_map = payload.get("goals") or payload.get("specs") or {}
    out: list[dict] = []
    for goal_id, spec in goal_map.items():
        steps = spec.get("steps") or []
        # Only goals with at least one mutation stage step carrying B106 meta
        has_meta = any(
            step.get("network_assertion") or step.get("success_assertion")
            for step in steps
        )
        if not has_meta:
            continue
        out.append({"goal_id": goal_id, "spec": spec})
    return out


def _gather_spec_files(phase_dir: Path) -> list[Path]:
    """Per-phase Playwright spec files. Look in:
      - phase_dir/playwright-specs/ (canonical)
      - phase_dir/PLAYWRIGHT-SPECS/ (alt case)
      - apps/*/e2e/*.spec.ts under repo root (B92+ codegen)
    Returns all matching files; downstream checks tolerate ambiguity.
    """
    repo_root = Path.cwd()
    out: list[Path] = []
    for sub in ("playwright-specs", "PLAYWRIGHT-SPECS", "e2e", "tests"):
        d = phase_dir / sub
        if d.is_dir():
            out.extend(d.rglob("*.spec.ts"))
            out.extend(d.rglob("*.spec.js"))
            out.extend(d.rglob("*.spec.tsx"))
    apps_dir = repo_root / "apps"
    if apps_dir.is_dir():
        for app in apps_dir.iterdir():
            if not app.is_dir():
                continue
            for e2e in (app / "e2e", app / "tests"):
                if e2e.is_dir():
                    out.extend(e2e.rglob("*.spec.ts"))
                    out.extend(e2e.rglob("*.spec.js"))
    return out


def _spec_text_for_goal(goal_id: str, spec_files: list[Path]) -> str:
    """Return concatenated text of all spec files that reference the goal id."""
    parts: list[str] = []
    pattern = re.compile(rf"\b{re.escape(goal_id)}\b")
    for f in spec_files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        if pattern.search(text):
            parts.append(text)
    return "\n".join(parts)


def _audit_goal(goal_entry: dict, spec_files: list[Path]) -> dict:
    goal_id = goal_entry["goal_id"]
    spec = goal_entry["spec"]
    steps = spec.get("steps") or []
    needs_network = any(s.get("network_assertion") for s in steps)
    needs_success = any(s.get("success_assertion") for s in steps)
    spec_text = _spec_text_for_goal(goal_id, spec_files)
    findings: list[str] = []
    if needs_network:
        if not _NETWORK_CAPTURE_RE.search(spec_text):
            findings.append(
                "missing network capture (page.waitForResponse / "
                "page.on('response')) for mutation submit"
            )
        else:
            if not _STATUS_LT_400_RE.search(spec_text) and not _ERROR_TOAST_RE.search(spec_text):
                findings.append(
                    "network captured but no status<400 assert AND no "
                    "error-toast assertion — 4xx will pass silently"
                )
    if needs_success:
        has_toast = bool(_SUCCESS_FEEDBACK_RE.search(spec_text))
        has_nav = bool(_NAVIGATION_RE.search(spec_text))
        nav_expected = any(
            (s.get("success_assertion") or {}).get("expect_navigation_to")
            for s in steps
        )
        if nav_expected and not has_nav:
            findings.append(
                "mutation_evidence implies redirect but spec has no "
                "page.waitForURL / page.waitForNavigation"
            )
        if not nav_expected and not has_toast:
            findings.append(
                "mutation_evidence implies success feedback but spec has no "
                "success-toast / status-locator visibility assertion"
            )
    return {
        "goal_id": goal_id,
        "spec_files_seen": bool(spec_text),
        "findings": findings,
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="verify-fe-form-submit-coverage",
        description=(
            "B106 v4.70.0 — verify generated Playwright specs cover FE form "
            "submission paths (response status, error toast, success message, "
            "redirect) for every mutation goal. Closes top 50% UAT bug classes "
            "(form 4xx silently swallowed, missing success message, broken "
            "redirect) before human UAT step."
        ),
    )
    ap.add_argument("--phase")
    ap.add_argument("--phase-dir")
    ap.add_argument("--severity", choices=("warn", "block"), default="warn")
    ap.add_argument("--json", dest="json_out", action="store_true", default=True)
    ap.add_argument("--no-json", dest="json_out", action="store_false")
    args = ap.parse_args()
    try:
        phase_dir = _find_phase_dir(args.phase, args.phase_dir)
        if not phase_dir:
            payload = {
                "status": "ERROR",
                "message": "phase dir not resolved; pass --phase or --phase-dir",
            }
            print(json.dumps(payload))
            return 2
        mutation_entries = _load_lifecycle_specs(phase_dir)
        spec_files = _gather_spec_files(phase_dir)
        audits = [_audit_goal(e, spec_files) for e in mutation_entries]
        total_findings = sum(len(a["findings"]) for a in audits)
        # B106.1 (Codex postmortem 2026-05-23): when phase carries mutation
        # goals but audit count is zero, that's a HARNESS bug (wrong JSON
        # root, missing B106 metadata, regen drift) — surface as a finding
        # not a silent PASS.
        has_lifecycle_file = (phase_dir / "LIFECYCLE-SPECS.json").is_file()
        zero_audit_with_mutation_goals = False
        if has_lifecycle_file and len(audits) == 0:
            try:
                payload = json.loads((phase_dir / "LIFECYCLE-SPECS.json").read_text(encoding="utf-8"))
                goal_map = payload.get("goals") or payload.get("specs") or {}
                mutation_goal_count = sum(
                    1 for g in goal_map.values()
                    if (g.get("goal_class") or "").lower() in {"mutation", "create-only", "update-only", "delete-only"}
                    or (g.get("goal_type") or "").lower() in {"mutation", "multi-actor", "workflow"}
                )
                zero_audit_with_mutation_goals = mutation_goal_count > 0
            except Exception:
                pass
        result = {
            "phase_dir": str(phase_dir),
            "severity": args.severity,
            "mutation_goals_audited": len(audits),
            "spec_files_seen": len(spec_files),
            "total_findings": total_findings,
            "goals_with_findings": sum(1 for a in audits if a["findings"]),
            "zero_audit_with_mutation_goals": zero_audit_with_mutation_goals,
            "audits": audits,
            "status": (
                "PASS" if total_findings == 0 and not zero_audit_with_mutation_goals
                else "FAIL"
            ),
        }
        if zero_audit_with_mutation_goals:
            result["zero_audit_diagnostic"] = (
                "LIFECYCLE-SPECS.json contains mutation goals but B106 audit "
                "found 0 entries with network_assertion/success_assertion "
                "metadata — possible JSON-root mismatch, generator regen "
                "needed, or B106 not yet propagated to this phase."
            )
        if args.json_out:
            print(json.dumps(result, indent=2))
        else:
            print(f"verify-fe-form-submit-coverage — {result['status']}")
            print(f"  goals_audited: {result['mutation_goals_audited']}")
            print(f"  spec_files: {result['spec_files_seen']}")
            print(f"  total_findings: {total_findings}")
            for a in audits:
                if a["findings"]:
                    print(f"  - {a['goal_id']}:")
                    for f in a["findings"]:
                        print(f"      * {f}")
        if result["status"] == "PASS":
            return 0
        if args.severity == "warn":
            return 0
        return 1
    except Exception as exc:
        print(f"verify-fe-form-submit-coverage: internal error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
