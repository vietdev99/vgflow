#!/usr/bin/env python3
"""verify-role-swap-coverage.py — B111 v4.71.1.

Verify multi-actor goals have role-swap evidence in generated Playwright
specs. Pre-B111, codegen ran whole spec as the FIRST actor; role-B-only
branches (admin approval, viewer 403, etc.) never executed → UAT phase
caught conditional-visibility / RBAC bugs.

Each goal with `role_swap_assertion` metadata requires the spec to
contain at least one of:
  - `browser.newContext(` (per-actor context isolation)
  - `loginAs('<actor>'` / `loginAs(\"<actor>\"`
  - `await context.close(` followed by `newContext(`
  - `await page.context().clearCookies(` followed by login flow

Severity warn initially. Operator flips to block after fixture surface
(`loginAs` helper or per-actor context) is in apps/<app>/e2e/utils/.

Exit codes:
  0 PASS / warn mode with findings
  1 FAIL (block mode)
  2 internal error
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


_NEW_CONTEXT_RE = re.compile(r"browser\.newContext\(")
# Accept any arg order: loginAs('admin'), loginAs(page, 'admin'),
# loginAs({ role: 'admin' })
_LOGIN_AS_RE = re.compile(
    r"loginAs\s*\([^)]*['\"]([A-Za-z_][\w-]*)['\"]",
)
_CONTEXT_FOR_RE = re.compile(
    r"contextFor\s*\([^)]*['\"]([A-Za-z_][\w-]*)['\"]",
)
_LOGOUT_LOGIN_RE = re.compile(
    r"(?:clearCookies|context\.close|signOut|logout)[\s\S]{0,200}"
    r"(?:loginAs|signIn|page\.goto\([^)]*login)",
    re.IGNORECASE,
)


def _load_lifecycle(phase_dir: Path) -> dict:
    p = phase_dir / "LIFECYCLE-SPECS.json"
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _gather_specs(phase_dir: Path) -> list[Path]:
    out: list[Path] = []
    for sub in ("playwright-specs", "PLAYWRIGHT-SPECS", "e2e", "tests"):
        d = phase_dir / sub
        if d.is_dir():
            out.extend(d.rglob("*.spec.ts"))
            out.extend(d.rglob("*.spec.js"))
            out.extend(d.rglob("*.spec.tsx"))
    repo = Path.cwd()
    apps = repo / "apps"
    if apps.is_dir():
        for app in apps.iterdir():
            if not app.is_dir():
                continue
            for e2e in (app / "e2e", app / "tests"):
                if e2e.is_dir():
                    out.extend(e2e.rglob("*.spec.ts"))
                    out.extend(e2e.rglob("*.spec.js"))
    return out


def _spec_text_for_goal(goal_id: str, specs: list[Path]) -> str:
    parts: list[str] = []
    pat = re.compile(rf"\b{re.escape(goal_id)}\b")
    for f in specs:
        try:
            t = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        if pat.search(t):
            parts.append(t)
    return "\n".join(parts)


def _audit_goal(goal_id: str, goal: dict, specs: list[Path]) -> dict:
    # Find all role_swap_assertion entries in goal steps
    swap_steps = [
        s for s in (goal.get("steps") or [])
        if isinstance(s, dict) and s.get("role_swap_assertion")
    ]
    if not swap_steps:
        return {"goal_id": goal_id, "needs_role_swap": False, "findings": []}
    # Expected actors set from metadata
    expected_actors: set[str] = set()
    for s in swap_steps:
        rsa = s.get("role_swap_assertion") or {}
        for a in rsa.get("actors_in_workflow") or []:
            expected_actors.add(a)
    spec_text = _spec_text_for_goal(goal_id, specs)
    findings: list[str] = []
    if not spec_text:
        findings.append("no Playwright spec file references this goal")
        return {
            "goal_id": goal_id,
            "needs_role_swap": True,
            "expected_actors": sorted(expected_actors),
            "findings": findings,
        }
    seen_actors: set[str] = set()
    seen_actors.update(m.group(1) for m in _LOGIN_AS_RE.finditer(spec_text))
    seen_actors.update(m.group(1) for m in _CONTEXT_FOR_RE.finditer(spec_text))
    has_swap_mechanism = bool(
        _NEW_CONTEXT_RE.search(spec_text)
        or _LOGIN_AS_RE.search(spec_text)
        or _CONTEXT_FOR_RE.search(spec_text)
        or _LOGOUT_LOGIN_RE.search(spec_text)
    )
    if not has_swap_mechanism:
        findings.append(
            f"multi-actor goal ({len(expected_actors)} actors) but spec has "
            f"no role-swap mechanism (newContext / loginAs / "
            f"contextFor / logout+login)"
        )
    missing_actors = expected_actors - seen_actors
    # Don't flag missing-actor when no loginAs/contextFor pattern was
    # detected at all — that means the spec uses newContext or
    # logout+login pattern; harder to extract names. Only flag when
    # SOME actors are present but others missing.
    if seen_actors and missing_actors:
        findings.append(
            f"goal declares actors {sorted(expected_actors)} but spec only "
            f"exercises {sorted(seen_actors)} — missing: "
            f"{sorted(missing_actors)}"
        )
    return {
        "goal_id": goal_id,
        "needs_role_swap": True,
        "expected_actors": sorted(expected_actors),
        "findings": findings,
    }


def main() -> int:
    ap = argparse.ArgumentParser(prog="verify-role-swap-coverage")
    ap.add_argument("--phase-dir", required=True)
    ap.add_argument("--severity", choices=("warn", "block"), default="warn")
    ap.add_argument("--json", dest="json_out", action="store_true", default=True)
    ap.add_argument("--no-json", dest="json_out", action="store_false")
    args = ap.parse_args()
    try:
        phase_dir = Path(args.phase_dir).resolve()
        lifecycle = _load_lifecycle(phase_dir)
        goal_map = lifecycle.get("goals") or lifecycle.get("specs") or {}
        specs = _gather_specs(phase_dir)
        audits = []
        for gid, gdata in goal_map.items():
            entry = _audit_goal(gid, gdata, specs)
            if entry["needs_role_swap"]:
                audits.append(entry)
        total_findings = sum(len(a["findings"]) for a in audits)
        result = {
            "phase_dir": str(phase_dir),
            "multi_actor_goals": len(audits),
            "spec_files_seen": len(specs),
            "total_findings": total_findings,
            "audits": audits,
            "severity": args.severity,
            "status": "PASS" if total_findings == 0 else "FAIL",
        }
        if args.json_out:
            print(json.dumps(result, indent=2))
        else:
            print(f"verify-role-swap-coverage — {result['status']}")
            for a in audits:
                if a["findings"]:
                    print(f"  - {a['goal_id']}:")
                    for f in a["findings"]:
                        print(f"      * {f}")
        if result["status"] == "PASS":
            return 0
        return 1 if args.severity == "block" else 0
    except Exception as exc:
        print(f"verify-role-swap-coverage: internal error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
