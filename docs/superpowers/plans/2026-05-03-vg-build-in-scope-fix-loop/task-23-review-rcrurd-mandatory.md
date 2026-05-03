<!-- Per-task plan file. Self-contained — execute as instructed. -->
<!-- Index: ../2026-05-03-vg-build-in-scope-fix-loop.md -->

## Task 23: Review mandatory RCRURD verification per mutation goal (runtime gate)

**Files:**
- Create: `scripts/validators/verify-rcrurd-runtime.py` (per-goal runtime check, reads invariant from Task 22 parser)
- Create: `tests/test_rcrurd_runtime.py`
- Modify: `commands/vg/review.md` (Phase 4 goal_comparison: mandatory verification per mutation goal)
- Modify: `commands/vg/review.md` frontmatter `must_emit_telemetry`

**Why (Codex GPT-5.5 review 2026-05-03):** VG's existing review pipeline has lens-plan gating + CRUD depth + mutation-submitted gating + RCRURD post-state checks — but `lens-business-coherence` is NOT required for every mutation goal, and `phase2d_crud_roundtrip_dispatch` only runs when `CRUD-SURFACES.md` declares `kit: crud-roundtrip`. The user's bug pattern (toast OK + DB unchanged) is R8 in lens-form-lifecycle: existing infrastructure detects it, but invocation isn't guaranteed per goal.

This task adds the RUNTIME gate: for every mutation goal in TEST-GOALS, review MUST execute the structured invariant from Task 22 against the deployed/staged build. Result emitted as machine-readable evidence. BLOCK review.completed if any goal lacks evidence OR fails the assertion.

**Codex GPT-5.5 ordering note:** A-min → B → C means Task 22 (schema) → Task 23 (runtime, this) → Task 24 (codegen). Runtime catches the real bug earliest after build; codegen consumes the same schema later.

**Architecture:**
1. Review Phase 4 reads `${PHASE_DIR}/TEST-GOALS/G-NN.md` per goal
2. For `goal_type: mutation`, extract structured invariant via Task 22 parser
3. Execute via `verify-rcrurd-runtime.py`:
   - Capture pre-state (precondition assert against `read.endpoint`)
   - Execute write (deployed app via curl/fetch, using configured auth)
   - Execute read with `cache_policy: no_store` headers (Cache-Control: no-store, Pragma: no-cache)
   - Apply settle policy (immediate = single read; poll = retry until timeout_ms)
   - Evaluate `assert[]` via JSONPath
   - Evaluate `side_effects[]` if present
4. Emit BuildWarningEvidence (severity=BLOCK on fail, ADVISORY on inconclusive)
5. Phase 4 BLOCKs review.completed when any mutation goal evidence missing OR severity=BLOCK

- [ ] **Step 1: Write the failing test**

Create `tests/test_rcrurd_runtime.py`:

