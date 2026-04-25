#!/usr/bin/env python3
"""
audit-rule-cards.py — sample rule cards + flag likely-wrong classifications.

Random samples N rules from generated cards, scores each rule's tag against
multiple semantic signals, and flags rules whose current tag conflicts with
the signals (likely misclassified).

Heuristics for "suspicious" classification:

  1. enforce-tagged rule whose linked validator's DESCRIPTION shares <2
     content words with rule text → weak link, may be wrong validator.

  2. remind-tagged rule whose body contains validator-name-like substring
     ("verify-X" or distinctive 9+ char token from a validator) → should
     be enforce instead.

  3. advisory-tagged rule whose body contains MUST/PHẢI/NEVER → too soft,
     should be remind.

  4. enforce → validator pair where rule body mentions a DIFFERENT
     validator's distinctive token → maybe wrong target.

Output: prints flagged rules with rationale. Operator reviews + decides
whether to adjust classifier or accept tag.

Usage:
  audit-rule-cards.py --sample 100         # random 100 rules across skills
  audit-rule-cards.py --skill vg-build     # all rules from one skill
  audit-rule-cards.py --tag enforce        # only enforce-tagged
  audit-rule-cards.py --suspicious-only    # only flagged ones
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent

RULE_LINE_RE = re.compile(
    # Match a rule line with tag + optional validator + body
    r"-\s+\[(enforce|remind|advisory)\]\s*"
    r"(?:\*\*([^*]+)\*\*\s*:\s*)?"
    r"([^\n]+?)"
    r"(?:\s*→\s*`([^`]+)`)?"
    r"\s*$",
    re.MULTILINE,
)

# Top rule pattern (R1..RN format)
TOP_RULE_RE = re.compile(
    r"^-\s+\*\*R(\d+)\s+—\s+([^*]+?)\*\*\s*\[(enforce|remind|advisory)\]"
    r"(?:\s*→\s*`([^`]+)`)?\s*\n\s+([^\n]+)",
    re.MULTILINE,
)


def collect_rules(skill_filter: str | None = None) -> list[dict]:
    """Read all RULES-CARDS.md files and extract rules with tags."""
    rules: list[dict] = []
    skills_dir = REPO_ROOT / ".codex" / "skills"
    for skill_dir in sorted(skills_dir.iterdir()):
        if not skill_dir.is_dir() or not skill_dir.name.startswith("vg-"):
            continue
        if skill_filter and skill_filter not in skill_dir.name:
            continue
        cards = skill_dir / "RULES-CARDS.md"
        if not cards.exists():
            continue
        text = cards.read_text(encoding="utf-8", errors="replace")

        # Split by step section to attach context
        current_step = "(top-level)"
        for line in text.splitlines():
            if line.startswith("### Step:"):
                m = re.search(r"`([^`]+)`", line)
                if m:
                    current_step = m.group(1)
                continue

            # Top-level rules (R1..RN)
            m_top = re.match(
                r"-\s+\*\*R(\d+)\s+—\s+([^*]+?)\*\*\s*\[(enforce|remind|advisory)\]"
                r"(?:\s*→\s*`([^`]+)`)?",
                line,
            )
            if m_top:
                rules.append({
                    "skill": skill_dir.name,
                    "step": current_step,
                    "id": f"R{m_top.group(1)}",
                    "title": m_top.group(2).strip(),
                    "tag": m_top.group(3),
                    "validator": m_top.group(4),
                    "body": "",  # filled later by next non-empty line
                    "kind": "top",
                })
                continue

            # Step-level rules: "- [tag] **MARKER**: body" or "- [tag] **MARKER**: body → `validator`"
            m = RULE_LINE_RE.match(line)
            if m:
                rules.append({
                    "skill": skill_dir.name,
                    "step": current_step,
                    "id": "",
                    "title": "",
                    "tag": m.group(1),
                    "validator": m.group(4),
                    "body": m.group(3).strip() if m.group(3) else "",
                    "marker": m.group(2),
                    "kind": "step",
                })

        # Second pass — fill body for top rules (next line after rule header)
        for i, line in enumerate(text.splitlines()):
            m_top = re.match(
                r"-\s+\*\*R(\d+)\s+—",
                line,
            )
            if m_top:
                # Next line(s) should be the body
                lines = text.splitlines()
                j = i + 1
                while j < len(lines) and not lines[j].strip():
                    j += 1
                if j < len(lines):
                    body = lines[j].strip()
                    # Find this rule and update body
                    for r in rules:
                        if (r["skill"] == skill_dir.name and
                            r["id"] == f"R{m_top.group(1)}" and
                            not r.get("body")):
                            r["body"] = body
                            break
    return rules


def load_validator_index() -> dict:
    """Load validator descriptions + name->desc-tokens index."""
    manifest_path = REPO_ROOT / ".claude" / "scripts" / "validators" / "dispatch-manifest.json"
    if not manifest_path.exists():
        return {}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return manifest.get("validators", {})


def desc_tokens(description: str) -> set[str]:
    """Extract distinctive words from validator description."""
    GENERIC = {
        "must", "phải", "rule", "rules", "check", "validate", "verify",
        "auto", "manual", "default", "live", "static",
        "with", "from", "into", "when", "where", "this", "that",
        "phase", "skill", "step", "command", "validator", "block",
        "warn", "error", "fail", "pass", "missing",
        "before", "after", "during", "while", "until",
        "code", "file", "files", "line", "lines", "list",
    }
    tokens = set(re.findall(r"[a-z][a-z0-9-]{3,}", description.lower()))
    return tokens - GENERIC


def audit_rule(rule: dict, validators: dict) -> list[str]:
    """Return list of issues found for this rule. Empty list = looks OK."""
    issues: list[str] = []
    text = (rule.get("title", "") + " " + rule.get("body", "")).lower()
    text_words = set(re.findall(r"[a-z][a-z0-9-]+", text))

    tag = rule["tag"]
    validator = rule.get("validator")

    # Heuristic 1: enforce-tagged rule with weak link to validator
    if tag == "enforce" and validator and validator in validators:
        v_desc = validators[validator].get("description", "")
        v_tokens = desc_tokens(v_desc)
        # Also include validator name tokens
        v_name_tokens = set(re.split(r"[-_]+", validator.lower()))
        v_name_tokens -= {"verify", "scan", "check"}
        all_v_tokens = v_tokens | v_name_tokens

        overlap = all_v_tokens & text_words
        if len(overlap) < 2:
            # Strong overlap requires 2+ shared words. Check for 1 distinctive.
            distinctive = any(len(t) >= 9 for t in overlap)
            if not distinctive:
                issues.append(
                    f"weak-validator-link: tag→{validator} but only "
                    f"{len(overlap)} content word(s) shared (need ≥2 or ≥9-char distinctive)"
                )

    # Heuristic 2: remind-tagged rule that mentions a verify-X validator name
    if tag == "remind":
        # Look for "verify-X" pattern in rule text
        verify_mentions = re.findall(r"\bverify-[a-z][a-z0-9-]+", text)
        for vm in verify_mentions:
            if vm in validators:
                issues.append(
                    f"remind-but-mentions-validator: rule body mentions {vm} — should be enforce?"
                )
                break
        # Also distinctive tokens
        for v_name in validators:
            v_tokens = set(re.split(r"[-_]+", v_name.lower())) - {"verify"}
            distinctive = {t for t in v_tokens if len(t) >= 10}
            if distinctive & text_words:
                # Possible enforce match missed
                pass  # commented — too noisy

    # Heuristic 3: advisory-tagged rule with imperative language
    if tag == "advisory":
        if re.search(r"\b(must|phải|never|không\s+bao\s+giờ|mandatory|required)\b",
                     text, re.IGNORECASE):
            # Skip if rule was tagged advisory by severity_hint (CONVENTION etc.)
            marker = rule.get("marker", "").upper()
            if marker not in ("CONVENTION", "REF", "FILES", "SKIP-WHEN", "FORMAT", "SCHEMA"):
                issues.append(
                    "advisory-but-imperative: body has MUST/PHẢI/NEVER — should be remind?"
                )

    # Heuristic 4: enforce → validator pair where text mentions DIFFERENT validator
    if tag == "enforce" and validator:
        verify_mentions = re.findall(r"\bverify-[a-z][a-z0-9-]+", text)
        other = [vm for vm in verify_mentions if vm != validator and vm in validators]
        if other:
            issues.append(
                f"validator-mismatch: tagged→{validator} but body mentions {other[0]}"
            )

    return issues


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sample", type=int, default=100,
                    help="Random sample size (default 100)")
    ap.add_argument("--skill", default=None,
                    help="Limit to one skill")
    ap.add_argument("--tag", choices=["enforce", "remind", "advisory"],
                    default=None)
    ap.add_argument("--suspicious-only", action="store_true",
                    help="Only show flagged rules")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    rules = collect_rules(args.skill)
    if args.tag:
        rules = [r for r in rules if r["tag"] == args.tag]

    print(f"Total rules collected: {len(rules)}")

    validators = load_validator_index()
    print(f"Validator index: {len(validators)} entries")
    print()

    # Random sample
    if args.sample and args.sample < len(rules):
        random.seed(args.seed)
        sampled = random.sample(rules, args.sample)
    else:
        sampled = rules

    audited = 0
    flagged = 0
    issue_counts: dict[str, int] = {}

    for r in sampled:
        issues = audit_rule(r, validators)
        audited += 1
        if issues:
            flagged += 1
            for issue in issues:
                kind = issue.split(":", 1)[0]
                issue_counts[kind] = issue_counts.get(kind, 0) + 1
            if not args.suspicious_only or issues:
                preview = (r.get("title") or r.get("body", ""))[:80]
                print(f"⚠ [{r['tag']:8s}] {r['skill']:25s} {r.get('id', ''):4s} {preview}")
                for issue in issues:
                    print(f"     ↳ {issue}")
                print()
        elif not args.suspicious_only:
            preview = (r.get("title") or r.get("body", ""))[:60]
            print(f"  [{r['tag']:8s}] {r['skill']:25s} {r.get('id', ''):4s} {preview}")

    print()
    print(f"Audited: {audited}")
    print(f"Flagged: {flagged} ({100*flagged//audited if audited else 0}%)")
    print()
    print("Issue distribution:")
    for kind, count in sorted(issue_counts.items(), key=lambda x: -x[1]):
        print(f"  {kind:30s}  {count}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
