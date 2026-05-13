"""tests/test_h2_fe_be_advisory_exit_code.py — H2 dead advisory fix."""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
CANON = REPO / "commands" / "vg" / "_shared" / "review" / "preflight.md"
MIRROR = REPO / ".claude" / "commands" / "vg" / "_shared" / "review" / "preflight.md"


def _read(p): return p.read_text(encoding="utf-8")


def test_fe_be_validator_call_does_not_mask_exit():
    body = _read(CANON)
    # Find the redirect line of the FE-BE validator invocation
    # The block ends with redirect to .diag file + optional `|| true` then FE_BE_RC=$?
    diag_redirect = 'fe-be-call-graph-advisory.diag" 2>&1'
    diag_idx = body.find(diag_redirect)
    assert diag_idx > 0, "Could not locate fe-be-call-graph-advisory.diag redirect line"
    # Get the redirect line
    line_start = body.rfind("\n", 0, diag_idx) + 1
    line_end = body.find("\n", diag_idx)
    redirect_line = body[line_start:line_end]
    assert "|| true" not in redirect_line, (
        f"H2: validator redirect line MUST NOT contain `|| true` — that masks "
        f"exit code, making FE_BE_RC always 0 and the advisory warning dead.\n"
        f"Got: {redirect_line!r}"
    )


def test_fe_be_advisory_warning_branch_reachable():
    body = _read(CANON)
    # The warning branch + emit-event must be present AFTER the FE_BE_RC check
    assert 'if [ "$FE_BE_RC" -ne 0 ]' in body or 'if [ ${FE_BE_RC} -ne 0 ]' in body
    assert "verify-fe-be-call-graph.py advisory" in body
    assert "review.fe_be_drift_warn" in body


def test_mirror_byte_identical():
    if MIRROR.is_file():
        assert _read(CANON) == _read(MIRROR)
