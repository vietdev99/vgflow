"""Task 38 — verify BLOCK 5 FE contract validator.

Pin: validator BLOCKs when BLOCK 5 missing on any endpoint, validates
all 16 fields, enforces per-method matrix (GET-list ⇒ pagination_contract;
POST/PUT/PATCH ⇒ form_submission_idempotency_key).

`--allow-block5-missing` escapes BLOCK with override-debt entry.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
VALIDATOR = REPO / "scripts/validators/verify-fe-contract-block5.py"

# Minimal BE 4-block stub (BLOCK 1..4); BLOCK 5 absent.
ENDPOINT_BE_ONLY = """\
# POST /api/sites

## BLOCK 1: Auth + middleware
- requires: publisher
## BLOCK 2: Zod schemas
- request: SiteCreateInput
## BLOCK 3: Error responses
- 401, 403, 422
## BLOCK 4: Test sample
- POST /api/sites with cred=publisher
"""

ENDPOINT_WITH_BLOCK5 = ENDPOINT_BE_ONLY + """\

## BLOCK 5: FE consumer contract

```typescript
export const PostSitesFEContract = {
  url: '/api/sites',
  consumers: ['apps/web/src/sites/**/*.tsx'],
  ui_states: { loading: 'spinner', error: 'inline-banner', empty: 'cta-create-first', success: 'toast-then-redirect' },
  query_param_schema: {},
  invalidates: ['GetSites'],
  optimistic: false,
  toast_text: { success: 'Site created', error_403: 'Need publisher role' },
  navigation_post_action: 'navigate:/sites/{id}',
  auth_role_visibility: ['publisher'],
  error_to_action_map: { 401: 'navigate:/login', 403: 'modal:contact-admin' },
  pagination_contract: null,
  debounce_ms: null,
  prefetch_triggers: [],
  websocket_correlate: null,
  request_id_propagation: false,
  form_submission_idempotency_key: 'header:Idempotency-Key',
} as const;
```
"""


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["python3", str(VALIDATOR), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def test_block5_missing_blocks_validator(tmp_path: Path) -> None:
    contracts_dir = tmp_path / "API-CONTRACTS"
    contracts_dir.mkdir()
    (contracts_dir / "post-api-sites.md").write_text(ENDPOINT_BE_ONLY, encoding="utf-8")

    result = _run(["--contracts-dir", str(contracts_dir)], REPO)
    assert result.returncode != 0, "expected BLOCK on missing BLOCK 5"
    assert "BLOCK 5" in result.stdout + result.stderr


def test_block5_present_passes(tmp_path: Path) -> None:
    contracts_dir = tmp_path / "API-CONTRACTS"
    contracts_dir.mkdir()
    (contracts_dir / "post-api-sites.md").write_text(ENDPOINT_WITH_BLOCK5, encoding="utf-8")

    result = _run(["--contracts-dir", str(contracts_dir)], REPO)
    assert result.returncode == 0, f"expected pass, got: {result.stdout}\n{result.stderr}"


def test_get_list_requires_pagination_contract(tmp_path: Path) -> None:
    contracts_dir = tmp_path / "API-CONTRACTS"
    contracts_dir.mkdir()
    bad = ENDPOINT_WITH_BLOCK5.replace("# POST /api/sites", "# GET /api/sites").replace(
        "pagination_contract: null", "pagination_contract: null  // INVALID: GET list requires non-null"
    )
    # Force the per-method matrix breach: GET on a list path with pagination_contract: null
    bad = bad.replace("pagination_contract: null", "pagination_contract_omitted: true")
    (contracts_dir / "get-api-sites.md").write_text(bad, encoding="utf-8")

    result = _run(["--contracts-dir", str(contracts_dir)], REPO)
    assert result.returncode != 0
    assert "pagination_contract" in result.stdout + result.stderr


def test_post_requires_idempotency_key(tmp_path: Path) -> None:
    contracts_dir = tmp_path / "API-CONTRACTS"
    contracts_dir.mkdir()
    bad = ENDPOINT_WITH_BLOCK5.replace(
        "form_submission_idempotency_key: 'header:Idempotency-Key'",
        "form_submission_idempotency_key_omitted: true",
    )
    (contracts_dir / "post-api-sites.md").write_text(bad, encoding="utf-8")

    result = _run(["--contracts-dir", str(contracts_dir)], REPO)
    assert result.returncode != 0
    assert "form_submission_idempotency_key" in result.stdout + result.stderr


def test_allow_block5_missing_with_override_debt(tmp_path: Path) -> None:
    """`--allow-block5-missing --override-reason=...` escapes BLOCK with override-debt."""
    contracts_dir = tmp_path / "API-CONTRACTS"
    contracts_dir.mkdir()
    (contracts_dir / "post-api-sites.md").write_text(ENDPOINT_BE_ONLY, encoding="utf-8")
    debt_path = tmp_path / "override-debt.json"

    result = _run(
        [
            "--contracts-dir", str(contracts_dir),
            "--allow-block5-missing",
            "--override-reason", "PV3 phase 4.1 legacy backfill — see Task 38 retroactivity",
            "--override-debt-path", str(debt_path),
        ],
        REPO,
    )
    assert result.returncode == 0, f"expected pass under override, got: {result.stderr}"
    assert debt_path.exists(), "override-debt entry must be written"
    debt = json.loads(debt_path.read_text(encoding="utf-8"))
    assert debt["reason"]
    assert debt["scope"] == "fe-contract-block5-missing"
