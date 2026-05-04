<!-- Per-task plan file. Self-contained — execute as instructed. -->
<!-- Index: ../2026-05-03-vg-build-in-scope-fix-loop.md -->
<!-- Plan: 2026-05-03-vg-build-in-scope-fix-loop -->


## Task 1: Severity taxonomy + evidence schema

**Files:**
- Create: `scripts/lib/severity_taxonomy.py`
- Create: `schemas/build-warning-evidence.schema.json`
- Test: `tests/test_severity_taxonomy.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_severity_taxonomy.py`:

```python
"""Severity taxonomy enum + machine-readable evidence shape."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def test_severity_enum_has_4_tiers() -> None:
    import sys
    sys.path.insert(0, str(REPO / "scripts" / "lib"))
    from severity_taxonomy import Severity  # type: ignore

    assert {s.value for s in Severity} == {
        "BLOCK", "TRIAGE_REQUIRED", "FORWARD_DEP", "ADVISORY",
    }


def test_severity_ordering() -> None:
    import sys
    sys.path.insert(0, str(REPO / "scripts" / "lib"))
    from severity_taxonomy import Severity  # type: ignore

    # BLOCK is most severe; ADVISORY least.
    assert Severity.BLOCK.weight > Severity.TRIAGE_REQUIRED.weight
    assert Severity.TRIAGE_REQUIRED.weight > Severity.FORWARD_DEP.weight
    assert Severity.FORWARD_DEP.weight > Severity.ADVISORY.weight


def test_evidence_schema_validates_minimal_doc() -> None:
    import sys
    sys.path.insert(0, str(REPO / "scripts" / "lib"))
    from severity_taxonomy import validate_evidence  # type: ignore

    doc = {
        "warning_id": "fe-be-gap-1",
        "severity": "BLOCK",
        "category": "fe_be_call_graph",
        "phase": "4.1",
        "evidence_refs": [{"file": "apps/web/src/pages/InvoiceDetailPage.tsx", "line": 42}],
        "summary": "FE calls GET /api/v1/admin/invoices/:id/payments — BE has no GET handler",
        "detected_by": "verify-fe-be-call-graph.py",
        "detected_at": "2026-05-03T10:00:00Z",
    }
    validate_evidence(doc)  # raises on schema violation


def test_evidence_schema_rejects_missing_severity() -> None:
    import sys
    sys.path.insert(0, str(REPO / "scripts" / "lib"))
    from severity_taxonomy import validate_evidence  # type: ignore

    doc = {"warning_id": "x", "category": "y", "phase": "1.0",
           "evidence_refs": [], "summary": "x", "detected_by": "x",
           "detected_at": "2026-01-01T00:00:00Z"}
    with pytest.raises(Exception, match="severity"):
        validate_evidence(doc)
```

- [ ] **Step 2: Run tests to confirm fail**

Run: `cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix" && python3 -m pytest tests/test_severity_taxonomy.py -v`
Expected: 4 failures (module + schema do not exist).

- [ ] **Step 3: Write the schema + module**

Create `schemas/build-warning-evidence.schema.json`:

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "BuildWarningEvidence",
  "type": "object",
  "required": ["warning_id", "severity", "category", "phase", "evidence_refs", "summary", "detected_by", "detected_at"],
  "properties": {
    "warning_id":   {"type": "string", "minLength": 1},
    "severity":     {"type": "string", "enum": ["BLOCK", "TRIAGE_REQUIRED", "FORWARD_DEP", "ADVISORY"]},
    "category":     {"type": "string", "enum": [
      "fe_be_call_graph", "contract_shape_mismatch", "spec_drift",
      "i18n_coverage", "a11y_coverage", "perf_budget", "visual_drift",
      "test_gap", "other"
    ]},
    "phase":        {"type": "string", "minLength": 1},
    "evidence_refs": {
      "type": "array",
      "minItems": 1,
      "items": {
        "type": "object",
        "required": ["file"],
        "properties": {
          "file":      {"type": "string"},
          "line":      {"type": "integer", "minimum": 1},
          "snippet":   {"type": "string"},
          "endpoint":  {"type": "string"},
          "task_id":   {"type": "string"}
        }
      }
    },
    "summary":      {"type": "string", "minLength": 1},
    "detected_by":  {"type": "string", "minLength": 1},
    "detected_at":  {"type": "string", "format": "date-time"},
    "owning_artifact": {"type": "string"},
    "recommended_action": {"type": "string"},
    "confidence":   {"type": "number", "minimum": 0.0, "maximum": 1.0}
  }
}
```

Create `scripts/lib/severity_taxonomy.py`:

```python
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
```

- [ ] **Step 4: Run tests to confirm pass**

Run:
```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -c "import jsonschema" 2>/dev/null || pip3 install jsonschema
python3 -m pytest tests/test_severity_taxonomy.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/severity_taxonomy.py schemas/build-warning-evidence.schema.json tests/test_severity_taxonomy.py
git commit -m "feat(build-fix-loop): add 4-tier severity taxonomy + evidence schema"
```

---

