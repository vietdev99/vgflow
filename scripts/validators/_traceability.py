"""Shared helpers for traceability validators (v2.46+).

Closes Phase 3.2 dogfood gap: AI bịa goal/decision/business-rule. Each
validator forms one link in the chain SPECS → CONTEXT → BLUEPRINT → BUILD
→ REVIEW → TEST → ACCEPT. Helpers here parse upstream artifacts so each
validator can cross-check downstream claims.

Migration: validators support `--severity warn` for pre-2026-05-01 phases
that don't have new traceability fields populated yet. Defaults to block.
"""
from __future__ import annotations

import os
import re
from pathlib import Path


def parse_yaml_frontmatter_block(body: str, key: str) -> str:
    """Extract YAML-style field value from goal block body.

    Goals in TEST-GOALS.md use `**Key:**` markdown OR `key:` YAML format.
    Tries both. Returns raw value (string) or empty string if not found.
    """
    # Try **Key:** markdown format
    m = re.search(
        rf"^\*\*{re.escape(key)}:?\*\*\s*(.+?)(?=^\*\*|\n##|\Z)",
        body,
        re.MULTILINE | re.DOTALL,
    )
    if m:
        return m.group(1).strip()
    # Try YAML key: value format
    m = re.search(
        rf"^{re.escape(key)}:\s*(.+?)(?=^\w+:|\n##|\Z)",
        body,
        re.MULTILINE | re.DOTALL,
    )
    if m:
        return m.group(1).strip()
    return ""


def parse_list_field(raw: str) -> list[str]:
    """Parse YAML inline list `[a, b, c]` OR comma-separated OR bullet list."""
    if not raw:
        return []
    raw = raw.strip().rstrip(",")
    # Inline list: [a, b, c]
    m = re.match(r"^\[(.*)\]$", raw, re.DOTALL)
    if m:
        items = [
            x.strip().strip('"').strip("'") for x in m.group(1).split(",") if x.strip()
        ]
        return items
    # Bullet list (markdown)
    if raw.lstrip().startswith("-"):
        return [
            line.lstrip("- ").strip().strip('"').strip("'")
            for line in raw.splitlines()
            if line.strip().startswith("-")
        ]
    # Comma-separated
    if "," in raw:
        return [x.strip().strip('"').strip("'") for x in raw.split(",") if x.strip()]
    # Single item
    return [raw.strip().strip('"').strip("'")]


def find_decision_in_context(decision_id: str, context_text: str) -> str | None:
    """Search CONTEXT.md for decision heading. Returns matched line or None.

    Decision IDs: D-XX (same-phase) or P3.D-XX (cross-phase). Strip the
    phase prefix to find local heading.
    """
    local_id = decision_id.split(".")[-1]  # "P3.D-46" → "D-46"
    pat = re.compile(
        rf"^##+\s*(?:\*\*)?{re.escape(local_id)}\b.*$",
        re.MULTILINE,
    )
    m = pat.search(context_text)
    if m:
        return m.group(0).strip()
    # Fallback — scan for "D-46" / "P3.D-46" anywhere in text
    if decision_id in context_text or local_id in context_text:
        return f"<inline reference to {decision_id} found, but no heading>"
    return None


def find_business_rule_in_log(rule_id: str, log_text: str) -> str | None:
    """Search DISCUSSION-LOG.md for business rule definition.

    Convention: "BR-NN: <statement>" or "**BR-NN**: <statement>".
    """
    pat = re.compile(
        rf"^[*]*\*?{re.escape(rule_id)}\*?[*]*:?\s*(.+?)$",
        re.MULTILINE,
    )
    m = pat.search(log_text)
    if m:
        return m.group(1).strip()
    return None


def find_section_anchor(spec_ref: str, repo_root: Path) -> bool:
    """Verify SPEC ref like 'SPECS.md#section-anchor' resolves to a heading.

    Walks the file path component, then checks for matching heading.
    """
    if "#" not in spec_ref:
        return False
    file_part, anchor = spec_ref.split("#", 1)
    # Resolve relative to current phase dir or repo root
    candidates = [
        repo_root / file_part,
        Path(os.environ.get("PHASE_DIR", "")) / file_part if os.environ.get("PHASE_DIR") else None,
    ]
    for path in candidates:
        if path and path.exists():
            text = path.read_text(encoding="utf-8", errors="replace")
            # Convert anchor (slug) to heading variants
            anchor_norm = anchor.lower().replace("_", "-").replace(" ", "-")
            for line in text.splitlines():
                if not line.startswith("#"):
                    continue
                heading = line.lstrip("#").strip()
                heading_slug = re.sub(r"[^\w\s-]", "", heading.lower()).strip().replace(" ", "-")
                if heading_slug == anchor_norm or anchor_norm in heading_slug:
                    return True
    return False


