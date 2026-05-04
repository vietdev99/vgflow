"""scanner_report_contract — Task 35 finding-ID namespace.

Codex round-2 amendment E: regex matches real PV3 format
`### EP-001 [MAJOR] GET /api/...` (severity in brackets, not colon).
"""
from __future__ import annotations

import re

VALID_PREFIXES = ("EP", "DR", "RV", "GC", "FN", "SC", "TM")

FINDING_ID_REGEX = re.compile(r"^(EP|DR|RV|GC|FN|SC|TM)-\d{3}$")

# Real PV3 format: ### EP-001 [MAJOR] description
FEEDBACK_HEADER_REGEX = re.compile(
    r"^###\s+([A-Z]{1,3}-\d{1,3})\s+\[(?:CRITICAL|MAJOR|MINOR|INFO)\]\s",
    re.MULTILINE,
)

# Legacy single-letter → 2-letter suggestion mapping
LEGACY_PREFIX_SUGGESTIONS = {
    "E": "EP",   # Endpoint
    "D": "DR",   # Drift (DC- decision is decision-IDs, not findings)
    "R": "RV",   # Rule-violation
    "G": "GC",   # Goal-comparison
    "F": "FN",   # Foundation
    "S": "SC",   # Schema
    "T": "TM",   # Telemetry
}


def is_conforming(finding_id: str) -> bool:
    return bool(FINDING_ID_REGEX.match(finding_id))


def suggest_replacement(finding_id: str) -> str | None:
    """Map legacy single-letter prefix to 2-letter; return None if no mapping."""
    m = re.match(r"^([A-Z])-(\d{1,3})$", finding_id)
    if not m:
        return None
    prefix, num = m.groups()
    new_prefix = LEGACY_PREFIX_SUGGESTIONS.get(prefix)
    if not new_prefix:
        return None
    return f"{new_prefix}-{int(num):03d}"
