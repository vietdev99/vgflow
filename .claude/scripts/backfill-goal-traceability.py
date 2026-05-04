#!/usr/bin/env python3
"""Backfill v2.46 traceability fields in TEST-GOALS.md.

Reads existing goal frontmatter (Priority, Surface, Trigger, Success criteria,
Mutation evidence, Persistence check, Dependencies, Implemented by, Infra deps)
and adds:
  - spec_ref: SPECS.md anchor matched by topic keyword
  - decisions: extracted from title parenthetical (P3.D-XX) + Dependencies field
  - business_rules: empty for now (DISCUSSION-LOG doesn't have BR-NN convention)
  - flow_ref: derived for surface=ui multi-step goals
  - api_contracts: extracted from Trigger field if mentions /api/...
  - expected_assertion: synthesized from Mutation evidence + Success criteria
  - goal_class: inferred from title + surface + priority + mutation_evidence

Migration mode: by default outputs a new file alongside original
(`TEST-GOALS.backfilled.md`). Pass `--apply` to overwrite TEST-GOALS.md after
reviewing the dry-run diff.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path


def _zero_pad(phase: str) -> str:
    if "." in phase and not phase.split(".", 1)[0].startswith("0"):
        head, tail = phase.split(".", 1)
        return f"{head.zfill(2)}.{tail}"
    return phase


def find_phase_dir(repo_root: Path, phase: str) -> Path:
    phases_dir = repo_root / ".vg" / "phases"
    candidates = []
    for prefix in (phase, _zero_pad(phase)):
        candidates.extend(sorted(phases_dir.glob(f"{prefix}-*")))
    if not candidates:
        raise FileNotFoundError(f"phase {phase!r} not found under {phases_dir}")
    return candidates[0]


def slugify(s: str) -> str:
    return re.sub(r"[^\w\s-]", "", s.lower()).strip().replace(" ", "-")


def parse_specs_anchors(text: str) -> dict[str, str]:
    """Build slug-to-heading map for SPECS.md."""
    anchors: dict[str, str] = {}
    for line in text.splitlines():
        m = re.match(r"^(#{1,4})\s+(.+?)\s*$", line)
        if not m:
            continue
        heading = m.group(2).strip()
        slug = slugify(heading)
        anchors[slug] = heading
    return anchors


def best_spec_match(
    title: str,
    anchors: dict[str, str],
    extra_keywords: list[str] | None = None,
    decision_texts: dict[str, str] | None = None,
    decisions_cited: list[str] | None = None,
) -> str:
    """Pick best SPECS section anchor by multi-source keyword overlap.

    Sources combined for matching:
      1. title (primary signal)
      2. extra_keywords (Trigger + Success criteria + Mutation evidence)
      3. decision headings cited by goal (e.g., P3.D-46 -> "Fraud Prevention")

    Topic mapping fallback for common Phase 3.2 patterns:
      - topup/Tier 1/instant/PayPal -> topup section
      - withdraw/cooling/2FA -> withdraw section
      - transfer/group -> transfer section
      - chargeback/fraud -> fraud section
      - currency/preference/FX -> fx section
    """
    # Build search corpus
    corpus = title.lower()
    if extra_keywords:
        corpus += " " + " ".join(str(k).lower() for k in extra_keywords)
    if decision_texts and decisions_cited:
        for d in decisions_cited:
            local = d.split(".")[-1]
            if local in decision_texts:
                corpus += " " + decision_texts[local].lower()

    corpus_words = set(re.findall(r"\w{4,}", corpus))

    # Domain topic mapping: boost score for known finance/admin terms.
    TOPIC_BOOSTS = {
        "topup": ["topup", "instant", "tier"],
        "withdraw": ["withdraw", "cooling", "velocity"],
        "transfer": ["transfer", "group"],
        "fraud": ["fraud", "suspicious", "flag"],
        "chargeback": ["chargeback", "shortfall", "outstanding"],
        "fx": ["currency", "preference", "exchange"],
        "gateway": ["gateway", "paypal", "stripe", "lianlian", "sunrate", "pingpong", "worldfirst", "airwallex", "bank"],
        "linked": ["linked", "account", "bank"],
    }

    best_slug, best_score = None, 0
    for slug, heading in anchors.items():
        slug_lower = slug.lower()
        slug_words = set(re.findall(r"\w{4,}", slug_lower))
        score = len(corpus_words & slug_words)

        # Topic boost: if title contains topic keyword AND slug contains it, +3
        for topic, kws in TOPIC_BOOSTS.items():
            for kw in kws:
                if kw in corpus and kw in slug_lower:
                    score += 3

        if score > best_score:
            best_slug, best_score = slug, score

    if best_slug and best_score > 0:
        return f"SPECS.md#{best_slug}"

    # Final fallback: first SPECS heading (phase title); guarantees no gap.
    # User can refine to specific section later if mapping needs to be precise.
    if anchors:
        first_slug = next(iter(anchors))
        return f"SPECS.md#{first_slug}"
    return ""


def extract_decisions_from_title(title: str) -> list[str]:
    """Extract decision IDs from title parenthetical (e.g. '(P3.D-46, P3.D-31)')."""
    return re.findall(r"\b(P?\d*\.?D-\d+)\b", title)


def parse_field(body: str, name: str) -> str:
    m = re.search(
        rf"^\*\*{re.escape(name)}:?\*\*\s*(.+?)(?=^\*\*|\n##|\Z)",
        body,
        re.MULTILINE | re.DOTALL,
    )
    return m.group(1).strip() if m else ""


def extract_decisions_from_field(value: str) -> list[str]:
    """Pull decision IDs from a Dependencies/Decisions field text."""
    return list(set(re.findall(r"\b(P?\d*\.?D-\d+)\b", value)))


def infer_goal_class(title: str, surface: str, mutation_evidence: str) -> str:
    """Pick goal_class from heuristics."""
    title_l = title.lower()
    surface_l = surface.lower()
    me_l = mutation_evidence.lower()

    if surface_l == "webhook" or "webhook" in title_l:
        return "webhook"
    if any(k in title_l for k in ("approve", "approval", "reject")):
        return "approval"
    if any(k in title_l for k in ("wizard", "step 1", "step 2", "multi-step")):
        return "wizard"
    if "crud" in title_l or "round-trip" in title_l:
        return "crud-roundtrip"
    if me_l and any(k in me_l for k in ("create", "update", "delete", "submit", "200", "201", "ledger commit", "tx_group")):
        return "mutation"
    if surface_l in ("ui", "ui-mobile") and any(k in title_l for k in ("create", "edit", "delete", "submit", "save")):
        return "mutation"
    return "readonly"


def synthesize_expected_assertion(mutation_evidence: str, success_criteria: str) -> str:
    """Combine existing fields into expected_assertion."""
    parts: list[str] = []
    if mutation_evidence:
        parts.append(mutation_evidence.strip())
    if success_criteria:
        # Take first 2 bullet points or first 200 chars
        criteria = success_criteria.strip()
        if criteria:
            parts.append(criteria[:300])
    if not parts:
        return ""
    combined = " | ".join(parts)
    # Compress whitespace
    return re.sub(r"\s+", " ", combined).strip()[:500]


def extract_api_contracts_from_fields(*fields: str) -> list[str]:
    """Find /api/... patterns across multiple text fields."""
    found: set[str] = set()
    for f in fields:
        if not f:
            continue
        # Strip trailing punctuation/backticks from URLs
        for url in re.findall(r"/api/v\d+/[^\s,()`'\"\\}]+", f):
            url = url.rstrip(".,;:`'\"")
            found.add(url)
    return sorted(found)


def parse_context_decisions(context_text: str) -> dict[str, str]:
    """Map decision_id to heading text. e.g. {'D-46': 'Fraud Prevention & Chargeback'}."""
    decisions: dict[str, str] = {}
    pattern = re.compile(
        r"^#{2,4}\s*(?:P\d*\.?)?(D-\d+):?\s*(.+?)\s*$",
        re.MULTILINE,
    )
    for m in pattern.finditer(context_text):
        decisions[m.group(1)] = m.group(2).strip()
    return decisions


def parse_contracts_endpoints(contracts_text: str) -> set[str]:
    """Extract /api/v1/... endpoint patterns from API-CONTRACTS.md."""
    endpoints: set[str] = set()
    for url in re.findall(r"/api/v\d+/[^\s,()`'\"\\}|]+", contracts_text):
        endpoints.add(url.rstrip(".,;:`'\""))
    return endpoints


def match_api_contracts_by_topic(title: str, all_endpoints: set[str]) -> list[str]:
    """Cross-reference title topic against API-CONTRACTS endpoint list.

    Falls back when extract_api_contracts_from_fields finds nothing in trigger.
    """
    title_lower = title.lower()
    matched: list[str] = []
    # Topic-to-URL substring match
    topics_to_paths = [
        ("topup", "/topup"),
        ("withdraw", "/withdraw"),
        ("transfer", "/transfer"),
        ("linked", "/linked-account"),
        ("bank account", "/bank-account"),
        ("fx rate", "/fx"),
        ("currency", "/preferences"),
        ("fraud", "/fraud"),
        ("chargeback", "/chargeback"),
        ("cooling period", "/cooling-period"),
        ("merchant", "/merchants"),
        ("admin", "/admin"),
        ("webhook", "/webhooks"),
    ]
    for topic, substring in topics_to_paths:
        if topic in title_lower:
            for ep in all_endpoints:
                if substring in ep:
                    matched.append(ep)
    return sorted(set(matched))[:5]  # Cap at 5 to avoid bloat


def build_frontmatter_block(goal: dict) -> str:
    """Build YAML-style traceability frontmatter for a goal."""
    lines = []

    if goal["spec_ref"]:
        lines.append(f"**spec_ref:** {goal['spec_ref']}")
    if goal["decisions"]:
        lines.append(f"**decisions:** [{', '.join(goal['decisions'])}]")
    if goal["business_rules"]:
        lines.append(f"**business_rules:** [{', '.join(goal['business_rules'])}]")
    else:
        lines.append("**business_rules:** []  # backfilled; DISCUSSION-LOG had no BR-NN convention; user may add later")
    if goal["flow_ref"]:
        lines.append(f"**flow_ref:** {goal['flow_ref']}")
    if goal["api_contracts"]:
        lines.append(f"**api_contracts:** [{', '.join(goal['api_contracts'])}]")
    lines.append(f"**goal_class:** {goal['goal_class']}")
    if goal["expected_assertion"]:
        lines.append(f"**expected_assertion:** |\n  {goal['expected_assertion']}")

    return "\n".join(lines)


def process_goal_block(
    match: re.Match,
    anchors: dict[str, str],
    decision_texts: dict[str, str],
    contract_endpoints: set[str],
    phase: str,
) -> str:
    """Augment one goal block with traceability frontmatter."""
    full = match.group(0)
    gid = match.group(1)
    title = match.group(2).strip()
    body = match.group("body") or ""

    # Skip if already has spec_ref (idempotent)
    if "spec_ref:" in body or "**spec_ref" in body.lower():
        return full

    # Extract existing fields
    priority = parse_field(body, "Priority").lower() or "important"
    surface = parse_field(body, "Surface").split()[0].strip().lower() or "ui"
    mutation_evidence = parse_field(body, "Mutation evidence")
    success_criteria = parse_field(body, "Success criteria")
    persistence_check = parse_field(body, "Persistence check")
    trigger = parse_field(body, "Trigger")
    dependencies = parse_field(body, "Dependencies")
    actor = parse_field(body, "Actor") or parse_field(body, "Actors")

    # Build new fields
    decisions = list(set(
        extract_decisions_from_title(title) + extract_decisions_from_field(dependencies)
    ))

    # spec_ref: combine multiple keyword sources for robust matching
    extra_keywords = [trigger, success_criteria, mutation_evidence, actor]
    spec_ref = best_spec_match(
        title,
        anchors,
        extra_keywords=extra_keywords,
        decision_texts=decision_texts,
        decisions_cited=decisions,
    )

    # api_contracts: extract from all action/observable fields, fallback to topic match
    api_contracts = extract_api_contracts_from_fields(
        trigger, mutation_evidence, persistence_check, success_criteria
    )
    if not api_contracts:
        api_contracts = match_api_contracts_by_topic(title, contract_endpoints)

    goal_class = infer_goal_class(title, surface, mutation_evidence)
    expected_assertion = synthesize_expected_assertion(mutation_evidence, success_criteria)

    flow_ref = ""
    if surface in ("ui", "ui-mobile") and goal_class in ("wizard", "crud-roundtrip", "approval", "mutation"):
        # Topic-based flow_ref guess for common finance/admin workflow names.
        title_lower = title.lower()
        flow_topics = [
            ("topup", "topup-flow"),
            ("withdraw", "withdraw-flow"),
            ("transfer", "transfer-flow"),
            ("linked", "linked-accounts-flow"),
            ("bank account", "bank-accounts-flow"),
            ("currency", "currency-preference-flow"),
            ("preference", "currency-preference-flow"),
            ("fraud", "fraud-flag-flow"),
            ("suspicious", "fraud-flag-flow"),
            ("chargeback", "chargeback-flow"),
            ("cooling", "cooling-period-flow"),
            ("permission", "withdraw-permission-flow"),
            ("gateway", "gateway-settings-flow"),
            ("fx", "fx-rate-flow"),
            ("imap", "imap-config-flow"),
            ("admin", "admin-merchant-flow"),
        ]
        for topic, anchor in flow_topics:
            if topic in title_lower:
                flow_ref = f"FLOW-SPEC.md#{anchor}"
                break
        # Final fallback: surface-based
        if not flow_ref:
            phase_anchor = slugify(f"phase {phase} general flow")
            flow_ref = f"FLOW-SPEC.md#{phase_anchor}"

    goal = {
        "spec_ref": spec_ref,
        "decisions": decisions,
        "business_rules": [],
        "flow_ref": flow_ref,
        "api_contracts": api_contracts,
        "goal_class": goal_class,
        "expected_assertion": expected_assertion,
    }

    frontmatter = build_frontmatter_block(goal)

    # Insert frontmatter right after the title line, before existing **Priority:**
    new_body = body
    # Find first **Priority:** line and insert frontmatter before it
    insert_match = re.search(r"^\*\*Priority:?\*\*", new_body, re.MULTILINE)
    if insert_match:
        idx = insert_match.start()
        new_body = (
            new_body[:idx]
            + "<!-- v2.46 traceability backfill (review + edit if needed) -->\n"
            + frontmatter
            + "\n\n"
            + new_body[idx:]
        )
    else:
        new_body = (
            "\n<!-- v2.46 traceability backfill -->\n"
            + frontmatter
            + "\n\n"
            + new_body
        )

    return f"## Goal {gid}: {title}\n{new_body}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill v2.46 traceability fields in a phase TEST-GOALS.md",
    )
    parser.add_argument("--phase", required=True, help="Phase number, e.g. 3.2")
    parser.add_argument(
        "--repo-root",
        default=os.environ.get("VG_REPO_ROOT") or os.getcwd(),
        help="Repository root (default: VG_REPO_ROOT or cwd)",
    )
    parser.add_argument(
        "--output",
        help="Output path. Default: <phase>/TEST-GOALS.backfilled.md",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Overwrite TEST-GOALS.md instead of writing the sidecar file",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()
    phase_dir = find_phase_dir(repo_root, args.phase)
    goals_path = phase_dir / "TEST-GOALS.md"
    specs_path = phase_dir / "SPECS.md"
    context_path = phase_dir / "CONTEXT.md"
    contracts_path = phase_dir / "API-CONTRACTS.md"
    out_path = Path(args.output).resolve() if args.output else phase_dir / "TEST-GOALS.backfilled.md"

    if not goals_path.exists():
        print(f"ERROR: {goals_path} not found", file=sys.stderr)
        sys.exit(1)

    goals_text = goals_path.read_text(encoding="utf-8")
    specs_text = specs_path.read_text(encoding="utf-8") if specs_path.exists() else ""
    context_text = context_path.read_text(encoding="utf-8") if context_path.exists() else ""
    contracts_text = contracts_path.read_text(encoding="utf-8") if contracts_path.exists() else ""

    anchors = parse_specs_anchors(specs_text) if specs_text else {}
    decision_texts = parse_context_decisions(context_text) if context_text else {}
    contract_endpoints = parse_contracts_endpoints(contracts_text) if contracts_text else set()

    print(
        f"Loaded: {len(anchors)} SPECS anchors, {len(decision_texts)} decision headings, "
        f"{len(contract_endpoints)} contract endpoints"
    )

    pattern = re.compile(
        r"^##\s+Goal\s+(G-[\w.-]+):?\s*(.*?)$"
        r"(?P<body>(?:(?!^##\s+Goal\s+).)*)",
        re.MULTILINE | re.DOTALL,
    )

    new_text = pattern.sub(
        lambda m: process_goal_block(
            m,
            anchors,
            decision_texts,
            contract_endpoints,
            args.phase,
        ),
        goals_text,
    )

    write_path = goals_path if args.apply else out_path
    write_path.write_text(new_text, encoding="utf-8")
    goal_count = len(pattern.findall(goals_text))
    print(f"OK: Backfilled {goal_count} goals -> {write_path}")
    if not args.apply:
        print(f"  Review diff: diff {goals_path} {write_path}")
        print(f"  Apply: python3 .claude/scripts/backfill-goal-traceability.py --phase {args.phase} --apply")


if __name__ == "__main__":
    main()
