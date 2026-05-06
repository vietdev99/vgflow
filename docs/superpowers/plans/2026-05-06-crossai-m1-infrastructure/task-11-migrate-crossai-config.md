# Task 11: Add additive migration planner + optional `migrate-crossai` helper

**Goal:** Add a shared migration planner that detects legacy `vg.config.md` (has `crossai_clis:` but missing `crossai_stages:` or `crossai.policy`) and computes an additive patch with sensible defaults. An optional `migrate-crossai` helper command may expose that planner, but M1 does NOT wire auto-migration into first invocation yet. The activation path is deferred until build/scope/blueprint can all consume the same helper consistently.

**Files:**
- Modify: `scripts/vg-orchestrator/__main__.py` (shared helper + optional subparser)
- Mirror: `.claude/scripts/vg-orchestrator/__main__.py`
- Test: `scripts/tests/test_crossai_migrate_plan.py` (new)

---

- [ ] **Step 1: Create the failing test file**

Create `scripts/tests/test_crossai_migrate_plan.py`:

```python
"""Tests for CrossAI additive migration planning (M1 Task 11)."""
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ORCH = REPO_ROOT / ".claude" / "scripts" / "vg-orchestrator"


def _run_orch(args, cwd=None):
    return subprocess.run(
        [sys.executable, str(ORCH), *args],
        capture_output=True, text=True, cwd=cwd,
        env={"PATH": "/usr/bin:/bin"},
    )


_LEGACY_CONFIG = """\
# Legacy project config (pre-M1 schema)
project_name: "demo"

crossai_clis:
  - name: "Codex"
    command: 'cat {context} | codex exec'
    label: "Codex"
"""


def _write_legacy(tmp_path):
    (tmp_path / ".claude").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".claude" / "vg.config.md").write_text(_LEGACY_CONFIG)


def test_migrate_dry_run_shows_appended_block(tmp_path):
    """--dry-run prints what would be appended without modifying file."""
    _write_legacy(tmp_path)
    proc = _run_orch(["migrate-crossai", "--dry-run"], cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert "crossai_stages:" in proc.stdout
    assert "crossai:" in proc.stdout
    assert "policy:" in proc.stdout
    # File untouched
    assert (tmp_path / ".claude" / "vg.config.md").read_text() == _LEGACY_CONFIG


def test_migrate_write_appends_missing_blocks(tmp_path):
    """--write appends crossai_stages + crossai.policy + thresholds."""
    _write_legacy(tmp_path)
    proc = _run_orch(["migrate-crossai", "--write"], cwd=tmp_path)
    assert proc.returncode == 0
    content = (tmp_path / ".claude" / "vg.config.md").read_text()
    assert "crossai_clis:" in content  # original preserved
    assert "crossai_stages:" in content  # appended
    assert "policy:" in content
    assert "heuristic_thresholds:" in content


def test_migrate_idempotent_when_already_migrated(tmp_path):
    """If crossai_stages already present, --write is a no-op."""
    full = _LEGACY_CONFIG + """
crossai_stages:
  blueprint:
    primary_clis: ["Codex"]
    verifier_cli: "Codex"
"""
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "vg.config.md").write_text(full)
    proc = _run_orch(["migrate-crossai", "--write"], cwd=tmp_path)
    assert proc.returncode == 0
    content = (tmp_path / ".claude" / "vg.config.md").read_text()
    assert content.count("crossai_stages:") == 1


def test_migrate_no_config_errors(tmp_path):
    """No vg.config.md → exit 2 with actionable hint to run `/vg:project --init-only`."""
    proc = _run_orch(["migrate-crossai", "--dry-run"], cwd=tmp_path)
    assert proc.returncode == 2
    assert "/vg:project --init-only" in proc.stderr or "/vg:project --init-only" in proc.stdout


def test_migrate_uses_existing_clis_for_stages(tmp_path):
    """Migration's stage primary_clis should reference CLIs from existing
    crossai_clis registry (not fabricate names)."""
    _write_legacy(tmp_path)
    proc = _run_orch(["migrate-crossai", "--write"], cwd=tmp_path)
    content = (tmp_path / ".claude" / "vg.config.md").read_text()
    # Original has only "Codex" — migrated stages should reference it
    assert "Codex" in content
    # Resolves end-to-end:
    sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))
    from crossai_config import resolve_stage_config
    cfg = resolve_stage_config("blueprint", tmp_path)
    assert any(c.name == "Codex" for c in cfg.primary_clis)
```

- [ ] **Step 2: Run tests to verify failure**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -m pytest scripts/tests/test_crossai_migrate_plan.py -v
```

Expected: failures because the planner/helper does not exist yet.

- [ ] **Step 3: Add subparser + cmd in `scripts/vg-orchestrator/__main__.py`**

Append after Task 10's subparser registration only if you expose a helper CLI:

```python
    s = sub.add_parser(
        "migrate-crossai",
        help="Append missing crossai_stages + crossai.policy blocks "
             "to existing vg.config.md (legacy project upgrade)",
    )
    grp = s.add_mutually_exclusive_group(required=True)
    grp.add_argument("--dry-run", action="store_true",
                     help="Print appended content to stdout, no file write")
    grp.add_argument("--write", action="store_true",
                     help="Append to .claude/vg.config.md (idempotent)")
    s.set_defaults(func=cmd_migrate_crossai_config)
