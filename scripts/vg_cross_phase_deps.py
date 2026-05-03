#!/usr/bin/env python3
"""
vg_cross_phase_deps.py — Cross-Phase Dependencies Aggregator (v1.14.0+ A.4)

Theo dõi goals DEFERRED (hoãn lại chờ phase khác) qua file `.vg/CROSS-PHASE-DEPS.md`.

Commands:
  append {source_phase}     — scan GOAL-COVERAGE-MATRIX.md cho DEFERRED rows,
                               append (idempotent) vào aggregator.
  flip {accepting_phase}    — khi phase X được accept, update Flipped At cho
                               mọi row có Depends On == X và chưa flipped.
  check-dependents {phase}  — in ra source phases đang chờ phase này; exit 0 nếu
                               không có, exit 1 nếu có (dùng ở /vg:accept).
  check-milestone-complete  — in ra rows chưa flipped (Flipped At == null);
                               exit 0 nếu 0 rows, exit 1 nếu còn rows.
  list                      — show toàn bộ bảng.

Idempotent — chạy nhiều lần không trùng row.

Format:
    # Cross-Phase Dependencies
    ...
    | Source Phase | Goal ID | Goal Text | Depends On | Added At | Flipped At |
    |---|---|---|---|---|---|
    | 7.10 | G-05 | Analytics shows ... | 7.12 | 2026-04-18T... | null |
"""
from __future__ import annotations

import sys
import re
import argparse
from datetime import datetime, timezone
from pathlib import Path

# UTF-8 stdout (Windows cp1258 defend)
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

DEPS_FILE = Path(".vg/CROSS-PHASE-DEPS.md")
PHASES_ROOT = Path(".vg/phases")

HEADER = """# Cross-Phase Dependencies

Phase → phase dependencies tracked at scope time (`depends_on_phase: X` tag).
Mỗi row = 1 goal bị hoãn (DEFERRED) vì chờ phase khác ship trước.

Write triggers:
- `/vg:review` pass: scan GOAL-COVERAGE-MATRIX.md cho DEFERRED rows → append.
- `/vg:accept X`: flip "Flipped At" cho mọi row `Depends On == X` khi X được accept.
- `/vg:complete-milestone`: BLOCK nếu còn row nào `Flipped At == null`.

| Source Phase | Goal ID | Goal Text | Depends On | Added At | Flipped At |
|---|---|---|---|---|---|
"""


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def read_deps() -> tuple[str, list[dict]]:
    """Đọc file aggregator, trả về (header_block, rows_list)."""
    if not DEPS_FILE.exists():
        return HEADER, []
    text = DEPS_FILE.read_text(encoding="utf-8")
    rows = []
    # Parse table rows: | src | gid | text | dep | added | flipped |
    for line in text.splitlines():
        m = re.match(r"^\|\s*([^|]+?)\s*\|\s*(G-[\w.-]+)\s*\|\s*(.+?)\s*\|\s*([\w.-]+)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*$", line)
        if not m:
            continue
        src, gid, txt, dep, added, flipped = m.groups()
        if src.strip().lower() == "source phase":
            continue  # header
        rows.append({
            "source": src.strip(),
            "goal_id": gid.strip(),
            "goal_text": txt.strip(),
            "depends_on": dep.strip(),
            "added_at": added.strip(),
            "flipped_at": flipped.strip(),
        })
    return HEADER, rows


def write_deps(rows: list[dict]) -> None:
    DEPS_FILE.parent.mkdir(parents=True, exist_ok=True)
    lines = [HEADER]
    for r in rows:
        lines.append(
            f"| {r['source']} | {r['goal_id']} | {r['goal_text']} | {r['depends_on']} "
            f"| {r['added_at']} | {r['flipped_at']} |"
        )
    lines.append("")
    DEPS_FILE.write_text("\n".join(lines), encoding="utf-8")


