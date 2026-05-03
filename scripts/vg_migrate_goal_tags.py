#!/usr/bin/env python3
"""
vg_migrate_goal_tags.py — Clone-not-modify migrator cho scope tags (v1.14.0+ spec section 9)

Scans accepted phases, clones artifacts tới `.vg/.migration-review/{phase}/` sandbox,
auto-suggests `depends_on_phase` + `verification_strategy` tags dựa heuristic.
User review bản clone; nếu đồng ý → `--apply` mới copy tag về canonical CONTEXT.md.

Nguyên tắc CLONE-NOT-MODIFY:
  - KHÔNG bao giờ edit `.vg/phases/{phase}/CONTEXT.md` canonical trực tiếp.
  - Clone vào sandbox folder riêng `.vg/.migration-review/`.
  - `--apply` chỉ chạy khi user explicit approve.

Commands:
  scan            — list phases với UAT status + migration candidates
  clone {phase}   — copy artifacts sang sandbox
  suggest {phase} — heuristic tags + unified diff output
  apply {phase}   — copy approved suggestions về canonical

Heuristic:
  - UNREACHABLE trong SANDBOX-TEST cũ + text "depends on phase X"
    → suggest `depends_on_phase: X`
  - Goal có keyword `manual|physical|external|device|fingerprint|stripe|production-only`
    → suggest `verification_strategy: manual`
  - Goal có keyword `time|ttl|expires|after.*hour|schedule`
    → suggest `verification_strategy: faketime`
  - Goal có keyword `fixture|seed|sample data|test.*mode`
    → suggest `verification_strategy: fixture`
"""
from __future__ import annotations

import sys
import re
import argparse
import shutil
from pathlib import Path
from datetime import datetime, timezone

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


VG_ROOT = Path(".vg")
PHASES_DIR = VG_ROOT / "phases"
SANDBOX_DIR = VG_ROOT / ".migration-review"

ARTIFACTS_TO_CLONE = [
    "CONTEXT.md",
    "GOAL-COVERAGE-MATRIX.md",
    "SANDBOX-TEST.md",
    "TEST-GOALS.md",
    "UAT.md",
    "SPECS.md",
]

# Heuristic patterns
CROSS_PHASE_HINTS = re.compile(r"depend(?:s|ing)?\s+on\s+phase\s+([\d.]+)", re.I)
MANUAL_KEYWORDS   = re.compile(r"\b(manual|physical|external|device|fingerprint|stripe|captcha|sms|otp|production-only|real[\s-]+payment)\b", re.I)
FAKETIME_KEYWORDS = re.compile(r"\b(time|ttl|expires?|after\s+\d+\s*hour|schedule|cron|renewal|subscription)\b", re.I)
FIXTURE_KEYWORDS  = re.compile(r"\b(fixture|seed|sample\s+data|test[_\s-]+mode|test[_\s-]+keys?|sandbox[_\s-]+key)\b", re.I)


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def phase_status(phase_dir: Path) -> str:
    """Return ACCEPTED / COMPLETE / IN_PROGRESS / UNKNOWN."""
    state = phase_dir / "PIPELINE-STATE.json"
    if state.exists():
        try:
            import json
            s = json.loads(state.read_text(encoding="utf-8"))
            status = s.get("status", "").lower()
            if status in ("complete", "accepted"):
                return "ACCEPTED"
            return status.upper() or "UNKNOWN"
        except Exception:
            return "UNKNOWN"
    uat = phase_dir / "UAT.md"
    if uat.exists():
        return "HAS_UAT"
    return "UNKNOWN"


