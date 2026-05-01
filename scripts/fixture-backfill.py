#!/usr/bin/env python3
"""Generate FIXTURES/{G-XX}.yaml from existing RUNTIME-MAP.json scanner evidence.

RFC v9 PR-A.5 — migration tool for phases that completed /vg:build before
recipe authoring became required. Walks goal_sequences[].steps[] for mutation
goals, reconstructs probable POST/PUT/PATCH/DELETE shape from scanner-recorded
network entries, and emits a draft fixture-recipe.v1.json-conformant YAML.

Quality is best-effort:
- HIGH confidence: scanner captured a complete request body — verbatim copy.
- MEDIUM confidence: body partially captured; structural skeleton emitted with
  ${var} placeholders for missing fields.
- LOW confidence: only network method+endpoint visible; emit a stub with
  TODO comments for the user. Prints flagged goals after run.

Output:
  ${PHASE_DIR}/FIXTURES/G-XX.yaml (one per mutation goal)
  ${PHASE_DIR}/FIXTURES/.backfill-report.json (summary + confidence per goal)

Usage:
  scripts/fixture-backfill.py --phase 3.2 --dry-run        # preview
  scripts/fixture-backfill.py --phase 3.2 --apply          # commit
  scripts/fixture-backfill.py --phase 3.2 --apply --only G-10,G-11
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    print("PyYAML required — `pip install pyyaml>=6.0`", file=sys.stderr)
    sys.exit(2)


MUTATION_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
SUBMIT_VERBS = (
    "submit", "approve", "confirm", "save", "create", "update",
    "delete", "reject", "send", "duyệt", "xác nhận", "gửi",
    "tạo", "cập nhật", "xóa", "từ chối",
)
SUBMIT_ACTIONS = {"click", "submit", "tap", "press"}


@dataclass
class GoalEvidence:
    goal_id: str
    title: str
    steps: list[dict] = field(default_factory=list)
    mutation_steps: list[dict] = field(default_factory=list)
    confidence: str = "LOW"
    rationale: list[str] = field(default_factory=list)


def find_phase_dir(repo_root: Path, phase: str) -> Path | None:
    phases_dir = repo_root / ".vg" / "phases"
    if not phases_dir.exists():
        return None
    candidates = sorted(phases_dir.glob(f"{phase}-*"))
    if not candidates and "." in phase and not phase.split(".")[0].startswith("0"):
        head, _, tail = phase.partition(".")
        candidates = sorted(phases_dir.glob(f"{head.zfill(2)}.{tail}-*"))
    return candidates[0] if candidates else None


def is_mutation_step(step: dict) -> bool:
    if not isinstance(step, dict):
        return False
    action = str(step.get("do") or step.get("action") or "").lower()
    if action not in SUBMIT_ACTIONS:
        return False
    target = " ".join(
        str(step.get(k, "")) for k in ("target", "label", "selector", "name")
    ).lower()
    return any(v in target for v in SUBMIT_VERBS)


def extract_mutation_network(step: dict) -> list[dict]:
    """Return all 2xx mutation network entries for a step."""
    out: list[dict] = []

    def walk(value: Any) -> None:
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
                method = str(e.get("method") or "").upper()
                status = e.get("status", e.get("status_code"))
                try:
                    code = int(status)
                except (TypeError, ValueError):
                    continue
                if method in MUTATION_METHODS and 200 <= code < 300:
                    out.append(e)
            for v in value.values():
                walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)

    walk(step)
    return out


def collect_goals(runtime: dict, only: set[str] | None) -> dict[str, GoalEvidence]:
    sequences = runtime.get("goal_sequences") or {}
    out: dict[str, GoalEvidence] = {}
    for gid, seq in sequences.items():
        if only and gid not in only:
            continue
        if not isinstance(seq, dict):
            continue
        steps = seq.get("steps") or []
        if not isinstance(steps, list):
            continue
        ge = GoalEvidence(goal_id=gid, title=str(seq.get("title", ""))[:120])
        for step in steps:
            if isinstance(step, dict):
                ge.steps.append(step)
                if is_mutation_step(step):
                    nets = extract_mutation_network(step)
                    if nets:
                        ge.mutation_steps.append({"step": step, "network": nets})
        if ge.mutation_steps:
            out[gid] = ge
    return out


def assess_confidence(evidence: GoalEvidence) -> None:
    """Annotate confidence based on what was captured."""
    if not evidence.mutation_steps:
        evidence.confidence = "LOW"
        evidence.rationale.append("no mutation step with 2xx network found")
        return
    has_body = False
    has_url_path = False
    for ms in evidence.mutation_steps:
        for net in ms["network"]:
            if net.get("body") or net.get("request_body"):
                has_body = True
            if net.get("endpoint") or net.get("url"):
                has_url_path = True
    if has_body and has_url_path:
        evidence.confidence = "HIGH"
        evidence.rationale.append("body + endpoint captured")
    elif has_url_path:
        evidence.confidence = "MEDIUM"
        evidence.rationale.append("endpoint captured; body missing → skeleton emitted")
    else:
        evidence.confidence = "LOW"
        evidence.rationale.append("only network method known; user must complete")


def derive_recipe(evidence: GoalEvidence) -> dict[str, Any]:
    """Build a fixture-recipe.v1.json-shaped dict from captured evidence."""
    steps_out: list[dict] = []
    for i, ms in enumerate(evidence.mutation_steps):
        for j, net in enumerate(ms["network"]):
            method = str(net.get("method", "POST")).upper()
            endpoint = net.get("endpoint") or net.get("url") or "/TODO"
            if not endpoint.startswith("/"):
                endpoint = "/" + endpoint.lstrip("/")
            body = net.get("body") or net.get("request_body")
            step_id = f"mutation_{i}_{j}" if len(evidence.mutation_steps) > 1 else f"mutation_{i}"
            step: dict[str, Any] = {
                "id": step_id,
                "kind": "api_call",
                "role": "TODO_role",
                "method": method,
                "endpoint": endpoint,
            }
            if method in {"POST", "PUT"}:
                step["idempotency_key"] = f"backfill-${{phase}}-${{goal}}-${{step}}-${{timestamp}}"
            if body:
                step["body"] = body
            elif method in {"POST", "PUT", "PATCH"}:
                step["body"] = {"TODO": "scanner did not capture request body — fill in"}
            steps_out.append(step)

    title = evidence.title or evidence.goal_id
    description = (
        f"Backfilled from RUNTIME-MAP scanner evidence on "
        f"{datetime.now(timezone.utc).isoformat(timespec='seconds')}. "
        f"Confidence: {evidence.confidence}. "
        f"Reasoning: {'; '.join(evidence.rationale) or 'see backfill report'}. "
        f"User must verify role assignment and replace TODO_role / TODO body fields."
    )
    return {
        "schema_version": "1.0",
        "goal": evidence.goal_id,
        "description": description,
        "fixture_intent": {
            "declared_in": f"TEST-GOALS.md#{evidence.goal_id}",
            "validates": title or "mutation lifecycle (backfill — fill in)",
        },
        "_backfill_meta": {
            "confidence": evidence.confidence,
            "rationale": evidence.rationale,
            "tool_version": "1.0",
        },
        "steps": steps_out,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Backfill FIXTURES/{G-XX}.yaml from RUNTIME-MAP")
    ap.add_argument("--phase", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--only", help="Comma-separated goal IDs", default=None)
    ap.add_argument("--repo-root", default=None)
    args = ap.parse_args()

    if not args.dry_run and not args.apply:
        ap.error("must specify --dry-run or --apply")
    if args.dry_run and args.apply:
        ap.error("--dry-run and --apply mutually exclusive")

    repo = Path(args.repo_root or os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
    phase_dir = find_phase_dir(repo, args.phase)
    if phase_dir is None:
        print(f"Phase '{args.phase}' not found at {repo / '.vg/phases'}", file=sys.stderr)
        return 1

    runtime_path = phase_dir / "RUNTIME-MAP.json"
    if not runtime_path.exists():
        print(f"RUNTIME-MAP.json not found at {runtime_path}", file=sys.stderr)
        return 1
    runtime = json.loads(runtime_path.read_text(encoding="utf-8"))

    only = {g.strip() for g in args.only.split(",")} if args.only else None
    evidences = collect_goals(runtime, only)
    if not evidences:
        print(f"No mutation goals with 2xx evidence found in {runtime_path}")
        return 0

    for ge in evidences.values():
        assess_confidence(ge)

    fixtures_dir = phase_dir / "FIXTURES"
    print(f"{'APPLY' if args.apply else 'DRY-RUN'}: {len(evidences)} mutation goal(s)")
    print(f"Output dir: {fixtures_dir}")
    print()

    summary = {
        "phase": args.phase,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "goals": [],
    }
    by_confidence = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}

    if args.apply:
        fixtures_dir.mkdir(exist_ok=True)

    for gid, ge in evidences.items():
        recipe = derive_recipe(ge)
        target = fixtures_dir / f"{gid}.yaml"
        by_confidence[ge.confidence] += 1

        print(f"  {gid:10s} confidence={ge.confidence:6s} steps={len(recipe['steps'])} "
              f"existing={'yes' if target.exists() else 'no'}")
        if args.apply:
            if target.exists():
                # Don't clobber existing recipes; user can manually merge.
                target = target.with_suffix(".yaml.backfill-draft")
            target.write_text(
                yaml.safe_dump(recipe, sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )

        summary["goals"].append({
            "goal_id": gid,
            "confidence": ge.confidence,
            "rationale": ge.rationale,
            "step_count": len(recipe["steps"]),
            "output_path": str(target.relative_to(repo)) if args.apply else None,
        })

    print()
    print(f"  HIGH: {by_confidence['HIGH']}, MEDIUM: {by_confidence['MEDIUM']}, "
          f"LOW: {by_confidence['LOW']}")

    if args.apply:
        report_path = fixtures_dir / ".backfill-report.json"
        report_path.write_text(
            json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"  Report: {report_path}")
        if by_confidence["LOW"] > 0:
            print()
            print(f"⚠ {by_confidence['LOW']} LOW-confidence goal(s) — review manually before /vg:review.")
    else:
        print()
        print("Re-run with --apply to write FIXTURES/{G-XX}.yaml.")
        if by_confidence["LOW"] > 0:
            print(f"⚠ {by_confidence['LOW']} LOW-confidence goal(s) flagged.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
