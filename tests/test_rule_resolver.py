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