```

Add a shared helper first, then optionally wrap it with `cmd_migrate_crossai_config()`:

```python
def cmd_migrate_crossai_config(args) -> int:
    """Append crossai_stages + crossai.policy + heuristic_thresholds blocks
    to existing vg.config.md (legacy project upgrade helper).
    Reuses CLI names from existing crossai_clis registry. Idempotent.

    --dry-run: print to stdout
    --write: append to file + emit crossai.config_migrated telemetry
    """
    target = Path(".claude") / "vg.config.md"
    if not target.exists():
        print(
            "\033[38;5;208mvg.config.md missing. Run "
            "`/vg:project --init-only` first.\033[0m",
            file=sys.stderr,
        )
        return 2
    text = target.read_text(encoding="utf-8")
    has_stages = "crossai_stages:" in text
    has_policy_block = bool(re.search(
        r"^crossai:\s*$\s+(policy|heuristic_thresholds):",
        text, re.MULTILINE,
    ))

    # Reuse CLI names from existing crossai_clis registry. Import the
    # parser from crossai_config (added in M1 Task 03).
    sys.path.insert(0, str(_REPO_ROOT / "scripts" / "lib"))
    from crossai_config import _parse_crossai_clis_full  # noqa: PLC0415
    clis = _parse_crossai_clis_full(text)
    if not clis:
        print(
            "\033[38;5;208mNo crossai_clis declared in vg.config.md. "
            "Run `/vg:project --init-only` to regenerate config.\033[0m",
            file=sys.stderr,
        )
        return 2
    primary_names = [c.name for c in clis if c.role == "primary"]
    verifier_names = [c.name for c in clis if c.role == "verifier"]
    if not primary_names:
        primary_names = [clis[0].name]
    if not verifier_names:
        verifier_names = [primary_names[0]]

    blocks: list[str] = []
    if not has_stages:
        primary_arr = ", ".join(f'"{n}"' for n in primary_names[:2])
        stages_lines = ["", "crossai_stages:"]
        for stage in ("scope", "blueprint", "build"):
            stages_lines.append(f"  {stage}:")
            stages_lines.append(f"    primary_clis: [{primary_arr}]")
            stages_lines.append(f'    verifier_cli: "{verifier_names[0]}"')
        blocks.append("\n".join(stages_lines))
    if not has_policy_block:
        policy_lines = [
            "",
            "crossai:",
            '  policy: "auto"  # strict | auto | off (auto-migrated)',
            "  heuristic_thresholds:",
            "    min_endpoints: 3",
            "    min_critical_goals: 2",
            "    min_plan_tasks: 5",
        ]
        blocks.append("\n".join(policy_lines))

    if not blocks:
        print(
            "\033[33mvg.config.md already has crossai_stages + crossai "
            "policy blocks; nothing to migrate.\033[0m",
            file=sys.stderr,
        )
        return 0

    appended = "\n".join(blocks) + "\n"
    if args.dry_run:
        sys.stdout.write(appended)
        return 0

    with target.open("a", encoding="utf-8") as f:
        f.write(appended)
    print(
        f"Migrated {target}: appended "
        f"{'+'.join('crossai_stages' if 'crossai_stages' in b else 'crossai.policy' for b in blocks)}",
        file=sys.stderr,
    )

    # Emit telemetry (best-effort; ignore if events.db unavailable)
    try:
        db.append_event(
            run_id="migrate-crossai",
            event_type="crossai.config_migrated",
            phase="",
            command="migrate-crossai",
            actor="orchestrator",
            outcome="INFO",
            payload={
                "added_stages": not has_stages,
                "added_policy": not has_policy_block,
                "primary_count": len(primary_names),
            },
        )
    except Exception:
        pass
    return 0
```

- [ ] **Step 4: Sync mirror + run tests**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
cp scripts/vg-orchestrator/__main__.py .claude/scripts/vg-orchestrator/__main__.py
python3 -m pytest scripts/tests/test_crossai_migrate_plan.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
git add scripts/vg-orchestrator/__main__.py \
        .claude/scripts/vg-orchestrator/__main__.py \
        scripts/tests/test_crossai_migrate_plan.py
git commit -m "feat(orchestrator): additive crossai migration planner

M1 Task 11 — compute and optionally apply additive crossai migration
patches for legacy vg.config.md. Idempotent (skip if blocks already
present). Reuses CLI names from existing crossai_clis registry; falls
back gracefully when no role field.

M1 only ships the shared planner/helper. First-invocation lazy migration
activation stays deferred until build/scope/blueprint all share the same
entry path in M2.

Emits crossai.config_migrated telemetry event for audit trail.

Tests: additive migration planner/helper coverage (dry-run, write append,
idempotent, no config error, stage uses existing CLIs).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```