```python
"""Tests for verify-rcrurd-runtime.py — review-side mandatory gate."""
from __future__ import annotations

import json
import subprocess
import textwrap
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import urlparse

import pytest

REPO = Path(__file__).resolve().parent.parent
GATE = REPO / "scripts" / "validators" / "verify-rcrurd-runtime.py"


class FakeAPIHandler(BaseHTTPRequestHandler):
    """Stateful in-memory API stub for runtime tests.

    Behaviors driven by class attributes set in tests:
      - PATCH /api/users/U → 200 (mode: PERSIST | LIE | ERROR_500)
      - GET /api/users/U  → reflects in-memory state
    """
    state = {"U": {"id": "U", "roles": []}}
    write_mode = "PERSIST"

    def log_message(self, format: str, *args) -> None:  # silence
        return

    def do_PATCH(self) -> None:
        path = urlparse(self.path).path
        if path.startswith("/api/users/"):
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            uid = path.rsplit("/", 1)[-1]
            if FakeAPIHandler.write_mode == "PERSIST":
                FakeAPIHandler.state.setdefault(uid, {"id": uid, "roles": []})
                FakeAPIHandler.state[uid]["roles"] = body.get("roles", [])
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": True}).encode("utf-8"))
            elif FakeAPIHandler.write_mode == "LIE":
                # Lying success: 200 + ok=true but state NOT mutated
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": True}).encode("utf-8"))
            else:
                self.send_response(500)
                self.end_headers()
        else:
            self.send_response(404); self.end_headers()

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path.startswith("/api/users/"):
            uid = path.rsplit("/", 1)[-1]
            entity = FakeAPIHandler.state.get(uid, {"id": uid, "roles": []})
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(json.dumps(entity).encode("utf-8"))
        else:
            self.send_response(404); self.end_headers()


@pytest.fixture
def fake_api():
    server = HTTPServer(("127.0.0.1", 0), FakeAPIHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    # Reset state per test
    FakeAPIHandler.state = {"U": {"id": "U", "roles": []}}
    FakeAPIHandler.write_mode = "PERSIST"
    yield base
    server.shutdown()


def _make_invariant(tmp_path: Path, base_url: str) -> Path:
    """Write a TEST-GOAL.md fixture with structured invariant."""
    goal = tmp_path / "G-04.md"
    goal.write_text(textwrap.dedent(f"""
        # G-04: Admin grants role

        **goal_type:** mutation

        **Persistence check:** After PATCH role, GET user must show new role.

        ## Read-after-write invariant

        ```yaml-rcrurd
        goal_type: mutation
        read_after_write_invariant:
          write:
            method: PATCH
            endpoint: {base_url}/api/users/U
          read:
            method: GET
            endpoint: {base_url}/api/users/U
            cache_policy: no_store
            settle: {{mode: immediate}}
          assert:
            - path: $.roles
              op: contains
              value_from: action.new_role
        ```
    """).strip(), encoding="utf-8")
    return goal


def test_runtime_passes_when_state_actually_persists(tmp_path: Path, fake_api: str) -> None:
    goal = _make_invariant(tmp_path, fake_api)
    out = tmp_path / "evidence.json"

    result = subprocess.run([
        "python3", str(GATE),
        "--goal-file", str(goal),
        "--phase", "test-1.0",
        "--action-payload", json.dumps({"new_role": "admin", "roles": ["admin"]}),
        "--evidence-out", str(out),
    ], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    ev = json.loads(out.read_text(encoding="utf-8"))
    assert ev["severity"] == "ADVISORY"  # PASS = informational, not BLOCK
    assert ev["category"] == "rcrurd_runtime"


def test_runtime_blocks_on_lying_success(tmp_path: Path, fake_api: str) -> None:
    """The user's bug: PATCH 200, but state NOT mutated. Must BLOCK."""
    FakeAPIHandler.write_mode = "LIE"
    goal = _make_invariant(tmp_path, fake_api)
    out = tmp_path / "evidence.json"

    result = subprocess.run([
        "python3", str(GATE),
        "--goal-file", str(goal),
        "--phase", "test-1.0",
        "--action-payload", json.dumps({"new_role": "admin", "roles": ["admin"]}),
        "--evidence-out", str(out),
    ], capture_output=True, text=True, check=False)
    assert result.returncode == 1
    ev = json.loads(out.read_text(encoding="utf-8"))
    assert ev["severity"] == "BLOCK"
    assert "R8" in ev["summary"] or "update_did_not_apply" in ev["summary"].lower() \
        or "did_not_apply" in ev["summary"].lower()


def test_non_mutation_goal_skipped(tmp_path: Path, fake_api: str) -> None:
    """Read-only goal has no invariant — gate must SKIP, not fail."""
    goal = tmp_path / "G-99.md"
    goal.write_text(textwrap.dedent("""
        # G-99: Health check

        **goal_type:** read_only

        ## (no invariant block — not a mutation)
    """).strip(), encoding="utf-8")
    result = subprocess.run([
        "python3", str(GATE),
        "--goal-file", str(goal),
        "--phase", "test-1.0",
    ], capture_output=True, text=True, check=False)
    assert result.returncode == 0
    assert "skipped" in result.stdout.lower() or "non-mutation" in result.stdout.lower()
```

- [ ] **Step 2: Run failing tests**

