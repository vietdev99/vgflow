"""
Phase 16 W0 — task_hasher.py unit tests.

Verifies the canonical SHA256 normalization rules per scripts/lib/task_hasher.py
docstring. These properties are LOAD-BEARING for D-01 (.meta.json sidecar) and
D-06 (post-spawn 3-way audit).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
HASHER_PATH = REPO_ROOT / "scripts" / "lib" / "task_hasher.py"


def _load_hasher():
    spec = importlib.util.spec_from_file_location("task_hasher", HASHER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def hasher():
    return _load_hasher()


# ─── Determinism ─────────────────────────────────────────────────────────

class TestDeterminism:
    def test_same_input_same_hash(self, hasher):
        text = "Hello\nWorld\n"
        a = hasher.task_block_sha256(text)
        b = hasher.task_block_sha256(text)
        assert a == b
        assert len(a[0]) == 64  # SHA256 hex

    def test_empty_input_stable(self, hasher):
        a = hasher.task_block_sha256("")
        b = hasher.task_block_sha256(None)  # None coerced to ""
        assert a == b
        assert a[1] == 0  # zero lines


# ─── Normalization rules ─────────────────────────────────────────────────

class TestNormalization:
    def test_crlf_lf_collapse(self, hasher):
        # CRLF + LF should produce same hash + same byte/line count
        crlf = "Hello\r\nWorld\r\n"
        lf = "Hello\nWorld\n"
        assert hasher.task_block_sha256(crlf) == hasher.task_block_sha256(lf)

    def test_trailing_whitespace_stripped(self, hasher):
        a = hasher.task_block_sha256("Hello   \nWorld\t\t\n")
        b = hasher.task_block_sha256("Hello\nWorld\n")
        assert a == b

    def test_blank_line_runs_collapsed(self, hasher):
        many_blanks = "A\n\n\n\n\nB\n"
        normal = "A\n\nB\n"
        assert hasher.task_block_sha256(many_blanks) == hasher.task_block_sha256(normal)

    def test_leading_trailing_blanks_stripped(self, hasher):
        a = hasher.task_block_sha256("\n\n\nHello\nWorld\n\n\n")
        b = hasher.task_block_sha256("Hello\nWorld")
        assert a == b

    def test_nfc_normalization(self, hasher):
        # `é` (NFC, single codepoint U+00E9) vs `e` + combining acute (NFD)
        nfc = "café"
        nfd = "café"
        assert hasher.task_block_sha256(nfc) == hasher.task_block_sha256(nfd)


# ─── Sensitivity (must detect REAL changes) ──────────────────────────────

class TestSensitivity:
    def test_different_text_different_hash(self, hasher):
        a, _, _ = hasher.task_block_sha256("Hello")
        b, _, _ = hasher.task_block_sha256("World")
        assert a != b

    def test_one_char_change_detected(self, hasher):
        a, _, _ = hasher.task_block_sha256("Hello\nWorld\n")
        b, _, _ = hasher.task_block_sha256("Hello\nWorld!\n")
        assert a != b


# ─── Counts (must reflect normalized form) ───────────────────────────────

class TestCounts:
    def test_line_count_after_normalize(self, hasher):
        _, lines, _ = hasher.task_block_sha256("\n\nHello\nWorld\n\n\n")
        assert lines == 2  # leading/trailing blanks stripped → 2 lines

    def test_byte_count_utf8(self, hasher):
        _, _, byte_count = hasher.task_block_sha256("café")
        # NFC NFKC: "café" = 5 bytes UTF-8 (c+a+f+é=2 bytes)
        assert byte_count == 5


# ─── stable_meta builder shape ───────────────────────────────────────────

class TestStableMeta:
    def test_required_keys_present(self, hasher):
        meta = hasher.stable_meta(
            task_id=3,
            phase="7.14.3",
            wave="wave-2",
            source_path="PLAN.md",
            source_format="heading",
            body_text="Some body content",
        )
        required = {
            "task_id", "task_id_str", "phase", "wave", "source_path",
            "source_format", "source_block_sha256", "source_block_line_count",
            "source_block_byte_count", "extracted_at", "vg_version", "extractor",
        }
        assert required.issubset(meta.keys()), (
            f"missing keys: {required - meta.keys()}"
        )

    def test_task_id_str_format(self, hasher):
        meta_int = hasher.stable_meta(
            task_id=5, phase="x", wave="w", source_path="x",
            source_format="heading", body_text="x",
        )
        assert meta_int["task_id_str"] == "T-5"
        assert meta_int["task_id"] == 5

    def test_meta_uses_canonical_hasher(self, hasher):
        body = "Hello\r\n\r\n\r\nWorld\r\n"
        meta = hasher.stable_meta(
            task_id=1, phase="x", wave="w", source_path="x",
            source_format="heading", body_text=body,
        )
        # The hash field must equal task_block_sha256 of the same body
        sha, _, _ = hasher.task_block_sha256(body)
        assert meta["source_block_sha256"] == sha
