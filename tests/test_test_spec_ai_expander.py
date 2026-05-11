from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = REPO_ROOT / "scripts" / "test_spec_ai_expander.py"

spec = importlib.util.spec_from_file_location("test_spec_ai_expander", MODULE_PATH)
assert spec and spec.loader
expander = importlib.util.module_from_spec(spec)
spec.loader.exec_module(expander)


def _phase(tmp_path: Path, body: str) -> Path:
    phase = tmp_path / ".vg" / "phases" / "06-sample"
    phase.mkdir(parents=True)
    (phase / "TEST-GOALS.md").write_text(body, encoding="utf-8")
    return phase


def test_detects_non_web_phase_profiles_from_artifacts(tmp_path: Path) -> None:
    assert expander.detect_phase_profile(_phase(tmp_path / "mobile", "Maestro flow for Android device screen")) == "mobile-hybrid"
    assert expander.detect_phase_profile(_phase(tmp_path / "cli", "Run CLI command, assert exit code, stdout, stderr")) == "cli-tool"
    assert expander.detect_phase_profile(_phase(tmp_path / "backend", "POST API endpoint emits queue event and DB row")) == "backend-only"
    assert expander.detect_phase_profile(_phase(tmp_path / "lib", "Library public API function with property invariant")) == "library"


def test_surface_field_does_not_force_mixed_profile_when_code_is_web(tmp_path: Path) -> None:
    root = tmp_path / "app"
    phase = _phase(root, "Surface: account portal\nProfile: feature\nResponsive mobile tables and device/browser display\n")
    source = root / "src" / "screens"
    source.mkdir(parents=True)
    (source / "page.tsx").write_text("export default function Page() { return <main /> }", encoding="utf-8")

    assert expander.detect_phase_profile(phase, root) == "web-fullstack"


def test_execution_plan_attaches_runner_by_profile() -> None:
    lifecycle = {
        "phase": "06-sample",
        "goals": {
            "G-01": {
                "title": "Create resource",
                "goal_type": "mutation",
                "primary_endpoints": [{"method": "POST", "path": "/api/resources"}],
                "steps": [{"stage": stage} for stage in expander.REQUIRED_STAGES],
            }
        },
    }
    expander.ensure_execution_plans(lifecycle, "cli-tool", {"routes": [], "forms": [], "mutations": [], "files_scanned": 0})

    plan = lifecycle["goals"]["G-01"]["execution_plan"]
    assert plan["profile"] == "cli-tool"
    assert plan["runner"] == "cli"
    assert plan["entrypoints"] == ["POST /api/resources"]


def test_validate_expansion_rejects_bad_dependency_and_stage_order() -> None:
    payload = {
        "goals": {
            "G-01": {
                "actors": [{"id": "owner", "role": "owner", "session": "owner_session"}],
                "fixture_dag": [{"id": "resource", "kind": "resource", "depends_on": ["missing"], "cleanup": "delete"}],
                "steps": [{"stage": "create"}],
                "execution_plan": {"profile": "web-fullstack", "runner": "playwright", "entrypoints": ["/"], "assertions": ["state"], "artifacts": ["trace"]},
            }
        }
    }

    errors = expander.validate_expansion(payload)

    assert any("missing dependencies" in error for error in errors)
    assert any("required RCRURDR stages" in error for error in errors)


def test_apply_expansion_merges_goal_specific_localizer_output() -> None:
    lifecycle = {
        "goals": {
            "G-01": {
                "title": "Create resource",
                "steps": [{"stage": stage} for stage in expander.REQUIRED_STAGES],
            }
        }
    }
    patch = {
        "schema_version": "1.0",
        "goals": {
            "G-01": {
                "actors": [
                    {"id": "owner", "role": "resource owner", "session": "owner_session"},
                    {"id": "collaborator", "role": "secondary actor", "session": "collaborator_session"},
                ],
                "fixture_dag": [
                    {"id": "owner_session", "kind": "auth", "depends_on": [], "cleanup": "revoke"},
                    {"id": "resource", "kind": "resource", "depends_on": ["owner_session"], "cleanup": "delete"},
                ],
                "steps": [
                    {"stage": stage, "actor": "owner", "action": f"{stage} action", "evidence": ["evidence"]}
                    for stage in expander.REQUIRED_STAGES
                ],
                "artifact_capture": [{"id": "resource_id", "source": "response", "identifier": "id", "consumer_step": "read_after_create"}],
                "cleanup": [{"target": "resource", "action": "delete"}],
                "execution_plan": {"profile": "web-fullstack", "runner": "playwright", "entrypoints": ["/resources"], "assertions": ["fresh read"], "artifacts": ["trace"]},
            }
        },
    }

    merged, meta = expander.apply_expansion(lifecycle, patch)

    assert meta["applied_goals"] == ["G-01"]
    assert merged["goals"]["G-01"]["actors"][1]["id"] == "collaborator"
    assert merged["goals"]["G-01"]["ai_expanded"] is True
