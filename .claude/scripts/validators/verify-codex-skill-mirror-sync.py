#!/usr/bin/env python3
"""Validate Codex skill mirror sync across source, local, and global copies.

This validator is layout-aware:

* Source repository mode:
  commands/vg + skills/* -> codex-skills -> .codex/skills -> ~/.codex/skills

* Installed project mode:
  .claude/commands/vg -> $VGFLOW_REPO/codex-skills -> .codex/skills
  -> ~/.codex/skills

It checks mirror byte parity after newline normalization. Functional
source-to-Codex body equivalence is handled by verify-codex-mirror-equivalence.py.
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

CONTRACTED_SKILLS = (
    "accept",
    "blueprint",
    "build",
    "review",
    "scope",
    "specs",
    "test",
)


def _sha256(path: Path, normalize_newlines: bool = True) -> Optional[str]:
    try:
        data = path.read_bytes()
        if normalize_newlines:
            data = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        return hashlib.sha256(data).hexdigest()
    except (FileNotFoundError, PermissionError):
        return None


def _file_manifest(root: Path) -> Optional[dict[str, str]]:
    if not root.is_dir():
        return None
    manifest: dict[str, str] = {}
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        digest = _sha256(path)
        if digest is None:
            return None
        manifest[rel] = digest
    return manifest


def _resolve_repo_root() -> Path:
    env = os.environ.get("REPO_ROOT") or os.environ.get("VG_REPO_ROOT")
    if env:
        return Path(env).resolve()
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return Path(out.strip()).resolve()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return Path.cwd().resolve()


def _is_source_repo(root: Path) -> bool:
    return (root / "commands" / "vg").is_dir() and (root / "codex-skills").is_dir()


def _resolve_vgflow_repo(repo_root: Path) -> Optional[Path]:
    env = os.environ.get("VGFLOW_REPO")
    if env:
        p = Path(env).resolve()
        return p if (p / "codex-skills").is_dir() else None
    for candidate in (
        repo_root.parent / "vgflow-repo",
        Path.home() / "Workspace" / "Messi" / "Code" / "vgflow-repo",
    ):
        if (candidate / "codex-skills").is_dir():
            return candidate.resolve()
    return None


def _global_codex_skills() -> Path:
    return Path.home() / ".codex" / "skills"


def _source_commands_dir(repo_root: Path, source_repo: bool) -> Path:
    if source_repo:
        return repo_root / "commands" / "vg"
    return repo_root / ".claude" / "commands" / "vg"


def _source_support_dir(repo_root: Path, source_repo: bool) -> Path:
    if source_repo:
        return repo_root / "skills"
    return repo_root / ".claude" / "skills"


def _authoritative_codex_dir(
    repo_root: Path,
    source_repo: bool,
    vgflow_repo: Optional[Path],
) -> Path:
    if source_repo:
        return repo_root / "codex-skills"
    if vgflow_repo:
        return vgflow_repo / "codex-skills"
    return repo_root / ".codex" / "skills"


def _discover_skill_names(
    source_commands: Path,
    authoritative_codex: Path,
) -> list[str]:
    names: list[str] = []
    if source_commands.is_dir():
        for f in sorted(source_commands.glob("*.md")):
            name = f.stem
            if name.startswith("_") or name.endswith("-insert"):
                continue
            names.append(name)

    if authoritative_codex.is_dir():
        for skill_dir in sorted(authoritative_codex.glob("vg-*")):
            if (skill_dir / "SKILL.md").is_file():
                name = skill_dir.name.removeprefix("vg-")
                if (source_commands / f"{name}.md").is_file() or name in CONTRACTED_SKILLS:
                    names.append(name)

    for req in CONTRACTED_SKILLS:
        names.append(req)

    seen: set[str] = set()
    deduped: list[str] = []
    for name in names:
        if name not in seen:
            seen.add(name)
            deduped.append(name)
    return deduped


def _discover_support_skill_names(support_dir: Path) -> list[str]:
    if not support_dir.is_dir():
        return []
    return sorted(
        path.name
        for path in support_dir.iterdir()
        if path.is_dir() and (path / "SKILL.md").is_file()
    )


def _check_chain_a(
    skill: str,
    repo_root: Path,
    source_repo: bool,
    vgflow_repo: Optional[Path],
) -> dict:
    source_commands = _source_commands_dir(repo_root, source_repo)
    local_path = source_commands / f"{skill}.md"
    local_hash = _sha256(local_path)

    result = {
        "chain": "A",
        "skill": skill,
        "local_source": {
            "path": str(local_path),
            "sha256": local_hash,
            "exists": local_hash is not None,
        },
        "upstream_source": None,
        "in_sync": local_hash is not None,
    }

    if not source_repo and vgflow_repo:
        upstream_path = vgflow_repo / "commands" / "vg" / f"{skill}.md"
        upstream_hash = _sha256(upstream_path)
        result["upstream_source"] = {
            "path": str(upstream_path),
            "sha256": upstream_hash,
            "exists": upstream_hash is not None,
        }
        result["in_sync"] = (
            local_hash is not None
            and upstream_hash is not None
            and local_hash == upstream_hash
        )

    return result


def _check_support_chain_a(
    skill: str,
    repo_root: Path,
    source_repo: bool,
    vgflow_repo: Optional[Path],
) -> dict:
    support_dir = _source_support_dir(repo_root, source_repo)
    local_path = support_dir / skill / "SKILL.md"
    local_hash = _sha256(local_path)

    result = {
        "chain": "A",
        "kind": "support",
        "skill": skill,
        "local_source": {
            "path": str(local_path),
            "sha256": local_hash,
            "exists": local_hash is not None,
        },
        "upstream_source": None,
        "in_sync": local_hash is not None,
    }

    if not source_repo and vgflow_repo:
        upstream_path = vgflow_repo / "skills" / skill / "SKILL.md"
        upstream_hash = _sha256(upstream_path)
        result["upstream_source"] = {
            "path": str(upstream_path),
            "sha256": upstream_hash,
            "exists": upstream_hash is not None,
        }
        result["in_sync"] = (
            local_hash is not None
            and upstream_hash is not None
            and local_hash == upstream_hash
        )

    return result


def _check_chain_b(
    skill: str,
    repo_root: Path,
    authoritative_codex: Path,
    skip_global: bool,
    source_repo: bool,
    codex_name: Optional[str] = None,
) -> dict:
    codex_name = codex_name or f"vg-{skill}"
    canonical_dir = authoritative_codex / codex_name
    local_dir = repo_root / ".codex" / "skills" / codex_name
    global_dir = _global_codex_skills() / codex_name

    canonical_path = canonical_dir / "SKILL.md"
    local_path = local_dir / "SKILL.md"
    global_path = global_dir / "SKILL.md"

    mirrors = [
        (
            "canonical_codex",
            canonical_path,
            _sha256(canonical_path),
            canonical_dir,
            _file_manifest(canonical_dir),
        )
    ]
    local_root = repo_root / ".codex" / "skills"
    if local_root.is_dir() or not source_repo:
        mirrors.append(
            ("local_codex", local_path, _sha256(local_path), local_dir, _file_manifest(local_dir))
        )
    if not skip_global:
        mirrors.append(
            ("global_codex", global_path, _sha256(global_path), global_dir, _file_manifest(global_dir))
        )

    result = {
        "chain": "B",
        "skill": skill,
        "codex_name": codex_name,
        "in_sync": False,
    }
    hashes = []
    manifests = []
    for key, path, digest, skill_dir, manifest in mirrors:
        result[key] = {
            "path": str(path),
            "sha256": digest,
            "exists": digest is not None,
            "dir": str(skill_dir),
            "dir_exists": skill_dir.is_dir(),
            "file_count": len(manifest) if manifest is not None else None,
        }
        hashes.append(digest)
        manifests.append(manifest)

    all_present = all(digest is not None for digest in hashes)
    all_match = len({digest for digest in hashes if digest is not None}) <= 1
    all_manifests_present = all(manifest is not None for manifest in manifests)
    manifest_match = (
        len(
            {
                json.dumps(manifest, sort_keys=True)
                for manifest in manifests
                if manifest is not None
            }
        )
        <= 1
    )
    result["manifest_drift"] = all_manifests_present and not manifest_match
    result["in_sync"] = all_present and all_match and all_manifests_present and manifest_match
    return result


def _format_human_report(results: list[dict], quiet: bool, source_repo: bool) -> str:
    drift = [r for r in results if not r.get("in_sync", False)]
    if not drift and quiet:
        return ""

    lines: list[str] = []
    if not drift:
        lines.append(f"OK: Codex skill mirror sync clean ({len(results)} checks)")
        return "\n".join(lines)

    lines.append(f"DRIFT: Codex skill mirror drift in {len(drift)} check(s)")
    lines.append(f"{'skill':<18} {'chain':<6} status")
    lines.append(f"{'-'*18} {'-'*6} {'-'*30}")

    for r in drift:
        tags: list[str] = []
        if r["chain"] == "A":
            local = r["local_source"]
            upstream = r.get("upstream_source")
            if not local["exists"]:
                tags.append("SOURCE_MISSING" if source_repo else "RTB_MISSING")
            if upstream and not upstream["exists"]:
                tags.append("VGFLOW_MISSING")
            if (
                upstream
                and local["sha256"]
                and upstream["sha256"]
                and local["sha256"] != upstream["sha256"]
            ):
                tags.append("SOURCE_vs_VGFLOW_DRIFT" if source_repo else "RTB_vs_VGFLOW_DRIFT")
        else:
            for key, tag in (
                ("canonical_codex", "CANONICAL_CODEX_MISSING"),
                ("local_codex", "LOCAL_MISSING"),
                ("global_codex", "GLOBAL_MISSING"),
            ):
                item = r.get(key)
                if item and not item["exists"]:
                    tags.append(tag)
            hashes = {
                item["sha256"]
                for key in ("canonical_codex", "local_codex", "global_codex")
                if (item := r.get(key)) and item["exists"]
            }
            if len(hashes) > 1 or r.get("manifest_drift"):
                tags.append("CODEX_MIRROR_DRIFT")
        lines.append(f"{r['skill']:<18} {r['chain']:<6} {','.join(tags) or 'UNKNOWN'}")

    lines.append("")
    lines.append("Fix: run `bash sync.sh` from vgflow-repo or `/vg:sync` from an installed project.")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--fast", action="store_true", help="accepted for compatibility")
    ap.add_argument("--skill")
    ap.add_argument("--skip-vgflow", action="store_true")
    ap.add_argument("--skip-global", action="store_true")
    ap.add_argument("--phase", help="orchestrator-injected; ignored")
    args = ap.parse_args()

    repo_root = _resolve_repo_root()
    source_repo = _is_source_repo(repo_root)
    vgflow_repo = None if (args.skip_vgflow or source_repo) else _resolve_vgflow_repo(repo_root)
    source_commands = _source_commands_dir(repo_root, source_repo)
    authoritative_codex = _authoritative_codex_dir(repo_root, source_repo, vgflow_repo)

    support_dir = _source_support_dir(repo_root, source_repo)
    support_skills = _discover_support_skill_names(support_dir)

    if args.skill:
        requested = args.skill.removeprefix("$")
        command_candidate = requested.removeprefix("vg-")
        if (source_commands / f"{command_candidate}.md").is_file():
            skills = [command_candidate]
            support_skills = []
        elif (support_dir / requested / "SKILL.md").is_file():
            skills = []
            support_skills = [requested]
        else:
            skills = [command_candidate]
            support_skills = []
    else:
        skills = _discover_skill_names(source_commands, authoritative_codex)

    results: list[dict] = []
    for skill in skills:
        results.append(_check_chain_a(skill, repo_root, source_repo, vgflow_repo))
        results.append(
            _check_chain_b(
                skill,
                repo_root,
                authoritative_codex,
                args.skip_global,
                source_repo,
            )
        )

    for skill in support_skills:
        results.append(_check_support_chain_a(skill, repo_root, source_repo, vgflow_repo))
        results.append(
            _check_chain_b(
                skill,
                repo_root,
                authoritative_codex,
                args.skip_global,
                source_repo,
                codex_name=skill,
            )
        )

    drift_count = sum(1 for r in results if not r.get("in_sync", False))

    if args.json:
        print(
            json.dumps(
                {
                    "validator": "verify-codex-skill-mirror-sync",
                    "verdict": "PASS" if drift_count == 0 else "WARN",
                    "repo_root": str(repo_root),
                    "source_repo": source_repo,
                    "vgflow_repo": str(vgflow_repo) if vgflow_repo else None,
                    "authoritative_codex": str(authoritative_codex),
                    "skills_checked": len(skills) + len(support_skills),
                    "drift_count": drift_count,
                    "results": results,
                },
                indent=2,
            )
        )
    else:
        out = _format_human_report(results, args.quiet, source_repo)
        if out:
            print(out)

    return 1 if drift_count > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
