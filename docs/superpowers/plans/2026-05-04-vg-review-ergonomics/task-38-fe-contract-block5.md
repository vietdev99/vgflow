<!-- Per-task plan file. Self-contained — execute as instructed. -->
<!-- Index: ../2026-05-04-vg-review-ergonomics.md -->
<!-- Spec: docs/superpowers/specs/2026-05-04-vg-review-ergonomics-design.md (Bug F lines 291-365) -->

## Task 38: BLOCK 5 FE Contract + 2-pass blueprint (Pass 2 subagent + validator + `--only=<step>` flag)

**Files:**
- Create: `agents/vg-blueprint-fe-contracts/SKILL.md`
- Create: `commands/vg/_shared/blueprint/fe-contracts-overview.md`
- Create: `commands/vg/_shared/blueprint/fe-contracts-delegation.md`
- Create: `scripts/validators/verify-fe-contract-block5.py`
- Modify: `commands/vg/blueprint.md` (add step `2b6d_fe_contracts` between existing `2b5e_a_lens_walk` and `2b7_flow_detect`; add `--only=<step>` arg parsing; add 2 telemetry events)
- Modify: `commands/vg/_shared/blueprint/contracts-overview.md` (cite BLOCK 5 fields appendix once Pass 2 wires them)
- Modify: `commands/vg/_shared/blueprint/close.md` (run `verify-fe-contract-block5.py` before close)
- Test: `tests/test_blueprint_fe_contracts_pass.py`
- Test: `tests/test_blueprint_only_step.py`
- Test: `tests/test_verify_fe_contract_block5.py`

**Why:** PV3 dogfood revealed `API-CONTRACTS.md` is BE-only (4 blocks per endpoint: auth/middleware, Zod schemas, error responses, test sample). FE codegen has nothing to read for canonical URL, UI states, query params, cache invalidation, optimistic semantics, toast text. Result: wrong URLs even though code generated, missing UI loading/error states, scattered toast messages.

Solution = **2-pass blueprint** + **BLOCK 5** appended per endpoint:
- **Pass 1** (existing `vg-blueprint-contracts`) — BE 4 blocks, unchanged.
- **Pass 2** (NEW `vg-blueprint-fe-contracts`) — runs AFTER `2b5e_a_lens_walk` (so UI-MAP + VIEW-COMPONENTS exist). Reads BE 4 blocks + UI-MAP + VIEW-COMPONENTS. Emits BLOCK 5 (16 fields) per endpoint. Orchestrator appends to `${PHASE_DIR}/API-CONTRACTS/<slug>.md`.

Codex round-2 Amendment D added `/vg:blueprint <phase> --only=fe-contracts` as part of this task — re-runs Pass 2 only, for retroactive BLOCK 5 backfill (PV3 phase 4.1). Validator BLOCKs missing BLOCK 5; legacy phases use `--allow-block5-missing` with override-debt.

**Cross-task contract recap (locked):** BLOCK 5 has exactly 16 fields per spec lines 312-326. Per-method matrix: `pagination_contract` required only for `GET` list endpoints; `form_submission_idempotency_key` required only for `POST/PUT/PATCH`. Validator regex MUST match per-endpoint file format described below. Pass 2 telemetry events: `blueprint.fe_contracts_pass_completed` (info) + `blueprint.fe_contract_block5_blocked` (warn).

---

- [ ] **Step 1: Write the failing validator test (Step 1 of 4 — verify-fe-contract-block5.py)**

Create `tests/test_verify_fe_contract_block5.py`:

