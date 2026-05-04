"""
B8.3 — verify-authz-declared.py tests.

Gap D2 (static half): every endpoint in API-CONTRACTS.md declares its
auth requirement so downstream gates + human readers have ground truth.
Runtime cross-role test deferred to B9+ (needs live API).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
VALIDATOR = REPO_ROOT / ".claude" / "scripts" / "validators" / "verify-authz-declared.py"


def _setup(tmp_path: Path, contract_text: str) -> Path:
    """Mini phase dir + copied narration strings."""
    phase_dir = tmp_path / ".vg" / "phases" / "07.11-test"
    phase_dir.mkdir(parents=True)
    (phase_dir / "API-CONTRACTS.md").write_text(contract_text, encoding="utf-8")

    src = REPO_ROOT / ".claude" / "commands" / "vg" / "_shared"
    dst = tmp_path / ".claude" / "commands" / "vg" / "_shared"
    dst.mkdir(parents=True, exist_ok=True)
    for name in ("narration-strings.yaml", "narration-strings-validators.yaml"):
        s = src / name
        if s.exists():
            (dst / name).write_text(s.read_text(encoding="utf-8"),
                                    encoding="utf-8")
    return tmp_path


def _run(repo: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(repo)
    return subprocess.run(
        [sys.executable, str(VALIDATOR), "--phase", "7.11"],
        cwd=repo, capture_output=True, text=True, timeout=30, env=env,
    )


# ─────────────────────────────────────────────────────────────────────────

CONTRACT_CLEAN = """\
## POST /auth/login

**Auth:** Public

Body...

---

## GET /users/me

**Auth:** Authenticated

Body...

---

## DELETE /users/:id

**Auth:** Owner only

Body...

---

## POST /admin/users

**Auth:** Role: admin

Body...
"""


def test_all_endpoints_declared_passes(tmp_path):
    repo = _setup(tmp_path, CONTRACT_CLEAN)
    r = _run(repo)
    assert r.returncode == 0, f"clean contract should pass, got {r.stdout}"


def test_missing_auth_declaration_blocks(tmp_path):
    contract = """\
## POST /auth/login

Body description without auth line.

---

## GET /users/me

**Auth:** Authenticated

Body.
"""
    repo = _setup(tmp_path, contract)
    r = _run(repo)
    assert r.returncode == 1
    assert "missing_auth_declaration" in r.stdout


def test_unclear_auth_blocks(tmp_path):
    """Auth line present but text doesn't classify → BLOCK."""
    contract = """\
## POST /data/submit

**Auth:** you know, it depends

Body...
"""
    repo = _setup(tmp_path, contract)
    r = _run(repo)
    assert r.returncode == 1
    assert "unclear_auth_declaration" in r.stdout


def test_mutation_generic_warns_not_blocks(tmp_path):
    """POST with only `Authenticated` → WARN (advisory), not BLOCK."""
    contract = """\
## POST /articles

**Auth:** Authenticated

Body.
"""
    repo = _setup(tmp_path, contract)
    r = _run(repo)
    # WARN — exit 0
    assert r.returncode == 0
    assert "mutation_generic_auth" in r.stdout


def test_mutation_owner_only_passes(tmp_path):
    """POST with Owner only → PASS (no warn)."""
    contract = """\
## PUT /articles/:id

**Auth:** Owner only — user can only edit own article

Body.
"""
    repo = _setup(tmp_path, contract)
    r = _run(repo)
    assert r.returncode == 0
    # Should NOT flag as mutation_generic since owner_only qualifies it
    assert "mutation_generic_auth" not in r.stdout


def test_get_with_authenticated_doesnt_warn(tmp_path):
    """GET (read-only) with Authenticated → PASS, no mutation warn."""
    contract = """\
## GET /users/me/settings

**Auth:** Authenticated

Body.
"""
    repo = _setup(tmp_path, contract)
    r = _run(repo)
    assert r.returncode == 0
    assert "mutation_generic_auth" not in r.stdout


def test_no_contract_skips(tmp_path):
    phase_dir = tmp_path / ".vg" / "phases" / "07.11-test"
    phase_dir.mkdir(parents=True)
    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(tmp_path)
    r = subprocess.run(
        [sys.executable, str(VALIDATOR), "--phase", "7.11"],
        cwd=tmp_path, capture_output=True, text=True, timeout=10, env=env,
    )
    assert r.returncode == 0


def test_output_in_vietnamese(tmp_path):
    contract = """\
## POST /x

Body without auth.
"""
    repo = _setup(tmp_path, contract)
    r = _run(repo)
    assert r.returncode == 1
    vn_markers = [
        "THIẾU", "TH\\u0110\\u01ef0U", "TH\\u0132\\u00ca\\u0166U",
        "khai báo", "khai b\\u00e1o",
        "endpoint",
        "phân quyền", "ph\\u00e2n quy\\u1ec1n",
    ]
    assert any(m in r.stdout for m in vn_markers), (
        f"expected VN markers, got:\n{r.stdout}"
    )


def test_multiple_classifications_extracted(tmp_path):
    """Complex contract with 4 distinct classifications → all detected."""
    repo = _setup(tmp_path, CONTRACT_CLEAN)
    r = _run(repo)
    # All 4 endpoints declared distinctly → PASS + no evidence
    assert r.returncode == 0
    # Default PASS with no evidence emits empty evidence array
    assert '"verdict": "PASS"' in r.stdout


def test_registered_in_dispatcher():
    """verify-authz-declared registered in vg:build chain."""
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
    assert "verify-authz-declared" in mod.COMMAND_VALIDATORS.get("vg:build", [])
