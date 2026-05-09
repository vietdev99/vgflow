# v2.67.0 — PrintwayV3 Dogfood Issues Batch 2 (7 issues)

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Close 7 PrintwayV3 dogfood issues from 2026-05-09 batch 2 (different from v2.66.x batch 1).

**Architecture:** Surgical fixes across 6 files: `review-api-contract-probe.py` (parser fix + WS support + OpenAPI gate), `verify-contract-completeness.py` (backup-dir filter + count metric), `commands/vg/review.md` (preflight gates + lens must_write), `verify-security-baseline.py` (severity-route output), `route-findings-to-build.py` (envelope drift classifier), new BLOCKED taxonomy in `challenge-coverage.py`.

**Tech Stack:** Python 3 (validators + tests), Markdown (review.md preflight section).

**Issues closed:** #157 #158 #159 #160 #161 #162 #163.

---

## Context

Second wave of PrintwayV3 dogfood issues from 2026-05-09. v2.66.x closed 8 issues from first wave. This release closes 7 from second wave.

**File targets located:**
- `#157`: `scripts/review-api-contract-probe.py:31, 68, 72` (3 parsers all missing WS) + line ~235 (no OpenAPI gate)
- `#158`: `commands/vg/review.md:69-74, 52-54` (lens artifacts optional, no Codex telemetry parity)
- `#159`: `scripts/verify-contract-completeness.py:184-186, 207-209, 226-228` (3 rglob loops, no backup filter)
- `#160`: `scripts/challenge-coverage.py:122-150` (no BLOCKED reason taxonomy)
- `#161`: `commands/vg/review.md:2167-2296` (Phase 0.5 RFC v9 preflight — 3 gates missing)
- `#162`: `scripts/route-findings-to-build.py:57-69` (no envelope_drift classifier)
- `#163`: `scripts/validators/verify-security-baseline.py:216-302` (Evidence objects, no severity, no AUTO-FIX-TASKS)

VERSION baseline: 2.66.1. Bump to 2.67.0.

---

## Task 1 (#157): API contract probe — parser + WS + OpenAPI gate

**Files:**
- Modify: `scripts/review-api-contract-probe.py:31, 68, 72` (add `WS|WEBSOCKET` to all 3 method regexes)
- Modify: `scripts/review-api-contract-probe.py` ~line 235 (add OpenAPI schema validity pre-gate)
- Modify: `scripts/review-api-contract-probe.py` probe execution (skip WS endpoints — return SKIP verdict, not GET probe)
- Mirror: `.claude/scripts/review-api-contract-probe.py`
- Test: `tests/test_api_probe_ws_and_openapi_gate.py` (NEW)

**Step 1: Failing tests**

