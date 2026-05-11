import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def load_module(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_deploy_command_prefers_global_only_config_path():
    preflight = (REPO_ROOT / "commands/vg/_shared/deploy/preflight.md").read_text(encoding="utf-8")
    execute = (REPO_ROOT / "commands/vg/_shared/deploy/execute.md").read_text(encoding="utf-8")
    text = preflight + "\n" + execute

    assert 'for candidate in ".vg/config.md" ".claude/vg.config.md" "vg.config.md"' in text
    assert "export VG_CONFIG_PATH" in text
    assert r"r'^environments:\s*$'" in text
    assert "end = re.search(r'^[A-Za-z_][A-Za-z0-9_-]*:\\s*', tail, re.M)" in text
    assert r"r'^[ \t]+%s:[ \t]*$'" in text
    assert "open('.claude/vg.config.md'" not in text
    assert "grep -qE \"^[[:space:]]+${env}:[[:space:]]*\\$\" .claude/vg.config.md" not in text
    assert 'grep -E "^meta_memory_mode:" "$VG_CONFIG_PATH"' in execute


def test_config_loader_uses_resolved_config_before_graphify():
    text = (REPO_ROOT / "commands/vg/_shared/config-loader.md").read_text(encoding="utf-8")

    resolver_pos = text.index("VG_CONFIG_PATH=\"\"")
    graphify_pos = text.index("GRAPHIFY_ENABLED=")
    assert resolver_pos < graphify_pos
    assert '"${VG_CONFIG_PATH:-.claude/vg.config.md}"' in text
    assert "sed -e '1s/^\\xEF\\xBB\\xBF//' -e 's/\\r$//' \"$VG_CONFIG_PATH\"" in text


def test_deploy_aggregator_config_resolution_prefers_vg_config(tmp_path, monkeypatch):
    mod = load_module("vg_deploy_aggregator", "scripts/vg_deploy_aggregator.py")
    (tmp_path / ".vg").mkdir()
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".vg" / "config.md").write_text("project_name: modern\n", encoding="utf-8")
    (tmp_path / ".claude" / "vg.config.md").write_text("project_name: legacy\n", encoding="utf-8")

    assert mod.resolve_config_path(tmp_path) == tmp_path / ".vg" / "config.md"


def test_deploy_runbook_drafter_config_resolution_falls_back_to_legacy(tmp_path):
    mod = load_module("vg_deploy_runbook_drafter", "scripts/vg_deploy_runbook_drafter.py")
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "vg.config.md").write_text("project_name: legacy\n", encoding="utf-8")

    assert mod.resolve_config_path(tmp_path) == tmp_path / ".claude" / "vg.config.md"


def test_codex_env_config_resolution_prefers_vg_config(tmp_path):
    mod = load_module("codex_vg_env", ".claude/scripts/lib/codex_vg_env.py")
    (tmp_path / ".vg").mkdir()
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".vg" / "config.md").write_text("profile: web-fullstack\n", encoding="utf-8")
    (tmp_path / ".claude" / "vg.config.md").write_text("profile: legacy\n", encoding="utf-8")

    assert mod.resolve_config_path(tmp_path) == tmp_path / ".vg" / "config.md"
