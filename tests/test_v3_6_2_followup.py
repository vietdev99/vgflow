"""v3.6.2 — generator preserve hardening + /vg:update chmod.

Coverage:
1. generate-codex-skills.sh declares target_has_curated_codex_content
2. write_codex_skill SKIPS targets with curated content unless --force-overwrite-curated
3. --force-overwrite-curated CLI flag accepted
4. /vg:update rotate-and-repair.md chmod +x hooks before install-hooks.sh
5. canonical/mirror byte-identity for rotate-and-repair.md
6. Smoke: running generator with --force on a target with HARD-GATE-CODEX
   does NOT modify the target.
7. Deep matrix: invalid YAML repair across no-force, --force, curated,
   mark-step heuristic, overwrite opt-in, and idempotent reruns.
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
GENERATOR = REPO_ROOT / "scripts" / "generate-codex-skills.sh"
ROTATE_CANON = REPO_ROOT / "commands" / "vg" / "_shared" / "update" / "rotate-and-repair.md"
ROTATE_MIRROR = REPO_ROOT / ".claude" / "commands" / "vg" / "_shared" / "update" / "rotate-and-repair.md"

_BASH_SKIP = pytest.mark.skipif(
    not shutil.which("bash") or sys.platform == "win32",
    reason="bash + POSIX semantics required for generator smoke",
)

SOURCE_DESC = 'Source says "quoted phrase" safely'
SOURCE_BODY = "Source body generated from canonical command.\n"
CURATED_BODY = (
    "Curated content must remain.\n\n"
    "<HARD-GATE-CODEX>\n"
    "Operator MUST emit mark-step manually.\n"
    "</HARD-GATE-CODEX>\n"
)
INVALID_FM = (
    "---\n"
    'name: "vg-yamlrepair"\n'
    'description: "Broken "quoted phrase" frontmatter"\n'
    "metadata:\n"
    '  short-description: "Broken "quoted phrase" frontmatter"\n'
    "---\n\n"
)
VALID_FM = (
    "---\n"
    'name: "vg-yamlrepair"\n'
    'description: "curated"\n'
    "metadata:\n"
    '  short-description: "curated"\n'
    "---\n\n"
)


def _stage_generator_repo(tmp_path: Path) -> tuple[Path, Path]:
    """Create a minimal repo that exercises the real generator script."""
    fake_repo = tmp_path / "repo"
    (fake_repo / "commands" / "vg").mkdir(parents=True)
    (fake_repo / "skills").mkdir(parents=True)
    (fake_repo / "codex-skills" / "vg-yamlrepair").mkdir(parents=True)

    (fake_repo / "commands" / "vg" / "yamlrepair.md").write_text(
        "---\n"
        "name: vg:yamlrepair\n"
        f"description: {SOURCE_DESC}\n"
        "---\n\n"
        f"{SOURCE_BODY}",
        encoding="utf-8",
    )

    (fake_repo / "scripts").mkdir()
    shutil.copy(GENERATOR, fake_repo / "scripts" / "generate-codex-skills.sh")
    os.chmod(fake_repo / "scripts" / "generate-codex-skills.sh", 0o755)
    return fake_repo, fake_repo / "codex-skills" / "vg-yamlrepair" / "SKILL.md"


def _run_generator(fake_repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(fake_repo / "scripts" / "generate-codex-skills.sh"), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _frontmatter_from_text(text: str) -> dict:
    fm_text = text.split("---", 2)[1]
    return yaml.safe_load(fm_text)


def _assert_valid_source_frontmatter(text: str) -> None:
    fm = _frontmatter_from_text(text)
    assert fm["name"] == "vg-yamlrepair"
    assert fm["description"] == SOURCE_DESC
    assert fm["metadata"]["short-description"] == SOURCE_DESC


# ── content checks ────────────────────────────────────────────────────────


def test_generator_declares_curated_detector():
    body = GENERATOR.read_text(encoding="utf-8")
    assert "target_has_curated_codex_content" in body
    assert "HARD-GATE-CODEX" in body, (
        "detector must look for HARD-GATE-CODEX marker"
    )
    assert "vg-orchestrator mark-step" in body, (
        "detector must look for ≥8 mark-step lines heuristic"
    )


def test_generator_skips_curated_by_default():
    body = GENERATOR.read_text(encoding="utf-8")
    # write_codex_skill should refuse to overwrite curated targets unless override flag
    assert "FORCE_OVERWRITE_CURATED" in body
    # And the skip path SHOULD print "Skipped (curated content detected)"
    assert "Skipped (curated content detected)" in body


def test_generator_cli_accepts_force_overwrite_curated():
    body = GENERATOR.read_text(encoding="utf-8")
    assert "--force-overwrite-curated)" in body
    assert "FORCE_OVERWRITE_CURATED=true" in body


def test_rotate_and_repair_chmods_hooks():
    body = ROTATE_CANON.read_text(encoding="utf-8")
    # chmod block must precede install-hooks invocation
    chmod_pos = body.find('chmod +x "${REPO_ROOT}/.claude/scripts/hooks/"*.sh')
    install_pos = body.find('HOOK_INSTALL=')
    assert chmod_pos > 0, "rotate-and-repair must chmod .claude/scripts/hooks/*.sh"
    assert install_pos > chmod_pos, (
        "chmod must happen BEFORE install-hooks.sh writes settings.json"
    )
    # And cover the other directories that house hook-callable scripts
    for sub in (
        '.claude/scripts/hooks/"*.py',
        '.claude/scripts/"*.sh',
        '.claude/scripts/"*.py',
        '.claude/scripts/validators/"*.py',
        '.claude/scripts/vg-orchestrator/"*.py',
        '.claude/scripts/lib/"*.py',
        '.claude/scripts/blueprint/"*.py',
        '.claude/commands/vg/_shared/lib/"*.sh',
    ):
        assert sub in body, f"rotate-and-repair must chmod {sub}"


def test_rotate_and_repair_mirror_byte_identity():
    assert ROTATE_CANON.read_bytes() == ROTATE_MIRROR.read_bytes()


# ── functional smoke ──────────────────────────────────────────────────────


@_BASH_SKIP
def test_generator_force_does_not_clobber_curated(tmp_path):
    """Create a fake curated SKILL.md and verify --force leaves it untouched."""
    # Stage a minimal source tree: commands/vg/X.md + a curated target.
    fake_repo = tmp_path / "repo"
    (fake_repo / "commands" / "vg").mkdir(parents=True)
    (fake_repo / "skills").mkdir(parents=True)
    (fake_repo / "codex-skills").mkdir(parents=True)
    (fake_repo / "codex-skills" / "vg-curatedtest").mkdir()

    # Source command
    (fake_repo / "commands" / "vg" / "curatedtest.md").write_text(
        "---\nname: vg:curatedtest\ndescription: Curated test source\n---\n\nBody.\n",
        encoding="utf-8",
    )
    # Curated target with HARD-GATE-CODEX marker
    target = fake_repo / "codex-skills" / "vg-curatedtest" / "SKILL.md"
    curated_body = (
        '---\nname: "vg-curatedtest"\ndescription: "curated"\n'
        'metadata:\n  short-description: "curated"\n---\n\n'
        "Curated content here.\n\n"
        "<HARD-GATE-CODEX>\nOperator MUST emit mark-step manually.\n</HARD-GATE-CODEX>\n"
    )
    target.write_text(curated_body, encoding="utf-8")

    # Copy generator into fake repo so its REPO_ROOT resolution finds the
    # right tree (script uses cd $(dirname $0)/.. as REPO_ROOT)
    (fake_repo / "scripts").mkdir()
    shutil.copy(GENERATOR, fake_repo / "scripts" / "generate-codex-skills.sh")
    os.chmod(fake_repo / "scripts" / "generate-codex-skills.sh", 0o755)

    r = subprocess.run(
        ["bash", str(fake_repo / "scripts" / "generate-codex-skills.sh"), "--force"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert r.returncode == 0, f"generator exited {r.returncode}\n{r.stdout}\n{r.stderr}"
    # Target must be unchanged
    after = target.read_text(encoding="utf-8")
    assert after == curated_body, (
        "curated SKILL.md must NOT be modified by --force regen.\n"
        f"stdout={r.stdout}\n"
    )
    # And stdout should mention the skip
    assert "Skipped (curated content detected)" in r.stdout or "vg-curatedtest" in r.stdout

@_BASH_SKIP
def test_generator_repairs_invalid_yaml_even_when_curated(tmp_path):
    """Invalid SKILL frontmatter must not stay skipped behind curated guard."""
    fake_repo = tmp_path / "repo"
    (fake_repo / "commands" / "vg").mkdir(parents=True)
    (fake_repo / "skills").mkdir(parents=True)
    (fake_repo / "codex-skills" / "vg-yamlrepair").mkdir(parents=True)

    (fake_repo / "commands" / "vg" / "yamlrepair.md").write_text(
        "---\n"
        "name: vg:yamlrepair\n"
        "description: Source says \"quoted phrase\" safely\n"
        "---\n\n"
        "Source body that should not replace curated content.\n",
        encoding="utf-8",
    )

    target = fake_repo / "codex-skills" / "vg-yamlrepair" / "SKILL.md"
    target.write_text(
        '---\n'
        'name: "vg-yamlrepair"\n'
        'description: "Broken "quoted phrase" frontmatter"\n'
        'metadata:\n'
        '  short-description: "Broken "quoted phrase" frontmatter"\n'
        '---\n\n'
        "Curated content must remain.\n\n"
        "<HARD-GATE-CODEX>\n"
        "Operator MUST emit mark-step manually.\n"
        "</HARD-GATE-CODEX>\n",
        encoding="utf-8",
    )

    (fake_repo / "scripts").mkdir()
    shutil.copy(GENERATOR, fake_repo / "scripts" / "generate-codex-skills.sh")
    os.chmod(fake_repo / "scripts" / "generate-codex-skills.sh", 0o755)

    r = subprocess.run(
        ["bash", str(fake_repo / "scripts" / "generate-codex-skills.sh"), "--force"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert r.returncode == 0, f"generator exited {r.returncode}\n{r.stdout}\n{r.stderr}"

    repaired = target.read_text(encoding="utf-8")
    fm_text = repaired.split("---", 2)[1]
    fm = yaml.safe_load(fm_text)
    assert fm["name"] == "vg-yamlrepair"
    assert fm["description"] == 'Source says "quoted phrase" safely'
    assert "Curated content must remain." in repaired
    assert "<HARD-GATE-CODEX>" in repaired
    assert "Source body that should not replace curated content." not in repaired
    assert "Repaired invalid YAML frontmatter" in r.stdout


@_BASH_SKIP
def test_generator_repairs_invalid_yaml_existing_target_without_force(tmp_path):
    """No-force skip path must repair invalid frontmatter before returning."""
    fake_repo, target = _stage_generator_repo(tmp_path)
    target.write_text(
        INVALID_FM + "Manual non-curated content must remain.\n",
        encoding="utf-8",
    )

    r = _run_generator(fake_repo)

    assert r.returncode == 0, f"generator exited {r.returncode}\n{r.stdout}\n{r.stderr}"
    repaired = target.read_text(encoding="utf-8")
    _assert_valid_source_frontmatter(repaired)
    assert "Manual non-curated content must remain." in repaired
    assert SOURCE_BODY not in repaired
    assert "Repaired invalid YAML frontmatter: vg-yamlrepair" in r.stdout
    assert "Summary: 0 generated, 0 skipped, 1 repaired" in r.stdout


@_BASH_SKIP
def test_generator_regenerates_non_curated_invalid_yaml_when_forced(tmp_path):
    """--force may replace invalid non-curated targets with generated content."""
    fake_repo, target = _stage_generator_repo(tmp_path)
    target.write_text(
        INVALID_FM + "Manual non-curated content should be replaced.\n",
        encoding="utf-8",
    )

    r = _run_generator(fake_repo, "--force")

    assert r.returncode == 0, f"generator exited {r.returncode}\n{r.stdout}\n{r.stderr}"
    generated = target.read_text(encoding="utf-8")
    _assert_valid_source_frontmatter(generated)
    assert SOURCE_BODY in generated
    assert "Manual non-curated content should be replaced." not in generated
    assert "Generated: vg-yamlrepair" in r.stdout


@_BASH_SKIP
def test_generator_repairs_curated_invalid_yaml_without_force(tmp_path):
    """Curated targets still get frontmatter repair on no-force runs."""
    fake_repo, target = _stage_generator_repo(tmp_path)
    target.write_text(INVALID_FM + CURATED_BODY, encoding="utf-8")

    r = _run_generator(fake_repo)

    assert r.returncode == 0, f"generator exited {r.returncode}\n{r.stdout}\n{r.stderr}"
    repaired = target.read_text(encoding="utf-8")
    _assert_valid_source_frontmatter(repaired)
    assert CURATED_BODY in repaired
    assert SOURCE_BODY not in repaired
    assert "Repaired invalid YAML frontmatter: vg-yamlrepair" in r.stdout


@_BASH_SKIP
def test_generator_force_overwrite_curated_replaces_body(tmp_path):
    """Explicit override is still an escape hatch for curated targets."""
    fake_repo, target = _stage_generator_repo(tmp_path)
    target.write_text(VALID_FM + CURATED_BODY, encoding="utf-8")

    r = _run_generator(fake_repo, "--force-overwrite-curated")

    assert r.returncode == 0, f"generator exited {r.returncode}\n{r.stdout}\n{r.stderr}"
    generated = target.read_text(encoding="utf-8")
    _assert_valid_source_frontmatter(generated)
    assert SOURCE_BODY in generated
    assert CURATED_BODY not in generated
    assert "<HARD-GATE-CODEX>" not in generated
    assert "Generated: vg-yamlrepair" in r.stdout


@_BASH_SKIP
def test_generator_mark_step_heuristic_preserves_curated_without_hard_gate(tmp_path):
    """Eight explicit mark-step lines count as curated content without hard gate."""
    fake_repo, target = _stage_generator_repo(tmp_path)
    mark_steps = "\n".join(
        f"vg-orchestrator mark-step review marker_{i}" for i in range(8)
    )
    original = VALID_FM + "Manual marker table.\n" + mark_steps + "\n"
    target.write_text(original, encoding="utf-8")

    r = _run_generator(fake_repo, "--force")

    assert r.returncode == 0, f"generator exited {r.returncode}\n{r.stdout}\n{r.stderr}"
    assert target.read_text(encoding="utf-8") == original
    assert "Skipped (curated content detected): vg-yamlrepair" in r.stdout


@_BASH_SKIP
def test_generator_mark_step_heuristic_repairs_invalid_yaml(tmp_path):
    """Invalid YAML is repaired even when curation is detected by mark-step count."""
    fake_repo, target = _stage_generator_repo(tmp_path)
    mark_steps = "\n".join(
        f"vg-orchestrator mark-step review marker_{i}" for i in range(8)
    )
    target.write_text(
        INVALID_FM + "Manual marker table.\n" + mark_steps + "\n",
        encoding="utf-8",
    )

    r = _run_generator(fake_repo, "--force")

    assert r.returncode == 0, f"generator exited {r.returncode}\n{r.stdout}\n{r.stderr}"
    repaired = target.read_text(encoding="utf-8")
    _assert_valid_source_frontmatter(repaired)
    assert "Manual marker table." in repaired
    assert mark_steps in repaired
    assert SOURCE_BODY not in repaired
    assert "Repaired invalid YAML frontmatter (curated content preserved)" in r.stdout


@_BASH_SKIP
def test_generator_repair_then_rerun_is_idempotent_for_curated_target(tmp_path):
    """After repair, a second --force run skips curated content unchanged."""
    fake_repo, target = _stage_generator_repo(tmp_path)
    target.write_text(INVALID_FM + CURATED_BODY, encoding="utf-8")

    first = _run_generator(fake_repo, "--force")
    after_first = target.read_text(encoding="utf-8")
    second = _run_generator(fake_repo, "--force")
    after_second = target.read_text(encoding="utf-8")

    assert first.returncode == 0, f"first run failed\n{first.stdout}\n{first.stderr}"
    assert second.returncode == 0, f"second run failed\n{second.stdout}\n{second.stderr}"
    _assert_valid_source_frontmatter(after_first)
    assert after_second == after_first
    assert "Repaired invalid YAML frontmatter (curated content preserved)" in first.stdout
    assert "Skipped (curated content detected): vg-yamlrepair" in second.stdout
