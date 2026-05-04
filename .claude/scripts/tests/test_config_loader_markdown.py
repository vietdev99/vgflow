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