```python
"""Task 38 — verify BLOCK 5 FE contract validator.

Pin: validator BLOCKs when BLOCK 5 missing on any endpoint, validates
all 16 fields, enforces per-method matrix (GET-list ⇒ pagination_contract;
POST/PUT/PATCH ⇒ form_submission_idempotency_key).

`--allow-block5-missing` escapes BLOCK with override-debt entry.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
VALIDATOR = REPO / "scripts/validators/verify-fe-contract-block5.py"

# Minimal BE 4-block stub (BLOCK 1..4); BLOCK 5 absent.
ENDPOINT_BE_ONLY = """\
# POST /api/sites

## BLOCK 1: Auth + middleware
- requires: publisher
## BLOCK 2: Zod schemas
- request: SiteCreateInput
## BLOCK 3: Error responses
- 401, 403, 422
## BLOCK 4: Test sample
- POST /api/sites with cred=publisher
"""

ENDPOINT_WITH_BLOCK5 = ENDPOINT_BE_ONLY + """\

## BLOCK 5: FE consumer contract

```typescript
export const PostSitesFEContract = {
  url: '/api/sites',
  consumers: ['apps/web/src/sites/**/*.tsx'],
  ui_states: { loading: 'spinner', error: 'inline-banner', empty: 'cta-create-first', success: 'toast-then-redirect' },
  query_param_schema: {},
  invalidates: ['GetSites'],
  optimistic: false,
  toast_text: { success: 'Site created', error_403: 'Need publisher role' },
  navigation_post_action: 'navigate:/sites/{id}',
  auth_role_visibility: ['publisher'],
  error_to_action_map: { 401: 'navigate:/login', 403: 'modal:contact-admin' },
  pagination_contract: null,
  debounce_ms: null,
  prefetch_triggers: [],
  websocket_correlate: null,
  request_id_propagation: false,
  form_submission_idempotency_key: 'header:Idempotency-Key',
} as const;
```
"""


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["python3", str(VALIDATOR), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def test_block5_missing_blocks_validator(tmp_path: Path) -> None:
    contracts_dir = tmp_path / "API-CONTRACTS"
    contracts_dir.mkdir()
    (contracts_dir / "post-api-sites.md").write_text(ENDPOINT_BE_ONLY, encoding="utf-8")

    result = _run(["--contracts-dir", str(contracts_dir)], REPO)
    assert result.returncode != 0, "expected BLOCK on missing BLOCK 5"
    assert "BLOCK 5" in result.stdout + result.stderr


def test_block5_present_passes(tmp_path: Path) -> None:
    contracts_dir = tmp_path / "API-CONTRACTS"
    contracts_dir.mkdir()
    (contracts_dir / "post-api-sites.md").write_text(ENDPOINT_WITH_BLOCK5, encoding="utf-8")

    result = _run(["--contracts-dir", str(contracts_dir)], REPO)
    assert result.returncode == 0, f"expected pass, got: {result.stdout}\n{result.stderr}"


def test_get_list_requires_pagination_contract(tmp_path: Path) -> None:
    contracts_dir = tmp_path / "API-CONTRACTS"
    contracts_dir.mkdir()
    bad = ENDPOINT_WITH_BLOCK5.replace("# POST /api/sites", "# GET /api/sites").replace(
        "pagination_contract: null", "pagination_contract: null  // INVALID: GET list requires non-null"
    )
    # Force the per-method matrix breach: GET on a list path with pagination_contract: null
    bad = bad.replace("pagination_contract: null", "pagination_contract_omitted: true")
    (contracts_dir / "get-api-sites.md").write_text(bad, encoding="utf-8")

    result = _run(["--contracts-dir", str(contracts_dir)], REPO)
    assert result.returncode != 0
    assert "pagination_contract" in result.stdout + result.stderr


def test_post_requires_idempotency_key(tmp_path: Path) -> None:
    contracts_dir = tmp_path / "API-CONTRACTS"
    contracts_dir.mkdir()
    bad = ENDPOINT_WITH_BLOCK5.replace(
        "form_submission_idempotency_key: 'header:Idempotency-Key'",
        "form_submission_idempotency_key_omitted: true",
    )
    (contracts_dir / "post-api-sites.md").write_text(bad, encoding="utf-8")

    result = _run(["--contracts-dir", str(contracts_dir)], REPO)
    assert result.returncode != 0
    assert "form_submission_idempotency_key" in result.stdout + result.stderr


def test_allow_block5_missing_with_override_debt(tmp_path: Path) -> None:
    """`--allow-block5-missing --override-reason=...` escapes BLOCK with override-debt."""
    contracts_dir = tmp_path / "API-CONTRACTS"
    contracts_dir.mkdir()
    (contracts_dir / "post-api-sites.md").write_text(ENDPOINT_BE_ONLY, encoding="utf-8")
    debt_path = tmp_path / "override-debt.json"

    result = _run(
        [
            "--contracts-dir", str(contracts_dir),
            "--allow-block5-missing",
            "--override-reason", "PV3 phase 4.1 legacy backfill — see Task 38 retroactivity",
            "--override-debt-path", str(debt_path),
        ],
        REPO,
    )
    assert result.returncode == 0, f"expected pass under override, got: {result.stderr}"
    assert debt_path.exists(), "override-debt entry must be written"
    debt = json.loads(debt_path.read_text(encoding="utf-8"))
    assert debt["reason"]
    assert debt["scope"] == "fe-contract-block5-missing"
```

