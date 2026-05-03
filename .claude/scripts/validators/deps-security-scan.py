#!/usr/bin/env python3
"""
Validator: deps-security-scan.py

B8.1 (OHOK D1): detect known CVEs in dependencies before push. Blocks
pushes that introduce vulnerable packages at or above `severity_threshold`
(config.security_gates.cve_threshold).

Scope (MVP — iteration 1):
  - npm / pnpm audit for Node workspaces
  - pip-audit for Python projects (if installed)
  - Ecosystem auto-detected by lock-file presence

Deferred:
  - trivy / snyk / gh-advisory-database direct integration
  - SBOM generation
  - License audit (separate concern, separate validator)

Allowlist: .vg/cve-waivers.yml — entries with CVE id, reason, expiry.
Expired waivers re-activate the block.

Exits:
  0  PASS (no CVEs at/above threshold) or WARN (lower severity present)
  1  BLOCK (CVEs ≥ threshold without allowlist entry)

Usage:
  deps-security-scan.py [--threshold high]
  deps-security-scan.py --threshold moderate --timeout 60
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, timer, emit_and_exit  # noqa: E402
from _i18n import t  # noqa: E402

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
WAIVERS_PATH = REPO_ROOT / ".vg" / "cve-waivers.yml"

SEVERITY_ORDER = {
    "info": 0, "low": 1, "moderate": 2, "medium": 2,
    "high": 3, "critical": 4,
}


def _severity_ge(a: str, threshold: str) -> bool:
    return SEVERITY_ORDER.get(a.lower(), 0) >= SEVERITY_ORDER.get(
        threshold.lower(), 3)


def _detect_ecosystems() -> list[str]:
    """Return ecosystems active in repo based on lock-file presence."""
    eco: list[str] = []
    if (REPO_ROOT / "package.json").exists():
        if (REPO_ROOT / "pnpm-lock.yaml").exists():
            eco.append("pnpm")
        elif (REPO_ROOT / "yarn.lock").exists():
            eco.append("yarn")
        elif (REPO_ROOT / "package-lock.json").exists():
            eco.append("npm")
        else:
            eco.append("npm")  # best effort
    if ((REPO_ROOT / "requirements.txt").exists()
        or (REPO_ROOT / "pyproject.toml").exists()
            or (REPO_ROOT / "poetry.lock").exists()):
        eco.append("python")
    return eco


def _run_with_timeout(cmd: list[str], timeout: int) -> tuple[int, str, str]:
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            cwd=REPO_ROOT,
        )
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except FileNotFoundError:
        return 127, "", f"{cmd[0]}: not found"
    except Exception as e:
        return 1, "", str(e)


def _parse_npm_audit(json_text: str) -> list[dict]:
    """Parse `npm audit --json` / `pnpm audit --json` output into flat list
    of {id, severity, title, package, fix_available}."""
    try:
        data = json.loads(json_text)
    except (json.JSONDecodeError, ValueError):
        return []
    vulns: list[dict] = []

    # npm v7+ shape
    for pkg_name, info in (data.get("vulnerabilities") or {}).items():
        sev = info.get("severity", "unknown")
        via_list = info.get("via") or []
        for via in via_list:
            if isinstance(via, dict):
                vulns.append({
                    "id": str(via.get("source") or via.get("url") or ""),
                    "severity": sev,
                    "title": via.get("title", ""),
                    "package": pkg_name,
                    "fix_available": bool(info.get("fixAvailable")),
                })
            elif isinstance(via, str) and not any(
                v.get("package") == pkg_name and v.get("id") == via for v in vulns
            ):
                vulns.append({
                    "id": "",
                    "severity": sev,
                    "title": f"via {via}",
                    "package": pkg_name,
                    "fix_available": bool(info.get("fixAvailable")),
                })

    # pnpm audit shape
    for adv in data.get("advisories", {}).values() or []:
        if not isinstance(adv, dict):
            continue
        vulns.append({
            "id": str(adv.get("id", "")),
            "severity": adv.get("severity", "unknown"),
            "title": adv.get("title", ""),
            "package": adv.get("module_name", ""),
            "fix_available": bool(adv.get("patched_versions")),
        })

    return vulns


def _parse_pip_audit(json_text: str) -> list[dict]:
    """Parse `pip-audit --format json` output."""
    try:
        data = json.loads(json_text)
    except (json.JSONDecodeError, ValueError):
        return []
    vulns: list[dict] = []
    for dep in data.get("dependencies", []) or data:
        if not isinstance(dep, dict):
            continue
        name = dep.get("name", "")
        for v in dep.get("vulns", []):
            if not isinstance(v, dict):
                continue
            # pip-audit doesn't always emit severity — default to "high" so
            # it flags absent of signal. Most CVEs surface as high anyway.
            sev = v.get("severity") or "high"
            vulns.append({
                "id": str(v.get("id", "")),
                "severity": str(sev).lower(),
                "title": v.get("description", "")[:120],
                "package": name,
                "fix_available": bool(v.get("fix_versions")),
            })
    return vulns


def _load_waivers() -> list[dict]:
    if not WAIVERS_PATH.exists():
        return []
    try:
        import yaml  # type: ignore
    except ImportError:
        return []
    try:
        data = yaml.safe_load(
            WAIVERS_PATH.read_text(encoding="utf-8", errors="replace")
        ) or []
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    return [e for e in data if isinstance(e, dict) and "id" in e]


def _waiver_matches(vuln_id: str, package: str,
                    waivers: list[dict]) -> bool:
    now = datetime.now(timezone.utc)
    for entry in waivers:
        if entry.get("id") and str(entry["id"]) != vuln_id:
            continue
        if entry.get("package") and entry["package"] != package:
            continue
        exp = entry.get("expires")
        if exp:
            try:
                exp_dt = datetime.fromisoformat(
                    str(exp).replace("Z", "+00:00")
                )
                if exp_dt.tzinfo is None:
                    exp_dt = exp_dt.replace(tzinfo=timezone.utc)
                if now > exp_dt:
                    continue  # expired
            except Exception:
                continue
        return True
    return False


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--threshold", default="high",
                    choices=["low", "moderate", "high", "critical"])
    ap.add_argument("--timeout", type=int, default=60)
    ap.add_argument("--skip-npm", action="store_true")
    ap.add_argument("--skip-python", action="store_true")
    args = ap.parse_args()

    out = Output(validator="deps-security-scan")
    with timer(out):
        ecosystems = _detect_ecosystems()
        if not ecosystems:
            # Nothing to scan
            emit_and_exit(out)

        waivers = _load_waivers()
        all_vulns: list[dict] = []
        errors: list[str] = []

        if "pnpm" in ecosystems and not args.skip_npm:
            rc, stdout, stderr = _run_with_timeout(
                ["pnpm", "audit", "--json"], args.timeout,
            )
            if rc in (0, 1):  # pnpm exits 1 when vulns present
                all_vulns.extend(_parse_npm_audit(stdout))
            elif rc == 127:
                errors.append("pnpm: not installed")
            elif rc == 124:
                errors.append("pnpm audit: timeout")
        elif ("npm" in ecosystems or "yarn" in ecosystems) and not args.skip_npm:
            rc, stdout, stderr = _run_with_timeout(
                ["npm", "audit", "--json"], args.timeout,
            )
            if rc in (0, 1):
                all_vulns.extend(_parse_npm_audit(stdout))
            elif rc == 127:
                errors.append("npm: not installed")
            elif rc == 124:
                errors.append("npm audit: timeout")

        if "python" in ecosystems and not args.skip_python:
            rc, stdout, stderr = _run_with_timeout(
                ["pip-audit", "--format", "json"], args.timeout,
            )
            if rc in (0, 1):
                all_vulns.extend(_parse_pip_audit(stdout))
            elif rc == 127:
                # pip-audit optional — no error, just skip
                pass
            elif rc == 124:
                errors.append("pip-audit: timeout")

        # Filter by threshold and waivers
        blocking: list[dict] = []
        below: list[dict] = []
        waived: list[dict] = []
        for v in all_vulns:
            if _waiver_matches(v.get("id", ""), v.get("package", ""), waivers):
                waived.append(v)
                continue
            if _severity_ge(v.get("severity", "unknown"), args.threshold):
                blocking.append(v)
            else:
                below.append(v)

        if errors:
            for err in errors:
                out.warn(Evidence(
                    type="scanner_error",
                    message=t("deps_security.scanner_error.message",
                              details=err),
                    fix_hint=t("deps_security.scanner_error.fix_hint"),
                ))

        if blocking:
            # Emit block evidence
            sample = blocking[:10]
            actual = "; ".join(
                f"{v.get('package','?')} [{v.get('severity','?')}] "
                f"{v.get('id','')} — {v.get('title','')[:60]}"
                for v in sample
            )
            out.add(Evidence(
                type="cve_blocking",
                message=t(
                    "deps_security.cve_blocking.message",
                    count=len(blocking), threshold=args.threshold,
                ),
                actual=actual,
                fix_hint=t("deps_security.cve_blocking.fix_hint"),
            ))

        if below:
            out.warn(Evidence(
                type="cve_below_threshold",
                message=t(
                    "deps_security.cve_below_threshold.message",
                    count=len(below), threshold=args.threshold,
                ),
            ))

        if waived and not blocking:
            out.warn(Evidence(
                type="cve_waived",
                message=t(
                    "deps_security.cve_waived.message",
                    count=len(waived),
                ),
                fix_hint=t("deps_security.cve_waived.fix_hint"),
            ))

    emit_and_exit(out)


if __name__ == "__main__":
    main()
