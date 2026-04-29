#!/usr/bin/env python3
"""
migrate-design-paths.py — auto-move legacy design refs into v2.30+ 2-tier layout.

v2.30.0 splits `.vg/design-normalized/` (single project-level dir) into:
  - `.vg/phases/{N}/design/`      ← phase-scoped (Tier 1)
  - `.vg/design-system/`          ← project-shared (Tier 2)

This script handles the migration:
  1. Walk legacy `.vg/design-normalized/` (or `.planning/design-normalized/`).
  2. For each slug, scan all `.vg/phases/{N}/PLAN.md` for `<design-ref slug="...">`
     citations to that slug.
  3. If exactly one phase cites the slug → move slug's files into that phase's
     `design/` dir.
  4. If multiple phases cite the same slug → move to project-shared
     `.vg/design-system/` (it's actually shared by definition).
  5. If zero phases cite → orphan; move to `.vg/design-system/orphans/` for
     user triage.

Backups: pre-migration state is copied to `.vg/.design-migration-backup/{ts}/`
before any move so user can roll back via `mv` or `rsync`.

Dry-run is the default. Pass `--apply` to actually move files.

Usage:
  python scripts/migrate-design-paths.py [--repo <path>] [--apply] [--verbose]
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path


DESIGN_REF_RE = re.compile(r'<design-ref\s+slug=["\']([^"\']+)["\']')
LEGACY_DIRS_REL = (
    Path(".vg") / "design-normalized",
    Path(".planning") / "design-normalized",
)


def find_legacy_dir(repo: Path) -> Path | None:
    for rel in LEGACY_DIRS_REL:
        p = repo / rel
        if p.is_dir():
            return p
    return None


def collect_slugs(legacy: Path) -> dict[str, list[Path]]:
    """Return {slug: [list of file paths under legacy that belong to this slug]}.

    Slug is extracted from the file stem before the first dot (so
    `home.default.png` → `home`, `home.structural.html` → `home`,
    `home.interactions.md` → `home`).
    """
    by_slug: dict[str, list[Path]] = defaultdict(list)
    # Also collect "shared" non-slug files that belong to the dir itself
    # (e.g. manifest.json) — they go to project-shared regardless.
    shared_files: list[Path] = []

    for f in legacy.rglob("*"):
        if not f.is_file():
            continue
        rel = f.relative_to(legacy)
        # Top-level files (manifest.json, _INDEX.md) → shared bucket
        if len(rel.parts) == 1:
            shared_files.append(f)
            continue
        # Slug = stem of filename before first dot
        slug = f.stem.split(".", 1)[0]
        by_slug[slug].append(f)

    if shared_files:
        # Return shared files under reserved key __shared_root__
        by_slug["__shared_root__"] = shared_files
    return dict(by_slug)


def scan_phase_citations(repo: Path) -> dict[str, set[str]]:
    """Return {slug: set(phase_dir_names)} from PLAN.md `<design-ref>` citations."""
    cites: dict[str, set[str]] = defaultdict(set)
    phases_root = repo / ".vg" / "phases"
    if not phases_root.is_dir():
        return cites
    for ph in phases_root.iterdir():
        if not ph.is_dir():
            continue
        for plan in ph.rglob("PLAN*.md"):
            try:
                text = plan.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for m in DESIGN_REF_RE.finditer(text):
                slug = m.group(1)
                # Skip Form B / no-asset placeholder citations
                if slug.startswith("no-asset"):
                    continue
                cites[slug].add(ph.name)
    return dict(cites)


def classify(
    by_slug: dict[str, list[Path]],
    cites: dict[str, set[str]],
) -> list[dict]:
    """Build move plan: list of {slug, files, target, target_kind, reason}."""
    plan: list[dict] = []

    for slug, files in by_slug.items():
        if slug == "__shared_root__":
            plan.append({
                "slug": slug,
                "files": files,
                "target_kind": "shared",
                "reason": "top-level files (manifest, etc) are shared by nature",
            })
            continue

        cited_by = cites.get(slug, set())
        if not cited_by:
            plan.append({
                "slug": slug,
                "files": files,
                "target_kind": "orphan",
                "reason": "not cited by any phase PLAN.md",
            })
        elif len(cited_by) == 1:
            phase_name = next(iter(cited_by))
            plan.append({
                "slug": slug,
                "files": files,
                "target_kind": "phase",
                "phase_name": phase_name,
                "reason": f"cited only by phase {phase_name}",
            })
        else:
            plan.append({
                "slug": slug,
                "files": files,
                "target_kind": "shared",
                "reason": f"cited by multiple phases: {sorted(cited_by)}",
            })

    return plan


def resolve_target(repo: Path, entry: dict, legacy: Path) -> Path:
    """Resolve target dir for a plan entry. Files keep their relative subdir
    inside the destination tier (e.g. `screenshots/home.default.png` stays
    under `<target>/screenshots/`).
    """
    kind = entry["target_kind"]
    if kind == "phase":
        return repo / ".vg" / "phases" / entry["phase_name"] / "design"
    if kind == "shared":
        return repo / ".vg" / "design-system"
    if kind == "orphan":
        return repo / ".vg" / "design-system" / "orphans"
    raise ValueError(f"unknown target_kind: {kind}")


def execute_plan(plan: list[dict], legacy: Path, repo: Path,
                  dry_run: bool, verbose: bool) -> dict:
    """Apply (or report) the plan. Returns summary dict."""
    summary = {
        "phase_moves": 0,
        "shared_moves": 0,
        "orphan_moves": 0,
        "files_moved": 0,
        "files_skipped_collision": 0,
        "errors": [],
    }

    backup_dir = None
    if not dry_run:
        ts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_dir = repo / ".vg" / ".design-migration-backup" / ts
        backup_dir.mkdir(parents=True, exist_ok=True)
        # Snapshot the entire legacy dir before modification
        try:
            shutil.copytree(legacy, backup_dir / legacy.name, dirs_exist_ok=False)
        except Exception as e:
            summary["errors"].append(f"backup failed: {e}")
            return summary

    for entry in plan:
        target_dir = resolve_target(repo, entry, legacy)
        kind = entry["target_kind"]

        if verbose or dry_run:
            print(f"[{kind:<6}] slug={entry['slug']!r} → {target_dir}")
            print(f"          reason: {entry['reason']}")

        for src in entry["files"]:
            rel = src.relative_to(legacy)
            dst = target_dir / rel
            if verbose or dry_run:
                print(f"    {src.relative_to(repo)} → {dst.relative_to(repo)}")

            if dry_run:
                continue

            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                if dst.exists():
                    summary["files_skipped_collision"] += 1
                    summary["errors"].append(
                        f"collision: {dst.relative_to(repo)} already exists, "
                        f"skipped move from {src.relative_to(repo)}"
                    )
                    continue
                shutil.move(str(src), str(dst))
                summary["files_moved"] += 1
            except Exception as e:
                summary["errors"].append(
                    f"move failed: {src} → {dst}: {e}"
                )

        if kind == "phase":
            summary["phase_moves"] += 1
        elif kind == "shared":
            summary["shared_moves"] += 1
        else:
            summary["orphan_moves"] += 1

    if not dry_run:
        # Remove the (now possibly empty) legacy dir if all its files migrated
        try:
            remaining = list(legacy.rglob("*"))
            remaining_files = [r for r in remaining if r.is_file()]
            if not remaining_files:
                shutil.rmtree(legacy)
                if verbose:
                    print(f"✓ removed empty legacy dir {legacy.relative_to(repo)}")
            else:
                summary["errors"].append(
                    f"legacy dir {legacy.relative_to(repo)} still has "
                    f"{len(remaining_files)} files — kept in place"
                )
        except Exception as e:
            summary["errors"].append(f"legacy cleanup failed: {e}")

    summary["backup"] = (
        str(backup_dir.relative_to(repo)) if backup_dir else None
    )
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", default=".", help="Repo root (default: cwd)")
    ap.add_argument("--apply", action="store_true",
                    help="Actually move files (default: dry-run)")
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args()

    repo = Path(args.repo).resolve()
    legacy = find_legacy_dir(repo)
    if legacy is None:
        print(f"✓ No legacy design dir found under {repo} — nothing to migrate.")
        return 0

    print(f"▸ Legacy design dir: {legacy.relative_to(repo)}")

    by_slug = collect_slugs(legacy)
    if not by_slug:
        print(f"✓ Legacy dir is empty — removing.")
        if args.apply:
            shutil.rmtree(legacy)
        return 0

    cites = scan_phase_citations(repo)
    print(f"▸ Scanned PLAN.md citations: {len(cites)} unique slugs cited "
          f"across {sum(1 for _ in (repo / '.vg' / 'phases').iterdir() if _.is_dir()) if (repo / '.vg' / 'phases').is_dir() else 0} phases")

    plan = classify(by_slug, cites)
    print(f"▸ Migration plan: {len(plan)} slug groups\n")

    summary = execute_plan(plan, legacy, repo, dry_run=not args.apply,
                           verbose=args.verbose)

    print("\n=== Summary ===")
    print(json.dumps(summary, indent=2))

    if not args.apply:
        print("\n(dry-run — re-run with --apply to actually move)")
        return 1

    if summary["errors"]:
        print(f"\n⚠ {len(summary['errors'])} errors — review before deleting backup.")
        return 2

    print(f"\n✓ Migration complete. Backup: {summary.get('backup')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
