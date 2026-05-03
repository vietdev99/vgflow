#!/usr/bin/env python3
"""
phase-migrate.py — Apply migrations from phase-recon state.

Reads `.recon-state.json` produced by phase-recon.py. Applies one or more
migration / archive / rename operations. Destructive moves always land in
`${PHASE_DIR}/.archive/{timestamp}/` with a manifest.json — never rm.

For "complex" migrations (seed / extract_decisions / flow_to_goals / etc.),
this script does not attempt AI-level summarisation. It writes a draft V6
artifact with the legacy content copied verbatim under a template header, so
that downstream `/vg:scope`, `/vg:blueprint` etc. can refine it.

USAGE
  phase-migrate.py --phase-dir P --apply M01           # apply one migration
  phase-migrate.py --phase-dir P --apply M01,M02       # multiple
  phase-migrate.py --phase-dir P --apply-all-recommended
  phase-migrate.py --phase-dir P --consolidate         # run numbered-plan consolidation
  phase-migrate.py --phase-dir P --archive R01         # archive one rot item
  phase-migrate.py --phase-dir P --archive-all-rot
  phase-migrate.py --phase-dir P --dry-run             # print actions, no writes

EXIT CODES
  0 ok
  1 bad args / state missing
  2 action failed (partial work may remain — see stderr)
"""
import argparse
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---- Loading state ---------------------------------------------------------

def load_state(phase_dir: Path) -> dict:
    state_path = phase_dir / ".recon-state.json"
    if not state_path.exists():
        print(f"\033[38;5;208m.recon-state.json missing in {phase_dir}\033[0m", file=sys.stderr)
        print("   Run phase-recon.py first.", file=sys.stderr)
        sys.exit(1)
    return json.loads(state_path.read_text(encoding="utf-8"))


def archive_root(phase_dir: Path) -> Path:
    """Timestamped archive subdir. One dir per migration session."""
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    d = phase_dir / ".archive" / ts
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---- Manifest --------------------------------------------------------------

class Manifest:
    def __init__(self, archive_dir: Path):
        self.archive_dir = archive_dir
        self.path = archive_dir / "manifest.json"
        self.entries: list[dict] = []
        if self.path.exists():
            try:
                self.entries = json.loads(self.path.read_text(encoding="utf-8")).get("entries", [])
            except json.JSONDecodeError:
                self.entries = []

    def add(self, kind: str, source: str, target: str | None = None, meta: dict | None = None):
        self.entries.append({
            "kind": kind,
            "source": source,
            "target": target,
            "meta": meta or {},
            "ts": datetime.now(tz=timezone.utc).isoformat(),
        })

    def save(self):
        self.path.write_text(
            json.dumps({"entries": self.entries}, indent=2),
            encoding="utf-8",
        )


# ---- Template header builder ----------------------------------------------

def wrap_draft(migration_type: str, source_name: str, raw_content: str,
               phase_num: str, target_label: str) -> str:
    """
    Wrap legacy content with a V6-draft frontmatter + usage notice.
    Downstream refinement happens in /vg:scope, /vg:blueprint, etc.
    """
    now = datetime.now(tz=timezone.utc).isoformat()
    header = (
        f"---\n"
        f"migrated_from: {source_name}\n"
        f"migrated_at: {now}\n"
        f"migration_type: {migration_type}\n"
        f"phase: {phase_num}\n"
        f"status: draft\n"
        f"---\n\n"
        f"# Phase {phase_num} — {target_label} (migrated draft)\n\n"
        f"> **Migration notice:** seeded from `{source_name}` during phase reconnaissance.\n"
        f"> Review and refine via the appropriate VG step (see CLAUDE.md / command docs).\n\n"
        f"<!-- ORIGINAL {source_name} CONTENT — refine above and strip this block when done -->\n\n"
    )
    return header + raw_content + "\n"


# ---- Migration executors ---------------------------------------------------
#
# Each executor returns True on success. Mutates files under phase_dir.
# All moves go through manifest + .archive/.

def exec_rename(phase_dir: Path, source: str, target: str,
                manifest: Manifest, dry_run: bool) -> bool:
    src = phase_dir / source
    tgt = phase_dir / target
    if not src.exists():
        print(f"    \033[38;5;208msource missing: {source}\033[0m", file=sys.stderr)
        return False
    if tgt.exists():
        print(f"    \033[38;5;208mtarget exists: {target} (refusing overwrite — archive first)\033[0m", file=sys.stderr)
        return False
    print(f"    rename {source} → {target}")
    if dry_run:
        return True
    src.rename(tgt)
    manifest.add("rename", source, target)
    return True


