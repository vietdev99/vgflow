# Batch 13 — Simplicity gate + Token budget (Rule 2 + Rule 6 from tinbeta AGENTS.md) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Close 2 PARTIAL rules from tinbeta/AGENTS.md 12-rule comparison.

- **Rule 2 (Simplicity First)**: No code-level gate ensures generated/committed work isn't over-complicated. Developer-side only. Add complexity-budget validator wired into build close.
- **Rule 6 (Token budgets not advisory)**: `check-quota.py` exists for field-test only. No general per-task / per-session token budget. Add generic budget tracker + config.

**Tech Stack:** Python + bash. No new deps.

**Working directory:** `main`.

---

## Conventions

- Mirror byte-identical to `.claude/`
- Regression sweep: `python -m pytest tests/ -q --tb=no -k "complexity or token_budget or rule_2 or rule_6"`
- Single `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` per commit

---

## Task 1: Rule 2 — verify-task-complexity.py validator

**Files:**
- Create: `scripts/validators/verify-task-complexity.py`
- Modify: `commands/vg/_shared/build/close.md` (wire at 12_run_complete area or post-mortem)
- Modify: `templates/vg/PLAN.template.md` (document `complexity_budget` field) — if template exists
- Mirrors
- Test: `tests/test_rule2_complexity_gate.py`

**Step 1: Failing test**

```python
"""tests/test_rule2_complexity_gate.py — Rule 2 simplicity gate."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
VAL = REPO / "scripts" / "validators" / "verify-task-complexity.py"


def test_validator_exists():
    assert VAL.is_file(), "Rule 2: verify-task-complexity.py must ship"


def test_no_budget_in_plan_skips_check(tmp_path):
    """When PLAN.md has no complexity_budget, validator must skip cleanly (advisory)."""
    phase_dir = tmp_path / ".vg" / "phases" / "99-test"
    phase_dir.mkdir(parents=True)
    (phase_dir / "PLAN.md").write_text("# Plan\nNo budget here.\n", encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(VAL), "--phase-dir", str(phase_dir), "--task-id", "T-01"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, f"Rule 2: missing budget should skip cleanly. stderr={r.stderr}"


def test_budget_overrun_warns_or_blocks(tmp_path):
    """When task delta exceeds declared budget, validator must surface OVERRUN."""
    phase_dir = tmp_path / ".vg" / "phases" / "99-test"
    phase_dir.mkdir(parents=True)
    plan_text = """# Plan

## Task T-01
**complexity_budget:** max_loc_delta=10

Implementation
"""
    (phase_dir / "PLAN.md").write_text(plan_text, encoding="utf-8")
    # Inject a fake diff stats file so validator can compute overrun
    (phase_dir / ".task-diff-stats.json").write_text(
        '{"T-01": {"loc_delta": 200, "files_changed": 5}}', encoding="utf-8"
    )
    r = subprocess.run(
        [sys.executable, str(VAL), "--phase-dir", str(phase_dir), "--task-id", "T-01"],
        capture_output=True, text=True,
    )
    # Advisory: prints OVERRUN; exit 0 unless --strict
    combined = r.stdout + r.stderr
    assert "overrun" in combined.lower() or "exceed" in combined.lower() or "200" in combined, (
        f"Rule 2: 200 loc delta vs max_loc_delta=10 must surface OVERRUN. Got: {combined[:300]}"
    )


def test_strict_mode_blocks_on_overrun(tmp_path):
    """--strict promotes overrun to non-zero exit."""
    phase_dir = tmp_path / ".vg" / "phases" / "99-test"
    phase_dir.mkdir(parents=True)
    (phase_dir / "PLAN.md").write_text(
        "## Task T-01\n**complexity_budget:** max_loc_delta=5\n", encoding="utf-8"
    )
    (phase_dir / ".task-diff-stats.json").write_text(
        '{"T-01": {"loc_delta": 500, "files_changed": 3}}', encoding="utf-8"
    )
    r = subprocess.run(
        [sys.executable, str(VAL), "--phase-dir", str(phase_dir), "--task-id", "T-01", "--strict"],
        capture_output=True, text=True,
    )
    assert r.returncode != 0, "Rule 2: --strict must escalate overrun to non-zero exit"
```

**Step 2: Run** → 4 fail.

**Step 3: Implement**

Create `scripts/validators/verify-task-complexity.py`:

```python
#!/usr/bin/env python3
"""verify-task-complexity.py — Rule 2 (simplicity gate) Batch 13

Reads PLAN.md per-task complexity_budget field (e.g. max_loc_delta=200).
Reads .task-diff-stats.json (written by build close pre-validator).
Surfaces OVERRUN when actual delta exceeds budget.

Advisory by default (exit 0). --strict promotes to non-zero exit.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path


BUDGET_RE = re.compile(
    r"\*\*complexity_budget:\*\*\s*([^\n]+)",
    re.IGNORECASE,
)


def _parse_budget(text: str, task_id: str) -> dict[str, int]:
    """Find task block in PLAN.md, extract complexity_budget key=value pairs."""
    # Find task section
    task_re = re.compile(rf"##\s+Task\s+{re.escape(task_id)}\b(.+?)(?=##\s+Task\s+|\Z)", re.S | re.I)
    m = task_re.search(text)
    if not m:
        return {}
    block = m.group(1)
    bm = BUDGET_RE.search(block)
    if not bm:
        return {}
    pairs = bm.group(1)
    out: dict[str, int] = {}
    for kv in re.finditer(r"(\w+)\s*=\s*(\d+)", pairs):
        out[kv.group(1)] = int(kv.group(2))
    return out


def _read_actual(stats_path: Path, task_id: str) -> dict[str, int]:
    if not stats_path.is_file():
        return {}
    try:
        data = json.loads(stats_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data.get(task_id, {}) or {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase-dir", required=True, type=Path)
    ap.add_argument("--task-id", required=True)
    ap.add_argument("--strict", action="store_true",
                    help="Escalate overrun to non-zero exit (default: advisory)")
    args = ap.parse_args()

    plan_path = args.phase_dir / "PLAN.md"
    if not plan_path.is_file():
        print(f"⚠ Rule 2: PLAN.md missing at {plan_path} — skip complexity gate")
        return 0

    budget = _parse_budget(plan_path.read_text(encoding="utf-8"), args.task_id)
    if not budget:
        print(f"ℹ Rule 2: no complexity_budget for {args.task_id} — skip")
        return 0

    actual = _read_actual(args.phase_dir / ".task-diff-stats.json", args.task_id)
    if not actual:
        print(f"⚠ Rule 2: no diff stats for {args.task_id} — skip")
        return 0

    overruns: list[str] = []
    for key, max_val in budget.items():
        # max_X budget vs X actual (normalize key name)
        actual_key = key.replace("max_", "")
        actual_val = actual.get(actual_key, 0)
        if actual_val > max_val:
            overruns.append(f"  {actual_key}: {actual_val} > budget {max_val} (OVERRUN by {actual_val - max_val})")

    if overruns:
        print(f"⚠ Rule 2: task {args.task_id} complexity OVERRUN:")
        for o in overruns:
            print(o)
        print(f"   Re-evaluate: is this task over-complicated? Senior engineer test failed.")
        return 1 if args.strict else 0
    print(f"✓ Rule 2: task {args.task_id} within complexity budget")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

In `commands/vg/_shared/build/close.md` at run_complete area (or post-mortem), add stats-collector + validator invocation:

```bash
# Rule 2 Batch 13: collect per-task diff stats + complexity gate
COMPLEXITY_VAL="${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/validators/verify-task-complexity.py"
[ -f "$COMPLEXITY_VAL" ] || COMPLEXITY_VAL="${REPO_ROOT:-.}/scripts/validators/verify-task-complexity.py"
TASK_STATS="${PHASE_DIR}/.task-diff-stats.json"
if [ -f "$COMPLEXITY_VAL" ] && [ -d "${PHASE_DIR}/.task-markers" ]; then
  # Collect git diff stats per task commit
  ${PYTHON_BIN:-python3} - <<PYEOF > "$TASK_STATS"
import json, subprocess
from pathlib import Path
stats = {}
markers_dir = Path("${PHASE_DIR}/.task-markers")
for m in markers_dir.glob("T-*.done") if markers_dir.is_dir() else []:
    task_id = m.stem
    try:
        sha = m.read_text(encoding="utf-8").split("|")[3] if "|" in m.read_text(encoding="utf-8") else ""
    except Exception:
        sha = ""
    if not sha or sha == "nogit":
        continue
    diff = subprocess.run(["git", "diff", "--shortstat", f"{sha}^", sha],
                          capture_output=True, text=True)
    out = diff.stdout.strip()
    # "3 files changed, 87 insertions(+), 12 deletions(-)"
    import re
    files = int((re.search(r"(\d+) files? changed", out) or ["", "0"])[1] or 0) if re.search(r"(\d+) files? changed", out) else 0
    ins = int((re.search(r"(\d+) insertions", out) or ["", "0"])[1] or 0) if re.search(r"(\d+) insertions", out) else 0
    dels = int((re.search(r"(\d+) deletions", out) or ["", "0"])[1] or 0) if re.search(r"(\d+) deletions", out) else 0
    stats[task_id] = {"files_changed": files, "loc_delta": ins + dels}
