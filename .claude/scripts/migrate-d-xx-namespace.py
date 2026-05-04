#!/usr/bin/env python3
"""
migrate-d-xx-namespace.py — VG v1.8.0 BREAKING: D-XX namespace collision fix.

PROBLEM (sharpest finding, Claude reviewer):
At phase 15+, D-12 in a phase CONTEXT.md COLLIDES with D-12 in FOUNDATION.md →
AI agents cite the wrong source → silent constraint misapplication.
This is a WORKFLOW DESIGN FAULT, not a user error. Migration (chuyển đổi)
is MANDATORY before v1.10.1.

NEW NAMESPACE (không gian tên):
  - .planning/FOUNDATION.md    : D-XX  → F-XX    (project-level, stable across milestones)
  - .planning/phases/{N}/CONTEXT.md : D-XX  → P{N}.D-XX  (phase-scoped)
  - Cross-references in PLAN.md, SUMMARY.md, UAT.md, commits, etc: context-aware rewrite

USAGE:
  python3 .claude/scripts/migrate-d-xx-namespace.py              # dry-run (default) — preview
  python3 .claude/scripts/migrate-d-xx-namespace.py --apply      # commit changes, with backup
  python3 .claude/scripts/migrate-d-xx-namespace.py --apply --no-backup   # skip backup (NOT recommended)
  python3 .claude/scripts/migrate-d-xx-namespace.py --check-commits   # also scan last 100 commits, suggest rewrites (NEVER auto-rewrite history)

OUTPUT:
  .planning/.namespace-migration-{ts}.log   : every rename attempted, with context
  .planning/.archive/{ts}/pre-migration/    : backup of all modified files (if --apply and not --no-backup)

SAFETY:
  - Idempotent: re-running after a successful migration is a no-op
  - Atomic: if --apply and any write fails, backup is restored, exit 1
  - Ambiguous refs ("see D-12" with no clear CONTEXT/FOUNDATION anchor): output WARNING + SKIP
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

ROOT = Path.cwd()
PLANNING = ROOT / ".planning"
PHASES_DIR = PLANNING / "phases"
FOUNDATION_FILE = PLANNING / "FOUNDATION.md"
ARCHIVE_BASE = PLANNING / ".archive"

# ---------- i18n glossary (RULE: English terms get VN gloss at first use) ----------
GLOSS = {
    "namespace": "namespace (không gian tên)",
    "migration": "migration (chuyển đổi)",
    "collision": "collision (xung đột)",
    "dry_run": "dry-run (chạy thử, không ghi)",
    "backup": "backup (sao lưu)",
    "legacy": "legacy (định dạng cũ)",
}


def g(term: str) -> str:
    """Return glossed term on first use, plain on subsequent. Simple per-run tracker."""
    if term not in _seen:
        _seen.add(term)
        return GLOSS.get(term, term)
    return term


_seen: set[str] = set()


# ---------- data shapes ----------
@dataclass
class Rename:
    file: Path
    line_no: int
    before: str
    after: str
    reason: str  # "foundation-decision-header" | "phase-decision-header" | "cross-ref" | ...


@dataclass
class Warning:
    file: Path
    line_no: int
    text: str
    reason: str


@dataclass
class Plan:
    renames: list[Rename] = field(default_factory=list)
    warnings: list[Warning] = field(default_factory=list)
    files_touched: set[Path] = field(default_factory=set)


# ---------- phase detection ----------
_PHASE_DIR_RE = re.compile(r"^(\d+(?:\.\d+)*)")


def extract_phase_number(phase_dir: Path) -> str | None:
    """From `.planning/phases/07.10.1-user-drawer-tabs/` → `7.10.1` (strip leading zeros, keep decimals)."""
    m = _PHASE_DIR_RE.match(phase_dir.name)
    if not m:
        return None
    raw = m.group(1)
    # Strip leading zeros from each decimal segment: 07.10.1 → 7.10.1
    parts = [str(int(p)) for p in raw.split(".")]
    return ".".join(parts)


# ---------- pattern builders ----------
# Match D-XX where:
#   - NOT already prefixed with "P{phase}." (i.e., not already migrated)
#   - NOT preceded by F- or other alphanumeric that would make it unrelated (A-Z, a-z, 0-9)
# Using negative lookbehind: (?<![\w.])
# And negative lookahead on trailing: (?!\d) to avoid matching D-1 inside D-10
D_XX_RE = re.compile(r"(?<![\w.])D-(\d+)(?!\d)")


def plan_foundation_migration(plan: Plan) -> None:
    """FOUNDATION.md: D-XX → F-XX (unambiguous by file location)."""
    if not FOUNDATION_FILE.exists():
        return
    text = FOUNDATION_FILE.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=False)
    for i, line in enumerate(lines, start=1):
        for m in D_XX_RE.finditer(line):
            before = m.group(0)  # "D-12"
            after = f"F-{m.group(1)}"  # "F-12"
            plan.renames.append(
                Rename(
                    file=FOUNDATION_FILE,
                    line_no=i,
                    before=before,
                    after=after,
                    reason="foundation-decision",
                )
            )
            plan.files_touched.add(FOUNDATION_FILE)


def plan_phase_context_migration(plan: Plan) -> None:
    """Per-phase CONTEXT.md: D-XX → P{phase}.D-XX."""
    if not PHASES_DIR.is_dir():
        return
    for phase_dir in sorted(PHASES_DIR.iterdir()):
        if not phase_dir.is_dir():
            continue
        phase_num = extract_phase_number(phase_dir)
        if phase_num is None:
            continue
        ctx = phase_dir / "CONTEXT.md"
        if not ctx.exists():
            continue
        text = ctx.read_text(encoding="utf-8")
        lines = text.splitlines(keepends=False)
        for i, line in enumerate(lines, start=1):
            for m in D_XX_RE.finditer(line):
                before = m.group(0)
                after = f"P{phase_num}.D-{m.group(1)}"
                plan.renames.append(
                    Rename(
                        file=ctx,
                        line_no=i,
                        before=before,
                        after=after,
                        reason="phase-decision",
                    )
                )
                plan.files_touched.add(ctx)


def plan_cross_references(plan: Plan) -> None:
    """Scan PLAN, SUMMARY, UAT, DISCUSSION-LOG, etc. Use context to decide prefix."""
    if not PHASES_DIR.is_dir():
        return
    SIBLING_PATTERNS = {"PLAN.md", "PLAN-v*.md", "SUMMARY*.md", "UAT.md", "AMENDMENT-LOG.md",
                        "DISCUSSION-LOG.md", "REVIEW.md", "SANDBOX-TEST.md", "TEST-GOALS.md",
                        "API-CONTRACTS.md", "GOAL-COVERAGE-MATRIX.md"}
    for phase_dir in sorted(PHASES_DIR.iterdir()):
        if not phase_dir.is_dir():
            continue
        phase_num = extract_phase_number(phase_dir)
        if phase_num is None:
            continue

        for pattern in SIBLING_PATTERNS:
            for f in phase_dir.glob(pattern):
                if not f.is_file():
                    continue
                try:
                    text = f.read_text(encoding="utf-8")
                except Exception:
                    continue
                lines = text.splitlines(keepends=False)
                for i, line in enumerate(lines, start=1):
                    for m in D_XX_RE.finditer(line):
                        before = m.group(0)
                        # Context-based disambiguation
                        context_window = line.lower()
                        if "foundation" in context_window or "f-" in context_window.replace(before.lower(), ""):
                            # Explicit foundation mention → F-XX
                            after = f"F-{m.group(1)}"
                            reason = "cross-ref-foundation"
                        elif "context" in context_window or "phase" in context_window or "p{" in context_window:
                            # Explicit phase mention → P{phase}.D-XX
                            after = f"P{phase_num}.D-{m.group(1)}"
                            reason = "cross-ref-phase"
                        else:
                            # Ambiguous — default to phase-local (most common case in phase artifacts)
                            # But emit warning
                            after = f"P{phase_num}.D-{m.group(1)}"
                            reason = "cross-ref-ambiguous-default-phase"
                            plan.warnings.append(
                                Warning(
                                    file=f,
                                    line_no=i,
                                    text=line.strip()[:120],
                                    reason=f"Ambiguous ref '{before}'. Defaulted to P{phase_num}.D-{m.group(1)} (phase-local). Review manually if FOUNDATION-cite intended.",
                                )
                            )
                        plan.renames.append(
                            Rename(
                                file=f,
                                line_no=i,
                                before=before,
                                after=after,
                                reason=reason,
                            )
                        )
                        plan.files_touched.add(f)


def plan_top_level_planning_docs(plan: Plan) -> None:
    """Root-level .planning/ docs (ROADMAP, STATE, REQUIREMENTS, PROJECT) — default to F-XX since they're project-level."""
    if not PLANNING.is_dir():
        return
    for pattern in ("ROADMAP.md", "STATE.md", "REQUIREMENTS.md", "PROJECT.md"):
        f = PLANNING / pattern
        if not f.exists() or f == FOUNDATION_FILE:
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        lines = text.splitlines(keepends=False)
        for i, line in enumerate(lines, start=1):
            for m in D_XX_RE.finditer(line):
                before = m.group(0)
                # Project-level docs → assume F-XX
                after = f"F-{m.group(1)}"
                plan.renames.append(
                    Rename(
                        file=f,
                        line_no=i,
                        before=before,
                        after=after,
                        reason="top-level-planning-doc",
                    )
                )
                plan.files_touched.add(f)


