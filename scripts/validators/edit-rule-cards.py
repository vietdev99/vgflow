#!/usr/bin/env python3
"""
edit-rule-cards.py — manage operator-curated rule cards (manual layer).

Auto-extracted cards (RULES-CARDS.md) regenerate from skill body each
time extract-rule-cards.py runs. Operators sometimes need to:

  - Add a rule the auto-extractor missed (e.g., implicit conventions
    expressed in code rather than prose)
  - Override auto-tag (e.g., demote false-positive enforce → remind)
  - Add a domain-specific anti-pattern from past incidents

Manual rules live in a SEPARATE file: RULES-CARDS-MANUAL.md.
The inject helper (inject-rule-cards.sh) reads both auto + manual when
emitting cards at step start.

This CLI manages the manual layer.

Usage:

  Add a manual rule:
    edit-rule-cards.py add --skill vg-build --step 8c_executor_context \\
      --tag enforce --validator verify-context-refs \\
      --body "Each task <context-refs> must list relevant D-XX from CONTEXT.md"

  Add a top-level rule (applies to all steps):
    edit-rule-cards.py add --skill vg-build --top \\
      --tag remind --body "Always quote file paths with spaces in bash"

  Override auto-extracted rule's tag (when classifier got it wrong):
    edit-rule-cards.py override --skill vg-test --step 5b_runtime --rule-id 3 \\
      --new-tag remind --reason "validator doesn't actually exist for this"

  Add an anti-pattern with incident reference:
    edit-rule-cards.py add-anti --skill vg-review \\
      --step phase2_browser_discovery \\
      --body "❌ Don't use waitForLoadState('networkidle') — SPA polls forever; use 'domcontentloaded'" \\
      --incident "Phase 7.14.3 — 30s timeout in 22 spec locations"

  List manual rules for a skill:
    edit-rule-cards.py list --skill vg-build

  Remove a manual rule:
    edit-rule-cards.py remove --skill vg-build --rule-id MANUAL-3

Manual file format (.codex/skills/{skill}/RULES-CARDS-MANUAL.md):

  # MANUAL RULES — vg-build (operator-curated)
  >
  > Edited by operator. Preserved across `extract-rule-cards.py` re-runs.
  > Inject helper reads both this file AND auto RULES-CARDS.md at step start.

  ## Top-level (apply to ALL steps)

  - **MANUAL-1** [remind] Always quote file paths with spaces in bash
    *Added: 2026-04-26 by operator*

  ## Step: `8c_executor_context`

  - **MANUAL-2** [enforce] → `verify-context-refs`
    Each task <context-refs> must list relevant D-XX from CONTEXT.md
    *Added: 2026-04-26 by operator*

  ## Overrides (auto-rule tag corrections)

  - **OVERRIDE-1**: vg-test step 5b_runtime rule 3 → remind
    *Reason: validator doesn't actually exist for this*
    *Added: 2026-04-26*
"""
from __future__ import annotations

import argparse
import datetime
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent

VALID_TAGS = ("enforce", "remind", "advisory")


def manual_file_path(skill: str) -> Path:
    """Return path to manual cards file for given skill."""
    skill = skill.replace(".codex/skills/", "").rstrip("/")
    return REPO_ROOT / ".codex" / "skills" / skill / "RULES-CARDS-MANUAL.md"


def auto_file_path(skill: str) -> Path:
    return REPO_ROOT / ".codex" / "skills" / skill / "RULES-CARDS.md"


def init_manual_file(skill: str) -> str:
    # NOTE: section header levels MUST match auto RULES-CARDS.md format:
    #   ## Top-level (apply to ALL steps)   ← 2 hashes (top-level matches auto)
    #   ### Step: `step_name`               ← 3 hashes (step matches auto)
    #   ### Step: `step_name` — Anti-patterns
    #   ## Overrides (auto-rule tag corrections)
    # Inject helper awk script keys on these exact patterns to merge
    # auto + manual sections cleanly.
    return f"""# MANUAL RULES — {skill} (operator-curated)

> Edited by operator. Preserved across `extract-rule-cards.py` re-runs.
> Inject helper reads both this file AND auto RULES-CARDS.md at step start.
>
> Format conventions (header levels MUST match auto file format):
>   - Top-level rules:    `## Top-level (apply to ALL steps)`
>   - Per-step rules:     `### Step: \\`step_name\\``
>   - Anti-patterns:      `### Step: \\`step_name\\` — Anti-patterns`
>   - Overrides:          `## Overrides (auto-rule tag corrections)`

## Top-level (apply to ALL steps)

_(none yet — use `edit-rule-cards.py add --skill {skill} --top` to add)_

## Overrides (auto-rule tag corrections)

_(none yet — use `edit-rule-cards.py override` to add)_
"""


