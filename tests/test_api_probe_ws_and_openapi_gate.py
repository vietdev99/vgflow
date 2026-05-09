"""v2.67.0 #157 — API probe parses WS, skips probe, OpenAPI 500 pre-gated.

Tests verify three changes to scripts/review-api-contract-probe.py:

1. All 3 method regexes (HEADER_RE, TABLE_ROW_RE, SPLIT_FILE_HEAD_RE)
   include WS|WEBSOCKET — previously WS endpoints fell through silently
   and parser returned 0 endpoints for any contract that listed WS routes.

2. probe_endpoint() short-circuits WS endpoints with a SKIP verdict
   instead of running an HTTP GET probe (which would always 404 against
   a WebSocket upgrade handler).

3. _openapi_schema_valid(phase_dir) inspects openapi-generation.log for
   FST_ERR_INVALID_SCHEMA / 500-level signals and pre-gates the run.
   When the OpenAPI schema is broken, docs-derived probes are not
   trustworthy — exit 2 instead of producing a misleading FAIL.
"""
from __future__ import annotations

import importlib.util
import re
import sys
import tempfile
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "review-api-contract-probe.py"


@pytest.fixture(scope="module")
def probe_module():
    """Import review-api-contract-probe.py as a module for direct API access.

    Registers in ``sys.modules`` BEFORE ``exec_module`` so dataclass forward
    refs resolve under ``from __future__ import annotations``.
    """
    name = "review_api_contract_probe_v267"
    spec = importlib.util.spec_from_file_location(name, SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return mod


# ---------------------------------------------------------------------------
# 1. Regex coverage — WS in all 3 parser regexes
# ---------------------------------------------------------------------------

def test_header_regex_includes_ws(probe_module):
    """HEADER_RE (legacy `### METHOD /path`) must match WS + WEBSOCKET."""
    pat = probe_module.HEADER_RE.pattern
    assert "WS" in pat, f"HEADER_RE must include WS: {pat}"
    assert "WEBSOCKET" in pat, f"HEADER_RE must include WEBSOCKET: {pat}"


def test_table_row_regex_includes_ws(probe_module):
    """TABLE_ROW_RE (Layer 2 index table) must match WS + WEBSOCKET."""
    pat = probe_module.TABLE_ROW_RE.pattern
    assert "WS" in pat, f"TABLE_ROW_RE must include WS: {pat}"
    assert "WEBSOCKET" in pat, f"TABLE_ROW_RE must include WEBSOCKET: {pat}"


def test_split_file_regex_includes_ws(probe_module):
    """SPLIT_FILE_HEAD_RE (Layer 1 per-file `# METHOD /path`) must match WS."""
    pat = probe_module.SPLIT_FILE_HEAD_RE.pattern
    assert "WS" in pat, f"SPLIT_FILE_HEAD_RE must include WS: {pat}"
    assert "WEBSOCKET" in pat, f"SPLIT_FILE_HEAD_RE must include WEBSOCKET: {pat}"


# ---------------------------------------------------------------------------
# 2. WS endpoints parsed end-to-end via Layer 2 table format
# ---------------------------------------------------------------------------

def test_ws_endpoints_parsed_from_table(probe_module, tmp_path):
    """A `WS` row in the Layer 2 index table must surface as Endpoint."""
    sample = (
        "| Slug | Method | Path | File |\n"
        "|------|--------|------|------|\n"
        "| users-list | GET | /api/users | users.md |\n"
        "| ws-notify  | WS  | /ws/notifications | ws-notify.md |\n"
    )
    contracts_path = tmp_path / "API-CONTRACTS.md"
    contracts_path.write_text(sample, encoding="utf-8")

    endpoints = probe_module.parse_contracts(contracts_path)
    methods = [ep.method for ep in endpoints]
    assert "WS" in methods, (
        f"WS row must parse as endpoint with method=WS, got methods={methods}"
    )


# ---------------------------------------------------------------------------
# 3. WS probe SKIP path — WS endpoints must NOT run HTTP GET
# ---------------------------------------------------------------------------

def test_ws_endpoints_skipped_not_probed_as_get(probe_module, monkeypatch):
    """probe_endpoint(WS endpoint) must return verdict=SKIP, status=0,
    without invoking _curl. This is the load-bearing assertion: previously
    WS endpoints got `OPTIONS /ws/path` (since method != "GET" → mutation
    fallback), which 404'd against the WS upgrade handler.
    """
    Endpoint = probe_module.Endpoint
    ep = Endpoint(method="WS", path="/ws/notifications", auth=None)

    # Poison _curl: if it gets called for a WS endpoint, the test fails.
    def poison_curl(*args, **kwargs):
        raise AssertionError(
            "_curl must NOT be invoked for WS endpoint — probe should short-circuit"
        )

    monkeypatch.setattr(probe_module, "_curl", poison_curl)

    result = probe_module.probe_endpoint("https://example.test/", ep, [], 5)
    assert result.verdict == "SKIP", (
        f"WS endpoint must SKIP, got verdict={result.verdict}"
    )
    assert result.status == 0, (
        f"WS SKIP must report status=0 (no probe attempted), got {result.status}"
    )
    # Detail should reference WS / WebSocket so reports are scrutable
    assert re.search(r"ws|websocket", result.detail, re.IGNORECASE), (
        f"WS SKIP detail must mention WS/WebSocket: {result.detail}"
    )


# ---------------------------------------------------------------------------
# 4. OpenAPI pre-gate — FST_ERR_INVALID_SCHEMA / 500 must block run
# ---------------------------------------------------------------------------

def test_openapi_pregate_helper_exists(probe_module):
    """_openapi_schema_valid(phase_dir) must be present and callable."""
    assert hasattr(probe_module, "_openapi_schema_valid"), (
        "scripts/review-api-contract-probe.py must export _openapi_schema_valid"
    )


def test_openapi_pregate_blocks_on_fst_err_invalid_schema(probe_module, tmp_path):
    """When openapi-generation.log contains FST_ERR_INVALID_SCHEMA, pre-gate
    returns (False, reason). Run must not proceed."""
    log = tmp_path / "openapi-generation.log"
    log.write_text(
        "[12:34:56] generating /api/openapi.json\n"
        "[12:34:57] FST_ERR_INVALID_SCHEMA: schema must be a valid JSON schema\n",
        encoding="utf-8",
    )
    valid, reason = probe_module._openapi_schema_valid(tmp_path)
    assert valid is False, "FST_ERR_INVALID_SCHEMA must mark schema invalid"
    assert "FST_ERR_INVALID_SCHEMA" in reason or "openapi" in reason.lower(), (
        f"reason must mention the failure mode: {reason}"
    )


def test_openapi_pregate_passes_when_log_missing(probe_module, tmp_path):
    """When no openapi-generation.log exists, pre-gate is a no-op (returns
    valid=True). Phases without OpenAPI should not be punished."""
    valid, reason = probe_module._openapi_schema_valid(tmp_path)
    assert valid is True, "missing log → no-op pass, got valid=False"


def test_openapi_pregate_passes_on_clean_log(probe_module, tmp_path):
    """When openapi-generation.log is clean, pre-gate passes."""
    log = tmp_path / "openapi-generation.log"
    log.write_text(
        "[12:34:56] generating /api/openapi.json\n"
        "[12:34:57] schema valid, 42 routes documented\n",
        encoding="utf-8",
    )
    valid, reason = probe_module._openapi_schema_valid(tmp_path)
    assert valid is True, f"clean log should pass, got reason={reason}"
