#!/usr/bin/env python3
"""
vg_deploy_runbook_drafter.py — auto-draft DEPLOY-RUNBOOK.md per phase (v1.14.0+ C.1)

Parse `.deploy-log.txt` + `.deploy-snapshot.txt` → DEPLOY-RUNBOOK.md.staged.

7 sections (spec C.1):
  1. Prerequisites — từ SPECS.md `Parent phase:` field + CONTEXT.md dependencies.
  2. Deploy sequence — commands grouped theo tag + timing từ log.
  3. Verification — health commands từ log + link SMOKE-PACK.md.
  4. Rollback — rollback tags từ log; stub nếu không có.
  5. Lessons — HUMAN-FILLED, placeholder với auto-detected patterns.
  6. References — placeholder; aggregator (step 8) populate.
  7. Infra snapshot — copy .deploy-snapshot.txt inline.

Output: {phase_dir}/DEPLOY-RUNBOOK.md.staged (promoted → DEPLOY-RUNBOOK.md bởi /vg:accept C.3).
Idempotent — re-run overwrite staged.
"""
from __future__ import annotations

import sys
import re
import json
import argparse
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict

# UTF-8 stdout (Windows cp1258 defense)
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_deploy_log(log_path: Path) -> list[dict]:
    """Parse `.deploy-log.txt` → list of {tag, cmd, rc, duration, stdout_tail}.

    Format each command block:
      [ISO] [TAG] BEGIN <cmd>
      [ISO] [TAG] END rc=N duration=Ns
      (optional) [ISO] [TAG] STDOUT_LAST_LINES:
                  → line1 ...
    """
    if not log_path.exists():
        return []

    text = log_path.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()

    entries = []
    pending: dict | None = None

    begin_re = re.compile(r"^\[([^\]]+)\] \[([^\]]+)\] BEGIN (.+)$")
    end_re   = re.compile(r"^\[([^\]]+)\] \[([^\]]+)\] END rc=(-?\d+) duration=(\d+)s")
    stout_re = re.compile(r"^\[([^\]]+)\] \[([^\]]+)\] STDOUT_LAST_LINES:")
    line_re  = re.compile(r"^  → (.+)$")

    collecting_stdout = False
    for line in lines:
        bm = begin_re.match(line)
        em = end_re.match(line)
        sm = stout_re.match(line)
        lm = line_re.match(line)

        if bm:
            pending = {
                "begin_ts": bm.group(1),
                "tag":      bm.group(2),
                "cmd":      bm.group(3),
                "stdout_tail": [],
            }
            collecting_stdout = False
        elif em and pending:
            pending["end_ts"]   = em.group(1)
            pending["rc"]       = int(em.group(3))
            pending["duration"] = int(em.group(4))
            # Keep pending — STDOUT_LAST_LINES may follow
        elif sm and pending:
            collecting_stdout = True
        elif lm and pending and collecting_stdout:
            pending["stdout_tail"].append(lm.group(1))
        elif pending and "rc" in pending and not (bm or lm):
            # Next non-stdout line — commit pending
            entries.append(pending)
            pending = None
            collecting_stdout = False
            if bm:
                # Re-process if we just matched a BEGIN
                pass

    # Final pending
    if pending and "rc" in pending:
        entries.append(pending)

    return entries


def parse_specs_parent_phase(phase_dir: Path) -> str | None:
    """Grep SPECS.md cho `Parent phase:` hoặc `parent_phase:`"""
    specs = phase_dir / "SPECS.md"
    if not specs.exists():
        return None
    text = specs.read_text(encoding="utf-8", errors="ignore")
    m = re.search(r"^(?:\*\*)?[Pp]arent\s*[Pp]hase:?(?:\*\*)?\s*([0-9.]+)", text, re.M)
    return m.group(1) if m else None


