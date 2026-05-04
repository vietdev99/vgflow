from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_LOADER = REPO_ROOT / "commands" / "vg" / "_shared" / "config-loader.md"
BLUEPRINT_DIR = REPO_ROOT / "commands" / "vg" / "_shared" / "blueprint"


def _config_loader_shell() -> str:
    text = CONFIG_LOADER.read_text(encoding="utf-8")
    match = re.search(r"```bash\n(vg_config_get\(\).*?export -f vg_config_get vg_config_get_array 2>/dev/null \|\| true)\n```", text, re.S)
    assert match, "config-loader vg_config_get block not found"
    return match.group(1)

def _blueprint_design_autotrigger_shell() -> str:
    text = (BLUEPRINT_DIR / "preflight.md").read_text(encoding="utf-8")
    section = text.split("Design-extract auto-trigger", 1)[1]
    match = re.search(r"```bash\n(.*?)\n```", section, re.S)
    assert match, "blueprint design-extract auto-trigger block not found"
    return match.group(1)


def test_vg_config_get_strips_inline_comments(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / ".claude").mkdir(parents=True)
    (repo / ".claude" / "vg.config.md").write_text(
        "profile: cli-tool # local comment\n"
        "contract_format:\n"
        "  type: zod_code_block # use TS fences\n"
        "design_assets:\n"
        "  paths:\n"
        "    - designs/main.png # imported from mockup\n",
        encoding="utf-8",
    )
    script = (
        _config_loader_shell()
        + "\n"
        + "vg_config_get profile missing\n"
        + "vg_config_get contract_format.type missing\n"
        + "vg_config_get_array design_assets.paths\n"
    )
    result = subprocess.run(
        ["bash", "-lc", script],
        cwd=repo,
        env={**os.environ},
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "cli-tool",
        "zod_code_block",
        "designs/main.png",
    ]


def test_blueprint_shell_avoids_duplicate_zero_count_pattern() -> None:
    offenders = []
    for path in BLUEPRINT_DIR.glob("*.md"):
        text = path.read_text(encoding="utf-8")
        if re.search(r"grep -cE?.*\|\|\s*echo\s+\"?0\"?", text):
            offenders.append(path.name)
    assert offenders == []


def test_blueprint_preflight_avoids_empty_array_expansion_under_nounset() -> None:
    text = (BLUEPRINT_DIR / "preflight.md").read_text(encoding="utf-8")
    assert '"${DETECT_FLAGS[@]}"' not in text
    assert '"${PREFLIGHT_EXTRA[@]}"' not in text

def test_blueprint_design_autotrigger_skips_non_ui_profiles(tmp_path: Path) -> None:
    phase = tmp_path / ".vg" / "phases" / "1-cli"
    phase.mkdir(parents=True)
    script = (
        "set -euo pipefail\n"
        "vg_config_get_array() { printf '%s\\n' \"$VG_TEST_DESIGN_PATHS\"; }\n"
        + _blueprint_design_autotrigger_shell()
    )
    for profile in ("cli-tool", "library", "infra", "docs"):
        result = subprocess.run(
            ["bash", "-lc", script],
            cwd=tmp_path,
            env={
                **os.environ,
                "REPO_ROOT": str(tmp_path),
                "PHASE_DIR": str(phase),
                "PHASE_PROFILE": profile,
                "PYTHON_BIN": "python3",
                "VG_TEST_DESIGN_PATHS": "missing-designs/**/*.png",
            },
            text=True,
            capture_output=True,
            timeout=10,
        )
        assert result.returncode == 0, result.stderr
        assert f"PHASE_PROFILE={profile}" in result.stdout
        assert "Design assets detected" not in result.stdout

def test_blueprint_design_autotrigger_skips_empty_globs(tmp_path: Path) -> None:
    phase = tmp_path / ".vg" / "phases" / "1-feature"
    phase.mkdir(parents=True)
    script = (
        "set -euo pipefail\n"
        "vg_config_get_array() { printf '%s\\n' \"$VG_TEST_DESIGN_PATHS\"; }\n"
        + _blueprint_design_autotrigger_shell()
    )
    result = subprocess.run(
        ["bash", "-lc", script],
        cwd=tmp_path,
        env={
            **os.environ,
            "REPO_ROOT": str(tmp_path),
            "PHASE_DIR": str(phase),
            "PHASE_PROFILE": "feature",
            "PYTHON_BIN": "python3",
            "VG_TEST_DESIGN_PATHS": "missing-designs/**/*.png\nalso-missing.fig",
        },
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert "design_assets.paths matched no files" in result.stdout
    assert "Design assets detected" not in result.stdout

def test_blueprint_design_autotrigger_uses_resolved_paths_not_raw_find_patterns() -> None:
    text = (BLUEPRINT_DIR / "preflight.md").read_text(encoding="utf-8")
    assert "DESIGN_MATCHED_PATHS" in text
    assert "find $pattern" not in text