- [ ] **Step 2: Run failing test**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -m pytest tests/test_verify_fe_contract_block5.py -v
```

Expected: 5 FAILED with `FileNotFoundError: scripts/validators/verify-fe-contract-block5.py`.

- [ ] **Step 3: Implement `verify-fe-contract-block5.py`**

Create `scripts/validators/verify-fe-contract-block5.py`:

```python
#!/usr/bin/env python3
"""Task 38 — verify BLOCK 5 FE consumer contract is present + complete.

Scans `${PHASE_DIR}/API-CONTRACTS/<slug>.md` files. Each file must contain
exactly one ```typescript fenced block under a `## BLOCK 5: FE consumer
contract` heading. The block must declare 16 keys (see REQUIRED_FIELDS).

Per-method matrix:
- GET on a list path (no `:id` / `{id}`) ⇒ pagination_contract MUST be a
  non-null object with `type` field.
- POST/PUT/PATCH ⇒ form_submission_idempotency_key MUST be a non-null
  string starting with 'header:' or 'body:'.

Exit codes:
- 0 = OK or override accepted
- 1 = BLOCK (missing/incomplete BLOCK 5)
- 2 = wrong invocation
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REQUIRED_FIELDS = (
    "url",
    "consumers",
    "ui_states",
    "query_param_schema",
    "invalidates",
    "optimistic",
    "toast_text",
    "navigation_post_action",
    "auth_role_visibility",
    "error_to_action_map",
    "pagination_contract",
    "debounce_ms",
    "prefetch_triggers",
    "websocket_correlate",
    "request_id_propagation",
    "form_submission_idempotency_key",
)

# Heading + fenced typescript block.
BLOCK5_RE = re.compile(
    r"##\s+BLOCK\s+5:\s+FE consumer contract\s*\n+```(?:typescript|ts)\n(?P<body>.+?)\n```",
    re.DOTALL,
)
# Endpoint method/path from filename (`post-api-sites.md`) or top heading.
HEADING_RE = re.compile(r"^#\s+(GET|POST|PUT|PATCH|DELETE)\s+(\S+)", re.MULTILINE)


def _parse_method_path(text: str, filename: str) -> tuple[str | None, str | None]:
    m = HEADING_RE.search(text)
    if m:
        return m.group(1).upper(), m.group(2)
    # Fallback: derive from filename (post-api-sites → POST /api/sites)
    parts = filename.removesuffix(".md").split("-")
    if not parts:
        return None, None
    method = parts[0].upper()
    path = "/" + "/".join(parts[1:]).replace("--", "/")
    return method, path


def _is_list_path(path: str) -> bool:
    return "{" not in path and ":id" not in path


def _block5_findings(contract_path: Path) -> list[str]:
    text = contract_path.read_text(encoding="utf-8")
    method, path = _parse_method_path(text, contract_path.name)
    findings: list[str] = []

    m = BLOCK5_RE.search(text)
    if not m:
        findings.append(f"{contract_path.name}: BLOCK 5 missing")
        return findings

    body = m.group("body")
    for field in REQUIRED_FIELDS:
        # Field must appear as `field:` token at start of identifier boundary.
        if not re.search(rf"\b{re.escape(field)}\s*:", body):
            findings.append(f"{contract_path.name}: BLOCK 5 missing field '{field}'")

    # Per-method matrix
    if method == "GET" and path and _is_list_path(path):
        if re.search(r"\bpagination_contract\s*:\s*null\b", body):
            findings.append(
                f"{contract_path.name}: GET list endpoint requires non-null pagination_contract"
            )
        if not re.search(r"\bpagination_contract\s*:", body):
            findings.append(
                f"{contract_path.name}: GET list endpoint missing pagination_contract field"
            )
    if method in {"POST", "PUT", "PATCH"}:
        if re.search(r"\bform_submission_idempotency_key\s*:\s*null\b", body):
            findings.append(
                f"{contract_path.name}: {method} endpoint requires non-null form_submission_idempotency_key"
            )
        if not re.search(r"\bform_submission_idempotency_key\s*:", body):
            findings.append(
                f"{contract_path.name}: {method} endpoint missing form_submission_idempotency_key field"
            )
    return findings


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--contracts-dir", required=True, help="Path to API-CONTRACTS/ split dir")
    p.add_argument("--allow-block5-missing", action="store_true")
    p.add_argument("--override-reason", default="")
    p.add_argument("--override-debt-path", default="")
    args = p.parse_args()

    contracts_dir = Path(args.contracts_dir)
    if not contracts_dir.is_dir():
        print(f"ERROR: --contracts-dir not a directory: {contracts_dir}", file=sys.stderr)
        return 2

    all_findings: list[str] = []
    for contract_file in sorted(contracts_dir.glob("*.md")):
        if contract_file.name == "index.md":
            continue
        all_findings.extend(_block5_findings(contract_file))

    if not all_findings:
        return 0

    if args.allow_block5_missing:
        if not args.override_reason:
            print("ERROR: --allow-block5-missing requires --override-reason", file=sys.stderr)
            return 2
        debt = {
            "scope": "fe-contract-block5-missing",
            "reason": args.override_reason,
            "findings": all_findings,
        }
        if args.override_debt_path:
            Path(args.override_debt_path).write_text(json.dumps(debt, indent=2), encoding="utf-8")
        print(f"OVERRIDE accepted ({len(all_findings)} findings logged to override-debt)")
        return 0

    print("BLOCK: BLOCK 5 FE consumer contract findings:")
    for f in all_findings:
        print(f"  - {f}")
    print("Fix: run `/vg:blueprint <phase> --only=fe-contracts` to regenerate Pass 2.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
```

```bash
chmod +x scripts/validators/verify-fe-contract-block5.py
```

- [ ] **Step 4: Run validator tests — verify GREEN**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -m pytest tests/test_verify_fe_contract_block5.py -v
```

Expected: 5 PASSED.

- [ ] **Step 5: Write failing test for `--only=<step>` flag**

Create `tests/test_blueprint_only_step.py`:

```python
"""Task 38 — verify `/vg:blueprint <phase> --only=<step>` flag parses + skips
non-named steps. Codex round-2 Amendment D scope.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
BP_MD = REPO / "commands/vg/blueprint.md"

