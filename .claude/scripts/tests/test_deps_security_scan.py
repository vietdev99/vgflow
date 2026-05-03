"""
B8.1 — deps-security-scan.py regression tests.

Covers gap D1 (CVE scanning). Tests mix unit-level parser logic with
end-to-end integration via subprocess + --skip flags.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
VALIDATOR = REPO_ROOT / ".claude" / "scripts" / "validators" / "deps-security-scan.py"


@pytest.fixture(scope="module")
def deps_mod():
    """Import validator as a module for unit-level parser tests."""
    spec = importlib.util.spec_from_file_location(
        "deps_security_scan", VALIDATOR,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["deps_security_scan"] = mod
    spec.loader.exec_module(mod)
    return mod


def _copy_strings(tmp_path: Path) -> None:
    """Make tmp_path look like a repo for _i18n lookups."""
    src = REPO_ROOT / ".claude" / "commands" / "vg" / "_shared"
    dst = tmp_path / ".claude" / "commands" / "vg" / "_shared"
    dst.mkdir(parents=True, exist_ok=True)
    for name in ("narration-strings.yaml", "narration-strings-validators.yaml"):
        s = src / name
        if s.exists():
            (dst / name).write_text(s.read_text(encoding="utf-8"),
                                    encoding="utf-8")


def _run(tmp_path: Path, *args: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(tmp_path)
    return subprocess.run(
        [sys.executable, str(VALIDATOR), *args],
        cwd=tmp_path, capture_output=True, text=True, timeout=30, env=env,
    )


# ─────────────────────────────────────────────────────────────────────────

def test_severity_ge(deps_mod):
    assert deps_mod._severity_ge("critical", "high") is True
    assert deps_mod._severity_ge("high", "high") is True
    assert deps_mod._severity_ge("moderate", "high") is False
    assert deps_mod._severity_ge("low", "moderate") is False
    assert deps_mod._severity_ge("unknown", "high") is False


def test_parse_npm_audit_v7_shape(deps_mod):
    sample = json.dumps({
        "vulnerabilities": {
            "lodash": {
                "severity": "critical",
                "via": [
                    {"source": 1234, "title": "Prototype pollution",
                     "url": "https://npmjs.com/advisories/1234"}
                ],
                "fixAvailable": True,
            },
            "axios": {
                "severity": "moderate",
                "via": [{"source": 5678, "title": "SSRF"}],
                "fixAvailable": False,
            },
        }
    })
    vulns = deps_mod._parse_npm_audit(sample)
    assert len(vulns) == 2
    sevs = sorted(v["severity"] for v in vulns)
    assert sevs == ["critical", "moderate"]


def test_parse_pip_audit_shape(deps_mod):
    sample = json.dumps({
        "dependencies": [
            {
                "name": "urllib3",
                "vulns": [{
                    "id": "PYSEC-2023-01",
                    "description": "Authorization bypass",
                    "fix_versions": ["2.0.1"],
                }]
            }
        ]
    })
    vulns = deps_mod._parse_pip_audit(sample)
    assert len(vulns) == 1
    assert vulns[0]["id"] == "PYSEC-2023-01"
    assert vulns[0]["package"] == "urllib3"


def test_no_ecosystems_passes(tmp_path):
    """No package.json, no requirements.txt → skip silently."""
    _copy_strings(tmp_path)
    r = _run(tmp_path, "--skip-npm", "--skip-python")
    assert r.returncode == 0


def test_skip_flags_bypass_scanners(tmp_path):
    """With both skip flags, no scanner runs → PASS."""
    _copy_strings(tmp_path)
    (tmp_path / "package.json").write_text('{"name": "x"}', encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("flask\n", encoding="utf-8")
    r = _run(tmp_path, "--skip-npm", "--skip-python")
    assert r.returncode == 0


def test_waiver_match(deps_mod, tmp_path):
    """_waiver_matches suppresses matching id+package; expired ones don't."""
    waivers = [
        {"id": "CVE-2024-0001", "package": "x", "reason": "no fix yet",
         "expires": "2099-12-31"},
        {"id": "CVE-2020-9999", "package": "y", "reason": "old",
         "expires": "2020-01-01"},
    ]
    assert deps_mod._waiver_matches("CVE-2024-0001", "x", waivers) is True
    assert deps_mod._waiver_matches("CVE-2020-9999", "y", waivers) is False  # expired
    assert deps_mod._waiver_matches("CVE-2024-0001", "z", waivers) is False  # wrong pkg
    assert deps_mod._waiver_matches("CVE-9999-9999", "x", waivers) is False  # unknown id


def test_detect_ecosystems_node(tmp_path, deps_mod, monkeypatch):
    monkeypatch.setenv("VG_REPO_ROOT", str(tmp_path))
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    (tmp_path / "pnpm-lock.yaml").write_text("lockfile: 6.0\n", encoding="utf-8")
    # Re-resolve REPO_ROOT in module
    deps_mod.REPO_ROOT = tmp_path
    eco = deps_mod._detect_ecosystems()
    assert "pnpm" in eco


def test_detect_ecosystems_python(tmp_path, deps_mod):
    deps_mod.REPO_ROOT = tmp_path
    (tmp_path / "requirements.txt").write_text("django\n", encoding="utf-8")
    eco = deps_mod._detect_ecosystems()
    assert "python" in eco


def test_vn_narration_keys_resolve(tmp_path):
    """Verify the cve_blocking key resolves to VN text via _i18n.t()."""
    _copy_strings(tmp_path)
    sys.path.insert(0, str(REPO_ROOT / ".claude" / "scripts" / "validators"))
    import _i18n
    _i18n._reset_cache_for_tests()
    # Point helper at the fake repo so it loads our copied strings
    os.environ["VG_REPO_ROOT"] = str(tmp_path)
    # Write a vg.config.md with vi locale
    (tmp_path / ".claude").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".claude" / "vg.config.md").write_text(
        "narration:\n  locale: \"vi\"\n  fallback_locale: \"en\"\n",
        encoding="utf-8",
    )
    _i18n._reset_cache_for_tests()
    msg = _i18n.t("deps_security.cve_blocking.message", count=3, threshold="high")
    # VN template: "{count} CVE (lỗ hổng công khai) với severity >= {threshold} ..."
    assert "CVE" in msg
    assert "lỗ hổng" in msg or "công khai" in msg, f"got: {msg}"
    assert "3" in msg
    # Cleanup env so other tests aren't affected
    del os.environ["VG_REPO_ROOT"]
    _i18n._reset_cache_for_tests()


def test_deps_security_scan_not_in_dispatcher():
    """deps-security-scan stays pre-push only (requires online CVE DB).
    secrets-scan moved to review+test dispatchers at SEC-1 (2026-04-23)
    because users running review/test saw zero security signal — that
    test is now in test_review_security_validators.py.
    """
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
    for cmd, validators in mod.COMMAND_VALIDATORS.items():
        assert "deps-security-scan" not in validators, (
            f"deps-security-scan should run pre-push only (CVE DB online "
            f"dependency). Remove from {cmd}."
        )