Run: `cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix" && python3 -m pytest tests/test_rcrurd_runtime.py -v`
Expected: 3 failures (gate doesn't exist).

- [ ] **Step 3: Write the runtime gate**

Create `scripts/validators/verify-rcrurd-runtime.py`:

```python
#!/usr/bin/env python3
"""verify-rcrurd-runtime.py — Task 23 runtime gate.

Per Codex GPT-5.5 review (2026-05-03): consume structured invariant from
Task 22 parser, execute write+read against deployed app, apply assertions.
Emit BuildWarningEvidence with severity=BLOCK on R8/R7/R5 violation.

NOT a generic curl wrapper — it understands the schema, applies cache_policy
+ settle semantics, and produces machine-readable evidence routable by the
classifier (Task 7).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "lib"))
from rcrurd_invariant import extract_from_test_goal_md, RCRURDInvariant, Assertion  # type: ignore  # noqa: E402


def _eval_jsonpath(body: object, path: str) -> list[object]:
    """Tiny JSONPath subset — supports $.a, $.a.b, $.a[*], $.a[*].b. Sufficient
    for invariant assertions; full jsonpath-ng dependency avoided to keep
    the gate dependency-light."""
    if path == "$":
        return [body]
    cur: list[object] = [body]
    parts = path[2:].split(".") if path.startswith("$.") else [path[1:]]
    for part in parts:
        m = re.match(r"^([^\[]+)(\[\*\])?$", part)
        if not m:
            return []
        key, star = m.group(1), m.group(2)
        nxt: list[object] = []
        for c in cur:
            if isinstance(c, dict) and key in c:
                v = c[key]
                if star and isinstance(v, list):
                    nxt.extend(v)
                else:
                    nxt.append(v)
        cur = nxt
    return cur


def _resolve_value(value_from: str, payload: dict) -> object:
    """Resolve `value_from` directive. Format:
       action.<key> — read from CLI --action-payload JSON
       literal:<text> — return the literal text
       derived_from_<key> — caller-side derivation (returns sentinel for now)"""
    if value_from.startswith("literal:"):
        return value_from.split(":", 1)[1]
    if value_from.startswith("action."):
        key = value_from.split(".", 1)[1]
        return payload.get(key)
    if value_from.startswith("derived_from_"):
        return f"<derived:{value_from}>"
    return value_from


def _apply_op(observed: list[object], op: str, expected: object) -> tuple[bool, str]:
    if op == "contains":
        flat = [item for sub in observed for item in (sub if isinstance(sub, list) else [sub])]
        ok = expected in flat
        return ok, f"observed={flat[:5]}, expected_contains={expected!r}"
    if op == "not_contains":
        flat = [item for sub in observed for item in (sub if isinstance(sub, list) else [sub])]
        ok = expected not in flat
        return ok, f"observed={flat[:5]}, expected_not_contains={expected!r}"
    if op == "equals":
        ok = (len(observed) == 1 and observed[0] == expected)
        return ok, f"observed={observed[:1]}, expected_equals={expected!r}"
    if op == "matches":
        ok = (len(observed) == 1 and isinstance(observed[0], str)
              and re.match(str(expected), observed[0]) is not None)
        return ok, f"observed={observed[:1]}, expected_matches={expected!r}"
    return False, f"unknown op {op!r}"


def _http_request(method: str, url: str, body: dict | None, headers: dict[str, str]) -> tuple[int, dict]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    if data is not None:
        headers = {**headers, "Content-Type": "application/json"}
    req = urllib.request.Request(url, method=method, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8")
            try:
                return resp.getcode(), json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                return resp.getcode(), {"_raw": raw}
    except urllib.error.HTTPError as e:
        try:
            err_body = json.loads(e.read().decode("utf-8"))
        except Exception:
            err_body = {}
        return e.code, err_body


def _cache_headers(cache_policy: str) -> dict[str, str]:
    if cache_policy == "no_store":
        return {"Cache-Control": "no-store, no-cache", "Pragma": "no-cache"}
    if cache_policy == "bypass_cdn":
        return {"Cache-Control": "no-store", "X-Bypass-CDN": "1"}
    return {}  # cache_ok


def _eval_assertions(read_body: dict, assertions: tuple[Assertion, ...],
                     payload: dict) -> list[dict]:
    results = []
    for a in assertions:
        observed = _eval_jsonpath(read_body, a.path)
        expected = _resolve_value(a.value_from, payload)
        ok, detail = _apply_op(observed, a.op, expected)
        results.append({
            "path": a.path, "op": a.op, "value_from": a.value_from,
            "passed": ok, "detail": detail,
            **({"layer": a.layer} if a.layer else {}),
        })
    return results


def _settle_loop(read_url: str, headers: dict[str, str], settle, timeout_default: int = 5000):
    """Honor settle.mode. Returns (status, body, attempts)."""
    if settle.mode == "immediate":
        status, body = _http_request("GET", read_url, None, headers)
        return status, body, 1
    timeout_ms = settle.timeout_ms or timeout_default
    interval_ms = settle.interval_ms or 500
    deadline = time.monotonic() + (timeout_ms / 1000.0)
    attempts = 0
    last = (0, {})
    while time.monotonic() < deadline:
        attempts += 1
        last = _http_request("GET", read_url, None, headers)
        # Caller decides PASS/FAIL — settle just retries until deadline, returns last.
        # (Optional: short-circuit if all assertions PASS — TODO if needed.)
        time.sleep(interval_ms / 1000.0)
    return last[0], last[1], attempts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--goal-file", required=True)
    parser.add_argument("--phase", required=True)
    parser.add_argument("--action-payload", default="{}",
                        help='JSON dict resolving action.<key> placeholders + write body')
    parser.add_argument("--auth-header", default="",
                        help='e.g. "Authorization: Bearer <token>" — passed to both write+read')
    parser.add_argument("--evidence-out")
    args = parser.parse_args()

    goal_path = Path(args.goal_file)
    if not goal_path.exists():
        print(f"ERROR: goal-file not found: {goal_path}", file=sys.stderr)
        return 2
    text = goal_path.read_text(encoding="utf-8")

    # Skip non-mutation goals (Task 22 invariant only required for mutation)
    if "**goal_type:** mutation" not in text and "goal_type: mutation" not in text:
        print(f"✓ {goal_path.name} is non-mutation — skipped (no invariant required)")
        return 0

    inv = extract_from_test_goal_md(text)
    if inv is None:
        # Mutation goal but no structured invariant — Rule 3b should have blocked
        # at blueprint time, but we BLOCK here too for defense-in-depth.
        print(f"⛔ {goal_path.name}: mutation goal missing structured invariant", file=sys.stderr)
        return 1

    payload = json.loads(args.action_payload)
    extra_headers = {}
    if args.auth_header and ":" in args.auth_header:
        k, v = args.auth_header.split(":", 1)
        extra_headers[k.strip()] = v.strip()

    # Optional pre-state precondition (e.g. role NOT YET present)
    pre_results: list[dict] = []
    if inv.preconditions:
        pre_status, pre_body = _http_request(
            "GET", inv.read.endpoint, None,
            {**_cache_headers(inv.read.cache_policy), **extra_headers},
        )
        pre_results = _eval_assertions(pre_body, inv.preconditions, payload)

    # Write
    write_status, write_body = _http_request(
        inv.write.method, inv.write.endpoint, payload, extra_headers,
    )
    if write_status >= 400:
        # Non-2xx write — R1 silent_state_mismatch might apply
        evidence = _emit_evidence(args, goal_path, "BLOCK",
            f"R1 silent_state_mismatch — write returned {write_status}",
            write_status, {}, [], pre_results, None, None)
        return 1

    # Read with cache_policy + settle
    read_headers = {**_cache_headers(inv.read.cache_policy), **extra_headers}
    read_status, read_body, attempts = _settle_loop(inv.read.endpoint, read_headers, inv.read.settle)

    # Evaluate assertions
    assert_results = _eval_assertions(read_body, inv.assertions, payload)
    side_results = _eval_assertions(read_body, inv.side_effects, payload) if inv.side_effects else []

    # Decide severity
    failed_assert = [r for r in assert_results if not r["passed"]]
    failed_side = [r for r in side_results if not r["passed"]]
    if failed_assert:
        # R8 update_did_not_apply (most common — toast OK + DB unchanged)
        summary = (f"R8 update_did_not_apply — write {write_status} but read shows "
                   f"{len(failed_assert)} assertion(s) failed: "
                   + "; ".join(r["detail"] for r in failed_assert[:3]))
        evidence = _emit_evidence(args, goal_path, "BLOCK", summary,
            write_status, write_body, assert_results, pre_results, read_status, read_body)
        return 1
    if failed_side:
        summary = (f"side_effect mismatch — primary assertion passed but {len(failed_side)} "
                   f"side_effect(s) failed: "
                   + "; ".join(f"{r.get('layer','?')}:{r['detail']}" for r in failed_side[:3]))
        evidence = _emit_evidence(args, goal_path, "BLOCK", summary,
            write_status, write_body, assert_results, pre_results, read_status, read_body, side_results)
        return 1

    # All passed — informational evidence
    summary = (f"RCRURD PASS for {goal_path.stem}: write {write_status}, "
               f"read {read_status}, {len(assert_results)} assertion(s) verified, "
               f"{len(side_results)} side_effect(s) verified, settle attempts={attempts}")
    _emit_evidence(args, goal_path, "ADVISORY", summary,
        write_status, write_body, assert_results, pre_results, read_status, read_body, side_results)
    print(f"✓ {summary}")
    return 0


def _emit_evidence(args, goal_path: Path, severity: str, summary: str,
                   write_status: int, write_body: dict, assert_results: list,
                   pre_results: list, read_status: int | None, read_body: dict | None,
                   side_results: list | None = None) -> dict:
    ev = {
        "warning_id": f"rcrurd-{args.phase}-{goal_path.stem}",
        "severity": severity,
        "category": "rcrurd_runtime",
        "phase": args.phase,
        "evidence_refs": [{"file": str(goal_path), "task_id": goal_path.stem}],
        "summary": summary,
        "detected_by": "verify-rcrurd-runtime.py",
        "detected_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "owning_artifact": "TEST-GOALS/" + goal_path.name,
        "recommended_action": (
            "Investigate write handler / DB transaction / cache invalidation. "
            "Verify the API actually persists the change (DB inspection)."
        ),
        "confidence": 1.0 if severity == "BLOCK" else 0.5,
        "details": {
            "write_status": write_status,
            "read_status": read_status,
            "assertions": assert_results,
            "preconditions": pre_results,
            "side_effects": side_results or [],
        },
    }
    if args.evidence_out:
        Path(args.evidence_out).write_text(json.dumps(ev, indent=2), encoding="utf-8")
    return ev


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests**

Run:
```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
chmod +x scripts/validators/verify-rcrurd-runtime.py
python3 -m pytest tests/test_rcrurd_runtime.py -v
```
Expected: 3 passed (PASS-when-persists, BLOCK-on-LIE, SKIP-non-mutation).

- [ ] **Step 5: Wire into review.md Phase 4**

Edit `commands/vg/review.md`. Find Phase 4 (search `goal_comparison`). Insert before the existing per-goal logic:

```markdown
### Phase 4 — RCRURD runtime verification (mandatory per mutation goal — Codex GPT-5.5 review 2026-05-03)

For every TEST-GOALS/G-NN.md with `goal_type: mutation`, run the runtime
gate. BLOCK review.completed if any goal lacks evidence OR fails.

```bash
EVIDENCE_DIR="${PHASE_DIR}/.rcrurd-evidence"
mkdir -p "$EVIDENCE_DIR"
RCRURD_FAILED=0

for goal in "${PHASE_DIR}/TEST-GOALS"/G-*.md; do
  grep -qE "goal_type:\s*mutation" "$goal" || continue
  ev_out="${EVIDENCE_DIR}/$(basename "$goal" .md).json"

  # Action payload comes from per-phase fixture (FIXTURES/G-NN.json) —
  # caller writes the action data so the gate can resolve action.<key>.
  payload="{}"
  fixture="${PHASE_DIR}/FIXTURES/$(basename "$goal" .md).action.json"
  [ -f "$fixture" ] && payload=$(cat "$fixture")

  "${PYTHON_BIN:-python3}" .claude/scripts/validators/verify-rcrurd-runtime.py \
    --goal-file "$goal" \
    --phase "${PHASE_NUMBER}" \
    --action-payload "$payload" \
    --auth-header "$(vg_config_get review.rcrurd_auth_header '')" \
    --evidence-out "$ev_out" || RCRURD_FAILED=1
done

if [ "$RCRURD_FAILED" = "1" ]; then
  echo "⛔ Phase 4 RCRURD runtime — at least one mutation goal failed"
  echo "   Evidence: ${EVIDENCE_DIR}/*.json"
  echo "   Route through classifier (Task 7) — most are IN_SCOPE for current phase"
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
    "review.rcrurd_runtime_failed" \
    --payload "{\"phase\":\"${PHASE_NUMBER}\",\"evidence_dir\":\"${EVIDENCE_DIR}\"}" \
    2>/dev/null || true
  exit 1
fi

"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
  "review.rcrurd_runtime_passed" \
  --payload "{\"phase\":\"${PHASE_NUMBER}\"}" 2>/dev/null || true
```
```

Add to `commands/vg/review.md` frontmatter `must_emit_telemetry`:

```yaml
    - event_type: "review.rcrurd_runtime_passed"
      phase: "${PHASE_NUMBER}"
    - event_type: "review.rcrurd_runtime_failed"
      phase: "${PHASE_NUMBER}"
      severity: "warn"
```

- [ ] **Step 6: Commit**

```bash
git add scripts/validators/verify-rcrurd-runtime.py \
        tests/test_rcrurd_runtime.py \
        commands/vg/review.md
git commit -m "feat(rcrurd): mandatory runtime verification per mutation goal in /vg:review

Codex GPT-5.5 review 2026-05-03: lens-business-coherence not guaranteed
to run per mutation goal. Add Phase 4 runtime gate executing structured
invariant from Task 22 parser. BLOCK review.completed on assertion fail
(R8 update_did_not_apply, etc).

cache_policy: no_store enforced via Cache-Control + Pragma headers.
settle: poll honors timeout_ms/interval_ms (eventual consistency)."
```