def parse_matrix_deferred(phase_dir: Path) -> list[dict]:
    """Extract DEFERRED goals từ GOAL-COVERAGE-MATRIX.md của 1 phase.

    Status cell format: `| G-XX | priority | surface | DEFERRED | evidence (depends_on_phase: X.Y) |`
    """
    matrix = phase_dir / "GOAL-COVERAGE-MATRIX.md"
    if not matrix.exists():
        return []
    text = matrix.read_text(encoding="utf-8")
    # Chỉ parse section ## Goal Details
    m = re.search(r"^## Goal Details\s*\n(.*?)(?=^\s*## |\Z)", text, re.M | re.S)
    if not m:
        return []
    body = m.group(1)

    # Đọc TEST-GOALS.md để lấy goal text đầy đủ
    goals_txt = phase_dir / "TEST-GOALS.md"
    goal_titles = {}
    if goals_txt.exists():
        tg = goals_txt.read_text(encoding="utf-8")
        for gm in re.finditer(r"^## Goal (G-[\w.-]+)\s*:\s*(.+)$", tg, re.M):
            goal_titles[gm.group(1)] = gm.group(2).strip()

    rows = []
    for line in body.splitlines():
        if "DEFERRED" not in line:
            continue
        # Match pattern: `| G-XX | priority | surface | DEFERRED | evidence (depends_on_phase: X.Y) |`
        m2 = re.match(r"^\|\s*(G-[\w.-]+)\s*\|[^|]*\|[^|]*\|\s*DEFERRED\s*\|(.+?)\|\s*$", line)
        if not m2:
            continue
        gid = m2.group(1)
        evidence = m2.group(2).strip()
        # Parse `depends_on_phase: X.Y` from evidence cell
        dep_match = re.search(r"depends_on_phase\s*:\s*([\w.-]+)", evidence)
        if not dep_match:
            continue  # DEFERRED cần có target phase mới ghi aggregator
        dep = dep_match.group(1)
        title = goal_titles.get(gid, "(no title)")
        rows.append({
            "goal_id": gid,
            "goal_text": title[:80],   # cắt để giữ 1 line
            "depends_on": dep,
        })
    return rows


def cmd_append(source_phase: str) -> int:
    """Scan source_phase's matrix for DEFERRED + append idempotently."""
    phase_dir = PHASES_ROOT / source_phase
    if not phase_dir.exists():
        # Try glob with prefix (e.g., "7.10" matches "07.10-name/")
        candidates = list(PHASES_ROOT.glob(f"{source_phase}*"))
        if not candidates:
            candidates = list(PHASES_ROOT.glob(f"0{source_phase}*"))
        if not candidates:
            print(f"⛔ Không tìm thấy phase dir cho '{source_phase}'")
            return 1
        phase_dir = candidates[0]

    # Normalize source phase ID (strip directory prefix + suffix)
    src_id = phase_dir.name
    src_id = re.sub(r"^0", "", src_id)          # 07.10-name → 7.10-name
    src_id = re.sub(r"-.*$", "", src_id)         # 7.10-name → 7.10

    new_rows = parse_matrix_deferred(phase_dir)
    if not new_rows:
        print(f"ℹ Phase {src_id}: không có goal DEFERRED — bỏ qua append.")
        return 0

    _, existing = read_deps()
    existing_keys = {(r["source"], r["goal_id"]) for r in existing}

    appended = 0
    for nr in new_rows:
        key = (src_id, nr["goal_id"])
        if key in existing_keys:
            continue  # idempotent
        existing.append({
            "source":     src_id,
            "goal_id":    nr["goal_id"],
            "goal_text":  nr["goal_text"],
            "depends_on": nr["depends_on"],
            "added_at":   iso_now(),
            "flipped_at": "null",
        })
        appended += 1

    if appended:
        write_deps(existing)
        print(f"✓ Appended {appended} DEFERRED entries cho phase {src_id} → {DEPS_FILE}")
    else:
        print(f"ℹ Phase {src_id}: {len(new_rows)} DEFERRED goals đã có sẵn — không duplicate.")
    return 0