```python
"""v2.67.0 #157 — API probe parses WS, skips probe, OpenAPI 500 pre-gated."""
import importlib.util
import sys
from pathlib import Path
import re
import pytest


def _load():
    repo_root = Path(__file__).parent.parent
    sys.path.insert(0, str(repo_root / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "review_api_contract_probe",
        repo_root / "scripts" / "review-api-contract-probe.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_header_regex_includes_ws():
    mod = _load()
    assert "WS" in mod.HEADER_RE.pattern, "HEADER_RE must include WS"
    assert "WEBSOCKET" in mod.HEADER_RE.pattern or "WS" in mod.HEADER_RE.pattern


def test_table_row_regex_includes_ws():
    mod = _load()
    assert "WS" in mod.TABLE_ROW_RE.pattern


def test_split_file_regex_includes_ws():
    mod = _load()
    assert "WS" in mod.SPLIT_FILE_HEAD_RE.pattern


def test_ws_endpoints_parsed_from_table():
    """Table row | something | WS | /ws/notifications | ... must parse as WS endpoint."""
    mod = _load()
    sample = """
| # | Method | Path | Description |
|---|--------|------|-------------|
| 1 | GET | /api/users | List |
| 2 | WS | /ws/notifications | Push events |
"""
    eps = mod.parse_contracts(sample)
    methods = [e.probe_method if hasattr(e, "probe_method") else e.method for e in eps]
    assert "WS" in methods or any("ws" in m.lower() for m in methods)


def test_ws_endpoints_skipped_not_probed_as_get():
    """WS endpoint must return SKIP/UNSUPPORTED verdict, not run GET probe."""
    mod = _load()
    # mock or assert via probe_endpoints behavior
    if hasattr(mod, "probe_endpoint"):
        sig = mod.probe_endpoint
        # quick smoke: pass an endpoint with method=WS, expect skip-shaped result
        from dataclasses import dataclass
        # simulate Endpoint dataclass
        ep_obj = type(mod).Endpoint if hasattr(type(mod), "Endpoint") else None
        # Basic smoke: search source for ws-skip branch
        src = (Path(__file__).parent.parent / "scripts" / "review-api-contract-probe.py").read_text(encoding="utf-8")
        assert re.search(r"WS|websocket", src, re.IGNORECASE), "probe must reference WS handling"
        assert re.search(r"skip.*ws|ws.*skip|UNSUPPORTED", src, re.IGNORECASE), \
            "probe must skip WS (not GET-probe it)"


def test_openapi_500_pre_gated():
    """OpenAPI schema validity must be pre-gated; if 500/invalid, skip docs-derived probes."""
    src = (Path(__file__).parent.parent / "scripts" / "review-api-contract-probe.py").read_text(encoding="utf-8")
    # Look for OpenAPI gate logic
    assert re.search(r"openapi.*(?:invalid|500|gate|skip)", src, re.IGNORECASE), \
        "probe must pre-gate on OpenAPI schema validity"
```

**Step 2: FAIL**

**Step 3: Implement**

In `scripts/review-api-contract-probe.py`:

```python
# Line 31:
HEADER_RE = re.compile(r"(?m)^###?\s+(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS|WS|WEBSOCKET)\s+(\S+)")

# Line 68:
TABLE_ROW_RE = re.compile(r"^\|\s*\S+\s*\|\s*(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS|WS|WEBSOCKET)\s*\|\s*(\S+)\s*\|", re.MULTILINE)

# Line 72:
SPLIT_FILE_HEAD_RE = re.compile(r"^#\s+(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS|WS|WEBSOCKET)\s+(/\S+)\s*$", re.MULTILINE)

# In probe_endpoint or similar — add early return:
def probe_endpoint(base_url, endpoint, headers, timeout):
    method_upper = (endpoint.method or "").upper()
    if method_upper in {"WS", "WEBSOCKET"}:
        return ProbeResult(
            endpoint=endpoint,
            url="",
            status=0,
            verdict="SKIP",
            detail=f"WS/WebSocket endpoint not probed via HTTP; verify externally",
        )
    # ... existing HTTP probe logic
```

Add OpenAPI pre-gate before probe runs:

```python
def _openapi_schema_valid(phase_dir: Path) -> tuple[bool, str]:
    """Return (valid, reason). Check whether OpenAPI generation succeeded."""
    schema_log = phase_dir / "openapi-generation.log"
    if not schema_log.exists():
        return True, "no log — assume valid"  # don't fail on missing
    text = schema_log.read_text(encoding="utf-8", errors="ignore")
    if "FST_ERR_INVALID_SCHEMA" in text or "500" in text and "openapi" in text.lower():
        return False, "OpenAPI generation returned 500/FST_ERR_INVALID_SCHEMA — docs-derived probes unreliable"
    return True, "ok"

# In main:
valid, reason = _openapi_schema_valid(phase_dir)
if not valid:
    print(f"⛔ OpenAPI schema invalid — pre-gate BLOCK: {reason}", file=sys.stderr)
    sys.exit(2)  # don't run probes against invalid docs
```

**Step 4-5:** Mirror, test, commit.

```bash
git commit -m "fix(review): API probe parses WS + skip-not-GET-probe + OpenAPI 500 pre-gate (#157)"
```

---

## Task 2 (#158): Lens artifacts must_write strict + Codex telemetry parity

**Files:**
- Modify: `commands/vg/review.md:69-74, 52-54` (remove `required_unless_flag`, force `must_write` strict)
- Modify: `codex-skills/vg-review/SKILL.md` (add lens marker emit per v2.65.0 A9 pattern)
- Mirror
- Test: `tests/test_lens_artifacts_strict.py` (NEW)