def read_manual(skill: str) -> str:
    path = manual_file_path(skill)
    if not path.exists():
        return init_manual_file(skill)
    return path.read_text(encoding="utf-8")


def write_manual(skill: str, content: str) -> None:
    path = manual_file_path(skill)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def next_id(content: str, prefix: str = "MANUAL") -> int:
    """Find next available ID number."""
    ids = re.findall(rf"\b{prefix}-(\d+)\b", content)
    if not ids:
        return 1
    return max(int(x) for x in ids) + 1


def find_or_create_section(content: str, header: str) -> tuple[str, int, int]:
    """Find or create a section header. Return (content_with_section, start_line, end_line).

    `header` must include leading `##` or `###` markers. Section ends at
    next equal-or-shallower header, or EOF.

    Examples:
      find_or_create_section(content, "## Top-level (apply to ALL steps)")
      find_or_create_section(content, "### Step: `0_parse_args`")
      find_or_create_section(content, "## Overrides (auto-rule tag corrections)")
    """
    lines = content.splitlines(keepends=True)
    # Determine header depth from leading hashes
    hash_count = len(header) - len(header.lstrip("#"))
    target = f"{header}\n"
    target_alt = f"{header}\r\n"

    # Find existing
    for i, line in enumerate(lines):
        if line == target or line == target_alt:
            # Find end of section: next header at SAME OR SHALLOWER depth
            j = i + 1
            while j < len(lines):
                stripped = lines[j].lstrip()
                if stripped.startswith("#"):
                    line_hashes = len(lines[j]) - len(lines[j].lstrip("#"))
                    if line_hashes <= hash_count:
                        break
                j += 1
            return content, i, j

    # Insert before "## Overrides" (always last) or at end
    insert_at = len(lines)
    for i, line in enumerate(lines):
        if line.startswith("## Overrides"):
            insert_at = i
            break

    new_section = f"\n{header}\n\n_(empty — pending content)_\n"
    new_lines = lines[:insert_at] + [new_section] + lines[insert_at:]
    new_content = "".join(new_lines)

    # Re-find boundaries
    return find_or_create_section(new_content, header)


def cmd_add(args: argparse.Namespace) -> int:
    if args.tag not in VALID_TAGS:
        sys.stderr.write(f"\033[38;5;208m--tag must be one of {VALID_TAGS}\033[0m\n")
        return 1
    if not args.body or len(args.body) < 10:
        sys.stderr.write("\033[38;5;208m--body must be ≥10 chars\033[0m\n")
        return 1

    content = read_manual(args.skill)
    rule_id = f"MANUAL-{next_id(content)}"
    today = datetime.date.today().isoformat()

    if args.top:
        section_header = "## Top-level (apply to ALL steps)"
    else:
        if not args.step:
            sys.stderr.write("\033[38;5;208m--step required (or use --top for global rule)\033[0m\n")
            return 1
        section_header = f"### Step: `{args.step}`"

    content, start, end = find_or_create_section(content, section_header)
    lines = content.splitlines(keepends=True)

    # Build new rule line
    validator_ref = f" → `{args.validator}`" if args.validator else ""
    new_rule_lines = [
        f"\n- **{rule_id}** [{args.tag}]{validator_ref}\n",
        f"  {args.body}\n",
        f"  *Added: {today}",
    ]
    if args.reason:
        new_rule_lines[-1] += f" — {args.reason}"
    new_rule_lines[-1] += "*\n"

    # Insert before end of section
    insert_at = end
    # Remove "(empty)" placeholder if present
    section_text = "".join(lines[start:end])
    if "(empty —" in section_text or "(none yet" in section_text:
        # Remove the placeholder line
        for i in range(start + 1, end):
            if "(empty" in lines[i] or "(none yet" in lines[i]:
                lines.pop(i)
                end -= 1
                insert_at = end
                break

    new_content = "".join(lines[:insert_at]) + "".join(new_rule_lines) + "".join(lines[insert_at:])
    write_manual(args.skill, new_content)
    print(f"✓ Added {rule_id} to {section_header} in {manual_file_path(args.skill).relative_to(REPO_ROOT)}")
    return 0