def exec_seed_or_draft(phase_dir: Path, source: str, target: str,
                       migration_type: str, phase_num: str,
                       target_label: str, manifest: Manifest, dry_run: bool) -> bool:
    """
    Generic "copy legacy content into a V6 draft file" executor.
    Used for: seed, extract_decisions, merge_decisions, flow_to_goals,
    specs_to_goals, extract_goal_status.
    """
    src = phase_dir / source
    tgt = phase_dir / target
    if not src.exists():
        print(f"    \033[38;5;208msource missing: {source}\033[0m", file=sys.stderr)
        return False
    if tgt.exists():
        print(f"    \033[38;5;208mtarget exists: {target} — skip (would overwrite; archive source manually)\033[0m", file=sys.stderr)
        return False
    raw = src.read_text(encoding="utf-8")
    draft = wrap_draft(migration_type, source, raw, phase_num, target_label)
    print(f"    seed {source} → {target} ({migration_type}, {len(raw)} chars)")
    if dry_run:
        return True
    tgt.write_text(draft, encoding="utf-8")
    # After seeding, archive the source (no longer authoritative)
    archive_dir = manifest.archive_dir
    dest = archive_dir / source
    shutil.move(str(src), str(dest))
    manifest.add("seed", source, target, {"archived_source": str(dest.relative_to(phase_dir))})
    return True


def exec_append(phase_dir: Path, source: str, target: str,
                migration_type: str, heading: str,
                manifest: Manifest, dry_run: bool) -> bool:
    """
    Append legacy content to existing V6 artifact under a heading banner.
    Used for: append_gap_wave, append_criteria, merge_tasks, wave_structure.
    """
    src = phase_dir / source
    tgt = phase_dir / target
    if not src.exists():
        print(f"    \033[38;5;208msource missing: {source}\033[0m", file=sys.stderr)
        return False
    if not tgt.exists():
        print(f"    \033[38;5;208mtarget missing: {target} — cannot append; use seed migration first\033[0m", file=sys.stderr)
        return False
    raw = src.read_text(encoding="utf-8")
    now = datetime.now(tz=timezone.utc).isoformat()
    banner = (
        f"\n\n"
        f"<!-- BEGIN migrated from {source} on {now} -->\n"
        f"## {heading} (from `{source}`)\n\n"
    )
    footer = f"\n<!-- END migrated from {source} -->\n"
    print(f"    append {source} → {target} ({migration_type}, {len(raw)} chars)")
    if dry_run:
        return True
    with tgt.open("a", encoding="utf-8") as f:
        f.write(banner + raw + footer)
    # Archive the source
    archive_dir = manifest.archive_dir
    dest = archive_dir / source
    shutil.move(str(src), str(dest))
    manifest.add("append", source, target, {"archived_source": str(dest.relative_to(phase_dir))})
    return True


def exec_consolidate_sequence(phase_dir: Path, phase_num: str, kind: str,
                              manifest: Manifest, dry_run: bool) -> bool:
    """
    Consolidate {phase}-NN-{kind}.md files into single {kind}.md with Wave headers.
    kind ∈ {"PLAN", "SUMMARY"}.
    Skips (returns True) if there are no numbered files of that kind.
    Fails if target {kind}.md already exists (conflict — manual resolution).
    """
    kind_upper = kind.upper()
    pattern = re.compile(rf"^\d+(?:\.\d+)*-\d+-{kind_upper}(?:-[\w-]+)?\.md$")
    target = phase_dir / f"{kind_upper}.md"
    numbered = sorted([p for p in phase_dir.iterdir()
                       if p.is_file() and pattern.match(p.name)])
    if not numbered:
        return True  # nothing to do, not an error
    if target.exists():
        print(f"    \033[38;5;208m{kind_upper}.md exists — numbered {kind_upper}s left; archive manually if desired\033[0m",
              file=sys.stderr)
        return False

    now = datetime.now(tz=timezone.utc).isoformat()
    title = "Plan" if kind_upper == "PLAN" else "Summary"
    refine_hint = ("Refine structure via /vg:blueprint" if kind_upper == "PLAN"
                   else "Refine via /vg:build (the authoritative build summary)")
    parts = [
        f"---\n"
        f"consolidated_from: {[p.name for p in numbered]}\n"
        f"consolidated_at: {now}\n"
        f"phase: {phase_num}\n"
        f"status: draft\n"
        f"---\n\n"
        f"# Phase {phase_num} — {title} (consolidated)\n\n"
        f"> **Consolidation notice:** merged from {len(numbered)} numbered sub-{title.lower()}s.\n"
        f"> Each sub-{title.lower()} is preserved as a Wave section below. {refine_hint}.\n\n"
    ]
    for idx, p in enumerate(numbered, start=1):
        wave_label = re.search(rf"-(\d+)-{kind_upper}", p.name)
        wave_num = wave_label.group(1) if wave_label else f"{idx:02d}"
        content = p.read_text(encoding="utf-8")
        parts.append(f"\n<!-- BEGIN wave {wave_num} from {p.name} -->\n"
                     f"## Wave {wave_num} (from `{p.name}`)\n\n"
                     f"{content}\n"
                     f"<!-- END wave {wave_num} -->\n")

    print(f"    consolidate {len(numbered)} numbered {kind_upper.lower()}s → {kind_upper}.md")
    if dry_run:
        return True
    target.write_text("".join(parts), encoding="utf-8")
    for p in numbered:
        dest = manifest.archive_dir / p.name
        shutil.move(str(p), str(dest))
        manifest.add("consolidate", p.name, f"{kind_upper}.md",
                     {"archived_source": str(dest.relative_to(phase_dir))})
    return True


