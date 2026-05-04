"""Severity taxonomy + evidence schema validator for build warnings.

4-tier severity (Codex review 2026-05-03):
  BLOCK            — deterministic violation; build cannot proceed
  TRIAGE_REQUIRED  — ambiguous; user must triage; no silent forward-dep
  FORWARD_DEP      — confirmed not in current phase scope; routes to next /vg:scope
  ADVISORY         — informational; no gate

Higher weight = more severe.
"""
from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Any

import jsonschema  # type: ignore


_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "build-warning-evidence.schema.json"
_SCHEMA: dict[str, Any] | None = None


class Severity(Enum):
    BLOCK = "BLOCK"
    TRIAGE_REQUIRED = "TRIAGE_REQUIRED"
    FORWARD_DEP = "FORWARD_DEP"
    ADVISORY = "ADVISORY"

    @property
    def weight(self) -> int:
        return {
            "BLOCK": 4,
            "TRIAGE_REQUIRED": 3,
            "FORWARD_DEP": 2,
            "ADVISORY": 1,
        }[self.value]

    def blocks_build(self) -> bool:
        return self in (Severity.BLOCK, Severity.TRIAGE_REQUIRED)


def _load_schema() -> dict[str, Any]:
    global _SCHEMA
    if _SCHEMA is None:
        _SCHEMA = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    return _SCHEMA


def validate_evidence(doc: dict[str, Any]) -> None:
    """Raise jsonschema.ValidationError if doc does not conform."""
    jsonschema.validate(instance=doc, schema=_load_schema())