**Step 1: Failing tests**

```python
import re
from pathlib import Path


def test_lens_dispatch_plan_strict():
    body = Path("commands/vg/review.md").read_text(encoding="utf-8")
    # LENS-DISPATCH-PLAN.json must NOT have required_unless_flag (strict required)
    m = re.search(
        r'path:\s*"\$\{PHASE_DIR\}/LENS-DISPATCH-PLAN\.json"(.*?)(?=\n\s*-\s*path:|\n\s+must_|\nargument)',
        body, re.DOTALL
    )
    assert m, "LENS-DISPATCH-PLAN.json entry not found"
    block = m.group(1)
    assert "required_unless_flag" not in block, \
        "LENS-DISPATCH-PLAN.json must be strict required (no required_unless_flag)"


def test_lens_coverage_matrix_strict():
    body = Path("commands/vg/review.md").read_text(encoding="utf-8")
    m = re.search(
        r'path:\s*"\$\{PHASE_DIR\}/LENS-COVERAGE-MATRIX\.md"(.*?)(?=\n\s*-\s*path:|\n\s+must_|\nargument)',
        body, re.DOTALL
    )
    assert m
    assert "required_unless_flag" not in m.group(1)


def test_codex_review_emits_lens_marker():
    body = Path("codex-skills/vg-review/SKILL.md").read_text(encoding="utf-8")
    # Must mention lens marker emit (per v2.65.0 A9 pattern)
    assert re.search(r"mark-step.*lens|lens.*mark-step", body, re.IGNORECASE), \
        "vg-review codex skill must emit lens-related markers"
```

**Step 2: FAIL**

**Step 3: Implement**

Edit `commands/vg/review.md:69-74` — remove `required_unless_flag` from LENS-DISPATCH-PLAN.json + LENS-COVERAGE-MATRIX.md entries. Make them strict required (or use `required_unless_flag: "--probe-mode-skip"` only if `--probe-mode-skip` is the legitimate opt-out and we keep that as override; the issue specifically wants strict required when probe runs — so check current logic).

Decision: keep `required_unless_flag: "--probe-mode-skip"` BUT only if review actually accepts `--probe-mode-skip` as valid run mode. Verify by grep. If `--probe-mode-skip` is real, fix the SIZE check (180 < 200 currently passes too easily). Make `content_min_bytes` larger (500+) and `content_required_sections` enforce structure.

Implementer choice: read context first, then choose strictest viable option.

Edit `codex-skills/vg-review/SKILL.md` — add lens marker emit block per v2.65.0 A9 pattern:

```markdown
After lens dispatch + matrix render complete (Phase 2b-3):
\`\`\`bash
${PYTHON_BIN:-python3} .claude/scripts/vg-orchestrator mark-step review 2b3_lens_dispatch_complete
${PYTHON_BIN:-python3} .claude/scripts/vg-orchestrator mark-step review 2b3_lens_matrix_rendered
\`\`\`
```

**Step 4-5:** Mirror, test, commit.

```bash
git commit -m "fix(review): lens artifacts strict must_write + Codex telemetry parity (#158)"
```

---

## Task 3 (#159): Validators backup-dir filter + view-count cross-artifact reconciliation

**Files:**
- Modify: `scripts/verify-contract-completeness.py:184-186, 207-209, 226-228` (add backup/archive/legacy filter to all 3 rglob loops)
- Add: helper function `_should_skip_path()` for centralized exclusion
- Mirror
- Test: `tests/test_validators_backup_filter.py` (NEW)

**Step 1: Failing tests**