def scan() -> int:
    if not PHASES_DIR.exists():
        print(f"\033[38;5;208mKhông tìm thấy {PHASES_DIR}\033[0m")
        return 1

    phases = sorted(p for p in PHASES_DIR.iterdir() if p.is_dir())
    print(f"{'Phase':<45} {'Status':<15} Migrate?")
    print(f"{'-'*45} {'-'*15} {'-'*10}")

    candidates = []
    for p in phases:
        status = phase_status(p)
        # Migrate candidate: ACCEPTED và CONTEXT.md không có tag yet
        migrate = "—"
        if status in ("ACCEPTED", "HAS_UAT"):
            ctx = p / "CONTEXT.md"
            if ctx.exists():
                text = ctx.read_text(encoding="utf-8", errors="ignore")
                has_tags = bool(re.search(r"^(?:\s*)(depends_on_phase|verification_strategy)\s*:",
                                          text, re.M))
                migrate = "already-tagged" if has_tags else "✓ candidate"
                if not has_tags:
                    candidates.append(p.name)
        print(f"{p.name:<45} {status:<15} {migrate}")

    print()
    print(f"Total phases: {len(phases)}, migrate candidates: {len(candidates)}")
    if candidates:
        print()
        print("Next steps:")
        print(f"  python {sys.argv[0]} clone {candidates[0]}")
        print(f"  python {sys.argv[0]} suggest {candidates[0]}")
        print(f"  # review .vg/.migration-review/{candidates[0]}/SUGGESTED-TAGS.diff")
        print(f"  python {sys.argv[0]} apply {candidates[0]}")
    return 0


def clone(phase_name: str) -> int:
    src = PHASES_DIR / phase_name
    if not src.exists():
        # Try glob
        cand = list(PHASES_DIR.glob(f"*{phase_name}*"))
        if len(cand) == 1:
            src = cand[0]
            phase_name = src.name
        else:
            print(f"\033[38;5;208mPhase không xác định: {phase_name}\033[0m")
            return 1

    dest = SANDBOX_DIR / phase_name
    dest.mkdir(parents=True, exist_ok=True)

    copied = []
    for fname in ARTIFACTS_TO_CLONE:
        s = src / fname
        if s.exists():
            shutil.copy2(s, dest / fname)
            copied.append(fname)

    # Write a README trong sandbox
    (dest / "MIGRATION-README.md").write_text(
        f"# Migration Sandbox — Phase {phase_name}\n"
        f"\n"
        f"**Created:** {iso_now()}\n"
        f"**Source:** `{src}/` (canonical, KHÔNG bị modify)\n"
        f"**Cloned artifacts:** {', '.join(copied)}\n"
        f"\n"
        f"Quy trình:\n"
        f"1. `python {sys.argv[0]} suggest {phase_name}` — auto-suggest tags, write SUGGESTED-TAGS.diff\n"
        f"2. Review diff — edit nếu muốn reject suggestion nào\n"
        f"3. `python {sys.argv[0]} apply {phase_name}` — copy tag về canonical CONTEXT.md\n"
        f"\n"
        f"Rollback: delete sandbox folder + re-run clone (canonical không bị touch).\n",
        encoding="utf-8"
    )

    print(f"✓ Cloned {len(copied)} artifacts tới {dest}")
    print(f"  Next: python {sys.argv[0]} suggest {phase_name}")
    return 0


