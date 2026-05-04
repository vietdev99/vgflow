#!/usr/bin/env python3
"""
verify-flow-compliance.py — v2.38.0 end-of-flow auditor.

Verifies that AI executed all required steps for the phase profile,
based on evidence file presence (more robust than step markers, which
have inconsistent naming across commands).

Reads:
  - FLOW-COMPLIANCE.yaml (template) for profile × command × evidence matrix
  - vg.config.md for project override (`flow_compliance:` block)
  - Phase profile from SPECS.md frontmatter or vg.config phase_profiles default
  - .vg/phases/{N}/ for evidence files

Writes:
  - .vg/phases/{N}/.flow-compliance-{command}.yaml — per-command audit report

Exit codes:
  0 — COMPLIANT (or severity=warn AND non-compliant)
  1 — NON-COMPLIANT (severity=block) without --skip-compliance
  2 — config / IO error

Usage:
  verify-flow-compliance.py --phase-dir <path> --command review
  verify-flow-compliance.py --phase-dir <path> --command build --profile feature
  verify-flow-compliance.py --phase-dir <path> --command accept   # aggregates prior 4 flows
  verify-flow-compliance.py --phase-dir <path> --command review --skip-compliance="<reason>"
  verify-flow-compliance.py --phase-dir <path> --command review --json
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sys
from glob import glob
from pathlib import Path

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()


def load_yaml(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        import yaml
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except ImportError:
        return {}
    except Exception:
        return {}


def load_compliance_template() -> dict:
    candidates = [
        REPO_ROOT / ".claude" / "commands" / "vg" / "_shared" / "templates" / "FLOW-COMPLIANCE.yaml",
        REPO_ROOT / "commands" / "vg" / "_shared" / "templates" / "FLOW-COMPLIANCE.yaml",
    ]
    for p in candidates:
        data = load_yaml(p)
        if data:
            return (data.get("flow_compliance") or {})
    return {}


def detect_profile(phase_dir: Path) -> str:
    specs_path = phase_dir / "SPECS.md"
    if specs_path.is_file():
        text = specs_path.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"^phase_profile:\s*([a-zA-Z0-9_-]+)", text, re.M)
        if m:
            return m.group(1).strip()

    cfg_path = REPO_ROOT / ".claude" / "vg.config.md"
    if cfg_path.is_file():
        text = cfg_path.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"^\s*default_profile:\s*[\"']?([a-zA-Z0-9_-]+)", text, re.M)
        if m:
            return m.group(1)

    return "feature"


def resolve_evidence_paths(phase_dir: Path, patterns: list[str]) -> list[tuple[str, list[Path]]]:
    out: list[tuple[str, list[Path]]] = []
    for pat in patterns:
        if any(ch in pat for ch in "*?["):
            matches = [Path(p) for p in glob(str(phase_dir / pat))]
        else:
            p = phase_dir / pat
            matches = [p] if p.exists() else []
        out.append((pat, matches))
    return out


def audit_command(phase_dir: Path, command: str, profile: str,
                  template: dict) -> dict:
    cmd_block = template.get(command) or {}
    profile_block = cmd_block.get(profile)
    if not profile_block:
        profile_block = cmd_block.get("all_profiles") or cmd_block.get("feature") or {}

    required = profile_block.get("evidence_required") or []
    optional = profile_block.get("evidence_optional") or []

    required_results = resolve_evidence_paths(phase_dir, required)
    optional_results = resolve_evidence_paths(phase_dir, optional)

    missing_required = [(pat, []) for pat, paths in required_results if not paths]
    found_required = [(pat, [str(p.relative_to(phase_dir).as_posix()) for p in paths]) for pat, paths in required_results if paths]
    found_optional = [(pat, [str(p.relative_to(phase_dir).as_posix()) for p in paths]) for pat, paths in optional_results if paths]

    verdict = "COMPLIANT" if not missing_required else "NON-COMPLIANT"

    return {
        "command": command,
        "phase_profile": profile,
        "checked_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "evidence_required_patterns": required,
        "evidence_optional_patterns": optional,
        "found_required": [{"pattern": pat, "files": files} for pat, files in found_required],
        "found_optional": [{"pattern": pat, "files": files} for pat, files in found_optional],
        "missing_required": [pat for pat, _ in missing_required],
        "verdict": verdict,
    }


def aggregate_from_prior_audits(phase_dir: Path) -> list[dict]:
    audits: list[dict] = []
    for cmd in ("blueprint", "build", "review", "test"):
        audit_path = phase_dir / f".flow-compliance-{cmd}.yaml"
        if audit_path.is_file():
            data = load_yaml(audit_path)
            if data:
                audits.append(data)
    return audits


def write_audit_yaml(phase_dir: Path, command: str, audit: dict, override_reason: str | None) -> Path:
    audit["override_reason"] = override_reason
    audit["override_active"] = bool(override_reason)
    if override_reason and audit["verdict"] == "NON-COMPLIANT":
        audit["effective_verdict"] = "OVERRIDE-LOGGED"
    else:
        audit["effective_verdict"] = audit["verdict"]

    out_path = phase_dir / f".flow-compliance-{command}.yaml"
    try:
        import yaml
        body = yaml.safe_dump(audit, default_flow_style=False, sort_keys=False)
    except ImportError:
        body = json.dumps(audit, indent=2)
    tmp = out_path.with_suffix(".yaml.tmp")
    tmp.write_text(body, encoding="utf-8")
    tmp.replace(out_path)
    return out_path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase-dir", required=True)
    ap.add_argument("--command", required=True, choices=["blueprint", "build", "review", "test", "accept"])
    ap.add_argument("--profile", default=None, help="Override detected profile")
    ap.add_argument("--severity", choices=["warn", "block"], default="block")
    ap.add_argument("--skip-compliance", default=None, help="Override reason — logged as OVERRIDE-DEBT, exit 0")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    phase_dir = Path(args.phase_dir).resolve()
    if not phase_dir.is_dir():
        print(f"\033[38;5;208mPhase dir not found: {phase_dir}\033[0m", file=sys.stderr)
        return 2

    template = load_compliance_template()
    if not template:
        print("\033[38;5;208mFLOW-COMPLIANCE.yaml template not found\033[0m", file=sys.stderr)
        return 2

    profile = args.profile or detect_profile(phase_dir)

    if args.command == "accept":
        prior_audits = aggregate_from_prior_audits(phase_dir)
        per_command = []
        for a in prior_audits:
            per_command.append({
                "command": a.get("command"),
                "verdict": a.get("verdict"),
                "effective_verdict": a.get("effective_verdict"),
                "missing_required": a.get("missing_required") or [],
                "override_active": a.get("override_active", False),
            })

        accept_audit = audit_command(phase_dir, "accept", profile, template)

        non_compliant = [c for c in per_command if c["effective_verdict"] not in ("COMPLIANT", "OVERRIDE-LOGGED")]

        accept_audit["aggregated_prior_flows"] = per_command
        accept_audit["prior_flows_non_compliant"] = [c["command"] for c in non_compliant]

        if non_compliant:
            accept_audit["verdict"] = "NON-COMPLIANT"

        write_audit_yaml(phase_dir, "accept", accept_audit, args.skip_compliance)

        if args.json:
            print(json.dumps(accept_audit, indent=2))
        elif not args.quiet:
            if accept_audit["verdict"] == "COMPLIANT":
                print(f"✓ Flow compliance OK across all flows (profile={profile})")
            else:
                print(f"\033[38;5;208mFlow compliance FAILED:\033[0m")
                for c in non_compliant:
                    print(f"   {c['command']}: missing {', '.join(c['missing_required']) or '(see report)'}")
                print(f"   accept itself: {', '.join(accept_audit['missing_required']) or 'OK'}")

        if accept_audit["verdict"] != "COMPLIANT" and not args.skip_compliance and args.severity == "block":
            return 1
        return 0

    audit = audit_command(phase_dir, args.command, profile, template)
    audit_path = write_audit_yaml(phase_dir, args.command, audit, args.skip_compliance)

    if args.json:
        print(json.dumps(audit, indent=2))
    elif not args.quiet:
        if audit["verdict"] == "COMPLIANT":
            print(f"✓ Flow compliance: {args.command} (profile={profile}) — all required evidence present")
        elif args.skip_compliance:
            print(f"\033[33mFlow compliance: {args.command} non-compliant but override active\033[0m")
            print(f"   Missing: {', '.join(audit['missing_required'])}")
            print(f"   Reason: {args.skip_compliance}")
        else:
            tag = "" if args.severity == "block" else ""
            print(f"{tag} Flow compliance: {args.command} NON-COMPLIANT (profile={profile})")
            print(f"   Missing required evidence: {', '.join(audit['missing_required'])}")
            print(f"   Override: --skip-compliance=\"<reason>\" logs OVERRIDE-DEBT")
            print(f"   Report: {audit_path}")

    if audit["verdict"] != "COMPLIANT" and not args.skip_compliance and args.severity == "block":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
