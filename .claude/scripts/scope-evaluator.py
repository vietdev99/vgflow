#!/usr/bin/env python3
"""
VG Bootstrap — Scope DSL Evaluator (v1.15.0)

Evaluates scope expressions for rules and override-debt entries.

Grammar:
    scope: {any_of: [pred, ...]} | {all_of: [pred, ...]} | {not: scope} | pred
    pred: "<var> <op> <value>"
    var: dotted path (e.g., "phase.surfaces", "step", "phase.has_mutation")
    op: "contains" | "matches" | "==" | "!=" | "does_not_contain"
    value: 'string', "string", true/false, number, bare word

Fail-closed policy:
    For rules:      unknown variable → predicate false (rule SKIPS, safe default)
    For overrides:  unknown variable → predicate false (gate ACTIVE, safe default)
    (Caller decides polarity by how they use the result.)

Usage:
    from scope_evaluator import evaluate_scope
    ctx = {"phase": {"surfaces": ["web"], "has_mutation": True}, "step": "review"}
    assert evaluate_scope({"any_of": ["phase.surfaces contains 'web'"]}, ctx) == True

CLI:
    python scope-evaluator.py --scope-json '{"any_of":[...]}' --context-json '{...}'
    # exits 0 if match, 1 if no match, 2 on error
"""
from __future__ import annotations

import fnmatch
import json
import re
import sys
from typing import Any


class ScopeEvalError(Exception):
    """Raised on malformed scope or context."""


_PRED_RE = re.compile(
    r"^\s*(?P<var>[a-zA-Z_][a-zA-Z0-9_.]*)\s+"
    r"(?P<op>contains|does_not_contain|matches|==|!=)\s+"
    r"(?P<value>.+?)\s*$"
)


def _lookup(context: dict, dotted: str) -> tuple[bool, Any]:
    """Resolve 'phase.surfaces' from context. Returns (found, value)."""
    cur: Any = context
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return False, None
    return True, cur


def _parse_value(raw: str) -> Any:
    raw = raw.strip()
    # quoted string
    if (raw.startswith("'") and raw.endswith("'")) or (
        raw.startswith('"') and raw.endswith('"')
    ):
        return raw[1:-1]
    # bool
    if raw.lower() == "true":
        return True
    if raw.lower() == "false":
        return False
    if raw.lower() == "null" or raw.lower() == "none":
        return None
    # number
    try:
        if "." in raw:
            return float(raw)
        return int(raw)
    except ValueError:
        pass
    # bare word treated as string (be lenient)
    return raw


def _eval_predicate(pred: str, context: dict) -> bool:
    m = _PRED_RE.match(pred)
    if not m:
        raise ScopeEvalError(f"Malformed predicate: {pred!r}")

    var = m.group("var")
    op = m.group("op")
    value = _parse_value(m.group("value"))

    found, actual = _lookup(context, var)
    if not found:
        # Fail-closed: unknown variable → predicate is false.
        # (Caller decides polarity — for rules this means SKIP, for overrides
        # the caller should invert or use positive framing to get "gate ACTIVE".)
        return False

    if op == "==":
        return actual == value
    if op == "!=":
        return actual != value
    if op == "contains":
        if actual is None:
            return False
        if isinstance(actual, (list, tuple, set)):
            return value in actual
        if isinstance(actual, str):
            return isinstance(value, str) and value in actual
        return False
    if op == "does_not_contain":
        if actual is None:
            return True
        if isinstance(actual, (list, tuple, set)):
            return value not in actual
        if isinstance(actual, str):
            return not (isinstance(value, str) and value in actual)
        return True
    if op == "matches":
        if actual is None or not isinstance(value, str):
            return False
        if isinstance(actual, (list, tuple, set)):
            return any(fnmatch.fnmatch(str(x), value) for x in actual)
        return fnmatch.fnmatch(str(actual), value)

    raise ScopeEvalError(f"Unknown operator: {op!r}")


def evaluate_scope(scope: Any, context: dict) -> bool:
    """Evaluate a scope expression against a context.

    `scope` may be:
      - a string predicate: "phase.surfaces contains 'web'"
      - a dict with {any_of: [...]}, {all_of: [...]}, or {not: <scope>}
      - None / empty dict → True (scope matches everything — USE SPARINGLY)
    """
    if scope is None:
        return True
    if isinstance(scope, str):
        return _eval_predicate(scope, context)
    if not isinstance(scope, dict):
        raise ScopeEvalError(f"Scope must be str or dict, got {type(scope).__name__}")

    if not scope:
        return True  # empty dict = match all

    # any_of / all_of / not
    if "any_of" in scope:
        preds = scope["any_of"]
        if not isinstance(preds, list) or not preds:
            raise ScopeEvalError("any_of must be a non-empty list")
        return any(evaluate_scope(p, context) for p in preds)

    if "all_of" in scope:
        preds = scope["all_of"]
        if not isinstance(preds, list) or not preds:
            raise ScopeEvalError("all_of must be a non-empty list")
        return all(evaluate_scope(p, context) for p in preds)

    if "not" in scope:
        return not evaluate_scope(scope["not"], context)

    # Fallback: treat as predicate in required_all pattern (override-debt legacy)
    if "required_all" in scope:
        return evaluate_scope({"all_of": scope["required_all"]}, context)

    raise ScopeEvalError(f"Unknown scope structure: {list(scope.keys())!r}")


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Evaluate VG bootstrap scope DSL")
    ap.add_argument("--scope-json", required=True)
    ap.add_argument("--context-json", required=True)
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args()

    try:
        scope = json.loads(args.scope_json)
        context = json.loads(args.context_json)
    except json.JSONDecodeError as e:
        print(f"JSON parse error: {e}", file=sys.stderr)
        return 2

    try:
        result = evaluate_scope(scope, context)
    except ScopeEvalError as e:
        print(f"Scope error: {e}", file=sys.stderr)
        return 2

    if args.verbose:
        print(f"scope={scope} context={context} => {result}", file=sys.stderr)
    print("true" if result else "false")
    return 0 if result else 1


if __name__ == "__main__":
    sys.exit(main())
