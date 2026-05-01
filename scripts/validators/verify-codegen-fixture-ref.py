#!/usr/bin/env python3
"""Validate codegen specs reference FIXTURE.* when goal has captured store.

Codex-HIGH-3 fix: Codex flagged that the codegen integration was a
comment-only stub. This validator catches the regression — if a goal
has FIXTURES-CACHE entry but its generated .spec.ts doesn't reference
`FIXTURE.*` identifiers, the codegen-fixture-inject step was skipped
or didn't run.

Severity: BLOCK at /vg:test exit. Override via --allow-no-fixture-ref
(logs override-debt; legitimate only when codegen intentionally
ignored the fixture, e.g., goal is read-only).

Usage:
  scripts/validators/verify-codegen-fixture-ref.py \\
    --phase 3.2 \\
    --tests-dir apps/web/e2e
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import Evidence, Output, emit_and_exit, find_phase_dir, timer  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from runtime.fixture_cache import load as cache_load
except ImportError:
    cache_load = None  # type: ignore[assignment]


SPEC_PATTERN = re.compile(r"(G-[\w.-]+)\.spec\.ts$")
FIXTURE_REF_RE = re.compile(r"\bFIXTURE\.[a-zA-Z_$][\w$]*\b")


def find_specs(tests_dir: Path) -> dict[str, Path]:
    if not tests_dir.exists():
        return {}
    out: dict[str, Path] = {}
    for spec in sorted(tests_dir.rglob("*.spec.ts")):
        m = SPEC_PATTERN.search(spec.name)
        if m:
            out[m.group(1)] = spec
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    ap.add_argument("--tests-dir", default="apps/web/e2e",
                    help="Generated tests directory (relative to repo root)")
    ap.add_argument("--severity", choices=["block", "warn"], default="block")
    ap.add_argument("--allow-no-fixture-ref", action="store_true")
    args = ap.parse_args()

    out = Output(validator="codegen-fixture-ref")
    with timer(out):
        phase_dir = find_phase_dir(args.phase)
        if phase_dir is None:
            out.add(Evidence(type="phase_not_found", message=f"phase: {args.phase}"))
            emit_and_exit(out)

        if cache_load is None:
            out.add(Evidence(
                type="runtime_unavailable",
                message="scripts/runtime not importable — install RFC v9 deps",
            ))
            emit_and_exit(out)

        cache_data = cache_load(phase_dir)
        entries = cache_data.get("entries") or {}
        goals_with_captured = {
            gid for gid, e in entries.items()
            if isinstance(e, dict) and e.get("captured")
        }

        if not goals_with_captured:
            out.add(Evidence(
                type="no_captured_goals",
                message="FIXTURES-CACHE.json has no captured stores — nothing to verify",
            ), escalate=False)
            emit_and_exit(out)

        import os
        repo = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
        tests_dir = (repo / args.tests_dir).resolve()
        specs = find_specs(tests_dir)

        missing_refs: list[dict] = []
        missing_specs: list[str] = []
        ok_count = 0

        for gid in sorted(goals_with_captured):
            spec_path = specs.get(gid)
            if spec_path is None:
                missing_specs.append(gid)
                continue
            text = spec_path.read_text(encoding="utf-8")
            if not FIXTURE_REF_RE.search(text):
                missing_refs.append({
                    "gid": gid,
                    "spec": str(spec_path.relative_to(repo)) if spec_path.is_relative_to(repo) else str(spec_path),
                })
            else:
                ok_count += 1

        out.add(Evidence(
            type="codegen_fixture_summary",
            message=(
                f"{len(goals_with_captured)} goal(s) have captured store; "
                f"{ok_count} spec(s) reference FIXTURE; "
                f"{len(missing_refs)} spec(s) missing FIXTURE ref; "
                f"{len(missing_specs)} goal(s) have no spec at all"
            ),
        ), escalate=False)

        if args.allow_no_fixture_ref and (missing_refs or missing_specs):
            out.add(Evidence(
                type="override_accepted",
                message=f"--allow-no-fixture-ref override (debt logged)",
            ), escalate=False)
            emit_and_exit(out)

        for entry in missing_refs:
            out.add(
                Evidence(
                    type="fixture_ref_missing",
                    message=(
                        f"{entry['gid']} has FIXTURES-CACHE.captured but spec "
                        f"{entry['spec']} does not reference FIXTURE.*. "
                        f"codegen-fixture-inject did not run."
                    ),
                    file=entry["spec"],
                    fix_hint=(
                        f"Run: scripts/codegen-fixture-inject.py "
                        f"--phase {args.phase} --goal {entry['gid']} "
                        f"--spec {entry['spec']}"
                    ),
                ),
                escalate=(args.severity == "block"),
            )

        for gid in missing_specs:
            out.add(
                Evidence(
                    type="spec_missing_for_captured_goal",
                    message=(
                        f"{gid} has captured store but no .spec.ts found "
                        f"under {args.tests_dir}. /vg:test codegen step "
                        f"skipped this goal."
                    ),
                    fix_hint=(
                        f"Re-run /vg:test {args.phase} (codegen step), or "
                        f"verify the goal is in scope for codegen."
                    ),
                ),
                escalate=(args.severity == "block"),
            )

        if (missing_refs or missing_specs) and args.severity == "warn":
            if out.verdict == "BLOCK":
                out.verdict = "WARN"
            out.add(Evidence(
                type="severity_downgraded",
                message=(
                    f"{len(missing_refs) + len(missing_specs)} issues "
                    f"downgraded to WARN."
                ),
            ), escalate=False)

    emit_and_exit(out)


if __name__ == "__main__":
    main()