def suggest(phase_name: str) -> int:
    sandbox = SANDBOX_DIR / phase_name
    if not sandbox.exists():
        print(f"\033[38;5;208mSandbox chưa clone: {sandbox}\033[0m")
        print(f"   Run: python {sys.argv[0]} clone {phase_name}")
        return 1

    ctx = sandbox / "CONTEXT.md"
    goals = sandbox / "TEST-GOALS.md"
    sandbox_test = sandbox / "SANDBOX-TEST.md"

    if not ctx.exists():
        print(f"\033[38;5;208mCONTEXT.md không có trong sandbox\033[0m")
        return 1

    ctx_text = ctx.read_text(encoding="utf-8", errors="ignore")
    goals_text = goals.read_text(encoding="utf-8", errors="ignore") if goals.exists() else ""
    sandbox_test_text = sandbox_test.read_text(encoding="utf-8", errors="ignore") if sandbox_test.exists() else ""

    suggestions = []

    # Extract goal blocks từ TEST-GOALS để phân loại
    goal_blocks = re.split(r"^## Goal (G-[\w.-]+)", goals_text, flags=re.M)
    # Split pattern gives: ["", "G-01", "content", "G-02", "content", ...]
    for i in range(1, len(goal_blocks), 2):
        gid = goal_blocks[i]
        body = goal_blocks[i + 1] if i + 1 < len(goal_blocks) else ""

        # Heuristic 1: cross-phase from SANDBOX-TEST hay body
        combined = body + " " + sandbox_test_text
        cm = CROSS_PHASE_HINTS.search(combined)
        if cm:
            target = cm.group(1)
            suggestions.append({
                "goal_id": gid,
                "tag": "depends_on_phase",
                "value": target,
                "reason": f"SANDBOX-TEST/goal body có 'depends on phase {target}'",
            })
            continue  # depends_on_phase overrides verification_strategy

        # Heuristic 2: manual
        if MANUAL_KEYWORDS.search(body):
            matches = MANUAL_KEYWORDS.findall(body)
            suggestions.append({
                "goal_id": gid,
                "tag": "verification_strategy",
                "value": "manual",
                "reason": f"keywords: {', '.join(set(matches[:3]))}",
            })
            continue

        # Heuristic 3: faketime
        if FAKETIME_KEYWORDS.search(body):
            matches = FAKETIME_KEYWORDS.findall(body)
            suggestions.append({
                "goal_id": gid,
                "tag": "verification_strategy",
                "value": "faketime",
                "reason": f"keywords: {', '.join(set(matches[:3]))}",
            })
            continue

        # Heuristic 4: fixture
        if FIXTURE_KEYWORDS.search(body):
            matches = FIXTURE_KEYWORDS.findall(body)
            suggestions.append({
                "goal_id": gid,
                "tag": "verification_strategy",
                "value": "fixture",
                "reason": f"keywords: {', '.join(set(matches[:3]))}",
            })

    # Write SUGGESTED-TAGS.diff (unified diff-like format với comment)
    out = [
        f"# SUGGESTED TAGS — Phase {phase_name}",
        f"# Generated: {iso_now()}",
        f"# Reviewed by: user (edit before --apply)",
        f"#",
        f"# Format: +tag: value   # reason",
        f"# Remove `+` để reject suggestion.",
        f"",
    ]

    if not suggestions:
        out.append("# No tags suggested (heuristic không match).")
        out.append("# Phase này có thể không có goals cross-phase hoặc manual/fixture/faketime.")
    else:
        by_goal = {}
        for s in suggestions:
            by_goal.setdefault(s["goal_id"], []).append(s)

        for gid in sorted(by_goal.keys()):
            out.append(f"## {gid}")
            for s in by_goal[gid]:
                out.append(f"+ {s['tag']}: {s['value']}   # {s['reason']}")
            out.append("")

    diff_path = sandbox / "SUGGESTED-TAGS.diff"
    diff_path.write_text("\n".join(out), encoding="utf-8")

    print(f"✓ {len(suggestions)} suggestions → {diff_path}")
    if suggestions:
        print(f"  Review + edit (remove `+` để reject) rồi:")
        print(f"  python {sys.argv[0]} apply {phase_name}")
    return 0


