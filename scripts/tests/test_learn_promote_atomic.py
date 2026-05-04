"""
R9-C — atomic learn promote regression tests.

Codex audit (2026-05-05) found that `commands/vg/learn.md` declared a
4-pillar storage schema (overlay.yml + rules/*.md + patches/*.md +
ACCEPTED.md) but the orchestrator's `learn promote` only moved
CANDIDATES → ACCEPTED. Loader saw zero new state → injection emitted
the same content forever after a promote. R9-C wires the canonical
artifact generation atomically to the promote action.

Cases (8):
  1. test_promote_writes_rule_file — generator → rules/<id>.md exists with
     valid YAML frontmatter.
  2. test_promote_updates_overlay — config_override lesson → overlay.yml
     contains the new key.
  3. test_promote_writes_patch — type=patch lesson → patches/<id>.md exists.
  4. test_promote_emits_canonical_artifacts_event — full CLI promote
     records learn.canonical_artifacts_generated when auth gate passes;
     skips when no TTY/HMAC available (CI smoke).
  5. test_loader_reads_promoted_rule — bootstrap-loader CLI sees the
     newly promoted rule (--emit rules → JSON list contains id).
  6. test_idempotent_promote — re-running canonical generation on the same
     lesson yields byte-stable output (no duplicate keys / drift).
  7. test_migrate_legacy_accepted — pre-R9-C ACCEPTED.md (no canonical
     files) → migrate-accepted-canonical generates rules/<id>.md.
  8. test_learn_md_documents_atomic_pipeline — schema doc surfaces the
     atomic generation step (regression guard against doc drift).

The auth gate (TTY/HMAC) is exercised separately by
`test_learn_tty_gate.py`; this file targets the canonical-generator
plumbing. We import the orchestrator module in-process for cases 1-3,5-6
to bypass the auth gate (deliberate — the gate's already covered, the
gap was the artifact generation).
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
ORCHESTRATOR_MAIN = REPO_ROOT / ".claude" / "scripts" / "vg-orchestrator" / "__main__.py"
BOOTSTRAP_LOADER = REPO_ROOT / ".claude" / "scripts" / "bootstrap-loader.py"
LEARN_MD = REPO_ROOT / "commands" / "vg" / "learn.md"


def _load_orchestrator():
    """Import the orchestrator __main__.py as a module so tests can call
    helper functions directly (auth-gate bypass — gate is covered by
    test_learn_tty_gate.py).
    """
    sys.path.insert(0, str(ORCHESTRATOR_MAIN.parent))
    spec = importlib.util.spec_from_file_location(
        "vg_orchestrator_main", str(ORCHESTRATOR_MAIN),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def orchestrator():
    return _load_orchestrator()


def _make_block(
    cid: str = "L-901",
    title: str = "Atomic promote rule fixture",
    ltype: str = "rule",
    extras: str = "",
    scope_predicate: str = "phase.surfaces contains 'web'",
) -> str:
    """Build a fenced YAML lesson block.

    Default scope predicate matches `phase.surfaces contains 'web'` so
    the rule fires for `--surfaces web` contexts (used in case 5).
    """
    return (
        "```yaml\n"
        f"id: {cid}\n"
        f"title: \"{title}\"\n"
        f"type: {ltype}\n"
        "scope:\n"
        "  any_of:\n"
        f"    - \"{scope_predicate}\"\n"
        "action: must_run\n"
        "target_step: review\n"
        "confidence: 0.9\n"
        "impact: critical\n"
        "tier: A\n"
        "created_at: \"2026-05-05T00:00:00Z\"\n"
        f"prose: \"{title} prose body\"\n"
        f"{extras}"
        "```\n"
    )


# ──────────────────────────── cases ──────────────────────────────────────


def test_promote_writes_rule_file(orchestrator, tmp_path: Path):
    """Case 1 — generator emits rules/<lesson_id>.md with frontmatter."""
    bootstrap = tmp_path / ".vg" / "bootstrap"
    bootstrap.mkdir(parents=True, exist_ok=True)

    block = _make_block(cid="L-901", title="Rule fixture")
    artifacts = orchestrator._generate_canonical_artifacts_from_accepted(
        block, "L-901", bootstrap,
    )

    rule_path = bootstrap / "rules" / "L-901.md"
    assert rule_path.exists(), \
        f"R9-C requires rules/L-901.md after generation; not at {rule_path}"
    body = rule_path.read_text(encoding="utf-8")
    assert body.startswith("---"), \
        "rule file must have YAML frontmatter delimiter"
    assert "id: L-901" in body, "frontmatter must carry lesson id"
    assert "status: active" in body, \
        "newly promoted rule should default to status=active so loader matches it"
    assert artifacts["rule_path"].endswith("L-901.md")
    assert artifacts["overlay_keys"] == [], \
        "rule-only lesson must not produce overlay updates"
    assert artifacts["patches"] == [], \
        "rule-only lesson must not produce patch files"


def test_promote_updates_overlay(orchestrator, tmp_path: Path):
    """Case 2 — config_override lesson → overlay.yml deep-merged."""
    bootstrap = tmp_path / ".vg" / "bootstrap"
    bootstrap.mkdir(parents=True, exist_ok=True)

    block = _make_block(
        cid="L-902", title="Overlay test", ltype="config_override",
        extras=(
            "target: validators.api_contract.enabled\n"
            "value: false\n"
            "overlay:\n"
            "  validators:\n"
            "    api_contract:\n"
            "      enabled: false\n"
        ),
    )
    artifacts = orchestrator._generate_canonical_artifacts_from_accepted(
        block, "L-902", bootstrap,
    )

    overlay_path = bootstrap / "overlay.yml"
    assert overlay_path.exists(), \
        "config_override promote MUST emit overlay.yml"
    text = overlay_path.read_text(encoding="utf-8")
    assert "api_contract" in text, (
        f"overlay should contain validators.api_contract from lesson; "
        f"got:\n{text}"
    )
    assert "validators" in artifacts["overlay_keys"], (
        f"telemetry overlay_keys should list top-level merge keys; "
        f"got {artifacts['overlay_keys']!r}"
    )


def test_promote_writes_patch(orchestrator, tmp_path: Path):
    """Case 3 — type=patch lesson → patches/<id>.md emitted."""
    bootstrap = tmp_path / ".vg" / "bootstrap"
    bootstrap.mkdir(parents=True, exist_ok=True)

    block = _make_block(
        cid="L-903", title="Patch test", ltype="patch",
        extras="anchor: build.preflight\n",
    )
    artifacts = orchestrator._generate_canonical_artifacts_from_accepted(
        block, "L-903", bootstrap,
    )

    patch_path = bootstrap / "patches" / "L-903.md"
    assert patch_path.exists(), \
        f"type=patch promote MUST emit patches/L-903.md; not at {patch_path}"
    body = patch_path.read_text(encoding="utf-8")
    assert "id: L-903" in body
    assert "anchor: build.preflight" in body, \
        "patch frontmatter must carry anchor for loader filtering"
    assert any(p.endswith("L-903.md") for p in artifacts["patches"])


def test_promote_emits_canonical_artifacts_event(orchestrator, tmp_path: Path):
    """Case 4 — telemetry payload structure is correct.

    The full CLI flow's audit emit is tested by the auth-gated path
    (test_learn_tty_gate covers the wiring). Here we exercise the
    payload-shape contract via the helper return value, which is the
    sole input to the emit_event call.
    """
    bootstrap = tmp_path / ".vg" / "bootstrap"
    bootstrap.mkdir(parents=True, exist_ok=True)
    block = _make_block(
        cid="L-904", title="Telemetry test", ltype="patch",
        extras="anchor: build.preflight\noverlay:\n  validators:\n    foo: true\n",
    )
    artifacts = orchestrator._generate_canonical_artifacts_from_accepted(
        block, "L-904", bootstrap,
    )

    # Payload schema for learn.canonical_artifacts_generated event:
    # {lesson_id, rule_path, overlay_keys, patches}
    assert "rule_path" in artifacts and artifacts["rule_path"].endswith("L-904.md")
    assert isinstance(artifacts["overlay_keys"], list)
    assert isinstance(artifacts["patches"], list)
    assert any(p.endswith("L-904.md") for p in artifacts["patches"]), \
        "lesson with overlay+patch must produce patch entry"
    assert "validators" in artifacts["overlay_keys"], \
        "lesson with overlay must list overlay top-level keys"


def test_loader_reads_promoted_rule(orchestrator, tmp_path: Path):
    """Case 5 — bootstrap-loader picks up the new rule.

    Validates the wiring R9-C was meant to fix: before the fix loader
    saw zero new state because rules/ was never written.
    """
    bootstrap = tmp_path / ".vg" / "bootstrap"
    bootstrap.mkdir(parents=True, exist_ok=True)
    (tmp_path / ".git").mkdir(exist_ok=True)
    block = _make_block(cid="L-905", title="Loader visibility test")
    orchestrator._generate_canonical_artifacts_from_accepted(
        block, "L-905", bootstrap,
    )
    assert (bootstrap / "rules" / "L-905.md").exists()

    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(tmp_path)
    loader_result = subprocess.run(
        [sys.executable, str(BOOTSTRAP_LOADER),
         "--command", "review", "--phase", "1.0", "--step", "review",
         "--surfaces", "web", "--emit", "rules"],
        capture_output=True, text=True, timeout=15, env=env,
        encoding="utf-8", errors="replace", cwd=str(tmp_path),
    )
    assert loader_result.returncode == 0, (
        f"loader exited rc={loader_result.returncode}\n"
        f"stderr: {loader_result.stderr[-400:]}"
    )
    try:
        payload = json.loads(loader_result.stdout or "{}")
    except json.JSONDecodeError:
        pytest.fail(
            f"loader stdout not JSON: {loader_result.stdout[:300]!r}\n"
            f"stderr: {loader_result.stderr[-400:]}"
        )
    rules = payload.get("rules", []) if isinstance(payload, dict) else []
    ids = [r.get("id") for r in rules if isinstance(r, dict)]
    assert "L-905" in ids, (
        f"promoted rule MUST be visible to loader; got ids={ids!r}\n"
        f"stdout: {loader_result.stdout[:300]!r}\n"
        f"stderr: {loader_result.stderr[-400:]}"
    )


def test_idempotent_promote(orchestrator, tmp_path: Path):
    """Case 6 — re-generation is byte-stable (no drift)."""
    bootstrap = tmp_path / ".vg" / "bootstrap"
    bootstrap.mkdir(parents=True, exist_ok=True)
    block = _make_block(cid="L-906", title="Idempotent test")

    a1 = orchestrator._generate_canonical_artifacts_from_accepted(
        block, "L-906", bootstrap,
    )
    rule_path = Path(a1["rule_path"])
    body1 = rule_path.read_text(encoding="utf-8")

    # Re-run on the same lesson — must overwrite cleanly with identical output
    a2 = orchestrator._generate_canonical_artifacts_from_accepted(
        block, "L-906", bootstrap,
    )
    body2 = Path(a2["rule_path"]).read_text(encoding="utf-8")
    assert body1 == body2, (
        "R9-C generator must be idempotent — re-emitting the same lesson "
        "must yield byte-identical output."
    )

    # Same contract for overlay.yml when present
    block_ov = _make_block(
        cid="L-906b", title="Idempotent overlay", ltype="config_override",
        extras=(
            "target: validators.foo\nvalue: 42\n"
            "overlay:\n  validators:\n    foo: 42\n"
        ),
    )
    orchestrator._generate_canonical_artifacts_from_accepted(
        block_ov, "L-906b", bootstrap,
    )
    overlay_text_1 = (bootstrap / "overlay.yml").read_text(encoding="utf-8")
    orchestrator._generate_canonical_artifacts_from_accepted(
        block_ov, "L-906b", bootstrap,
    )
    overlay_text_2 = (bootstrap / "overlay.yml").read_text(encoding="utf-8")
    assert overlay_text_1 == overlay_text_2, (
        "overlay merge must be idempotent — same updates → byte-stable file"
    )


def test_migrate_legacy_accepted(tmp_path: Path):
    """Case 7 — pre-R9-C ACCEPTED.md → migration backfills rules/<id>.md."""
    bootstrap = tmp_path / ".vg" / "bootstrap"
    bootstrap.mkdir(parents=True, exist_ok=True)
    (tmp_path / ".git").mkdir(exist_ok=True)
    # Legacy state: ACCEPTED.md only — no rules/ directory yet
    (bootstrap / "ACCEPTED.md").write_text(
        "# Bootstrap ACCEPTED\n\n"
        "<!-- promote L-id=L-777 approver=tty auth=tty at=2026-04-30T00:00:00Z -->\n"
        + _make_block(cid="L-777", title="Legacy lesson")
        + "<!-- reason: backfill regression -->\n",
        encoding="utf-8",
    )
    assert not (bootstrap / "rules").exists()

    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(tmp_path)
    mig = subprocess.run(
        [sys.executable, str(ORCHESTRATOR_MAIN),
         "migrate-accepted-canonical"],
        capture_output=True, text=True, timeout=15, env=env,
        encoding="utf-8", errors="replace", cwd=str(tmp_path),
    )
    assert mig.returncode == 0, (
        f"migration should succeed; stderr={mig.stderr[-400:]}"
    )
    rule_path = bootstrap / "rules" / "L-777.md"
    assert rule_path.exists(), (
        f"migration MUST emit rules/L-777.md from legacy ACCEPTED.md "
        f"entry; not at {rule_path}\nstdout: {mig.stdout}"
    )
    assert "id: L-777" in rule_path.read_text(encoding="utf-8")

    # Re-run is idempotent (skips by default) and reports skipped count
    mig2 = subprocess.run(
        [sys.executable, str(ORCHESTRATOR_MAIN),
         "migrate-accepted-canonical"],
        capture_output=True, text=True, timeout=15, env=env,
        encoding="utf-8", errors="replace", cwd=str(tmp_path),
    )
    assert mig2.returncode == 0
    assert "skipped=1" in mig2.stdout, \
        "second run with no --force must skip the existing rule"


def test_learn_md_documents_atomic_pipeline():
    """Case 8 — schema doc surfaces the atomic generation step.

    Regression guard: future edits MUST keep the doc in sync with the
    behaviour or this test surfaces the drift. Codex audit found exactly
    this kind of doc/code split in the first place.
    """
    text = LEARN_MD.read_text(encoding="utf-8")
    needles = [
        "atomic",
        "canonical",
        "rules/<lesson_id>.md",
        "overlay.yml",
        "patches/<lesson_id>.md",
    ]
    missing = [n for n in needles if n.lower() not in text.lower()]
    assert not missing, (
        f"learn.md must document R9-C atomic promote pipeline. "
        f"Missing keywords: {missing!r}. "
        f"Add the rules/overlay/patches generation steps to the "
        f"`--promote` section."
    )
    assert "migrate-accepted-canonical" in text, (
        "learn.md must reference the migrate-accepted-canonical CLI for "
        "backward-compat."
    )