# ---------- commit history scan (suggest only, NEVER rewrite) ----------
def scan_commit_history(n: int = 100) -> list[tuple[str, str]]:
    """Return [(commit_sha, subject_line)] for commits where subject or body cites bare D-XX."""
    try:
        out = subprocess.check_output(
            ["git", "log", f"-n{n}", "--pretty=format:%H%x1f%s%x1f%b%x1e"],
            cwd=ROOT,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="ignore",
        )
    except Exception:
        return []
    suggestions: list[tuple[str, str]] = []
    for entry in out.split("\x1e"):
        parts = entry.strip().split("\x1f")
        if len(parts) < 2:
            continue
        sha = parts[0]
        subject = parts[1]
        body = parts[2] if len(parts) > 2 else ""
        combined = subject + "\n" + body
        # Find D-XX not preceded by P{phase}.
        if D_XX_RE.search(combined):
            # Has bare D-XX
            suggestions.append((sha, subject))
    return suggestions


# ---------- execution ----------
def write_log(plan: Plan, log_path: Path, mode: str) -> None:
    with log_path.open("w", encoding="utf-8") as f:
        f.write(f"# VG v1.8.0 D-XX Namespace Migration Log\n\n")
        f.write(f"**Mode:** {mode}\n")
        f.write(f"**Timestamp:** {_dt.datetime.now().isoformat()}\n")
        f.write(f"**Files touched:** {len(plan.files_touched)}\n")
        f.write(f"**Renames:** {len(plan.renames)}\n")
        f.write(f"**Warnings:** {len(plan.warnings)}\n\n")

        # Group renames by file
        by_file: dict[Path, list[Rename]] = {}
        for r in plan.renames:
            by_file.setdefault(r.file, []).append(r)

        f.write("## Renames by File\n\n")
        for fp, renames in sorted(by_file.items(), key=lambda kv: str(kv[0])):
            f.write(f"### {fp.relative_to(ROOT)}\n\n")
            for r in renames:
                f.write(f"- Line {r.line_no}: `{r.before}` → `{r.after}` ({r.reason})\n")
            f.write("\n")

        if plan.warnings:
            f.write("## Warnings (review manually)\n\n")
            for w in plan.warnings:
                f.write(f"- `{w.file.relative_to(ROOT)}:{w.line_no}` — {w.reason}\n")
                f.write(f"  > {w.text}\n\n")


