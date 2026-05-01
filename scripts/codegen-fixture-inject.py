#!/usr/bin/env python3
"""Inject `FIXTURE = {...}` const block into generated Playwright .spec.ts.

RFC v9 PR-E Codex-HIGH-3 fix — was a comment-only stub. Now actually
reads FIXTURES-CACHE.json captured store and prepends a typed TypeScript
constant at the top of the spec, so generated tests reference
`FIXTURE.pending_id` instead of hard-coded values from RUNTIME-MAP.

Mode 1 (single-file): inject for one goal_id into one spec file.
  scripts/codegen-fixture-inject.py \\
    --phase 3.2 --goal G-10 \\
    --spec apps/web/e2e/3.2-goal-G-10.spec.ts

Mode 2 (sweep): walk all generated specs in a directory; inject for any
spec whose name maps to a goal that has a captured store.
  scripts/codegen-fixture-inject.py \\
    --phase 3.2 --sweep apps/web/e2e/

Idempotent: if the spec already starts with `// VGFLOW_FIXTURE_INJECTED`
sentinel, the script replaces the existing block instead of stacking.

Output JSON:
  {"injected": [...], "skipped": [...], "errors": [...]}

Exit:
  0 — success (≥0 specs injected)
  1 — phase or cache file missing
  2 — arg error
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from runtime.fixture_cache import load as cache_load  # noqa: E402


SENTINEL_OPEN = "// VGFLOW_FIXTURE_INJECTED — DO NOT EDIT BELOW UNTIL CLOSE"
SENTINEL_CLOSE = "// VGFLOW_FIXTURE_INJECTED_END"


def _find_phase_dir(repo: Path, phase: str) -> Path | None:
    phases_dir = repo / ".vg" / "phases"
    if not phases_dir.exists():
        return None
    for prefix in (phase, _zero_pad(phase)):
        matches = sorted(phases_dir.glob(f"{prefix}-*"))
        if matches:
            return matches[0]
    return None


def _zero_pad(phase: str) -> str:
    if "." in phase and not phase.split(".")[0].startswith("0"):
        head, _, tail = phase.partition(".")
        return f"{head.zfill(2)}.{tail}"
    return phase


def _ts_literal(value: Any, indent: int = 2) -> str:
    """Render a Python value as a TypeScript literal."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        # Use JSON-escape for safety (handles backslashes, quotes, control chars)
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        items = [_ts_literal(v, indent + 2) for v in value]
        return "[" + ", ".join(items) + "]"
    if isinstance(value, dict):
        sp = " " * (indent + 2)
        ep = " " * indent
        lines = []
        for k, v in value.items():
            key = k if re.match(r"^[a-zA-Z_$][\w$]*$", str(k)) else json.dumps(k)
            lines.append(f"{sp}{key}: {_ts_literal(v, indent + 2)}")
        return "{\n" + ",\n".join(lines) + f"\n{ep}}}"
    # Fallback: stringify
    return json.dumps(str(value))


def render_block(captured: dict, *, goal_id: str, phase: str) -> str:
    """Build the full FIXTURE injection block (sentinel + const + sentinel)."""
    body = _ts_literal(captured)
    return (
        f"{SENTINEL_OPEN}\n"
        f"// goal: {goal_id}, phase: {phase}\n"
        f"// Source: FIXTURES-CACHE.json captured store from last review run.\n"
        f"// Edit FIXTURES/{goal_id}.yaml + re-run /vg:review to regenerate.\n"
        f"const FIXTURE = {body} as const;\n"
        f"{SENTINEL_CLOSE}\n"
    )


