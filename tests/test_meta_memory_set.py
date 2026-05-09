"""Helper /vg:meta-memory atomic edit of vg.config.md."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HELPER = REPO_ROOT / "scripts" / "vg-meta-memory-set.py"


def _run(*args, cwd=None):
    return subprocess.run(
        [sys.executable, str(HELPER), *args],
        capture_output=True, text=True, cwd=cwd,
    )


def test_set_valid_mode_in_existing_config(tmp_path):
    cfg = tmp_path / "vg.config.md"
    cfg.write_text(
        "# Sample\n\nmeta_memory_mode: disabled\n\nother_field: 1\n",
        encoding="utf-8",
    )
    r = _run("--mode", "inject-as-advice", "--config", str(cfg))
    assert r.returncode == 0, r.stderr
    body = cfg.read_text(encoding="utf-8")
    assert "meta_memory_mode: inject-as-advice" in body
    assert "other_field: 1" in body  # other content preserved


def test_invalid_mode_rejected(tmp_path):
    cfg = tmp_path / "vg.config.md"
    cfg.write_text("meta_memory_mode: disabled\n", encoding="utf-8")
    r = _run("--mode", "bogus", "--config", str(cfg))
    assert r.returncode != 0


def test_idempotent_no_change(tmp_path):
    cfg = tmp_path / "vg.config.md"
    body = "meta_memory_mode: reflect-only\n"
    cfg.write_text(body, encoding="utf-8")
    r = _run("--mode", "reflect-only", "--config", str(cfg))
    assert r.returncode == 0
    assert cfg.read_text(encoding="utf-8") == body


def test_status_when_set(tmp_path):
    cfg = tmp_path / "vg.config.md"
    cfg.write_text("meta_memory_mode: inject-as-advice\n", encoding="utf-8")
    r = _run("--mode", "status", "--config", str(cfg))
    assert r.returncode == 0
    assert "inject-as-advice" in r.stdout


def test_status_when_missing_config(tmp_path):
    cfg = tmp_path / "vg.config.md"
    r = _run("--mode", "status", "--config", str(cfg))
    assert r.returncode == 0
    assert "<not set>" in r.stdout


def test_status_when_field_not_declared(tmp_path):
    cfg = tmp_path / "vg.config.md"
    cfg.write_text("# Other content\n", encoding="utf-8")
    r = _run("--mode", "status", "--config", str(cfg))
    assert r.returncode == 0
    assert "<not declared>" in r.stdout


def test_appends_when_field_absent(tmp_path):
    cfg = tmp_path / "vg.config.md"
    cfg.write_text("# Only header\n", encoding="utf-8")
    r = _run("--mode", "default", "--config", str(cfg))
    assert r.returncode == 0
    body = cfg.read_text(encoding="utf-8")
    assert "meta_memory_mode: default" in body
    assert "# Only header" in body


def test_atomic_write_no_temp_leftover(tmp_path):
    cfg = tmp_path / "vg.config.md"
    cfg.write_text("meta_memory_mode: disabled\n", encoding="utf-8")
    r = _run("--mode", "inject-as-advice", "--config", str(cfg))
    assert r.returncode == 0
    leftover = list(tmp_path.glob(".vg.config.*.tmp"))
    assert leftover == [], f"tempfiles not cleaned up: {leftover}"


def test_helper_mirror_byte_identical():
    canonical = REPO_ROOT / "scripts" / "vg-meta-memory-set.py"
    mirror = REPO_ROOT / ".claude" / "scripts" / "vg-meta-memory-set.py"
    if not mirror.exists():
        return
    assert canonical.read_bytes() == mirror.read_bytes()


def test_command_md_mirror_byte_identical():
    canonical = REPO_ROOT / "commands" / "vg" / "meta-memory.md"
    mirror = REPO_ROOT / ".claude" / "commands" / "vg" / "meta-memory.md"
    if not mirror.exists():
        return
    assert canonical.read_bytes() == mirror.read_bytes()
