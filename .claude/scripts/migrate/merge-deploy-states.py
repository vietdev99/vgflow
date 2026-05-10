#!/usr/bin/env python3
"""v2.85.0 Stage 7.1 — merge per-phase DEPLOY-STATE.json into project STATE.json.

v2.x layout: each phase wrote its own `${PHASE_DIR}/DEPLOY-STATE.json`.
v3.0.0 layout: single project-level `.vg/deploy/STATE.json`.

This helper consolidates v2.x state during migration:
  1. Walk `.vg/phases/*/DEPLOY-STATE.json`
  2. For each env, keep the entry with the latest `deployed_at` timestamp
  3. Per-phase `preferred_env_for` → project-level
     `preferred_env_for_phase[<phase>]`
  4. Write to `.vg/deploy/STATE.json` via `deploy.state.DeployState`
     (atomic write, schema-validated shape)

USAGE
  python3 merge-deploy-states.py --project-root .  [--dry-run] [--backup]

EXIT CODES
  0  ok (state written or dry-run summary)
  1  bad args
  2  no per-phase state files found (nothing to merge — not an error,
     but caller may want to skip the rest of migration)
  3  write failed
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _add_project_to_path(project_root: Path) -> None:
    """Make `deploy.state` importable. Probe order:
    1. project's .claude/scripts/ (project-local install)
    2. project's scripts/ (canonical / dev clone)
    3. ~/.vgflow/scripts/ (v3 global install)
    4. This script's parent's parent (e.g., scripts/migrate/ → scripts/)
       — handles the case where the migration helper is invoked from a
       repo that has the v2.85.0+ helpers but the target project doesn't
       yet."""
    candidates = [
        project_root / ".claude" / "scripts",
        project_root / "scripts",
        Path.home() / ".vgflow" / "scripts",
        Path(__file__).resolve().parent.parent,
    ]
    for c in candidates:
        if (c / "deploy" / "state.py").exists():
            sys.path.insert(0, str(c))
            return


def _collect_phase_states(project_root: Path) -> dict[str, dict]:
    """Walk .vg/phases/*/DEPLOY-STATE.json. Returns phase→state-dict."""
    out: dict[str, dict] = {}
    phases_dir = project_root / ".vg" / "phases"
    if not phases_dir.is_dir():
        return out
    for state_file in sorted(phases_dir.glob("*/DEPLOY-STATE.json")):
        phase = state_file.parent.name
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(
                f"⚠ skipping {state_file}: {e}",
                file=sys.stderr,
            )
            continue
        if not isinstance(data, dict):
            continue
        out[phase] = data
    return out


def _merge_envs(per_phase: dict[str, dict]) -> tuple[dict[str, dict], dict[str, str]]:
    """Latest deployed_at wins per env. Returns (envs, preferred_env_for_phase)."""
    envs: dict[str, dict] = {}
    preferred: dict[str, str] = {}

    for phase, state in per_phase.items():
        # Per-phase preferred_env_for → project-level preferred_env_for_phase[phase]
        pref = state.get("preferred_env_for")
        if pref and isinstance(pref, str):
            preferred[phase] = pref

        deployed = state.get("deployed") or {}
        if not isinstance(deployed, dict):
            continue
        for env, entry in deployed.items():
            if not isinstance(entry, dict):
                continue
            ts = entry.get("deployed_at") or ""
            existing = envs.get(env)
            if existing and (existing.get("deployed_at") or "") >= ts:
                continue
            new_entry = dict(entry)
            # Annotate phase_context if not already present
            new_entry.setdefault("phase_context", phase)
            envs[env] = new_entry

    return envs, preferred


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--project-root", default=".", help="Project root (cwd default)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print merged state to stdout; do NOT write STATE.json")
    ap.add_argument("--backup", action="store_true",
                    help="If STATE.json exists, copy to .bak.<epoch> before write")
    args = ap.parse_args()

    project = Path(args.project_root).resolve()
    _add_project_to_path(project)
    try:
        from deploy.state import DeployState  # type: ignore[import-not-found]
    except ImportError:
        print(
            "⛔ cannot import deploy.state — install vgflow first or run from a project with .claude/scripts/",
            file=sys.stderr,
        )
        return 1

    per_phase = _collect_phase_states(project)
    if not per_phase:
        print(
            f"no per-phase DEPLOY-STATE.json found under {project}/.vg/phases/",
            file=sys.stderr,
        )
        return 2

    envs, preferred = _merge_envs(per_phase)

    if args.dry_run:
        out = {
            "schema_version": 1,
            "envs": envs,
            "preferred_env_for_phase": preferred,
            "active_environments": list(envs.keys()),
        }
        print(json.dumps(out, indent=2, sort_keys=True))
        print(f"\n# {len(per_phase)} phase state(s) merged → {len(envs)} env(s)", file=sys.stderr)
        return 0

    state = DeployState.load(project)
    for env, entry in envs.items():
        state.set_env(
            env,
            sha=entry.get("sha", ""),
            deployed_at=entry.get("deployed_at", ""),
            phase_context=entry.get("phase_context"),
            previous_sha=entry.get("previous_sha"),
            health=entry.get("health"),
            deploy_duration_sec=entry.get("deploy_duration_sec"),
            deploy_commands=entry.get("deploy_commands"),
            deployer=entry.get("deployer"),
            release_tag=entry.get("release_tag"),
        )
    for phase, env in preferred.items():
        if env in envs:
            state.set_preferred_env_for_phase(phase, env)

    try:
        path = state.save(backup=args.backup)
    except OSError as e:
        print(f"⛔ write failed: {e}", file=sys.stderr)
        return 3

    print(
        f"✓ merged {len(per_phase)} phase state(s) → {path}\n"
        f"  envs:                    {len(envs)} ({', '.join(envs)})\n"
        f"  preferred_env_for_phase: {len(preferred)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
