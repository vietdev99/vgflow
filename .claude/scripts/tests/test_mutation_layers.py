"""
B12.1 — mutation-layers.py tests.

Extends R7 from generated-specs-only → all *.spec.ts with mutation
keywords. Catches ghost-save bugs (toast shown but reload loses data).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = REPO_ROOT / ".claude" / "scripts" / "validators" / "mutation-layers.py"


def _setup(tmp_path: Path, specs: dict[str, str]) -> Path:
    """Build repo with apps/web/e2e/*.spec.ts + narration strings."""
    for rel, content in specs.items():
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

    (tmp_path / ".vg" / "phases" / "09-test").mkdir(parents=True)
    return tmp_path


def _run(repo: Path, extra_args: list[str] | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(repo)
    args = [sys.executable, str(VALIDATOR), "--phase", "9"] + (extra_args or [])
    return subprocess.run(args, cwd=repo, capture_output=True, text=True,
                          timeout=30, env=env)


def _parse(stdout: str) -> dict:
    for line in reversed(stdout.splitlines()):
        if line.strip().startswith("{"):
            return json.loads(line.strip())
    raise AssertionError(f"no JSON:\n{stdout}")


# ─────────────────────────────────────────────────────────────────────────

SPEC_FULL_3_LAYERS = """
test('create campaign creates successfully', async ({ page }) => {
  await page.getByRole('button', { name: 'Create' }).click();
  await page.getByLabel('Name').fill('Test');
  await page.getByRole('button', { name: 'Save' }).click();

  // Layer 1: toast
  await expect(page.getByRole('status')).toContainText(/success|created/i);

  // Layer 2: network settle
  await page.waitForLoadState('networkidle');

  // Layer 3: persist verify
  await page.reload();
  await expect(page.getByText('Test')).toBeVisible();
});
"""

SPEC_ONLY_TOAST = """
test('submit form quickly', async ({ page }) => {
  await page.getByRole('button', { name: 'Submit' }).click();
  await expect(page.getByRole('status')).toContainText('saved');
});
"""

SPEC_ONLY_PERSIST = """
test('update settings reload and check', async ({ page }) => {
  await page.getByRole('button', { name: 'Update' }).click();
  await page.reload();
});
"""

SPEC_NON_MUTATION = """
test('view dashboard renders metrics', async ({ page }) => {
  await page.goto('/dashboard');
  await expect(page.getByText('Revenue')).toBeVisible();
});
"""


def test_full_3_layers_passes(tmp_path):
    repo = _setup(tmp_path, {"apps/web/e2e/good.spec.ts": SPEC_FULL_3_LAYERS})
    r = _run(repo)
    out = _parse(r.stdout)
    assert r.returncode == 0
    assert out["verdict"] == "PASS"


def test_only_toast_blocks(tmp_path):
    repo = _setup(tmp_path, {"apps/web/e2e/bad.spec.ts": SPEC_ONLY_TOAST})
    r = _run(repo)
    out = _parse(r.stdout)
    assert r.returncode == 1
    # Missing network + persist
    msg = json.dumps(out["evidence"])
    assert "network" in msg and "persist" in msg


def test_only_persist_blocks(tmp_path):
    repo = _setup(tmp_path, {"apps/web/e2e/bad2.spec.ts": SPEC_ONLY_PERSIST})
    r = _run(repo)
    out = _parse(r.stdout)
    assert r.returncode == 1
    msg = json.dumps(out["evidence"])
    assert "toast" in msg and "network" in msg


def test_non_mutation_spec_ignored(tmp_path):
    """Read-only specs don't need mutation layers."""
    repo = _setup(tmp_path, {"apps/web/e2e/read.spec.ts": SPEC_NON_MUTATION})
    r = _run(repo)
    out = _parse(r.stdout)
    assert r.returncode == 0
    assert out["verdict"] == "PASS"


def test_allow_missing_flag_warns_not_blocks(tmp_path):
    repo = _setup(tmp_path, {"apps/web/e2e/bad.spec.ts": SPEC_ONLY_TOAST})
    r = _run(repo, extra_args=["--allow-missing"])
    out = _parse(r.stdout)
    assert r.returncode == 0  # warn, not block
    assert out["verdict"] == "WARN"


def test_no_specs_skips(tmp_path):
    (tmp_path / ".vg" / "phases" / "09-test").mkdir(parents=True)
    src = REPO_ROOT / ".claude" / "commands" / "vg" / "_shared"
    dst = tmp_path / ".claude" / "commands" / "vg" / "_shared"
    dst.mkdir(parents=True, exist_ok=True)
    for name in ("narration-strings.yaml", "narration-strings-validators.yaml"):
        s = src / name
        if s.exists():
            (dst / name).write_text(s.read_text(encoding="utf-8"),
                                    encoding="utf-8")
    r = _run(tmp_path)
    assert r.returncode == 0


def test_mixed_specs_one_bad_blocks_all(tmp_path):
    """One bad spec among good ones still blocks overall."""
    repo = _setup(tmp_path, {
        "apps/web/e2e/good.spec.ts": SPEC_FULL_3_LAYERS,
        "apps/web/e2e/bad.spec.ts": SPEC_ONLY_TOAST,
        "apps/web/e2e/read.spec.ts": SPEC_NON_MUTATION,
    })
    r = _run(repo)
    out = _parse(r.stdout)
    assert r.returncode == 1
    assert out["verdict"] == "BLOCK"


def test_registered_in_test_dispatcher():
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
    assert "mutation-layers" in mod.COMMAND_VALIDATORS.get("vg:test", [])
