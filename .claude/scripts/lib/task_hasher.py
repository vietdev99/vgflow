"""
task_hasher.py — Phase 16 D-01 canonical SHA256 helper.

Deterministic hash of a task block body for executor-prompt fidelity audit.
Used by:
  - pre-executor-check.py (T-1.1) to write .meta.json sidecar at extraction
  - verify-task-fidelity.py (T-4.3) to recompute + compare post-spawn

Normalization rules (chosen to be both Windows/Unix line-ending tolerant
AND robust to common whitespace edits that don't change semantics):

  1. Strip trailing whitespace per line (CRLF → LF + drop trailing spaces)
  2. Collapse runs of 3+ blank lines to a single blank line
  3. Strip leading + trailing blank lines from the whole block
  4. Apply Unicode NFC normalization (so visually-identical accented text
     hashes the same regardless of source encoding)
  5. Encode UTF-8 → SHA256 hex

Returns (hex_digest_64chars, line_count_after_normalize, byte_count_after_normalize).

EXAMPLE:
    >>> sha, lines, bytes_ = task_block_sha256("Hello\\r\\nWorld\\n\\n\\n\\n")
    >>> len(sha) == 64
    True
    >>> lines == 2
    True
    >>> bytes_ == 11  # "Hello\\nWorld" UTF-8
    True
"""
from __future__ import annotations

import hashlib
import re
import unicodedata


_BLANK_LINE_RUN = re.compile(r"\n{3,}")


def task_block_sha256(text: str) -> tuple[str, int, int]:
    """Whitespace-normalized SHA256 of a task block.

    See module docstring for normalization rules.
    """
    if text is None:
        text = ""
    # Step 1: per-line rstrip (handles CRLF + trailing spaces)
    lines = [ln.rstrip() for ln in text.splitlines()]
    # Step 2 + 3: collapse blank-line runs + strip leading/trailing blanks
    joined = "\n".join(lines)
    collapsed = _BLANK_LINE_RUN.sub("\n\n", joined).strip("\n")
    # Step 4: NFC normalize (handles `é` vs `e + combining acute`)
    normalized = unicodedata.normalize("NFC", collapsed)
    # Step 5: hash
    blob = normalized.encode("utf-8")
    return (
        hashlib.sha256(blob).hexdigest(),
        len(normalized.splitlines()) if normalized else 0,
        len(blob),
    )


def stable_meta(
    task_id: int | str,
    phase: str,
    wave: str,
    source_path: str,
    source_format: str,
    body_text: str,
    extracted_at: str | None = None,
    vg_version: str | None = None,
) -> dict:
    """Build the .meta.json shape per Phase 16 D-01 spec.

    Pure helper — does not write the file (caller controls IO).
    """
    sha, line_count, byte_count = task_block_sha256(body_text)
    if extracted_at is None:
        from datetime import datetime, timezone
        extracted_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    if vg_version is None:
        # Best-effort version from VERSION file at repo root; tolerant if missing.
        try:
            from pathlib import Path as _P
            vroot = _P(__file__).resolve().parents[2] / "VERSION"
            vg_version = vroot.read_text(encoding="utf-8").strip() if vroot.exists() else "unknown"
        except Exception:
            vg_version = "unknown"
    task_id_str = (
        f"T-{task_id}" if isinstance(task_id, int) or str(task_id).isdigit() else str(task_id)
    )
    return {
        "task_id": int(task_id) if str(task_id).isdigit() else task_id,
        "task_id_str": task_id_str,
        "phase": phase,
        "wave": wave,
        "source_path": source_path,
        "source_format": source_format,  # "heading" | "xml"
        "source_block_sha256": sha,
        "source_block_line_count": line_count,
        "source_block_byte_count": byte_count,
        "extracted_at": extracted_at,
        "vg_version": vg_version,
        "extractor": "pre-executor-check.py:extract_task_section_v2",
    }
