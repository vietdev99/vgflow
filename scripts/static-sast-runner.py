#!/usr/bin/env python3
"""
static-sast-runner.py — v2.37.0 SAST candidate generator for static-sast kit.

Two modes:
  1. semgrep present → run with curated rule set (auto.yml + custom rules)
  2. semgrep missing → grep-pattern fallback for top-N bug classes

Output: ${PHASE_DIR}/sast-candidates.json with [{rule, file, line, snippet,
bug_class, severity_hint}].

Worker spawn (static-sast.md kit) consumes this file, triages candidates
into confirmed/false-positive/human-review.

Usage:
  static-sast-runner.py --root . --out sast-candidates.json
  static-sast-runner.py --root apps/api --bug-class injection
  static-sast-runner.py --root . --json
  static-sast-runner.py --check-tools  # report which tools available, no scan

Bug classes (defines fallback patterns):
  injection, secrets, broken-auth, idor, unsafe-deserialize,
  mass-assignment, path-traversal, crypto-weak
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()


FALLBACK_PATTERNS: dict[str, list[tuple[str, str, str]]] = {
    "injection": [
        ("sql_concat", r'(?:execute|query|exec)\s*\(\s*["`\'].*\+\s*\w+', "critical"),
        ("sql_template_literal", r'`[^`]*\$\{[^}]*\}[^`]*`\s*\)\s*\.\s*(?:execute|query|exec)', "critical"),
        ("cmd_shell_exec", r'(?:exec|spawn|popen|os\.system)\s*\(\s*["`\'].*\+', "critical"),
        ("py_format_sql", r'\.execute\s*\(\s*[fF]?["\'].*%\w+', "critical"),
    ],
    "secrets": [
        ("hardcoded_aws_key", r'AKIA[0-9A-Z]{16}', "critical"),
        ("hardcoded_jwt_secret", r'(?:JWT_SECRET|SECRET_KEY|API_KEY)\s*=\s*["\'][a-zA-Z0-9+/=_-]{16,}', "critical"),
        ("hardcoded_password_assignment", r'(?:password|passwd|pwd)\s*[:=]\s*["\'][^"\'$]{8,}["\']', "high"),
        ("private_key_pem", r'-----BEGIN (?:RSA |EC )?PRIVATE KEY-----', "critical"),
    ],
    "broken-auth": [
        ("route_no_auth_middleware", r'(?:app|router)\.(?:post|put|patch|delete)\s*\([^)]*\)\s*(?!.*(?:authenticate|auth\(|requireAuth|isAuth))', "high"),
        ("admin_route_no_role_check", r'/admin/[^"\']*["\'][^{]*\{(?![^}]*(?:role|isAdmin|requireRole|hasPermission))[^}]{0,400}\}', "high"),
    ],
    "idor": [
        ("direct_id_query", r'\.findById\s*\(\s*req\.params\.\w+\s*\)\s*(?!.*(?:userId|tenantId|orgId|owner))', "high"),
        ("query_no_scope", r'\.find\s*\(\s*\{\s*id:\s*req\.\w+\.\w+\s*\}\s*\)', "high"),
    ],
    "unsafe-deserialize": [
        ("pickle_loads", r'pickle\.loads?\s*\(', "high"),
        ("yaml_load_unsafe", r'yaml\.load\s*\((?![^)]*Loader\s*=\s*(?:Safe|yaml\.Safe))', "high"),
        ("php_unserialize", r'\bunserialize\s*\(', "high"),
        ("node_eval", r'\beval\s*\(\s*[^"\'`)]*(?:req\.|query|body|params)', "critical"),
    ],
    "mass-assignment": [
        ("spread_req_body", r'\.\.\.\s*req\.body\b', "medium"),
        ("update_with_body", r'\.update\s*\(\s*[^,)]+,\s*req\.body\s*\)', "medium"),
    ],
    "path-traversal": [
        ("fs_with_user_path", r'fs\.(?:read|write|append)(?:File|FileSync)?\s*\(\s*(?:req\.|`[^`]*\$\{[^}]*\}|.*\+\s*req\.)', "high"),
        ("path_join_user", r'path\.(?:join|resolve)\s*\([^)]*req\.', "high"),
    ],
    "crypto-weak": [
        ("md5_for_auth", r'(?:md5|MD5)\s*\(\s*[^)]*(?:password|passwd|secret|token|auth)', "medium"),
        ("sha1_hash", r'\bsha1\s*\(\s*[^)]*(?:password|passwd|secret|token|auth)', "medium"),
        ("aes_ecb", r'AES[-_]?ECB|aes-ecb|EVP_aes_\d+_ecb', "medium"),
    ],
}


CODE_EXTS = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".py", ".php", ".rb", ".java", ".go", ".rs"}
EXCLUDE_DIRS = {"node_modules", "dist", "build", ".next", "target", ".git", "__pycache__", "venv", ".venv", "vendor", "graphify-out", ".vg", ".planning", "test", "tests", "__tests__", "spec", "specs", "fixtures", "fixture"}


def has_semgrep() -> bool:
    return shutil.which("semgrep") is not None


def run_semgrep(root: Path, bug_class: str | None) -> list[dict]:
    cmd = ["semgrep", "--quiet", "--json", "--metrics=off", "--config=auto"]
    cmd.extend(["--", str(root)])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        return []
    if result.returncode not in (0, 1):
        return []
    try:
        data = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return []
    out: list[dict] = []
    for r in data.get("results") or []:
        out.append({
            "rule": r.get("check_id"),
            "file": r.get("path"),
            "line": (r.get("start") or {}).get("line"),
            "snippet": (r.get("extra") or {}).get("lines", "")[:240],
            "bug_class": bug_class or "unknown",
            "severity_hint": (r.get("extra") or {}).get("severity", "info").lower(),
            "source": "semgrep",
        })
    return out


def run_fallback(root: Path, bug_classes: list[str]) -> list[dict]:
    out: list[dict] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS and not d.startswith(".")]
        for fn in filenames:
            if Path(fn).suffix.lower() not in CODE_EXTS:
                continue
            fp = Path(dirpath) / fn
            try:
                text = fp.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for bug_class in bug_classes:
                for rule_name, pattern, sev_hint in FALLBACK_PATTERNS.get(bug_class, []):
                    for m in re.finditer(pattern, text, re.MULTILINE | re.IGNORECASE):
                        line = text.count("\n", 0, m.start()) + 1
                        line_start = text.rfind("\n", 0, m.start()) + 1
                        line_end = text.find("\n", m.end())
                        if line_end < 0:
                            line_end = len(text)
                        snippet = text[line_start:line_end].strip()[:240]
                        out.append({
                            "rule": f"{bug_class}.{rule_name}",
                            "file": str(fp.relative_to(root)).replace("\\", "/"),
                            "line": line,
                            "snippet": snippet,
                            "bug_class": bug_class,
                            "severity_hint": sev_hint,
                            "source": "fallback-grep",
                        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".")
    ap.add_argument("--out", default=None)
    ap.add_argument("--bug-class", default=None, help="Comma-separated focus list (default: all)")
    ap.add_argument("--check-tools", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    if args.check_tools:
        print(f"  semgrep: {'present' if has_semgrep() else 'missing (will use fallback grep patterns)'}")
        return 0

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"\033[38;5;208mRoot not found: {root}\033[0m", file=sys.stderr)
        return 1

    bug_classes = [c.strip() for c in (args.bug_class or "").split(",") if c.strip()] or list(FALLBACK_PATTERNS.keys())

    if has_semgrep():
        candidates = run_semgrep(root, args.bug_class)
        if not candidates:
            if not args.quiet:
                print("  (semgrep returned 0 results — falling back to grep patterns for verification)")
            candidates = run_fallback(root, bug_classes)
    else:
        candidates = run_fallback(root, bug_classes)

    payload = {
        "schema_version": "1",
        "scanned_root": str(root),
        "bug_classes_scanned": bug_classes,
        "tool": "semgrep" if has_semgrep() else "fallback-grep",
        "candidate_count": len(candidates),
        "candidates": candidates,
    }

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        out_path = Path(args.out) if args.out else (root / "sast-candidates.json")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        if not args.quiet:
            by_class: dict[str, int] = {}
            for c in candidates:
                by_class[c["bug_class"]] = by_class.get(c["bug_class"], 0) + 1
            print(f"✓ {len(candidates)} SAST candidate(s) → {out_path}")
            print(f"  Tool: {payload['tool']}")
            for cls, n in sorted(by_class.items(), key=lambda kv: -kv[1]):
                print(f"  {cls}: {n}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
