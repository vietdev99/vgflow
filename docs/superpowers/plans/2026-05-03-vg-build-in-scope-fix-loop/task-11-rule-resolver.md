<!-- Per-task plan file. Self-contained — execute as instructed. -->
<!-- Index: ../2026-05-03-vg-build-in-scope-fix-loop.md -->
<!-- Plan: 2026-05-03-vg-build-in-scope-fix-loop -->


## Task 11: L1 — Rule resolver (preventive, scope-matched)

**Files:**
- Create: `scripts/lib/rule_resolver.py`
- Test: `tests/test_rule_resolver.py`
- Modify: `commands/vg/_shared/build/waves-delegation.md` (capsule envelope adds bootstrap_rules)

- [ ] **Step 1: Write failing test**

Create `tests/test_rule_resolver.py`:

```python
"""Rule resolver — Codex feedback: scope-match instead of dump-all."""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent


def test_global_hard_rules_always_returned(tmp_path: Path) -> None:
    rules_file = tmp_path / "rules.yaml"
    rules_file.write_text(textwrap.dedent("""
        rules:
          - rule_id: i18n-required
            severity: BLOCK
            scope_match: { applies_when: always }
            verification: grep_negative
            verification_arg: "useTranslation\\\\|t\\\\("
            enforce: "Wrap user-facing strings with useTranslation()/t()."
          - rule_id: a11y-baseline
            severity: ADVISORY
            scope_match: { applies_when: file_ext_in, value: [".tsx"] }
            enforce: "Each interactive control must have aria-label or visible label."
    """).strip(), encoding="utf-8")

    sys.path.insert(0, str(REPO / "scripts" / "lib"))
    from rule_resolver import resolve_rules  # type: ignore

    rules = resolve_rules(rules_file=rules_file, task_files=["apps/api/src/billing/foo.ts"])
    rule_ids = {r["rule_id"] for r in rules}
    assert "i18n-required" in rule_ids
    assert "a11y-baseline" not in rule_ids  # task touches .ts (not .tsx)
    sys.path.remove(str(REPO / "scripts" / "lib"))


def test_scope_matched_rules_filtered_by_extension(tmp_path: Path) -> None:
    rules_file = tmp_path / "rules.yaml"
    rules_file.write_text(textwrap.dedent("""
        rules:
          - rule_id: a11y-baseline
            severity: ADVISORY
            scope_match: { applies_when: file_ext_in, value: [".tsx"] }
            enforce: "x"
    """).strip(), encoding="utf-8")

    sys.path.insert(0, str(REPO / "scripts" / "lib"))
    from rule_resolver import resolve_rules  # type: ignore

    rules_tsx = resolve_rules(rules_file=rules_file, task_files=["apps/web/Page.tsx"])
    rules_ts = resolve_rules(rules_file=rules_file, task_files=["apps/api/handler.ts"])
    assert any(r["rule_id"] == "a11y-baseline" for r in rules_tsx)
    assert not any(r["rule_id"] == "a11y-baseline" for r in rules_ts)
    sys.path.remove(str(REPO / "scripts" / "lib"))
```

- [ ] **Step 2: Run failing tests**

Run: `python3 -m pytest tests/test_rule_resolver.py -v`
Expected: 2 failures.

- [ ] **Step 3: Write the resolver**

Create `scripts/lib/rule_resolver.py`:

```python
"""rule_resolver — Codex blind-spot #5 + L1.

Replaces "dump every memory rule into capsule" with scope-matched injection.

Three rule classes:
  - GLOBAL HARD: always injected (small set; applies_when=always)
  - DOMAIN: injected when scope_match condition true for any task_file
  - ADVISORY: lookup-only; NOT auto-injected; subagent can request via
    `lookup_rule(rule_id)` if curious

Each rule MUST declare `verification` — if a rule cannot be verified, it
CANNOT be a blocking rule (gets demoted to ADVISORY).

Scope-match operators:
  applies_when: always
  applies_when: file_ext_in       value: [".tsx", ".ts"]
  applies_when: path_prefix_in    value: ["apps/web/"]
  applies_when: contains_keyword  value: ["axios.get", "fetch("]
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml  # type: ignore


def _matches(scope_match: dict, task_files: list[str]) -> bool:
    op = scope_match.get("applies_when", "always")
    val = scope_match.get("value", [])
    if op == "always":
        return True
    if op == "file_ext_in":
        return any(any(f.endswith(ext) for ext in val) for f in task_files)
    if op == "path_prefix_in":
        return any(any(f.startswith(p) for p in val) for f in task_files)
    if op == "contains_keyword":
        # Reading file contents is too expensive at resolve-time; defer to
        # subagent. Treat as "match" when any keyword present in any task_file
        # name as a coarse heuristic.
        return any(any(k in f for k in val) for f in task_files)
    return False


def resolve_rules(rules_file: Path, task_files: list[str]) -> list[dict[str, Any]]:
    """Load rules.yaml and return list of rules applying to the task scope."""
    if not rules_file.exists():
        return []
    data = yaml.safe_load(rules_file.read_text(encoding="utf-8")) or {}
    out: list[dict[str, Any]] = []
    for r in data.get("rules", []):
        scope = r.get("scope_match", {"applies_when": "always"})
        # Demote unverifiable BLOCK to ADVISORY
        if r.get("severity") == "BLOCK" and not r.get("verification"):
            r = {**r, "severity": "ADVISORY", "demoted_reason": "no verification"}
        if _matches(scope, task_files):
            out.append(r)
    return out
```

- [ ] **Step 4: Wire into capsule envelope (waves-delegation.md)**

Edit `commands/vg/_shared/build/waves-delegation.md`. Find the input envelope JSON shape (look for `task_id` field). Add:

```json
"bootstrap_rules": [
  /* resolved by orchestrator pre-spawn via:
     python3 .claude/scripts/lib/rule_resolver.py --rules .vg/BOOTSTRAP-RULES.yaml \
       --task-files <comma-list of files this task touches>
     Each rule has: rule_id, severity, enforce, verification (cmd), verification_arg.
     Subagent MUST honor BLOCK/TRIAGE_REQUIRED rules; ADVISORY are informational. */
],
```

- [ ] **Step 5: Run tests + commit**

Run:
```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -c "import yaml" 2>/dev/null || pip3 install pyyaml
python3 -m pytest tests/test_rule_resolver.py -v
git add scripts/lib/rule_resolver.py tests/test_rule_resolver.py commands/vg/_shared/build/waves-delegation.md
git commit -m "feat(build-fix-loop): add L1 scope-matched rule resolver + capsule wiring"
```
Expected: 2 passed.

---

