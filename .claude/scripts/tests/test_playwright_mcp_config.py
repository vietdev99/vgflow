"""Tests for environment-level Playwright MCP worker configuration."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = REPO_ROOT / "scripts" / "validators" / "verify-playwright-mcp-config.py"
LOCK_SOURCE = REPO_ROOT / "playwright-locks" / "playwright-lock.sh"


def _env(home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "USERPROFILE": str(home),
            "PYTHONIOENCODING": "utf-8",
        }
    )
    env.pop("CODEX_HOME", None)
    return env


def _user_data_dir(args: list[str]) -> str:
    index = args.index("--user-data-dir")
    return args[index + 1]


def test_validator_repairs_stale_hardcoded_playwright_settings(tmp_path):
    home = tmp_path / "home"
    claude = home / ".claude"
    codex = home / ".codex"
    claude.mkdir(parents=True)
    codex.mkdir(parents=True)

    stale_args = [
        "@playwright/mcp@latest",
        "--user-data-dir",
        "C:/Users/Lionel Messi/.claude/playwright-profile-1",
    ]
    (claude / "settings.json").write_text(
        json.dumps(
            {
                "preserved": True,
                "mcpServers": {
                    f"playwright{i}": {"command": "npx", "args": stale_args}
                    for i in range(1, 6)
                },
            }
        ),
        encoding="utf-8",
    )
    (codex / "config.toml").write_text(
        "\n\n".join(
            [
                "[agents.keep]\ndescription = \"preserve me\"",
                *[
                    "\n".join(
                        [
                            f"[mcp_servers.playwright{i}]",
                            'command = "npx"',
                            'args = ["@playwright/mcp@latest", "--user-data-dir", "C:/Users/Lionel Messi/.codex/playwright-profile-1"]',
                        ]
                    )
                    for i in range(1, 6)
                ],
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    lock_path = claude / "playwright-locks" / "playwright-lock.sh"
    lock_path.parent.mkdir(parents=True)
    lock_path.write_text('LOCK_DIR="C:/Users/Lionel Messi/.claude/playwright-locks"\n', encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(VALIDATOR),
            "--home",
            str(home),
            "--repair",
            "--lock-source",
            str(LOCK_SOURCE),
            "--json",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        env=_env(home),
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["changed"] is True

    settings = json.loads((claude / "settings.json").read_text(encoding="utf-8"))
    assert settings["preserved"] is True
    for i in range(1, 6):
        entry = settings["mcpServers"][f"playwright{i}"]
        assert entry["command"] == "npx"
        assert _user_data_dir(entry["args"]).replace("\\", "/").endswith(
            f"/.claude/playwright-profile-{i}"
        )
        assert not _user_data_dir(entry["args"]).replace("\\", "/").startswith(
            "C:/Users/Lionel Messi/.claude/"
        )

    config = (codex / "config.toml").read_text(encoding="utf-8")
    assert "[agents.keep]" in config
    assert "C:/Users/Lionel Messi/.codex/" not in config
    for i in range(1, 6):
        assert f"[mcp_servers.playwright{i}]" in config
        assert f"/.codex/playwright-profile-{i}" in config.replace("\\", "/")

    lock_text = lock_path.read_text(encoding="utf-8")
    assert "VG_PLAYWRIGHT_LOCK_DIR" in lock_text
    assert "C:/Users/Lionel Messi" not in lock_text

    check = subprocess.run(
        [sys.executable, str(VALIDATOR), "--home", str(home), "--json"],
        capture_output=True,
        text=True,
        timeout=30,
        env=_env(home),
        encoding="utf-8",
        errors="replace",
    )
    assert check.returncode == 0, check.stderr
    check_payload = json.loads(check.stdout)
    assert check_payload["ok"] is True
    assert check_payload["changed"] is False


def test_validator_can_allow_intentional_custom_profile_dirs(tmp_path):
    home = tmp_path / "home"
    claude = home / ".claude"
    codex = home / ".codex"
    claude.mkdir(parents=True)
    codex.mkdir(parents=True)
    (claude / "playwright-locks").mkdir(parents=True)
    (claude / "playwright-locks" / "playwright-lock.sh").write_text(
        'LOCK_DIR="${VG_PLAYWRIGHT_LOCK_DIR:-$HOME/.claude/playwright-locks}"\n',
        encoding="utf-8",
    )
    (claude / "settings.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    f"playwright{i}": {
                        "command": "npx",
                        "args": [
                            "@playwright/mcp@latest",
                            "--user-data-dir",
                            f"/custom/claude/pw-{i}",
                        ],
                    }
                    for i in range(1, 6)
                }
            }
        ),
        encoding="utf-8",
    )
    (codex / "config.toml").write_text(
        "\n\n".join(
            "\n".join(
                [
                    f"[mcp_servers.playwright{i}]",
                    'command = "npx"',
                    f'args = ["@playwright/mcp@latest", "--user-data-dir", "/custom/codex/pw-{i}"]',
                ]
            )
            for i in range(1, 6)
        )
        + "\n",
        encoding="utf-8",
    )

    strict = subprocess.run(
        [sys.executable, str(VALIDATOR), "--home", str(home), "--quiet"],
        capture_output=True,
        text=True,
        timeout=30,
        env=_env(home),
        encoding="utf-8",
        errors="replace",
    )
    assert strict.returncode == 1

    custom = subprocess.run(
        [
            sys.executable,
            str(VALIDATOR),
            "--home",
            str(home),
            "--allow-custom-profile-dirs",
            "--quiet",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        env=_env(home),
        encoding="utf-8",
        errors="replace",
    )
    assert custom.returncode == 0, custom.stderr
