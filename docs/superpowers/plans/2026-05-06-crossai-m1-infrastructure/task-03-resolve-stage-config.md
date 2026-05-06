# Task 03: Implement `resolve_stage_config(stage, repo_root)`

**Goal:** Read `vg.config.md` and produce a `StageConfig` for the requested stage. Parses `crossai_clis:` block (extending existing `_parse_crossai_clis` from Task 1) plus the new `crossai_stages:` block. Validates that referenced CLI names exist in the registry.

**Files:**
- Modify: `scripts/lib/crossai_config.py` (append after Task 2 dataclasses)
- Mirror: `.claude/scripts/lib/crossai_config.py`
- Test: `scripts/tests/test_crossai_config_resolve.py` (extend with Task 3 tests)

---

- [ ] **Step 1: Append failing tests to `scripts/tests/test_crossai_config_resolve.py`**

Append (after Task 02 tests):

```python


# ---- Task 03 tests ----


_SAMPLE_CONFIG = """\
crossai_clis:
  - name: "Codex-GPT-5.5"
    command: 'cat {context} | codex exec -m gpt-5.5 "{prompt}"'
    label: "Codex GPT 5.5"
    role: "primary"
  - name: "Gemini-Pro-1M"
    command: 'cat {context} | gemini -m cx/gemini-3.1-pro-preview -p "{prompt}" --yolo'
    label: "Gemini 3.1 Pro Preview"
    role: "primary"
  - name: "Claude-Sonnet-4.6"
    command: 'cat {context} | claude --model sonnet -p "{prompt}"'
    label: "Claude Sonnet 4.6"
    role: "verifier"

crossai_stages:
  scope:
    primary_clis: ["Gemini-Pro-1M", "Codex-GPT-5.5"]
    verifier_cli: "Claude-Sonnet-4.6"
  blueprint:
    primary_clis: ["Gemini-Pro-1M", "Codex-GPT-5.5"]
    verifier_cli: "Claude-Sonnet-4.6"
  build:
    primary_clis: ["Gemini-Pro-1M", "Codex-GPT-5.5"]
    verifier_cli: "Claude-Sonnet-4.6"
"""


def _seed_config(tmp_path, content=_SAMPLE_CONFIG):
    """Stage a vg.config.md at the canonical .claude/ path."""
    cfg_dir = tmp_path / ".claude"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "vg.config.md").write_text(content)
    return tmp_path


def test_resolve_stage_config_blueprint(tmp_path):
    """Resolve blueprint stage → 2 primaries + 1 verifier, by-name lookup."""
    from crossai_config import resolve_stage_config
    _seed_config(tmp_path)
    cfg = resolve_stage_config("blueprint", tmp_path)
    assert cfg.stage == "blueprint"
    assert [c.name for c in cfg.primary_clis] == ["Gemini-Pro-1M", "Codex-GPT-5.5"]
    assert cfg.verifier_cli.name == "Claude-Sonnet-4.6"
    assert cfg.verifier_cli.role == "verifier"


def test_resolve_stage_config_scope(tmp_path):
    from crossai_config import resolve_stage_config
    _seed_config(tmp_path)
    cfg = resolve_stage_config("scope", tmp_path)
    assert cfg.stage == "scope"
    assert len(cfg.primary_clis) == 2


def test_resolve_stage_config_build(tmp_path):
    from crossai_config import resolve_stage_config
    _seed_config(tmp_path)
    cfg = resolve_stage_config("build", tmp_path)
    assert cfg.stage == "build"


def test_resolve_stage_config_unknown_stage(tmp_path):
    """Unknown stage → ValueError."""
    from crossai_config import resolve_stage_config
    import pytest
    _seed_config(tmp_path)
    with pytest.raises(ValueError, match="unknown stage"):
        resolve_stage_config("nonsense", tmp_path)


def test_resolve_stage_config_missing_cli_reference(tmp_path):
    """`primary_clis` references a CLI not declared in `crossai_clis:` → ValueError."""
    from crossai_config import resolve_stage_config
    import pytest
    bad_config = _SAMPLE_CONFIG + """
crossai_stages:
  scope:
    primary_clis: ["DoesNotExist"]
    verifier_cli: "Claude-Sonnet-4.6"
"""
    # Override stages block (Python rsplit on the second crossai_stages: would
    # be ambiguous; just write a minimal config from scratch)
    minimal = """\
crossai_clis:
  - name: "Codex-GPT-5.5"
    command: 'cmd'
    label: "Codex"
    role: "primary"

crossai_stages:
  scope:
    primary_clis: ["DoesNotExist"]
    verifier_cli: "Codex-GPT-5.5"
"""
    _seed_config(tmp_path, content=minimal)
    with pytest.raises(ValueError, match="DoesNotExist"):
        resolve_stage_config("scope", tmp_path)


def test_resolve_stage_config_missing_stages_block(tmp_path):
    """vg.config.md has crossai_clis but no crossai_stages → ValueError pointing
    operator at lazy-migration command."""
    from crossai_config import resolve_stage_config
    import pytest
    minimal = """\
crossai_clis:
  - name: "Codex-GPT-5.5"
    command: 'cmd'
    label: "Codex"
"""
    _seed_config(tmp_path, content=minimal)
    with pytest.raises(ValueError, match="crossai_stages"):
        resolve_stage_config("blueprint", tmp_path)


def test_resolve_stage_config_no_config_file(tmp_path):
    """No vg.config.md anywhere → ValueError."""
    from crossai_config import resolve_stage_config
    import pytest
    with pytest.raises(ValueError, match="vg.config.md"):
        resolve_stage_config("blueprint", tmp_path)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -m pytest scripts/tests/test_crossai_config_resolve.py -v -k "test_resolve_stage_config"
```

