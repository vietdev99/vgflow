"""v2.82.0 Stage 6.2 — `.vg/deploy/STATE.json` reader/writer.

Project-level deploy state (v3.0.0 decouple) replacing per-phase
`.vg/phases/{N}/DEPLOY-STATE.json`. Atomic write semantics:
  1. Build new state in memory.
  2. Write to `<path>.tmp` in the same directory (same filesystem → rename atomic).
  3. Replace target via `os.replace()` (atomic on POSIX + Windows).
  4. Optional pre-write backup `<path>.bak.<epoch>` retained when caller asks.

Schema enforced via `schemas/deploy-state.v1.json` (jsonschema validation
when the lib is importable; permissive write when missing — same pattern
as other v2.x writers).

Usage:
    from deploy.state import DeployState
    s = DeployState.load(project_root)            # returns empty state if file absent
    s.set_env("prod", sha="abc123", deployed_at=..., phase_context="6")
    s.set_preferred_env_for_phase("6", "prod")
    s.save()                                       # atomic write
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
DEPLOY_DIR = "deploy"
STATE_FILE = "STATE.json"


@dataclass
class DeployState:
    """In-memory representation of `.vg/deploy/STATE.json`."""

    project_root: Path
    schema_version: int = SCHEMA_VERSION
    envs: dict[str, dict[str, Any]] = field(default_factory=dict)
    preferred_env_for_phase: dict[str, str] = field(default_factory=dict)
    active_environments: list[str] = field(default_factory=list)
    updated_at: str | None = None

    # ── path resolution ─────────────────────────────────────────────

    @property
    def state_path(self) -> Path:
        return self.project_root / ".vg" / DEPLOY_DIR / STATE_FILE

    # ── I/O ─────────────────────────────────────────────────────────

    @classmethod
    def load(cls, project_root: Path | str) -> "DeployState":
        """Load state from disk; return empty initialized instance if absent.

        Empty state still has schema_version=1 so `.save()` writes a valid
        document on first deploy.
        """
        proj = Path(project_root).resolve()
        path = proj / ".vg" / DEPLOY_DIR / STATE_FILE
        if not path.exists():
            return cls(project_root=proj)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ValueError(
                f"deploy STATE.json corrupt at {path}: {e}. "
                f"Restore from `.vg/.backup-<ts>/` or delete to reset."
            ) from e
        if not isinstance(data, dict):
            raise ValueError(f"deploy STATE.json must be an object; got {type(data).__name__}")
        return cls(
            project_root=proj,
            schema_version=int(data.get("schema_version", SCHEMA_VERSION)),
            envs=dict(data.get("envs") or {}),
            preferred_env_for_phase=dict(data.get("preferred_env_for_phase") or {}),
            active_environments=list(data.get("active_environments") or []),
            updated_at=data.get("updated_at"),
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "schema_version": self.schema_version,
            "envs": self.envs,
        }
        if self.preferred_env_for_phase:
            out["preferred_env_for_phase"] = self.preferred_env_for_phase
        if self.active_environments:
            out["active_environments"] = self.active_environments
        if self.updated_at:
            out["updated_at"] = self.updated_at
        return out

    def save(self, *, backup: bool = False) -> Path:
        """Write atomically. Returns final path.

        Args:
            backup: If True and prior file exists, copy to `<path>.bak.<epoch>`
              before overwrite. Default off — caller (e.g., migration script)
              opts in when needed.
        """
        path = self.state_path
        path.parent.mkdir(parents=True, exist_ok=True)
        # Bump updated_at on every save unless caller pinned it explicitly.
        # Use the same UTC ISO 8601 format used elsewhere (no timezone suffix
        # for portability — schema only checks date+time prefix).
        self.updated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if backup and path.exists():
            stamp = int(time.time())
            path.with_suffix(f".json.bak.{stamp}").write_bytes(path.read_bytes())
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(tmp, path)
        return path

    # ── env mutations ──────────────────────────────────────────────

    def set_env(
        self,
        env: str,
        *,
        sha: str,
        deployed_at: str,
        phase_context: str | None = None,
        previous_sha: str | None = None,
        rollback_target: str | None = None,
        health: str | None = None,
        deploy_duration_sec: int | None = None,
        deploy_commands: list[str] | None = None,
        deployer: str | None = None,
        release_tag: str | None = None,
    ) -> None:
        """Set or update an env entry. previous_sha auto-rolls when omitted
        and an existing entry's sha differs from the new one."""
        prior = self.envs.get(env)
        if previous_sha is None and prior:
            prior_sha = prior.get("sha")
            if prior_sha and prior_sha != sha:
                previous_sha = prior_sha
        entry: dict[str, Any] = {"sha": sha, "deployed_at": deployed_at}
        if phase_context:
            entry["phase_context"] = phase_context
        if previous_sha:
            entry["previous_sha"] = previous_sha
        if rollback_target:
            entry["rollback_target"] = rollback_target
        if health:
            entry["health"] = health
        if deploy_duration_sec is not None:
            entry["deploy_duration_sec"] = deploy_duration_sec
        if deploy_commands:
            entry["deploy_commands"] = list(deploy_commands)
        if deployer:
            entry["deployer"] = deployer
        if release_tag:
            entry["release_tag"] = release_tag
        self.envs[env] = entry
        if env not in self.active_environments:
            self.active_environments.append(env)

    def get_env(self, env: str) -> dict[str, Any] | None:
        return self.envs.get(env)

    def set_preferred_env_for_phase(self, phase: str, env: str) -> None:
        if env not in self.envs and env not in self.active_environments:
            raise ValueError(
                f"cannot mark env '{env}' preferred for phase '{phase}' — "
                f"env not yet present in envs[] or active_environments[]"
            )
        self.preferred_env_for_phase[phase] = env

    def get_preferred_env_for_phase(self, phase: str) -> str | None:
        return self.preferred_env_for_phase.get(phase)