def detect_lessons_patterns(entries: list[dict]) -> list[str]:
    """Auto-detect patterns worth flagging for user review at /vg:accept.

    Triggers per spec C.3:
    - Timing outliers: cmd > 1.5× median cho cùng tag
    - Exit-code non-zero: cmd fail ≥ 1 lần
    - Retries: same cmd repeated
    """
    patterns = []

    # Group by tag, compute median duration per tag
    by_tag = defaultdict(list)
    for e in entries:
        by_tag[e["tag"]].append(e)

    for tag, items in by_tag.items():
        if len(items) < 2:
            continue
        durations = sorted(e["duration"] for e in items)
        median = durations[len(durations) // 2] if durations else 0
        if median == 0:
            continue
        for e in items:
            if e["duration"] > median * 1.5:
                patterns.append(
                    f"⚠ [{tag}] `{e['cmd'][:60]}...` chạy {e['duration']}s "
                    f"(median {median}s — chậm 1.5×). Xem cause."
                )

    # Non-zero exit codes
    for e in entries:
        if e.get("rc", 0) != 0:
            patterns.append(
                f"⚠ [{e['tag']}] rc={e['rc']} — `{e['cmd'][:60]}...`. "
                f"Root cause + fix dùng sau?"
            )

    # Duplicate commands = retry signal
    cmd_counts = defaultdict(int)
    for e in entries:
        cmd_counts[e["cmd"]] += 1
    for cmd, cnt in cmd_counts.items():
        if cnt > 1:
            patterns.append(
                f"⚠ Lệnh chạy {cnt} lần: `{cmd[:60]}...` — retry hay pattern khác?"
            )

    return patterns


def section_1_prerequisites(phase_dir: Path) -> list[str]:
    """Section 1: Prerequisites."""
    parent = parse_specs_parent_phase(phase_dir)
    lines = ["## 1. Prerequisites (Điều kiện tiên quyết)", ""]

    if parent:
        lines.append(f"- Phase phụ thuộc: **{parent}** — phải deployed + accepted trước khi deploy phase này.")

    # Infra deps from CONTEXT.md (optional parse)
    ctx = phase_dir / "CONTEXT.md"
    if ctx.exists():
        text = ctx.read_text(encoding="utf-8", errors="ignore")
        infra_match = re.search(r"(?:Infra|Dependencies)[:\s]*\n((?:\s*-\s*.+\n)+)", text)
        if infra_match:
            lines.append("- Hạ tầng cần chạy trước:")
            for m in re.finditer(r"^\s*-\s*(.+)$", infra_match.group(1), re.M):
                lines.append(f"  - {m.group(1)}")

    if len(lines) == 2:
        lines.append("- (Không tìm được parent phase hay infra deps từ SPECS/CONTEXT — user bổ sung nếu cần.)")

    lines.append("")
    return lines


def section_2_deploy_sequence(entries: list[dict]) -> list[str]:
    """Section 2: Deploy sequence từ log."""
    lines = ["## 2. Deploy sequence (Trình tự triển khai)", ""]

    if not entries:
        lines.extend([
            "_(Không có `.deploy-log.txt` — phase này chưa chạy qua `--sandbox` mode với deploy-logging bật.)_",
            "",
        ])
        return lines

    lines.append("Commands tự động từ `.deploy-log.txt` (theo thứ tự):")
    lines.append("")
    lines.append("| # | Tag | Lệnh | Duration | rc |")
    lines.append("|---|-----|------|----------|-----|")

    for i, e in enumerate(entries, 1):
        cmd_disp = e["cmd"].replace("|", "\\|")
        if len(cmd_disp) > 80:
            cmd_disp = cmd_disp[:77] + "..."
        rc_disp = "✅ 0" if e["rc"] == 0 else f"⛔ {e['rc']}"
        lines.append(f"| {i} | {e['tag']} | `{cmd_disp}` | {e['duration']}s | {rc_disp} |")

    lines.append("")
    lines.append("**Copy-paste block (chạy lại đầy đủ):**")
    lines.append("")
    lines.append("```bash")
    for e in entries:
        if e["rc"] == 0:  # Chỉ include lệnh thành công
            lines.append(e["cmd"])
    lines.append("```")
    lines.append("")
    return lines


def section_3_verification(entries: list[dict]) -> list[str]:
    """Section 3: Verification — health tags + SMOKE-PACK reference."""
    lines = ["## 3. Verification (Kiểm tra sau triển khai)", ""]

    health_entries = [e for e in entries if e["tag"] == "health" or "health" in e["cmd"].lower()]

    if health_entries:
        lines.append("Smoke checks đã chạy tại lần deploy này:")
        lines.append("")
        lines.append("```bash")
        for e in health_entries:
            lines.append(f"# Expected rc={e['rc']} ({e['duration']}s)")
            lines.append(e["cmd"])
        lines.append("```")
    else:
        lines.append("_(Không có tag `health` trong log — thêm smoke checks khi wire `deploy_exec` trong build/test sandbox.)_")

    lines.append("")
    lines.append("**Reference:** Xem `.vg/SMOKE-PACK.md` (aggregator step 9) để có bộ smoke snippet đầy đủ cho mọi service.")
    lines.append("")
    return lines


def section_4_rollback(entries: list[dict]) -> list[str]:
    """Section 4: Rollback."""
    lines = ["## 4. Rollback (Khôi phục)", ""]

    rollback_entries = [e for e in entries if e["tag"] == "rollback" or "rollback" in e["cmd"].lower() or "revert" in e["cmd"].lower()]

    if rollback_entries:
        lines.append("Rollback commands đã dùng:")
        lines.append("")
        lines.append("```bash")
        for e in rollback_entries:
            lines.append(e["cmd"])
        lines.append("```")
    else:
        lines.append("_(Deploy này không có rollback. User điền recovery path cụ thể nếu cần:)_")
        lines.append("")
        lines.append("```bash")
        lines.append("# VD thường dùng:")
        lines.append("# ssh vollx 'pm2 stop <service> && git -C /home/vollx/vollxssp revert <sha> && pm2 restart <service>'")
        lines.append("# Hoặc: restore DB backup nếu có migration")
        lines.append("```")

    lines.append("")
    return lines


def section_5_lessons(patterns: list[str]) -> list[str]:
    """Section 5: Lessons — auto-detected patterns + placeholder."""
    lines = ["## 5. Lessons (Bài học)", ""]
    lines.append("<!-- LESSONS_USER_INPUT_PENDING -->")
    lines.append("")
    lines.append("### Auto-detected patterns (từ parser .deploy-log.txt)")
    lines.append("")

    if patterns:
        for p in patterns:
            lines.append(f"- {p}")
    else:
        lines.append("_(Không có pattern nào bị flag — timing đều, không fail, không retry.)_")

    lines.append("")
    lines.append("### User-filled (điền ở /vg:accept)")
    lines.append("")
    lines.append("_Người deploy ghi pitfalls, timing surprise, fix cần nhớ cho phase sau. Trống = user đã skip ở accept; auto-patterns vẫn có giá trị cho aggregator._")
    lines.append("")
    return lines


def section_6_references() -> list[str]:
    """Section 6: References — aggregator populate."""
    return [
        "## 6. References (Tham chiếu)",
        "",
        "_(Section này do `vg_deploy_aggregator.py` (step 8) populate tự động: liệt kê phase RUNBOOK khác động tới cùng service.)_",
        "",
    ]


def section_7_infra_snapshot(phase_dir: Path) -> list[str]:
    """Section 7: Infra state snapshot (từ .deploy-snapshot.txt)."""
    lines = ["## 7. Infra state snapshot (Trạng thái hạ tầng lúc deploy)", ""]

    snapshot = phase_dir / ".deploy-snapshot.txt"
    if not snapshot.exists():
        lines.append("_(Chưa có `.deploy-snapshot.txt` — snapshot chưa chạy. Gọi `deploy_log_snapshot` sau deploy thành công.)_")
        lines.append("")
        return lines

    lines.append("```")
    lines.append(snapshot.read_text(encoding="utf-8", errors="ignore").rstrip())
    lines.append("```")
    lines.append("")
    return lines


def draft_runbook(phase_dir: Path) -> Path:
    """Main: parse log + snapshot, write RUNBOOK.md.staged."""
    log_path = phase_dir / ".deploy-log.txt"
    entries = parse_deploy_log(log_path)
    patterns = detect_lessons_patterns(entries)

    phase_name = phase_dir.name
    out = []
    out.append(f"# Deploy Runbook — Phase {phase_name}")
    out.append("")
    out.append(f"**Generated:** {iso_now()}")
    out.append(f"**Source:** `.deploy-log.txt` ({len(entries)} commands) + `.deploy-snapshot.txt`")
    out.append(f"**Status:** STAGED (promoted to canonical bởi `/vg:accept {phase_name}`)")
    out.append("")
    out.append("_7 sections: Prerequisites / Deploy sequence / Verification / Rollback / Lessons / References / Infra snapshot._")
    out.append("")
    out.append("---")
    out.append("")

    out.extend(section_1_prerequisites(phase_dir))
    out.extend(section_2_deploy_sequence(entries))
    out.extend(section_3_verification(entries))
    out.extend(section_4_rollback(entries))
    out.extend(section_5_lessons(patterns))
    out.extend(section_6_references())
    out.extend(section_7_infra_snapshot(phase_dir))

    staged = phase_dir / "DEPLOY-RUNBOOK.md.staged"
    staged.write_text("\n".join(out), encoding="utf-8")

    return staged


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="Draft DEPLOY-RUNBOOK.md từ deploy log")
    p.add_argument("phase_dir", help="Path to phase dir (e.g., .vg/phases/07.12-conversion-tracking-pixel)")
    p.add_argument("--print", action="store_true", help="Print staged path after write")
    args = p.parse_args(argv)

    phase_dir = Path(args.phase_dir)
    if not phase_dir.exists():
        print(f"⛔ Phase dir không tồn tại: {phase_dir}")
        return 1

    staged = draft_runbook(phase_dir)
    print(f"✓ Staged RUNBOOK: {staged}")
    print(f"   Promote tại /vg:accept: mv '{staged}' '{staged.with_suffix('')}'")

    # Quick summary
    log = phase_dir / ".deploy-log.txt"
    if log.exists():
        n = len(parse_deploy_log(log))
        print(f"   Parsed {n} commands từ .deploy-log.txt")
    else:
        print(f"   ⚠ .deploy-log.txt không tồn tại — sections 2-4 sẽ trống")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