Expected: 7 failures (`AttributeError: module 'crossai_config' has no attribute 'resolve_stage_config'`).

- [ ] **Step 3: Implement parser + resolver in `scripts/lib/crossai_config.py`**

Append to `scripts/lib/crossai_config.py` (after the `StageConfig` dataclass from Task 02):

```python


# ── crossai_clis full parser (extends Task 01 _parse_crossai_clis) ──────


def _parse_crossai_clis_full(config_text: str) -> list[CLISpec]:
    """Extract full CLISpec entries from `crossai_clis:` block.

    Format (markdown YAML-ish, indented):
        crossai_clis:
          - name: "Codex"
            command: 'cat ...'
            label: "Codex GPT 5.5"
            role: "primary"
          - name: "Gemini"
            command: 'cat ...'
            label: "Gemini Pro"
    """
    specs: list[CLISpec] = []
    in_block = False
    current: dict[str, str] = {}

    def _flush() -> None:
        if current.get("name"):
            specs.append(CLISpec(
                name=current["name"],
                command=current.get("command", ""),
                label=current.get("label", current["name"]),
                role=current.get("role", "primary"),
            ))
        current.clear()

    for line in config_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("crossai_clis:"):
            in_block = True
            continue
        if in_block:
            # End of block: next top-level YAML key (no indent + colon)
            if line and not line[0].isspace() and ":" in line and not stripped.startswith("- "):
                _flush()
                in_block = False
                continue
            if stripped.startswith("- name:"):
                _flush()
                m = re.match(r'-\s*name:\s*"?([^"\n]+?)"?\s*$', stripped)
                if m:
                    current["name"] = m.group(1)
            elif ":" in stripped:
                key, _, val = stripped.partition(":")
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key in ("command", "label", "role") and current.get("name"):
                    current[key] = val
    _flush()
    return specs


# ── crossai_stages parser ──────────────────────────────────────────────


def _parse_crossai_stages(config_text: str) -> dict[str, dict]:
    """Extract `crossai_stages:` block as nested dict.

    Returns:
        {
            "scope": {"primary_clis": ["A", "B"], "verifier_cli": "C"},
            "blueprint": {...},
            "build": {...},
        }
    """
    out: dict[str, dict] = {}
    in_block = False
    current_stage: str | None = None
    for line in config_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("crossai_stages:"):
            in_block = True
            continue
        if in_block:
            # End of block: next top-level YAML key (no indent + colon)
            if line and not line[0].isspace() and ":" in line:
                in_block = False
                current_stage = None
                continue
            # Stage key (one indent level)
            indent = len(line) - len(line.lstrip())
            if indent == 2 and stripped.endswith(":"):
                current_stage = stripped[:-1]
                out[current_stage] = {}
                continue
            if current_stage and indent >= 4:
                if "primary_clis:" in stripped:
                    # parse list: primary_clis: ["A", "B"]
                    list_str = stripped.split("primary_clis:", 1)[1].strip()
                    list_str = list_str.strip("[]")
                    items = [x.strip().strip('"').strip("'") for x in list_str.split(",") if x.strip()]
                    out[current_stage]["primary_clis"] = items
                elif "verifier_cli:" in stripped:
                    val = stripped.split("verifier_cli:", 1)[1].strip()
                    val = val.strip('"').strip("'")
                    out[current_stage]["verifier_cli"] = val if val else None
    return out


# ── resolve_stage_config public API ────────────────────────────────────


_VALID_STAGES = ("scope", "blueprint", "build")


def resolve_stage_config(stage: str, repo_root: Path) -> StageConfig:
    """Read `vg.config.md` and return a `StageConfig` for the requested stage.

    Args:
        stage: one of "scope", "blueprint", "build".
        repo_root: project root that contains `.claude/vg.config.md` (or
            `.vg/vg.config.md` as fallback).

    Raises:
        ValueError: missing config file, missing crossai_stages block,
            unknown stage, or stage references a CLI not in the registry.
    """
    if stage not in _VALID_STAGES:
        raise ValueError(
            f"unknown stage {stage!r}; must be one of {_VALID_STAGES}"
        )
    repo_root = Path(repo_root).resolve()
    cfg = _find_config(repo_root)
    if cfg is None:
        raise ValueError(
            f"vg.config.md not found under {repo_root}. Run "
            "`/vg:project --init-only` to generate one."
        )
    text = cfg.read_text(encoding="utf-8", errors="replace")
    clis = _parse_crossai_clis_full(text)
    by_name = {c.name: c for c in clis}
    stages = _parse_crossai_stages(text)
    if stage not in stages:
        raise ValueError(
            f"crossai_stages.{stage} block missing in "
            f"{cfg.relative_to(repo_root)}. Run "
            "`vg-orchestrator migrate-crossai` to add defaults."
        )
    stage_block = stages[stage]
    primary_names = stage_block.get("primary_clis") or []
    verifier_name = stage_block.get("verifier_cli")
    primary_specs: list[CLISpec] = []
    for name in primary_names:
        if name not in by_name:
            raise ValueError(
                f"crossai_stages.{stage}.primary_clis references "
                f"{name!r} but it is not declared in crossai_clis:"
            )
        primary_specs.append(by_name[name])
    verifier_spec: CLISpec | None = None
    if verifier_name:
        if verifier_name not in by_name:
            raise ValueError(
                f"crossai_stages.{stage}.verifier_cli references "
                f"{verifier_name!r} but it is not declared in crossai_clis:"
            )
        verifier_spec = by_name[verifier_name]
    return StageConfig(
        stage=stage,
        primary_clis=primary_specs,
        verifier_cli=verifier_spec,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -m pytest scripts/tests/test_crossai_config_resolve.py -v
```

Expected: all Task 02 + Task 03 tests pass (12 total so far).

- [ ] **Step 5: Sync mirror + commit**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
cp scripts/lib/crossai_config.py .claude/scripts/lib/crossai_config.py
git add scripts/lib/crossai_config.py \
        .claude/scripts/lib/crossai_config.py \
        scripts/tests/test_crossai_config_resolve.py
git commit -m "feat(crossai-config): resolve_stage_config(stage, repo_root)

M1 Task 03 — read vg.config.md crossai_clis + crossai_stages blocks,
return validated StageConfig for the requested stage. Validates CLI
name references; raises ValueError with actionable hints (run
`/vg:project --init-only` or migrate-crossai) on missing config/sections.

New helpers: _parse_crossai_clis_full (extends Task 01 _parse_crossai_clis
with command/label/role fields), _parse_crossai_stages (nested block).

Tests: 7 new (resolve scope/blueprint/build, unknown stage,
missing-cli reference, missing stages block, no config file).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```
