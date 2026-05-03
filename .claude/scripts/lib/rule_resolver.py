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
        if r.get("severity") == "BLOCK" and not r.get("verification"):
            r = {**r, "severity": "ADVISORY", "demoted_reason": "no verification"}
        if _matches(scope, task_files):
            out.append(r)
    return out
