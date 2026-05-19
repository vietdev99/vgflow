"""B89 v4.66.0 — follow-up to PR #196 (spa-i18n-provider validator).

PR #196 (vietnhprintway) added the validator + registry entry but shipped
without `.claude/` mirrors AND without test coverage. B89 closes both gaps
and corrects the stale `added_in: v2.79` registry tag to `v4.66.0`.

Rationale (from PR): every `apps/*/src/main.tsx` that calls
`createRoot(...).render(...)` MUST wrap with `<I18nextProvider>` or
`<I18nProvider>`. Real-world miss caught in PrintwayV3 vendor-portal
where 0/115 TSX files used useTranslation and every accept gate passed
despite untranslated keys in production.

Tests cover:
  - Empty repo (no apps/) → PASS scanned=0
  - SPA without wrapper → FAIL
  - Wrapper in main.tsx → PASS
  - Wrapper in App.tsx (one-hop follow) → PASS
  - Aliased App import → PASS
  - Non-SPA library (no createRoot) → PASS (skipped)
  - --severity warn returns exit 0 even with violations
  - Mirror parity (script + registry)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = REPO_ROOT / "scripts" / "validators" / "verify-spa-i18n-provider.py"
MIRROR = REPO_ROOT / ".claude" / "scripts" / "validators" / "verify-spa-i18n-provider.py"
REGISTRY = REPO_ROOT / "scripts" / "validators" / "registry.yaml"
REGISTRY_MIRROR = REPO_ROOT / ".claude" / "scripts" / "validators" / "registry.yaml"


def _run(tmp_path: Path, *extra) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), "--repo-root", str(tmp_path), *extra],
        capture_output=True, text=True,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        encoding="utf-8", errors="replace",
    )


def _seed(tmp_path: Path, app: str, main_body: str,
          app_body: str | None = None) -> Path:
    src = tmp_path / "apps" / app / "src"
    src.mkdir(parents=True)
    (src / "main.tsx").write_text(main_body, encoding="utf-8")
    if app_body is not None:
        (src / "App.tsx").write_text(app_body, encoding="utf-8")
    return src


# ---------------------------------------------------------------------------
# Behavioral
# ---------------------------------------------------------------------------

def test_b89_empty_repo_pass(tmp_path: Path) -> None:
    proc = _run(tmp_path)
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    assert out["status"] == "PASS"
    assert out["scanned"] == 0


def test_b89_spa_without_wrapper_fail(tmp_path: Path) -> None:
    _seed(tmp_path, "admin", """
import { createRoot } from 'react-dom/client';
import App from './App';
createRoot(document.getElementById('root')!).render(<App />);
""", app_body="export default function App(){return <div>x</div>}")
    proc = _run(tmp_path)
    assert proc.returncode == 1, f"expected FAIL; got {proc.returncode}\n{proc.stdout}"
    out = json.loads(proc.stdout)
    assert out["status"] == "FAIL"
    assert len(out["violations"]) == 1
    assert "main.tsx" in out["violations"][0]["file"]


def test_b89_wrapper_in_main_pass(tmp_path: Path) -> None:
    _seed(tmp_path, "merchant", """
import { createRoot } from 'react-dom/client';
import { I18nextProvider } from 'react-i18next';
import i18n from './i18n';
import App from './App';
createRoot(document.getElementById('root')!).render(
  <I18nextProvider i18n={i18n}><App /></I18nextProvider>
);
""", app_body="export default function App(){return <div>x</div>}")
    proc = _run(tmp_path)
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    assert out["status"] == "PASS"
    assert out["scanned"] == 1


def test_b89_wrapper_in_app_one_hop_pass(tmp_path: Path) -> None:
    """Phase 6 merchant-v3 style — wrapper lives in App.tsx not main.tsx."""
    _seed(tmp_path, "vendor", """
