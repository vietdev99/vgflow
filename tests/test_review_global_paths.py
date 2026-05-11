from __future__ import annotations

import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
VG_RUN = REPO_ROOT / "commands" / "vg" / "_shared" / "lib" / "vg-run.sh"


def test_review_markdown_uses_global_paths_not_project_local_scripts() -> None:
    review_files = [
        REPO_ROOT / "commands" / "vg" / "review.md",
        *sorted((REPO_ROOT / "commands" / "vg" / "_shared" / "review").glob("*.md")),
    ]
    offenders: list[str] = []
    for path in review_files:
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if ".claude/scripts" in line:
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{line_no}: {line.strip()}")
            if ".claude/commands/vg" in line and "VG_RUN_LIB" not in line:
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{line_no}: {line.strip()}")

    assert not offenders, "\n".join(offenders[:20])


def test_vg_run_resolves_global_only_install_without_project_claude(tmp_path: Path) -> None:
    project = tmp_path / "project"
    vg_home = tmp_path / "home-vgflow"
    project.mkdir()
    (vg_home / "scripts" / "vg-orchestrator").mkdir(parents=True)
    (vg_home / "scripts" / "vg-orchestrator" / "__main__.py").write_text("", encoding="utf-8")
    (vg_home / "commands" / "vg" / "_shared" / "lib").mkdir(parents=True)
    (vg_home / "commands" / "vg" / "_shared" / "lib" / "phase-profile.sh").write_text(
        "detect_phase_profile() { echo feature; }\n",
        encoding="utf-8",
    )

    script = f"""
set -euo pipefail
export REPO_ROOT="{project}"
export VG_HOME="{vg_home}"
source "{VG_RUN}"
test "$VG_SCRIPT_ROOT" = "{vg_home}/scripts"
test "$VG_COMMAND_ROOT" = "{vg_home}/commands/vg"
test "$(vg_script_path vg-orchestrator)" = "{vg_home}/scripts/vg-orchestrator"
test "$(vg_command_path _shared/lib/phase-profile.sh)" = "{vg_home}/commands/vg/_shared/lib/phase-profile.sh"
vg_source_lib phase-profile.sh
test "$(detect_phase_profile)" = "feature"
"""
    result = subprocess.run(
        ["bash", "-lc", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
    )
    assert result.returncode == 0, result.stderr + result.stdout
