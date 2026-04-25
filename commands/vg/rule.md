---
description: Quản lý rule cards qua mô tả tự nhiên — wrapper cho edit-rule-cards.py
argument-hint: "<intent> <skill> [step] <description>"
allowed-tools: Bash, Read
---

# /vg:rule — natural-language rule card management

Wrapper around `edit-rule-cards.py` that lets operator describe rule changes
in natural Vietnamese/English instead of remembering CLI flags.

**Source-of-truth skill body:** `.codex/skills/vg-rule/SKILL.md` (this file
is the slash-command stub — Skill tool routes invocation to that file).

## Quick examples

```
/vg:rule add vg-build: luôn quote file paths có spaces
/vg:rule add vg-test step 5d_codegen: đừng dùng networkidle
/vg:rule override vg-build R8 → remind, vì R8 là narrative thôi
/vg:rule list vg-build
/vg:rule xóa MANUAL-3 ở vg-build
```

## How it works

1. Parse `$ARGUMENTS` to detect intent: add | add-anti | override | list | remove
2. Extract fields: skill, step, tag, body, validator, reason
3. Show user the parsed fields → ask confirm/edit
4. Invoke `edit-rule-cards.py` with parsed args
5. Read back updated cards section as confirmation

See `.codex/skills/vg-rule/SKILL.md` for full parsing rules + edge cases.

## Process

Read the skill body for full workflow:

```bash
cat .codex/skills/vg-rule/SKILL.md
```

Then parse `$ARGUMENTS`, ask clarifications if needed, invoke CLI:

```bash
python3 .claude/scripts/validators/edit-rule-cards.py <subcommand> [...args]
```