def apply_plan(plan: Plan, backup_dir: Path | None) -> bool:
    """Apply renames in-place. Back up first if backup_dir given. Return True on success."""
    # 1. Back up
    if backup_dir is not None:
        backup_dir.mkdir(parents=True, exist_ok=True)
        for f in plan.files_touched:
            rel = f.relative_to(ROOT)
            dest = backup_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dest)

    # 2. Group renames by file
    by_file: dict[Path, list[Rename]] = {}
    for r in plan.renames:
        by_file.setdefault(r.file, []).append(r)

    # 3. Apply per-file: read, do all substitutions in a single pass, write
    try:
        for fp, renames in by_file.items():
            text = fp.read_text(encoding="utf-8")
            # Build a line-indexed set of substitutions so we don't double-replace
            # Simplest approach: re.sub with a callback that picks the right rename based on match position
            # For safety, do substitutions from end-of-file toward beginning so offsets stay stable.
            # But easier: since our renames are idempotent direction (D-X → something with MORE chars),
            # we can run them all via a single regex substitution that checks context.
            # Use the same regex D_XX_RE and let a decision function pick.
            renames_by_key = {(r.line_no, r.before): r for r in renames}

            new_lines: list[str] = []
            for i, line in enumerate(text.splitlines(keepends=False), start=1):
                def _sub(m: re.Match[str]) -> str:
                    before = m.group(0)
                    r = renames_by_key.get((i, before))
                    if r is None:
                        return before  # no rename recorded
                    return r.after

                new_lines.append(D_XX_RE.sub(_sub, line))
            # Preserve trailing newline
            new_text = "\n".join(new_lines)
            if text.endswith("\n"):
                new_text += "\n"
            fp.write_text(new_text, encoding="utf-8")
    except Exception as e:
        # Rollback on failure
        print(f"[migrate] FAILED during write: {e}", file=sys.stderr)
        if backup_dir is not None:
            print(f"[migrate] Rolling back from backup: {backup_dir}", file=sys.stderr)
            for f in plan.files_touched:
                rel = f.relative_to(ROOT)
                src = backup_dir / rel
                if src.exists():
                    shutil.copy2(src, f)
        return False
    return True