def cmd_override(args: argparse.Namespace) -> int:
    if args.new_tag not in VALID_TAGS:
        sys.stderr.write(f"\033[38;5;208m--new-tag must be one of {VALID_TAGS}\033[0m\n")
        return 1

    content = read_manual(args.skill)
    rule_id = f"OVERRIDE-{next_id(content, 'OVERRIDE')}"
    today = datetime.date.today().isoformat()

    content, start, end = find_or_create_section(content, "## Overrides (auto-rule tag corrections)")
    lines = content.splitlines(keepends=True)

    # Build override entry
    target = f"step `{args.step}` rule {args.rule_id}" if args.step else f"rule {args.rule_id}"
    new_lines = [
        f"\n- **{rule_id}**: {target} → **{args.new_tag}**\n",
    ]
    if args.validator:
        new_lines.append(f"  Set validator: `{args.validator}`\n")
    if args.reason:
        new_lines.append(f"  *Reason: {args.reason}*\n")
    new_lines.append(f"  *Added: {today}*\n")

    # Find insert point + remove placeholder
    insert_at = end
    section_text = "".join(lines[start:end])
    if "(none yet" in section_text or "(empty" in section_text:
        for i in range(start + 1, end):
            if "(none yet" in lines[i] or "(empty" in lines[i]:
                lines.pop(i)
                end -= 1
                insert_at = end
                break

    new_content = "".join(lines[:insert_at]) + "".join(new_lines) + "".join(lines[insert_at:])
    write_manual(args.skill, new_content)
    print(f"✓ Added {rule_id} to Overrides in {manual_file_path(args.skill).relative_to(REPO_ROOT)}")
    return 0


