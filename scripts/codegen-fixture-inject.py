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


def _is_safe_to_substitute(value: str) -> bool:
    """A captured STRING value qualifies for body substitution only when
    it's distinctive enough that an exact-string match in the spec body
    is overwhelmingly likely to be the captured value, not a coincidence.

    Codex-HIGH-3-bis safety guard:
    - Length ≥ 8 (avoids matching short tokens like 'pending').
    - OR sentinel-prefixed (VG_FIXTURE_*, *@fixture.vgflow.test).
    - UUID-like, or contains hyphens/underscores typical of identifiers.
    """
    if not isinstance(value, str) or not value:
        return False
    if "VG_FIXTURE_" in value:
        return True
    if "@fixture.vgflow.test" in value.lower():
        return True
    if len(value) < 8:
        return False
    # UUID-like (8-4-4-4-12 hex chunks) or contains digits/hyphens
    if re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", value):
        return True
    if any(c.isdigit() for c in value) and re.search(r"[-_]", value):
        return True
    if len(value) >= 16:  # very long strings unlikely to coincide
        return True
    return False


_VALID_TS_IDENT_RE = re.compile(r"^[a-zA-Z_$][\w$]*$")


def _fixture_ref(key: str) -> str:
    """Render `FIXTURE.<key>` or `FIXTURE["<key>"]` depending on whether
    `key` is a valid TS identifier (Codex-MEDIUM-2 fix)."""
    if _VALID_TS_IDENT_RE.match(key):
        return f"FIXTURE.{key}"
    # Non-identifier (hyphen, space, starts with digit, etc.) → bracket notation
    return f'FIXTURE[{json.dumps(key)}]'


def substitute_literals(text: str, captured: dict) -> tuple[str, int]:
    """Replace exact-quoted-string occurrences of captured values with
    FIXTURE.<name> (or FIXTURE["<name>"] for non-identifier keys) refs.

    Conservative: only substitutes inside quoted strings ("..." or '...'
    or `...`), never bare identifiers. Skips substitution inside the
    sentinel-bracketed FIXTURE const block itself.

    Returns (new_text, substitution_count).
    """
    # Carve out the FIXTURE const block so we don't substitute inside it
    sentinel_re = re.compile(
        re.escape(SENTINEL_OPEN) + r".*?" + re.escape(SENTINEL_CLOSE),
        re.DOTALL,
    )
    parts: list[str] = []
    last_end = 0
    fixture_blocks: list[str] = []
    for m in sentinel_re.finditer(text):
        parts.append(text[last_end:m.start()])
        fixture_blocks.append(m.group(0))
        last_end = m.end()
    parts.append(text[last_end:])

    count = 0
    new_parts: list[str] = []
    for part in parts:
        for key, value in captured.items():
            if not _is_safe_to_substitute(value):
                continue
            ref = _fixture_ref(str(key))  # Codex-MEDIUM-2: bracket if non-identifier
            # Match value inside double, single, or backtick quotes
            patterns = [
                (re.compile('"' + re.escape(value) + '"'), ref),
                (re.compile("'" + re.escape(value) + "'"), ref),
                (re.compile('`' + re.escape(value) + '`'), f'String({ref})'),
            ]
            for pat, repl in patterns:
                part, n = pat.subn(repl, part)
                count += n
        new_parts.append(part)

    # Stitch parts and untouched fixture blocks back together
    out = []
    for i, p in enumerate(new_parts):
        out.append(p)
        if i < len(fixture_blocks):
            out.append(fixture_blocks[i])
    return "".join(out), count


def inject_into_spec(
    spec_path: Path,
    block: str,
    *,
    captured: dict | None = None,
    substitute: bool = False,
) -> tuple[str, int]:
    """Idempotent inject. Returns (action, substitution_count).

    action: 'injected' | 'replaced' | 'unchanged'
    substitution_count: number of literal→FIXTURE.x replacements (0 unless substitute=True)
    """
    text = spec_path.read_text(encoding="utf-8")

    # If sentinel block already present → replace it
    pattern = re.compile(
        re.escape(SENTINEL_OPEN) + r".*?" + re.escape(SENTINEL_CLOSE) + r"\n?",
        re.DOTALL,
    )
    if pattern.search(text):
        new_text = pattern.sub(block, text)
        action = "replaced" if new_text != text else "unchanged"
    else:
        # Prepend after any leading comment/import block
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
        new_text = "".join(lines[:insert_idx] + [block + "\n"] + lines[insert_idx:])
        action = "injected"

    sub_count = 0
    if substitute and captured:
        new_text, sub_count = substitute_literals(new_text, captured)

    if new_text != text:
        spec_path.write_text(new_text, encoding="utf-8")

    return action, sub_count


def find_specs_for_phase(sweep_dir: Path, phase: str) -> list[tuple[str, Path]]:
    """Return [(goal_id, spec_path)] for all specs naming a goal under sweep_dir.

    Recognized filename patterns (case-insensitive on goal_id):
    - {anything}-{G-XX}.spec.ts                   — goal-based codegen
    - {anything}-{g-xx}.spec.ts                   — interactive codegen lowercase
    - {anything}-{G-XX}.url-state.spec.ts         — interactive subtype
    - auto-{g-xx-slug}.spec.ts                    — auto-emitted skeletons
    """
    out: list[tuple[str, Path]] = []
    if not sweep_dir.exists():
        return out
    # Codex-MEDIUM-1 fix: case-insensitive G- prefix + tolerate
    # `.url-state.spec.ts` and other suffix variants.
    pattern = re.compile(
        r"(?i)\b(G-[\w.-]+?)(?:\.url-state)?\.spec\.ts$",
    )
    for spec in sorted(sweep_dir.rglob("*.spec.ts")):
        m = pattern.search(spec.name)
        if m:
            # Normalize goal_id to canonical uppercase form so cache lookup
            # works regardless of filename casing.
            goal_id = m.group(1)
            head, _, tail = goal_id.partition("-")
            normalized = head.upper() + ("-" + tail if tail else "")
            out.append((normalized, spec))
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
    ap.add_argument("--substitute", action="store_true",
                    help="Codex-HIGH-3-bis: also substitute literal "
                         "occurrences of captured values with FIXTURE.<name>. "
                         "Conservative: only safe-distinctive strings "
                         "(sentinel-prefixed, UUID-like, or ≥16 chars).")
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
                "substitutions": 0,
            })
            continue
        try:
            action, sub_count = inject_into_spec(
                spec_path, block,
                captured=captured if args.substitute else None,
                substitute=args.substitute,
            )
            injected.append({
                "goal": goal_id,
                "spec": str(spec_path),
                "action": action,
                "captured_keys": list(captured.keys()),
                "substitutions": sub_count,
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
