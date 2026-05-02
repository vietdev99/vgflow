import hmac, hashlib, json, subprocess
from pathlib import Path


HELPER = Path(__file__).resolve().parents[1] / "vg-orchestrator-emit-evidence-signed.py"


def test_emit_evidence_signed_writes_hmac_payload(tmp_path, monkeypatch):
    key = b"test-key-32-bytes-aaaaaaaaaaaaaaa"
    key_path = tmp_path / ".evidence-key"
    key_path.write_bytes(key)
    key_path.chmod(0o600)
    monkeypatch.setenv("VG_EVIDENCE_KEY_PATH", str(key_path))

    out_path = tmp_path / "evidence.json"
    payload = {"contract_sha256": "abc", "todowrite_at": "2026-05-03T10:00:00Z"}
    subprocess.run(
        [
            "python3", str(HELPER),
            "--out", str(out_path),
            "--payload", json.dumps(payload),
        ],
        check=True,
    )
    written = json.loads(out_path.read_text())
    assert written["payload"] == payload
    expected = hmac.new(key, json.dumps(payload, sort_keys=True).encode(), hashlib.sha256).hexdigest()
    assert written["hmac_sha256"] == expected
    assert written["signed_at"].endswith("Z")
    assert "T" in written["signed_at"]


def test_emit_evidence_signed_rejects_when_key_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("VG_EVIDENCE_KEY_PATH", str(tmp_path / "missing"))
    result = subprocess.run(
        ["python3", str(HELPER),
         "--out", str(tmp_path / "out.json"), "--payload", "{}"],
        capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "evidence key" in result.stderr.lower()


def test_emit_evidence_signed_rejects_loose_key_mode(tmp_path, monkeypatch):
    key = b"test-key-32-bytes-aaaaaaaaaaaaaaa"
    key_path = tmp_path / ".evidence-key"
    key_path.write_bytes(key)
    key_path.chmod(0o644)  # too permissive
    monkeypatch.setenv("VG_EVIDENCE_KEY_PATH", str(key_path))
    result = subprocess.run(
        ["python3", str(HELPER), "--out", str(tmp_path / "out.json"), "--payload", "{}"],
        capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "0600" in result.stderr or "mode" in result.stderr.lower()