def text_similarity(a: str, b: str) -> float:
    """Naive Jaccard similarity on word tokens. 0..1.

    Used to check `expected_assertion` vs `asserted_quote` match without
    requiring exact verbatim (which would be too brittle).
    """
    if not a or not b:
        return 0.0
    tokens_a = set(re.findall(r"\w+", a.lower()))
    tokens_b = set(re.findall(r"\w+", b.lower()))
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union)


def get_traceability_mode() -> str:
    """Read VG_TRACEABILITY_MODE env. Default 'block' for new phases.

    Set 'warn' for migration phase — validators emit warnings but don't
    block run-complete. Per-validator can also accept --severity flag.
    """
    return os.environ.get("VG_TRACEABILITY_MODE", "block").lower()


def parse_goals_with_frontmatter(goals_text: str) -> list[dict]:
    """Parse TEST-GOALS.md goals with full frontmatter extraction.

    Returns list of dicts with: id, title, body (full text), and parsed
    fields: spec_ref, decisions, business_rules, flow_ref, api_contracts,
    expected_assertion, goal_class, priority, surface, mutation_evidence,
    persistence_check.
    """
    goals = []
    pattern = re.compile(
        r"^##\s+Goal\s+(G-[\w.-]+):?\s*(.*?)$"
        r"(?P<body>(?:(?!^##\s+Goal\s+).)*)",
        re.MULTILINE | re.DOTALL,
    )
    for m in pattern.finditer(goals_text):
        gid = m.group(1)
        title = m.group(2).strip()
        body = m.group("body") or ""
        goal = {
            "id": gid,
            "title": title,
            "body": body,
            "priority": parse_yaml_frontmatter_block(body, "Priority").lower() or "important",
            "surface": parse_yaml_frontmatter_block(body, "Surface").split()[0].strip().lower() or "ui",
            "spec_ref": parse_yaml_frontmatter_block(body, "spec_ref")
            or parse_yaml_frontmatter_block(body, "Spec ref"),
            "decisions": parse_list_field(
                parse_yaml_frontmatter_block(body, "decisions")
                or parse_yaml_frontmatter_block(body, "Decisions")
                or parse_yaml_frontmatter_block(body, "Dependencies")
            ),
            "business_rules": parse_list_field(
                parse_yaml_frontmatter_block(body, "business_rules")
                or parse_yaml_frontmatter_block(body, "Business rules")
            ),
            "flow_ref": parse_yaml_frontmatter_block(body, "flow_ref")
            or parse_yaml_frontmatter_block(body, "Flow ref"),
            "api_contracts": parse_list_field(
                parse_yaml_frontmatter_block(body, "api_contracts")
                or parse_yaml_frontmatter_block(body, "API contracts")
            ),
            "expected_assertion": parse_yaml_frontmatter_block(body, "expected_assertion")
            or parse_yaml_frontmatter_block(body, "Expected assertion")
            or parse_yaml_frontmatter_block(body, "Mutation evidence"),
            "goal_class": parse_yaml_frontmatter_block(body, "goal_class").lower()
            or parse_yaml_frontmatter_block(body, "Goal class").lower(),
            "mutation_evidence": parse_yaml_frontmatter_block(body, "Mutation evidence"),
            "persistence_check": parse_yaml_frontmatter_block(body, "Persistence check"),
        }
        goals.append(goal)
    return goals


# Goal class → minimum steps mapping (per scanner-report-contract RCRURD)
GOAL_CLASS_MIN_STEPS = {
    "readonly": 3,
    "mutation": 6,
    "approval": 8,
    "wizard": 10,
    "crud-roundtrip": 14,
    "webhook": 4,
}


def infer_goal_class(goal: dict) -> str:
    """Infer goal_class when not explicitly set (migration support)."""
    explicit = goal.get("goal_class", "").strip().lower()
    if explicit:
        return explicit
    surface = goal.get("surface", "").lower()
    me = (goal.get("mutation_evidence") or "").lower()
    title = (goal.get("title") or "").lower()
    if surface == "webhook" or "webhook" in title:
        return "webhook"
    if "approve" in title or "approval" in title or "reject" in title:
        return "approval"
    if "wizard" in title or "step 1" in title or "step 2" in title or "multi-step" in title:
        return "wizard"
    if "crud" in title or "round-trip" in title:
        return "crud-roundtrip"
    if me and any(
        k in me.lower() for k in ("create", "update", "delete", "submit", "200", "201")
    ):
        return "mutation"
    return "readonly"


def min_steps_for_goal(goal: dict) -> int:
    """Resolve min_steps threshold for a goal."""
    cls = infer_goal_class(goal)
    return GOAL_CLASS_MIN_STEPS.get(cls, 3)
