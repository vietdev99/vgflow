#!/usr/bin/env python3
"""Static check: every VG host command that benefits from reflection has a
reflection step wired. Enforces the "reflection mandatory at end of every step"
hard rule.

Exit 0 if all hosts have reflection. Exit 1 with per-file violation list
otherwise. Safe to run on a clean repo — read-only.

Host commands that MUST have reflection:
  - build.md (end-of-wave via 8.5 bootstrap_reflection_per_wave OR
    accumulation at phase-end — both implementations count)
  - blueprint.md (end of overall step via 2e_bootstrap_reflection)
  - scope.md (end of discussion)
  - review.md (end of review, after GOAL-COVERAGE-MATRIX written)

Detection: grep for either of these patterns in the host's markdown source:
  - <step name="*reflect*">                  (dedicated step)
  - <step name="*_bootstrap_reflection*">    (alternative naming)
  - Use skill: vg-reflector                  (inline invocation)
  - reflection-trigger.md                    (shared reference include)
"""

import re
import sys
from pathlib import Path


HOST_COMMANDS = {
    "build.md": "end-of-wave reflection (accumulate for multi-wave) → phase-end prompt",
    "blueprint.md": "end-of-step reflection after 2d crossai",
    "scope.md": "end-of-round reflection after final decision consolidation",
    "review.md": "end-of-review reflection after GOAL-COVERAGE-MATRIX",
}

# Any of these patterns counts as reflection present. We're permissive on
# structure — the *semantic* requirement is that reflector fires at step end,
# not that the step be named one specific way.
PATTERNS = [
    re.compile(r"<step name=\"[^\"]*reflect[^\"]*\">", re.IGNORECASE),
    re.compile(r"<step name=\"[^\"]*bootstrap_reflection[^\"]*\">", re.IGNORECASE),
    re.compile(r"Use skill:\s*vg-reflector", re.IGNORECASE),
    re.compile(r"reflection-trigger\.md", re.IGNORECASE),
]


def check_file(path: Path) -> tuple[bool, str]:
    if not path.exists():
        return (False, f"{path.name}: MISSING host command file")

    text = path.read_text(encoding="utf-8", errors="replace")
    for pat in PATTERNS:
        if pat.search(text):
            return (True, f"{path.name}: ✓ reflection wired ({pat.pattern[:60]}...)")
    return (False, f"{path.name}: ✗ no reflection step/skill reference found")


def main(argv: list[str]) -> int:
    base = Path(argv[1]) if len(argv) > 1 else Path(".claude/commands/vg")

    if not base.is_dir():
        print(f"\033[38;5;208mhost commands dir not found: {base}\033[0m")
        return 2

    violations = []
    passes = []

    for name, desc in HOST_COMMANDS.items():
        ok, msg = check_file(base / name)
        if ok:
            passes.append(msg)
        else:
            violations.append(f"  - {msg} — expected: {desc}")

    print(f"=== Reflection coverage check ({len(HOST_COMMANDS)} hosts) ===")
    for p in passes:
        print(f"  {p}")

    if violations:
        print()
        print(f"\033[38;5;208m{len(violations)} host(s) missing reflection wiring:\033[0m")
        for v in violations:
            print(v)
        print()
        print("Fix: add either a <step name=\"*_reflection*\"> block referencing")
        print("     reflection-trigger.md, OR an inline Use skill: vg-reflector")
        print("     invocation at end-of-step (per shared protocol).")
        return 1

    print()
    print(f"✓ All {len(HOST_COMMANDS)} host commands have reflection wiring")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
