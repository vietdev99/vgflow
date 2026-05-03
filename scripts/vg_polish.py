#!/usr/bin/env python3
"""
vg_polish.py — engine for /vg:polish (v2.20.0).

Optional code-cleanup pass. Atomic commit per fix. NOT a pipeline gate.
Light mode is safe (touches only code that can never affect runtime
behavior); deep mode warns on long functions but does not auto-refactor
in v1.

USAGE
  vg_polish.py --mode {scan|apply}
               [--level {light|deep}]
               [--scope <phase-N|since:SHA|file:PATH>]
               [--dry-run]
               [--allow-dirty]
               [--report <out.json>]

DETECTORS (v1)
  Light:
    - console_log         — strip console.log/debug/info (TS/JS only)
    - trailing_whitespace — rstrip per line (source files)
  Deep (light + warn-only):
    - empty_blocks        — empty if/else/catch (warn, no auto-fix)
    - long_function       — function >80 lines (warn, no auto-fix)

EXIT
  0 — scan succeeded OR all fixes applied cleanly
  1 — scan succeeded with candidates (apply mode would fix)
  2 — apply succeeded but at least one fix was reverted
  3 — fatal error (bad args, no git, scope resolve fail, etc.)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field, asdict
from pathlib import Path

REPO_ROOT_ENV = os.environ.get("VG_REPO_ROOT")
if REPO_ROOT_ENV:
    REPO_ROOT = Path(REPO_ROOT_ENV).resolve()
else:
    here = Path(__file__).resolve()
    REPO_ROOT = next(
        (p for p in [here.parent, *here.parents]
         if (p / "VERSION").exists() and (p / ".git").exists()),
        here.parents[1],
    )

# File-extension → detector eligibility.
TS_JS_EXTS = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}
SOURCE_EXTS = TS_JS_EXTS | {
    ".py", ".rb", ".go", ".rs", ".java", ".kt",
    ".md", ".yml", ".yaml", ".json", ".sh", ".css", ".scss",
}
SKIP_DIRS = {
    "node_modules", "dist", "build", ".next", "target",
    "venv", ".venv", "__pycache__", ".git", "coverage",
    "vendor", ".pytest_cache", ".vg",
}

# console.log/debug/info — single-line, no template-literal continuation.
# Skip if line is already commented out.
CONSOLE_RE = re.compile(
    r"^(?P<indent>\s*)console\.(?P<kind>log|debug|info)\s*\([^;\n]*\)\s*;?\s*$"
)
# Trailing whitespace, but only flag if there's actual content before it
# (don't touch all-whitespace lines that may be intentional spacing).
TRAILING_WS_RE = re.compile(r"^(?P<content>.*\S)(?P<ws>[ \t]+)$")
# Empty blocks: { } with optional whitespace/newline. Heuristic only — flag,
# don't auto-fix. Multi-line for readability.
EMPTY_BLOCK_RE = re.compile(
    r"\b(?P<kw>if|else|catch|try|finally)\b[^{]*\{\s*\}",
    re.MULTILINE,
)


@dataclass
class Fix:
    """One pending or applied fix."""
    fix_type: str       # "console_log" / "trailing_whitespace" / etc
    file: str           # repo-relative path
    line: int           # 1-indexed
    snippet: str        # the offending content (for human review)
    severity: str = "fix"  # "fix" or "warn"
    applied: bool = False
    reverted: bool = False
    commit_sha: str | None = None
    error: str | None = None


@dataclass
class Report:
    mode: str
    level: str
    scope: str
    candidates_count: int = 0
    applied_count: int = 0
    reverted_count: int = 0
    warn_count: int = 0
    fixes: list[Fix] = field(default_factory=list)


# ───── scope resolution ───────────────────────────────────────────────


def resolve_scope(scope: str | None) -> list[Path]:
    """Resolve --scope into a list of files to scan.

    Forms:
      None              — every tracked source file
      "phase-N"         — files referenced under .vg/phases/N-*/
      "since:SHA"       — files changed since SHA (`git diff --name-only SHA`)
      "file:PATH"       — single file (must exist)
    """
    if not scope:
        return _git_tracked_files()
    if scope.startswith("file:"):
        p = Path(scope[5:])
        if not p.is_absolute():
            p = (REPO_ROOT / p).resolve()
        if not p.exists():
            sys.stderr.write(f"\033[38;5;208mscope file not found: {p}\033[0m\n")
            sys.exit(3)
        return [p]
    if scope.startswith("since:"):
        sha = scope[6:]
        try:
            out = subprocess.run(
                ["git", "diff", "--name-only", sha, "--"],
                cwd=REPO_ROOT, capture_output=True, text=True,
                check=True, timeout=30,
            ).stdout
        except subprocess.CalledProcessError as e:
            sys.stderr.write(
                f"\033[38;5;208mgit diff failed for since:{sha}: {e.stderr}\033[0m\n"
            )
            sys.exit(3)
        return [REPO_ROOT / line.strip() for line in out.splitlines()
                if line.strip() and (REPO_ROOT / line.strip()).exists()]
    if scope.startswith("phase-"):
        phase_num = scope[6:]
        phases_dir = REPO_ROOT / ".vg" / "phases"
        if not phases_dir.exists():
            sys.stderr.write(
                f"\033[33mno .vg/phases/ — scope=phase-{phase_num} resolves to \033[0m"
                "all tracked files (no phase context)\n"
            )
            return _git_tracked_files()
        # Match phases starting with phase_num (e.g., phase-7 → 7-foo, phase-7-foo)
        matches = sorted(
            p for p in phases_dir.iterdir()
            if p.is_dir() and (p.name == phase_num or
                               p.name.startswith(f"{phase_num}-") or
                               p.name.startswith(f"phase-{phase_num}-"))
        )
        if not matches:
            sys.stderr.write(f"\033[38;5;208mphase dir not found: {scope}\033[0m\n")
            sys.exit(3)
        # Phase scope = files modified in commits referencing that phase.
        # Heuristic: git log grep for "({phase_num}-" or "(phase-{phase_num}"
        try:
            out = subprocess.run(
                ["git", "log", "--name-only", "--pretty=format:",
                 f"--grep=({phase_num}[-.]"],
                cwd=REPO_ROOT, capture_output=True, text=True,
                timeout=30,
            ).stdout
        except subprocess.SubprocessError:
            out = ""
        files = sorted({line.strip() for line in out.splitlines()
                        if line.strip()})
        return [REPO_ROOT / f for f in files
                if (REPO_ROOT / f).exists()]
    sys.stderr.write(f"\033[38;5;208minvalid --scope: {scope}\033[0m\n")
    sys.exit(3)


def _git_tracked_files() -> list[Path]:
    try:
        out = subprocess.run(
            ["git", "ls-files"],
            cwd=REPO_ROOT, capture_output=True, text=True,
            check=True, timeout=30,
        ).stdout
    except subprocess.CalledProcessError as e:
        sys.stderr.write(f"\033[38;5;208mgit ls-files failed: {e.stderr}\033[0m\n")
        sys.exit(3)
    return [REPO_ROOT / line.strip() for line in out.splitlines()
            if line.strip() and (REPO_ROOT / line.strip()).exists()]


def _eligible(p: Path) -> bool:
    """True if path is a source file we want to inspect."""
    if any(part in SKIP_DIRS for part in p.parts):
        return False
    if p.suffix not in SOURCE_EXTS:
        return False
    try:
        return p.is_file() and p.stat().st_size < 2_000_000  # 2 MB cap
    except OSError:
        return False


# ───── detectors ──────────────────────────────────────────────────────


def detect_console_logs(p: Path, lines: list[str]) -> list[Fix]:
    """TS/JS only — strip leftover debug logs."""
    if p.suffix not in TS_JS_EXTS:
        return []
    out: list[Fix] = []
    for i, line in enumerate(lines, start=1):
        # Skip already-commented
        stripped = line.lstrip()
        if stripped.startswith("//"):
            continue
        m = CONSOLE_RE.match(line.rstrip("\r\n"))
        if not m:
            continue
        out.append(Fix(
            fix_type="console_log",
            file=str(p.relative_to(REPO_ROOT)).replace("\\", "/"),
            line=i,
            snippet=line.rstrip("\r\n").lstrip(),
        ))
    return out


def detect_trailing_whitespace(p: Path, lines: list[str]) -> list[Fix]:
    out: list[Fix] = []
    for i, line in enumerate(lines, start=1):
        stripped_eol = line.rstrip("\r\n")
        if TRAILING_WS_RE.match(stripped_eol):
            out.append(Fix(
                fix_type="trailing_whitespace",
                file=str(p.relative_to(REPO_ROOT)).replace("\\", "/"),
                line=i,
                snippet=stripped_eol,
            ))
    return out


def detect_empty_blocks(p: Path, content: str) -> list[Fix]:
    """Warn-only (deep mode)."""
    if p.suffix not in TS_JS_EXTS:
        return []
    out: list[Fix] = []
    for m in EMPTY_BLOCK_RE.finditer(content):
        # Compute line number from offset
        line_no = content[:m.start()].count("\n") + 1
        out.append(Fix(
            fix_type="empty_block",
            file=str(p.relative_to(REPO_ROOT)).replace("\\", "/"),
            line=line_no,
            snippet=m.group(0)[:80],
            severity="warn",
        ))
    return out


def detect_long_functions(p: Path, lines: list[str]) -> list[Fix]:
    """Warn-only (deep mode). Heuristic: count lines between function-like
    declaration and matching `}` at column 0 / dedented."""
    if p.suffix not in TS_JS_EXTS:
        return []
    out: list[Fix] = []
    fn_re = re.compile(
        r"^(\s*)(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\("
    )
    open_brace_re = re.compile(r"\{\s*$")
    in_fn = None  # tuple (start_line, indent, name)
    depth = 0
    for i, raw in enumerate(lines, start=1):
        line = raw.rstrip("\r\n")
        if in_fn is None:
            m = fn_re.match(line)
            if m and open_brace_re.search(line):
                in_fn = (i, len(m.group(1)), m.group(2))
                depth = 1
            continue
        # Track brace depth; cheap heuristic, doesn't handle braces in strings.
        depth += line.count("{") - line.count("}")
        if depth <= 0:
            length = i - in_fn[0] + 1
            if length > 80:
                out.append(Fix(
                    fix_type="long_function",
                    file=str(p.relative_to(REPO_ROOT)).replace("\\", "/"),
                    line=in_fn[0],
                    snippet=f"{in_fn[2]}() — {length} lines",
                    severity="warn",
                ))
            in_fn = None
            depth = 0
    return out


def scan_file(p: Path, level: str) -> list[Fix]:
    fixes: list[Fix] = []
    try:
        content = p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    lines = content.splitlines(keepends=False)
    fixes += detect_console_logs(p, lines)
    fixes += detect_trailing_whitespace(p, lines)
    if level == "deep":
        fixes += detect_empty_blocks(p, content)
        fixes += detect_long_functions(p, lines)
    return fixes


# ───── apply ──────────────────────────────────────────────────────────


def apply_fix(fix: Fix) -> tuple[bool, str]:
    """Apply ONE fix to ONE file in memory + on disk.

    Returns (success, message). Caller is responsible for git commit.
    """
    p = (REPO_ROOT / fix.file).resolve()
    if not p.exists():
        return False, f"file disappeared: {fix.file}"
    try:
        text = p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return False, f"read failed: {e}"

    # Use newline preserved by file (LF or CRLF). Detect from content.
    nl = "\r\n" if "\r\n" in text else "\n"
    lines = text.split(nl)
    # Last element may be "" if file ended with newline; preserve.
    has_trailing_nl = text.endswith(nl)

    idx = fix.line - 1
    if idx < 0 or idx >= len(lines):
        return False, f"line {fix.line} out of range"

    if fix.fix_type == "console_log":
        if not CONSOLE_RE.match(lines[idx]):
            return False, "snippet drifted (line no longer matches)"
        # Drop the line entirely.
        del lines[idx]
    elif fix.fix_type == "trailing_whitespace":
        m = TRAILING_WS_RE.match(lines[idx])
        if not m:
            return False, "snippet drifted (no trailing whitespace anymore)"
        lines[idx] = m.group("content")
    else:
        return False, f"unsupported auto-fix type: {fix.fix_type}"

    new_text = nl.join(lines)
    if has_trailing_nl and not new_text.endswith(nl):
        new_text += nl
    try:
        p.write_text(new_text, encoding="utf-8", newline="")
    except OSError as e:
        return False, f"write failed: {e}"
    return True, "ok"


def git_commit_fix(fix: Fix, scope_label: str) -> tuple[bool, str]:
    """Stage + commit one fix atomically. Returns (success, sha-or-error)."""
    try:
        subprocess.run(
            ["git", "add", "--", fix.file],
            cwd=REPO_ROOT, check=True, capture_output=True, text=True,
        )
        msg = (
            f"polish: {fix.fix_type} in {fix.file}\n"
            f"\n"
            f"Scope: {scope_label}\n"
            f"Line:  {fix.line}\n"
            f"\n"
            f"no-impact"
        )
        subprocess.run(
            ["git", "commit", "-m", msg],
            cwd=REPO_ROOT, check=True, capture_output=True, text=True,
        )
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT, check=True, capture_output=True, text=True,
        ).stdout.strip()
        return True, sha
    except subprocess.CalledProcessError as e:
        # Reset staging if commit failed
        try:
            subprocess.run(["git", "reset", "HEAD", "--", fix.file],
                           cwd=REPO_ROOT, capture_output=True)
            subprocess.run(["git", "checkout", "--", fix.file],
                           cwd=REPO_ROOT, capture_output=True)
        except subprocess.SubprocessError:
            pass
        return False, (e.stderr or e.stdout or str(e))[:200]


def emit_telemetry(event: str, payload: dict) -> None:
    """Best-effort. Never block on failure."""
    orchestrator = REPO_ROOT / ".claude" / "scripts" / "vg-orchestrator" / "__main__.py"
    if not orchestrator.exists():
        return
    try:
        subprocess.run(
            [sys.executable, str(orchestrator), "emit-event",
             "--event-type", event,
             "--payload", json.dumps(payload),
             "--actor", "user-polish"],
            cwd=REPO_ROOT, capture_output=True, timeout=10,
        )
    except subprocess.SubprocessError:
        pass


# ───── main ───────────────────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["scan", "apply"], default="scan")
    ap.add_argument("--level", choices=["light", "deep"], default="light")
    ap.add_argument("--scope", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-dirty", action="store_true")
    ap.add_argument("--report", default=None)
    args = ap.parse_args()

    if args.mode == "apply" and not args.allow_dirty:
        # Engine-level safety: refuse to commit on top of a dirty tree
        # unless explicitly allowed (slash command also guards this).
        try:
            r = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=REPO_ROOT, capture_output=True, text=True,
                check=True, timeout=10,
            )
            if r.stdout.strip():
                sys.stderr.write(
                    "\033[38;5;208mworking tree dirty. Commit/stash first or pass \033[0m"
                    "--allow-dirty.\n"
                )
                return 3
        except subprocess.SubprocessError:
            pass

    files = [p for p in resolve_scope(args.scope) if _eligible(p)]
    report = Report(
        mode=args.mode, level=args.level,
        scope=args.scope or "<repo>",
    )

    print(f"Scanning {len(files)} file(s) (level={args.level}) …")
    all_fixes: list[Fix] = []
    for p in files:
        all_fixes.extend(scan_file(p, args.level))

    # Sort: fixes before warns; within each, by file then line.
    all_fixes.sort(key=lambda f: (f.severity != "fix", f.file, f.line))
    report.fixes = all_fixes
    report.candidates_count = sum(1 for f in all_fixes if f.severity == "fix")
    report.warn_count = sum(1 for f in all_fixes if f.severity == "warn")

    if args.mode == "scan" or args.dry_run:
        _print_scan(report)
        _write_report(report, args.report)
        # Exit 1 in scan if there are auto-fixable candidates (CI-friendly).
        return 1 if report.candidates_count > 0 else 0

    # Apply mode
    emit_telemetry("polish.apply_started", {
        "candidates": report.candidates_count,
        "level": args.level,
        "scope": args.scope or "<repo>",
    })

    print(f"\nApplying {report.candidates_count} fix(es) …")
    scope_label = args.scope or "<repo>"
    # Apply in reverse line order per file: deleting/editing line N must
    # not shift the index of subsequent lines we still need to fix in the
    # same file. Sort: file ASC, line DESC, so each per-file group runs
    # bottom-up.
    fixes_to_apply = [f for f in all_fixes if f.severity == "fix"]
    fixes_to_apply.sort(key=lambda f: (f.file, -f.line))
    for fix in fixes_to_apply:
        ok, msg = apply_fix(fix)
        if not ok:
            fix.error = msg
            print(f"  ✗ {fix.file}:{fix.line} ({fix.fix_type}) — {msg}")
            continue
        ok, sha_or_err = git_commit_fix(fix, scope_label)
        if not ok:
            fix.error = sha_or_err
            print(f"  ✗ {fix.file}:{fix.line} ({fix.fix_type}) — "
                  f"commit failed: {sha_or_err}")
            continue
        fix.applied = True
        fix.commit_sha = sha_or_err
        report.applied_count += 1
        print(f"  ✓ {fix.file}:{fix.line} ({fix.fix_type}) → {sha_or_err[:8]}")
        emit_telemetry("polish.fix_applied", {
            "file": fix.file, "line": fix.line,
            "fix_type": fix.fix_type, "sha": sha_or_err,
        })

    print(f"\n  Applied:  {report.applied_count}")
    print(f"  Reverted: {report.reverted_count}")
    print(f"  Warned:   {report.warn_count}")

    _write_report(report, args.report)

    if report.reverted_count > 0:
        return 2
    return 0


def _print_scan(report: Report) -> None:
    if not report.fixes:
        print("No candidates found.")
        return
    print(f"\nFound {report.candidates_count} fix candidate(s) "
          f"+ {report.warn_count} warning(s):\n")
    by_file: dict[str, list[Fix]] = {}
    for f in report.fixes:
        by_file.setdefault(f.file, []).append(f)
    for file, fixes in by_file.items():
        print(f"  {file}")
        for f in fixes:
            sev = "" if f.severity == "warn" else "  "
            short = f.snippet[:70] + ("…" if len(f.snippet) > 70 else "")
            print(f"    {sev}L{f.line:>5}  [{f.fix_type:<22}]  {short}")


def _write_report(report: Report, out_path: str | None) -> None:
    if not out_path:
        return
    Path(out_path).write_text(
        json.dumps(asdict(report), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


if __name__ == "__main__":
    sys.exit(main())
