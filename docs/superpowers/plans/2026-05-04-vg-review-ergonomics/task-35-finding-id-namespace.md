<!-- Per-task plan file. Self-contained — execute as instructed. -->
<!-- Index: ../2026-05-04-vg-review-ergonomics.md -->
<!-- Spec: docs/superpowers/specs/2026-05-04-vg-review-ergonomics-design.md -->

## Task 35: Finding-ID namespace EP/DR/RV/GC/FN/SC/TM-NNN

**Files:**
- Create: `scripts/lib/scanner_report_contract.py`
- Create: `scripts/validators/verify-finding-id-namespace.py`
- Modify: `commands/vg/_shared/scanner-report-contract.md` (append namespace section)
- Test: `tests/test_finding_id_namespace.py`

**Why:** PV3 review run output uses ad-hoc `E-001` for missing endpoint. AI itself doesn't know what `E-` means. Codex round-1 found 5 prefix collisions with existing IDs (`F-001` in replay-finding.py, `D-XX` decisions, `G-XX` goals, `R-XX` rules, `OD-` override-debt). Re-namespaced to 2-letter prefixes EP/DR/RV/GC/FN/SC/TM (Codex round-2 Amendment E: regex matches real PV3 format `### EP-001 [MAJOR]`).

- [ ] **Step 1: Write the failing test**

Create `tests/test_finding_id_namespace.py`:

```python
"""Task 35 — finding-ID namespace validator."""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
VALIDATOR = REPO / "scripts/validators/verify-finding-id-namespace.py"


def test_conforming_id_passes(tmp_path: Path) -> None:
    """Real PV3 format: ### EP-001 [MAJOR] GET /api/..."""
    feedback = tmp_path / "REVIEW-FEEDBACK.md"
    feedback.write_text(textwrap.dedent("""
        # Review Feedback

        ### EP-001 [MAJOR] GET /api/users — handler missing
        Description: handler not registered in app.ts.

        ### DR-002 [MINOR] Foundation drift on field naming
        Description: snake_case vs camelCase drift.
    """).strip(), encoding="utf-8")
    result = subprocess.run([
        "python3", str(VALIDATOR),
        "--feedback", str(feedback),
        "--phase", "test-1.0",
    ], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_legacy_E_001_emits_warn_telemetry(tmp_path: Path) -> None:
    """AI emits old `E-001` (from PV3 history) — validator catches + suggests fix."""
    feedback = tmp_path / "REVIEW-FEEDBACK.md"
    feedback.write_text(textwrap.dedent("""
        ### E-001 [MAJOR] GET /api/users — handler missing
    """).strip(), encoding="utf-8")
    ev_out = tmp_path / "ev.json"
    result = subprocess.run([
        "python3", str(VALIDATOR),
        "--feedback", str(feedback),
        "--phase", "test-1.0",
        "--evidence-out", str(ev_out),
    ], capture_output=True, text=True)
    # Warn-tier: returncode 0 (don't fail review yet, gradual rollout)
    assert result.returncode == 0
    import json
    ev = json.loads(ev_out.read_text(encoding="utf-8"))
    assert ev["non_conforming_count"] == 1
    assert ev["suggestions"][0]["original"] == "E-001"
    assert ev["suggestions"][0]["suggested"] == "EP-001"


def test_invalid_prefix_emits_warn(tmp_path: Path) -> None:
    """Single-letter prefix not in allowed set → suggest 2-letter equivalent."""
    feedback = tmp_path / "REVIEW-FEEDBACK.md"
    feedback.write_text(textwrap.dedent("""
        ### Z-005 [MINOR] unknown category
    """).strip(), encoding="utf-8")
    ev_out = tmp_path / "ev.json"
    subprocess.run([
        "python3", str(VALIDATOR),
        "--feedback", str(feedback),
        "--phase", "test-1.0",
        "--evidence-out", str(ev_out),
    ], capture_output=True, text=True, check=False)
    import json
    ev = json.loads(ev_out.read_text(encoding="utf-8"))
    assert ev["non_conforming_count"] == 1
    # No mapping for Z- → suggestion is null (manual review needed)
    assert ev["suggestions"][0]["suggested"] is None


def test_scanner_contract_namespace_section_present() -> None:
    """scanner-report-contract.md MUST document the prefix table."""
    text = (REPO / "commands/vg/_shared/scanner-report-contract.md").read_text(encoding="utf-8")
    for prefix in ("EP-", "DR-", "RV-", "GC-", "FN-", "SC-", "TM-"):
        assert prefix in text, f"prefix {prefix} missing from scanner-report-contract.md"


def test_module_constants() -> None:
    """scanner_report_contract.py exports the prefix list + regex."""
    sys.path.insert(0, str(REPO / "scripts/lib"))
    from scanner_report_contract import VALID_PREFIXES, FINDING_ID_REGEX
    assert "EP" in VALID_PREFIXES
    assert "DR" in VALID_PREFIXES
    assert FINDING_ID_REGEX.match("EP-001")
    assert not FINDING_ID_REGEX.match("E-001")  # 1-letter rejected
    assert not FINDING_ID_REGEX.match("EP-1")   # not zero-padded
    sys.path.remove(str(REPO / "scripts/lib"))
```

