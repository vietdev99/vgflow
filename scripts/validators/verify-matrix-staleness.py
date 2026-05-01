#!/usr/bin/env python3
"""Detect stale READY status in GOAL-COVERAGE-MATRIX.md vs RUNTIME-MAP.json.

Closes Phase 3.2 dogfood gap: matrix says READY but scanner output shows
no submit evidence (modal opened, never submitted). User clicks button on
sandbox → toast error → bug. Matrix claimed PASS = lying.

Mechanism: cross-check goal_sequences[].steps[] against goal's mutation_evidence
declaration:
- mutation_evidence non-empty → goal expects submit + 2xx network
- goal_sequences[gid].result == 'passed' AND no submit click → SUSPECTED
- goal_sequences[gid].result == 'passed' AND no 2xx mutation network → SUSPECTED
- goal_sequences[gid].result == 'passed' AND only cancel-only steps → SUSPECTED

Output:
- Updates GOAL-COVERAGE-MATRIX.md: change SUSPECTED goals' status from READY → SUSPECTED
- Writes detailed report: ${PHASE_DIR}/.matrix-staleness.json
- BLOCKs at /vg:review entry (before --retry-failed short-circuit)
- Severity: BLOCK default; --severity warn for migration

When this validator passes (zero SUSPECTED), --retry-failed can trust matrix.
When BLOCKs, user MUST run --retry-failed (which will now include SUSPECTED)
to refresh evidence.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, emit_and_exit, find_phase_dir, timer  # noqa: E402

MUTATION_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
SUBMIT_TARGET_RE = re.compile(
    r"\b(submit|approve|confirm|save|create|update|delete|reject|send|"
    r"d[uồ]ng\s*[yý]|duy[eệ]t|x[aá]c\s*nh[aậ]n|g[uử]i|t[aạ]o|c[aậ]p\s*nh[aậ]t|"
    r"x[oó]a|t[uừ]\s*ch[oố]i)\b",
    re.IGNORECASE,
)
CANCEL_TARGET_RE = re.compile(
    r"\b(cancel|close|dismiss|abort|back|h[uủ]y|d[oó]ng|b[oỏ]\s*qua)\b",
    re.IGNORECASE,
)


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def parse_goals(text: str) -> list[dict]:
    """Parse TEST-GOALS.md goals minimally — id + mutation_evidence + title."""
    goals = []
    for m in re.finditer(
        r"^##\s+Goal\s+(G-[\w.-]+):?\s*(.*?)$"
        r"(?P<body>(?:(?!^##\s+Goal\s+).)*)",
        text,
        re.MULTILINE | re.DOTALL,
    ):
        gid = m.group(1)
        title = m.group(2).strip()
        body = m.group("body") or ""
        me_m = re.search(
            r"\*\*Mutation evidence:\*\*\s*(.+?)(?=\*\*|\n##|\Z)",
            body,
            re.DOTALL,
        )
        mutation_evidence = me_m.group(1).strip() if me_m else ""
        surface_m = re.search(r"\*\*Surface:\*\*\s*(\w+)", body)
        surface = surface_m.group(1).lower() if surface_m else "ui"
        # v2.46-wave3.2.1: only browser-surface goals need submit click + 2xx via browser.
        # Backend goals (api/data/integration/time-driven/custom) are verified by:
        # - verify-mutation-actually-submitted.py (wave-1, goal_sequences-level)
        # - verify-replay-evidence.py (curl replay)
        # - surface-probe.sh (handler grep, migration check, cron registration)
        # Including them here produces ~56% false positives (Phase 3.2 dogfood:
        # 21/36 flagged were backend, not UI). Only flag ui/ui-mobile.
        is_browser_surface = surface in ("ui", "ui-mobile")
        goals.append({
            "id": gid,
            "title": title,
            "mutation_evidence": mutation_evidence,
            "surface": surface,
            "needs_submit": bool(
                is_browser_surface and mutation_evidence and len(mutation_evidence) > 10
            ),
        })
    return goals


def has_submit_step(seq: dict) -> bool:
    steps = seq.get("steps") or []
    if not isinstance(steps, list):
        return False
    for step in steps:
        if not isinstance(step, dict):
            continue
        action = str(step.get("do") or step.get("action") or "").lower()
        if action not in {"click", "tap", "press", "submit"}:
            continue
        target = " ".join(
            str(step.get(k, "")) for k in ("target", "label", "selector", "name")
        )
        if SUBMIT_TARGET_RE.search(target) and not CANCEL_TARGET_RE.search(target):
            return True
    return False


def has_mutation_network(seq: dict) -> bool:
    """Walk seq for any 2xx POST/PUT/PATCH/DELETE."""
    def walk(value):
        if isinstance(value, dict):
            net = value.get("network")
            entries = []
            if isinstance(net, list):
                entries = net
            elif isinstance(net, dict):
                entries = [net]
            for e in entries:
                if not isinstance(e, dict):
                    continue
                method = str(e.get("method") or e.get("verb") or "").upper()
                status = e.get("status", e.get("status_code"))
                try:
                    code = int(status)
                except (TypeError, ValueError):
                    continue
                if method in MUTATION_METHODS and 200 <= code < 400:
                    return True
            for v in value.values():
                if walk(v):
                    return True
        elif isinstance(value, list):
            for v in value:
                if walk(v):
                    return True
        return False
    return walk(seq)


def parse_matrix_status(matrix_text: str) -> dict[str, str]:
    """Extract goal → status from matrix table."""
    status_map: dict[str, str] = {}
    pattern = re.compile(
        r"^\|\s*(G-[\w.-]+)\s*\|[^|]*\|[^|]*\|\s*([A-Z_]+)\s*\|",
        re.MULTILINE,
    )
    for m in pattern.finditer(matrix_text):
        status_map[m.group(1)] = m.group(2).strip()
    return status_map


def update_matrix_status(matrix_text: str, gid: str, new_status: str, note: str = "") -> str:
    """Replace status column for a specific goal id in matrix."""
    # Pattern: row starts with | G-XX |, capture columns up to status, replace status
    pattern = re.compile(
        rf"^(\|\s*{re.escape(gid)}\s*\|[^|]*\|[^|]*\|)\s*[A-Z_]+\s*(\|.*)$",
        re.MULTILINE,
    )
    def repl(m):
        suffix = m.group(2)
        if note:
            # Append note to evidence column (after first | in suffix)
            parts = suffix.split("|", 2)
            if len(parts) >= 2:
                ev = parts[1].rstrip()
                ev += f" [{note}]"
                suffix = "|" + ev + ("|" + parts[2] if len(parts) > 2 else "|")
        return f"{m.group(1)} {new_status} {suffix}"
    return pattern.sub(repl, matrix_text)


def main() -> None:
    parser = argparse.ArgumentParser(description="Detect matrix staleness vs runtime evidence")
    parser.add_argument("--phase", required=True)
    parser.add_argument("--severity", choices=["block", "warn"], default="block")
    parser.add_argument(
        "--apply-status-update",
        action="store_true",
        help="Rewrite matrix in place: stale READY → SUSPECTED",
    )
    parser.add_argument(
        "--allow-stale-matrix",
        action="store_true",
        help="Override: don't BLOCK on stale READY. Logs OVERRIDE-DEBT.",
    )
    args = parser.parse_args()

    out = Output(validator="matrix-staleness")
    with timer(out):
        phase_dir = find_phase_dir(args.phase)
        if phase_dir is None:
            out.add(Evidence(type="phase_not_found", message=f"Phase not found: {args.phase}"))
            emit_and_exit(out)

        goals_path = phase_dir / "TEST-GOALS.md"
        runtime_path = phase_dir / "RUNTIME-MAP.json"
        matrix_path = phase_dir / "GOAL-COVERAGE-MATRIX.md"
        if not all(p.exists() for p in (goals_path, runtime_path, matrix_path)):
            emit_and_exit(out)

        goals = parse_goals(_read(goals_path))
        try:
            runtime = json.loads(_read(runtime_path))
        except json.JSONDecodeError:
            emit_and_exit(out)
        sequences = runtime.get("goal_sequences") or {}
        matrix_text = _read(matrix_path)
        matrix_status = parse_matrix_status(matrix_text)

        suspected: list[dict] = []
        for goal in goals:
            if not goal["needs_submit"]:
                continue
            gid = goal["id"]
            if matrix_status.get(gid) != "READY":
                continue  # Already not READY, no staleness check needed
            seq = sequences.get(gid)
            if not isinstance(seq, dict):
                # Matrix says READY but no goal_sequence at all → fabricated
                suspected.append({
                    "id": gid,
                    "title": goal["title"][:80],
                    "reason": "matrix=READY but goal_sequences[gid] missing",
                    "evidence_class": "no_sequence",
                })
                continue

            steps = seq.get("steps") or []
            has_submit = has_submit_step(seq)
            has_2xx_mut = has_mutation_network(seq)

            if not steps:
                suspected.append({
                    "id": gid,
                    "title": goal["title"][:80],
                    "reason": "matrix=READY but goal_sequences[gid].steps empty",
                    "evidence_class": "empty_steps",
                })
            elif not has_submit:
                suspected.append({
                    "id": gid,
                    "title": goal["title"][:80],
                    "reason": "matrix=READY but no submit/approve/confirm click in steps",
                    "evidence_class": "no_submit_step",
                })
            elif not has_2xx_mut:
                suspected.append({
                    "id": gid,
                    "title": goal["title"][:80],
                    "reason": (
                        "matrix=READY with submit step but no successful "
                        "POST/PUT/PATCH/DELETE 2xx network"
                    ),
                    "evidence_class": "submit_no_2xx",
                })

        # Write detailed report
        report_path = phase_dir / ".matrix-staleness.json"
        report_path.write_text(
            json.dumps(
                {
                    "phase": args.phase,
                    "total_mutation_goals": sum(1 for g in goals if g["needs_submit"]),
                    "suspected_count": len(suspected),
                    "suspected": suspected,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        # Optionally update matrix in place
        if args.apply_status_update and suspected:
            new_text = matrix_text
            for s in suspected:
                new_text = update_matrix_status(
                    new_text, s["id"], "SUSPECTED",
                    note=f"stale: {s['evidence_class']}",
                )
            matrix_path.write_text(new_text, encoding="utf-8")

        # Emit evidence + verdict
        for s in suspected:
            out.add(
                Evidence(
                    type="matrix_stale_ready",
                    message=f"{s['id']} '{s['title']}': {s['reason']}",
                    file=str(matrix_path),
                    fix_hint=(
                        "Run /vg:review {phase} --retry-failed --include-suspected "
                        "to refresh evidence; OR /vg:review {phase} --re-scan-goals="
                        f"{','.join(s['id'] for s in suspected[:5])}"
                    ),
                ),
                escalate=(args.severity == "block" and not args.allow_stale_matrix),
            )

        if suspected and (args.severity == "warn" or args.allow_stale_matrix):
            if out.verdict == "BLOCK":
                out.verdict = "WARN"
            out.add(
                Evidence(
                    type="severity_downgraded",
                    message=f"{len(suspected)} stale READY downgraded to WARN.",
                ),
                escalate=False,
            )

    emit_and_exit(out)


if __name__ == "__main__":
    main()