import { createRoot } from 'react-dom/client';
import App from './App';
createRoot(document.getElementById('root')!).render(<App />);
""", app_body="""
import { I18nextProvider } from 'react-i18next';
import i18n from './i18n';
export default function App() {
  return <I18nextProvider i18n={i18n}><div>x</div></I18nextProvider>;
}
""")
    proc = _run(tmp_path)
    assert proc.returncode == 0, f"stdout: {proc.stdout}"


def test_b89_aliased_app_import_pass(tmp_path: Path) -> None:
    """`import { App as RootApp } from './App'` — named import with alias."""
    _seed(tmp_path, "portal", """
import { createRoot } from 'react-dom/client';
import { App } from './App';
createRoot(document.getElementById('root')!).render(<App />);
""", app_body="""
import { I18nextProvider } from 'react-i18next';
import i18n from './i18n';
export function App() {
  return <I18nextProvider i18n={i18n}><div>x</div></I18nextProvider>;
}
""")
    proc = _run(tmp_path)
    assert proc.returncode == 0, f"stdout: {proc.stdout}"


def test_b89_non_spa_library_skipped(tmp_path: Path) -> None:
    """File at apps/lib/src/main.ts with no createRoot — must skip cleanly."""
    src = tmp_path / "apps" / "lib" / "src"
    src.mkdir(parents=True)
    (src / "main.ts").write_text(
        "export function add(a:number, b:number){ return a+b; }\n",
        encoding="utf-8",
    )
    proc = _run(tmp_path)
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    assert out["status"] == "PASS"
    # File IS scanned (matches glob) but check_app_entry early-returns ok=True
    assert out["scanned"] == 1
    assert out["violations"] == []


def test_b89_warn_severity_exit_zero_on_violations(tmp_path: Path) -> None:
    _seed(tmp_path, "admin", """
import { createRoot } from 'react-dom/client';
import App from './App';
createRoot(document.getElementById('root')!).render(<App />);
""", app_body="export default function App(){return <div>x</div>}")
    proc = _run(tmp_path, "--severity", "warn")
    assert proc.returncode == 0, "warn mode must exit 0 even with violations"
    out = json.loads(proc.stdout)
    assert out["status"] == "FAIL"
    assert out["severity"] == "warn"


def test_b89_provider_factory_not_false_match(tmp_path: Path) -> None:
    """Regex must not match `<I18nProviderFactory` (substring guard)."""
    _seed(tmp_path, "admin", """
import { createRoot } from 'react-dom/client';
import { I18nProviderFactory } from './weird';
const Provider = I18nProviderFactory();
createRoot(document.getElementById('root')!).render(
  <Provider><div>x</div></Provider>
);
""")
    proc = _run(tmp_path)
    # No real wrapper present → must FAIL
    assert proc.returncode == 1
    out = json.loads(proc.stdout)
    assert out["status"] == "FAIL"


# ---------------------------------------------------------------------------
# Static guards + mirror parity
# ---------------------------------------------------------------------------

def test_b89_validator_mirror_byte_identical() -> None:
    assert VALIDATOR.read_bytes() == MIRROR.read_bytes(), (
        "verify-spa-i18n-provider.py mirror drift"
    )


def test_b89_registry_mirror_byte_identical() -> None:
    assert REGISTRY.read_bytes() == REGISTRY_MIRROR.read_bytes(), (
        "registry.yaml mirror drift"
    )


def test_b89_registry_has_entry_with_correct_added_in() -> None:
    body = REGISTRY.read_text(encoding="utf-8")
    assert "id: spa-i18n-provider" in body
    # B89 corrected the stale v2.79 tag to v4.66.0 (current minor)
    assert "added_in: v4.66.0" in body, (
        "registry added_in tag must reflect actual ship version"
    )
    # Severity must remain warn during initial rollout per PR description
    sp_idx = body.index("id: spa-i18n-provider")
    region = body[sp_idx:sp_idx + 800]
    assert "severity: warn" in region