VALID_STEP_NAMES = {"fe-contracts", "rcrurdr-invariants", "workflows", "lens-walk", "edge-cases"}


def test_blueprint_argument_hint_declares_only_flag() -> None:
    text = BP_MD.read_text(encoding="utf-8")
    # Frontmatter argument-hint must mention --only=<step>
    m = re.search(r"^argument-hint:\s*(.+)$", text, re.MULTILINE)
    assert m, "blueprint.md frontmatter missing argument-hint"
    hint = m.group(1)
    assert "--only=" in hint, f"argument-hint must declare --only=<step>: {hint}"


def test_blueprint_md_documents_only_step_dispatch() -> None:
    """The slim entry must contain a parse-and-dispatch block for --only."""
    text = BP_MD.read_text(encoding="utf-8")
    assert "--only=" in text
    # All valid step names must be enumerated in the slim entry's only-step list
    only_block_match = re.search(r"<only-step-list>(.+?)</only-step-list>", text, re.DOTALL)
    assert only_block_match, "blueprint.md must wrap valid step list in <only-step-list>...</only-step-list>"
    enumerated = only_block_match.group(1)
    for name in VALID_STEP_NAMES:
        assert name in enumerated, f"missing valid step name '{name}' in <only-step-list>"


def test_blueprint_md_rejects_unknown_only_step_name() -> None:
    """The slim entry must instruct rejection for unknown --only=<name> with explicit error."""
    text = BP_MD.read_text(encoding="utf-8")
    # Must contain a sentence describing rejection of unknown values
    pattern = r"--only.+(?:unknown|invalid|not in).{0,80}error"
    assert re.search(pattern, text, re.IGNORECASE | re.DOTALL), \
        "blueprint.md must specify error behavior for unknown --only=<step> value"
```

- [ ] **Step 6: Run failing test**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -m pytest tests/test_blueprint_only_step.py -v
```

Expected: 3 FAILED.

- [ ] **Step 7: Patch `commands/vg/blueprint.md` — declare `--only=<step>` + add `2b6d_fe_contracts` step + telemetry**

Modify `commands/vg/blueprint.md`:

1. **Frontmatter `argument-hint`** — add `[--only=<step>]`. Locate line near top, e.g.:

```
argument-hint: <phase-id> [--profile=<name>] [--skip-edge-cases] [--skip-lens-walk] [--only=<step>]
```

2. **Add new required step `2b6d_fe_contracts`** in the steps block, between `2b5e_a_lens_walk` and `2b7_flow_detect`. Insert after the `2b5e_edge_cases` block (around line 94):

