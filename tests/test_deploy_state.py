"""v2.82.0 Stage 6.1 / 6.2 — deploy STATE.json schema + reader/writer.

Project-level deploy state replacing per-phase
`.vg/phases/{N}/DEPLOY-STATE.json`. Atomic writes, schema-validated.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA = REPO_ROOT / "schemas" / "deploy-state.v1.json"
DEPLOY_STATE_MOD = REPO_ROOT / ".claude" / "scripts" / "deploy" / "state.py"

sys.path.insert(0, str(REPO_ROOT / ".claude" / "scripts"))


@pytest.fixture
def state():
    """Lazy-import so collection works even if module is missing."""
    from deploy.state import DeployState  # type: ignore[import-not-found]

    return DeployState


# ── schema ──────────────────────────────────────────────────────────


def test_schema_is_valid_json():
    body = SCHEMA.read_text(encoding="utf-8")
    json.loads(body)


def test_schema_has_required_top_level():
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert schema["$id"].endswith("/deploy-state.v1.json")
    assert schema["required"] == ["schema_version", "envs"]
    assert schema["properties"]["schema_version"]["const"] == 1


def test_schema_envstate_requires_sha_and_deployed_at():
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    env_state = schema["definitions"]["EnvState"]
    assert env_state["required"] == ["sha", "deployed_at"]


def test_schema_phase_context_pattern():
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    pattern = schema["definitions"]["EnvState"]["properties"]["phase_context"]["pattern"]
    import re

    rgx = re.compile(pattern)
    assert rgx.match("6")
    assert rgx.match("6.1")
    assert rgx.match("12.4.7")
    assert not rgx.match("phase-6")


# ── load empty ──────────────────────────────────────────────────────


def test_load_empty_returns_initialized_instance(tmp_path, state):
    s = state.load(tmp_path)
    assert s.schema_version == 1
    assert s.envs == {}
    assert s.preferred_env_for_phase == {}


def test_load_corrupt_raises(tmp_path, state):
    deploy_dir = tmp_path / ".vg" / "deploy"
    deploy_dir.mkdir(parents=True)
    (deploy_dir / "STATE.json").write_text("{not json}", encoding="utf-8")
    with pytest.raises(ValueError, match="corrupt"):
        state.load(tmp_path)


def test_load_non_object_raises(tmp_path, state):
    deploy_dir = tmp_path / ".vg" / "deploy"
    deploy_dir.mkdir(parents=True)
    (deploy_dir / "STATE.json").write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="object"):
        state.load(tmp_path)


# ── set_env + save ──────────────────────────────────────────────────


def test_set_env_minimal_required(tmp_path, state):
    s = state.load(tmp_path)
    s.set_env("prod", sha="abc1234", deployed_at="2026-05-10T10:00:00Z")
    s.save()
    written = json.loads((tmp_path / ".vg" / "deploy" / "STATE.json").read_text(encoding="utf-8"))
    assert written["envs"]["prod"]["sha"] == "abc1234"
    assert written["envs"]["prod"]["deployed_at"].startswith("2026-05-10")
    assert written["schema_version"] == 1
    assert "prod" in written["active_environments"]
    assert "updated_at" in written


def test_set_env_with_phase_context_and_health(tmp_path, state):
    s = state.load(tmp_path)
    s.set_env(
        "staging",
        sha="def5678",
        deployed_at="2026-05-10T10:00:00Z",
        phase_context="6",
        health="passing",
        deploy_duration_sec=42,
        deploy_commands=["fly deploy --remote-only"],
        deployer="ci@vgflow.dev",
        release_tag="v2.81.0",
    )
    s.save()
    e = json.loads((tmp_path / ".vg" / "deploy" / "STATE.json").read_text(encoding="utf-8"))[
        "envs"
    ]["staging"]
    assert e["phase_context"] == "6"
    assert e["health"] == "passing"
    assert e["deploy_duration_sec"] == 42
    assert e["deploy_commands"] == ["fly deploy --remote-only"]
    assert e["deployer"] == "ci@vgflow.dev"
    assert e["release_tag"] == "v2.81.0"


def test_set_env_auto_rolls_previous_sha(tmp_path, state):
    s = state.load(tmp_path)
    s.set_env("prod", sha="aaa", deployed_at="2026-05-10T10:00:00Z")
    s.save()
    s = state.load(tmp_path)
    s.set_env("prod", sha="bbb", deployed_at="2026-05-10T11:00:00Z")
    s.save()
    e = json.loads((tmp_path / ".vg" / "deploy" / "STATE.json").read_text(encoding="utf-8"))[
        "envs"
    ]["prod"]
    assert e["sha"] == "bbb"
    assert e["previous_sha"] == "aaa"


def test_set_env_explicit_previous_sha_wins_over_auto(tmp_path, state):
    s = state.load(tmp_path)
    s.set_env("prod", sha="aaa", deployed_at="2026-05-10T10:00:00Z")
    s.save()
    s = state.load(tmp_path)
    s.set_env(
        "prod",
        sha="bbb",
        deployed_at="2026-05-10T11:00:00Z",
        previous_sha="explicit-override",
    )
    s.save()
    e = json.loads((tmp_path / ".vg" / "deploy" / "STATE.json").read_text(encoding="utf-8"))[
        "envs"
    ]["prod"]
    assert e["previous_sha"] == "explicit-override"


def test_active_environments_dedupes(tmp_path, state):
    s = state.load(tmp_path)
    s.set_env("prod", sha="aaa", deployed_at="2026-05-10T10:00:00Z")
    s.set_env("prod", sha="bbb", deployed_at="2026-05-10T11:00:00Z")
    assert s.active_environments == ["prod"]


# ── preferred_env_for_phase ─────────────────────────────────────────


def test_preferred_env_for_phase_requires_existing_env(tmp_path, state):
    s = state.load(tmp_path)
    with pytest.raises(ValueError, match="env not yet present"):
        s.set_preferred_env_for_phase("6", "ghost")


def test_preferred_env_for_phase_writes(tmp_path, state):
    s = state.load(tmp_path)
    s.set_env("prod", sha="aaa", deployed_at="2026-05-10T10:00:00Z")
    s.set_preferred_env_for_phase("6", "prod")
    assert s.get_preferred_env_for_phase("6") == "prod"
    s.save()
    written = json.loads((tmp_path / ".vg" / "deploy" / "STATE.json").read_text(encoding="utf-8"))
    assert written["preferred_env_for_phase"]["6"] == "prod"


# ── atomic write ────────────────────────────────────────────────────


def test_save_uses_tmp_then_rename(tmp_path, state):
    """tmp file should not exist after save (rename atomic)."""
    s = state.load(tmp_path)
    s.set_env("prod", sha="aaa", deployed_at="2026-05-10T10:00:00Z")
    s.save()
    deploy_dir = tmp_path / ".vg" / "deploy"
    assert (deploy_dir / "STATE.json").exists()
    assert not (deploy_dir / "STATE.json.tmp").exists()


def test_save_with_backup_keeps_prior(tmp_path, state):
    s = state.load(tmp_path)
    s.set_env("prod", sha="aaa", deployed_at="2026-05-10T10:00:00Z")
    s.save()
    s = state.load(tmp_path)
    s.set_env("prod", sha="bbb", deployed_at="2026-05-10T11:00:00Z")
    s.save(backup=True)
    deploy_dir = tmp_path / ".vg" / "deploy"
    backups = list(deploy_dir.glob("STATE.json.bak.*"))
    assert len(backups) == 1
