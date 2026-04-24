#!/usr/bin/env python3
"""
verify-log-hygiene.py — Phase M Batch 2 of v2.5.2 hardening.

Problem closed:
  Logging Authorization headers, request bodies, passwords, or raw
  emails into app logs is a classic accidental-leak source. AI-written
  handler code frequently emits `logger.info(req)` or
  `console.log(req.body)` on debug/trace paths and the leak survives
  into production. Sanitization middleware (pino-redact, winston mask,
  loguru sanitizer) is the standard mitigation but often absent.

Two modes:

SAST (default):
  Scan source files for logging calls that pass sensitive fields.
  Flag:
    - logger.*/console.log/log.info called with objects containing
      Authorization, req.body (on mutation routes), password, token,
      secret, api_key, raw email
    - Detect sanitization middleware presence; if absent → warn that
      a leak is likely

Runtime (--log-file <path>):
  Scan the log file for raw sensitive values:
    - Authorization: Bearer <20+ non-whitespace non-asterisk chars>
    - Email address patterns not redacted (no `*` in local part)
    - "password":"value" / "token":"value" / "secret":"value"
      with non-redacted values

--mode both → run both checks if both --project-root and --log-file
             are given.

Exit codes:
  0 = hygiene OK (no leaks found, or warns only)
  1 = BLOCK (raw sensitive logged)
  2 = config error

Usage:
  verify-log-hygiene.py --project-root .
  verify-log-hygiene.py --project-root . --log-file /var/log/app.log
  verify-log-hygiene.py --log-file /var/log/app.log --mode runtime
  verify-log-hygiene.py --project-root . --json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


# --- SAST patterns -----------------------------------------------------

LOGGER_CALL_RE = re.compile(
    r"""(?:
        logger\.(?:info|debug|warn|error|trace|log)
        |console\.(?:log|info|debug|warn|error)
        |log\.(?:info|debug|warn|error)
        |fastify\.log\.(?:info|debug|warn|error)
        |req\.log\.(?:info|debug|warn|error)
        |print
        |println!
        |slog\.(?:Info|Debug|Error|Warn)
    )\s*\((.*?)\)""",
    re.VERBOSE | re.DOTALL,
)

SENSITIVE_ARG_PATTERNS = [
    (r"\bauthorization\b", "Authorization header"),
    (r"\breq\.body\b", "req.body (may contain password/pii)"),
    (r"\bpassword\b", "password field"),
    (r"\bpasswd\b", "password field"),
    (r"\btoken\b", "token field"),
    (r"\bsecret\b", "secret field"),
    (r"\bapi[_\s-]?key\b", "api_key field"),
    (r"\baccess[_\s-]?key\b", "access_key field"),
    (r"\bprivate[_\s-]?key\b", "private_key field"),
    (r"\bssn\b", "ssn field"),
    (r"\bcredit[_\s-]?card\b", "credit_card field"),
]

SANITIZER_PATTERNS = [
    r"pino-?redact",
    r"pino\s*\(\s*\{[^}]*redact",
    r"winston.*mask",
    r"winston.*format.*redact",
    r"loguru.*sanitize",
    r"\bsanitize[_\s-]?log[_\s-]?data\b",
    r"@fastify/redact",
    r"\bsanitize[_\s-]?headers\b",
    r"\bscrub[_\s-]?sensitive\b",
    r"\bmask[_\s-]?fields\b",
    r"SENSITIVE_FIELDS",
    r"REDACTED_FIELDS",
]

# --- Runtime patterns --------------------------------------------------

RAW_BEARER_RE = re.compile(
    r"""Authorization\s*:\s*Bearer\s+([^\s*]{20,})""",
    re.IGNORECASE,
)
# match a raw JWT-like token (3 segments separated by .)
JWT_IN_LOG_RE = re.compile(
    r"""eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+"""
)

RAW_EMAIL_RE = re.compile(
    r"""\b([a-z0-9][a-z0-9._+\-]*)@([a-z0-9\-]+\.[a-z]{2,6})\b""",
    re.IGNORECASE,
)

RAW_PASSWORD_JSON_RE = re.compile(
    r'"password"\s*:\s*"([^"*]{3,})"',
    re.IGNORECASE,
)
RAW_TOKEN_JSON_RE = re.compile(
    r'"token"\s*:\s*"([^"*]{8,})"',
    re.IGNORECASE,
)
RAW_SECRET_JSON_RE = re.compile(
    r'"secret"\s*:\s*"([^"*]{4,})"',
    re.IGNORECASE,
)

CODE_EXTS = (".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs", ".py",
             ".go", ".java", ".rs")


def _iter_code_files(root: Path):
    skip = {"node_modules", "dist", "build", ".git", ".vg",
            "__pycache__", ".next", "target", "vendor"}
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if any(part in skip for part in p.parts):
            continue
        if p.suffix.lower() in CODE_EXTS:
            yield p


def _scan_sast(root: Path) -> dict:
    findings = {
        "leaky_calls": [],      # list of (file, line, matched, field_type)
        "has_sanitizer": False,
        "sanitizer_refs": [],
        "files_scanned": 0,
    }
    sanitizer_re = re.compile("|".join(SANITIZER_PATTERNS), re.IGNORECASE)

    for f in _iter_code_files(root):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        findings["files_scanned"] += 1

        if sanitizer_re.search(text):
            findings["has_sanitizer"] = True
            findings["sanitizer_refs"].append(str(f))

        for m in LOGGER_CALL_RE.finditer(text):
            call_args = m.group(1)
            # Line number
            line_no = text[:m.start()].count("\n") + 1
            for pattern, label in SENSITIVE_ARG_PATTERNS:
                if re.search(pattern, call_args, re.IGNORECASE):
                    findings["leaky_calls"].append({
                        "file": str(f),
                        "line": line_no,
                        "snippet": call_args.strip()[:140],
                        "field": label,
                    })
                    break  # one violation per call is enough
    return findings


def _scan_runtime(log_file: Path) -> dict:
    findings = {
        "bearer_hits": [],
        "jwt_hits": [],
        "email_hits": [],
        "password_hits": [],
        "token_hits": [],
        "secret_hits": [],
        "lines_scanned": 0,
    }
    if not log_file.exists():
        return findings

    with log_file.open("r", encoding="utf-8", errors="replace") as fh:
        for lineno, line in enumerate(fh, start=1):
            findings["lines_scanned"] += 1
            if RAW_BEARER_RE.search(line):
                findings["bearer_hits"].append(
                    {"line": lineno, "snippet": line.strip()[:200]}
                )
            for m in JWT_IN_LOG_RE.finditer(line):
                findings["jwt_hits"].append(
                    {"line": lineno, "token_prefix": m.group(0)[:30]}
                )
            for m in RAW_EMAIL_RE.finditer(line):
                local = m.group(1)
                # treat as raw if local part doesn't contain '*' (i.e. not masked)
                if "*" not in local and len(local) > 1:
                    findings["email_hits"].append({
                        "line": lineno,
                        "email": m.group(0),
                    })
            for m in RAW_PASSWORD_JSON_RE.finditer(line):
                findings["password_hits"].append({
                    "line": lineno,
                    "value_len": len(m.group(1)),
                })
            for m in RAW_TOKEN_JSON_RE.finditer(line):
                findings["token_hits"].append({
                    "line": lineno,
                    "value_len": len(m.group(1)),
                })
            for m in RAW_SECRET_JSON_RE.finditer(line):
                findings["secret_hits"].append({
                    "line": lineno,
                    "value_len": len(m.group(1)),
                })
    return findings


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--project-root",
                    help="root for SAST scan")
    ap.add_argument("--log-file",
                    help="runtime log file to scan")
    ap.add_argument("--mode", choices=["sast", "runtime", "both"],
                    default=None,
                    help="override mode selection (default: auto)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    if not args.project_root and not args.log_file:
        print("⛔ must supply --project-root or --log-file", file=sys.stderr)
        return 2

    # Auto-select mode if not specified
    if args.mode is None:
        if args.project_root and args.log_file:
            args.mode = "both"
        elif args.project_root:
            args.mode = "sast"
        else:
            args.mode = "runtime"

    blocks: list[str] = []
    warns: list[str] = []
    sast_result = None
    runtime_result = None

    if args.mode in ("sast", "both") and args.project_root:
        root = Path(args.project_root).resolve()
        if not root.exists():
            print(f"⛔ project-root missing: {root}", file=sys.stderr)
            return 2
        sast_result = _scan_sast(root)
        if sast_result["leaky_calls"]:
            sample = sast_result["leaky_calls"][:5]
            blocks.append(
                f"{len(sast_result['leaky_calls'])} logger call(s) pass "
                f"sensitive fields. Example: "
                f"{sample[0]['file']}:{sample[0]['line']} logs "
                f"{sample[0]['field']!r}"
            )
        if not sast_result["has_sanitizer"] and sast_result["files_scanned"] > 0:
            warns.append(
                "no log-sanitization middleware (pino-redact, winston mask, "
                "loguru sanitizer) detected — adopt one to mask tokens/PII"
            )

    if args.mode in ("runtime", "both") and args.log_file:
        log_path = Path(args.log_file).resolve()
        if not log_path.exists():
            print(f"⛔ log-file missing: {log_path}", file=sys.stderr)
            return 2
        runtime_result = _scan_runtime(log_path)
        if runtime_result["bearer_hits"]:
            blocks.append(
                f"{len(runtime_result['bearer_hits'])} raw Authorization: "
                f"Bearer token(s) found in log (first at line "
                f"{runtime_result['bearer_hits'][0]['line']})"
            )
        if runtime_result["jwt_hits"]:
            blocks.append(
                f"{len(runtime_result['jwt_hits'])} raw JWT(s) logged "
                f"(first at line {runtime_result['jwt_hits'][0]['line']})"
            )
        if runtime_result["password_hits"]:
            blocks.append(
                f"{len(runtime_result['password_hits'])} password field(s) "
                f"logged with non-redacted value"
            )
        if runtime_result["token_hits"]:
            blocks.append(
                f"{len(runtime_result['token_hits'])} token field(s) logged "
                f"with non-redacted value"
            )
        if runtime_result["secret_hits"]:
            blocks.append(
                f"{len(runtime_result['secret_hits'])} secret field(s) "
                f"logged with non-redacted value"
            )
        if runtime_result["email_hits"]:
            warns.append(
                f"{len(runtime_result['email_hits'])} raw email(s) in log — "
                f"consider masking PII (e.g. j***@example.com)"
            )

    verdict = "FAIL" if blocks else ("WARN" if warns else "OK")

    output = {
        "validator": "verify-log-hygiene",
        "verdict": verdict,
        "mode": args.mode,
        "blocks": blocks,
        "warns": warns,
        "sast": sast_result,
        "runtime": runtime_result,
    }

    if args.json:
        print(json.dumps(output, indent=2, default=str))
    else:
        if verdict == "FAIL":
            print(f"⛔ Log hygiene: {len(blocks)} block(s), "
                  f"{len(warns)} warn(s)")
            for b in blocks:
                print(f"  [BLOCK] {b}")
            for w in warns:
                print(f"  [WARN]  {w}")
        elif verdict == "WARN":
            if not args.quiet:
                print(f"⚠ Log hygiene: {len(warns)} warn(s)")
                for w in warns:
                    print(f"  [WARN]  {w}")
        elif not args.quiet:
            print("✓ Log hygiene OK")

    if verdict == "FAIL":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
