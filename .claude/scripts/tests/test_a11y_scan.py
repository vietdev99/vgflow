"""
B9.1 — accessibility-scan.py tests.

Static WCAG 2.2 A/AA check: blocks serious/critical violations before
review phase 2b Haiku scanners run. Cheap pre-filter (<2s).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
VALIDATOR = REPO_ROOT / ".claude" / "scripts" / "validators" / "accessibility-scan.py"


def _setup(tmp_path: Path, files: dict[str, str]) -> Path:
    """Create a minimal repo with FE source files + narration strings."""
    (tmp_path / "apps" / "web" / "src").mkdir(parents=True)
    for rel, content in files.items():
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content, encoding="utf-8")

    src = REPO_ROOT / ".claude" / "commands" / "vg" / "_shared"
    dst = tmp_path / ".claude" / "commands" / "vg" / "_shared"
    dst.mkdir(parents=True, exist_ok=True)
    for name in ("narration-strings.yaml", "narration-strings-validators.yaml"):
        s = src / name
        if s.exists():
            (dst / name).write_text(s.read_text(encoding="utf-8"),
                                    encoding="utf-8")

    # Init git so git diff fallback doesn't crash
    subprocess.run(["git", "init", "-q"], cwd=str(tmp_path))
    subprocess.run(["git", "config", "user.email", "a@b.c"], cwd=str(tmp_path))
    subprocess.run(["git", "config", "user.name", "t"], cwd=str(tmp_path))
    subprocess.run(["git", "add", "-A"], cwd=str(tmp_path))
    subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=str(tmp_path))

    (tmp_path / ".vg" / "phases" / "09-test").mkdir(parents=True)
    return tmp_path


def _run(repo: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(repo)
    return subprocess.run(
        [sys.executable, str(VALIDATOR), "--phase", "9", "--commits", "1"],
        cwd=repo, capture_output=True, text=True, timeout=30, env=env,
    )


def _parse(stdout: str) -> dict:
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            return json.loads(line)
    raise AssertionError(f"no JSON output:\n{stdout}")


# ─────────────────────────────────────────────────────────────────────────

def test_clean_fe_passes(tmp_path):
    repo = _setup(tmp_path, {
        "apps/web/src/Good.tsx": (
            '<img src="/x.png" alt="logo" />\n'
            '<button aria-label="Close">X</button>\n'
            '<a href="/home">Home</a>\n'
        ),
    })
    r = _run(repo)
    out = _parse(r.stdout)
    assert r.returncode == 0
    assert out["verdict"] == "PASS"


def test_img_without_alt_blocks(tmp_path):
    repo = _setup(tmp_path, {
        "apps/web/src/Bad.tsx": '<img src="/logo.png" />',
    })
    r = _run(repo)
    out = _parse(r.stdout)
    assert r.returncode == 1
    assert out["verdict"] == "BLOCK"
    assert any(e["type"] == "a11y_block_violations" for e in out["evidence"])


def test_empty_button_blocks(tmp_path):
    repo = _setup(tmp_path, {
        "apps/web/src/Bad.tsx": "<button></button>",
    })
    r = _run(repo)
    out = _parse(r.stdout)
    assert r.returncode == 1
    assert "button-no-label" in r.stdout


def test_onclick_on_div_blocks(tmp_path):
    repo = _setup(tmp_path, {
        "apps/web/src/Bad.tsx": "<div onClick={foo}>Click me</div>",
    })
    r = _run(repo)
    out = _parse(r.stdout)
    assert r.returncode == 1
    assert "onclick-non-interactive" in r.stdout


def test_allowlist_suppresses(tmp_path):
    repo = _setup(tmp_path, {
        "apps/web/src/Bad.tsx": '<img src="/logo.png" />',
    })
    # Allowlist the path
    (repo / ".vg").mkdir(exist_ok=True)
    (repo / ".vg" / "a11y-allowlist.yml").write_text(
        'patterns:\n  - "apps/web/src/Bad.tsx"\n', encoding="utf-8",
    )
    r = _run(repo)
    out = _parse(r.stdout)
    assert r.returncode == 0
    assert out["verdict"] == "PASS"


def test_no_source_files_skips(tmp_path):
    """No matching FE files → PASS without running (other projects, docs)."""
    repo = _setup(tmp_path, {
        "README.md": "nothing to see",
    })
    r = _run(repo)
    out = _parse(r.stdout)
    assert r.returncode == 0
    assert out["verdict"] == "PASS"


def test_button_with_img_alt_implicit_label(tmp_path):
    """Button wrapping <img alt='X'> has implicit label — should pass."""
    repo = _setup(tmp_path, {
        "apps/web/src/Good.tsx":
            '<button><img src="/x.png" alt="Close"/></button>',
    })
    r = _run(repo)
    out = _parse(r.stdout)
    assert r.returncode == 0


def test_registered_in_review_dispatcher():
    """accessibility-scan must be in COMMAND_VALIDATORS[vg:review]."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "vg_orchestrator_main",
        REPO_ROOT / ".claude" / "scripts" / "vg-orchestrator" / "__main__.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["vg_orchestrator_main"] = mod
    try:
        spec.loader.exec_module(mod)
    except SystemExit:
        pass
    assert "accessibility-scan" in mod.COMMAND_VALIDATORS.get("vg:review", [])
