"""block_severity — single source of truth for severity → behavior mapping.

Severity levels:
  warn     — log only; Stop hook does NOT exit 2 on warn-only obligations
  error    — default; orange ANSI; Stop hook exits 2 if unpaired
  critical — red ANSI; Stop hook exits 2 + injects AskUserQuestion hint;
             refire (Task 28) >= 2 escalates to mandatory user question

Behavior table is LOCKED. Adding a new severity requires updating this
module, the Stop hook query, AND the test matrix.
"""
from __future__ import annotations

from dataclasses import dataclass

VALID_SEVERITIES = ("warn", "error", "critical")
DEFAULT_SEVERITY = "error"

ANSI_ORANGE = "\033[38;5;208m"
ANSI_RED = "\033[31m"
ANSI_YELLOW = "\033[33m"
ANSI_RESET = "\033[0m"


@dataclass(frozen=True)
class SeverityBehavior:
    severity: str
    ansi_color: str
    exits_stop_hook: bool
    requires_handled: bool
    forces_user_question: bool


BEHAVIORS: dict[str, SeverityBehavior] = {
    "warn": SeverityBehavior(
        severity="warn",
        ansi_color=ANSI_YELLOW,
        exits_stop_hook=False,
        requires_handled=False,
        forces_user_question=False,
    ),
    "error": SeverityBehavior(
        severity="error",
        ansi_color=ANSI_ORANGE,
        exits_stop_hook=True,
        requires_handled=True,
        forces_user_question=False,
    ),
    "critical": SeverityBehavior(
        severity="critical",
        ansi_color=ANSI_RED,
        exits_stop_hook=True,
        requires_handled=True,
        forces_user_question=True,
    ),
}


def normalize(s: str | None) -> str:
    """Map None/empty/invalid → DEFAULT_SEVERITY. Lowercase normalize."""
    if not s:
        return DEFAULT_SEVERITY
    s = s.strip().lower()
    return s if s in VALID_SEVERITIES else DEFAULT_SEVERITY


def behavior(severity: str | None) -> SeverityBehavior:
    return BEHAVIORS[normalize(severity)]


def ansi_for(severity: str | None) -> str:
    return behavior(severity).ansi_color


def should_escalate(severity: str | None, fire_count: int) -> bool:
    """Critical severity + fire_count >= 2 (refire) → escalate to user question."""
    b = behavior(severity)
    return b.severity == "critical" and fire_count >= 2
