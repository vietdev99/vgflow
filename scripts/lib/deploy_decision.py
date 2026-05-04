"""deploy_decision — policy layer reading ENV-BASELINE.md.

Per-profile default policy:
  web-fullstack | web-backend-only → recommend sandbox
  web-frontend-only                → recommend staging (no sandbox)
  mobile                           → recommend internal-test
  cli-tool | library               → recommend skip (no deploy needed)

Phase-changes hint optional: {"frontend": bool, "backend": bool, "schema": bool}.
If schema changed, recommend staging (need real DB).

Codex Round 2 Correction B: detect_phase_changes() reads task capsules,
build progress, then git diff for deterministic file evidence (not LLM
keyword grep on PLAN).
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

PROFILE_RE = re.compile(r"\*\*Profile:\*\*\s*(\S+)")
ENV_ROW_RE = re.compile(r"^\|\s*([a-z][a-z0-9-]*)\s*\|", re.MULTILINE)


def _parse_env_baseline(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    profile_match = PROFILE_RE.search(text)
    profile = profile_match.group(1) if profile_match else "unknown"

    matrix_section = re.search(r"##\s+Environment matrix(.+?)(?=^##\s|\Z)", text, re.MULTILINE | re.DOTALL)
    envs: list[str] = []
    if matrix_section:
        for m in ENV_ROW_RE.finditer(matrix_section.group(1)):
            name = m.group(1).strip()
            if name not in {"env", "---"} and name not in envs:
                envs.append(name)
    return {"profile": profile, "envs": envs}


_PROFILE_DEFAULT_ENV = {
    "web-fullstack": "sandbox",
    "web-backend-only": "sandbox",
    "web-frontend-only": "staging",
    "mobile": "internal-test",
    "mobile-native": "internal-test",
    "mobile-cross": "internal-test",
    "cli-tool": "skip",
    "library": "skip",
}


def detect_phase_changes(phase_dir: Path, repo_root: Path = Path(".")) -> dict[str, bool]:
    """Detect what kinds of changes the phase introduced. Deterministic file evidence.

    Order of authority (Codex round 2):
      1. Task capsules: `${PHASE_DIR}/.task-capsules/task-NN.capsule.json` `edits_files`
      2. Build progress: `${PHASE_DIR}/.build-progress.json` `tasks[].files_touched`
      3. git diff: `git diff --name-only HEAD~1..HEAD` (best-effort)
    """
    flags = {"frontend": False, "backend": False, "schema": False}
    paths_touched: set[str] = set()

    capsule_dir = phase_dir / ".task-capsules"
    if capsule_dir.exists():
        for cap in capsule_dir.glob("task-*.capsule.json"):
            try:
                data = json.loads(cap.read_text(encoding="utf-8"))
                for f in data.get("edits_files", []) + [data.get("edits_endpoint", "")]:
                    if f:
                        paths_touched.add(f)
            except (OSError, ValueError):
                continue

    progress = phase_dir / ".build-progress.json"
    if progress.exists() and not paths_touched:
        try:
            data = json.loads(progress.read_text(encoding="utf-8"))
            for t in data.get("tasks", []):
                paths_touched.update(t.get("files_touched", []))
        except (OSError, ValueError):
            pass

    if not paths_touched:
        try:
            r = subprocess.run(["git", "diff", "--name-only", "HEAD~1..HEAD"],
                       cwd=repo_root, capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                paths_touched.update(p for p in r.stdout.splitlines() if p.strip())
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    for p in paths_touched:
        pl = p.lower()
        if any(x in pl for x in ("apps/web/", "apps/frontend/", "src/components/", ".tsx", ".jsx", "/pages/", "/views/")):
            flags["frontend"] = True
        if any(x in pl for x in ("apps/api/", "apps/backend/", "src/server/", "/handlers/", "/routes/", "/controllers/")):
            flags["backend"] = True
        if any(x in pl for x in ("/migrations/", "/schema.sql", "schema.prisma", "models.py", "/db/schema/", ".sql", "alembic/")):
            flags["schema"] = True

    return flags


def propose_target(
    env_baseline_path: Path,
    phase_changes: dict[str, bool] | None = None,
    phase_dir: Path | None = None,
) -> dict[str, Any]:
    """Return {recommended_env, available_envs, profile, reason, confidence}.

    If `phase_changes` is None and `phase_dir` is given, deterministically
    detects changes via detect_phase_changes (Codex round 2 Correction B).
    """
    if not env_baseline_path.exists():
        return {
            "recommended_env": "skip",
            "available_envs": [],
            "profile": "unknown",
            "reason": "ENV-BASELINE.md missing — run /vg:project --update --env-baseline",
            "confidence": 0.0,
        }

    if phase_changes is None and phase_dir is not None:
        phase_changes = detect_phase_changes(phase_dir)

    parsed = _parse_env_baseline(env_baseline_path)
    profile = parsed["profile"]
    envs = parsed["envs"]
    default_env = _PROFILE_DEFAULT_ENV.get(profile, "skip")

    if phase_changes and phase_changes.get("schema") and "staging" in envs:
        return {
            "recommended_env": "staging",
            "available_envs": envs,
            "profile": profile,
            "reason": "schema change requires real DB — staging recommended",
            "confidence": 0.85,
        }

    if default_env != "skip" and default_env not in envs:
        candidates = [e for e in envs if e not in {"dev", "prod"}]
        if candidates:
            return {
                "recommended_env": candidates[0],
                "available_envs": envs,
                "profile": profile,
                "reason": f"profile default {default_env!r} unavailable — using {candidates[0]!r}",
                "confidence": 0.6,
            }

    return {
        "recommended_env": default_env,
        "available_envs": envs,
        "profile": profile,
        "reason": f"profile {profile!r} default policy",
        "confidence": 0.8 if default_env in envs else 0.4,
    }
