"""Deploy decision policy — reads ENV-BASELINE.md and proposes target env."""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def test_web_fullstack_default_proposes_sandbox(tmp_path: Path) -> None:
    eb = tmp_path / "ENV-BASELINE.md"
    eb.write_text(textwrap.dedent("""
        # Environment Baseline — X

        **Profile:** web-fullstack

        ## Recommended tech stack
        | Layer | Tool | Version | Rationale |
        |---|---|---|---|
        | Runtime | Node | 22 | LTS |

        ## Environment matrix
        | Env | Purpose | Hosting | Run command | Deploy method | DB strategy | Secrets source | Auto-promote? |
        |---|---|---|---|---|---|---|---|
        | dev | local | localhost | dev | none | sqlite | env | – |
        | sandbox | AI test | vps | pm2 | rsync | postgres | vault | from /vg:test |
        | staging | UAT | staging | (cdn) | git push | postgres | vercel | manual |
        | prod | prod | app.com | (cdn) | git push | postgres | vercel | approval |

        ## Decisions (E-XX namespace)
        ### E-01: x
        **Reasoning:** y
        **Reverse cost:** LOW
        **Sources cited:** https://x
    """).strip(), encoding="utf-8")

    sys.path.insert(0, str(REPO / "scripts" / "lib"))
    from deploy_decision import propose_target  # type: ignore

    proposal = propose_target(eb, phase_changes={"frontend": True, "backend": True})
    assert proposal["recommended_env"] == "sandbox"
    assert "sandbox" in proposal["available_envs"]
    assert proposal["confidence"] >= 0.7
    sys.path.remove(str(REPO / "scripts" / "lib"))


def test_frontend_only_phase_proposes_staging(tmp_path: Path) -> None:
    eb = tmp_path / "ENV-BASELINE.md"
    eb.write_text(textwrap.dedent("""
        # Environment Baseline — X

        **Profile:** web-frontend-only

        ## Recommended tech stack
        | Layer | Tool | Version | Rationale |
        |---|---|---|---|
        | Runtime | Node | 22 | x |

        ## Environment matrix
        | Env | Purpose | Hosting | Run command | Deploy method | API target | Secrets source | Auto-promote? |
        |---|---|---|---|---|---|---|---|
        | dev | local | localhost | dev | none | mock | env | – |
        | staging | UAT | staging | (cdn) | git push | prod-api | vercel | manual |
        | prod | prod | app | (cdn) | git push | prod | vercel | approval |

        ## Decisions (E-XX namespace)
        ### E-01: x
        **Reasoning:** y
        **Reverse cost:** LOW
        **Sources cited:** https://x
    """).strip(), encoding="utf-8")

    sys.path.insert(0, str(REPO / "scripts" / "lib"))
    from deploy_decision import propose_target  # type: ignore

    proposal = propose_target(eb, phase_changes={"frontend": True, "backend": False})
    assert proposal["recommended_env"] == "staging"
    sys.path.remove(str(REPO / "scripts" / "lib"))


def test_missing_envbaseline_returns_skip(tmp_path: Path) -> None:
    sys.path.insert(0, str(REPO / "scripts" / "lib"))
    from deploy_decision import propose_target  # type: ignore

    proposal = propose_target(tmp_path / "absent.md", phase_changes={})
    assert proposal["recommended_env"] == "skip"
    assert "missing" in proposal["reason"].lower()
    sys.path.remove(str(REPO / "scripts" / "lib"))


def test_detect_phase_changes_from_capsules(tmp_path: Path) -> None:
    """Codex round 2 Correction B — deterministic schema detection."""
    import json as _json
    phase_dir = tmp_path / "phase"
    capsule_dir = phase_dir / ".task-capsules"
    capsule_dir.mkdir(parents=True)
    (capsule_dir / "task-01.capsule.json").write_text(_json.dumps({
        "edits_files": ["apps/api/src/billing/migrations/2026-create-payments.sql",
                        "apps/web/src/InvoicePage.tsx"],
    }), encoding="utf-8")

    sys.path.insert(0, str(REPO / "scripts" / "lib"))
    from deploy_decision import detect_phase_changes  # type: ignore
    flags = detect_phase_changes(phase_dir)
    assert flags["frontend"] is True
    assert flags["schema"] is True
    sys.path.remove(str(REPO / "scripts" / "lib"))
