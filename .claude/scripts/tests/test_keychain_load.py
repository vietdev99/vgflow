"""
v2.7 Phase J — tests for keychain-first approver-key loading.

Covers the 6 cases per PLAN.md Phase J item 4:
  1. Keychain present + valid → load PASS, no fallback event
  2. Keychain absent + file present → fallback PASS, event emitted
  3. Both empty → first-call generates fresh key (writes to keychain
     when available, else file with fallback event)
  4. Keychain returns wrong/corrupt encoding → fallback to file (degrade
     gracefully — never blocks the gate on a bad backend)
  5. `keyring` ImportError → graceful degrade to file path
  6. Migration round-trip via the migration script's logic
"""
from __future__ import annotations

import base64
import importlib.util as _ilu
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

GATE_PATH = REPO_ROOT / ".claude" / "scripts" / "vg-orchestrator" / \
            "allow_flag_gate.py"
_spec = _ilu.spec_from_file_location("allow_flag_gate_kc", GATE_PATH)
_GATE = _ilu.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_GATE)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def isolated_key_dir(tmp_path, monkeypatch):
    """Redirect approver-key path to tmp; clear leak-prone env."""
    monkeypatch.setenv(_GATE.APPROVER_KEY_DIR_ENV, str(tmp_path))
    monkeypatch.delenv(_GATE.KEYCHAIN_DISABLE_ENV, raising=False)
    return tmp_path


@pytest.fixture
def fake_keyring(monkeypatch):
    """Inject a mock `keyring` module into sys.modules so the gate's
    deferred import picks it up. Returns the storage dict so each test
    can inspect / pre-seed."""
    storage: dict[tuple[str, str], str] = {}

    fake = MagicMock()

    class _KE(Exception):
        pass

    fake.errors = MagicMock()
    fake.errors.KeyringError = _KE

    def _get(service, user):
        return storage.get((service, user))

    def _set(service, user, password):
        storage[(service, user)] = password

    def _delete(service, user):
        storage.pop((service, user), None)

    fake.get_password = _get
    fake.set_password = _set
    fake.delete_password = _delete
    fake.get_keyring = lambda: "fake-keyring-backend"

    monkeypatch.setitem(sys.modules, "keyring", fake)
    monkeypatch.setitem(sys.modules, "keyring.errors", fake.errors)
    return storage


@pytest.fixture
def break_keyring_import(monkeypatch):
    """Ensure `import keyring` raises ImportError inside the gate."""
    monkeypatch.setitem(sys.modules, "keyring", None)
    # `import keyring.errors` reach via the parent — also block it
    monkeypatch.setitem(sys.modules, "keyring.errors", None)


@pytest.fixture
def collect_events(monkeypatch):
    """Capture any audit events the gate tries to emit so tests can
    assert on them without needing the events.db on disk."""
    captured: list[dict] = []

    def _fake_emit(event_type, payload):
        captured.append({"event_type": event_type, "payload": payload})

    monkeypatch.setattr(_GATE, "_emit_keychain_event", _fake_emit)
    return captured


# ---------------------------------------------------------------------------
# Case 1: keychain present + valid → load PASS, no fallback event
# ---------------------------------------------------------------------------

def test_case1_keychain_present_loads_without_fallback(
    isolated_key_dir, fake_keyring, collect_events
):
    seeded = b"\x01" * 32
    fake_keyring[("vg-approver", "approver")] = _GATE._b64url_encode(seeded)

    loaded = _GATE._load_approver_key_keychain_first()

    assert loaded == seeded
    # No fallback event — keychain path served the request.
    assert all(
        ev["event_type"] != "override.keychain_unavailable_fallback"
        for ev in collect_events
    ), f"Unexpected fallback event in case-1: {collect_events!r}"


# ---------------------------------------------------------------------------
# Case 2: keychain empty + file present → fallback PASS + event emitted
# ---------------------------------------------------------------------------

def test_case2_keychain_empty_file_present_falls_back(
    isolated_key_dir, fake_keyring, collect_events
):
    # Pre-seed a legacy file
    seeded = b"\x02" * 32
    file_path = isolated_key_dir / "approver-key"
    file_path.write_bytes(seeded)

    loaded = _GATE._load_approver_key_keychain_first()

    assert loaded == seeded
    fallback_events = [
        ev for ev in collect_events
        if ev["event_type"] == "override.keychain_unavailable_fallback"
    ]
    assert len(fallback_events) == 1, (
        f"Expected exactly one fallback event, got {collect_events!r}"
    )
    payload = fallback_events[0]["payload"]
    assert payload["service_name"] == "vg-approver"
    assert payload["keychain_reason"] == "not_found"
    assert payload["outcome"] == "loaded_from_file"


# ---------------------------------------------------------------------------
# Case 3: both empty → fresh key generated; written to keychain when
# available, else to file with fallback event.
# ---------------------------------------------------------------------------

def test_case3_both_empty_creates_fresh_in_keychain(
    isolated_key_dir, fake_keyring, collect_events
):
    loaded = _GATE._load_approver_key_keychain_first()

    assert isinstance(loaded, bytes) and len(loaded) == 32
    # Keychain should now hold the encoded fresh key.
    stored = fake_keyring.get(("vg-approver", "approver"))
    assert stored is not None
    assert _GATE._b64url_decode(stored) == loaded
    # Used keychain path for storage — no fallback file event expected
    assert all(
        ev["event_type"] != "override.keychain_unavailable_fallback"
        for ev in collect_events
    ), f"Should not emit fallback when keychain set succeeded: {collect_events!r}"