print(json.dumps(stats, indent=2))
PYEOF
  # Run validator per task
  for task in ${TASKS:-T-01 T-02 T-03}; do
    "${PYTHON_BIN:-python3}" "$COMPLEXITY_VAL" \
      --phase-dir "${PHASE_DIR}" --task-id "$task" || true
  done
fi
```

**Step 4-6:** pass + mirror + commit.

---

## Task 2: Rule 6 — generic token-budget tracker

**Files:**
- Create: `scripts/token-budget.py`
- Modify: `vg.config.template.md` (+ 2 mirrors) — add `token_budget` block
- Mirrors
- Test: `tests/test_rule6_token_budget.py`

**Step 1: Failing test**

```python
"""tests/test_rule6_token_budget.py — Rule 6 token budget tracker."""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
TB = REPO / "scripts" / "token-budget.py"


def test_tracker_script_exists():
    assert TB.is_file(), "Rule 6: scripts/token-budget.py must ship"


def test_tracker_add_accumulates(tmp_path):
    """Calling --add N twice must accumulate."""
    phase_dir = tmp_path / "phase"
    phase_dir.mkdir()
    for n in (1000, 1500):
        r = subprocess.run(
            [sys.executable, str(TB), "--phase-dir", str(phase_dir),
             "--task", "T-01", "--add", str(n)],
            capture_output=True, text=True,
        )
        assert r.returncode == 0, r.stderr
    ledger = phase_dir / ".token-budget.json"
    assert ledger.is_file()
    data = json.loads(ledger.read_text(encoding="utf-8"))
    assert data["tasks"]["T-01"]["used"] == 2500


def test_tracker_check_warns_at_80_percent(tmp_path):
    """At >=80% of per_task budget, --check must report WARN."""
    phase_dir = tmp_path / "phase"
    phase_dir.mkdir()
    # Default per_task=4000 from tinbeta. Set used=3500 (87.5%).
    subprocess.run(
        [sys.executable, str(TB), "--phase-dir", str(phase_dir),
         "--task", "T-01", "--add", "3500"],
        capture_output=True, text=True,
    )
    r = subprocess.run(
        [sys.executable, str(TB), "--phase-dir", str(phase_dir),
         "--task", "T-01", "--check"],
        capture_output=True, text=True,
    )
    assert "WARN" in r.stdout or "warn" in r.stdout.lower() or "80" in r.stdout, (
        f"Rule 6: 3500/4000 (87.5%) must trigger WARN. Got: {r.stdout!r}"
    )


def test_tracker_check_blocks_at_100_percent(tmp_path):
    """At >100% of per_task budget, --check must exit non-zero unless --allow-overrun."""
    phase_dir = tmp_path / "phase"
    phase_dir.mkdir()
    subprocess.run(
        [sys.executable, str(TB), "--phase-dir", str(phase_dir),
         "--task", "T-02", "--add", "5000"],
        capture_output=True, text=True,
    )
    r = subprocess.run(
        [sys.executable, str(TB), "--phase-dir", str(phase_dir),
         "--task", "T-02", "--check"],
        capture_output=True, text=True,
    )
    assert r.returncode != 0, (
        f"Rule 6: 5000/4000 over-budget must exit non-zero. Got rc={r.returncode}"
    )


