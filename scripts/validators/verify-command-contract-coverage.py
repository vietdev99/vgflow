#!/usr/bin/env python3
"""
verify-command-contract-coverage.py — Phase J of v2.5.2 hardening.

Problem closed:
  Only 7/41 VG commands had runtime_contract (specs, scope, blueprint,
  build, review, test, accept). The other 34 could mutate repo state,
  .vg/ artifacts, telemetry DB, or git — all without producing evidence
  the Stop hook could verify. Any of them (project, roadmap, amend, learn,
  security-audit-milestone, sync, update, reapply-patches, bootstrap,
  override-resolve, phase, next, recover, migrate, add-phase, remove-phase,
  scope-review) = unguarded forge surface.

This validator enforces universal coverage: every mutating command MUST
declare runtime_contract. Read-only commands must explicitly opt out via
observation_only=true + contract_exempt_reason.

Heuristics for mutates_repo detection (if not explicitly declared):
  - Frontmatter has runtime_contract → mutates_repo=true (already declared)
  - Body has "git commit", "git push", "git tag" → likely mutates
  - Body has Write/Edit tool invocations → mutates
  - Body has "emit-event", "mark-step", "run-start" → mutates
  - Body ONLY reads (grep/cat/Read tool) → observation_only candidate

Exit codes:
  0 = all commands covered (contracts OR exempt with reason)
  1 = coverage gaps detected
  2 = path/config error

Usage:
  verify-command-contract-coverage.py                # human report
  verify-command-contract-coverage.py --json         # machine-readable
  verify-command-contract-coverage.py --quiet        # suppress if clean
  verify-command-contract-coverage.py --strict       # treat heuristic = missing
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

# Commands classified as read-only / observation-only. They emit telemetry
# but don't mutate repo state, .vg/ artifacts, or git. Must carry
# observation_only=true + contract_exempt_reason in frontmatter.
EXPECTED_OBSERVATION_ONLY = frozenset({
    "progress", "health", "doctor", "gate-stats", "telemetry", "integrity",
    "regression", "prioritize",
})

# Mutating commands that MUST have runtime_contract per v2.5.2 Phase J.
# Derived from existing 7 + 17 Phase J backfill targets. Union with any
# skill file found that isn't in EXPECTED_OBSERVATION_ONLY.
KNOWN_MUTATING = frozenset({
    # Already had contract (v2.5.1):
    "specs", "scope", "blueprint", "build", "review", "test", "accept",
    # Phase J backfill targets:
    "project", "roadmap", "amend", "learn", "phase", "next", "recover",
    "sync", "update", "reapply-patches", "bootstrap", "override-resolve",
    "security-audit-milestone", "scope-review", "migrate", "add-phase",
    "remove-phase", "migrate-planning-vg", "lesson", "bug-report",
    "design-extract", "design-system", "extract-utils", "map",
    "setup-mobile", "init",
})


def _resolve_repo_root() -> Path:
    env = os.environ.get("REPO_ROOT")
    if env:
        return Path(env).resolve()
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL, text=True,
        )
        return Path(out.strip()).resolve()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return Path.cwd().resolve()


def _parse_frontmatter(text: str) -> dict:
    """Extract YAML frontmatter from .md file (between first two `---` lines)."""
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not m:
        return {}
    fm_text = m.group(1)
    # Minimal YAML parse — we only need 3 specific keys.
    # Full yaml.safe_load would be cleaner but adds dependency.
    result = {}
    # runtime_contract presence
    if re.search(r"^runtime_contract:", fm_text, re.MULTILINE):
        result["has_runtime_contract"] = True
    # mutates_repo
    m2 = re.search(r"^mutates_repo:\s*(true|false)", fm_text, re.MULTILINE)
    if m2:
        result["mutates_repo"] = m2.group(1) == "true"
    # observation_only
    m3 = re.search(r"^observation_only:\s*(true|false)", fm_text, re.MULTILINE)
    if m3:
        result["observation_only"] = m3.group(1) == "true"
    # contract_exempt_reason
    m4 = re.search(
        r'^contract_exempt_reason:\s*["\']?([^"\'\n]+)["\']?',
        fm_text, re.MULTILINE,
    )
    if m4:
        result["contract_exempt_reason"] = m4.group(1).strip()
    return result


_MUTATION_PATTERNS = [
    r"\bgit\s+commit\b",
    r"\bgit\s+push\b",
    r"\bgit\s+tag\b",
    r"\bgit\s+add\b",
    r"\bgit\s+reset\b",
    r"\bemit-event\b",
    r"\bmark-step\b",
    r"\brun-start\b",
    r"\brun-complete\b",
    r"\bWrite\b.*\bfile_path\b",   # Write tool invocation in prose
    r"\bEdit\b.*\bfile_path\b",    # Edit tool invocation in prose
    r">\s*\$\{?PHASE_DIR\}?",      # redirect into phase dir
    r">\s*['\"]?\.vg/",            # redirect into .vg/
]


def _body_looks_mutating(text: str) -> bool:
    body = re.sub(r"^---\n.*?\n---\n", "", text, count=1, flags=re.DOTALL)
    for pattern in _MUTATION_PATTERNS:
        if re.search(pattern, body):
            return True
    return False


def _classify_command(name: str, path: Path) -> dict:
    """Return classification dict for one skill file."""
    result = {
        "command": name,
        "path": str(path),
        "expected_mutates": name in KNOWN_MUTATING,
        "expected_observation_only": name in EXPECTED_OBSERVATION_ONLY,
    }

    try:
        text = path.read_text(encoding="utf-8")
    except (FileNotFoundError, PermissionError) as e:
        result["error"] = f"read failed: {e}"
        return result

    fm = _parse_frontmatter(text)
    result["has_runtime_contract"] = fm.get("has_runtime_contract", False)
    result["mutates_repo_declared"] = fm.get("mutates_repo")
    result["observation_only"] = fm.get("observation_only", False)
    result["contract_exempt_reason"] = fm.get("contract_exempt_reason")
    result["body_looks_mutating"] = _body_looks_mutating(text)

    # Verdict logic:
    verdict = "OK"
    reasons = []

    expected_mut = result["expected_mutates"]
    expected_obs = result["expected_observation_only"]
    has_contract = result["has_runtime_contract"]
    obs_only = result["observation_only"]
    exempt_reason = result["contract_exempt_reason"]

    if expected_mut:
        # Must have runtime_contract
        if not has_contract:
            verdict = "MISSING_CONTRACT"
            reasons.append(
                f"'{name}' is mutating (in KNOWN_MUTATING) but has no "
                f"runtime_contract frontmatter block"
            )
    elif expected_obs:
        # Must declare observation_only + contract_exempt_reason
        if not obs_only:
            verdict = "MISSING_OBSERVATION_DECL"
            reasons.append(
                f"'{name}' is read-only (in EXPECTED_OBSERVATION_ONLY) but "
                f"missing `observation_only: true` in frontmatter"
            )
        elif not exempt_reason or len(exempt_reason) < 10:
            verdict = "MISSING_EXEMPT_REASON"
            reasons.append(
                f"'{name}' has observation_only=true but "
                f"contract_exempt_reason missing or <10 chars"
            )
    else:
        # Not in either allowlist — use heuristic
        body_mut = result["body_looks_mutating"]
        if has_contract:
            # Already has contract — probably fine
            pass
        elif obs_only and exempt_reason and len(exempt_reason) >= 10:
            # Self-declared observation-only — trust it
            pass
        elif body_mut:
            verdict = "HEURISTIC_MUTATING"
            reasons.append(
                f"'{name}' body contains mutation patterns "
                f"(git/emit-event/Write/etc.) but no runtime_contract AND "
                f"no observation_only=true declaration"
            )
        else:
            verdict = "UNCLASSIFIED"
            reasons.append(
                f"'{name}' neither declares observation_only nor shows "
                f"mutation patterns — classify explicitly"
            )

    result["verdict"] = verdict
    result["reasons"] = reasons
    return result


def _report_human(results: list[dict], quiet: bool) -> str:
    issues = [r for r in results if r["verdict"] != "OK"]
    if not issues and quiet:
        return ""

    lines = []
    total = len(results)
    ok_count = sum(1 for r in results if r["verdict"] == "OK")

    if issues:
        lines.append(
            f"⛔ Command contract coverage: {len(issues)}/{total} command(s) "
            f"need fix\n"
        )
        grouped: dict = {}
        for r in issues:
            grouped.setdefault(r["verdict"], []).append(r["command"])
        for verdict, cmds in sorted(grouped.items()):
            lines.append(f"  [{verdict}] ({len(cmds)})")
            for c in sorted(cmds):
                lines.append(f"    - {c}.md")
            lines.append("")

        lines.append("Fix by verdict:")
        if "MISSING_CONTRACT" in grouped:
            lines.append(
                "  MISSING_CONTRACT: add `runtime_contract:` frontmatter "
                "with must_write + must_emit_telemetry"
            )
        if "MISSING_OBSERVATION_DECL" in grouped:
            lines.append(
                "  MISSING_OBSERVATION_DECL: add `observation_only: true` "
                "+ `contract_exempt_reason: \"read-only: ...\"`"
            )
        if "MISSING_EXEMPT_REASON" in grouped:
            lines.append(
                "  MISSING_EXEMPT_REASON: add `contract_exempt_reason` "
                "≥10 chars explaining why exempt"
            )
        if "HEURISTIC_MUTATING" in grouped:
            lines.append(
                "  HEURISTIC_MUTATING: body shows mutation; add "
                "runtime_contract OR observation_only=true"
            )
        if "UNCLASSIFIED" in grouped:
            lines.append(
                "  UNCLASSIFIED: classify explicitly via mutates_repo field"
            )
        lines.append("")
    else:
        if not quiet:
            lines.append(
                f"✓ Command contract coverage OK — {ok_count}/{total} "
                f"commands covered"
            )
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--quiet", action="store_true",
                    help="suppress output when clean")
    ap.add_argument("--json", action="store_true",
                    help="emit JSON for programmatic consumers")
    ap.add_argument("--strict", action="store_true",
                    help="treat HEURISTIC_MUTATING as hard miss (no grace)")
    ap.add_argument("--command", default=None,
                    help="check one command only by name")
    ap.add_argument("--phase", help="(orchestrator-injected; ignored by this validator)")
    args = ap.parse_args()

    repo_root = _resolve_repo_root()
    commands_dir = repo_root / ".claude" / "commands" / "vg"

    if not commands_dir.is_dir():
        print(f"⛔ Commands dir not found: {commands_dir}", file=sys.stderr)
        return 2

    # Discover skill files
    skill_files = sorted(commands_dir.glob("*.md"))
    # Skip staging + template
    skill_files = [
        f for f in skill_files
        if not f.stem.startswith("_") and f.stem != "README"
    ]

    if args.command:
        skill_files = [
            f for f in skill_files if f.stem == args.command
        ]
        if not skill_files:
            print(f"⛔ Command not found: {args.command}", file=sys.stderr)
            return 2

    results = []
    for sk in skill_files:
        results.append(_classify_command(sk.stem, sk))

    # Apply --strict: normally HEURISTIC_MUTATING is soft; strict treats
    # it same as MISSING_CONTRACT.
    if not args.strict:
        # Relax heuristic + unclassified → still log but don't fail
        for r in results:
            if r["verdict"] in ("HEURISTIC_MUTATING", "UNCLASSIFIED"):
                r["verdict_original"] = r["verdict"]
                r["verdict"] = "OK"

    issues = sum(1 for r in results if r["verdict"] != "OK")

    if args.json:
        # v2.6.1 (2026-04-26): top-level verdict for orchestrator schema.
        # Closes AUDIT.md D1 schema drift S3 — without verdict field,
        # dispatch silently treats issues as PASS.
        print(json.dumps({
            "validator": "verify-command-contract-coverage",
            "verdict": "BLOCK" if issues > 0 else "PASS",
            "repo_root": str(repo_root),
            "commands_checked": len(results),
            "issue_count": issues,
            "results": results,
        }, indent=2))
    else:
        out = _report_human(results, args.quiet)
        if out:
            print(out)

    return 1 if issues > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
