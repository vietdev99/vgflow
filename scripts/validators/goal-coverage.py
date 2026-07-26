#!/usr/bin/env python3
"""
Validator: goal-coverage.py

Purpose: TEST-GOALS.md goals must bind to actual test artifacts. Audit found
review marking goals PASS with verification_strategy: deferred pointing to
non-existent target phases. Test suite said PASSED with 0 goal evidence.

Checks:
- TEST-GOALS.md parsed for G-NN goals
- Each automated goal has a test file referencing TS-XX marker
- Deferred goals: target phase exists in ROADMAP.md
- Manual goals are flagged but not blocking

Usage: goal-coverage.py --phase <N>
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, timer, emit_and_exit, find_phase_dir  # noqa: E402

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
PHASES_DIR = REPO_ROOT / ".vg" / "phases"
ROADMAP = REPO_ROOT / ".vg" / "ROADMAP.md"

GOAL_RE = re.compile(
    r"##+\s+(?:Goal\s+)?G-(\d+)[:\s].+?(?=##+\s+(?:Goal\s+)?G-\d+|\Z)",
    re.DOTALL | re.MULTILINE,
)
STRATEGY_RE = re.compile(r"verification_strategy:\s*(\w+)", re.IGNORECASE)
DEPENDS_RE = re.compile(r"depends_on_phase:\s*(\S+)", re.IGNORECASE)
TS_BINDING_RE = re.compile(r"binds_to:\s*(TS-\d+(?:,\s*TS-\d+)*)", re.IGNORECASE)
# vg-test-codegen emits `vg-binding: {phase}.G-NN` markers inside generated
# .spec.ts files (NOT binds_to:TS-XX which codegen never produces). A goal is
# covered when a spec file carries a vg-binding marker naming that goal id.
# Dogfound P4.7 amend#6 (2026-07-05): 64 goals flagged unbound at accept even
# though 10 real specs existed — validator only knew TS-XX + Implemented-by.
VG_BINDING_RE = re.compile(r"vg-binding:\s*[\w.]*?\b(G-\d+)\b", re.IGNORECASE)
# Legacy format: goals declare implementation via "Implemented by:" with .spec.ts filenames
IMPL_BY_RE = re.compile(r"\*\*Implemented\s+by:\*\*", re.IGNORECASE)
# Match test artifacts across: *.spec.ts/js, *.test.ts/py, smoke-*.sh
SPEC_FILE_RE = re.compile(
    r"([a-zA-Z0-9_-]+\.(?:spec|test)\.[tj]sx?|[a-zA-Z0-9_-]+\.test\.py|"
    r"smoke-[a-zA-Z0-9_-]+\.sh|scripts/[a-zA-Z0-9_/-]+\.sh)"
)


def parse_goals(text: str) -> list[dict]:
    goals = []
    for m in GOAL_RE.finditer(text):
        goal_id = f"G-{m.group(1)}"
        body = m.group(0)
        strategy = STRATEGY_RE.search(body)
        depends = DEPENDS_RE.search(body)
        binding = TS_BINDING_RE.search(body)
        impl_by = IMPL_BY_RE.search(body)

        # Collect TS-XX tokens AND .spec.ts filenames mentioned in body
        ts_tokens = []
        if binding:
            ts_tokens.extend(b.strip() for b in binding.group(1).split(","))
        # Legacy "Implemented by:" → extract .spec.ts filenames as proxies
        impl_specs: list[str] = []
        if impl_by:
            # Take text between "**Implemented by:**" and next "**" line
            impl_block = body[impl_by.start():]
            next_bold = re.search(r"\n\s*\*\*[A-Z]", impl_block)
            if next_bold:
                impl_block = impl_block[:next_bold.start()]
            impl_specs = SPEC_FILE_RE.findall(impl_block)

        goals.append({
            "id": goal_id,
            "strategy": (strategy.group(1).lower() if strategy else "automated"),
            "depends_on_phase": depends.group(1) if depends else None,
            "binds_to": ts_tokens,
            "impl_specs": impl_specs,
        })
    return goals


def find_ts_refs(scan_globs: list[str]) -> set[str]:
    """Grep TS-XX markers across test files."""
    found = set()
    ts_re = re.compile(r"\bTS-(\d+)\b")
    for gp in scan_globs:
        for f in Path(REPO_ROOT).glob(gp):
            if not f.is_file():
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            for m in ts_re.finditer(text):
                found.add(f"TS-{m.group(1)}")
    return found


def find_vg_binding_goals(scan_globs: list[str]) -> set[str]:
    """Collect goal ids named by `vg-binding: {phase}.G-NN` markers in specs.

    vg-test-codegen writes these markers into generated .spec.ts files. A goal
    whose id shows up here has an executable spec bound to it, even without a
    TS-XX marker or an `Implemented by:` line.
    """
    found = set()
    for gp in scan_globs:
        for f in Path(REPO_ROOT).glob(gp):
            if not f.is_file():
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            for m in VG_BINDING_RE.finditer(text):
                found.add(m.group(1).upper())
    return found


def phase_in_roadmap(phase: str) -> bool:
    if not ROADMAP.exists():
        return False
    text = ROADMAP.read_text(encoding="utf-8", errors="replace")
    # Loose match — phase might appear as "Phase 7.12" or "7.12"
    return bool(re.search(rf"Phase\s*{re.escape(phase)}\b", text)) or \
           bool(re.search(rf"^- Phase\s*{re.escape(phase)}", text, re.M))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    args = ap.parse_args()

    out = Output(validator="goal-coverage")
    with timer(out):
        phase_dir = find_phase_dir(args.phase)
        phase_dirs = [phase_dir] if phase_dir else []
        if not phase_dirs:
            out.add(Evidence(type="missing_file",
                             message=f"phase dir for {args.phase} not found"))
            emit_and_exit(out)

        goals_file = phase_dirs[0] / "TEST-GOALS.md"
        if not goals_file.exists():
            out.add(Evidence(
                type="missing_file",
                message="TEST-GOALS.md missing",
                file=str(goals_file),
                fix_hint="Run /vg:blueprint to generate TEST-GOALS.md",
            ))
            emit_and_exit(out)

        goals = parse_goals(goals_file.read_text(encoding="utf-8", errors="replace"))
        if not goals:
            out.add(Evidence(
                type="count_below_threshold",
                message="0 goals found in TEST-GOALS.md",
                expected=">=1",
            ))
            emit_and_exit(out)

        # Scan test files for TS-XX references + filename index
        test_globs = [
            "apps/*/e2e/**/*.ts",
            "apps/*/e2e/**/*.spec.ts",
            "apps/*/src/**/*.test.ts",
            "apps/*/tests/**/*.py",
            "apps/*/tests/**/*.ts",
            f".vg/phases/{args.phase}-*/SANDBOX-TEST.md",
            f".vg/phases/{args.phase}-*/SANDBOX-TEST*.md",
        ]
        ts_refs = find_ts_refs(test_globs)
        # vg-binding markers — scan the same spec globs plus the lifecycle dir
        # where /vg:test-spec codegen lands per-goal specs.
        vg_binding_goals = find_vg_binding_goals(test_globs + [
            "tests/e2e/**/*.spec.ts",
            "tests/e2e/**/*.ts",
        ])
        existing_spec_files = set()
        for gp in test_globs + [
            "scripts/**/*.sh",
            "apps/*/scripts/**/*.sh",
        ]:
            for f in REPO_ROOT.glob(gp):
                if f.is_file():
                    existing_spec_files.add(f.name)

        unbound_automated = []
        deferred_missing_target = []
        manual_count = 0

        for g in goals:
            strategy = g["strategy"]
            if strategy == "manual":
                manual_count += 1
                continue

            if strategy == "deferred":
                target = g["depends_on_phase"]
                if not target:
                    deferred_missing_target.append(g["id"])
                elif not phase_in_roadmap(target):
                    deferred_missing_target.append(f"{g['id']} → {target}")
                continue

            # automated: covered by ANY of —
            #   (1) TS-XX binding + a spec referencing that TS-XX
            #   (2) legacy `Implemented by:` .spec.ts filename that exists
            #   (3) vg-binding: {phase}.G-NN marker in a spec (codegen default)
            has_ts_binding = bool(g["binds_to"])
            has_impl_specs = bool(g["impl_specs"])

            covered_by_ts = (
                has_ts_binding and any(ts in ts_refs for ts in g["binds_to"])
            )
            covered_by_spec = (
                has_impl_specs and any(
                    spec in existing_spec_files for spec in g["impl_specs"]
                )
            )
            covered_by_vg_binding = g["id"].upper() in vg_binding_goals

            if not (covered_by_ts or covered_by_spec or covered_by_vg_binding):
                detail = (
                    ",".join(g["binds_to"]) if has_ts_binding
                    else (",".join(g["impl_specs"]) if has_impl_specs
                          else "no-binding-declared")
                )
                unbound_automated.append(f"{g['id']}={detail}")

        if unbound_automated:
            out.add(Evidence(
                type="goal_unbound",
                message=f"{len(unbound_automated)} automated goals not bound to any test file",
                actual=", ".join(unbound_automated[:10]),
                fix_hint="Each automated goal MUST be bound: 'binds_to: TS-XX' + spec referencing TS-XX, OR '**Implemented by:** <file>.spec.ts', OR a spec carrying 'vg-binding: {phase}.G-NN' (codegen default).",
            ))

        if deferred_missing_target:
            out.add(Evidence(
                type="schema_violation",
                message=f"{len(deferred_missing_target)} deferred goals point to non-existent phase",
                actual=", ".join(deferred_missing_target[:10]),
                fix_hint="Update depends_on_phase to a phase present in ROADMAP.md, or re-strategy.",
            ))

        if manual_count > len(goals) / 2:
            out.warn(Evidence(
                type="count_below_threshold",
                message=f"{manual_count}/{len(goals)} goals are manual — low automation coverage",
            ))

    emit_and_exit(out)


if __name__ == "__main__":
    main()
