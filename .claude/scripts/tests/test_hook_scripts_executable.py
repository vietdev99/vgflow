import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HOOKS = [
    "scripts/hooks/vg-user-prompt-submit.sh",
    "scripts/hooks/vg-session-start.sh",
    "scripts/hooks/vg-pre-tool-use-bash.sh",
    "scripts/hooks/vg-pre-tool-use-write.sh",
    "scripts/hooks/vg-pre-tool-use-agent.sh",
    "scripts/hooks/vg-post-tool-use-todowrite.sh",
    "scripts/hooks/vg-stop.sh",
    "scripts/hooks/install-hooks.sh",
]


def test_all_hooks_executable():
    for path in HOOKS:
        p = REPO / path
        assert p.exists(), f"missing hook: {path}"
        assert os.access(str(p), os.X_OK), f"hook not executable: {path}"


def test_helpers_executable():
    for path in ["scripts/vg-orchestrator-emit-evidence-signed.py",
                 "scripts/vg-state-machine-validator.py",
                 "scripts/codex-spawn-record.py",
                 "scripts/codex-hooks-install.py",
                 "scripts/codex-hooks/vg-codex-spawn-guard.py",
                 "scripts/codex-hooks/vg-pre-tool-use-bash.py",
                 "scripts/codex-hooks/vg-pre-tool-use-apply-patch.py",
                 "scripts/codex-hooks/vg-post-tool-use-bash.py",
                 "scripts/codex-hooks/vg-stop.py"]:
        p = REPO / path
        assert p.exists()
        assert os.access(str(p), os.X_OK), f"helper not executable: {path}"
