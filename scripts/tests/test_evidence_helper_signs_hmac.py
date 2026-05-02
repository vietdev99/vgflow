import hmac, hashlib, json, os, subprocess, tempfile
from pathlib import Path


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
            "python3", "scripts/vg-orchestrator-emit-evidence-signed.py",
            "--out", str(out_path),
            "--payload", json.dumps(payload),
        ],
        check=True,
    )
    written = json.loads(out_path.read_text())
    assert written["payload"] == payload
    expected = hmac.new(key, json.dumps(payload, sort_keys=True).encode(), hashlib.sha256).hexdigest()
    assert written["hmac_sha256"] == expected


def test_emit_evidence_signed_rejects_when_key_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("VG_EVIDENCE_KEY_PATH", str(tmp_path / "missing"))
    result = subprocess.run(
        ["python3", "scripts/vg-orchestrator-emit-evidence-signed.py",
         "--out", str(tmp_path / "out.json"), "--payload", "{}"],
        capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "evidence key" in result.stderr.lower()