def inject_into_spec(spec_path: Path, block: str) -> str:
    """Idempotent inject. Returns 'injected' | 'replaced' | 'unchanged'."""
    text = spec_path.read_text(encoding="utf-8")

    # If sentinel block already present → replace it
    pattern = re.compile(
        re.escape(SENTINEL_OPEN) + r".*?" + re.escape(SENTINEL_CLOSE) + r"\n?",
        re.DOTALL,
    )
    if pattern.search(text):
        new_text = pattern.sub(block, text)
        if new_text == text:
            return "unchanged"
        spec_path.write_text(new_text, encoding="utf-8")
        return "replaced"

    # Else: prepend after any leading comment/import block
    # Find first non-comment, non-import line
    lines = text.splitlines(keepends=True)
    insert_idx = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "" or stripped.startswith("//") or stripped.startswith("import ") \
                or stripped.startswith("/*") or stripped.startswith("*") \
                or stripped.startswith("*/"):
            insert_idx = i + 1
            continue
        break
    new_lines = lines[:insert_idx] + [block + "\n"] + lines[insert_idx:]
    spec_path.write_text("".join(new_lines), encoding="utf-8")
    return "injected"


def find_specs_for_phase(sweep_dir: Path, phase: str) -> list[tuple[str, Path]]:
    """Return [(goal_id, spec_path)] for all specs naming a goal under sweep_dir."""
    out: list[tuple[str, Path]] = []
    if not sweep_dir.exists():
        return out
    # Common patterns: {phase}-goal-{G-XX}.spec.ts, {G-XX}.spec.ts, {phase}.{G-XX}.spec.ts
    pattern = re.compile(r"(G-[\w.-]+)\.spec\.ts$")
    for spec in sorted(sweep_dir.rglob("*.spec.ts")):
        m = pattern.search(spec.name)
        if m:
            out.append((m.group(1), spec))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    ap.add_argument("--goal", help="Single goal_id (use with --spec)")
    ap.add_argument("--spec", help="Single spec.ts path (use with --goal)")
    ap.add_argument("--sweep", help="Directory to walk for *.spec.ts")
    ap.add_argument("--repo-root", default=None)
    ap.add_argument("--dry-run", action="store_true",
                    help="Print plan; no writes")
    args = ap.parse_args()

    if not (args.spec or args.sweep):
        ap.error("must specify --spec/--goal OR --sweep")
    if args.spec and not args.goal:
        ap.error("--spec requires --goal")
    if args.sweep and (args.goal or args.spec):
        ap.error("--sweep is mutually exclusive with --spec/--goal")

    repo = Path(args.repo_root or os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
    phase_dir = _find_phase_dir(repo, args.phase)
    if phase_dir is None:
        print(json.dumps({"error": f"phase '{args.phase}' not found"}))
        return 1

    cache_data = cache_load(phase_dir)
    entries = cache_data.get("entries") or {}
    if not entries:
        print(json.dumps({"error": "FIXTURES-CACHE.json has no captured entries",
                            "phase": args.phase}))
        return 1

    targets: list[tuple[str, Path]] = []
    if args.sweep:
        sweep_dir = Path(args.sweep).resolve()
        targets = find_specs_for_phase(sweep_dir, args.phase)
    else:
        targets = [(args.goal, Path(args.spec).resolve())]

    injected: list[dict] = []
    skipped: list[dict] = []
    errors: list[dict] = []

    for goal_id, spec_path in targets:
        entry = entries.get(goal_id) or {}
        captured = entry.get("captured")
        if not captured:
            skipped.append({
                "goal": goal_id,
                "spec": str(spec_path),
                "reason": "no captured store in FIXTURES-CACHE",
            })
            continue
        if not spec_path.exists():
            errors.append({
                "goal": goal_id,
                "spec": str(spec_path),
                "error": "spec file not found",
            })
            continue
        block = render_block(captured, goal_id=goal_id, phase=args.phase)
        if args.dry_run:
            injected.append({
                "goal": goal_id,
                "spec": str(spec_path),
                "action": "dry-run",
                "captured_keys": list(captured.keys()),
            })
            continue
        try:
            action = inject_into_spec(spec_path, block)
            injected.append({
                "goal": goal_id,
                "spec": str(spec_path),
                "action": action,
                "captured_keys": list(captured.keys()),
            })
        except OSError as e:
            errors.append({"goal": goal_id, "spec": str(spec_path),
                            "error": str(e)})

    print(json.dumps({
        "phase": args.phase,
        "injected": injected,
        "skipped": skipped,
        "errors": errors,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
