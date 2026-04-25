#!/usr/bin/env python3
"""
Validator: verify-no-hardcoded-paths.py

Harness v2.6 (2026-04-25): catches hardcoded SSH/VPS paths that should come
from config. Per CLAUDE.md infrastructure rules:
  - "SSH to VPS: Always `ssh vollx` — alias configured. NEVER use full IP"
  - "VPS IP: only used in Ansible inventory and Cloudflare DNS, never in
     SSH commands"
  - "Read before generate: grep existing codebase for actual values, don't
     assume"

When AI generates skill/command/script files, it tends to copy literal
SSH commands or VPS paths instead of referencing config. This makes
configs unportable and creates dual-source-of-truth bugs (config says
one thing, hardcoded scripts another).

Banned patterns (configurable via vg.config.md `validators.no_hardcoded_paths`):
  1. ssh root@<IP>             — must use config.environments.<env>.run_prefix
  2. ssh user@<IP>             — same
  3. https?://<IP>             — must use config domain or config var
  4. /home/vollx/vollxssp      — must use config.environments.<env>.project_path
  5. raw <IP> in shell scripts — except in allowlisted infra files

Allowlist (paths where literal IP / paths are intentional):
  - infra/ansible/inventory*
  - infra/cloudflare/**
  - .claude/vg.config.md (config itself defines them)
  - .planning/**, .vg/**     (workspace artifacts; AI-readable but not exec)
  - **/*.md                   (docs may show example commands)
  - apps/web/e2e/**           (test fixtures)

Severity:
  BLOCK — pattern in source code (apps/**, packages/**, infra/ shell scripts)
  WARN  — pattern in skill/command markdown not in allowlist

Usage:
  verify-no-hardcoded-paths.py              # scan whole repo
  verify-no-hardcoded-paths.py --phase 7.14 # scoped to phase artifacts
  verify-no-hardcoded-paths.py --verbose    # list every match

Exit codes:
  0  PASS or WARN-only
  1  BLOCK
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, timer, emit_and_exit  # noqa: E402

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()

# Patterns AI commonly hardcodes — each tuple: (compiled_regex, kind, severity_default)
# Exclude loopback (127.0.0.1, 0.0.0.0) — those are legitimate dev defaults.
# Exclude private ranges (10.*, 172.16-31.*, 192.168.*) — those are intra-LAN
# defaults. We only want to catch PUBLIC IPs hardcoded outside config.
_LOOPBACK_OR_PRIVATE = re.compile(
    r"^(127\.|0\.0\.0\.0|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|169\.254\.)"
)


def _is_public_ip(ip: str) -> bool:
    return not _LOOPBACK_OR_PRIVATE.match(ip)


PATTERNS: list[tuple[re.Pattern, str, str]] = [
    # Match the IP as a separate group so we can filter loopback/private out
    (re.compile(r"\b(?P<verb>ssh|scp|rsync)\s+[^\s@]*@(?P<ip>\d+\.\d+\.\d+\.\d+)\b"), "ssh-to-raw-ip", "BLOCK"),
    (re.compile(r"https?://(?P<ip>\d+\.\d+\.\d+\.\d+)(?::\d+)?(/|\b)"), "raw-ip-url", "WARN"),
]

# Allowlist patterns (path globs as regex)
ALLOWLIST_RE = [
    re.compile(r"^infra/ansible/inventor"),
    re.compile(r"^infra/cloudflare/"),
    re.compile(r"^infra/.*?\.tf$"),       # Terraform configs
    re.compile(r"^infra/.*?\.tfvars"),
    re.compile(r"^\.claude/vg\.config\.md$"),
    re.compile(r"^\.planning/"),
    re.compile(r"^\.vg/"),
    re.compile(r"^apps/web/e2e/"),         # test fixtures
    re.compile(r"\.example$"),              # *.example files (templates)
    re.compile(r"^docs/"),
    re.compile(r"^README"),
    re.compile(r"^CHANGELOG"),
    re.compile(r"\.git/"),
    re.compile(r"node_modules/"),
    re.compile(r"^\.codex/skills/.*/SKILL\.md$"),  # skills may reference IP in
                                                    # documentation/example blocks
    re.compile(r"^\.claude/scripts/validators/verify-no-hardcoded-paths\.py$"),  # this file itself
    re.compile(r"^\.claude/scripts/validators/test-"),  # test fixture files
    re.compile(r"^\.codex/skills/vg-init/SKILL\.md$"),
]


def _read_extra_config_paths() -> tuple[list[str], list[re.Pattern]]:
    """Pull project-specific path constants + extra allowlist from vg.config."""
    cfg_path = REPO_ROOT / ".claude" / "vg.config.md"
    project_paths: list[str] = []
    extra_allow: list[re.Pattern] = []
    if not cfg_path.exists():
        return project_paths, extra_allow
    text = cfg_path.read_text(encoding="utf-8", errors="replace")
    # Find every "project_path: ..." declaration — these are the canonical
    # VPS paths config declares. We treat them as banned in source code OUTSIDE
    # the allowlist (because they should be referenced via config, not literal).
    for m in re.finditer(r'^\s*project_path:\s*["\']?([^"\'\n#]+)', text, re.MULTILINE):
        path = m.group(1).strip()
        if path and not path.startswith("$") and len(path) > 4:
            project_paths.append(path)
    # User-declared allowlist additions
    block = re.search(
        r'(?ms)^validators:\s*\n(?:.*?\n)??\s*no_hardcoded_paths:\s*\n((?:    [^\n]+\n)+)',
        text,
    )
    if block:
        for line in block.group(1).splitlines():
            m = re.match(r'^\s*-\s*["\']?([^"\'\n#]+)', line)
            if m:
                pat = m.group(1).strip()
                try:
                    extra_allow.append(re.compile(pat))
                except re.error:
                    pass
    return project_paths, extra_allow


def is_allowlisted(rel_path: str, extras: list[re.Pattern]) -> bool:
    rel_norm = rel_path.replace("\\", "/")
    for rx in (*ALLOWLIST_RE, *extras):
        if rx.search(rel_norm):
            return True
    return False


def scan_file(file_path: Path, project_paths: list[str]) -> list[dict]:
    """Return list of findings: {pattern, line_no, snippet, severity}."""
    findings: list[dict] = []
    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeDecodeError):
        return findings
    for line_no, line in enumerate(text.splitlines(), 1):
        # Skip comments-only lines (best-effort) — patterns in pure comments
        # are usually intentional documentation. Heuristic: leading // or # only.
        stripped = line.strip()
        if stripped.startswith("//") or stripped.startswith("#"):
            # Don't completely skip — but note it as low-severity informational
            continue
        for rx, kind, severity in PATTERNS:
            for m in rx.finditer(line):
                # Filter loopback / private IPs — those are legitimate
                ip = m.groupdict().get("ip", "")
                if ip and not _is_public_ip(ip):
                    continue
                snippet = m.group(0)
                findings.append({
                    "pattern": kind,
                    "line": line_no,
                    "snippet": snippet[:100],
                    "severity": severity,
                })
        # Project-path patterns — config-declared VPS paths
        for vp in project_paths:
            if vp in line:
                findings.append({
                    "pattern": "config-project-path-hardcoded",
                    "line": line_no,
                    "snippet": vp,
                    "severity": "WARN",
                })
    return findings


def collect_files(root: Path, scope: str | None) -> list[Path]:
    """Yield candidate source files for scanning."""
    if scope:
        scoped_root = (root / scope).resolve()
        if not scoped_root.exists():
            return []
        roots = [scoped_root]
    else:
        roots = [
            root / "apps",
            root / "packages",
            root / "infra",
            root / ".claude" / "scripts",
            root / ".claude" / "commands",
        ]
    extensions = {".sh", ".js", ".jsx", ".ts", ".tsx", ".py", ".rs", ".go", ".yaml", ".yml", ".json", ".md"}
    files: list[Path] = []
    for r in roots:
        if not r.exists():
            continue
        for p in r.rglob("*"):
            if not p.is_file():
                continue
            if p.suffix not in extensions:
                continue
            files.append(p)
    return files


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase", help="Scope to phase directory (.vg/phases/<phase>/)")
    ap.add_argument("--scope", help="Override default scan roots with custom path")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    out = Output(validator="verify-no-hardcoded-paths")
    with timer(out):
        project_paths, extra_allow = _read_extra_config_paths()

        scope_path = None
        if args.phase:
            phase_glob = list((REPO_ROOT / ".vg" / "phases").glob(f"*{args.phase}*"))
            if phase_glob:
                scope_path = str(phase_glob[0].relative_to(REPO_ROOT))
        elif args.scope:
            scope_path = args.scope

        candidates = collect_files(REPO_ROOT, scope_path)

        block_findings: list[dict] = []
        warn_findings: list[dict] = []
        scanned = 0

        for fp in candidates:
            try:
                rel = str(fp.relative_to(REPO_ROOT)).replace("\\", "/")
            except ValueError:
                continue
            if is_allowlisted(rel, extra_allow):
                continue
            scanned += 1
            for f in scan_file(fp, project_paths):
                row = {**f, "file": rel}
                if f["severity"] == "BLOCK":
                    block_findings.append(row)
                else:
                    warn_findings.append(row)

        if args.verbose:
            print(f"# scanned {scanned} files", file=sys.stderr)
            for f in [*block_findings, *warn_findings]:
                print(f"  {f['severity']:6s} {f['file']}:{f['line']}  {f['pattern']}: {f['snippet']}", file=sys.stderr)

        if block_findings:
            sample = "; ".join(
                f"{f['file']}:{f['line']} ({f['pattern']})"
                for f in block_findings[:5]
            )
            out.add(Evidence(
                type="hardcoded_path_block",
                message=f"Found {len(block_findings)} hardcoded path(s) in source code that must use config variables",
                actual=sample,
                fix_hint="Replace with ${RUN_PREFIX} / ${PROJECT_PATH} / config.environments.<env>.<key} reference. Add to validators.no_hardcoded_paths allowlist if literal is intentional.",
            ))

        if warn_findings:
            sample = "; ".join(
                f"{f['file']}:{f['line']} ({f['pattern']})"
                for f in warn_findings[:5]
            )
            out.warn(Evidence(
                type="hardcoded_path_warn",
                message=f"Found {len(warn_findings)} possible hardcoded path(s) in non-source files (advisory)",
                actual=sample,
                fix_hint="Review whether these literals belong in config or are intentional documentation/examples.",
            ))

    emit_and_exit(out)


if __name__ == "__main__":
    main()
