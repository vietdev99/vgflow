"""Tests for scripts/codegen-fixture-inject.py — Codex-HIGH-3 fix."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "codegen-fixture-inject.py"


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--repo-root", str(repo), *args],
        env={"VG_REPO_ROOT": str(repo), "PATH": "/usr/bin:/bin",
             "PYTHONPATH": str(REPO_ROOT / "scripts")},
        capture_output=True, text=True, timeout=30,
    )


def _phase_with_cache(tmp_path: Path, name: str, entries: dict) -> Path:
    phase_dir = tmp_path / ".vg" / "phases" / name
    phase_dir.mkdir(parents=True, exist_ok=True)
    (phase_dir / "FIXTURES-CACHE.json").write_text(
        json.dumps({"schema_version": "1.0", "entries": entries}, indent=2),
        encoding="utf-8",
    )
    return phase_dir


def test_injects_fixture_into_simple_spec(tmp_path):
    _phase_with_cache(tmp_path, "01.0-x", {
        "G-10": {"captured": {"pending_id": "p7", "amount": 0.01,
                                "tags": ["alpha", "beta"]}},
    })
    spec = tmp_path / "test.spec.ts"
    spec.write_text(
        "import { test, expect } from '@playwright/test';\n\n"
        "test('approve topup', async ({ page }) => {\n"
        "  await page.goto('/admin/topup');\n"
        "});\n",
        encoding="utf-8",
    )
    result = _run(tmp_path, "--phase", "1.0", "--goal", "G-10",
                   "--spec", str(spec))
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert len(out["injected"]) == 1
    assert out["injected"][0]["action"] == "injected"

    text = spec.read_text()
    assert "VGFLOW_FIXTURE_INJECTED" in text
    assert 'pending_id: "p7"' in text
    assert "amount: 0.01" in text
    assert '["alpha", "beta"]' in text
    assert "as const;" in text


def test_idempotent_replace_existing_block(tmp_path):
    _phase_with_cache(tmp_path, "01.0-x", {
        "G-10": {"captured": {"pending_id": "p1"}},
    })
    spec = tmp_path / "test.spec.ts"
    spec.write_text(
        "import { test } from '@playwright/test';\n\n"
        "test('x', async () => {});\n",
        encoding="utf-8",
    )
    # First inject
    r1 = _run(tmp_path, "--phase", "1.0", "--goal", "G-10", "--spec", str(spec))
    assert r1.returncode == 0
    text1 = spec.read_text()

    # Update cache, second inject — should REPLACE not stack
    _phase_with_cache(tmp_path, "01.0-x", {
        "G-10": {"captured": {"pending_id": "p2"}},  # different value
    })
    r2 = _run(tmp_path, "--phase", "1.0", "--goal", "G-10", "--spec", str(spec))
    out2 = json.loads(r2.stdout)
    assert out2["injected"][0]["action"] == "replaced"

    text2 = spec.read_text()
    # Only one block (count sentinels)
    assert text2.count("VGFLOW_FIXTURE_INJECTED — DO NOT EDIT") == 1
    assert 'pending_id: "p2"' in text2
    assert 'pending_id: "p1"' not in text2


def test_inject_after_imports_not_at_very_top(tmp_path):
    _phase_with_cache(tmp_path, "01.0-x", {
        "G-10": {"captured": {"id": "x"}},
    })
    spec = tmp_path / "test.spec.ts"
    spec.write_text(
        "// header comment\n"
        "import { test } from '@playwright/test';\n"
        "import { other } from './helpers';\n"
        "\n"
        "test('x', async () => {});\n",
        encoding="utf-8",
    )
    _run(tmp_path, "--phase", "1.0", "--goal", "G-10", "--spec", str(spec))
    text = spec.read_text()
    # The fixture block should appear AFTER the imports
    sentinel_pos = text.index("VGFLOW_FIXTURE_INJECTED")
    last_import_pos = text.rindex("import")
    assert sentinel_pos > last_import_pos


def test_skip_when_no_captured_store(tmp_path):
    _phase_with_cache(tmp_path, "01.0-x", {
        "G-10": {"lease": {"owner_session": "x"}},  # no `captured` key
    })
    spec = tmp_path / "test.spec.ts"
    spec.write_text("test('x', async () => {});\n", encoding="utf-8")
    result = _run(tmp_path, "--phase", "1.0", "--goal", "G-10", "--spec", str(spec))
    out = json.loads(result.stdout)
    assert out["injected"] == []
    assert len(out["skipped"]) == 1
    assert "no captured store" in out["skipped"][0]["reason"]
    assert "VGFLOW_FIXTURE_INJECTED" not in spec.read_text()


def test_dry_run_does_not_modify_file(tmp_path):
    _phase_with_cache(tmp_path, "01.0-x", {
        "G-10": {"captured": {"id": "x"}},
    })
    spec = tmp_path / "test.spec.ts"
    original = "test('x', async () => {});\n"
    spec.write_text(original, encoding="utf-8")
    result = _run(tmp_path, "--phase", "1.0", "--goal", "G-10",
                   "--spec", str(spec), "--dry-run")
    assert result.returncode == 0
    assert spec.read_text() == original


def test_sweep_mode_finds_specs(tmp_path):
    _phase_with_cache(tmp_path, "01.0-x", {
        "G-10": {"captured": {"id": "p1"}},
        "G-11": {"captured": {"id": "p2"}},
    })
    e2e = tmp_path / "e2e"
    e2e.mkdir()
    (e2e / "1.0-G-10.spec.ts").write_text(
        "import { test } from '@playwright/test';\n", encoding="utf-8",
    )
    (e2e / "1.0-G-11.spec.ts").write_text(
        "import { test } from '@playwright/test';\n", encoding="utf-8",
    )
    result = _run(tmp_path, "--phase", "1.0", "--sweep", str(e2e))
    out = json.loads(result.stdout)
    assert len(out["injected"]) == 2
    for spec in (e2e / "1.0-G-10.spec.ts", e2e / "1.0-G-11.spec.ts"):
        assert "VGFLOW_FIXTURE_INJECTED" in spec.read_text()


def test_sweep_skips_unrelated_specs(tmp_path):
    _phase_with_cache(tmp_path, "01.0-x", {
        "G-10": {"captured": {"id": "p1"}},
    })
    e2e = tmp_path / "e2e"
    e2e.mkdir()
    spec_other = e2e / "smoke.spec.ts"  # no goal id in name
    spec_other.write_text("test('x', async () => {});\n", encoding="utf-8")
    result = _run(tmp_path, "--phase", "1.0", "--sweep", str(e2e))
    out = json.loads(result.stdout)
    assert out["injected"] == []
    assert "VGFLOW_FIXTURE_INJECTED" not in spec_other.read_text()


def test_typescript_safe_key_quoting(tmp_path):
    _phase_with_cache(tmp_path, "01.0-x", {
        "G-10": {"captured": {
            "valid_id": "x",
            "kebab-key": "y",     # invalid TS identifier → must quote
            "with space": "z",
        }},
    })
    spec = tmp_path / "test.spec.ts"
    spec.write_text("test('x', async () => {});\n", encoding="utf-8")
    _run(tmp_path, "--phase", "1.0", "--goal", "G-10", "--spec", str(spec))
    text = spec.read_text()
    assert "valid_id:" in text  # unquoted valid identifier
    assert '"kebab-key":' in text  # quoted invalid identifier
    assert '"with space":' in text


def test_missing_spec_raises_error(tmp_path):
    _phase_with_cache(tmp_path, "01.0-x", {
        "G-10": {"captured": {"id": "x"}},
    })
    result = _run(tmp_path, "--phase", "1.0", "--goal", "G-10",
                   "--spec", str(tmp_path / "missing.spec.ts"))
    out = json.loads(result.stdout)
    assert len(out["errors"]) == 1
    assert "not found" in out["errors"][0]["error"]


def test_phase_not_found_returns_1(tmp_path):
    (tmp_path / ".vg" / "phases").mkdir(parents=True)
    spec = tmp_path / "x.spec.ts"
    spec.write_text("", encoding="utf-8")
    result = _run(tmp_path, "--phase", "99.99", "--goal", "G-1",
                   "--spec", str(spec))
    assert result.returncode == 1


# ─── Codex-HIGH-3-bis: --substitute literal-replacement pass ─────────


def test_substitute_replaces_quoted_string_with_fixture_ref(tmp_path):
    """Codex-HIGH-3-bis: codegen often emits hard-coded captured values
    as exact-string equality checks. --substitute swaps WHOLE-STRING
    quoted occurrences for FIXTURE.x references. (Substring/template
    literal substitution is out of scope — too brittle without AST.)"""
    _phase_with_cache(tmp_path, "01.0-x", {
        "G-10": {"captured": {
            "pending_id": "p7e9-2026-05-02-abc-uuid",
            "amount": 0.01,
        }},
    })
    spec = tmp_path / "test.spec.ts"
    spec.write_text(
        "import { test } from '@playwright/test';\n\n"
        "test('approve', async ({ page }) => {\n"
        "  const id = 'p7e9-2026-05-02-abc-uuid';\n"
        "  expect(received).toBe('p7e9-2026-05-02-abc-uuid');\n"
        '  expect(other).toBe("p7e9-2026-05-02-abc-uuid");\n'
        "});\n",
        encoding="utf-8",
    )
    result = _run(tmp_path, "--phase", "1.0", "--goal", "G-10",
                   "--spec", str(spec), "--substitute")
    assert result.returncode == 0
    out = json.loads(result.stdout)
    # 3 whole-string quoted matches: 'X', 'X', "X"
    assert out["injected"][0]["substitutions"] == 3, out

    text = spec.read_text()
    assert "FIXTURE.pending_id" in text
    assert "p7e9-2026-05-02-abc-uuid" in text  # still in FIXTURE block
    # Body no longer has the bare quoted literal outside the const block
    body_after_block = text.split("VGFLOW_FIXTURE_INJECTED_END", 1)[1]
    assert "'p7e9-2026-05-02-abc-uuid'" not in body_after_block
    assert '"p7e9-2026-05-02-abc-uuid"' not in body_after_block


def test_substitute_skips_short_values(tmp_path):
    """Conservative guard: 'ok' is too short — risk of coincidental match."""
    _phase_with_cache(tmp_path, "01.0-x", {
        "G-10": {"captured": {"status": "ok"}},
    })
    spec = tmp_path / "test.spec.ts"
    spec.write_text(
        "test('x', async () => { expect(result).toBe('ok'); });\n",
        encoding="utf-8",
    )
    _run(tmp_path, "--phase", "1.0", "--goal", "G-10",
          "--spec", str(spec), "--substitute")
    text = spec.read_text()
    # 'ok' should NOT be substituted (too short, ambiguous)
    assert "expect(result).toBe('ok')" in text
    assert "FIXTURE.status" not in text.split("VGFLOW_FIXTURE_INJECTED_END", 1)[1]


def test_substitute_picks_up_sentinel_prefixed_short_strings(tmp_path):
    """VG_FIXTURE_M1 is short but sentinel-prefixed — always safe."""
    _phase_with_cache(tmp_path, "01.0-x", {
        "G-10": {"captured": {"merchant": "VG_FIXTURE_M1"}},
    })
    spec = tmp_path / "test.spec.ts"
    spec.write_text(
        'test("x", async () => { mockApi("VG_FIXTURE_M1"); });\n',
        encoding="utf-8",
    )
    _run(tmp_path, "--phase", "1.0", "--goal", "G-10",
          "--spec", str(spec), "--substitute")
    text = spec.read_text()
    assert "FIXTURE.merchant" in text
    body = text.split("VGFLOW_FIXTURE_INJECTED_END", 1)[1]
    assert '"VG_FIXTURE_M1"' not in body  # substituted


def test_substitute_does_not_modify_inside_fixture_block(tmp_path):
    """Substitution must NOT recurse into the FIXTURE const block itself
    (would create `FIXTURE.x: FIXTURE.x` infinite loop)."""
    _phase_with_cache(tmp_path, "01.0-x", {
        "G-10": {"captured": {"pending_id": "p7e9-uuid-with-hyphens-here"}},
    })
    spec = tmp_path / "test.spec.ts"
    spec.write_text(
        "test('x', async () => { use('p7e9-uuid-with-hyphens-here'); });\n",
        encoding="utf-8",
    )
    _run(tmp_path, "--phase", "1.0", "--goal", "G-10",
          "--spec", str(spec), "--substitute")
    text = spec.read_text()
    # FIXTURE block content unchanged (still has the literal)
    fixture_block = text.split("VGFLOW_FIXTURE_INJECTED")[1].split(
        "VGFLOW_FIXTURE_INJECTED_END")[0]
    assert "p7e9-uuid-with-hyphens-here" in fixture_block
    # Body got substitution
    body = text.split("VGFLOW_FIXTURE_INJECTED_END", 1)[1]
    assert "FIXTURE.pending_id" in body


def test_substitute_handles_uuid_values(tmp_path):
    _phase_with_cache(tmp_path, "01.0-x", {
        "G-10": {"captured": {"id": "12345678-1234-1234-1234-123456789abc"}},
    })
    spec = tmp_path / "test.spec.ts"
    spec.write_text(
        "test('x', async () => { use('12345678-1234-1234-1234-123456789abc'); });\n",
        encoding="utf-8",
    )
    result = _run(tmp_path, "--phase", "1.0", "--goal", "G-10",
                   "--spec", str(spec), "--substitute")
    out = json.loads(result.stdout)
    assert out["injected"][0]["substitutions"] >= 1


def test_substitute_disabled_by_default(tmp_path):
    """Without --substitute flag, no body changes happen."""
    _phase_with_cache(tmp_path, "01.0-x", {
        "G-10": {"captured": {"pending_id": "p7e9-distinct-uuid-value"}},
    })
    spec = tmp_path / "test.spec.ts"
    spec.write_text(
        "test('x', async () => { use('p7e9-distinct-uuid-value'); });\n",
        encoding="utf-8",
    )
    _run(tmp_path, "--phase", "1.0", "--goal", "G-10", "--spec", str(spec))
    text = spec.read_text()
    body = text.split("VGFLOW_FIXTURE_INJECTED_END", 1)[1]
    assert "'p7e9-distinct-uuid-value'" in body  # NOT substituted


def test_arg_validation(tmp_path):
    # Missing --goal/--spec/--sweep
    r1 = _run(tmp_path, "--phase", "1.0")
    assert r1.returncode != 0
    # --spec without --goal
    r2 = _run(tmp_path, "--phase", "1.0", "--spec", "x.spec.ts")
    assert r2.returncode != 0
    # --sweep + --goal mutually exclusive
    r3 = _run(tmp_path, "--phase", "1.0", "--sweep", "/tmp",
              "--goal", "G-1", "--spec", "x.spec.ts")
    assert r3.returncode != 0