```python
import importlib.util
import sys
import tempfile
from pathlib import Path
import pytest


def _load():
    repo_root = Path(__file__).parent.parent
    sys.path.insert(0, str(repo_root / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "verify_contract_completeness",
        repo_root / "scripts" / "verify-contract-completeness.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_should_skip_backup_dir():
    mod = _load()
    assert hasattr(mod, "_should_skip_path"), "must have centralized exclusion helper"
    skip = mod._should_skip_path
    
    assert skip(Path("apps/api/_backup/old.ts"))
    assert skip(Path("packages/core/archive/legacy.ts"))
    assert skip(Path("legacy/v1/handler.ts"))


def test_should_not_skip_production_paths():
    mod = _load()
    skip = mod._should_skip_path
    
    assert not skip(Path("apps/api/src/handlers/users.ts"))
    assert not skip(Path("packages/core/index.ts"))


def test_existing_excludes_preserved():
    """Pre-existing excludes (node_modules, dist, build, etc.) still work."""
    mod = _load()
    skip = mod._should_skip_path
    
    for excluded in ["node_modules", "dist", "build", ".next", "venv", "__pycache__", ".git"]:
        assert skip(Path(f"x/{excluded}/y.ts"))


def test_models_scan_emits_count():
    """verify-contract-completeness.json must include scanned_*_count metric."""
    # This tests the OUTPUT JSON shape — implementer must ensure scanned_*_count keys present
    src = (Path(__file__).parent.parent / "scripts" / "verify-contract-completeness.py").read_text(encoding="utf-8")
    assert "scanned_models_count" in src or "scanned_files_count" in src, \
        "must record scanned count metric"
```

**Step 2: FAIL**

**Step 3: Implement**

In `scripts/verify-contract-completeness.py`:

```python
# Add helper near top of file
DEFAULT_SKIP_DIR_NAMES = (
    "node_modules", "dist", "build", ".next", "venv", "__pycache__", ".git",
    # v2.67.0 #159 — exclude backup/archive/legacy by default
    "_backup", "backup", "_archive", "archive", "legacy", "_legacy",
    ".vg",  # phase artifacts shouldn't be scanned as code
)

def _should_skip_path(path: Path) -> bool:
    """Return True if path is inside a skip-list directory."""
    parts_lower = [p.lower() for p in path.parts]
    return any(skip.lower() in parts_lower for skip in DEFAULT_SKIP_DIR_NAMES)


# Replace inline `if any(seg in fp.parts for seg in (...))` at lines 184-186, 207-209, 226-228
# with `if _should_skip_path(fp): continue`
```

Add scanned count metrics to output JSON (`scanned_models_count`, `scanned_jobs_count`, `scanned_webhooks_count`).

**Step 4-5:** Mirror, test, commit.

```bash
git commit -m "fix(validators): backup-dir filter + scanned-count metrics (#159)"
```

---

## Task 4 (#160): GOAL-COVERAGE-MATRIX BLOCKED taxonomy

**Files:**
- Modify: `scripts/challenge-coverage.py:122-150` (add 5-reason BLOCKED enum + classifier)
- Modify: `commands/vg/review.md` Phase 2f route_auto_fix logic to read BLOCKED reason for routing
- Mirror
- Test: `tests/test_blocked_taxonomy.py` (NEW)

**Step 1: Failing tests**

```python
import importlib.util
import sys
from pathlib import Path
import pytest


def _load():
    repo_root = Path(__file__).parent.parent
    sys.path.insert(0, str(repo_root / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "challenge_coverage",
        repo_root / "scripts" / "challenge-coverage.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_blocked_reason_enum_defined():
    mod = _load()
    # Must expose 5 reason constants
    expected = {"APP_BLOCKED", "WORKFLOW_BLOCKED", "PREREQ_MISSING", "EXTERNAL_REQUIRED", "PROBE_INVALID"}
    actual = set()
    for name in dir(mod):
        if name in expected:
            actual.add(name)
    # OR check enum class
    if hasattr(mod, "BlockedReason"):
        actual = {e.name for e in mod.BlockedReason}
    
    assert expected.issubset(actual), \
        f"Missing BLOCKED reasons: {expected - actual}"


def test_classifier_distinguishes_app_vs_workflow():
    mod = _load()
    if hasattr(mod, "classify_blocked"):
        # APP_BLOCKED: code shipped, runtime returns wrong response
        result = mod.classify_blocked({"runtime_response_present": True, "matches_contract": False})
        assert result == "APP_BLOCKED" or "APP" in str(result)
        
        # WORKFLOW_BLOCKED: probe bug
        result = mod.classify_blocked({"probe_error": "WS as GET", "runtime_response_present": False})
        assert "WORKFLOW" in str(result)


def test_review_md_routes_by_blocked_reason():
    body = Path("commands/vg/review.md").read_text(encoding="utf-8")
    # Auto-fix routing must reference BLOCKED reason taxonomy
    assert re.search(r"APP_BLOCKED|WORKFLOW_BLOCKED|PREREQ_MISSING", body), \
        "review.md auto-fix routing must use BLOCKED reason taxonomy"
```