def test_case3b_both_empty_no_keychain_falls_to_file(
    isolated_key_dir, break_keyring_import, collect_events
):
    """Variant: keychain unavailable AND file empty → fresh key written
    to file with fallback event."""
    loaded = _GATE._load_approver_key_keychain_first()

    assert isinstance(loaded, bytes) and len(loaded) == 32
    file_path = isolated_key_dir / "approver-key"
    assert file_path.exists()
    assert file_path.read_bytes() == loaded

    fallback_events = [
        ev for ev in collect_events
        if ev["event_type"] == "override.keychain_unavailable_fallback"
    ]
    assert len(fallback_events) == 1
    assert fallback_events[0]["payload"]["outcome"] == "created_fresh_in_file"
    assert fallback_events[0]["payload"]["keychain_reason"] == "import_error"


# ---------------------------------------------------------------------------
# Case 4: keychain returns malformed encoding → graceful fallback to file
# (we do NOT block the gate on a corrupt backend; we degrade)
# ---------------------------------------------------------------------------

def test_case4_keychain_malformed_falls_back_to_file(
    isolated_key_dir, fake_keyring, collect_events
):
    # Seed keychain with garbage that fails base64url decode
    fake_keyring[("vg-approver", "approver")] = "!!!!not-valid-base64!!!!"
    seeded = b"\x04" * 32
    file_path = isolated_key_dir / "approver-key"
    file_path.write_bytes(seeded)

    loaded = _GATE._load_approver_key_keychain_first()

    # Should fall back to file (not raise)
    assert loaded == seeded
    fallback_events = [
        ev for ev in collect_events
        if ev["event_type"] == "override.keychain_unavailable_fallback"
    ]
    assert len(fallback_events) == 1
    assert fallback_events[0]["payload"]["keychain_reason"] == "malformed"


# ---------------------------------------------------------------------------
# Case 5: `keyring` ImportError → graceful degrade to file path
# ---------------------------------------------------------------------------

def test_case5_import_failure_degrades_to_file(
    isolated_key_dir, break_keyring_import, collect_events
):
    seeded = b"\x05" * 32
    file_path = isolated_key_dir / "approver-key"
    file_path.write_bytes(seeded)

    loaded = _GATE._load_approver_key_keychain_first()

    assert loaded == seeded
    fallback_events = [
        ev for ev in collect_events
        if ev["event_type"] == "override.keychain_unavailable_fallback"
    ]
    assert len(fallback_events) == 1
    assert fallback_events[0]["payload"]["keychain_reason"] == "import_error"
    assert fallback_events[0]["payload"]["outcome"] == "loaded_from_file"


# ---------------------------------------------------------------------------
# Case 6: migration round-trip — write to keychain, read back, match
# ---------------------------------------------------------------------------

def test_case6_migration_round_trip(isolated_key_dir, fake_keyring):
    # Simulate the legacy file
    raw = b"\x06" * 32
    file_path = isolated_key_dir / "approver-key"
    file_path.write_bytes(raw)

    # Run the migration's core write step directly through the gate API
    ok, reason = _GATE._try_keychain_set("vg-approver", raw)
    assert ok is True and reason == "ok"

    # Read back via the same path
    got, get_reason = _GATE._try_keychain_get("vg-approver")
    assert get_reason == "ok"
    assert got == raw

    # Subsequent _load returns keychain copy, not file
    loaded = _GATE._load_approver_key_keychain_first()
    assert loaded == raw


# ---------------------------------------------------------------------------
# Additional coverage: KEYCHAIN_DISABLED env honored
# ---------------------------------------------------------------------------

def test_keychain_disable_env_forces_file_path(
    isolated_key_dir, fake_keyring, monkeypatch, collect_events
):
    """Operators on broken backends can set VG_KEYCHAIN_DISABLED=1 to
    short-circuit the keychain probe and go straight to file fallback."""
    seeded = b"\x07" * 32
    file_path = isolated_key_dir / "approver-key"
    file_path.write_bytes(seeded)
    fake_keyring[("vg-approver", "approver")] = _GATE._b64url_encode(b"\xff" * 32)
    monkeypatch.setenv(_GATE.KEYCHAIN_DISABLE_ENV, "1")

    loaded = _GATE._load_approver_key_keychain_first()

    # File wins because keychain probe is disabled
    assert loaded == seeded
    fallback_events = [
        ev for ev in collect_events
        if ev["event_type"] == "override.keychain_unavailable_fallback"
    ]
    assert len(fallback_events) == 1
    assert fallback_events[0]["payload"]["keychain_reason"] == "keychain_disabled"


# ---------------------------------------------------------------------------
# Config parsing sanity — service_name override works
# ---------------------------------------------------------------------------

def test_config_parser_reads_security_keychain_block():
    cfg = _GATE._read_keychain_config()
    assert cfg["service_name"] == "vg-approver"
    assert cfg["fallback_to_file"] is True
    assert cfg["fallback_file_path"].endswith(".approver-key")


# ---------------------------------------------------------------------------
# Backward compat: _get_or_create_key still works (delegates)
# ---------------------------------------------------------------------------

def test_get_or_create_key_delegates_to_keychain_first(
    isolated_key_dir, fake_keyring
):
    seeded = b"\x08" * 32
    fake_keyring[("vg-approver", "approver")] = _GATE._b64url_encode(seeded)

    # Existing call site (sign_approval / verify_approval / vg-auth.py)
    loaded = _GATE._get_or_create_key()

    assert loaded == seeded
