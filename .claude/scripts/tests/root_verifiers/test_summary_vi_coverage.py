"""
Tests for verify-summary-vi-coverage.py — BLOCK at vg:accept.

Closes user-feedback rule "Mỗi phase phải có XX-SUMMARY-VI.md tổng quan
tiếng Việt cụ thể". Validator scans phase dir for *-SUMMARY-VI.md and
verifies it's substantive (≥500 bytes, ≥3 VN diacritics, ≥2 headings).

Covers:
  - Phase dir absent → PASS
  - Phase profile=docs → skipped (PASS)
  - Phase profile=hotfix → skipped (PASS)
  - Substantive Vietnamese summary present → PASS
  - Summary file missing entirely → BLOCK
  - Summary file present but placeholder (too short) → BLOCK
  - Summary file present but no Vietnamese diacritics → BLOCK
  - Verdict schema canonical
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT_REAL = Path(__file__).resolve().parents[4]
VALIDATOR = REPO_ROOT_REAL / ".claude" / "scripts" / "validators" / \
    "verify-summary-vi-coverage.py"


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["VG_REPO_ROOT"] = str(cwd)
    return subprocess.run(
        [sys.executable, str(VALIDATOR), *args],
        capture_output=True, text=True, timeout=20, env=env,
        encoding="utf-8", errors="replace", cwd=str(cwd),
    )


def _verdict(stdout: str) -> str | None:
    try:
        return json.loads(stdout).get("verdict")
    except (json.JSONDecodeError, AttributeError):
        return None


def _make_phase(tmp_path: Path, profile: str = "feature",
                slug: str = "07.5-vi") -> Path:
    pdir = tmp_path / ".vg" / "phases" / slug
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "SPECS.md").write_text(
        f"---\nprofile: {profile}\n---\n# Specs\n",
        encoding="utf-8",
    )
    return pdir


SUBSTANTIVE_VI = """\
# Phase 7.5 — Tóm tắt thực hiện

## Bối cảnh

Phase này tập trung vào việc cải thiện chất lượng giao diện
quản lý chiến dịch quảng cáo, đảm bảo trải nghiệm người dùng
được nhất quán giữa các thiết bị và trình duyệt khác nhau.

## Những thay đổi chính

Đã hoàn tất việc đồng bộ thiết kế với HTML prototype gốc, bao
gồm việc cập nhật bảng màu chủ đạo, các thành phần điều hướng,
cũng như cải thiện tốc độ tải trang. Các quyết định đáng chú ý
đã được ghi nhận đầy đủ trong CONTEXT.md để tránh bị quên trong
các phase tiếp theo.

## Kết quả kiểm thử

Toàn bộ kịch bản kiểm thử đã chạy thành công trên môi trường
sandbox. Hai trường hợp đặc biệt được xử lý: bộ lọc đa lựa chọn
và phân trang có ghi nhớ trạng thái sau khi tải lại trang.
"""


class TestSummaryViCoverage:
    def test_phase_dir_missing_passes(self, tmp_path):
        r = _run(["--phase", "07.5"], tmp_path)
        assert r.returncode == 0, f"missing phase → PASS, rc={r.returncode}"

    def test_docs_profile_skipped(self, tmp_path):
        _make_phase(tmp_path, profile="docs")
        r = _run(["--phase", "07.5"], tmp_path)
        assert r.returncode == 0, f"docs profile → PASS (skip), got {r.returncode}"

    def test_hotfix_profile_skipped(self, tmp_path):
        _make_phase(tmp_path, profile="hotfix")
        r = _run(["--phase", "07.5"], tmp_path)
        assert r.returncode == 0, f"hotfix profile → PASS (skip), got {r.returncode}"

    def test_substantive_vi_summary_passes(self, tmp_path):
        pdir = _make_phase(tmp_path)
        (pdir / "07.5-SUMMARY-VI.md").write_text(SUBSTANTIVE_VI, encoding="utf-8")
        r = _run(["--phase", "07.5"], tmp_path)
        assert r.returncode == 0, \
            f"substantive VI summary → PASS, rc={r.returncode}, stdout={r.stdout[:300]}"
        assert _verdict(r.stdout) == "PASS"

    def test_summary_missing_blocks(self, tmp_path):
        _make_phase(tmp_path)
        r = _run(["--phase", "07.5"], tmp_path)
        assert r.returncode == 1, \
            f"missing VI summary → BLOCK, got {r.returncode}, stdout={r.stdout[:300]}"
        assert _verdict(r.stdout) == "BLOCK"
        data = json.loads(r.stdout)
        types = {ev.get("type") for ev in data.get("evidence", [])}
        assert "summary_vi_missing" in types

    def test_placeholder_too_short_blocks(self, tmp_path):
        pdir = _make_phase(tmp_path)
        (pdir / "07.5-SUMMARY-VI.md").write_text(
            "# Tóm tắt\nQuá ngắn.\n",  # <500 bytes
            encoding="utf-8",
        )
        r = _run(["--phase", "07.5"], tmp_path)
        assert r.returncode == 1, \
            f"placeholder summary → BLOCK, got {r.returncode}"
        assert _verdict(r.stdout) == "BLOCK"

    def test_no_vietnamese_diacritics_blocks(self, tmp_path):
        pdir = _make_phase(tmp_path)
        # 500+ bytes, 2+ headings, but ZERO Vietnamese diacritics
        body = (
            "# Phase Summary\n\n"
            "## Context\n\n"
            "This phase shipped backend changes to the API. We covered "
            "the auth flow, added input validation, wrote some tests.\n\n"
            "## Result\n\n"
            "Tests pass on sandbox. No regressions detected. The system "
            "is ready for acceptance review by the product owner today.\n"
            + ("Filler text padding to reach byte threshold. " * 6)
        )
        (pdir / "07.5-SUMMARY-VI.md").write_text(body, encoding="utf-8")
        r = _run(["--phase", "07.5"], tmp_path)
        assert r.returncode == 1, \
            f"no diacritics → BLOCK, got {r.returncode}, stdout={r.stdout[:300]}"

    def test_verdict_schema_canonical(self, tmp_path):
        _make_phase(tmp_path)
        r = _run(["--phase", "07.5"], tmp_path)
        try:
            data = json.loads(r.stdout)
        except json.JSONDecodeError:
            return
        v = data.get("verdict")
        if v is not None:
            assert v in {"PASS", "BLOCK", "WARN"}, f"verdict drift: {v!r}"
        assert "validator" in data
        assert "evidence" in data