```yaml
    # Task 38 (Bug F) — Pass 2 FE consumer contracts. Runs after lens-walk +
    # edge-cases so UI-MAP + VIEW-COMPONENTS exist. Profile-gated (web only).
    - name: "2b6d_fe_contracts"
      profile: "web-fullstack,web-frontend-only"
      severity: "warn"
      required_unless_flag: "--skip-fe-contracts"
```

3. **Add 2 telemetry events** under `must_emit_telemetry`:

```yaml
    # Task 38 — Pass 2 lifecycle (mutually exclusive with skipped event)
    - event_type: "blueprint.fe_contracts_pass_completed"
      phase: "${PHASE_NUMBER}"
      severity: "info"
    - event_type: "blueprint.fe_contract_block5_blocked"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
```

4. **Add `--skip-fe-contracts` to `forbidden_without_override` list** alongside the existing `--skip-edge-cases` / `--skip-lens-walk` entries.

5. **Add `--only=<step>` argument-parsing block to slim entry** (after STEP 1's existing arg-parse block). Insert this Markdown section before STEP 2:

```markdown
### `--only=<step>` (selective re-run, Codex round-2 Amendment D)

When `--only=<step>` is passed, run ONLY that named step + its required
prerequisites (preflight, parse_args, create_task_tracker, complete). Skip
all other steps. Used for retroactive backfill after a new step is added.

<only-step-list>
Valid step names:
- `fe-contracts` — re-run Pass 2 (Task 38). Prereqs: 2b_contracts, 2b5e_a_lens_walk, 2b6c_view_decomposition.
- `rcrurdr-invariants` — re-run Task 39 RCRURDR generator.
- `workflows` — re-run Task 40 Pass 3 workflow specs.
- `lens-walk` — re-run 2b5e_a_lens_walk in isolation.
- `edge-cases` — re-run 2b5e_edge_cases in isolation.
</only-step-list>

If `<step>` is unknown / invalid / not in the valid list, emit `error`
event `blueprint.only_step_unknown` and exit 1 with message:
`ERROR: unknown step '<step>' for --only=. Valid: fe-contracts, rcrurdr-invariants, workflows, lens-walk, edge-cases`.
```

- [ ] **Step 8: Run `--only` test — verify GREEN**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -m pytest tests/test_blueprint_only_step.py -v
```

Expected: 3 PASSED.

- [ ] **Step 9: Write failing test for Pass 2 subagent contract**

Create `tests/test_blueprint_fe_contracts_pass.py`:

```python
"""Task 38 — verify Pass 2 vg-blueprint-fe-contracts subagent contract.

Pin: agent SKILL.md must declare 16-field BLOCK 5 schema. Delegation
prompt must include UI-MAP + VIEW-COMPONENTS + BE 4-block citations as
input refs. Output must be JSON listing per-endpoint BLOCK 5 bodies.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILL_MD = REPO / "agents/vg-blueprint-fe-contracts/SKILL.md"
DELEGATION_MD = REPO / "commands/vg/_shared/blueprint/fe-contracts-delegation.md"
OVERVIEW_MD = REPO / "commands/vg/_shared/blueprint/fe-contracts-overview.md"

REQUIRED_FIELDS = (
    "url", "consumers", "ui_states", "query_param_schema", "invalidates",
    "optimistic", "toast_text", "navigation_post_action", "auth_role_visibility",
    "error_to_action_map", "pagination_contract", "debounce_ms",
    "prefetch_triggers", "websocket_correlate", "request_id_propagation",
    "form_submission_idempotency_key",
)


def test_skill_md_exists_with_proper_frontmatter() -> None:
    assert SKILL_MD.exists(), f"missing: {SKILL_MD}"
    text = SKILL_MD.read_text(encoding="utf-8")
    assert text.startswith("---\n"), "SKILL.md must start with frontmatter"
    assert re.search(r"^name:\s*vg-blueprint-fe-contracts$", text, re.MULTILINE)
    assert re.search(r"^description:\s*.+", text, re.MULTILINE)


def test_skill_md_declares_all_16_block5_fields() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    for field in REQUIRED_FIELDS:
        assert field in text, f"SKILL.md missing field doc: {field}"


def test_delegation_md_cites_inputs() -> None:
    assert DELEGATION_MD.exists(), f"missing: {DELEGATION_MD}"
    text = DELEGATION_MD.read_text(encoding="utf-8")
    # Must reference all 3 input artifacts
    for ref in ("UI-MAP", "VIEW-COMPONENTS", "API-CONTRACTS"):
        assert ref in text, f"delegation prompt must cite {ref}"


def test_delegation_md_declares_output_json_shape() -> None:
    text = DELEGATION_MD.read_text(encoding="utf-8")
    # Must declare a JSON return shape with `endpoints` array containing slug+body
    assert "endpoints" in text and "slug" in text and "block5_body" in text, \
        "delegation must declare return JSON shape: { endpoints: [{ slug, block5_body }] }"


def test_overview_md_documents_pass_2_position() -> None:
    assert OVERVIEW_MD.exists(), f"missing: {OVERVIEW_MD}"
    text = OVERVIEW_MD.read_text(encoding="utf-8")
    assert "Pass 2" in text
    assert "2b5e_a_lens_walk" in text and "2b7_flow_detect" in text, \
        "overview must position Pass 2 between lens-walk and flow_detect"
```

- [ ] **Step 10: Run failing test**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -m pytest tests/test_blueprint_fe_contracts_pass.py -v
```

Expected: 5 FAILED.

- [ ] **Step 11: Create Pass 2 agent files**

Create `agents/vg-blueprint-fe-contracts/SKILL.md`:

```markdown
---
name: vg-blueprint-fe-contracts
description: Generate BLOCK 5 FE consumer contracts for each API endpoint (Task 38 Pass 2). Reads BE 4 blocks + UI-MAP + VIEW-COMPONENTS, emits 16-field FE contract per endpoint.
tools: Read, Bash, Grep
---

# vg-blueprint-fe-contracts (Pass 2)

You generate **BLOCK 5: FE consumer contract** for each endpoint declared
in `${PHASE_DIR}/API-CONTRACTS/<slug>.md`. Pass 1 (vg-blueprint-contracts)
already wrote BLOCKs 1–4 (BE: auth/middleware, Zod schemas, error responses,
test sample). You append BLOCK 5.

## Input artifacts

You will receive a delegation prompt with explicit `@${PATH}` references:
- `${PHASE_DIR}/API-CONTRACTS.md` (or `${PHASE_DIR}/API-CONTRACTS/index.md` + per-endpoint files)
- `${PHASE_DIR}/UI-MAP.md`
- `${PHASE_DIR}/VIEW-COMPONENTS.md`
- `${PHASE_DIR}/PLAN.md` (for context_refs / consumer hints)

## Output (return as JSON to orchestrator)

```json
{
  "endpoints": [
    {
      "slug": "post-api-sites",
      "block5_body": "export const PostSitesFEContract = { ...16 fields... } as const;"
    }
  ]
}
```

The orchestrator appends each `block5_body` to the matching
`API-CONTRACTS/<slug>.md` file under heading `## BLOCK 5: FE consumer contract`.

## BLOCK 5 schema (16 fields, ALL required)

| Field | Type | Required | Notes |
|---|---|---|---|
| `url` | string | always | Canonical, FE typed client imports verbatim |
| `consumers` | string[] | always | Glob patterns preferred (`apps/web/src/sites/**/*.tsx`); literal component names ok |
| `ui_states` | object | always | Keys: `loading`, `error`, `empty`, `success` (all 4) |
| `query_param_schema` | object | always | `{}` for endpoints with no query params |
| `invalidates` | string[] | always | Cache keys to invalidate post-mutation; `[]` for read-only endpoints |
| `optimistic` | boolean | always | FE update strategy |
| `toast_text` | object | always | `{ success, error_<status> }` keys |
| `navigation_post_action` | string \| null | always | Must be consistent with BE `Location` header |
| `auth_role_visibility` | string[] | always | Roles allowed to render UI; `[]` = public |
| `error_to_action_map` | object | always | HTTP status → FE action |
| `pagination_contract` | object \| null | matrix | Required NON-NULL for `GET` list endpoints (`{type: cursor\|offset, ...}`) |
| `debounce_ms` | number \| null | always | For search/filter only; null otherwise |
| `prefetch_triggers` | string[] | always | `[]` if none |
| `websocket_correlate` | string \| null | always | WS event topic that invalidates this query |
| `request_id_propagation` | boolean | always | FE must propagate response.request_id to follow-ups |
| `form_submission_idempotency_key` | string \| null | matrix | Required NON-NULL for `POST/PUT/PATCH` |

Per-method matrix (validator enforces):
- `GET <list>` (path has no `{id}` / `:id`) ⇒ `pagination_contract` non-null
- `POST/PUT/PATCH` ⇒ `form_submission_idempotency_key` non-null

## Field derivation guidance

- `url` ← `# <METHOD> <path>` heading of contract file (verbatim, no paraphrase)
- `consumers` ← grep VIEW-COMPONENTS.md + UI-MAP.md for component names referencing the endpoint slug; emit glob `apps/web/src/<resource>/**/*.tsx` if no specific components found
- `ui_states` ← read UI-MAP.md per-route entry; map `loading-skeleton` → `loading: 'spinner-with-skeleton'`, etc.
- `invalidates` ← BE 4-block analysis: which `GET` endpoints share resource path with this mutation
- `auth_role_visibility` ← BLOCK 1 `requires:` field
- `error_to_action_map` ← BLOCK 3 error responses; map 401→`navigate:/login`, 403→`modal:contact-admin`, 422→`form-error-banner`, 429→`show-retry-after`

## Anti-laziness rules

- DO NOT invent URLs — copy verbatim from BLOCK 1 heading
- DO NOT skip fields — all 16 are required (use `null` / `[]` / `false` where not applicable)
- DO NOT paraphrase BLOCK 1 `requires:` into `auth_role_visibility` (must match exactly)
- If UI-MAP.md lacks a route entry for an endpoint's consumer page, emit empty `consumers: []` + flag in return JSON `notes` field
```

Create `commands/vg/_shared/blueprint/fe-contracts-overview.md`:

```markdown
# Pass 2 — FE consumer contracts (Task 38, Bug F)

## Position in pipeline

```
2b_contracts (Pass 1, BE 4 blocks) → ... → 2b5e_a_lens_walk → 2b5e_edge_cases →
2b6c_view_decomposition → 2b6_ui_spec → 2b6b_ui_map → 2b6d_fe_contracts (Pass 2 — THIS) →
2b7_flow_detect → 2b8_rcrurdr_invariants → 2b9_workflows → 2c_verify
```

Pass 2 runs AFTER UI artifacts exist (UI-MAP, VIEW-COMPONENTS, lens-walk seeds) so
the subagent can derive `consumers` / `ui_states` / `error_to_action_map` from real
FE structure rather than guessing.

## Steps

1. Read `_shared/blueprint/fe-contracts-delegation.md` for the prompt template.
2. Spawn `Agent(subagent_type="vg-blueprint-fe-contracts", prompt=<delegation>)` —
   narrate spawn + return per UX baseline R2 (`scripts/vg-narrate-spawn.sh`).
3. Parse return JSON `endpoints[]`. For each entry: append `block5_body` to
   `${PHASE_DIR}/API-CONTRACTS/<slug>.md` under heading `## BLOCK 5: FE consumer contract`.
   If file already has a BLOCK 5 (re-run via `--only=fe-contracts`), REPLACE the
   existing block (regex match on `## BLOCK 5:`).
4. Run `python3 scripts/validators/verify-fe-contract-block5.py --contracts-dir ${PHASE_DIR}/API-CONTRACTS`.
5. On validator pass: emit `blueprint.fe_contracts_pass_completed` event.
6. On validator fail: emit `blueprint.fe_contract_block5_blocked` event with finding count;
   route through Task 33 wrapper if interactive (auto-fix subagent option).

## Backward compat

- Phases predating this step (e.g., PV3 4.1) lack BLOCK 5. Validator BLOCKs unless
  `--allow-block5-missing --override-reason="<text>"` is passed.
- Backfill via `/vg:blueprint <phase> --only=fe-contracts`.
```

Create `commands/vg/_shared/blueprint/fe-contracts-delegation.md`:

```markdown
# Pass 2 delegation prompt (Task 38)

Use this template when spawning `vg-blueprint-fe-contracts`. Substitute
`${PHASE_DIR}` with the phase directory path before spawn.

```
You are vg-blueprint-fe-contracts (Pass 2). Generate BLOCK 5 FE consumer
contract for each endpoint in API-CONTRACTS.

Read these inputs:
- @${PHASE_DIR}/API-CONTRACTS/index.md (TOC of endpoints)
- @${PHASE_DIR}/API-CONTRACTS/<each-slug>.md (BLOCKs 1-4 per endpoint)
- @${PHASE_DIR}/UI-MAP.md
- @${PHASE_DIR}/VIEW-COMPONENTS.md
- @${PHASE_DIR}/PLAN.md (for component-name hints)

For EACH endpoint, emit BLOCK 5 with all 16 required fields. See
agents/vg-blueprint-fe-contracts/SKILL.md for field schema + per-method matrix.

Return JSON to stdout (no other output):
{
  "endpoints": [
    { "slug": "post-api-sites", "block5_body": "export const ... as const;" },
    { "slug": "get-api-sites", "block5_body": "export const ... as const;" }
  ],
  "notes": [...]   // optional: flag missing UI-MAP entries, ambiguous role mappings, etc.
}

The orchestrator merges each block5_body into the matching contract file.
```

## Anti-drift checklist (validator-aligned)

Each `block5_body` MUST:
- Open with `export const <PascalEndpointName>FEContract = {`
- Close with `} as const;`
- Contain exactly 16 keys (validator regex matches each `<field>:` token)
- Set per-method matrix fields non-null per Task 38 spec
```

- [ ] **Step 12: Run Pass 2 contract test — verify GREEN**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -m pytest tests/test_blueprint_fe_contracts_pass.py -v
```

Expected: 5 PASSED.

- [ ] **Step 13: Wire validator into `close.md` (run before blueprint.completed event)**

Modify `commands/vg/_shared/blueprint/close.md`. Locate the existing validator-run sequence (search for `verify-blueprint-split-size.py` or similar). Add this validator call BEFORE the `blueprint.completed` emit:

```bash
python3 scripts/validators/verify-fe-contract-block5.py \
  --contracts-dir "${PHASE_DIR}/API-CONTRACTS" \
  ${ALLOW_BLOCK5_MISSING_FLAG}
rc=$?
if [ "$rc" -ne 0 ]; then
  vg-orchestrator emit-event blueprint.fe_contract_block5_blocked --phase "${PHASE_NUMBER}"
  echo "BLOCK: BLOCK 5 FE contract validator failed. Use --allow-block5-missing for legacy phases." >&2
  exit "$rc"
fi
```

`${ALLOW_BLOCK5_MISSING_FLAG}` is set by slim entry arg-parser when user passes `--allow-block5-missing`.

- [ ] **Step 14: Run all 3 task-38 test suites + sync + commit**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -m pytest tests/test_verify_fe_contract_block5.py tests/test_blueprint_only_step.py tests/test_blueprint_fe_contracts_pass.py -v
```

Expected: 13 PASSED.

```bash
DEV_ROOT=. bash sync.sh --no-global 2>&1 | tail -3
git add scripts/validators/verify-fe-contract-block5.py \
        agents/vg-blueprint-fe-contracts/ \
        commands/vg/_shared/blueprint/fe-contracts-overview.md \
        commands/vg/_shared/blueprint/fe-contracts-delegation.md \
        commands/vg/_shared/blueprint/contracts-overview.md \
        commands/vg/_shared/blueprint/close.md \
        commands/vg/blueprint.md \
        tests/test_verify_fe_contract_block5.py \
        tests/test_blueprint_only_step.py \
        tests/test_blueprint_fe_contracts_pass.py \
        .claude/ codex-skills/ .codex/
git commit -m "feat(blueprint): Pass 2 FE consumer contracts BLOCK 5 (Task 38, Bug F)

Adds vg-blueprint-fe-contracts subagent + 16-field BLOCK 5 schema +
verify-fe-contract-block5.py validator + --only=<step> flag.

Background: PV3 dogfood found API-CONTRACTS.md is BE-only; FE codegen
has no canonical contract for url, ui_states, query params, cache
invalidation, optimistic, toast text. Result = wrong URLs even after
codegen, missing UI states, scattered toasts.

Pipeline change: 2-pass blueprint
- Pass 1 (existing vg-blueprint-contracts): BE 4 blocks, unchanged
- Pass 2 (NEW vg-blueprint-fe-contracts): runs after UI-MAP +
  VIEW-COMPONENTS + lens-walk so FE structure exists. Emits BLOCK 5
  per endpoint with 16 fields + per-method matrix (GET-list ⇒
  pagination_contract; POST/PUT/PATCH ⇒ idempotency_key).

Validator BLOCKs missing/incomplete BLOCK 5; legacy phases escape via
--allow-block5-missing --override-reason=<text> with override-debt.
Retroactive backfill via /vg:blueprint <phase> --only=fe-contracts.

Codex round-2 Amendment D: --only=<step> implementation included in
this task's scope (not a separate task). Validates step name against
known list (fe-contracts, rcrurdr-invariants, workflows, lens-walk,
edge-cases); unknown = error exit 1.

Telemetry: blueprint.fe_contracts_pass_completed (info) +
blueprint.fe_contract_block5_blocked (warn).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```
