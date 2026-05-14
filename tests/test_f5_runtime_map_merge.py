"""tests/test_f5_runtime_map_merge.py — F5 RUNTIME-MAP merge + schema."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
MERGE = REPO / "scripts" / "merge-runtime-map.py"


def test_merge_script_exists():
    assert MERGE.is_file(), "F5: scripts/merge-runtime-map.py must exist"


def test_merge_script_rejects_empty_scans_dir(tmp_path):
    scan_dir = tmp_path / ".scan"
    scan_dir.mkdir()
    out = tmp_path / "RUNTIME-MAP.json"
    r = subprocess.run(
        [sys.executable, str(MERGE), "--scan-dir", str(scan_dir), "--out", str(out)],
        capture_output=True, text=True,
    )
    # Empty scan dir = no views to merge — must fail (not silently emit 80-byte stub)
    assert r.returncode != 0, "F5: empty scan dir must fail merge, not produce stub"


def test_merge_produces_schema_compliant_output(tmp_path):
    """Smoke test: 2 scan files → merged RUNTIME-MAP.json with views[] array."""
    import json
    scan_dir = tmp_path / ".scan"
    scan_dir.mkdir()
    (scan_dir / "scan-login.json").write_text(json.dumps({
        "view": "login",
        "url": "/login",
        "elements": [{"selector": "input[name=email]"}],
        "actions": [{"type": "click", "selector": "button[type=submit]"}],
    }), encoding="utf-8")
    (scan_dir / "scan-dashboard.json").write_text(json.dumps({
        "view": "dashboard",
        "url": "/dashboard",
        "elements": [{"selector": ".kpi-card"}],
        "actions": [],
    }), encoding="utf-8")
    out = tmp_path / "RUNTIME-MAP.json"
    r = subprocess.run(
        [sys.executable, str(MERGE), "--scan-dir", str(scan_dir), "--out", str(out)],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, f"merge failed: {r.stderr}"
    assert out.is_file()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert "views" in data
    assert len(data["views"]) == 2
    assert all("elements" in v for v in data["views"])


def test_lens_findings_references_merge_script():
    body = (REPO / "commands/vg/_shared/review/lens-and-findings.md").read_text(encoding="utf-8")
    assert "merge-runtime-map.py" in body, (
        "F5: review/lens-and-findings.md must invoke merge-runtime-map.py "
        "for deterministic RUNTIME-MAP.json generation (not prose Glob merge)"
    )


def test_close_min_size_raised():
    body = (REPO / "commands/vg/_shared/review/close.md").read_text(encoding="utf-8")
    # F5: close.md must have an explicit size check for RUNTIME-MAP.json.
    # Either content_min_bytes >= 500 in a YAML-style entry, OR a bash check
    # for minimum file size (wc -c / stat / python check).
    # The file must contain a positive size gate so fabricated 80-byte stubs
    # cannot satisfy the contract.
    has_size_gate = (
        "content_min_bytes" in body and "RUNTIME-MAP" in body
    ) or (
        "RUNTIME-MAP" in body and ("500" in body or "min_size" in body or "wc -c" in body or "minimum" in body.lower())
    )
    assert has_size_gate, (
        "F5: close.md must have a size gate for RUNTIME-MAP.json "
        "(content_min_bytes >= 500 or equivalent bash check) so fabricated "
        "80-byte stubs cannot satisfy the artifact contract"
    )