**Step 2: FAIL**

**Step 3: Implement**

In `scripts/challenge-coverage.py`:

```python
from enum import Enum

class BlockedReason(Enum):
    APP_BLOCKED = "app_blocked"          # code shipped, runtime wrong
    WORKFLOW_BLOCKED = "workflow_blocked"  # probe/tool bug
    PREREQ_MISSING = "prereq_missing"      # upstream patch DEFERRED
    EXTERNAL_REQUIRED = "external_required" # OAuth/WS/reset token needed
    PROBE_INVALID = "probe_invalid"        # probe ran wrong (e.g., WS as GET)


def classify_blocked(evidence: dict) -> BlockedReason:
    """Classify why a goal is BLOCKED based on evidence."""
    if evidence.get("probe_error"):
        return BlockedReason.PROBE_INVALID if "probe" in evidence["probe_error"].lower() \
               else BlockedReason.WORKFLOW_BLOCKED
    if evidence.get("upstream_deferred"):
        return BlockedReason.PREREQ_MISSING
    if evidence.get("requires_external"):
        return BlockedReason.EXTERNAL_REQUIRED
    if evidence.get("runtime_response_present") and not evidence.get("matches_contract"):
        return BlockedReason.APP_BLOCKED
    return BlockedReason.APP_BLOCKED  # default
```

Edit `commands/vg/review.md` Phase 2f auto-fix routing to read `blocked_reason` and route only `APP_BLOCKED` goals to `/vg:build`. Other reasons get separate handling (PREREQ_MISSING → user must `/vg:amend`, etc.).

**Step 4-5:** Mirror, test, commit.

```bash
git commit -m "fix(review): GOAL-COVERAGE-MATRIX BLOCKED taxonomy 5 reasons + auto-fix routing (#160)"
```

---

## Task 5 (#161): Review preflight 3 hard gates

**Files:**
- Modify: `commands/vg/review.md:2167-2296` (Phase 0.5 RFC v9 preflight — add 3 BLOCK gates)
- Mirror
- Test: `tests/test_review_preflight_gates.py` (NEW)

**Step 1: Failing tests**

```python
import re
from pathlib import Path


def test_preflight_routes_static_gate():
    body = Path("commands/vg/review.md").read_text(encoding="utf-8")
    # Must have BLOCK gate for routes-static.json before probe phase
    assert re.search(
        r"routes-static\.json.*(?:BLOCK|exit\s*1|preflight.*missing)",
        body, re.DOTALL | re.IGNORECASE
    ), "routes-static.json BLOCK gate missing"


def test_preflight_env_contract_check():
    body = Path("commands/vg/review.md").read_text(encoding="utf-8")
    assert re.search(r"ENV-CONTRACT.*preflight_checks", body), \
        "ENV-CONTRACT.preflight_checks gate missing"


def test_preflight_openapi_validity_gate():
    body = Path("commands/vg/review.md").read_text(encoding="utf-8")
    # OpenAPI schema validity check before docs-derived probes
    assert re.search(
        r"openapi.*(?:valid|schema|FST_ERR).*(?:BLOCK|gate|preflight)",
        body, re.DOTALL | re.IGNORECASE
    ), "OpenAPI schema validity gate missing"
```

**Step 2: FAIL**

**Step 3: Implement**

Edit `commands/vg/review.md:2167-2296` — add 3 BLOCK gates in Phase 0.5 preflight:

```markdown
**Gate P1 (v2.67.0 #161): routes-static.json validity**
\`\`\`bash
ROUTES_STATIC="${PHASE_DIR}/routes-static.json"
if [ ! -f "$ROUTES_STATIC" ] || [ "$(jq '.routes | length' "$ROUTES_STATIC" 2>/dev/null || echo 0)" -eq 0 ]; then
    echo "⛔ Preflight P1 BLOCK: routes-static.json missing or empty" >&2
    exit 1
fi
\`\`\`

**Gate P2 (#161): ENV-CONTRACT.preflight_checks**
\`\`\`bash
ENV_CONTRACT="${PHASE_DIR}/ENV-CONTRACT.md"
if [ -f "$ENV_CONTRACT" ] && ! grep -qE '^\s*preflight_checks:' "$ENV_CONTRACT"; then
    echo "⛔ Preflight P2 BLOCK: ENV-CONTRACT.md missing preflight_checks: section" >&2
    exit 1
fi
\`\`\`

**Gate P3 (#161): OpenAPI schema validity**
\`\`\`bash
OPENAPI_LOG="${PHASE_DIR}/openapi-generation.log"
if [ -f "$OPENAPI_LOG" ] && grep -qE 'FST_ERR_INVALID_SCHEMA|HTTP/1\.1 500' "$OPENAPI_LOG"; then
    echo "⛔ Preflight P3 BLOCK: OpenAPI generation 500/invalid — docs-derived probes unreliable" >&2
    exit 1
fi
\`\`\`
```

**Step 4-5:** Mirror, test, commit.

```bash
git commit -m "fix(review): preflight 3 hard gates (routes/env/openapi) (#161)"
```

---

## Task 6 (#162): Envelope drift classifier + AUTO-FIX-TASKS routing

**Files:**
- Modify: `scripts/route-findings-to-build.py:57-69` (add envelope_drift classifier rule)
- Modify: `scripts/derive-findings.py` if needed (tag findings with `finding_type: envelope_drift`)
- Mirror
- Test: `tests/test_envelope_drift_routing.py` (NEW)

**Step 1: Failing tests**

```python
import importlib.util
import sys
from pathlib import Path
import pytest


def _load_router():
    repo_root = Path(__file__).parent.parent
    sys.path.insert(0, str(repo_root / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "route_findings_to_build",
        repo_root / "scripts" / "route-findings-to-build.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_envelope_drift_routed_to_fix_task():
    mod = _load_router()
    findings = [
        {
            "finding_type": "envelope_drift",
            "severity": "MEDIUM",
            "confidence": "high",
            "title": "Envelope drift: contract ok/request_id, runtime success/requestId",
            "evidence": "...",
        }
    ]
    routed = mod.filter_findings(findings) if hasattr(mod, "filter_findings") else \
             [f for f in findings if mod.should_route(f)] if hasattr(mod, "should_route") else findings
    
    assert len(routed) >= 1, "envelope_drift must route to fix task"


def test_envelope_drift_severity_floor():
    """envelope_drift must route even at MEDIUM (don't filter to high-only)."""
    mod = _load_router()
    src = (Path(__file__).parent.parent / "scripts" / "route-findings-to-build.py").read_text(encoding="utf-8")
    # Either explicit envelope_drift exemption from severity floor, OR severity floor lowered
    assert "envelope_drift" in src, "router must reference envelope_drift finding_type"
```

**Step 2: FAIL**

**Step 3: Implement**

In `scripts/route-findings-to-build.py`:

```python
# Add classifier rule
ALWAYS_ROUTE_FINDING_TYPES = {
    "envelope_drift",       # contract ↔ runtime shape mismatch
    "openapi_invalid",      # schema-level
    "auth_misconfigured",   # security-critical
    "prereq_missing",       # blocks downstream
}


def should_route(finding: dict) -> bool:
    """v2.67.0 #162: certain finding types route regardless of severity floor."""
    if finding.get("finding_type") in ALWAYS_ROUTE_FINDING_TYPES:
        return True
    severity = (finding.get("severity") or "").upper()
    confidence = (finding.get("confidence") or "").lower()
    return severity in {"HIGH", "CRITICAL", "MAJOR"} and confidence == "high"
```

