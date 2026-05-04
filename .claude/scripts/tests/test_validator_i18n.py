"""
B8.0 — validator i18n tests.

User mandate (2026-04-23): "ở tất cả các khâu, trả lời hoặc hiển thị
thông tin đều phải là ngôn ngữ loài người, cố gắng giải thích cụ thể
vấn đề, bằng ngôn ngữ được cài trong vg.config.md."

Tests:
  1. _i18n.t() returns Vietnamese when locale=vi (repo default).
  2. Switching to locale=en returns English.
  3. Unknown key → returns key literal (graceful, no crash).
  4. Template with placeholders interpolates correctly.
  5. End-to-end: commit-attribution.py BLOCK output contains VN text
     when locale=vi (proves retrofit wired through).
  6. End-to-end: verify-contract-runtime.py BLOCK output contains VN
     text when locale=vi.
  7. Each localized key has BOTH vi and en — no orphans.
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
VALIDATORS = REPO_ROOT / ".claude" / "scripts" / "validators"
sys.path.insert(0, str(VALIDATORS))


@pytest.fixture(autouse=True)
def _reset_cache():
    """Clear _i18n caches between tests so config changes take effect."""
    import _i18n
    _i18n._reset_cache_for_tests()
    yield
    _i18n._reset_cache_for_tests()


def _make_config(tmp_path: Path, locale: str, fallback: str = "en") -> Path:
    """Emit a minimal vg.config.md with just the narration block."""
    (tmp_path / ".claude").mkdir(parents=True, exist_ok=True)
    cfg = tmp_path / ".claude" / "vg.config.md"
    cfg.write_text(textwrap.dedent(f"""\
        # Fake vg.config.md for test

        narration:
          locale: "{locale}"
          fallback_locale: "{fallback}"
    """), encoding="utf-8")
    return cfg


# ─────────────────────────────────────────────────────────────────────────

def test_default_locale_returns_vietnamese(tmp_path, monkeypatch):
    """Repo default is locale=vi — t() must render Vietnamese."""
    monkeypatch.setenv("VG_REPO_ROOT", str(REPO_ROOT))
    import _i18n
    _i18n._reset_cache_for_tests()
    msg = _i18n.t("commit_attr.empty_message.message")
    # VN text has accents — "trống" has ống
    assert "trống" in msg or "ngôn ngữ" in msg or "commit" in msg.lower()
    # Must NOT be the English literal "Commit message is empty"
    assert msg != "Commit message is empty", (
        f"Expected VN, got English literal: {msg}"
    )


def test_english_locale_returns_english(tmp_path, monkeypatch):
    """Override locale=en → t() returns English templates."""
    _make_config(tmp_path, "en")
    monkeypatch.setenv("VG_REPO_ROOT", str(tmp_path))
    # Copy narration string tables into the fake repo for the helper to load
    _copy_string_tables(tmp_path)

    import _i18n
    _i18n._reset_cache_for_tests()
    msg = _i18n.t("commit_attr.empty_message.message")
    assert msg == "Commit message is empty", f"got: {msg}"


def test_unknown_key_returns_literal(tmp_path, monkeypatch):
    """Nonexistent key → return the key itself. No crash."""
    monkeypatch.setenv("VG_REPO_ROOT", str(REPO_ROOT))
    import _i18n
    _i18n._reset_cache_for_tests()
    result = _i18n.t("does.not.exist.at.all")
    assert result == "does.not.exist.at.all"


def test_placeholder_interpolation(tmp_path, monkeypatch):
    """Templates with {name} placeholders interpolate from kwargs."""
    monkeypatch.setenv("VG_REPO_ROOT", str(REPO_ROOT))
    import _i18n
    _i18n._reset_cache_for_tests()
    msg = _i18n.t(
        "commit_attr.phantom_citation.message",
        refs="D-99, G-42", phase="7.6",
    )
    assert "D-99" in msg
    assert "G-42" in msg
    assert "7.6" in msg


def test_missing_placeholder_returns_template(tmp_path, monkeypatch):
    """Template references {foo} but caller omits it → return template raw."""
    monkeypatch.setenv("VG_REPO_ROOT", str(REPO_ROOT))
    import _i18n
    _i18n._reset_cache_for_tests()
    # Should not raise even though refs/phase missing
    result = _i18n.t("commit_attr.phantom_citation.message")
    assert "{refs}" in result or "{phase}" in result or result  # no crash


def test_all_validator_keys_have_both_locales():
    """Every key in narration-strings-validators.yaml must have vi + en.
    Missing either is a content bug — catches authoring drift."""
    import yaml
    p = (REPO_ROOT / ".claude" / "commands" / "vg" / "_shared"
         / "narration-strings-validators.yaml")
    assert p.exists(), "validator strings file missing"
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}

    missing_vi: list[str] = []
    missing_en: list[str] = []

    def _walk(node, prefix=""):
        for k, v in node.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v, dict):
                if v and all(isinstance(vv, str) for vv in v.values()):
                    if "vi" not in v:
                        missing_vi.append(key)
                    if "en" not in v:
                        missing_en.append(key)
                else:
                    _walk(v, key)

    _walk(data)
    assert not missing_vi, f"keys missing vi: {missing_vi}"
    assert not missing_en, f"keys missing en: {missing_en}"


def test_e2e_commit_attr_emits_vietnamese(tmp_path):
    """End-to-end: commit-attribution.py on phantom D-XX → BLOCK with VN text."""
    _setup_i18n_repo(tmp_path, "vi")
    subprocess.run(["git", "init", "-q", "-b", "main"],
                   cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@x"],
                   cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"],
                   cwd=tmp_path, check=True)

    phase_dir = tmp_path / ".vg" / "phases" / "07.9-test"
    phase_dir.mkdir(parents=True)
    (phase_dir / "CONTEXT.md").write_text(
        "### D-01: only real decision\n", encoding="utf-8",
    )

    # Stage a code file + commit msg citing phantom D-99
    code = tmp_path / "apps" / "api" / "src" / "x.ts"
    code.parent.mkdir(parents=True)
    code.write_text("export const x = 1;\n", encoding="utf-8")
    subprocess.run(["git", "add", "apps/api/src/x.ts"],
                   cwd=tmp_path, check=True, capture_output=True)

    msg_file = tmp_path / "COMMIT_MSG"
    msg_file.write_text(
        "feat(7.9-01): x\n\nPer CONTEXT.md D-99\n", encoding="utf-8",
    )

    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(tmp_path)
    # Point repo at the real repo so config + strings load correctly
    # (tmp_path has no vg.config.md, so _i18n will default to vi anyway)
    r = subprocess.run(
        [sys.executable, str(VALIDATORS / "commit-attribution.py"),
         "--staged-only", "--msg-file", str(msg_file)],
        cwd=tmp_path, capture_output=True, text=True, timeout=30, env=env,
    )
    # Repo copy uses locale=vi. Expect distinctive VN phrases from
    # commit_attr.phantom_citation.message template.
    assert r.returncode == 1
    # JSON escapes non-ASCII as \uXXXX so check both raw + escaped forms.
    vn_markers = [
        "trích dẫn", "tr\\u00edch d\\u1eaf",       # "trích dẫn"
        "không tồn tại", "kh\\u00f4ng t\\u1ed3n",  # "không tồn tại"
        "KHÔNG tồn tại", "KH\\u00d4NG",            # uppercase variant
    ]
    assert any(m in r.stdout for m in vn_markers), (
        f"expected VN phantom-citation phrases, got:\n{r.stdout}"
    )


def test_e2e_contract_runtime_emits_vietnamese(tmp_path):
    """End-to-end: verify-contract-runtime.py on missing endpoint → VN text."""
    _setup_i18n_repo(tmp_path, "vi")
    phase_dir = tmp_path / ".vg" / "phases" / "07.9-test"
    phase_dir.mkdir(parents=True)
    (phase_dir / "API-CONTRACTS.md").write_text(
        "## POST /api/missing\n\nnot implemented\n", encoding="utf-8",
    )
    # Empty source tree
    (tmp_path / "apps" / "api" / "src").mkdir(parents=True)

    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(tmp_path)
    r = subprocess.run(
        [sys.executable, str(VALIDATORS / "verify-contract-runtime.py"),
         "--phase", "7.9"],
        cwd=tmp_path, capture_output=True, text=True, timeout=30, env=env,
    )
    # Empty apps/api/src triggers no_source_files branch whose VN template
    # starts "Không tìm thấy source file nào khớp globs".
    assert r.returncode in (0, 1)
    vn_markers = [
        "Không tìm thấy", "Kh\\u00f4ng t\\u00ecm th\\u1ea5y",
        "không thể verify", "kh\\u00f4ng th\\u1ec3 verify",
        "không có", "kh\\u00f4ng c\\u00f3",
    ]
    assert any(m in r.stdout for m in vn_markers), (
        f"expected VN contract phrases, got:\n{r.stdout}"
    )


# ─────────────────────────────────────────────────────────────────────────

def _copy_string_tables(dest_repo: Path) -> None:
    """Copy narration yaml files into a fake repo so _i18n can resolve them."""
    src = REPO_ROOT / ".claude" / "commands" / "vg" / "_shared"
    dst = dest_repo / ".claude" / "commands" / "vg" / "_shared"
    dst.mkdir(parents=True, exist_ok=True)
    for name in ("narration-strings.yaml", "narration-strings-validators.yaml"):
        s = src / name
        if s.exists():
            (dst / name).write_text(s.read_text(encoding="utf-8"),
                                    encoding="utf-8")


def _setup_i18n_repo(tmp_path: Path, locale: str = "vi") -> None:
    """Make tmp_path look enough like a repo for _i18n to resolve strings.
    Writes vg.config.md + copies narration tables."""
    _make_config(tmp_path, locale)
    _copy_string_tables(tmp_path)
