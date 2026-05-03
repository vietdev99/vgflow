#!/usr/bin/env python3
"""
Validator: verify-hardcode-register-drift.py

Phase K5 (workflow-hardening v2.7): drift gate for `.vg/HARDCODE-REGISTER.md`.

Compares the register's declared occurrence count against actual `ssh vollx`
literal count in source. When the gap exceeds tolerance, BLOCKs CI so the
operator must either (a) refactor the new hardcode to config OR (b) update
the register with an INTENTIONAL_HARDCODE entry justifying the new literal.

Companion to:
  - .claude/scripts/validators/verify-no-hardcoded-paths.py (line-level
    BLOCK validator that runs on every commit)
  - .vg/HARDCODE-REGISTER.md (audit register, refreshed per Phase K)

Behaviors:
  - Missing register     → PASS with note "no audit yet" (bootstrap-friendly)
  - Schema malformed     → BLOCK with schema error (--schema-only mode)
  - Counts match         → PASS
  - Drift detected       → BLOCK
  - Generated > 30 days  → WARN ("re-audit recommended"), still PASS
  - Annotated lines      → skipped per `# INTENTIONAL_HARDCODE:` marker

Exit codes:
  0  PASS or PASS+WARN
  1  BLOCK
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()

REGISTER_PATH = REPO_ROOT / ".vg" / "HARDCODE-REGISTER.md"

# Tolerated stale window before WARN.
STALE_DAYS = 30

# Patterns matched in source files (mirror verify-no-hardcoded-paths.py
# for the K4 SSH alias literal — drift gate counts the operational
# occurrences, NOT the test-fixture annotations).
SSH_ALIAS_RE = re.compile(r"\bssh\s+vollx\b(?!\.)")
INTENTIONAL_RE = re.compile(
    r"(?:#|//|<!--)\s*INTENTIONAL_HARDCODE\b",
    re.IGNORECASE,
)

# Allowlist (paths excluded from grep — mirrors verify-no-hardcoded-paths.py
# ALLOWLIST_RE so drift detection counts the SAME universe the BLOCK
# validator does. Keep these in sync.
ALLOWLIST_PREFIXES = (
    ".vg/",
    ".planning/",
    "infra/docs/",
    "infra/ansible/",
    "infra/cloudflare/",
    "docs/",
    "node_modules/",
    ".git/",
    ".codex/skills/",
    ".claude/backup/",        # frozen pre-VG snapshot — out of scope
    ".agent/",                 # legacy GSD agent workspace
    "apps/web/e2e/",          # test fixtures (mirror BLOCK validator)
)
ALLOWLIST_SUFFIXES = (
    ".example",
)
ALLOWLIST_FILES = (
    ".claude/vg.config.md",
    ".claude/scripts/validators/verify-no-hardcoded-paths.py",
    ".claude/scripts/validators/verify-hardcode-register-drift.py",
    ".claude/scripts/tests/test_hardcode_register_drift.py",  # K5 test self
    "CLAUDE.md",                # project root rule documentation
    "README.md",
    "CHANGELOG.md",
)

# Source extensions scanned (mirror verify-no-hardcoded-paths).
SOURCE_EXTS = {".sh", ".js", ".jsx", ".ts", ".tsx", ".py", ".rs",
               ".go", ".yaml", ".yml", ".json", ".md"}


def _emit(verdict: str, message: str, *, extra: dict | None = None) -> None:
    payload = {
        "validator": "verify-hardcode-register-drift",
        "verdict": verdict,
        "evidence": [{"type": "hardcode_register_drift", "message": message}],
    }
    if extra:
        payload["evidence"][0].update(extra)
    print(json.dumps(payload), flush=True)


def _is_allowlisted(rel: str) -> bool:
    rel = rel.replace("\\", "/")
    if rel in ALLOWLIST_FILES:
        return True
    for pre in ALLOWLIST_PREFIXES:
        if rel.startswith(pre):
            return True
    for suf in ALLOWLIST_SUFFIXES:
        if rel.endswith(suf):
            return True
    return False


_PRUNE_DIRS = {
    "node_modules",
    ".git",
    ".vg",
    ".planning",
    "docs",
    "__pycache__",
    ".turbo",
    ".next",
    "dist",
    "build",
    "target",
    ".pytest_cache",
}


def _walk_sources():
    """os.walk-based generator that prunes heavy/irrelevant dirs.

    Equivalent to rglob but Windows long-path safe — we never descend
    into node_modules/.git/etc which may exceed MAX_PATH.
    """
    for dirpath, dirnames, filenames in os.walk(REPO_ROOT):
        # Prune in-place so os.walk doesn't descend.
        dirnames[:] = [d for d in dirnames if d not in _PRUNE_DIRS]
        for name in filenames:
            yield Path(dirpath) / name


def _scan_sources() -> int:
    """Count `ssh vollx` literal occurrences in the source tree.

    Skips lines marked with `# INTENTIONAL_HARDCODE:` (and the
    immediately following non-blank line, which may be a triple-quoted
    string body — same lookback semantics as verify-no-hardcoded-paths).
    """
    count = 0
    for fp in _walk_sources():
        if not fp.is_file():
            continue
        if fp.suffix not in SOURCE_EXTS:
            continue
        try:
            rel = str(fp.relative_to(REPO_ROOT)).replace("\\", "/")
        except ValueError:
            continue
        if _is_allowlisted(rel):
            continue
        try:
            text = fp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lines = text.splitlines()
        # Annotation propagation — same logic as scan_file() in
        # verify-no-hardcoded-paths.py.
        annotated: dict[int, bool] = {}
        pending = False
        for idx, ln in enumerate(lines, 1):
            if INTENTIONAL_RE.search(ln):
                annotated[idx] = True
                pending = True
                continue
            if pending and ln.strip():
                annotated[idx] = True
                pending = False
            elif not ln.strip():
                continue
            else:
                pending = False
        for idx, ln in enumerate(lines, 1):
            if annotated.get(idx):
                continue
            if SSH_ALIAS_RE.search(ln):
                count += 1
    return count


def _parse_register() -> dict | None:
    """Parse the register, return dict with count + generated_date or None."""
    if not REGISTER_PATH.exists():
        return None
    text = REGISTER_PATH.read_text(encoding="utf-8", errors="replace")
    # Generated date — accept "Generated:" header.
    gen_match = re.search(
        r"^\*\*Generated:\*\*\s*([0-9]{4}-[0-9]{2}-[0-9]{2})",
        text,
        re.MULTILINE,
    )
    generated = gen_match.group(1) if gen_match else None
    # Total count — first prefer the count summary block, fall back to
    # counting table rows under "ssh_alias" tables.
    total_match = re.search(
        r"TOTAL\s+operational\s+occurrences:\s*(\d+)",
        text,
        re.IGNORECASE,
    )
    total = int(total_match.group(1)) if total_match else None
    if total is None:
        # Best-effort fallback: count rows in tables under section 4
        section_match = re.search(
            r"## 4\. Active occurrence registry(.+?)(?:^## |\Z)",
            text,
            re.DOTALL | re.MULTILINE,
        )
        if section_match:
            block = section_match.group(1)
            row_re = re.compile(
                r"^\|\s*[^\|]+\.(?:sh|py|md|js|ts|tsx|yml|yaml)\s*\|",
                re.MULTILINE,
            )
            total = len(row_re.findall(block))
    return {
        "generated": generated,
        "total": total or 0,
        "raw": text,
    }


def _validate_schema(parsed: dict) -> tuple[bool, str | None]:
    """Verify each row in section 4 has at least 4 pipe-delimited fields.

    Header rows + separator (`|---|`) are ignored.
    """
    text = parsed["raw"]
    section_match = re.search(
        r"## 4\. Active occurrence registry(.+?)(?:^## |\Z)",
        text,
        re.DOTALL | re.MULTILINE,
    )
    if not section_match:
        # Section 4 is optional — schema is vacuously valid.
        return True, None
    block = section_match.group(1)
    bad_rows: list[str] = []
    for line in block.splitlines():
        s = line.strip()
        if not s.startswith("|") or not s.endswith("|"):
            continue
        if re.match(r"^\|[\s|\-:]+\|$", s):
            continue  # separator
        # Skip header rows (no period or extension hint, and contains "file" etc)
        cells = [c.strip() for c in s.strip("|").split("|")]
        if not cells or all(not c for c in cells):
            continue
        if cells[0].lower() in ("file", "category", "path-prefix"):
            continue
        # Need at least 4 columns: file | line | literal | remediation
        if len(cells) < 4:
            bad_rows.append(s)
    if bad_rows:
        return False, f"{len(bad_rows)} register row(s) missing required columns (need ≥ 4: file|line|literal|remediation)"
    return True, None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--schema-only", action="store_true",
                    help="Validate register schema only (skip count check)")
    ap.add_argument("--tolerance", type=int, default=0,
                    help="Allowed |register - grep| difference before BLOCK")
    args = ap.parse_args()

    parsed = _parse_register()
    if parsed is None:
        # Bootstrap-friendly: no register yet → graceful PASS
        _emit(
            "PASS",
            "no audit yet (HARDCODE-REGISTER.md missing) — register will be "
            "created on next Phase K audit pass",
        )
        sys.exit(0)

    # Schema validation
    schema_ok, schema_err = _validate_schema(parsed)
    if not schema_ok:
        _emit("BLOCK", f"register schema invalid: {schema_err}")
        print(f"BLOCK: register schema invalid: {schema_err}", file=sys.stderr)
        sys.exit(1)
    if args.schema_only:
        _emit("PASS", "register schema validates")
        sys.exit(0)

    # Stale check
    stale_msg = ""
    if parsed["generated"]:
        try:
            gen_dt = datetime.strptime(parsed["generated"], "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            )
            age_days = (datetime.now(timezone.utc) - gen_dt).days
            if age_days > STALE_DAYS:
                stale_msg = (
                    f" (register is {age_days} days old > {STALE_DAYS} day "
                    "threshold — re-audit recommended) WARN: stale"
                )
        except ValueError:
            pass

    # Count comparison
    register_total = parsed["total"]
    grep_total = _scan_sources()
    diff = abs(register_total - grep_total)

    if diff > args.tolerance:
        _emit(
            "BLOCK",
            f"hardcode register drift: register declares {register_total} "
            f"operational occurrences but grep finds {grep_total} "
            f"(|diff|={diff} > tolerance={args.tolerance}). "
            "Either refactor the new literal to config OR update "
            "HARDCODE-REGISTER.md with an INTENTIONAL_HARDCODE entry.",
            extra={"register_count": register_total, "grep_count": grep_total},
        )
        sys.exit(1)

    _emit(
        "PASS",
        f"register count {register_total} matches grep count {grep_total}{stale_msg}",
        extra={
            "register_count": register_total,
            "grep_count": grep_total,
            "stale": bool(stale_msg),
        },
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
