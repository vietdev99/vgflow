"""v2.66.0 Task 3 (#151) — Gemini self-signed cert classifier + actionable hint.

Issue: scripts/crossai-normalize-results.py INFRA_PATTERNS lists `auth_missing`
BEFORE `tls_self_signed`, and the cert error text ("Error authenticating: ...
self-signed certificate in certificate chain") matches `error authenticating`
substring first. So Gemini cert errors get misclassified as auth_missing,
hiding the actual remedy (NODE_EXTRA_CA_CERTS).

Fix: Reorder so `tls_self_signed` comes BEFORE `auth_missing`, widen the regex
to match real-world error text (`self-signed certificate`, `certificate chain`,
`SELF_SIGNED_CERT_IN_CHAIN`, `unable to verify the first certificate`), and
add a FAILURE_HINTS dict mapping reason → operator-actionable text.
"""
import importlib.util
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).parent.parent


def _import_classifier():
    spec_path = REPO_ROOT / "scripts" / "crossai-normalize-results.py"
    spec = importlib.util.spec_from_file_location("crossai_normalize_results", spec_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["crossai_normalize_results"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_self_signed_cert_classified():
    """Gemini self-signed cert error must classify as tls_self_signed (not auth_missing)."""
    mod = _import_classifier()
    err_text = (
        "Error authenticating: _GaxiosError: request to "
        "https://cloudcode-pa.googleapis.com/v1internal:loadCodeAssist failed,\n"
        "  reason: self-signed certificate in certificate chain"
    )
    reason = mod._classify_failure(err_text, exit_code="1")
    assert reason == "tls_self_signed", (
        f"Expected tls_self_signed, got {reason!r} (substring 'authenticating' must NOT win)"
    )


def test_no_active_credentials_still_auth_missing():
    """Regression guard: non-cert auth errors still classify as auth_missing."""
    mod = _import_classifier()
    err_text = "Error: no active credentials found. Run gemini auth login."
    reason = mod._classify_failure(err_text, exit_code="1")
    assert reason == "auth_missing"


def test_tls_hint_message_present():
    """Result file metadata must include actionable hint text for tls_self_signed."""
    mod = _import_classifier()
    assert hasattr(mod, "FAILURE_HINTS"), "classifier must expose FAILURE_HINTS mapping"
    hints = mod.FAILURE_HINTS
    assert "tls_self_signed" in hints
    hint_text = hints["tls_self_signed"]
    assert (
        "NODE_EXTRA_CA_CERTS" in hint_text
        or "ca cert" in hint_text.lower()
        or "self-signed" in hint_text.lower()
    ), f"Hint must mention CA cert workaround: {hint_text!r}"
