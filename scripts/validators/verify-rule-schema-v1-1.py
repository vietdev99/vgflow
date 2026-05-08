#!/usr/bin/env python3
"""Validate rule frontmatter against meta-memory v1.1 schema.

Exit 0 = valid. Exit 1 = invalid (stderr explains why). Exit 2 = usage error.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ALLOWED_TARGET_STEPS = {
    "scope", "blueprint", "build", "review", "test", "accept",
    "deploy", "roam", "amend", "global",
}
ALLOWED_TYPES = {"declarative", "procedural", "rule", "config_override", "patch", "retract"}
ALLOWED_AUTHORITY = {"advisory", "reference"}  # NOT executable in v1

RELATIVE_DATE_RE = re.compile(
    r"\b(yesterday|today|tomorrow|"
    r"last\s+(week|month|year)|"
    r"next\s+(week|month|year))\b",
    re.IGNORECASE,
)


def parse_rule(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError("rule file must start with YAML frontmatter `---`")
    rest = text[4:]
    end = rest.find("\n---\n")
    if end < 0:
        raise ValueError("frontmatter not closed with `---`")
    front = yaml.safe_load(rest[:end]) or {}
    if not isinstance(front, dict):
        raise ValueError("frontmatter must be a YAML mapping")
    body = rest[end + 5:]
    return front, body


def validate(front: dict, body: str) -> list[str]:
    errors: list[str] = []

    target_step = front.get("target_step")
    if target_step not in ALLOWED_TARGET_STEPS:
        errors.append(
            f"target_step={target_step!r} invalid; must be one of {sorted(ALLOWED_TARGET_STEPS)}"
        )

    rtype = front.get("type", "declarative")
    if rtype not in ALLOWED_TYPES:
        errors.append(
            f"type={rtype!r} invalid; must be one of {sorted(ALLOWED_TYPES)}"
        )

    authority = front.get("authority", "advisory")
    if authority not in ALLOWED_AUTHORITY:
        errors.append(
            f"authority={authority!r} invalid; must be one of {sorted(ALLOWED_AUTHORITY)} "
            f"(executable BLOCKED in v1)"
        )

    if rtype == "procedural":
        if not front.get("sequence"):
            errors.append("procedural rule requires non-empty sequence[]")
        if not front.get("success_signals"):
            errors.append("procedural rule requires non-empty success_signals[]")
        if front.get("attribution_required") is not True:
            errors.append("procedural rule requires attribution_required: true")
    else:
        if front.get("sequence"):
            errors.append(
                f"non-procedural rule (type={rtype!r}) must NOT define sequence[]"
            )

    if RELATIVE_DATE_RE.search(body):
        errors.append(
            "rule body contains relative date (yesterday/today/last week/etc); "
            "use absolute YYYY-MM-DD"
        )

    return errors


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(
            "usage: verify-rule-schema-v1-1.py <rule.md>",
            file=sys.stderr,
        )
        return 2
    try:
        front, body = parse_rule(Path(argv[1]))
    except (OSError, ValueError, yaml.YAMLError) as e:
        print(f"parse error: {e}", file=sys.stderr)
        return 1
    errors = validate(front, body)
    if errors:
        for err in errors:
            print(f"INVALID: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