def apply(phase_name: str) -> int:
    sandbox = SANDBOX_DIR / phase_name
    diff_path = sandbox / "SUGGESTED-TAGS.diff"
    canonical_ctx = PHASES_DIR / phase_name / "CONTEXT.md"

    if not diff_path.exists():
        print(f"\033[38;5;208mSUGGESTED-TAGS.diff chưa có ở {diff_path}\033[0m")
        print(f"   Run: python {sys.argv[0]} suggest {phase_name}")
        return 1

    if not canonical_ctx.exists():
        print(f"\033[38;5;208mCanonical CONTEXT.md không tồn tại: {canonical_ctx}\033[0m")
        return 1

    # Parse approved suggestions (dòng bắt đầu bằng `+`)
    diff_text = diff_path.read_text(encoding="utf-8")
    approved = []
    current_goal = None
    for line in diff_text.splitlines():
        gm = re.match(r"^## (G-[\w.-]+)", line)
        if gm:
            current_goal = gm.group(1)
            continue
        tm = re.match(r"^\+\s+(depends_on_phase|verification_strategy)\s*:\s*(\S+)", line)
        if tm and current_goal:
            approved.append({
                "goal_id": current_goal,
                "tag": tm.group(1),
                "value": tm.group(2),
            })

    if not approved:
        print(f"ℹ Không có suggestion nào approved (0 dòng bắt đầu `+` trong diff).")
        print(f"   Edit {diff_path} — giữ lại `+` cho tag user đồng ý.")
        return 0

    # Backup canonical trước khi edit
    backup = canonical_ctx.with_suffix(f".md.pre-migration.{iso_now().replace(':','').replace('-','')}")
    shutil.copy2(canonical_ctx, backup)
    print(f"✓ Backup canonical → {backup.name}")

    # Apply: tìm goal trong CONTEXT.md, append tag dưới bullet Endpoints hoặc Test Scenarios
    ctx_text = canonical_ctx.read_text(encoding="utf-8")
    applied_count = 0

    for sug in approved:
        gid = sug["goal_id"]
        tag_line = f"  {sug['tag']}: {sug['value']}"

        # Pattern: tìm `### .*{gid}...` block, append tag trong Endpoints/Scenarios section
        # Simpler: find first `**Test Scenarios:**` hoặc `**Endpoints:**` section trong goal block
        # Nếu goal_id không ở CONTEXT.md (old format), append vào end of file với note
        if gid not in ctx_text:
            print(f"  \033[33m{gid} không tìm thấy trong canonical CONTEXT.md — skip.\033[0m")
            continue

        # Append tag vào dưới goal_id mention (crude but safe)
        # Tốt nhất: add note cuối file nếu format không chuẩn
        pattern = re.compile(
            rf"(\*\*Test Scenarios:\*\*|\*\*Endpoints:\*\*)(.*?)(\n\*\*|\n###|\Z)",
            re.S
        )
        match_found = False
        # Find first mention của {gid} và add tag sau block nearest
        gid_pos = ctx_text.find(gid)
        if gid_pos >= 0:
            # Find end of goal's block (next ### or end of section)
            search_from = gid_pos
            next_section = re.search(r"\n(### |## |\Z)", ctx_text[search_from:])
            insert_pos = search_from + next_section.start() if next_section else len(ctx_text)
            # Insert tag before next section
            ctx_text = ctx_text[:insert_pos] + f"\n{tag_line}\n" + ctx_text[insert_pos:]
            applied_count += 1
            match_found = True
            print(f"  ✓ {gid}: {sug['tag']}: {sug['value']}")

        if not match_found:
            print(f"  \033[33m{gid} pattern match failed — skip.\033[0m")

    canonical_ctx.write_text(ctx_text, encoding="utf-8")
    print()
    print(f"✓ Applied {applied_count}/{len(approved)} tags vào {canonical_ctx}")
    print(f"  Backup: {backup}")
    print(f"  Cleanup sandbox (optional): rm -rf {sandbox}")
    return 0


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="Migrate goal tags cho phases pre-v1.14.0")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("scan", help="List phases và migrate candidates")

    cp = sub.add_parser("clone", help="Clone phase artifacts tới sandbox")
    cp.add_argument("phase", help="Phase name hoặc prefix")

    sp = sub.add_parser("suggest", help="Heuristic auto-suggest tags")
    sp.add_argument("phase")

    ap = sub.add_parser("apply", help="Copy approved tags về canonical")
    ap.add_argument("phase")

    args = p.parse_args(argv)

    if args.cmd == "scan":
        return scan()
    if args.cmd == "clone":
        return clone(args.phase)
    if args.cmd == "suggest":
        return suggest(args.phase)
    if args.cmd == "apply":
        return apply(args.phase)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
