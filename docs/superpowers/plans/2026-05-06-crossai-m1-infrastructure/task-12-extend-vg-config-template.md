# Task 12: Extend `tests/fixtures/.../vg.config.md` template

**Goal:** Add commented default crossai sections (policy, heuristic_thresholds, role field, stages) to the canonical fixture used by tests + as project template. Sections are commented-out so existing fixture-based tests don't break; `/vg:project --init-only` or `migrate-crossai` will materialize them on real projects.

**Files:**
- Modify: `tests/fixtures/phase0-diagnostic-smoke/vg.config.md`
- Test: `scripts/tests/test_crossai_project_init_crossai.py` (extend with template-parity test)

---

- [ ] **Step 1: Append failing test**

Append to `scripts/tests/test_crossai_project_init_crossai.py`:

```python


# ---- Task 12 tests ----


def test_template_fixture_has_commented_crossai_sections():
    """The canonical fixture has commented examples of all new crossai
    sections so operators can uncomment + customize. Tests that depend on
    the fixture are not broken because sections start with `#`."""
    fixture = REPO_ROOT / "tests/fixtures/phase0-diagnostic-smoke/vg.config.md"
    content = fixture.read_text()
    # Each section header should appear, but commented (line starts with #)
    for marker in (
        "crossai:",
        "policy:",
        "heuristic_thresholds:",
        "crossai_stages:",
    ):
        # Find line containing marker
        lines_with_marker = [ln for ln in content.splitlines() if marker in ln]
        assert lines_with_marker, f"marker {marker!r} missing from template"
        # All occurrences should be commented (start with #)
        assert all(ln.lstrip().startswith("#") for ln in lines_with_marker), (
            f"marker {marker!r} should be commented in template; uncommented "
            f"lines found: {lines_with_marker}"
        )


def test_template_fixture_resolve_skips_commented_sections(tmp_path, monkeypatch):
    """resolve_stage_config() on the fixture-as-is should raise (sections
    commented out, so effectively missing). This proves `/vg:project --init-only` is
    needed on a fresh project copy."""
    fixture = REPO_ROOT / "tests/fixtures/phase0-diagnostic-smoke/vg.config.md"
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "vg.config.md").write_text(fixture.read_text())
    sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))
    from crossai_config import resolve_stage_config
    import pytest
    with pytest.raises(ValueError, match="crossai_stages"):
        resolve_stage_config("blueprint", tmp_path)
```

- [ ] **Step 2: Run tests to verify failure**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -m pytest scripts/tests/test_crossai_project_init_crossai.py::test_template_fixture_has_commented_crossai_sections \
                  scripts/tests/test_crossai_project_init_crossai.py::test_template_fixture_resolve_skips_commented_sections \
                  -v
```

Expected: 2 failures (markers missing from template).

- [ ] **Step 3: Append commented sections to the fixture**

Append to `tests/fixtures/phase0-diagnostic-smoke/vg.config.md`:

```markdown

# === CrossAI configuration (commented examples — uncomment + customize) ===
# Operators: run `/vg:project --init-only` to derive a populated config
# through the canonical generator path. Or `migrate-crossai --write` on existing
# projects to append missing fields without touching what's already set.
#
# Schema (Q6/Q7/Q23 of M1 spec):
#
# crossai_clis:
#   - name: "Codex-GPT-5.5"
#     command: 'cat {context} | codex exec -m gpt-5.5 "{prompt}"'
#     label: "Codex GPT 5.5"
#     role: "primary"           # primary | verifier
#   - name: "Gemini-Pro-1M"
#     command: 'cat {context} | gemini -m cx/gemini-3.1-pro-preview -p "{prompt}" --yolo'
#     label: "Gemini 3.1 Pro Preview (1M context)"
#     role: "primary"
#   - name: "Claude-Sonnet-4.6"
#     command: 'cat {context} | claude --model sonnet -p "{prompt}"'
#     label: "Claude Sonnet 4.6"
#     role: "verifier"
#
# crossai_stages:
#   scope:
#     primary_clis: ["Gemini-Pro-1M", "Codex-GPT-5.5"]
#     verifier_cli: "Claude-Sonnet-4.6"
#   blueprint:
#     primary_clis: ["Gemini-Pro-1M", "Codex-GPT-5.5"]
#     verifier_cli: "Claude-Sonnet-4.6"
#   build:
#     primary_clis: ["Gemini-Pro-1M", "Codex-GPT-5.5"]
#     verifier_cli: "Claude-Sonnet-4.6"
#
# crossai:
#   policy: "auto"   # strict | auto | off
#   heuristic_thresholds:
#     min_endpoints: 3
#     min_critical_goals: 2
#     min_plan_tasks: 5
# ===========================================================================
```

- [ ] **Step 4: Run tests**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -m pytest scripts/tests/test_crossai_project_init_crossai.py -v
```

Expected: all project-init CrossAI tests pass (Tasks 10 + 12).

- [ ] **Step 5: Commit**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
git add tests/fixtures/phase0-diagnostic-smoke/vg.config.md \
        scripts/tests/test_crossai_project_init_crossai.py
git commit -m "feat(template): commented crossai sections in canonical fixture

M1 Task 12 — extend tests/fixtures/phase0-diagnostic-smoke/vg.config.md
with commented examples of all new crossai sections (Q6/Q7/Q23 schema).
Operators uncomment + customize, or run `/vg:project --init-only` to
auto-populate through the canonical generator path. Existing tests using
the fixture are not broken because sections are commented.

Tests: 2 (template has commented markers; resolve still errors on
commented sections — proves migration is needed for real projects).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```
