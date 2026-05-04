"""block_context — resolve skill_path / command / step / hook_source for
block payload auto-attribution.

Inputs (all optional; resolver does best-effort):
  - run_id (preferred): query events.db for active run's command + recent step events
  - hook_name: caller hook script name (set by bash via $0 or Python via __file__)

Output: dict with keys subset of:
  {skill_path, command, phase, step, hook_source}

Missing keys = couldn't resolve (graceful degradation; never raises).
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

EVENTS_DB_REL = ".vg/events.db"

COMMAND_TO_SKILL = {
    "vg:build": "commands/vg/build.md",
    "vg:blueprint": "commands/vg/blueprint.md",
    "vg:review": "commands/vg/review.md",
    "vg:test": "commands/vg/test.md",
    "vg:accept": "commands/vg/accept.md",
    "vg:scope": "commands/vg/scope.md",
    "vg:specs": "commands/vg/specs.md",
    "vg:roam": "commands/vg/roam.md",
    "vg:debug": "commands/vg/debug.md",
    "vg:amend": "commands/vg/amend.md",
    "vg:deploy": "commands/vg/deploy.md",
    "vg:roadmap": "commands/vg/roadmap.md",
    "vg:project": "commands/vg/project.md",
}

STEP_TO_REF = {
    ("vg:build", "5_post_execution"): "commands/vg/_shared/build/post-execution-overview.md",
    ("vg:build", "4_waves"): "commands/vg/_shared/build/waves-overview.md",
    ("vg:build", "6_crossai"): "commands/vg/_shared/build/crossai-loop.md",
    ("vg:build", "8_5_in_scope_fix_loop"): "commands/vg/_shared/build/in-scope-fix-loop.md",
    ("vg:build", "12_5_pre_test_gate"): "commands/vg/_shared/build/pre-test-gate.md",
    ("vg:accept", "3_uat_checklist"): "commands/vg/_shared/accept/uat/checklist-build/overview.md",
    ("vg:accept", "5_interactive_uat"): "commands/vg/_shared/accept/uat/interactive.md",
    ("vg:accept", "7_post_accept_actions"): "commands/vg/_shared/accept/cleanup/overview.md",
}


def _resolve_db(repo_root: str | Path | None) -> Path:
    if repo_root:
        return Path(repo_root) / EVENTS_DB_REL
    env = os.environ.get("VG_REPO_ROOT")
    if env:
        return Path(env) / EVENTS_DB_REL
    p = Path.cwd()
    for cand in [p, *p.parents]:
        if (cand / ".git").exists():
            return cand / EVENTS_DB_REL
    return p / EVENTS_DB_REL


def resolve(run_id: str | None = None,
            hook_name: str | None = None,
            repo_root: str | Path | None = None) -> dict:
    """Return attribution dict; never raises."""
    out: dict = {}
    if hook_name:
        out["hook_source"] = Path(hook_name).name

    if not run_id:
        return out

    db = _resolve_db(repo_root)
    if not db.exists():
        return out

    conn = None
    try:
        conn = sqlite3.connect(str(db), timeout=2.0)
        # Get command + phase from runs row (best-effort — schema varies)
        try:
            row = conn.execute(
                "SELECT command, phase FROM runs WHERE run_id = ? LIMIT 1",
                (run_id,),
            ).fetchone()
            if row:
                if row[0]:
                    out["command"] = row[0]
                    skill = COMMAND_TO_SKILL.get(row[0])
                    if skill:
                        out["skill_path"] = skill
                if row[1]:
                    out["phase"] = row[1]
        except sqlite3.Error:
            pass

        # Get most recent step-active event for this run
        try:
            step_row = conn.execute(
                "SELECT json_extract(payload_json, '$.step') FROM events "
                "WHERE run_id = ? AND event_type LIKE '%.step_active' "
                "ORDER BY id DESC LIMIT 1",
                (run_id,),
            ).fetchone()
            if step_row and step_row[0]:
                out["step"] = step_row[0]
                if "command" in out:
                    ref = STEP_TO_REF.get((out["command"], out["step"]))
                    if ref:
                        out["skill_path"] = ref
        except sqlite3.Error:
            pass
    except sqlite3.Error:
        pass
    finally:
        if conn is not None:
            try:
                conn.close()
            except sqlite3.Error:
                pass
    return out
