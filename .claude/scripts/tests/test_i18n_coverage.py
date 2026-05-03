"""
B9.2 — i18n-coverage.py tests.

Static coverage scan: catches missing keys, cross-locale drift, and
hardcoded strings before review browser discovery.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
VALIDATOR = REPO_ROOT / ".claude" / "scripts" / "validators" / "i18n-coverage.py"


def _setup(tmp_path: Path, source_files: dict[str, str],
           locales: dict[str, dict]) -> Path:
    """Build repo with source + locale JSON files + narration strings."""
    for rel, content in source_files.items():
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content, encoding="utf-8")

    locales_dir = tmp_path / "apps" / "web" / "public" / "locales"
    locales_dir.mkdir(parents=True, exist_ok=True)
    for code, data in locales.items():
        (locales_dir / f"{code}.json").write_text(
            json.dumps(data), encoding="utf-8",
        )

    # Narration strings for _i18n.py
    src = REPO_ROOT / ".claude" / "commands" / "vg" / "_shared"
    dst = tmp_path / ".claude" / "commands" / "vg" / "_shared"
    dst.mkdir(parents=True, exist_ok=True)
    for name in ("narration-strings.yaml", "narration-strings-validators.yaml"):
        s = src / name
        if s.exists():
            (dst / name).write_text(s.read_text(encoding="utf-8"),
                                    encoding="utf-8")

    # Write vg.config.md with i18n section pointing to our default locale
    cfg = tmp_path / ".claude" / "vg.config.md"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(
        "---\ni18n:\n  enabled: true\n  default_locale: 'vi'\n"
        "  locales_dir: 'apps/web/public/locales'\n"
        "  block_on_missing_key: true\n"
        "  allow_hardcoded_threshold: 0.05\n---\n",
        encoding="utf-8",
    )

    # Git init for diff fallback
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
        if line.strip().startswith("{"):
            return json.loads(line.strip())
    raise AssertionError(f"no JSON:\n{stdout}")


# ─────────────────────────────────────────────────────────────────────────

def test_all_wrapped_all_keys_exist(tmp_path):
    repo = _setup(tmp_path, {
        "apps/web/src/Page.tsx": 'const x = t("campaigns.create");',
    }, {
        "vi": {"campaigns": {"create": "Tạo chiến dịch"}},
        "en": {"campaigns": {"create": "Create campaign"}},
    })
    r = _run(repo)
    out = _parse(r.stdout)
    assert r.returncode == 0, out
    assert out["verdict"] == "PASS"


def test_missing_key_blocks(tmp_path):
    repo = _setup(tmp_path, {
        "apps/web/src/Page.tsx": 'const x = t("campaigns.missing");',
    }, {
        "vi": {"campaigns": {"create": "Tạo"}},
    })
    r = _run(repo)
    out = _parse(r.stdout)
    assert r.returncode == 1
    assert any(e["type"] == "i18n_missing_keys" for e in out["evidence"])


def test_cross_locale_gap_blocks(tmp_path):
    repo = _setup(tmp_path, {
        "apps/web/src/Page.tsx": 'const x = t("a.b");',
    }, {
        "vi": {"a": {"b": "X", "c": "Y"}},  # extra key c
        "en": {"a": {"b": "X"}},             # missing c
    })
    r = _run(repo)
    out = _parse(r.stdout)
    assert r.returncode == 1
    assert any(e["type"] == "i18n_cross_locale_gaps" for e in out["evidence"])


def test_hardcoded_exceeds_threshold_blocks(tmp_path):
    # Many hardcoded labels, few t() calls → ratio > 0.05
    src = "\n".join([
        '<button>Submit</button>',
        '<div>Hello World</div>',
        '<span>Welcome back</span>',
        '<label>Username field</label>',
        '<p>Click here to continue</p>',
    ])
    repo = _setup(tmp_path, {
        "apps/web/src/Page.tsx": src,
    }, {
        "vi": {"a": {"b": "X"}},
    })
    r = _run(repo)
    out = _parse(r.stdout)
    assert r.returncode == 1
    assert any(e["type"] == "i18n_hardcoded_exceeds_threshold"
               for e in out["evidence"])


def test_hardcoded_under_threshold_warns(tmp_path):
    # 1 hardcoded out of many t() calls → under 5% threshold → WARN only
    calls = "\n".join([f'const x{i} = t("a.key{i}");' for i in range(30)])
    src = calls + '\n<div>Leaked Text</div>'
    locale = {"a": {f"key{i}": f"v{i}" for i in range(30)}}
    repo = _setup(tmp_path, {
        "apps/web/src/Page.tsx": src,
    }, {"vi": locale})
    r = _run(repo)
    out = _parse(r.stdout)
    assert r.returncode == 0
    # WARN surfaces advisory without BLOCK
    assert out["verdict"] in ("PASS", "WARN")


def test_no_locales_skips(tmp_path):
    """Project without locales dir → PASS silently (hasn't opted into i18n)."""
    # Manually setup without locales
    (tmp_path / "apps" / "web" / "src").mkdir(parents=True)
    (tmp_path / "apps" / "web" / "src" / "Page.tsx").write_text(
        '<div>Hello</div>', encoding="utf-8",
    )
    src = REPO_ROOT / ".claude" / "commands" / "vg" / "_shared"
    dst = tmp_path / ".claude" / "commands" / "vg" / "_shared"
    dst.mkdir(parents=True, exist_ok=True)
    for name in ("narration-strings.yaml", "narration-strings-validators.yaml"):
        s = src / name
        if s.exists():
            (dst / name).write_text(s.read_text(encoding="utf-8"),
                                    encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=str(tmp_path))
    subprocess.run(["git", "config", "user.email", "a@b.c"], cwd=str(tmp_path))
    subprocess.run(["git", "config", "user.name", "t"], cwd=str(tmp_path))
    subprocess.run(["git", "add", "-A"], cwd=str(tmp_path))
    subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=str(tmp_path))
    (tmp_path / ".vg" / "phases" / "09-test").mkdir(parents=True)

    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(tmp_path)
    r = subprocess.run(
        [sys.executable, str(VALIDATOR), "--phase", "9", "--commits", "1"],
        cwd=tmp_path, capture_output=True, text=True, timeout=15, env=env,
    )
    assert r.returncode == 0


def test_registered_in_review_dispatcher():
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
    assert "i18n-coverage" in mod.COMMAND_VALIDATORS.get("vg:review", [])