- [ ] **Step 2: Run failing tests**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -m pytest tests/test_finding_id_namespace.py -v
```

Expected: 5 failures (modules + validator + scanner-report-contract section all missing).

- [ ] **Step 3: Write the contract module**

Create `scripts/lib/scanner_report_contract.py`:

```python
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
```

- [ ] **Step 4: Write the validator**

Create `scripts/validators/verify-finding-id-namespace.py`:

```python
#!/usr/bin/env python3
"""verify-finding-id-namespace — Task 35 validator (warn-tier rollout)."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts/lib"))

from scanner_report_contract import (  # type: ignore
    FEEDBACK_HEADER_REGEX, is_conforming, suggest_replacement,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--feedback", required=True, help="path to REVIEW-FEEDBACK.md")
    parser.add_argument("--phase", required=True)
    parser.add_argument("--evidence-out")
    parser.add_argument("--severity", choices=("warn", "block"), default="warn",
                        help="warn (default, gradual rollout) or block (post-soak promotion)")
    args = parser.parse_args()

    feedback_path = Path(args.feedback)
    if not feedback_path.exists():
        print(f"ℹ no REVIEW-FEEDBACK.md at {feedback_path} — skip namespace check")
        return 0

    text = feedback_path.read_text(encoding="utf-8")
    findings: list[dict] = []
    suggestions: list[dict] = []

    for m in FEEDBACK_HEADER_REGEX.finditer(text):
        fid = m.group(1)
        conforming = is_conforming(fid)
        findings.append({"finding_id": fid, "conforming": conforming, "line_match": m.group(0)})
        if not conforming:
            suggestions.append({"original": fid, "suggested": suggest_replacement(fid)})

    summary = {
        "phase": args.phase,
        "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total": len(findings),
        "conforming_count": sum(1 for f in findings if f["conforming"]),
        "non_conforming_count": sum(1 for f in findings if not f["conforming"]),
        "suggestions": suggestions,
    }

    if args.evidence_out:
        Path(args.evidence_out).write_text(json.dumps(summary, indent=2), encoding="utf-8")

    if summary["non_conforming_count"] > 0:
        print(f"⚠ {summary['non_conforming_count']} non-conforming finding-ID(s) in REVIEW-FEEDBACK.md", file=sys.stderr)
        for s in suggestions[:5]:
            sug = s["suggested"] or "(no mapping — manual review)"
            print(f"   {s['original']} → {sug}", file=sys.stderr)

        # Emit warn-tier telemetry
        import subprocess
        subprocess.run([
            "python3", ".claude/scripts/vg-orchestrator", "emit-event",
            "review.finding_id_invalid",
            "--actor", "validator", "--outcome", "WARN",
            "--payload", json.dumps({
                "phase": args.phase,
                "non_conforming_count": summary["non_conforming_count"],
                "first_offenders": [s["original"] for s in suggestions[:3]],
            }),
        ], capture_output=True, timeout=10)

        if args.severity == "block":
            return 1  # Future: BLOCK after 14-day soak

    print(f"✓ finding-ID namespace: {summary['conforming_count']}/{summary['total']} conforming")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Append namespace section to scanner-report-contract.md**

Read existing `commands/vg/_shared/scanner-report-contract.md` first, find a sensible insertion point (after existing section on goal_class), then append:

```markdown
## Section 9 — Finding ID Namespace (Task 35)

Standardized prefixes for findings emitted to REVIEW-FEEDBACK.md /
TEST-REPORT.md / UAT.md. Validator at
`scripts/validators/verify-finding-id-namespace.py`.

| Prefix | Category | Source |
|---|---|---|
| `EP-` | Endpoint | API contract probe (Phase 2a.5), call-graph (Task 3 L4a-i) |
| `DR-` | Drift | Asserted-rule drift, foundation drift, matrix staleness |
| `RV-` | Rule-violation | Bootstrap-rule violation, scope-matched rule (Task 11) |
| `GC-` | Goal-comparison | Goal-comparison miss (Phase 4) |
| `FN-` | Foundation | FOUNDATION-DRIFT entries (distinct from `F-` replay-finding) |
| `SC-` | Schema | Contract-shape mismatch (Task 4 L4a-ii) |
| `TM-` | Telemetry | Missing required event |

ID format: `<prefix>-<3-digit-zero-padded>` (e.g. `EP-001`).

Header format in markdown reports (matches existing PV3 convention):
```
### EP-001 [MAJOR] GET /api/users — handler missing
```

Validator regex: `^###\s+(EP|DR|RV|GC|FN|SC|TM)-\d{3}\s+\[(?:CRITICAL|MAJOR|MINOR|INFO)\]\s`

### Promotion criteria

Validator runs warn-tier (severity=warn). Promote to BLOCK when:
- Zero `review.finding_id_invalid` events for 14 consecutive runs
- Across ≥2 projects

Operator-triggered (edit `--severity block` flag default in code), not auto-time-based.
```

- [ ] **Step 6: Run tests + commit**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
chmod +x scripts/validators/verify-finding-id-namespace.py
python3 -m pytest tests/test_finding_id_namespace.py -v
DEV_ROOT=. bash sync.sh --no-global 2>&1 | tail -3
git add scripts/lib/scanner_report_contract.py \
        scripts/validators/verify-finding-id-namespace.py \
        commands/vg/_shared/scanner-report-contract.md \
        tests/test_finding_id_namespace.py \
        .claude/ codex-skills/ .codex/
git commit -m "feat(review): finding-ID namespace EP/DR/RV/GC/FN/SC/TM (Task 35, Bug C)

Codex round-1 found 5 prefix collisions: F-/D-/G-/R-/OD- already used by
replay-finding/decision/goal/rule/override-debt. Re-namespaced to
non-colliding 2-letter prefixes per round-2 spec v3.1.

Validator regex matches real PV3 format ### EP-001 [MAJOR] (round-2
Amendment E). Warn-tier rollout: emit review.finding_id_invalid on
non-conforming, suggest legacy E-→EP-/D-→DR-/etc fix mapping. BLOCK
promotion after 14-day zero-event soak across ≥2 projects.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```