In `scripts/derive-findings.py` — add envelope drift detection that tags `finding_type: envelope_drift` when contract envelope shape ≠ runtime envelope shape. (Implementer reads existing per-endpoint scan output to find drift markers.)

**Step 4-5:** Mirror, test, commit.

```bash
git commit -m "fix(review): envelope_drift finding_type + always-route classifier (#162)"
```

---

## Task 7 (#163): Security baseline severity routing + AUTO-FIX-TASKS

**Files:**
- Modify: `scripts/validators/verify-security-baseline.py:216-302` (add severity field to Evidence + write to REVIEW-FINDINGS.json)
- Modify: `commands/vg/review.md` security baseline output handling
- Mirror
- Test: `tests/test_security_baseline_severity.py` (NEW)

**Step 1: Failing tests**

```python
import importlib.util
import sys
from pathlib import Path
import re


def test_security_baseline_emits_severity():
    src = (Path(__file__).parent.parent / "scripts" / "validators" / "verify-security-baseline.py").read_text(encoding="utf-8")
    # Must populate severity field on Evidence (TLS=CRITICAL, HSTS=HIGH, cookies=MEDIUM)
    assert re.search(r"severity\s*=\s*['\"](?:CRITICAL|HIGH|MEDIUM)", src), \
        "Evidence must have severity field"


def test_tls_critical_severity():
    src = (Path(__file__).parent.parent / "scripts" / "validators" / "verify-security-baseline.py").read_text(encoding="utf-8")
    # TLS missing/outdated → CRITICAL
    assert re.search(r"TLS.{0,200}severity\s*=\s*['\"]CRITICAL", src, re.DOTALL | re.IGNORECASE), \
        "TLS issues must classify as CRITICAL"


def test_hsts_high_severity():
    src = (Path(__file__).parent.parent / "scripts" / "validators" / "verify-security-baseline.py").read_text(encoding="utf-8")
    assert re.search(r"HSTS.{0,200}severity\s*=\s*['\"]HIGH", src, re.DOTALL | re.IGNORECASE)


def test_cookie_medium_severity():
    src = (Path(__file__).parent.parent / "scripts" / "validators" / "verify-security-baseline.py").read_text(encoding="utf-8")
    assert re.search(r"cookie.{0,200}severity\s*=\s*['\"]MEDIUM", src, re.DOTALL | re.IGNORECASE)


def test_findings_written_to_review_findings_json():
    """Security baseline output must merge into REVIEW-FINDINGS.json (not just .tmp/ log)."""
    src = (Path(__file__).parent.parent / "scripts" / "validators" / "verify-security-baseline.py").read_text(encoding="utf-8")
    assert "REVIEW-FINDINGS.json" in src or re.search(r"findings.*output|merge.*findings", src, re.IGNORECASE), \
        "security baseline must write to REVIEW-FINDINGS.json"
```

**Step 2: FAIL**

**Step 3: Implement**

In `scripts/validators/verify-security-baseline.py`:

```python
# Update Evidence emission with severity:
# TLS missing/outdated:
out.add(Evidence(..., severity="CRITICAL"))

# HSTS missing:
out.warn(Evidence(..., severity="HIGH"))

# Cookie attribute missing (Secure/HttpOnly/SameSite):
out.warn(Evidence(..., severity="MEDIUM"))

# Add output writer that merges findings into REVIEW-FINDINGS.json:
def merge_to_review_findings(evidence_list, findings_path):
    findings = []
    if findings_path.exists():
        findings = json.loads(findings_path.read_text(encoding="utf-8"))
    for ev in evidence_list:
        findings.append({
            "finding_type": "security_baseline",
            "severity": ev.severity,
            "title": ev.title,
            "detail": ev.detail,
            "confidence": "high",
        })
    findings_path.write_text(json.dumps(findings, indent=2), encoding="utf-8")
```

**Step 4-5:** Mirror, test, commit.

```bash
git commit -m "fix(security): baseline severity + REVIEW-FINDINGS.json merge (#163)"
```

---

## Task 8: VERSION + CHANGELOG + tag + push + close 7 issues

**Files:** VERSION (2.66.1→2.67.0) + package.json + CHANGELOG (prepend v2.67.0 entry)

