#!/usr/bin/env python3
"""
verify-container-hardening.py — Phase M Batch 1 of v2.5.2 hardening.

Problem closed:
  Static Dockerfile lint tools are often noisy + not wired into the VG
  release gate. This validator checks a focused subset of container
  hardening rules that are trust-anchor for production RTB services:

Dockerfile checks:
  1. USER directive present + not `root` / `0`     (BLOCK if root)
  2. Base image has specific tag (not `latest`)    (BLOCK)
  3. HEALTHCHECK present                           (WARN if missing)
  4. No `ADD http(s)://...`                        (BLOCK — supply chain risk)
  5. WORKDIR set                                   (WARN)
  6. alpine/distroless minimal base                (WARN on full distros)
  7. Multi-stage build detected (>=2 FROM)         (INFO — good practice)

docker-compose.yml checks (if present alongside Dockerfile):
  1. read_only: true                               (WARN if absent)
  2. cap_drop: [ALL]                               (WARN if absent)
  3. mem_limit / cpus set                          (WARN if absent)

Exit codes:
  0 = well-hardened (or WARN-only)
  1 = BLOCK condition met (root user, latest tag, ADD http)
  2 = config error (Dockerfile not found AND --require)

Usage:
  verify-container-hardening.py                     # auto-detect
  verify-container-hardening.py --dockerfile apps/api/Dockerfile
  verify-container-hardening.py --compose docker-compose.yml
  verify-container-hardening.py --require --json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


# ─── Dockerfile parsing ────────────────────────────────────────────────

FROM_RE = re.compile(r"^\s*FROM\s+(.+?)(?:\s+AS\s+\S+)?\s*$",
                     re.IGNORECASE | re.MULTILINE)
USER_RE = re.compile(r"^\s*USER\s+(\S+)", re.IGNORECASE | re.MULTILINE)
HEALTHCHECK_RE = re.compile(r"^\s*HEALTHCHECK\b", re.IGNORECASE | re.MULTILINE)
WORKDIR_RE = re.compile(r"^\s*WORKDIR\s+\S+", re.IGNORECASE | re.MULTILINE)
ADD_HTTP_RE = re.compile(r"^\s*ADD\s+https?://", re.IGNORECASE | re.MULTILINE)


MINIMAL_BASES = ("alpine", "distroless", "slim", "scratch")


def _check_dockerfile(path: Path) -> list[dict]:
    violations: list[dict] = []
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return [{"severity": "BLOCK",
                 "check": "unreadable",
                 "issue": f"{path}: {e}"}]

    # Strip comments
    lines = [ln for ln in content.splitlines()
             if not ln.strip().startswith("#")]
    stripped = "\n".join(lines)

    froms = FROM_RE.findall(stripped)
    if not froms:
        violations.append({"severity": "BLOCK", "check": "no_from",
                           "issue": "no FROM directive"})
        return violations

    # Multi-stage detection
    stages = len(froms)

    # Check every base image — last one is runtime
    runtime_base = froms[-1].strip()
    if ":" not in runtime_base or runtime_base.endswith(":latest"):
        violations.append({
            "severity": "BLOCK", "check": "latest_tag",
            "issue": f"runtime base {runtime_base!r} uses :latest or no tag",
        })

    # Minimal surface preference
    if not any(k in runtime_base.lower() for k in MINIMAL_BASES):
        violations.append({
            "severity": "WARN", "check": "full_distro",
            "issue": (
                f"runtime base {runtime_base!r} not alpine/distroless/slim/"
                "scratch — larger attack surface"
            ),
        })

    # USER directive
    user_matches = USER_RE.findall(stripped)
    last_user = user_matches[-1].strip() if user_matches else None
    if last_user is None:
        violations.append({
            "severity": "BLOCK", "check": "no_user",
            "issue": "no USER directive — container runs as root",
        })
    elif last_user.lower() in ("root", "0"):
        violations.append({
            "severity": "BLOCK", "check": "root_user",
            "issue": f"USER {last_user} — container runs as root",
        })

    # HEALTHCHECK
    if not HEALTHCHECK_RE.search(stripped):
        violations.append({
            "severity": "WARN", "check": "no_healthcheck",
            "issue": "HEALTHCHECK directive missing",
        })

    # WORKDIR
    if not WORKDIR_RE.search(stripped):
        violations.append({
            "severity": "WARN", "check": "no_workdir",
            "issue": "WORKDIR not set",
        })

    # ADD http:// or https://
    if ADD_HTTP_RE.search(stripped):
        violations.append({
            "severity": "BLOCK", "check": "add_external_url",
            "issue": "ADD <http(s)://...> is a supply-chain risk; "
                     "use RUN curl + verify checksum",
        })

    # Multi-stage info (not a violation, info-only in report)
    if stages >= 2:
        violations.append({
            "severity": "INFO", "check": "multi_stage",
            "issue": f"multi-stage build detected ({stages} stages) — good",
        })

    return violations


# ─── docker-compose.yml parsing (light YAML, stdlib only) ─────────────

def _check_compose(path: Path) -> list[dict]:
    violations: list[dict] = []
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return [{"severity": "WARN", "check": "unreadable",
                 "issue": f"{path}: {e}"}]

    # Light heuristics — we don't want to add PyYAML as dep
    has_readonly = bool(
        re.search(r"^\s*read_only\s*:\s*true\s*$",
                  content, re.IGNORECASE | re.MULTILINE)
    )
    has_cap_drop_all = bool(
        re.search(
            r"cap_drop\s*:\s*\n\s*-\s*(ALL|['\"]ALL['\"])\b",
            content, re.IGNORECASE,
        )
        or re.search(r"cap_drop\s*:\s*\[\s*['\"]?ALL['\"]?\s*\]",
                     content, re.IGNORECASE)
    )
    has_mem_limit = bool(
        re.search(r"^\s*(mem_limit|memory|cpus|limits)\s*:",
                  content, re.IGNORECASE | re.MULTILINE)
    )

    if not has_readonly:
        violations.append({
            "severity": "WARN", "check": "compose_no_readonly",
            "issue": "no `read_only: true` on services — writable FS",
        })
    if not has_cap_drop_all:
        violations.append({
            "severity": "WARN", "check": "compose_no_cap_drop",
            "issue": "no `cap_drop: [ALL]` — full capability set retained",
        })
    if not has_mem_limit:
        violations.append({
            "severity": "WARN", "check": "compose_no_limits",
            "issue": "no resource limits (mem_limit/cpus/limits) — DoS risk",
        })

    return violations


def _auto_detect_dockerfile(root: Path) -> Path | None:
    for candidate in [root / "Dockerfile",
                      root / "apps" / "api" / "Dockerfile",
                      root / "apps" / "web" / "Dockerfile"]:
        if candidate.exists():
            return candidate
    # Fall-back: glob
    for p in root.rglob("Dockerfile"):
        return p
    return None


def _auto_detect_compose(root: Path) -> Path | None:
    for candidate in [root / "docker-compose.yml",
                      root / "docker-compose.yaml",
                      root / "compose.yml", root / "compose.yaml"]:
        if candidate.exists():
            return candidate
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dockerfile", default=None,
                    help="explicit path to Dockerfile (default: auto-detect)")
    ap.add_argument("--compose", default=None,
                    help="explicit path to docker-compose (default: auto-detect)")
    ap.add_argument("--project-root", default=".")
    ap.add_argument("--require", action="store_true",
                    help="BLOCK when Dockerfile not found (instead of WARN)")
    # Orchestrator passes --phase to every validator. Container hardening
    # is project-wide (Dockerfile/compose are not phase-scoped); accept
    # the arg to avoid argparse crash.
    ap.add_argument("--phase", help="(orchestrator-injected; ignored — container scan is project-wide)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    root = Path(args.project_root).resolve()

    dockerfile = (Path(args.dockerfile).resolve() if args.dockerfile
                  else _auto_detect_dockerfile(root))
    compose = (Path(args.compose).resolve() if args.compose
               else _auto_detect_compose(root))

    all_violations: list[dict] = []

    if dockerfile is None or not dockerfile.exists():
        if args.require:
            all_violations.append({
                "severity": "BLOCK", "check": "dockerfile_missing",
                "issue": "no Dockerfile found (--require)",
            })
        else:
            if not args.quiet:
                print("\033[33m No Dockerfile found — skipping hardening check\033[0m",
                      file=sys.stderr)
            report = {
                "dockerfile": None, "compose": None,
                "violations": [], "block_count": 0, "warn_count": 0,
                "skipped": True,
            }
            if args.json:
                print(json.dumps(report, indent=2))
            return 0
    else:
        all_violations.extend([{**v, "source": str(dockerfile)}
                                for v in _check_dockerfile(dockerfile)])

    if compose and compose.exists():
        all_violations.extend([{**v, "source": str(compose)}
                                for v in _check_compose(compose)])

    blocks = [v for v in all_violations if v["severity"] == "BLOCK"]
    warns = [v for v in all_violations if v["severity"] == "WARN"]
    infos = [v for v in all_violations if v["severity"] == "INFO"]

    report = {
        "dockerfile": str(dockerfile) if dockerfile else None,
        "compose": str(compose) if compose else None,
        "violations": all_violations,
        "block_count": len(blocks),
        "warn_count": len(warns),
        "info_count": len(infos),
    }

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        if blocks:
            print(f"\033[38;5;208mContainer hardening: {len(blocks)} BLOCK, \033[0m"
                  f"{len(warns)} WARN\n")
            for v in all_violations:
                if v["severity"] in ("BLOCK", "WARN"):
                    print(f"  [{v['severity']}] {v['check']}: {v['issue']}")
        elif warns and not args.quiet:
            print(f"\033[33m Container hardening: {len(warns)} WARN (no blocks)\033[0m")
            for v in warns:
                print(f"  [WARN] {v['check']}: {v['issue']}")
        elif not args.quiet:
            print(
                f"✓ Container hardening OK — "
                f"{'Dockerfile' if dockerfile else 'no Dockerfile'} checked"
            )

    return 1 if blocks else 0


if __name__ == "__main__":
    sys.exit(main())