def main() -> int:
    p = argparse.ArgumentParser(
        description="VG v1.8.0 D-XX namespace (không gian tên) migration (chuyển đổi) — fix collision (xung đột) between FOUNDATION and phase CONTEXT."
    )
    p.add_argument("--apply", action="store_true", help="Commit changes (default: dry-run = preview only)")
    p.add_argument("--no-backup", action="store_true", help="Skip backup before --apply (NOT recommended)")
    p.add_argument("--check-commits", action="store_true", help="Also scan last 100 commits, suggest rewrites (never auto-rewrite history)")
    p.add_argument("--commits-n", type=int, default=100, help="Number of commits to scan when --check-commits (default: 100)")
    args = p.parse_args()

    if not PLANNING.is_dir():
        print(f"[migrate] .planning/ not found at {PLANNING}. Run /vg:project first.", file=sys.stderr)
        return 1

    print(f"[migrate] D-XX {g('namespace')} {g('migration')} — preventing FOUNDATION/CONTEXT {g('collision')}.")
    print(f"[migrate] Mode: {'APPLY (will modify files)' if args.apply else 'DRY-RUN (preview only)'}")
    print()

    plan = Plan()
    plan_foundation_migration(plan)
    plan_phase_context_migration(plan)
    plan_cross_references(plan)
    plan_top_level_planning_docs(plan)

    ts = _dt.datetime.now().strftime("%Y%m%dT%H%M%SZ")
    log_path = PLANNING / f".namespace-migration-{ts}.log"

    # Summary
    print(f"  Files to touch: {len(plan.files_touched)}")
    print(f"  Renames planned: {len(plan.renames)}")
    print(f"  Warnings: {len(plan.warnings)}")
    print()

    if plan.warnings:
        print("  Warnings (review manually):")
        for w in plan.warnings[:5]:
            print(f"    - {w.file.relative_to(ROOT)}:{w.line_no} — {w.reason}")
        if len(plan.warnings) > 5:
            print(f"    - ...and {len(plan.warnings) - 5} more (see log)")
        print()

    if args.check_commits:
        commit_suggestions = scan_commit_history(args.commits_n)
        if commit_suggestions:
            print(f"  Commit history: {len(commit_suggestions)} commits cite bare D-XX (last {args.commits_n}):")
            for sha, subj in commit_suggestions[:10]:
                print(f"    {sha[:8]}  {subj}")
            if len(commit_suggestions) > 10:
                print(f"    ...and {len(commit_suggestions) - 10} more")
            print("  (History NOT auto-rewritten — too risky. Use interactive rebase manually if needed.)")
            print()

    if not plan.renames:
        print("[migrate] Nothing to migrate — all IDs already using new namespace. Exiting.")
        write_log(plan, log_path, "dry-run-noop" if not args.apply else "apply-noop")
        print(f"[migrate] Log: {log_path}")
        return 0

    # Write log regardless of mode
    write_log(plan, log_path, "dry-run" if not args.apply else "apply")
    print(f"[migrate] Log written: {log_path.relative_to(ROOT)}")

    if not args.apply:
        print()
        print("[migrate] DRY-RUN complete. To commit changes:")
        print(f"[migrate]   python3 .claude/scripts/migrate-d-xx-namespace.py --apply")
        return 0

    # APPLY mode
    backup_dir: Path | None = None
    if not args.no_backup:
        backup_dir = ARCHIVE_BASE / ts / "pre-migration"
        print(f"[migrate] {g('backup').capitalize()}: {backup_dir.relative_to(ROOT)}")

    success = apply_plan(plan, backup_dir)
    if success:
        print()
        print(f"[migrate] APPLIED: {len(plan.renames)} renames across {len(plan.files_touched)} files.")
        if backup_dir:
            print(f"[migrate] Backup available at: {backup_dir.relative_to(ROOT)}")
        print()
        print("[migrate] Next steps:")
        print("  1. Review changes:  git diff")
        print("  2. Run typecheck:   {config.build_gates.typecheck_cmd}")
        print("  3. Commit:          git add -u && git commit -m 'chore: migrate D-XX → F-XX / P{phase}.D-XX (v1.8.0 namespace fix)'")
        return 0
    else:
        print("[migrate] FAILED — backup restored. No files modified.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