def exec_consolidate_plans(phase_dir: Path, phase_num: str,
                           manifest: Manifest, dry_run: bool) -> bool:
    """Backward-compat wrapper: consolidate PLANs only (used by --consolidate flag legacy path)."""
    return exec_consolidate_sequence(phase_dir, phase_num, "PLAN", manifest, dry_run)


def exec_archive(phase_dir: Path, filename: str,
                 reason: str, manifest: Manifest, dry_run: bool) -> bool:
    """Archive a single file (rot, superseded, or user-requested)."""
    src = phase_dir / filename
    if not src.exists():
        print(f"    \033[38;5;208msource missing: {filename}\033[0m", file=sys.stderr)
        return False
    dest = manifest.archive_dir / filename
    print(f"    archive {filename} (reason: {reason})")
    if dry_run:
        return True
    shutil.move(str(src), str(dest))
    manifest.add("archive", filename, None, {"reason": reason})
    return True


def exec_rename_rot(phase_dir: Path, filename: str,
                    target: str, manifest: Manifest, dry_run: bool) -> bool:
    """Promote a versioned file to canonical name (when canonical missing)."""
    src = phase_dir / filename
    tgt = phase_dir / target
    if not src.exists():
        print(f"    \033[38;5;208msource missing: {filename}\033[0m", file=sys.stderr)
        return False
    if tgt.exists():
        print(f"    \033[38;5;208mtarget exists: {target} — archive instead\033[0m", file=sys.stderr)
        return False
    print(f"    promote {filename} → {target}")
    if dry_run:
        return True
    src.rename(tgt)
    manifest.add("promote_rot", filename, target)
    return True


# ---- Migration dispatcher --------------------------------------------------

# Human-friendly headings for append migrations
APPEND_HEADINGS = {
    "append_gap_wave": "Gap closure wave",
    "append_criteria": "Additional success criteria",
    "merge_tasks": "Additional tasks",
    "wave_structure": "Parallel wave structure (pre-consolidation)",
}


def apply_migration(phase_dir: Path, state: dict, migration_id: str,
                    manifest: Manifest, dry_run: bool) -> bool:
    """Look up migration by ID and dispatch to executor."""
    candidate = next(
        (m for m in state.get("migration_candidates", []) if m["id"] == migration_id),
        None,
    )
    if not candidate:
        print(f"  \033[38;5;208mmigration ID not found: {migration_id}\033[0m", file=sys.stderr)
        return False

    source = candidate["source"]
    target = candidate["target"]
    mtype = candidate["type"]
    phase_num = state["phase"]

    print(f"  [{migration_id}] {mtype}: {source} → {target}")

    # Target already exists → refuse (user must archive source manually or we archive it without overwriting)
    if candidate["priority"] == "conflict":
        print(f"    \033[33mtarget exists — this migration requires target {target} missing. Skipping.\033[0m",
              file=sys.stderr)
        return False

    if mtype == "rename":
        return exec_rename(phase_dir, source, target, manifest, dry_run)

    if mtype in ("seed", "extract_decisions", "merge_decisions",
                 "flow_to_goals", "specs_to_goals", "extract_goal_status"):
        label = _target_label(target)
        return exec_seed_or_draft(phase_dir, source, target, mtype,
                                  phase_num, label, manifest, dry_run)

    if mtype in APPEND_HEADINGS:
        return exec_append(phase_dir, source, target, mtype,
                           APPEND_HEADINGS[mtype], manifest, dry_run)

    print(f"    \033[38;5;208munknown migration type: {mtype}\033[0m", file=sys.stderr)
    return False


def _target_label(target: str) -> str:
    return {
        "SPECS.md": "Specs",
        "CONTEXT.md": "Context",
        "PLAN.md": "Plan",
        "API-CONTRACTS.md": "API contracts",
        "TEST-GOALS.md": "Test goals",
        "GOAL-COVERAGE-MATRIX.md": "Goal coverage matrix",
        "SUMMARY.md": "Summary",
        "SANDBOX-TEST.md": "Sandbox test",
        "UAT.md": "UAT",
    }.get(target, Path(target).stem)


