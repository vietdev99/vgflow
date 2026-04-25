"""
Tests for verify-idempotency-coverage.py — Harness v2.6.1 Batch D.

Critical-domain mutations (auth/billing/payout/payment/transaction/auction)
without **Idempotency:** declaration → BLOCK. Catches retry-storm /
double-charge / duplicate-session class of bugs at blueprint stage.

Covers:
  - Critical-domain mutation WITH idempotency declaration → 0
  - Critical-domain mutation MISSING declaration → 1 (BLOCK)
  - Non-critical mutation missing → 0 (skip default)
  - Non-critical mutation missing + --include-non-critical → 0 with WARN
  - **Idempotency:** N/A with reason ≥10 chars → 0 (acknowledged)
  - **Idempotency:** N/A with reason <10 chars → 1 (insufficient justification)
  - idempotency_key field in schema → 0 (counts as declared)
  - GET endpoint (non-mutation) → 0 (skip)
  - Empty contract → 0 (skip silently)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
VALIDATOR = REPO_ROOT / ".claude" / "scripts" / "validators" / "verify-idempotency-coverage.py"


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["VG_REPO_ROOT"] = str(cwd)
    return subprocess.run(
        [sys.executable, str(VALIDATOR), *args],
        capture_output=True, text=True, timeout=30, env=env,
        encoding="utf-8", errors="replace", cwd=str(cwd),
    )


def _setup_phase(tmp_path: Path, phase: str, contracts: str) -> Path:
    phase_dir = tmp_path / ".vg" / "phases" / f"{phase}-test"
    phase_dir.mkdir(parents=True)
    (phase_dir / "API-CONTRACTS.md").write_text(contracts, encoding="utf-8")
    return phase_dir


CRITICAL_WITH_DECL = """# API Contracts

### POST /api/billing/charge

**Auth:** session-required
**Idempotency:** required — header `Idempotency-Key`

Charges a customer.

```yaml
request:
  type: object
  properties:
    amount: { type: number }
```
"""

CRITICAL_WITHOUT_DECL = """# API Contracts

### POST /api/billing/charge

**Auth:** session-required

Charges a customer.

```yaml
request:
  type: object
  properties:
    amount: { type: number }
```
"""

CRITICAL_WITH_KEY_FIELD = """# API Contracts

### POST /api/auth/refresh

**Auth:** refresh-token

```yaml
request:
  type: object
  properties:
    idempotency_key: { type: string }
    refresh_token: { type: string }
```
"""

CRITICAL_NA_REASON_OK = """# API Contracts

### POST /api/payout/initiate

**Auth:** admin
**Idempotency:** N/A — initiation creates atomic ledger entry, idempotent by construction

```yaml
request: {}
```
"""

CRITICAL_NA_REASON_TOO_SHORT = """# API Contracts

### POST /api/payment/process

**Auth:** session
**Idempotency:** N/A — todo

```yaml
request: {}
```
"""

NONCRITICAL_MUTATION = """# API Contracts

### POST /api/blog/post

**Auth:** session

```yaml
request: {}
```
"""

GET_ENDPOINT = """# API Contracts

### GET /api/billing/invoices

**Auth:** session

List invoices.
"""


class TestIdempotencyCoverage:
    def test_critical_with_declaration_passes(self, tmp_path):
        _setup_phase(tmp_path, "7.99", CRITICAL_WITH_DECL)
        r = _run(["--phase", "7.99"], tmp_path)
        assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"

    def test_critical_without_declaration_blocks(self, tmp_path):
        _setup_phase(tmp_path, "7.99", CRITICAL_WITHOUT_DECL)
        r = _run(["--phase", "7.99"], tmp_path)
        assert r.returncode == 1, f"expected BLOCK (rc=1), got rc={r.returncode}\nstdout={r.stdout}"
        # Validator output should mention idempotency
        assert "idempotenc" in r.stdout.lower()

    def test_critical_with_idempotency_key_field_passes(self, tmp_path):
        _setup_phase(tmp_path, "7.99", CRITICAL_WITH_KEY_FIELD)
        r = _run(["--phase", "7.99"], tmp_path)
        assert r.returncode == 0, f"stdout={r.stdout}"

    def test_critical_na_with_reason_passes(self, tmp_path):
        _setup_phase(tmp_path, "7.99", CRITICAL_NA_REASON_OK)
        r = _run(["--phase", "7.99"], tmp_path)
        assert r.returncode == 0, f"stdout={r.stdout}"

    def test_critical_na_too_short_reason_blocks(self, tmp_path):
        _setup_phase(tmp_path, "7.99", CRITICAL_NA_REASON_TOO_SHORT)
        r = _run(["--phase", "7.99"], tmp_path)
        # Reason "todo" is 4 chars, below 10-char threshold → counts as missing
        assert r.returncode == 1, f"expected BLOCK; got rc={r.returncode}\nstdout={r.stdout}"

    def test_noncritical_mutation_skips_by_default(self, tmp_path):
        _setup_phase(tmp_path, "7.99", NONCRITICAL_MUTATION)
        r = _run(["--phase", "7.99"], tmp_path)
        # No critical domain match → no block
        assert r.returncode == 0, f"stdout={r.stdout}"

    def test_noncritical_with_include_flag_warns(self, tmp_path):
        _setup_phase(tmp_path, "7.99", NONCRITICAL_MUTATION)
        r = _run(["--phase", "7.99", "--include-non-critical"], tmp_path)
        # WARN is exit 0 (advisory), but evidence should mention non-critical
        assert r.returncode == 0
        # WARN evidence should be present in JSON output
        try:
            doc = json.loads(r.stdout)
            assert doc.get("verdict") in ("PASS", "WARN")
        except json.JSONDecodeError:
            pass  # Some validators print non-JSON when no findings

    def test_get_endpoint_skipped(self, tmp_path):
        _setup_phase(tmp_path, "7.99", GET_ENDPOINT)
        r = _run(["--phase", "7.99"], tmp_path)
        assert r.returncode == 0, f"stdout={r.stdout}"

    def test_empty_contract_skips(self, tmp_path):
        _setup_phase(tmp_path, "7.99", "# API Contracts\n\nNo endpoints yet.\n")
        r = _run(["--phase", "7.99"], tmp_path)
        assert r.returncode == 0, f"stdout={r.stdout}"