def cmd_add_anti(args: argparse.Namespace) -> int:
    if not args.body or len(args.body) < 10:
        sys.stderr.write("\033[38;5;208m--body must be ≥10 chars\033[0m\n")
        return 1

    content = read_manual(args.skill)
    rule_id = f"ANTI-{next_id(content, 'ANTI')}"
    today = datetime.date.today().isoformat()

    section_header = (
        f"### Step: `{args.step}` — Anti-patterns" if args.step
        else "## Anti-patterns (apply to ALL steps)"
    )
    content, start, end = find_or_create_section(content, section_header)
    lines = content.splitlines(keepends=True)

    body = args.body
    if not body.startswith("❌"):
        body = f"❌ {body}"

    new_lines = [
        f"\n- **{rule_id}** {body}\n",
    ]
    if args.incident:
        new_lines.append(f"  *Incident: {args.incident}*\n")
    new_lines.append(f"  *Added: {today}*\n")

    insert_at = end
    section_text = "".join(lines[start:end])
    if "(none yet" in section_text or "(empty" in section_text:
        for i in range(start + 1, end):
            if "(none yet" in lines[i] or "(empty" in lines[i]:
                lines.pop(i)
                end -= 1
                insert_at = end
                break

    new_content = "".join(lines[:insert_at]) + "".join(new_lines) + "".join(lines[insert_at:])
    write_manual(args.skill, new_content)
    print(f"✓ Added {rule_id} to {section_header}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    path = manual_file_path(args.skill)
    if not path.exists():
        print(f"(no manual rules yet for {args.skill})")
        return 0
    content = path.read_text(encoding="utf-8")

    rules = re.findall(r"^- \*\*(MANUAL-\d+)\*\*\s+\[([\w]+)\](?:\s*→\s*`([^`]+)`)?\s*\n\s+(.+?)(?=\n-|\n##|\Z)",
                       content, re.MULTILINE | re.DOTALL)
    overrides = re.findall(r"^- \*\*(OVERRIDE-\d+)\*\*\s*:\s*(.+?)$", content, re.MULTILINE)
    antis = re.findall(r"^- \*\*(ANTI-\d+)\*\*\s+(.+?)(?=\n-|\n##|\Z)", content, re.MULTILINE | re.DOTALL)

    print(f"Manual rules for {args.skill}:")
    print(f"  File: {path.relative_to(REPO_ROOT)}")
    print()

    if rules:
        print(f"  Rules ({len(rules)}):")
        for r_id, tag, validator, body in rules:
            v_str = f" → {validator}" if validator else ""
            print(f"    {r_id} [{tag}]{v_str}: {body.strip().split(chr(10))[0][:80]}")
    else:
        print("  Rules: (none)")
    print()

    if overrides:
        print(f"  Overrides ({len(overrides)}):")
        for o_id, body in overrides:
            print(f"    {o_id}: {body.strip()[:100]}")
    else:
        print("  Overrides: (none)")
    print()

    if antis:
        print(f"  Anti-patterns ({len(antis)}):")
        for a_id, body in antis:
            print(f"    {a_id}: {body.strip().split(chr(10))[0][:80]}")
    else:
        print("  Anti-patterns: (none)")

    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    path = manual_file_path(args.skill)
    if not path.exists():
        sys.stderr.write(f"\033[38;5;208mno manual file for {args.skill}\033[0m\n")
        return 1
    content = path.read_text(encoding="utf-8")

    pattern = rf"\n- \*\*{re.escape(args.rule_id)}\*\*.*?(?=\n- |\n##|\Z)"
    new_content, count = re.subn(pattern, "", content, flags=re.DOTALL)
    if count == 0:
        sys.stderr.write(f"\033[38;5;208m{args.rule_id} not found in {args.skill}\033[0m\n")
        return 1

    write_manual(args.skill, new_content)
    print(f"✓ Removed {args.rule_id} ({count} entry) from {args.skill}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    # add
    p_add = sub.add_parser("add", help="Add a manual rule")
    p_add.add_argument("--skill", required=True)
    p_add.add_argument("--step", default=None,
                       help="Step name (omit + use --top for global rule)")
    p_add.add_argument("--top", action="store_true",
                       help="Top-level rule applying to all steps")
    p_add.add_argument("--tag", choices=VALID_TAGS, required=True)
    p_add.add_argument("--validator", default=None,
                       help="Optional: link to validator (for enforce tags)")
    p_add.add_argument("--body", required=True, help="Rule body text")
    p_add.add_argument("--reason", default=None,
                       help="Optional: why this rule exists")

    # override
    p_o = sub.add_parser("override", help="Override an auto-extracted rule's tag")
    p_o.add_argument("--skill", required=True)
    p_o.add_argument("--step", default=None)
    p_o.add_argument("--rule-id", required=True,
                     help="The auto rule's R-id (e.g. R5) or step rule index")
    p_o.add_argument("--new-tag", choices=VALID_TAGS, required=True)
    p_o.add_argument("--validator", default=None)
    p_o.add_argument("--reason", required=True,
                     help="Why the auto-tag is wrong")

    # add-anti
    p_anti = sub.add_parser("add-anti", help="Add an anti-pattern with optional incident reference")
    p_anti.add_argument("--skill", required=True)
    p_anti.add_argument("--step", default=None)
    p_anti.add_argument("--body", required=True)
    p_anti.add_argument("--incident", default=None,
                        help="Optional: incident this anti-pattern came from")

    # list
    p_list = sub.add_parser("list", help="List manual rules for a skill")
    p_list.add_argument("--skill", required=True)

    # remove
    p_rm = sub.add_parser("remove", help="Remove a manual rule")
    p_rm.add_argument("--skill", required=True)
    p_rm.add_argument("--rule-id", required=True,
                      help="ID like MANUAL-3, OVERRIDE-1, ANTI-2")

    args = ap.parse_args()

    handlers = {
        "add": cmd_add,
        "override": cmd_override,
        "add-anti": cmd_add_anti,
        "list": cmd_list,
        "remove": cmd_remove,
    }
    return handlers[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
