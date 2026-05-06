# Task 02: Add `CLISpec` + `StageConfig` dataclasses

**Goal:** Define typed data structures for CrossAI configuration. `CLISpec` represents one CLI invoker (name, command template, label, role). `StageConfig` represents one stage's binding (primary CLIs, verifier CLI).

**Files:**
- Modify: `scripts/lib/crossai_config.py` (append after existing `format_rejection` function)
- Mirror: `.claude/scripts/lib/crossai_config.py`
- Test: `scripts/tests/test_crossai_config_resolve.py` (new — Task 2 portion only; Task 3 extends)

---

- [ ] **Step 1: Write the failing test**

Create `scripts/tests/test_crossai_config_resolve.py`:

```python
"""Stage configuration helpers — CLISpec + StageConfig dataclasses
(Task 02), resolve_stage_config (Task 03), heuristic thresholds (Task 04).

This file accumulates tests across Tasks 2-4. Each task adds its own
test functions; the file grows monotonically.
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))


# ---- Task 02 tests ----

def test_clispec_construction():
    """CLISpec dataclass holds CLI invoker fields."""
    from crossai_config import CLISpec
    spec = CLISpec(
        name="Codex-GPT-5.5",
        command='cat {context} | codex exec -m gpt-5.5 "{prompt}"',
        label="Codex GPT 5.5",
        role="primary",
    )
    assert spec.name == "Codex-GPT-5.5"
    assert spec.role == "primary"
    assert "{context}" in spec.command
    assert "{prompt}" in spec.command


def test_clispec_default_role():
    """If `role` not specified, default to 'primary'."""
    from crossai_config import CLISpec
    spec = CLISpec(
        name="Gemini-Pro",
        command="echo {prompt}",
        label="Gemini",
    )
    assert spec.role == "primary"


def test_stageconfig_construction():
    """StageConfig holds primary list + verifier."""
    from crossai_config import CLISpec, StageConfig
    primary_a = CLISpec(name="A", command="cmd-a", label="A", role="primary")
    primary_b = CLISpec(name="B", command="cmd-b", label="B", role="primary")
    verifier = CLISpec(name="V", command="cmd-v", label="V", role="verifier")
    cfg = StageConfig(
        stage="blueprint",
        primary_clis=[primary_a, primary_b],
        verifier_cli=verifier,
    )
    assert cfg.stage == "blueprint"
    assert len(cfg.primary_clis) == 2
    assert cfg.verifier_cli.name == "V"


def test_stageconfig_optional_verifier():
    """`verifier_cli` may be None (e.g. when stage has only primary CLIs)."""
    from crossai_config import CLISpec, StageConfig
    primary = CLISpec(name="A", command="cmd", label="A", role="primary")
    cfg = StageConfig(
        stage="scope",
        primary_clis=[primary],
        verifier_cli=None,
    )
    assert cfg.verifier_cli is None


def test_clispec_role_validation():
    """`role` must be 'primary' or 'verifier'."""
    from crossai_config import CLISpec
    import pytest
    with pytest.raises(ValueError, match="role must be"):
        CLISpec(name="X", command="cmd", label="X", role="invalid")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -m pytest scripts/tests/test_crossai_config_resolve.py -v
```

Expected: 5 failures, all `ImportError: cannot import name 'CLISpec'` or `'StageConfig'`.

- [ ] **Step 3: Add dataclasses to `scripts/lib/crossai_config.py`**

Append to the end of `scripts/lib/crossai_config.py` (after the existing `format_rejection` function):

```python


# ── Stage configuration (M1 Task 02) ────────────────────────────────────


_VALID_ROLES = ("primary", "verifier")


@dataclass
class CLISpec:
    """One CrossAI CLI invoker entry from `vg.config.md` `crossai_clis:`.

    Attributes:
        name: Unique identifier referenced from `crossai_stages` block.
            Examples: "Codex-GPT-5.5", "Gemini-Pro-1M", "Claude-Sonnet-4.6".
        command: Shell command template with `{context}` and `{prompt}`
            placeholders. The orchestrator pipes brief content into stdin
            and substitutes `{prompt}` at invocation time.
        label: Human-readable name surfaced in TodoWrite UI + telemetry.
        role: Either "primary" (full review pass) or "verifier" (adjudicator
            in M3 multi-primary consensus). Default "primary".
    """
    name: str
    command: str
    label: str
    role: str = "primary"

    def __post_init__(self) -> None:
        if self.role not in _VALID_ROLES:
            raise ValueError(
                f"CLISpec.role must be one of {_VALID_ROLES}, got "
                f"{self.role!r}"
            )


@dataclass
class StageConfig:
    """One stage's CrossAI binding from `vg.config.md` `crossai_stages:`.

    Attributes:
        stage: One of "scope", "blueprint", "build".
        primary_clis: Ordered list of CLISpec with role="primary". M1 uses
            this as a typed config boundary while preserving current build
            runtime behavior. M3 invokes all primaries in parallel for
            consensus.
        verifier_cli: Optional CLISpec with role="verifier". Used by M3 to
            adjudicate disagreements; ignored in M1.
    """
    stage: str
    primary_clis: list[CLISpec]
    verifier_cli: CLISpec | None = None
```

Also add to the existing imports at the top of `scripts/lib/crossai_config.py`:

```python
from dataclasses import dataclass, field
```

(`field` is for Task 3; importing now avoids re-edit.)

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -m pytest scripts/tests/test_crossai_config_resolve.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Sync mirror**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
cp scripts/lib/crossai_config.py .claude/scripts/lib/crossai_config.py
diff -q scripts/lib/crossai_config.py .claude/scripts/lib/crossai_config.py
```

Expected: no output (byte-identical).

- [ ] **Step 6: Commit**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
git add scripts/lib/crossai_config.py \
        .claude/scripts/lib/crossai_config.py \
        scripts/tests/test_crossai_config_resolve.py
git commit -m "feat(crossai-config): add CLISpec + StageConfig dataclasses

M1 Task 02 — typed data structures for CrossAI stage configuration.
CLISpec captures one CLI invoker (name, command template, label, role).
StageConfig binds a stage (scope/blueprint/build) to primary CLIs +
optional verifier. Used by Task 03 resolve_stage_config() and Tasks 5-6
crossai_loop library.

Tests: 5 new (construction, default role, validation, optional verifier).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```
