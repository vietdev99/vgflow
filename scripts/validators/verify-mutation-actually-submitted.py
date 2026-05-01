#!/usr/bin/env python3
"""Verify mutation goals were ACTUALLY submitted, not just modal-opened.

Closes the "performative review" meta-bug surfaced in Phase 3.2 dogfood
(2026-05-01): scanner agents Cancel modals to avoid destructive sandbox
mutations → never test happy path → CSRF/auth/idempotency bugs slip through →
matrix marks goal `READY` based on modal-opened evidence alone.

This validator complements verify-runtime-map-crud-depth.py:
- crud-depth: requires POST/PUT/PATCH/DELETE network entry with 2xx
- this validator: ALSO requires the goal_sequences[].steps[] to contain
  the actual click on submit/approve/reject button — not just cancel-only

Catches:
1. Goals where steps[] only has `do=click target=cancel` (modal opened, cancelled)
2. Goals where scanner observed CSRF/auth error but classified `result=passed`
   with rationalization vocabulary ("expected security", "as designed")
3. Goals where mutation_evidence is declared in TEST-GOALS but goal_sequences
   shows no submit attempt

Severity: BLOCK (default) when --severity not passed. Override per-phase via
--allow-cancel-only-mutations CLI flag (logs OVERRIDE-DEBT).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Iterable

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, emit_and_exit, find_phase_dir, timer  # noqa: E402


REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()

# Patterns suggesting a step is the SUBMIT/OK branch (not cancel/close)
SUBMIT_TARGET_RE = re.compile(
    r"\b(submit|approve|confirm|save|create|update|delete|reject|send|"
    r"đồng\s*ý|duyệt|xác\s*nhận|gửi|tạo|cập\s*nhật|xóa|từ\s*chối)\b",
    re.IGNORECASE,
)
CANCEL_TARGET_RE = re.compile(
    r"\b(cancel|close|dismiss|abort|back|hủy|đóng|bỏ\s*qua|quay\s*lại)\b",
    re.IGNORECASE,
)
RATIONALIZATION_RE = re.compile(
    r"(expected\s+security|as\s+designed|expected\s+behavior|"
    r"working\s+as\s+intended|correct\s+behavior|csrf\s+token\s+prevented)",
    re.IGNORECASE,
)
MUTATION_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
EMPTY_FIELD_VALUES = {"", "none", "n/a", "na", "null", "-", "[]", "{}"}


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def _field(body: str, name: str) -> str:
    m = re.search(
        rf"^\*\*{re.escape(name)}:\*\*\s*(.+?)(?:\n\*\*|\n##|\Z)",
        body,
        re.MULTILINE | re.DOTALL,
    )
    return m.group(1).strip() if m else ""


def _meaningful(value: str) -> bool:
    compact = re.sub(r"\s+", " ", value.strip()).lower()
    return compact not in EMPTY_FIELD_VALUES and not compact.startswith(
        ("none:", "n/a:", "na:")
    )


def _parse_goals(text: str) -> list[dict[str, Any]]:
    """Parse TEST-GOALS.md → list of goals with mutation metadata."""
    goals: list[dict[str, Any]] = []
    for match in re.finditer(
        r"^##\s+Goal\s+(G-[\w.-]+):?\s*(.*?)$"
        r"(?P<body>(?:(?!^##\s+Goal\s+).)*)",
        text,
        re.MULTILINE | re.DOTALL,
    ):
        gid = match.group(1)
        title = match.group(2).strip()
        body = match.group("body") or ""
        priority = _field(body, "Priority").lower() or "important"
        surface = _field(body, "Surface").split()[0].strip().lower() or "ui"
        mutation_evidence = _field(body, "Mutation evidence")
        mutation_required_field = _field(body, "Mutation required").lower()
        # Default: mutation_required=true if mutation_evidence is declared
        if mutation_required_field in {"true", "yes", "1"}:
            mutation_required = True
        elif mutation_required_field in {"false", "no", "0"}:
            mutation_required = False
        else:
            mutation_required = _meaningful(mutation_evidence)
        goals.append(
            {
                "id": gid,
                "title": title,
                "body": body,
                "priority": priority,
                "surface": surface,
                "mutation_evidence": mutation_evidence,
                "mutation_required": mutation_required,
            }
        )
    return goals


def _walk(value: Any) -> Iterable[Any]:
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _network_entries(seq: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for node in _walk(seq):
        if not isinstance(node, dict):
            continue
        network = node.get("network")
        if isinstance(network, list):
            entries.extend(x for x in network if isinstance(x, dict))
        elif isinstance(network, dict):
            entries.append(network)
    return entries


def _status_ok(status: Any) -> bool:
    try:
        code = int(status)
    except (TypeError, ValueError):
        return False
    return 200 <= code < 400


def _has_submit_step(seq: dict[str, Any]) -> bool:
    """Check goal_sequences[gid].steps[] has at least one submit-class action."""
    steps = seq.get("steps") or []
    if not isinstance(steps, list):
        return False
    for step in steps:
        if not isinstance(step, dict):
            continue
        action = str(step.get("do") or step.get("action") or "").lower()
        if action not in {"click", "tap", "press", "submit"}:
            continue
        target_text = " ".join(
            str(step.get(k, "")) for k in ("target", "label", "selector", "name")
        )
        if SUBMIT_TARGET_RE.search(target_text) and not CANCEL_TARGET_RE.search(
            target_text
        ):
            return True
    return False


def _has_only_cancel_steps(seq: dict[str, Any]) -> bool:
    """Detect cancel-only sequences (modal opened, cancelled, never submitted)."""
    steps = seq.get("steps") or []
    if not isinstance(steps, list) or not steps:
        return False
    saw_cancel = False
    saw_submit = False
    for step in steps:
        if not isinstance(step, dict):
            continue
        target_text = " ".join(
            str(step.get(k, "")) for k in ("target", "label", "selector", "name")
        )
        if CANCEL_TARGET_RE.search(target_text):
            saw_cancel = True
        if SUBMIT_TARGET_RE.search(target_text) and not CANCEL_TARGET_RE.search(
            target_text
        ):
            saw_submit = True
    return saw_cancel and not saw_submit


def _has_rationalization(seq: dict[str, Any]) -> tuple[bool, str]:
    """Detect rationalization vocabulary in reason/observed/notes fields."""
    blob_parts: list[str] = []
    for node in _walk(seq):
        if isinstance(node, dict):
            for k in ("reason", "observed", "note", "notes", "summary", "expected"):
                v = node.get(k)
                if isinstance(v, str):
                    blob_parts.append(v)
        elif isinstance(node, str):
            blob_parts.append(node)
    blob = " ".join(blob_parts)
    m = RATIONALIZATION_RE.search(blob)
    return (bool(m), m.group(0) if m else "")


def _has_mutation_network(seq: dict[str, Any]) -> bool:
    for entry in _network_entries(seq):
        method = str(entry.get("method") or entry.get("verb") or "").upper()
        if method in MUTATION_METHODS and _status_ok(
            entry.get("status", entry.get("status_code"))
        ):
            return True
    return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify mutation goals were actually submitted, not modal-opened-then-cancelled"
    )
    parser.add_argument("--phase", required=True)
    parser.add_argument(
        "--severity",
        choices=["block", "warn"],
        default="block",
        help="block (default) = exit 1 on violations; warn = exit 0 with evidence emitted",
    )
    parser.add_argument(
        "--allow-cancel-only-mutations",
        action="store_true",
        help="Override: allow goals to be marked passed without submit step. Logs OVERRIDE-DEBT.",
    )
    args = parser.parse_args()

    out = Output(validator="mutation-actually-submitted")
    with timer(out):
        phase_dir = find_phase_dir(args.phase)
        if phase_dir is None:
            out.add(
                Evidence(
                    type="phase_not_found",
                    message=f"Phase directory not found for {args.phase}",
                    expected=".vg/phases/<phase>-*",
                )
            )
            emit_and_exit(out)

        goals_path = phase_dir / "TEST-GOALS.md"
        runtime_path = phase_dir / "RUNTIME-MAP.json"
        if not goals_path.exists() or not runtime_path.exists():
            emit_and_exit(out)

        goals = _parse_goals(_read(goals_path))
        try:
            runtime = json.loads(_read(runtime_path))
        except json.JSONDecodeError as exc:
            out.add(
                Evidence(
                    type="runtime_map_json_invalid",
                    message=f"RUNTIME-MAP.json parse failed: {exc}",
                    file=str(runtime_path),
                )
            )
            emit_and_exit(out)

        sequences = runtime.get("goal_sequences") or {}
        if not isinstance(sequences, dict):
            emit_and_exit(out)

        violations = 0
        for goal in goals:
            if not goal["mutation_required"]:
                continue
            gid = goal["id"]
            seq = sequences.get(gid)
            if not isinstance(seq, dict):
                # Missing sequence — caller (matrix-evidence-link / crud-depth) handles
                continue

            result = str(seq.get("result", "")).lower()
            if result not in {"passed", "pass", "ready", "yes"}:
                # Goal not claimed passing — nothing to falsify
                continue

            # Violation 1: cancel-only sequence (modal opened, cancelled, no submit)
            if _has_only_cancel_steps(seq):
                violations += 1
                out.add(
                    Evidence(
                        type="mutation_passed_but_cancel_only",
                        message=(
                            f"{gid}: marked passed but goal_sequences.steps shows cancel-only "
                            "path — never executed submit. Performative review."
                        ),
                        file=str(runtime_path),
                        expected="Step with do=click target~submit/approve/confirm + 2xx network",
                        actual=f"steps={len(seq.get('steps') or [])} all-cancel-or-no-submit",
                        fix_hint=(
                            "Re-run /vg:review with scanner directed to SUBMIT (sandbox = "
                            "disposable seed). Update prompt to ban 'Cancel modals only'."
                        ),
                    )
                )
                continue

            # Violation 2: no submit step at all
            if not _has_submit_step(seq):
                violations += 1
                out.add(
                    Evidence(
                        type="mutation_passed_without_submit_step",
                        message=(
                            f"{gid}: marked passed but goal_sequences.steps has no "
                            "submit/approve/confirm click action. Mutation goal requires "
                            "actual submit attempt."
                        ),
                        file=str(runtime_path),
                        expected="At least 1 step with do=click target~submit pattern",
                        fix_hint="Scanner must execute Submit/Approve/Confirm button click.",
                    )
                )
                continue

            # Violation 3: submit step exists but no 2xx mutation network observed
            if not _has_mutation_network(seq):
                violations += 1
                out.add(
                    Evidence(
                        type="mutation_passed_without_2xx_network",
                        message=(
                            f"{gid}: marked passed with submit step but no successful "
                            "POST/PUT/PATCH/DELETE network entry. Likely server "
                            "rejected (CSRF/auth/validation) — scanner classified "
                            "the rejection as 'passed' incorrectly."
                        ),
                        file=str(runtime_path),
                        expected="Mutation method + 2xx status",
                        actual=f"network_entries={len(_network_entries(seq))}",
                        fix_hint=(
                            "Check goal_sequences for 4xx/5xx responses. Reclassify "
                            "result=blocked with verbatim error code. Investigate root cause."
                        ),
                    )
                )
                continue

            # Violation 4: rationalization vocabulary in reason/observed
            has_rat, rat_phrase = _has_rationalization(seq)
            if has_rat:
                violations += 1
                out.add(
                    Evidence(
                        type="mutation_passed_with_rationalization",
                        message=(
                            f"{gid}: passed result paired with rationalization vocabulary "
                            f"\"{rat_phrase}\". Banned per scanner-report-contract Section 1 — "
                            "scanner CANNOT classify mismatch as expected. Commander adjudicates."
                        ),
                        file=str(runtime_path),
                        expected=(
                            "match: no with verbatim error; commander cross-references "
                            "TEST-GOALS to determine if observation is bug or correct security"
                        ),
                        fix_hint=(
                            "Re-run with banned vocabulary filter. Scanner must record "
                            "\"expected: 200 + status approved; observed: 403 CSRF_MISSING; "
                            "match: no\" — let commander decide if 403 is correct security "
                            "or FE bug missing CSRF token."
                        ),
                    )
                )

        # Severity downgrade: if --allow-cancel-only-mutations OR --severity=warn,
        # convert BLOCK verdict to WARN so orchestrator continues (override-debt
        # logged by /vg:review wrapper).
        if (args.allow_cancel_only_mutations or args.severity == "warn") and \
                out.verdict == "BLOCK":
            out.verdict = "WARN"
            out.add(
                Evidence(
                    type="severity_downgraded",
                    message=(
                        f"{violations} violation(s) detected but downgraded to WARN "
                        f"(severity={args.severity}, "
                        f"allow_cancel_only={args.allow_cancel_only_mutations}). "
                        "Logged for trust calibration. Run with --severity=block to enforce."
                    ),
                ),
                escalate=False,
            )

    emit_and_exit(out)


if __name__ == "__main__":
    main()
