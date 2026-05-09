"""v2.67.0 #159 — verify-contract-completeness.py centralized skip-dir
filter + scanned-count metrics.

Four checks:
1. _should_skip_path() helper exists and skips _backup / archive /
   legacy / _archive / .vg directories (the loops at lines 184/207/226
   currently filter only node_modules/dist/build/.next/venv/__pycache__/
   .git, so these directories are scanned and pollute the inventory).
2. _should_skip_path() does NOT skip production code paths.
3. _should_skip_path() preserves all pre-existing skip names so
   v2.39+ behavior is unchanged for the canonical exclusions.
4. The output JSON shape (CONTRACT-COMPLETENESS.json) records
   scanned_*_count metrics so cross-artifact reconciliation has the
   real "files inspected" denominator (currently only the
   *_inventoried hit counts are recorded).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "verify-contract-completeness.py"


def _load():
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "verify_contract_completeness",
        SCRIPT_PATH,
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_should_skip_backup_archive_legacy_dirs():
    """_backup / archive / legacy / _archive / .vg must be skipped."""
    mod = _load()
    assert hasattr(mod, "_should_skip_path"), (
        "v2.67.0 #159: must expose centralized _should_skip_path() helper"
    )
    skip = mod._should_skip_path

    assert skip(Path("apps/api/_backup/old.ts")), "_backup must skip"
    assert skip(Path("packages/core/archive/legacy.ts")), "archive must skip"
    assert skip(Path("legacy/v1/handler.ts")), "legacy must skip"
    assert skip(Path("apps/api/_archive/snapshots.ts")), "_archive must skip"
    assert skip(Path(".vg/runs/abc/scan.ts")), ".vg must skip"


def test_should_not_skip_production_paths():
    """Production source paths must NOT be skipped."""
    mod = _load()
    skip = mod._should_skip_path

    assert not skip(Path("apps/api/src/handlers/users.ts"))
    assert not skip(Path("packages/core/index.ts"))
    assert not skip(Path("server/routes/auth.py"))
    assert not skip(Path("scripts/verify-contract-completeness.py"))


def test_existing_excludes_preserved():
    """Pre-existing skip names (node_modules, dist, build, .next, venv,
    __pycache__, .git) must still be filtered."""
    mod = _load()
    skip = mod._should_skip_path

    for excluded in (
        "node_modules", "dist", "build", ".next", "venv",
        "__pycache__", ".git",
    ):
        assert skip(Path(f"x/{excluded}/y.ts")), (
            f"existing exclude {excluded!r} must remain skipped (v2.67.0 #159)"
        )


def test_scanned_count_metrics_in_output_json():
    """CONTRACT-COMPLETENESS.json payload must include scanned_*_count
    fields so cross-artifact reconciliation has the inspected denominator
    (not just the matched-pattern numerator already in *_inventoried).
    """
    src = SCRIPT_PATH.read_text(encoding="utf-8")
    # At least one of the per-loop scanned counters must be exported.
    expected_keys = (
        "scanned_models_count",
        "scanned_jobs_count",
        "scanned_webhooks_count",
    )
    found = [k for k in expected_keys if k in src]
    assert found, (
        "v2.67.0 #159: verify-contract-completeness.py output JSON must "
        "record scanned_*_count metrics. Expected at least one of "
        f"{expected_keys} in payload."
    )
    # All three should ideally be present for full reconciliation.
    assert len(found) == len(expected_keys), (
        f"v2.67.0 #159: missing scanned-count keys in payload: "
        f"{set(expected_keys) - set(found)}"
    )
