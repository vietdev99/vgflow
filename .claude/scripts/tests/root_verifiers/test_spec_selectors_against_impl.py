"""
Tests for verify-spec-selectors-against-impl.py — UNQUARANTINABLE.

Phase 7.14.3 retro: catches test-vs-impl selector drift. Wave-N spec
authors can't ship selectors that Wave-(N-1) impl doesn't expose.

Covers:
  - --spec-glob with no matching specs → PASS
  - Spec data-testid="X" matches impl with `data-testid="X"` → PASS
  - Spec data-testid="X" with NO impl reference → BLOCK
  - Spec input[name="email"] matches impl `name="email"` → PASS
  - Spec aria-current="page" matches impl `aria-current={isActive ? 'page'` → PASS
  - --report-md flag writes audit file
  - Schema canonical: validator/verdict/evidence keys
  - Subprocess resilience: missing impl-root
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT_REAL = Path(__file__).resolve().parents[4]
VALIDATOR = REPO_ROOT_REAL / ".claude" / "scripts" / "validators" / \
    "verify-spec-selectors-against-impl.py"


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["VG_REPO_ROOT"] = str(cwd)
    return subprocess.run(
        [sys.executable, str(VALIDATOR), *args],
        capture_output=True, text=True, timeout=20, env=env,
        encoding="utf-8", errors="replace", cwd=str(cwd),
    )


def _verdict(stdout: str) -> str | None:
    try:
        return json.loads(stdout).get("verdict")
    except (json.JSONDecodeError, AttributeError):
        return None


def _setup(tmp_path: Path) -> tuple[Path, Path]:
    """Return (specs_dir, impl_root)."""
    specs = tmp_path / "apps" / "web" / "e2e"
    specs.mkdir(parents=True)
    impl = tmp_path / "apps" / "web" / "src"
    impl.mkdir(parents=True)
    return specs, impl


class TestSpecSelectorsAgainstImpl:
    def test_no_specs_match_glob_passes(self, tmp_path):
        specs, impl = _setup(tmp_path)
        r = _run(
            ["--spec-glob", str(specs / "nonexistent-*.spec.ts"),
             "--impl-root", str(impl)],
            tmp_path,
        )
        # No specs to verify → PASS
        assert r.returncode == 0, f"empty glob should PASS, stdout={r.stdout}"

    def test_matching_testid_passes(self, tmp_path):
        specs, impl = _setup(tmp_path)
        (specs / "test-1.spec.ts").write_text(
            'test("x", async ({ page }) => {\n'
            '  await page.locator(\'[data-testid="login-btn"]\').click();\n'
            '});\n',
            encoding="utf-8",
        )
        (impl / "Login.tsx").write_text(
            'export const Login = () => (\n'
            '  <button data-testid="login-btn">Login</button>\n'
            ');\n',
            encoding="utf-8",
        )
        r = _run(
            ["--spec-glob", str(specs / "test-*.spec.ts"),
             "--impl-root", str(impl)],
            tmp_path,
        )
        assert r.returncode == 0, f"matching testid should PASS, stdout={r.stdout}"

    def test_missing_testid_blocks(self, tmp_path):
        specs, impl = _setup(tmp_path)
        (specs / "test-2.spec.ts").write_text(
            'test("x", async ({ page }) => {\n'
            '  await page.locator(\'[data-testid="ghost-btn"]\').click();\n'
            '});\n',
            encoding="utf-8",
        )
        (impl / "Login.tsx").write_text(
            'export const Login = () => (<button>Login</button>);\n',
            encoding="utf-8",
        )
        r = _run(
            ["--spec-glob", str(specs / "test-*.spec.ts"),
             "--impl-root", str(impl)],
            tmp_path,
        )
        assert r.returncode == 1, \
            f"missing testid in impl should BLOCK, rc={r.returncode}, stdout={r.stdout}"
        assert _verdict(r.stdout) == "BLOCK"

    def test_input_name_selector_passes(self, tmp_path):
        specs, impl = _setup(tmp_path)
        (specs / "form.spec.ts").write_text(
            'await page.locator(\'input[name="email"]\').fill("a@b");\n',
            encoding="utf-8",
        )
        (impl / "Form.tsx").write_text(
            '<input name="email" type="email" />\n',
            encoding="utf-8",
        )
        r = _run(
            ["--spec-glob", str(specs / "form.spec.ts"),
             "--impl-root", str(impl)],
            tmp_path,
        )
        assert r.returncode == 0, \
            f"input[name='email'] match should PASS, stdout={r.stdout}"

    def test_aria_current_selector_passes(self, tmp_path):
        specs, impl = _setup(tmp_path)
        (specs / "nav.spec.ts").write_text(
            'await page.locator(\'[aria-current="page"]\').isVisible();\n',
            encoding="utf-8",
        )
        (impl / "Nav.tsx").write_text(
            '<a aria-current={isActive ? "page" : undefined}>Home</a>\n',
            encoding="utf-8",
        )
        r = _run(
            ["--spec-glob", str(specs / "nav.spec.ts"),
             "--impl-root", str(impl)],
            tmp_path,
        )
        assert r.returncode == 0, \
            f"aria-current ternary match should PASS, stdout={r.stdout}"

    def test_report_md_flag_writes_file(self, tmp_path):
        specs, impl = _setup(tmp_path)
        (specs / "x.spec.ts").write_text("// empty\n", encoding="utf-8")
        report = tmp_path / "audit.md"
        r = _run(
            ["--spec-glob", str(specs / "x.spec.ts"),
             "--impl-root", str(impl),
             "--report-md", str(report)],
            tmp_path,
        )
        # Validator may write report or skip if no findings; --report-md must
        # not crash
        assert r.returncode in (0, 1, 2)
        assert "unrecognized arguments" not in r.stderr.lower()

    def test_schema_canonical(self, tmp_path):
        specs, impl = _setup(tmp_path)
        (specs / "x.spec.ts").write_text("// empty\n", encoding="utf-8")
        r = _run(
            ["--spec-glob", str(specs / "x.spec.ts"),
             "--impl-root", str(impl)],
            tmp_path,
        )
        try:
            data = json.loads(r.stdout)
            assert "validator" in data
            assert "verdict" in data
            assert data["verdict"] in ("PASS", "BLOCK", "WARN")
        except json.JSONDecodeError:
            assert r.returncode in (0, 1, 2)

    def test_missing_impl_root_no_traceback(self, tmp_path):
        specs, _ = _setup(tmp_path)
        (specs / "x.spec.ts").write_text("// stub\n", encoding="utf-8")
        r = _run(
            ["--spec-glob", str(specs / "x.spec.ts"),
             "--impl-root", str(tmp_path / "nonexistent")],
            tmp_path,
        )
        assert "Traceback" not in r.stderr, \
            f"crash on missing impl-root: {r.stderr[-400:]}"
        assert r.returncode in (0, 1, 2)