def test_tracker_allow_overrun_bypasses(tmp_path):
    """--allow-overrun bypasses BLOCK."""
    phase_dir = tmp_path / "phase"
    phase_dir.mkdir()
    subprocess.run(
        [sys.executable, str(TB), "--phase-dir", str(phase_dir),
         "--task", "T-03", "--add", "5000"],
        capture_output=True, text=True,
    )
    r = subprocess.run(
        [sys.executable, str(TB), "--phase-dir", str(phase_dir),
         "--task", "T-03", "--check", "--allow-overrun"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, "Rule 6: --allow-overrun must let over-budget pass with WARN"


def test_config_template_documents_token_budget_block():
    config_paths = [
        REPO / "vg.config.template.md",
        REPO / "templates" / "vg" / "vg.config.template.md",
    ]
    found = False
    for p in config_paths:
        if p.is_file():
            body = p.read_text(encoding="utf-8")
            if "token_budget" in body and "per_task" in body and "per_session" in body:
                found = True
                break
    assert found, (
        "Rule 6: vg.config.template.md must document token_budget.{per_task, per_session} block"
    )
```

**Step 2-6:** RED → implement → GREEN → mirror → commit.

Create `scripts/token-budget.py`:

```python
#!/usr/bin/env python3
"""token-budget.py — Rule 6 (token budgets not advisory) Batch 13

Per-task + per-session token usage tracker. Default budgets from
tinbeta/AGENTS.md Rule 6: 4000/task, 30000/session.

Usage:
  --add N --task T-XX           Accumulate N tokens against task
  --check --task T-XX           Report PASS/WARN/BLOCK (warn>=80%, block>=100%)
  --check --session             Report session-wide state
  --allow-overrun               Bypass BLOCK (still emits WARN)
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_PER_TASK = 4000
DEFAULT_PER_SESSION = 30000


def _read_ledger(path: Path) -> dict:
    if not path.is_file():
        return {"tasks": {}, "session_used": 0, "started_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"tasks": {}, "session_used": 0}


def _write_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".token-budget.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except Exception:
        try: os.unlink(tmp)
        except OSError: pass
        raise


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase-dir", required=True, type=Path)
    ap.add_argument("--task", default="")
    ap.add_argument("--add", type=int, default=0)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--session", action="store_true")
    ap.add_argument("--allow-overrun", action="store_true")
    ap.add_argument("--per-task", type=int, default=DEFAULT_PER_TASK)
    ap.add_argument("--per-session", type=int, default=DEFAULT_PER_SESSION)
    args = ap.parse_args()

    ledger_path = args.phase_dir / ".token-budget.json"
    data = _read_ledger(ledger_path)
    data.setdefault("tasks", {})

    # ADD action
    if args.add > 0:
        if args.task:
            t = data["tasks"].setdefault(args.task, {"used": 0})
            t["used"] += args.add
        data["session_used"] = data.get("session_used", 0) + args.add
        _write_atomic(ledger_path, data)
        print(f"+{args.add} tokens (task={args.task or 'none'}, session={data['session_used']})")
        return 0

    # CHECK action
    if args.check:
        if args.task:
            used = data.get("tasks", {}).get(args.task, {}).get("used", 0)
            budget = args.per_task
            scope = f"task {args.task}"
        elif args.session:
            used = data.get("session_used", 0)
            budget = args.per_session
            scope = "session"
        else:
            print("ERROR: --check requires --task or --session", file=sys.stderr)
            return 2

        pct = (used / budget * 100) if budget > 0 else 0
        if pct >= 100:
            print(f"⛔ Rule 6 BLOCK: {scope} {used}/{budget} ({pct:.0f}%) over budget")
            if not args.allow_overrun:
                return 1
            print(f"   --allow-overrun set; continuing with WARN")
        elif pct >= 80:
            print(f"⚠ Rule 6 WARN: {scope} {used}/{budget} ({pct:.0f}%) approaching budget")
        else:
            print(f"✓ Rule 6: {scope} {used}/{budget} ({pct:.0f}%) within budget")
        return 0

    print("ERROR: must pass --add or --check", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
```

Append to `vg.config.template.md`:

```yaml
# Rule 6 Batch 13: token budget (per tinbeta/AGENTS.md)
token_budget:
  per_task: 4000      # Default from AGENTS.md Rule 6
  per_session: 30000  # Default from AGENTS.md Rule 6
  enforce: warn       # warn | block | off (block requires --allow-overrun to bypass)
```

**Step 4-6:** pass + mirror + commit.

---

## Task 3: Regression sweep + release v4.16.0

Bump VERSION 4.15.1 → 4.16.0. CHANGELOG entry referencing tinbeta AGENTS.md comparison + 2 PARTIAL rules closed → 12/12 STRONG/BEST_MATCH on tinbeta criteria. Tag v4.16.0. Push. Re-sync ~/.vgflow.

End of Batch 13 plan. Estimated 3 hours.
