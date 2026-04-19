#!/usr/bin/env python3
"""
verify-wave-integrity.py — post-crash integrity reconciliation for /vg:build.

After power-off, OS crash, or other catastrophic termination:
  - Progress file may claim "committed" for a task whose commit SHA doesn't
    exist in git log (partial object write pre-ref-update)
  - Progress file may show "in-flight" for tasks that actually committed
    (crash between commit success and progress file update)
  - Staged files may be orphans from a crashed agent
  - Source files may be empty/truncated (rare — modern FS journaling usually
    prevents, but sudden power-off can trip it)
  - Untracked files may be legitimate agent WIP (Write finished) or junk

This script reconciles progress file vs git reality vs filesystem reality
and classifies EVERY task in the wave into one of 8 deterministic buckets
with a concrete recovery action per task.

Classification buckets:
  VALID_COMMITTED        — progress says committed, git log confirms, files intact
  CORRUPTED_MISSING      — progress says committed, but SHA not in git log (crash between
                           git commit success and progress write — very rare, safe to re-run task)
  DESYNC_EXTRA_COMMIT    — git log has commit for task N, but progress doesn't record it
                           (probably committed before progress was init'd — reconcile: update progress)
  ABANDONED              — in-flight > threshold + no commit produced (agent died)
  STAGED_ORPHAN          — in-flight, has staged files but no commit (mid-critical crash)
  NEW_UNTRACKED          — not in git log, but files declared in PLAN exist untracked (agent Write'd before crash)
  FAILED_RETRY           — progress marks failed, no commit, no files — re-run needed
  NOT_STARTED            — never ran (clean state)

Exit codes:
  0 — no corruption, no action needed
  1 — corruption detected, manual review required
  2 — integrity check failed (script error / bad args)

Usage (from /vg:build preflight or standalone):
  python verify-wave-integrity.py --phase-dir .vg/phases/10-... --wave 5
  python verify-wave-integrity.py --phase-dir ... --all-waves  # full phase history
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

RE_COMMIT_TASK = re.compile(r"^(feat|fix|refactor|test|chore|docs|style|perf)\((\d+(?:\.\d+)*)-(\d+)\):")
STALE_IN_FLIGHT_SECONDS = 600  # 10 min — likely abandoned after this
EMPTY_FILE_SUSPICION_BYTES = 10  # a .ts/.tsx/.rs file < 10 bytes is probably truncated


def git(args: list[str]) -> tuple[int, str]:
    """Run git, return (exit_code, stdout)."""
    try:
        r = subprocess.run(["git"] + args, capture_output=True, text=True, check=False, timeout=30)
        return r.returncode, r.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return 1, f"git error: {e}"


def load_progress(phase_dir: Path) -> dict | None:
    f = phase_dir / ".build-progress.json"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def commits_in_wave(wave_tag: str) -> list[dict]:
    """Return list of {sha, subject} for commits since wave_tag."""
    rc, out = git(["log", "--format=%H|%s", f"{wave_tag}..HEAD"])
    if rc != 0:
        return []
    commits = []
    for line in out.strip().splitlines():
        if "|" not in line:
            continue
        sha, subject = line.split("|", 1)
        m = RE_COMMIT_TASK.match(subject)
        task = int(m.group(3)) if m else None
        commits.append({"sha": sha, "subject": subject, "task": task})
    return commits


def commit_exists(sha: str) -> bool:
    """Check if a SHA is reachable in git — detects phantom commits from crash."""
    if not sha:
        return False
    rc, _ = git(["cat-file", "-e", f"{sha}^{{commit}}"])
    return rc == 0


def files_in_commit(sha: str) -> list[str]:
    rc, out = git(["show", "--pretty=", "--name-only", sha])
    return [line.strip() for line in out.splitlines() if line.strip()] if rc == 0 else []


def staged_files() -> list[str]:
    rc, out = git(["diff", "--cached", "--name-only"])
    return [line.strip() for line in out.splitlines() if line.strip()] if rc == 0 else []


def is_file_truncated(path: Path) -> bool:
    """Heuristic: source files < 10 bytes are likely FS partial-write corruption."""
    try:
        if not path.exists() or not path.is_file():
            return False
        if path.suffix not in {".ts", ".tsx", ".js", ".jsx", ".rs", ".py", ".go", ".md"}:
            return False
        size = path.stat().st_size
        return 0 < size < EMPTY_FILE_SUSPICION_BYTES
    except OSError:
        return False


def load_task_specs(phase_dir: Path) -> dict[int, dict]:
    """Load task <file-path> + <also-edits> for cross-check."""
    tasks = {}
    tasks_dir = phase_dir / ".wave-tasks"
    if not tasks_dir.exists():
        return tasks
    for tf in tasks_dir.glob("task-*.md"):
        m = re.match(r"task-(\d+)\.md$", tf.name)
        if not m:
            continue
        text = tf.read_text(encoding="utf-8", errors="replace")
        fp = re.search(r"<file-path>([^<]+)</file-path>", text)
        also = []
        for ae in re.finditer(r"<also-edits>([^<]+)</also-edits>", text):
            for p in re.split(r"[,\n;]", ae.group(1)):
                p = p.strip()
                if p and not p.startswith("#") and not p.startswith("<!--"):
                    also.append(p)
        tasks[int(m.group(1))] = {
            "file_path": fp.group(1).strip() if fp else None,
            "also_edits": also,
        }
    return tasks


def classify_task(
    task_num: int,
    progress: dict,
    commits: list[dict],
    task_spec: dict,
    repo_root: Path,
    now_epoch: float,
) -> dict:
    """Classify one task into one of the 8 buckets + attach evidence + recovery."""
    # Progress-side state
    committed_p = next((x for x in progress.get("tasks_committed", []) if x["task"] == task_num), None)
    in_flight_p = next((x for x in progress.get("tasks_in_flight", []) if x["task"] == task_num), None)
    failed_p    = next((x for x in progress.get("tasks_failed",    []) if x["task"] == task_num), None)

    # Git-side state
    git_commit = next((c for c in commits if c["task"] == task_num), None)

    # Filesystem state — does task's declared file exist on disk?
    fp = task_spec.get("file_path") if task_spec else None
    fs_file_exists = False
    fs_file_truncated = False
    fs_file_untracked = False
    if fp:
        abs_path = repo_root / fp
        fs_file_exists = abs_path.exists()
        fs_file_truncated = is_file_truncated(abs_path)
        if fs_file_exists and not git_commit:
            rc, _ = git(["ls-files", "--error-unmatch", fp])
            fs_file_untracked = (rc != 0)

    # ---- Classification logic (deterministic priority) ----

    # 1. Progress says committed
    if committed_p:
        sha = committed_p.get("commit", "")
        if git_commit and git_commit["sha"].startswith(sha):
            # Progress + git agree — verify files exist
            touched_files = files_in_commit(git_commit["sha"])
            missing = []
            truncated = []
            for f in touched_files:
                ap = repo_root / f
                if not ap.exists():
                    missing.append(f)
                elif is_file_truncated(ap):
                    truncated.append(f)
            if missing or truncated:
                return {
                    "task": task_num, "verdict": "CORRUPTED_FILE",
                    "detail": f"commit {sha[:8]} references files {missing + truncated} that are missing/truncated on disk",
                    "recovery": f"git checkout {sha} -- {' '.join(missing + truncated)}  # restore from commit blob",
                }
            return {"task": task_num, "verdict": "VALID_COMMITTED",
                    "detail": f"commit {sha[:8]}, {len(touched_files)} files, all intact"}
        else:
            # Progress claims commit but SHA not in git — phantom (crash between commit + progress write)
            if commit_exists(sha):
                return {"task": task_num, "verdict": "VALID_COMMITTED",
                        "detail": f"commit {sha[:8]} exists but not in wave tag range — progress may have stale wave_tag"}
            return {
                "task": task_num, "verdict": "CORRUPTED_MISSING",
                "detail": f"progress claims commit {sha[:8]} but not in git log (ref never updated after commit — object may be orphan, safe to re-run)",
                "recovery": f"re-run task: /vg:build {progress.get('phase')} --wave {progress.get('current_wave')} --only {task_num}",
            }

    # 2. Git log has commit for task but progress doesn't record
    if git_commit and not committed_p:
        return {
            "task": task_num, "verdict": "DESYNC_EXTRA_COMMIT",
            "detail": f"git has commit {git_commit['sha'][:8]} for task but progress file doesn't record it (likely committed before progress init)",
            "recovery": f"update progress: vg_build_progress_commit_task <phase_dir> {task_num} {git_commit['sha']}",
        }

    # 3. Progress marks failed
    if failed_p:
        reason = failed_p.get("reason", "unknown")
        if fs_file_untracked:
            return {
                "task": task_num, "verdict": "FAILED_PARTIAL_WORK",
                "detail": f"marked failed ({reason}), BUT agent wrote {fp} before dying — untracked on disk",
                "recovery": f"review {fp} — if usable: git add + commit manually; if junk: rm {fp} + re-run task",
            }
        return {
            "task": task_num, "verdict": "FAILED_RETRY",
            "detail": f"marked failed: {reason}",
            "recovery": f"/vg:build {progress.get('phase')} --wave {progress.get('current_wave')} --only {task_num}",
        }

    # 4. Progress marks in-flight
    if in_flight_p:
        try:
            from datetime import datetime, timezone
            started = in_flight_p.get("started_at", "")
            started_dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
            age = now_epoch - started_dt.timestamp()
        except (ValueError, AttributeError):
            age = 99999

        has_staged = any(
            f in (task_spec.get("also_edits", []) + ([fp] if fp else []))
            for f in staged_files()
        ) if task_spec else False

        if age > STALE_IN_FLIGHT_SECONDS:
            if has_staged:
                return {
                    "task": task_num, "verdict": "STAGED_ORPHAN",
                    "detail": f"in-flight {int(age)}s (stale), has staged files but no commit — crash mid-critical section",
                    "recovery": f"/vg:build {progress.get('phase')} --reset-queue --wave {progress.get('current_wave')} --only {task_num}  # reset staged + re-run",
                }
            if fs_file_untracked:
                return {
                    "task": task_num, "verdict": "ABANDONED_PARTIAL",
                    "detail": f"in-flight {int(age)}s (stale), agent wrote {fp} but never staged/committed",
                    "recovery": f"review {fp} manually — retain or discard, then /vg:build ... --only {task_num}",
                }
            return {
                "task": task_num, "verdict": "ABANDONED",
                "detail": f"in-flight {int(age)}s (> {STALE_IN_FLIGHT_SECONDS}s threshold) — agent dead, no visible work",
                "recovery": f"/vg:build {progress.get('phase')} --wave {progress.get('current_wave')} --only {task_num}",
            }
        return {
            "task": task_num, "verdict": "IN_FLIGHT_ACTIVE",
            "detail": f"in-flight {int(age)}s — still within threshold, may be actively working",
            "recovery": f"wait, then re-check via /vg:build {progress.get('phase')} --status",
        }

    # 5. Nothing recorded — not started, OR first-ever progress init
    if fs_file_untracked:
        return {
            "task": task_num, "verdict": "NEW_UNTRACKED",
            "detail": f"no progress entry BUT {fp} exists untracked — agent wrote before progress init?",
            "recovery": f"review {fp} — may be orphan or legitimate WIP",
        }
    return {"task": task_num, "verdict": "NOT_STARTED", "detail": "clean state"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase-dir", required=True, type=Path)
    ap.add_argument("--wave", type=int, help="Wave number (default: current from progress)")
    ap.add_argument("--repo-root", type=Path, default=Path.cwd())
    ap.add_argument("--json", action="store_true", help="Output JSON instead of report")
    args = ap.parse_args()

    phase_dir = args.phase_dir
    if not phase_dir.exists():
        print(f"⛔ phase-dir not found: {phase_dir}", file=sys.stderr)
        return 2

    progress = load_progress(phase_dir)
    if not progress:
        print(f"⚠ no .build-progress.json — wave was never started, nothing to reconcile", file=sys.stderr)
        return 0

    wave = args.wave or progress.get("current_wave")
    wave_tag = progress.get("wave_tag")
    if not wave_tag:
        print(f"⛔ progress file has no wave_tag — cannot reconcile against git", file=sys.stderr)
        return 2

    # Verify wave_tag exists
    rc, _ = git(["rev-parse", "--verify", wave_tag])
    if rc != 0:
        print(f"⛔ wave_tag {wave_tag} not found in git — was it pruned?", file=sys.stderr)
        return 2

    commits = commits_in_wave(wave_tag)
    task_specs = load_task_specs(phase_dir)

    import time
    now_epoch = time.time()

    # Classify every expected task
    expected = progress.get("tasks_expected", [])
    classifications = []
    for task_num in sorted(expected):
        spec = task_specs.get(task_num, {})
        c = classify_task(task_num, progress, commits, spec, args.repo_root, now_epoch)
        classifications.append(c)

    # Also flag extra commits (task numbers in git but not in expected)
    expected_set = set(expected)
    extras = [c for c in commits if c["task"] and c["task"] not in expected_set]
    for ex in extras:
        classifications.append({
            "task": ex["task"], "verdict": "EXTRA_UNEXPECTED",
            "detail": f"commit {ex['sha'][:8]} for task not in expected list {expected_set}",
            "recovery": "review intent — may be orchestrator fix commit (safe) OR wrong wave",
        })

    # Summary
    buckets: dict[str, list] = {}
    for c in classifications:
        buckets.setdefault(c["verdict"], []).append(c["task"])

    if args.json:
        print(json.dumps({
            "phase": progress.get("phase"),
            "wave": wave,
            "wave_tag": wave_tag,
            "classifications": classifications,
            "buckets": buckets,
        }, indent=2))
        return 0 if not any(v.startswith("CORRUPTED") or v in {"STAGED_ORPHAN", "ABANDONED_PARTIAL", "DESYNC_EXTRA_COMMIT"} for v in buckets) else 1

    # Pretty report
    print(f"━━━ Wave {wave} integrity reconciliation ━━━")
    print(f"Phase:    {progress.get('phase')}")
    print(f"Wave tag: {wave_tag}")
    print(f"Expected: {expected}")
    print()

    # Print by severity — corruption/orphan first
    severity_order = [
        "CORRUPTED_MISSING", "CORRUPTED_FILE",
        "STAGED_ORPHAN", "ABANDONED_PARTIAL", "ABANDONED",
        "DESYNC_EXTRA_COMMIT", "EXTRA_UNEXPECTED",
        "FAILED_PARTIAL_WORK", "FAILED_RETRY",
        "NEW_UNTRACKED", "IN_FLIGHT_ACTIVE",
        "VALID_COMMITTED", "NOT_STARTED",
    ]

    any_issue = False
    for verdict in severity_order:
        if verdict not in buckets:
            continue
        tasks = sorted(buckets[verdict])
        icon = {
            "VALID_COMMITTED": "✓",
            "NOT_STARTED":     "·",
            "IN_FLIGHT_ACTIVE":"⋯",
            "DESYNC_EXTRA_COMMIT": "!",
            "FAILED_RETRY":    "✗",
            "NEW_UNTRACKED":   "?",
            "EXTRA_UNEXPECTED":"?",
        }.get(verdict, "⛔")
        print(f"{icon} {verdict} — tasks {tasks}")
        for c in classifications:
            if c["verdict"] == verdict:
                print(f"    Task {c['task']}: {c['detail']}")
                if c.get("recovery"):
                    print(f"    → {c['recovery']}")
                    any_issue = True
        print()

    # Final verdict
    has_corruption = any(v.startswith("CORRUPTED") for v in buckets)
    has_orphan = any(v in {"STAGED_ORPHAN", "ABANDONED_PARTIAL", "NEW_UNTRACKED"} for v in buckets)
    has_desync = "DESYNC_EXTRA_COMMIT" in buckets

    if has_corruption:
        print("⛔ Integrity verdict: CORRUPTION detected — manual review required.")
        return 1
    if has_orphan or has_desync:
        print("⚠ Integrity verdict: recoverable issues — follow recovery commands above.")
        return 1
    print("✓ Integrity verdict: clean — no corruption, no abandoned work.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
