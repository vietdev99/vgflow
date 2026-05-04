#!/usr/bin/env python3
"""
verify-ui-structure.py — so sánh cây component thực tế vs kế hoạch.

CÔNG CỤ: Gate (cổng chặn) sau khi executor xây xong phase UI. Nhận 2 cây JSON:
  - expected: cây kế hoạch do planner viết trong UI-MAP.md (file markdown,
    script extract code block JSON từ đó)
  - actual: cây thực tế do generate-ui-map.mjs quét từ code vừa viết

PHÂN LOẠI LỆCH (drift):
  - MISSING: component xuất hiện trong expected nhưng không có trong actual
             → executor quên thực hiện
  - UNEXPECTED: component xuất hiện trong actual nhưng không có trong expected
                → executor tự thêm ngoài kế hoạch
  - LAYOUT_SHIFT: cùng component nhưng class layout khác (flex vs grid...)
                  → có thể cố ý, có thể bug
  - STRUCTURE_SHIFT: thứ tự children thay đổi
                     → thường cosmetic, warn only

EXIT:
  0 — không lệch quá ngưỡng cho phép
  2 — BLOCK (vượt ngưỡng MISSING/UNEXPECTED)
  1 — lỗi script (không đọc được file...)

PHASE 15 EXTENSIONS (D-03 + D-12b wave-scoped, D-08 profile threshold):
  --scope owner-wave-id=<id>   Filter expected tree to nodes whose
                               `owner_wave_id` (or ancestor's) matches <id>.
                               Use cho per-wave drift gate trong /vg:build
                               post-wave-commit hook. Implements D-03/D-12b
                               option C (scoped subtree) — only check what
                               wave declared touch, không alarm phần khác.
  --phase <id>                 Resolve drift thresholds via threshold-resolver
                               (lib/threshold-resolver.py, D-08): override >
                               profile (prototype 0.7 / default 0.85 /
                               production 0.95) > hard fallback. Computed
                               threshold maps to max-missing/max-unexpected.

USAGE:
  # Legacy single-shot
  python verify-ui-structure.py \
      --expected .vg/phases/11-settings/UI-MAP.md \
      --actual .vg/phases/11-settings/.ui-map-actual.json \
      --max-missing 0 --max-unexpected 3 --layout-advisory

  # Phase 15 — wave-scoped drift, profile-aware threshold
  python verify-ui-structure.py \
      --expected .vg/phases/7.14.3/UI-MAP.md \
      --actual .vg/phases/7.14.3/.wave-1-asbuilt.json \
      --scope owner-wave-id=wave-1 \
      --phase 7.14.3
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path


def extract_json_from_markdown(md_path: Path) -> dict | None:
    """Extract first ```json code block from markdown file."""
    if not md_path.exists():
        return None
    txt = md_path.read_text(encoding="utf-8", errors="ignore")
    m = re.search(r"```json\s*\n([\s\S]*?)\n```", txt)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as e:
        print(f"\033[38;5;208mUI-MAP.md chứa JSON không hợp lệ: {e}\033[0m", file=sys.stderr)
        return None


def load_tree(path: Path) -> dict | None:
    if not path.exists():
        return None
    if path.suffix == ".md":
        return extract_json_from_markdown(path)
    txt = path.read_text(encoding="utf-8", errors="ignore")
    try:
        return json.loads(txt)
    except json.JSONDecodeError:
        return None


def flatten(node: dict, parent: str = "(root)", out: list | None = None) -> list:
    """Flatten tree to list of {name, parent, layout, file} — order-preserving."""
    if out is None:
        out = []
    entry = {
        "name": node.get("name", "?"),
        "parent": parent,
        "layout": node.get("layout") or "",
        "file": node.get("file") or "",
        "kind": node.get("kind", "component"),
    }
    out.append(entry)
    children = node.get("children") or []
    for c in children:
        flatten(c, node.get("name", "?"), out)
    return out


# ─── Phase 15 D-03/D-12b — wave-scoped subtree filter ─────────────────────

def filter_subtree_by_wave(node: dict, target_wave: str,
                           ancestor_owns: bool = False) -> dict | None:
    """Return a copy of `node` containing only nodes whose owner_wave_id (or
    an ancestor's) equals `target_wave`. Returns None if neither node nor any
    descendant belongs to the target wave.

    Convention (per D-12a/b): planner tags nodes with `owner_wave_id` in
    UI-MAP.md when the wave is responsible for building/touching them.
    Children inherit ownership unless they override with their own
    owner_wave_id.
    """
    node_owns = node.get("owner_wave_id") == target_wave
    inherits = ancestor_owns and "owner_wave_id" not in node
    in_scope = node_owns or inherits

    children = node.get("children") or []
    kept_children = []
    for c in children:
        # If this node is in scope, descendants inherit (unless overridden).
        # If not, descendants check independently (handles sparse tagging).
        kc = filter_subtree_by_wave(c, target_wave, ancestor_owns=in_scope)
        if kc is not None:
            kept_children.append(kc)

    if not in_scope and not kept_children:
        return None

    out = {k: v for k, v in node.items() if k != "children"}
    out["children"] = kept_children
    return out


def _parse_scope_arg(scope: str) -> tuple[str, str] | None:
    """Parse `--scope owner-wave-id=<id>` → ('owner_wave_id', '<id>')."""
    if not scope:
        return None
    if "=" not in scope:
        return None
    key_raw, value = scope.split("=", 1)
    key = key_raw.strip().replace("-", "_")
    return key, value.strip()


def _resolve_threshold_for_phase(phase: str | None) -> float | None:
    """Call threshold-resolver helper if --phase given. Returns float or None."""
    if not phase:
        return None
    repo = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
    candidates = [
        Path(__file__).parent / "lib" / "threshold-resolver.py",
        repo / "scripts" / "lib" / "threshold-resolver.py",
        repo / ".claude" / "scripts" / "lib" / "threshold-resolver.py",
    ]
    helper = next((c for c in candidates if c.exists()), None)
    if helper is None:
        return None
    try:
        import subprocess
        r = subprocess.run(
            [sys.executable, str(helper), "--phase", phase],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0:
            return float(r.stdout.strip())
    except (subprocess.TimeoutExpired, ValueError):
        pass
    return None


def compare(expected: dict, actual: dict, layout_advisory: bool) -> dict:
    exp_flat = flatten(expected)
    act_flat = flatten(actual)

    # Build (name, parent) → layout map for each side
    exp_map = {(e["name"], e["parent"]): e["layout"] for e in exp_flat if e["kind"] == "component"}
    act_map = {(e["name"], e["parent"]): e["layout"] for e in act_flat if e["kind"] == "component"}

    missing = []
    unexpected = []
    layout_shift = []

    # MISSING: trong expected nhưng không trong actual
    for key, exp_layout in exp_map.items():
        if key not in act_map:
            missing.append({"name": key[0], "parent": key[1], "expected_layout": exp_layout})

    # UNEXPECTED: trong actual nhưng không trong expected
    for key, act_layout in act_map.items():
        if key not in exp_map:
            unexpected.append({"name": key[0], "parent": key[1], "actual_layout": act_layout})

    # LAYOUT_SHIFT: cùng (name, parent) nhưng layout khác
    for key, exp_layout in exp_map.items():
        if key in act_map and exp_layout != act_map[key]:
            # Chỉ flag nếu expected có layout (planner viết rõ) và khác
            if exp_layout.strip():
                layout_shift.append({
                    "name": key[0],
                    "parent": key[1],
                    "expected_layout": exp_layout,
                    "actual_layout": act_map[key],
                })

    return {
        "summary": {
            "expected_components": len(exp_map),
            "actual_components": len(act_map),
            "missing": len(missing),
            "unexpected": len(unexpected),
            "layout_shift": len(layout_shift),
        },
        "missing": missing,
        "unexpected": unexpected,
        "layout_shift": layout_shift,
    }


def print_report(diff: dict, thresholds: dict) -> None:
    s = diff["summary"]
    print("# UI Structure Drift Report\n")
    print(f"**Expected components:** {s['expected_components']}")
    print(f"**Actual components:** {s['actual_components']}")
    print(f"**MISSING (thiếu):** {s['missing']} (ngưỡng: {thresholds['max_missing']})")
    print(f"**UNEXPECTED (dư thừa):** {s['unexpected']} (ngưỡng: {thresholds['max_unexpected']})")
    print(f"**LAYOUT_SHIFT (lệch bố cục):** {s['layout_shift']} ({'advisory' if thresholds['layout_advisory'] else 'block'})\n")

    if diff["missing"]:
        print("## ⛔ MISSING — các component kế hoạch có nhưng code không có\n")
        for m in diff["missing"]:
            print(f"- `{m['name']}` dưới `{m['parent']}` (layout kế hoạch: {m['expected_layout'] or '—'})")
        print()

    if diff["unexpected"]:
        print("## ⚠ UNEXPECTED — code có thêm component ngoài kế hoạch\n")
        for u in diff["unexpected"]:
            print(f"- `{u['name']}` dưới `{u['parent']}` (layout thực tế: {u['actual_layout'] or '—'})")
        print()

    if diff["layout_shift"]:
        print("## ⚠ LAYOUT_SHIFT — bố cục khác kế hoạch\n")
        for l in diff["layout_shift"]:
            print(f"- `{l['name']}` dưới `{l['parent']}`")
            print(f"    kế hoạch: `{l['expected_layout']}`")
            print(f"    thực tế:  `{l['actual_layout']}`")
        print()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--expected", required=True, help="Path tới UI-MAP.md (kế hoạch) hoặc .json")
    ap.add_argument("--actual", required=True, help="Path tới cây thực tế (.json)")
    ap.add_argument("--max-missing", type=int, default=0, help="Số MISSING tối đa cho phép (default 0)")
    ap.add_argument("--max-unexpected", type=int, default=0, help="Số UNEXPECTED tối đa cho phép (default 0)")
    ap.add_argument("--layout-advisory", action="store_true", help="LAYOUT_SHIFT chỉ cảnh báo, không BLOCK")
    ap.add_argument("--json", action="store_true", help="In report dạng JSON")
    # Phase 15 D-03/D-12b — wave-scoped subtree
    ap.add_argument("--scope", help="Filter expected tree to subtree owned by wave (e.g. 'owner-wave-id=wave-1')")
    # Phase 15 D-08 — profile-aware threshold
    ap.add_argument("--phase", help="Resolve drift threshold via threshold-resolver (D-08 profile)")
    args = ap.parse_args()

    expected = load_tree(Path(args.expected))
    actual = load_tree(Path(args.actual))

    if expected is None:
        print(f"\033[38;5;208mKhông đọc được cây kế hoạch: {args.expected}\033[0m", file=sys.stderr)
        print("   File phải là JSON trực tiếp hoặc markdown có ```json``` code block.", file=sys.stderr)
        return 1
    if actual is None:
        print(f"\033[38;5;208mKhông đọc được cây thực tế: {args.actual}\033[0m", file=sys.stderr)
        print("   Sinh bằng: node .claude/scripts/generate-ui-map.mjs --format json --output <path>", file=sys.stderr)
        return 1

    # Phase 15 D-03/D-12b — apply wave-scoped subtree filter to expected
    if args.scope:
        parsed = _parse_scope_arg(args.scope)
        if parsed is None:
            print(f"⛔ --scope arg malformed: {args.scope!r}. Expected: 'owner-wave-id=<id>'",
                  file=sys.stderr)
            return 1
        key, value = parsed
        if key != "owner_wave_id":
            print(f"\033[38;5;208m--scope key not supported: {key!r}. Phase 15 only supports owner-wave-id.\033[0m",
                  file=sys.stderr)
            return 1
        # Use the embedded JSON code block "root" if present (Phase 15 ui-map.v1.json)
        # OR fall back to the whole tree (legacy nesting).
        scope_root = expected.get("root", expected)
        filtered = filter_subtree_by_wave(scope_root, value)
        if filtered is None:
            print(f"\033[33mWave-scoped filter: no nodes own owner_wave_id={value!r} in expected tree. \033[0m"
                  "Nothing to verify for this wave (PASS).", file=sys.stderr)
            return 0
        # Wrap back into expected shape (preserves any non-root metadata)
        if "root" in expected:
            expected = {**expected, "root": filtered}
        else:
            expected = filtered
        print(f"ℹ Phase 15 wave-scope: filtered expected to subtree owner_wave_id={value!r}",
              file=sys.stderr)

    # Phase 15 D-08 — profile-aware threshold resolution
    # Map fidelity threshold (0.0-1.0) → max-missing/max-unexpected counts.
    # Strategy: shorter list → stricter ratio. We compute count from total
    # expected components: max_drift = (1 - fidelity) * total. Split half each.
    resolved = _resolve_threshold_for_phase(args.phase)
    if resolved is not None:
        # Compute how many components in scope
        from copy import deepcopy
        scope_root_for_count = expected.get("root", expected) if isinstance(expected, dict) else expected
        flat = flatten(scope_root_for_count) if scope_root_for_count else []
        total_components = max(1, sum(1 for f in flat if f.get("kind", "component") == "component"))
        max_drift = int(round((1.0 - resolved) * total_components))
        # Split equally; round up to ensure at least 1 each
        per_bucket = max(1, max_drift // 2) if max_drift > 0 else 0
        if max_drift > 0:
            args.max_missing = per_bucket
            args.max_unexpected = max_drift - per_bucket if max_drift > per_bucket else per_bucket
        else:
            args.max_missing = 0
            args.max_unexpected = 0
        print(f"ℹ Phase 15 D-08 threshold: phase={args.phase} fidelity={resolved} "
              f"→ max_missing={args.max_missing} max_unexpected={args.max_unexpected} "
              f"(of {total_components} components in scope)", file=sys.stderr)

    diff = compare(expected, actual, args.layout_advisory)

    thresholds = {
        "max_missing": args.max_missing,
        "max_unexpected": args.max_unexpected,
        "layout_advisory": args.layout_advisory,
    }

    if args.json:
        print(json.dumps(diff, indent=2, ensure_ascii=False))
    else:
        print_report(diff, thresholds)

    # Exit policy
    s = diff["summary"]
    over_missing = s["missing"] > args.max_missing
    over_unexpected = s["unexpected"] > args.max_unexpected
    over_layout = s["layout_shift"] > 0 and not args.layout_advisory

    if over_missing or over_unexpected or over_layout:
        if not args.json:
            print("\n⛔ BLOCK: cấu trúc UI lệch so với kế hoạch.", file=sys.stderr)
            if over_missing:
                print(f"   MISSING {s['missing']} > ngưỡng {args.max_missing}", file=sys.stderr)
            if over_unexpected:
                print(f"   UNEXPECTED {s['unexpected']} > ngưỡng {args.max_unexpected}", file=sys.stderr)
            if over_layout:
                print(f"   LAYOUT_SHIFT {s['layout_shift']} > 0 (không advisory)", file=sys.stderr)
            print("   Fix: sửa code để khớp UI-MAP.md, HOẶC cập nhật UI-MAP.md nếu kế hoạch thay đổi.", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