def cmd_flip(accepting_phase: str) -> int:
    """Khi phase X accept, flip mọi row `Depends On == X` chưa flipped."""
    _, rows = read_deps()
    now = iso_now()
    flipped = 0
    for r in rows:
        if r["depends_on"] == accepting_phase and r["flipped_at"] == "null":
            r["flipped_at"] = now
            flipped += 1
    if flipped:
        write_deps(rows)
        print(f"✓ Flipped {flipped} rows (Depends On == {accepting_phase}) tại {now}")
        # Suggest re-verify for affected source phases
        affected = sorted({r["source"] for r in rows
                          if r["depends_on"] == accepting_phase and r["flipped_at"] == now})
        for src in affected:
            print(f"  → Gợi ý re-verify: /vg:review {src} --reverify-deferred")
    else:
        print(f"ℹ Không có row nào chờ phase {accepting_phase} — skip flip.")
    return 0


def cmd_check_dependents(accepting_phase: str) -> int:
    """Return non-zero nếu có source phase chờ accepting_phase flip."""
    _, rows = read_deps()
    pending = [r for r in rows
               if r["depends_on"] == accepting_phase and r["flipped_at"] == "null"]
    if not pending:
        print(f"✓ Không source phase nào đang chờ phase {accepting_phase}.")
        return 0
    print(f"\033[33m{len(pending)} goals chờ phase {accepting_phase} ship:\033[0m")
    sources = sorted({r["source"] for r in pending})
    for src in sources:
        gids = [r["goal_id"] for r in pending if r["source"] == src]
        print(f"  • Phase {src}: goals {', '.join(gids)}")
        print(f"    → /vg:review {src} --reverify-deferred (sau khi phase {accepting_phase} accept)")
    return 1


def cmd_check_milestone_complete() -> int:
    """Return non-zero nếu còn row chưa flipped (milestone-complete gate)."""
    _, rows = read_deps()
    pending = [r for r in rows if r["flipped_at"] == "null"]
    if not pending:
        print(f"✓ Tất cả DEFERRED deps đã flipped — milestone có thể complete.")
        return 0
    print(f"\033[38;5;208mCòn {len(pending)} cross-phase dependencies chưa flipped:\033[0m")
    for r in pending:
        print(f"  • Phase {r['source']} goal {r['goal_id']} chờ phase {r['depends_on']} "
              f"(added {r['added_at']})")
    print(f"\nMilestone không thể complete đến khi mọi dependency flipped.")
    return 1


def cmd_list() -> int:
    _, rows = read_deps()
    if not rows:
        print("ℹ CROSS-PHASE-DEPS.md trống — chưa có goal DEFERRED nào.")
        return 0
    print(f"Cross-Phase Dependencies — {len(rows)} rows\n")
    print(f"{'Source':<10} {'Goal':<8} {'Depends':<10} {'Flipped':<12} Text")
    print(f"{'-'*10} {'-'*8} {'-'*10} {'-'*12} {'-'*40}")
    for r in rows:
        status = "✓" if r["flipped_at"] != "null" else "…"
        print(f"{r['source']:<10} {r['goal_id']:<8} {r['depends_on']:<10} "
              f"{status:<12} {r['goal_text'][:50]}")
    return 0


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="Cross-phase dependencies aggregator")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("append", help="Scan phase's matrix for DEFERRED goals + append")
    a.add_argument("source_phase", help="Source phase ID (e.g., 7.10)")

    f = sub.add_parser("flip", help="Flip Flipped At for rows Depends On == phase")
    f.add_argument("accepting_phase", help="Accepting phase ID (e.g., 7.12)")

    cd = sub.add_parser("check-dependents", help="Check if any phase awaits this one")
    cd.add_argument("accepting_phase", help="Phase ID being accepted")

    sub.add_parser("check-milestone-complete", help="Gate: all deps flipped?")
    sub.add_parser("list", help="Show all tracked dependencies")

    args = p.parse_args(argv)

    if args.cmd == "append":
        return cmd_append(args.source_phase)
    if args.cmd == "flip":
        return cmd_flip(args.accepting_phase)
    if args.cmd == "check-dependents":
        return cmd_check_dependents(args.accepting_phase)
    if args.cmd == "check-milestone-complete":
        return cmd_check_milestone_complete()
    if args.cmd == "list":
        return cmd_list()
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