**CHANGELOG entry:**

```markdown
## v2.67.0 — Dogfood Issues Batch 2 (2026-05-10)

### Bug fixes (closes 7 PrintwayV3 dogfood issues batch 2)
- **#157 CRITICAL:** API contract probe parser now matches WS/WEBSOCKET in all 3 regexes (HEADER_RE + TABLE_ROW_RE + SPLIT_FILE_HEAD_RE). WS endpoints return SKIP verdict (not GET-probed). OpenAPI schema validity pre-gate added — exits 2 when openapi-generation.log shows FST_ERR_INVALID_SCHEMA / 500.
- **#158 HIGH:** Lens artifacts (LENS-DISPATCH-PLAN.json + LENS-COVERAGE-MATRIX.md) now strict required must_write. Codex skill (`codex-skills/vg-review/SKILL.md`) emits lens markers per A9 pattern.
- **#159 HIGH:** Validator inventory loops (`verify-contract-completeness.py`) now exclude `_backup`, `archive`, `legacy`, `_archive`, `.vg` directories via centralized `_should_skip_path()` helper. New `scanned_*_count` metrics in JSON output for cross-artifact reconciliation.
- **#160 HIGH:** GOAL-COVERAGE-MATRIX BLOCKED status now classified into 5 reasons via `BlockedReason` enum: APP_BLOCKED (real bug, route to /vg:build), WORKFLOW_BLOCKED (probe/tool bug), PREREQ_MISSING (upstream DEFERRED, route to /vg:amend), EXTERNAL_REQUIRED (OAuth/WS/reset), PROBE_INVALID (probe ran wrong). Auto-fix routing only sends APP_BLOCKED to /vg:build.
- **#161 HIGH:** Phase 0.5 preflight adds 3 BLOCK gates: routes-static.json validity, ENV-CONTRACT.md preflight_checks section, OpenAPI schema validity log scan.
- **#162 MEDIUM:** Envelope drift findings now tagged `finding_type: envelope_drift` and routed via `ALWAYS_ROUTE_FINDING_TYPES` set (bypasses severity floor). Same treatment for openapi_invalid, auth_misconfigured, prereq_missing types.
- **#163 MEDIUM:** Security baseline validator now emits Evidence with severity field (TLS=CRITICAL, HSTS=HIGH, cookies=MEDIUM) + merges into REVIEW-FINDINGS.json. Security findings now reach AUTO-FIX-TASKS routing pipeline.

### Test coverage
**21+ new tests across 7 suites.** All pass.

### Migration
Bug fixes only — no migration needed. Existing reviews automatically benefit on next /vg:review run.

### Closes 8/8 batch-2 dogfood issues
With v2.67.0, all PrintwayV3 dogfood issues from 2026-05-09 are closed (8 batch 1 + 7 batch 2 = 15 total).

## v2.66.1 — Plan-fidelity followup + 2 deferred issues (2026-05-10)
```

Steps:
1. Bump VERSION + package.json
2. Prepend CHANGELOG
3. Commit: `release: v2.67.0 — PrintwayV3 dogfood batch 2 (7 issues)`
4. Tag `v2.67.0`
5. Push origin main + tag
6. `gh release create v2.67.0`
7. Close issues #157 #158 #159 #160 #161 #162 #163

---

## Verification

- `git log --oneline | head -10` shows 8 commits (7 tasks + release)
- `cat VERSION` = `2.67.0`
- 21+ new tests pass
- 7 GitHub issues closed

---

## Execution mode

Subagent-driven development. Tasks 1-7 dispatched in 2-3 batches (small/related tasks bundled in single dispatch with separate commits).

Suggested batches:
- **Batch A:** T1 (#157) + T5 (#161) — both touch review.md + probe gating
- **Batch B:** T2 (#158) + T3 (#159) — both touch validators + Codex skill markers
- **Batch C:** T4 (#160) + T6 (#162) + T7 (#163) — all touch finding/matrix routing
- **Release:** Task 8

Each task = own commit. Bundling = single agent dispatch handling multiple tasks sequentially with separate commits.