def apply_archive(phase_dir: Path, state: dict, rot_id: str,
                  manifest: Manifest, dry_run: bool) -> bool:
    rot = next((r for r in state.get("rot_to_archive", []) if r["id"] == rot_id), None)
    if not rot:
        print(f"  \033[38;5;208mrot ID not found: {rot_id}\033[0m", file=sys.stderr)
        return False
    action = rot.get("action", "archive")
    if action == "rename":
        # Promote versioned to canonical
        target = rot.get("target")
        if not target:
            print(f"  \033[38;5;208mrot {rot_id} has action=rename but no target\033[0m", file=sys.stderr)
            return False
        return exec_rename_rot(phase_dir, rot["file"], target, manifest, dry_run)
    return exec_archive(phase_dir, rot["file"], rot.get("reason", ""), manifest, dry_run)


# ---- Main ------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Apply phase migrations / archive rot.")
    ap.add_argument("--phase-dir", required=True, type=Path)
    ap.add_argument("--apply", help="Comma-separated migration IDs (e.g., M01,M03)")
    ap.add_argument("--apply-all-recommended", action="store_true",
                    help="Apply every migration with priority=recommended")
    ap.add_argument("--consolidate", action="store_true",
                    help="Run numbered-plan consolidation (if candidate exists + priority=recommended)")
    ap.add_argument("--archive", help="Comma-separated rot IDs (e.g., R01,R02)")
    ap.add_argument("--archive-all-rot", action="store_true",
                    help="Archive every rot-listed item")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not any([args.apply, args.apply_all_recommended, args.consolidate,
                args.archive, args.archive_all_rot]):
        ap.error("no action given — use --apply / --archive / --consolidate / --*-all-*")

    phase_dir: Path = args.phase_dir.resolve()
    if not phase_dir.exists():
        print(f"\033[38;5;208mphase dir missing: {phase_dir}\033[0m", file=sys.stderr)
        sys.exit(1)

    state = load_state(phase_dir)
    arch = archive_root(phase_dir)
    manifest = Manifest(arch)
    print(f"═══ Phase {state['phase']} migrations ═══")
    print(f"Archive dir: {arch.relative_to(phase_dir)}")
    if args.dry_run:
        print("DRY RUN — no writes")
    print()

    ok_all = True

    # Execution order: consolidate → migrate → archive
    # (consolidation creates PLAN.md / SUMMARY.md that migrations may append to)

    # 1. Consolidate numbered plans + summaries
    if args.consolidate:
        for kind in ("PLAN", "SUMMARY"):
            print(f"  [C-{kind}] consolidate numbered {kind.lower()}s → {kind}.md")
            ok = exec_consolidate_sequence(phase_dir, state["phase"], kind, manifest, args.dry_run)
            ok_all = ok_all and ok

    # 2. Apply migrations (may append to files created by step 1)
    mig_ids: list[str] = []
    if args.apply:
        mig_ids = [x.strip() for x in args.apply.split(",") if x.strip()]
    if args.apply_all_recommended:
        mig_ids += [m["id"] for m in state.get("migration_candidates", [])
                    if m["priority"] == "recommended"]
    mig_ids = list(dict.fromkeys(mig_ids))  # dedupe preserve order

    for mid in mig_ids:
        ok = apply_migration(phase_dir, state, mid, manifest, args.dry_run)
        ok_all = ok_all and ok

    # 3. Archive rot
    rot_ids: list[str] = []
    if args.archive:
        rot_ids = [x.strip() for x in args.archive.split(",") if x.strip()]
    if args.archive_all_rot:
        rot_ids += [r["id"] for r in state.get("rot_to_archive", [])]
    rot_ids = list(dict.fromkeys(rot_ids))

    for rid in rot_ids:
        ok = apply_archive(phase_dir, state, rid, manifest, args.dry_run)
        ok_all = ok_all and ok

    # 4. Save manifest (even dry-run, so the user can review plan)
    if manifest.entries and not args.dry_run:
        manifest.save()
        print()
        print(f"✓ Manifest saved: {manifest.path.relative_to(phase_dir)}")
        print(f"  ({len(manifest.entries)} entries)")

    # 5. Invalidate cache so next phase-recon re-scans
    if not args.dry_run:
        state_path = phase_dir / ".recon-state.json"
        if state_path.exists():
            state_path.unlink()
            print("✓ Invalidated .recon-state.json — next phase-recon will rescan.")

    return 0 if ok_all else 2


if __name__ == "__main__":
    sys.exit(main())
