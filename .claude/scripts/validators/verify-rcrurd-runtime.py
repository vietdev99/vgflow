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
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "lib"))
from rcrurd_invariant import extract_from_test_goal_md, Assertion, LifecyclePhase  # type: ignore  # noqa: E402


def _eval_jsonpath(body: object, path: str) -> list[object]:
    """Tiny JSONPath subset — supports $.a, $.a.b, $.a[*], $.a[*].b."""
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
    return {}


def _eval_assertions(read_body: dict, assertions, payload: dict) -> list[dict]:
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
        time.sleep(interval_ms / 1000.0)
    return last[0], last[1], attempts


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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--goal-file", required=True)
    parser.add_argument("--phase", required=True)
    parser.add_argument("--action-payload", default="{}",
                        help='JSON dict resolving action.<key> placeholders + write body')
    parser.add_argument("--auth-header", default="")
    parser.add_argument("--evidence-out")
    args = parser.parse_args()

    goal_path = Path(args.goal_file)
    if not goal_path.exists():
        print(f"ERROR: goal-file not found: {goal_path}", file=sys.stderr)
        return 2
    text = goal_path.read_text(encoding="utf-8")

    if "**goal_type:** mutation" not in text and "goal_type: mutation" not in text:
        print(f"✓ {goal_path.name} is non-mutation — skipped (no invariant required)")
        return 0

    inv = extract_from_test_goal_md(text)
    if inv is None:
        print(f"⛔ {goal_path.name}: mutation goal missing structured invariant", file=sys.stderr)
        return 1

    payload = json.loads(args.action_payload)
    extra_headers = {}
    if args.auth_header and ":" in args.auth_header:
        k, v = args.auth_header.split(":", 1)
        extra_headers[k.strip()] = v.strip()

    # Task 39: dispatch based on lifecycle discriminator
    if inv.lifecycle in ("rcrurdr", "partial"):
        return _run_lifecycle_phases(args, goal_path, inv, payload, extra_headers)

    # Legacy single-cycle path (lifecycle == "rcrurd")
    pre_results: list[dict] = []
    if inv.preconditions:
        pre_status, pre_body = _http_request(
            "GET", inv.read.endpoint, None,
            {**_cache_headers(inv.read.cache_policy), **extra_headers},
        )
        pre_results = _eval_assertions(pre_body, inv.preconditions, payload)

    write_status, write_body = _http_request(
        inv.write.method, inv.write.endpoint, payload, extra_headers,
    )
    if write_status >= 400:
        _emit_evidence(args, goal_path, "BLOCK",
            f"R1 silent_state_mismatch — write returned {write_status}",
            write_status, write_body, [], pre_results, None, None)
        return 1

    read_headers = {**_cache_headers(inv.read.cache_policy), **extra_headers}
    read_status, read_body, attempts = _settle_loop(inv.read.endpoint, read_headers, inv.read.settle)

    assert_results = _eval_assertions(read_body, inv.assertions, payload)
    side_results = _eval_assertions(read_body, inv.side_effects, payload) if inv.side_effects else []

    failed_assert = [r for r in assert_results if not r["passed"]]
    failed_side = [r for r in side_results if not r["passed"]]
    if failed_assert:
        summary = (f"R8 update_did_not_apply — write {write_status} but read shows "
                   f"{len(failed_assert)} assertion(s) failed: "
                   + "; ".join(r["detail"] for r in failed_assert[:3]))
        _emit_evidence(args, goal_path, "BLOCK", summary,
            write_status, write_body, assert_results, pre_results, read_status, read_body)
        return 1
    if failed_side:
        summary = (f"side_effect mismatch — primary assertion passed but {len(failed_side)} "
                   f"side_effect(s) failed: "
                   + "; ".join(f"{r.get('layer','?')}:{r['detail']}" for r in failed_side[:3]))
        _emit_evidence(args, goal_path, "BLOCK", summary,
            write_status, write_body, assert_results, pre_results, read_status, read_body, side_results)
        return 1

    summary = (f"RCRURD PASS for {goal_path.stem}: write {write_status}, "
               f"read {read_status}, {len(assert_results)} assertion(s) verified, "
               f"{len(side_results)} side_effect(s) verified, settle attempts={attempts}")
    _emit_evidence(args, goal_path, "ADVISORY", summary,
        write_status, write_body, assert_results, pre_results, read_status, read_body, side_results)
    print(f"✓ {summary}")
    return 0


def _run_lifecycle_phases(args, goal_path, inv, payload: dict, extra_headers: dict) -> int:
    """Task 39: run write+read+assert per lifecycle phase for rcrurdr / partial."""
    phase_results: list[dict] = []
    for lp in inv.lifecycle_phases:
        write_status = 0
        write_body: dict = {}
        if lp.write is not None:
            write_status, write_body = _http_request(
                lp.write.method, lp.write.endpoint, payload, extra_headers,
            )
            if write_status >= 400:
                summary = (
                    f"R1 silent_state_mismatch — phase={lp.phase} write "
                    f"returned {write_status}"
                )
                _emit_evidence(
                    args, goal_path, "BLOCK", summary,
                    write_status, write_body, [], [], None, None,
                )
                return 1

        read_headers = {**_cache_headers(lp.read.cache_policy), **extra_headers}
        read_status, read_body, attempts = _settle_loop(
            lp.read.endpoint, read_headers, lp.read.settle
        )
        assert_results = _eval_assertions(read_body, lp.assertions, payload)
        failed = [r for r in assert_results if not r["passed"]]
        phase_results.append({
            "phase": lp.phase,
            "write_status": write_status,
            "read_status": read_status,
            "assertions": assert_results,
            "passed": len(failed) == 0,
        })
        if failed:
            summary = (
                f"R8 update_did_not_apply — phase={lp.phase} write {write_status} but "
                f"read shows {len(failed)} assertion(s) failed: "
                + "; ".join(r["detail"] for r in failed[:3])
            )
            _emit_evidence(
                args, goal_path, "BLOCK", summary,
                write_status, write_body, assert_results, [], read_status, read_body,
            )
            return 1

    total_assertions = sum(len(pr["assertions"]) for pr in phase_results)
    summary = (
        f"RCRURDR PASS for {goal_path.stem} ({inv.lifecycle}): "
        f"{len(phase_results)} phases, {total_assertions} assertion(s) verified"
    )
    _emit_evidence(
        args, goal_path, "ADVISORY", summary,
        0, {}, [], [], None, None,
    )
    print(f"✓ {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
