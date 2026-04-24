#!/usr/bin/env python3
"""
Codex skill mirror sync validator (Phase 0 of v2.5.2 hardening).

Problem closed:
  When .claude/commands/vg/ source is patched with anti-forge contracts
  but .codex/skills/ + ~/.codex/skills/ mirrors remain stale, Codex agents
  run the old trust model and can forge evidence against the pre-patch
  contract. v2.5.1's trust parity breach is exactly this.

This validator establishes the forensic baseline: SHA256 hash parity
across 3 locations (RTB source → local .codex mirror → global ~/.codex
mirror), plus optional vgflow-repo upstream verification.

Locations compared:
  - Chain A (Claude path):
      $REPO_ROOT/.claude/commands/vg/*.md
      $VGFLOW_REPO/commands/vg/*.md            (optional, if $VGFLOW_REPO set)
  - Chain B (Codex path):
      $VGFLOW_REPO/codex-skills/vg-*/SKILL.md  (authoritative mirror)
      $REPO_ROOT/.codex/skills/vg-*/SKILL.md
      $HOME/.codex/skills/vg-*/SKILL.md

Chain B is transformed from Chain A (strips <NARRATION_POLICY>, prepends
codex adapter prelude). Transform itself is NOT verified — only that all
3 Chain-B locations agree amongst themselves.

Exit codes:
  0 = all in sync
  1 = drift detected
  2 = path/config error

Usage:
  verify-codex-skill-mirror-sync.py                    # human-readable report
  verify-codex-skill-mirror-sync.py --quiet            # suppress output if synced
  verify-codex-skill-mirror-sync.py --fast             # mtime-only check (faster)
  verify-codex-skill-mirror-sync.py --json             # machine-readable
  verify-codex-skill-mirror-sync.py --skill blueprint  # check one skill only

Environment:
  REPO_ROOT     — project root (default: current dir via `git rev-parse`)
  VGFLOW_REPO   — path to vgflow-repo clone (optional sibling check)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

# v2.5.1 pinned set — the 7 contract-enforced commands.
# Additional skills (bootstrap, doctor, etc.) also mirrored but not pinned.
# If new skill added to .claude/commands/vg/, auto-discover via glob.
CONTRACTED_SKILLS = (
    "accept", "blueprint", "build", "review", "scope", "specs", "test",
)


def _sha256(path: Path, normalize_newlines: bool = True) -> Optional[str]:
    """Return hex SHA256 of file content, or None if missing.

    Normalize line endings (CRLF/CR → LF) before hashing — on Windows,
    git checkout may autocrlf convert, making byte-identical source
    files hash differently across RTB (LF) and vgflow-repo (CRLF).
    Functional content is the same; line endings are cosmetic.
    """
    try:
        data = path.read_bytes()
        if normalize_newlines:
            data = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        return hashlib.sha256(data).hexdigest()
    except (FileNotFoundError, PermissionError):
        return None


def _resolve_repo_root() -> Path:
    """Get project root via git, fallback to cwd."""
    env = os.environ.get("REPO_ROOT")
    if env:
        return Path(env).resolve()
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL, text=True,
        )
        return Path(out.strip()).resolve()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return Path.cwd().resolve()


def _resolve_vgflow_repo(repo_root: Path) -> Optional[Path]:
    """Locate vgflow-repo via VGFLOW_REPO env OR sibling-dir heuristic."""
    env = os.environ.get("VGFLOW_REPO")
    if env:
        p = Path(env).resolve()
        return p if (p / "sync.sh").exists() else None
    for candidate in (
        repo_root.parent / "vgflow-repo",
        Path.home() / "Workspace" / "Messi" / "Code" / "vgflow-repo",
    ):
        if (candidate / "sync.sh").exists():
            return candidate.resolve()
    return None


def _resolve_codex_global() -> Path:
    """~/.codex/skills/ — Codex CLI reads here for global skills."""
    return Path.home() / ".codex" / "skills"


def _discover_skill_names(claude_commands: Path) -> list[str]:
    """List all .md files in .claude/commands/vg/ (strip .md suffix)."""
    if not claude_commands.is_dir():
        return list(CONTRACTED_SKILLS)
    names = []
    for f in sorted(claude_commands.glob("*.md")):
        # Skip internal staging files
        name = f.stem
        if name.startswith("_"):
            continue
        names.append(name)
    # Union: ensure all contract-pinned skills present even if one got deleted
    seen = set(names)
    for req in CONTRACTED_SKILLS:
        if req not in seen:
            names.append(req)
    return names


def _check_chain_a_claude(
    skill: str,
    repo_root: Path,
    vgflow_repo: Optional[Path],
) -> dict:
    """Chain A = Claude source path. source must match vgflow-repo mirror."""
    rtb_path = repo_root / ".claude" / "commands" / "vg" / f"{skill}.md"
    rtb_hash = _sha256(rtb_path)

    result = {
        "chain": "A",
        "skill": skill,
        "rtb_source": {
            "path": str(rtb_path),
            "sha256": rtb_hash,
            "exists": rtb_hash is not None,
        },
    }

    if vgflow_repo:
        vgflow_path = vgflow_repo / "commands" / "vg" / f"{skill}.md"
        vgflow_hash = _sha256(vgflow_path)
        result["vgflow_mirror"] = {
            "path": str(vgflow_path),
            "sha256": vgflow_hash,
            "exists": vgflow_hash is not None,
        }
        if rtb_hash and vgflow_hash:
            result["in_sync"] = rtb_hash == vgflow_hash
        else:
            result["in_sync"] = False
    else:
        result["vgflow_mirror"] = None
        result["in_sync"] = True  # nothing to compare
    return result


def _check_chain_b_codex(
    skill: str,
    repo_root: Path,
    vgflow_repo: Optional[Path],
) -> dict:
    """Chain B = Codex transformed path. All 3 mirrors must agree."""
    local_path = repo_root / ".codex" / "skills" / f"vg-{skill}" / "SKILL.md"
    global_path = _resolve_codex_global() / f"vg-{skill}" / "SKILL.md"

    local_hash = _sha256(local_path)
    global_hash = _sha256(global_path)

    result = {
        "chain": "B",
        "skill": skill,
        "local_codex": {
            "path": str(local_path),
            "sha256": local_hash,
            "exists": local_hash is not None,
        },
        "global_codex": {
            "path": str(global_path),
            "sha256": global_hash,
            "exists": global_hash is not None,
        },
    }

    if vgflow_repo:
        vgflow_codex_path = (
            vgflow_repo / "codex-skills" / f"vg-{skill}" / "SKILL.md"
        )
        vgflow_codex_hash = _sha256(vgflow_codex_path)
        result["vgflow_codex"] = {
            "path": str(vgflow_codex_path),
            "sha256": vgflow_codex_hash,
            "exists": vgflow_codex_hash is not None,
        }
        mirrors = [vgflow_codex_hash, local_hash, global_hash]
    else:
        result["vgflow_codex"] = None
        mirrors = [local_hash, global_hash]

    # Strict parity: every expected mirror must exist AND all must hash
    # identically. Missing ≠ "no drift" — missing IS drift.
    all_present = all(h is not None for h in mirrors)
    all_match = len(set(h for h in mirrors if h is not None)) <= 1
    result["in_sync"] = all_present and all_match
    return result


def _format_human_report(results: list[dict], quiet: bool) -> str:
    """Build human-readable drift report."""
    drift = [r for r in results if not r.get("in_sync", False)]
    if not drift and quiet:
        return ""

    lines = []
    if drift:
        lines.append(f"⛔ Codex skill mirror drift: {len(drift)} skill(s) out of sync\n")
        lines.append(f"{'skill':<12} {'chain':<6} {'status':<20}")
        lines.append(f"{'-'*12} {'-'*6} {'-'*20}")
        for r in drift:
            skill = r["skill"]
            chain = r["chain"]
            # Identify which mirror drifted
            tags = []
            if r.get("chain") == "A":
                src = r["rtb_source"]
                mir = r.get("vgflow_mirror")
                if src and not src["exists"]:
                    tags.append("RTB_MISSING")
                if mir and not mir["exists"]:
                    tags.append("VGFLOW_MISSING")
                if (src and mir and src["sha256"] and mir["sha256"]
                        and src["sha256"] != mir["sha256"]):
                    tags.append("RTB_vs_VGFLOW_DRIFT")
            else:  # chain B
                loc = r["local_codex"]
                glb = r["global_codex"]
                vgc = r.get("vgflow_codex")
                if not loc["exists"]:
                    tags.append("LOCAL_MISSING")
                if not glb["exists"]:
                    tags.append("GLOBAL_MISSING")
                if vgc and not vgc["exists"]:
                    tags.append("VGFLOW_CODEX_MISSING")
                hashes = set()
                for m in (loc, glb, vgc):
                    if m and m["exists"]:
                        hashes.add(m["sha256"])
                if len(hashes) > 1:
                    tags.append("CODEX_MIRROR_DRIFT")
            lines.append(f"{skill:<12} {chain:<6} {','.join(tags) or 'UNKNOWN'}")

        lines.append("")
        lines.append("Fix:")
        lines.append("  DEV_ROOT=\"$PWD\" bash ../vgflow-repo/sync.sh")
        lines.append("")
    else:
        total = len(results)
        if not quiet:
            lines.append(f"✓ Codex skill mirror sync OK — {total} checks passed")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--quiet", action="store_true",
                    help="suppress output when fully synced")
    ap.add_argument("--json", action="store_true",
                    help="emit JSON for programmatic consumers")
    ap.add_argument("--fast", action="store_true",
                    help="mtime-only check (skip sha256 compute)")
    ap.add_argument("--skill", default=None,
                    help="check one skill only (by name, e.g. 'blueprint')")
    ap.add_argument("--skip-vgflow", action="store_true",
                    help="don't check vgflow-repo upstream")
    args = ap.parse_args()

    repo_root = _resolve_repo_root()
    claude_commands = repo_root / ".claude" / "commands" / "vg"

    vgflow_repo = None if args.skip_vgflow else _resolve_vgflow_repo(repo_root)

    if args.skill:
        skills_to_check = [args.skill]
    else:
        skills_to_check = _discover_skill_names(claude_commands)

    results = []
    for skill in skills_to_check:
        results.append(_check_chain_a_claude(skill, repo_root, vgflow_repo))
        results.append(_check_chain_b_codex(skill, repo_root, vgflow_repo))

    drift_count = sum(1 for r in results if not r.get("in_sync", False))

    if args.json:
        print(json.dumps({
            "repo_root": str(repo_root),
            "vgflow_repo": str(vgflow_repo) if vgflow_repo else None,
            "skills_checked": len(skills_to_check),
            "drift_count": drift_count,
            "results": results,
        }, indent=2))
    else:
        out = _format_human_report(results, args.quiet)
        if out:
            print(out)

    return 1 if drift_count > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
