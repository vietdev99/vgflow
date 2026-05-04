"""
Content-aware evidence checks. Beats the "echo TODO > PLAN.md" bypass
where an empty file passes basic file-exists gate.
"""
from __future__ import annotations

from pathlib import Path


def check_artifact(path: Path, min_bytes: int = 1,
                   required_sections: list[str] | None = None,
                   glob_fallback: bool = True) -> dict:
    """
    Returns {"ok": bool, "reason": str|None, "matched_path": str|None}.
    Checks:
    - file exists (with glob fallback — sibling like `{N}-UAT.md` satisfies
      a `UAT.md` contract when glob_fallback=True)
    - size >= min_bytes
    - contains every string in required_sections (substring match)

    Glob fallback rationale: accept.md writes `{PHASE_NUMBER}-UAT.md` but
    contract declares `${PHASE_DIR}/UAT.md`. Same semantic artifact, two
    filenames. Rather than mutate the contract schema or the code, match
    glob pattern `*{stem}*{suffix}` in parent dir. Strict mode
    (glob_fallback=False) preserves legacy behavior for tests that assert
    exact-path missing.
    """
    resolved = path
    if not path.exists() and glob_fallback and path.parent.exists():
        # Try globs: exact, `*<name>`, `<stem>*<suffix>`
        stem, suffix = path.stem, path.suffix
        patterns = [f"*{path.name}", f"{stem}*{suffix}", f"*{stem}*{suffix}"]
        for pat in patterns:
            matches = sorted(path.parent.glob(pat))
            if matches:
                resolved = matches[0]
                break

    if not resolved.exists():
        return {"ok": False, "reason": "missing", "matched_path": None}
    size = resolved.stat().st_size
    if size < min_bytes:
        return {"ok": False,
                "reason": f"too-small ({size} < {min_bytes})",
                "matched_path": str(resolved)}

    if required_sections:
        try:
            text = resolved.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return {"ok": False, "reason": f"unreadable: {e}",
                    "matched_path": str(resolved)}
        missing = [s for s in required_sections if s not in text]
        if missing:
            return {"ok": False,
                    "reason": f"missing-sections: {missing}",
                    "matched_path": str(resolved)}

    return {"ok": True, "reason": None, "matched_path": str(resolved)}


def check_telemetry(expected: list[dict], events: list[dict]) -> list[str]:
    """
    Returns list of missing telemetry event types (strings for error messages).
    Supports must_pair_with: event X requires matching event Y.
    """
    # Index events by type for fast lookup
    type_counts = {}
    for evt in events:
        et = evt.get("event_type")
        if et:
            type_counts[et] = type_counts.get(et, 0) + 1

    missing = []
    for spec in expected:
        event_type = spec["event_type"]
        min_count = int(spec.get("min_count", 1))
        actual_count = type_counts.get(event_type, 0)
        if actual_count < min_count:
            missing.append(
                f"{event_type} (expected ≥{min_count}, got {actual_count})"
            )
            continue

        pair = spec.get("must_pair_with")
        if pair:
            pair_count = type_counts.get(pair, 0)
            if pair_count < actual_count:
                missing.append(
                    f"{event_type} unpaired — {actual_count} without matching {pair}"
                )

    return missing
