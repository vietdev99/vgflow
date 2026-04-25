#!/usr/bin/env python3
"""inventory-skill-rules — scan VG skill markdown files, extract rules,
classify by enforceability.

PURPOSE:
  User feedback (2026-04-25):
    "phải xử lý được hết những gì đang note trong markdown, ở mức chi
     tiết nhất, phải có phương án enforce phù hợp với phase đang làm ở
     nền tảng nào, ngữ cảnh nào, môi trường gì"

  44 SKILL.md files contain hundreds of "MUST"/"PHẢI"/"BẮT BUỘC"/"NEVER"
  rules. AI lazy-reads markdown — many slip silently. This script
  inventories every rule + classifies whether it CAN be code-enforced
  (and proposes a validator name) or is inherently prose-only (advice,
  context-explanation, taste).

CLASSIFICATION:
  enforceable           — rule asserts a structural/textual/runtime fact
                          that can be checked statically or at runtime
  semi-enforceable      — needs heuristic (NLP score, screenshot diff,
                          telemetry trend) — possible but lossy
  prose-only            — taste, philosophy, anti-patterns ("don't do X
                          because Y") — best left as guidance

OUTPUT:
  --report-md PATH     Markdown table per skill: rule, classification,
                       proposed validator (if enforceable)
  --csv PATH           Machine-readable CSV for tooling

USAGE:
  python inventory-skill-rules.py \\
    --skills-glob ".codex/skills/vg-*/SKILL.md" \\
    --report-md .vg/harness-v2.6/RULE-INVENTORY.md \\
    --csv .vg/harness-v2.6/rules.csv

EXIT: 0 always (this is a discovery tool, not a gate).
"""

import argparse
import csv
import json
import re
import sys
from glob import glob
from pathlib import Path
from typing import NamedTuple


class Rule(NamedTuple):
    skill: str
    rule_id: str
    rule_text: str
    classification: str
    proposed_validator: str
    contexts: list[str]    # platform/profile/env applicability hints
    line_no: int


# Patterns that indicate a rule line:
# - "RULE:", "MUST", "PHẢI", "BẮT BUỘC", "NEVER", "DO NOT"
# - Numbered rules at top of <rules> blocks: "1. ...", "2. ..."
# - Rule lines starting with R<N>:
RULE_LINE_RE = re.compile(
    r"""
    (?:
      \*\*MUST\*\*|\bMUST\b|
      \bPHẢI\b|\bBẮT\s*BUỘC\b|
      \bNEVER\b|\bDO\s+NOT\b|
      ^\s*(?:R\d+|\d+)\.\s|
      \bRULE\b\s*[:\-]
    )
    """,
    re.IGNORECASE | re.VERBOSE | re.MULTILINE,
)

# Indicators of enforceable structural rules (file existence, format, etc.)
ENFORCEABLE_HINTS = [
    "must exist", "must contain", "must include", "must match",
    "must be", "missing", "required", "mandatory", "block", "fail",
    "exit code", "returns", "selector", "attribute", "data-testid",
    "regex", "schema", "endpoint", "header", "status code",
    "phải có", "phải tồn tại", "phải match", "thiếu", "yêu cầu",
    "bắt buộc", "block", "fail", "endpoint", "schema",
]

# Indicators that a rule is heuristic / score-based
SEMI_HINTS = [
    "human", "story", "narrative", "natural", "tone", "style", "verbose",
    "concise", "tự nhiên", "câu chuyện", "ngôn ngữ", "phong cách",
    "score", "threshold", "heuristic", "approximate", "screenshot",
]

# Indicators that a rule is inherently prose / philosophy
PROSE_HINTS = [
    "philosophy", "principle", "spirit", "intent", "best practice",
    "consider", "prefer", "encourage", "tinh thần", "ưu tiên",
    "nguyên tắc", "khuyến khích",
]

# Validator-name proposals based on rule keywords. First match wins.
VALIDATOR_KEYWORDS: list[tuple[str, str]] = [
    ("commit message", "commit-attribution"),
    ("citation", "commit-attribution"),
    ("data-testid", "spec-selectors-vs-impl"),
    ("data-column-id", "spec-selectors-vs-impl"),
    ("attribute", "spec-selectors-vs-impl"),
    ("filter", "test-goals-platform-essentials"),
    ("paging", "test-goals-platform-essentials"),
    ("pagination", "test-goals-platform-essentials"),
    ("column", "test-goals-platform-essentials"),
    ("layer 4", "test-goals-platform-essentials"),
    ("reload", "test-goals-platform-essentials"),
    ("state machine", "test-goals-platform-essentials"),
    ("state guard", "test-goals-platform-essentials"),
    ("state-machine", "test-goals-platform-essentials"),
    ("disabled", "test-goals-platform-essentials"),
    ("empty state", "test-goals-platform-essentials"),
    ("loading state", "test-goals-platform-essentials"),
    ("default sort", "test-goals-platform-essentials"),
    ("ngôn ngữ loài người", "human-language-response"),
    ("câu chuyện", "human-language-response"),
    ("storytelling", "human-language-response"),
    ("natural language", "human-language-response"),
    ("tiếng việt", "human-language-response"),
    ("translate", "human-language-response"),
    ("origin", "verify-auth-flow-smoke"),
    ("auth", "verify-auth-flow-smoke"),
    ("login", "verify-auth-flow-smoke"),
    ("color", "verify-visual-color-fidelity"),
    ("theme", "verify-visual-color-fidelity"),
    ("palette", "verify-visual-color-fidelity"),
    ("design system", "verify-visual-color-fidelity"),
    ("api endpoint", "verify-orphan-api-endpoints"),
    ("orphan", "verify-orphan-api-endpoints"),
    ("phantom", "verify-orphan-api-endpoints"),
    ("contract", "verify-contract-runtime"),
    ("typecheck", "build-typecheck"),
    ("hook", "no-no-verify"),
    ("--no-verify", "no-no-verify"),
    ("hardcode", "verify-no-hardcoded-paths"),
    ("hardcoded", "verify-no-hardcoded-paths"),
    ("ssh", "verify-no-hardcoded-paths"),
    ("vps", "verify-no-hardcoded-paths"),
    ("not_scanned", "verify-no-not-scanned-defer"),
    ("design-ref", "verify-design-ref-honored"),
    ("override-debt", "verify-override-debt-logged"),
    ("override-reason", "verify-override-debt-logged"),
    ("token", "verify-token-rotation"),
    ("rate limit", "verify-rate-limit-coverage"),
    ("idempot", "verify-idempotency-coverage"),
    ("csrf", "verify-csrf-coverage"),
    ("xss", "verify-xss-coverage"),
    ("injection", "verify-injection-coverage"),
    ("rollback", "verify-rollback-procedure"),
    ("smoke", "verify-smoke-after-deploy"),
    ("health check", "verify-smoke-after-deploy"),
    ("env var", "verify-env-vars-documented"),
    ("environment", "verify-env-vars-documented"),
    ("checkpoint", "verify-checkpoint-format"),
    ("step marker", "verify-step-markers"),
    ("step-markers", "verify-step-markers"),
    ("console error", "verify-console-no-error"),
    ("console.error", "verify-console-no-error"),
]

# Context hints — words that suggest applicability to specific
# platform/profile/env combinations
CONTEXT_HINTS = {
    "web-fullstack": ["web", "html", "browser", "playwright", "react",
                      "vite", "spa"],
    "web-frontend-only": ["frontend", "client-side", "react", "vue",
                          "tailwind"],
    "web-backend-only": ["backend", "fastify", "express", "api server",
                         "endpoint"],
    "mobile-rn": ["mobile", "react native", "expo", "ios", "android"],
    "mobile-flutter": ["flutter", "dart"],
    "desktop-electron": ["electron", "desktop", "main process"],
    "cli-tool": ["cli", "argv", "stdin", "stdout", "exit code"],
    "library": ["package", "library", "exports", "tree-shake"],
    "server-setup": ["ansible", "vps", "deploy", "systemd", "pm2"],
    "feature": ["feature", "user story"],
    "infra": ["infra", "deploy", "provisioning"],
    "hotfix": ["hotfix", "urgent", "production"],
    "bugfix": ["bugfix", "issue"],
    "migration": ["migration", "schema change"],
    "docs": ["docs", "documentation"],
    "env-local": ["local", "localhost", "dev mode"],
    "env-sandbox": ["sandbox", "vps", "staging"],
    "env-production": ["production", "prod", "live"],
}


def classify(rule_text: str) -> str:
    """Decide enforceable | semi-enforceable | prose-only."""
    text = rule_text.lower()
    if any(h in text for h in PROSE_HINTS):
        return "prose-only"
    if any(h in text for h in SEMI_HINTS):
        return "semi-enforceable"
    if any(h in text for h in ENFORCEABLE_HINTS):
        return "enforceable"
    return "prose-only"  # default conservative


def propose_validator(rule_text: str) -> str:
    text = rule_text.lower()
    for kw, validator in VALIDATOR_KEYWORDS:
        if kw in text:
            return validator
    return ""  # no proposal


def detect_contexts(rule_text: str) -> list[str]:
    text = rule_text.lower()
    out: list[str] = []
    for ctx, kws in CONTEXT_HINTS.items():
        if any(kw in text for kw in kws):
            out.append(ctx)
    return out or ["any"]


def extract_rule_id(line: str) -> str:
    """Try to identify a rule number/id from the line."""
    m = re.match(r"^\s*(R\d+|\d+\.)", line)
    if m:
        return m.group(1).rstrip(".")
    return ""


def extract_rules_from_skill(skill_path: Path) -> list[Rule]:
    """Pull candidate rule lines out of a skill markdown file."""
    skill_id = skill_path.parent.name  # e.g. "vg-review"
    text = skill_path.read_text(encoding="utf-8", errors="ignore")
    out: list[Rule] = []
    seen: set[str] = set()

    in_rules_block = False
    rules_block_depth = 0

    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue

        # Track rules blocks (loose — many skills mix prose + lists)
        if re.search(r"<rules>", line, re.IGNORECASE):
            in_rules_block = True
            continue
        if re.search(r"</rules>", line, re.IGNORECASE):
            in_rules_block = False
            continue

        # Filter to lines that look like a rule
        is_rule = bool(RULE_LINE_RE.search(line))
        if not (in_rules_block or is_rule):
            continue

        # Skip code-block lines (heuristic: indented ≥4 spaces or in fenced block)
        if raw_line.startswith("    ") and not in_rules_block:
            continue

        # Skip very short or generic lines
        if len(line) < 20:
            continue

        # Dedupe by exact text within skill
        if line in seen:
            continue
        seen.add(line)

        rule_id = extract_rule_id(raw_line)
        cls = classify(line)
        validator = propose_validator(line)
        contexts = detect_contexts(line)

        out.append(Rule(
            skill=skill_id,
            rule_id=rule_id or f"L{line_no}",
            rule_text=line[:300],
            classification=cls,
            proposed_validator=validator,
            contexts=contexts,
            line_no=line_no,
        ))

    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--skills-glob", default=".codex/skills/vg-*/SKILL.md")
    ap.add_argument("--report-md", default="")
    ap.add_argument("--csv", default="")
    ap.add_argument("--summary", action="store_true",
                    help="Print summary stats to stdout instead of full JSON.")
    args = ap.parse_args(argv)

    skill_files = [Path(p) for p in glob(args.skills_glob, recursive=True)]
    if not skill_files:
        print(f"⛔ No skills matched glob: {args.skills_glob}", file=sys.stderr)
        return 1

    all_rules: list[Rule] = []
    for sp in skill_files:
        all_rules.extend(extract_rules_from_skill(sp))

    # Stats
    by_class: dict[str, int] = {}
    by_skill: dict[str, int] = {}
    by_validator: dict[str, int] = {}
    for r in all_rules:
        by_class[r.classification] = by_class.get(r.classification, 0) + 1
        by_skill[r.skill] = by_skill.get(r.skill, 0) + 1
        if r.proposed_validator:
            by_validator[r.proposed_validator] = (
                by_validator.get(r.proposed_validator, 0) + 1
            )

    summary = {
        "total_rules": len(all_rules),
        "skills_scanned": len(skill_files),
        "by_classification": by_class,
        "rules_per_skill_top10": dict(sorted(
            by_skill.items(), key=lambda kv: -kv[1])[:10]),
        "validator_proposals_top10": dict(sorted(
            by_validator.items(), key=lambda kv: -kv[1])[:10]),
    }

    if args.summary:
        print(json.dumps(summary, indent=2, ensure_ascii=False))

    if args.csv:
        Path(args.csv).parent.mkdir(parents=True, exist_ok=True)
        with open(args.csv, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["skill", "rule_id", "line_no", "classification",
                        "proposed_validator", "contexts", "rule_text"])
            for r in all_rules:
                w.writerow([r.skill, r.rule_id, r.line_no, r.classification,
                            r.proposed_validator, "|".join(r.contexts),
                            r.rule_text])

    if args.report_md:
        Path(args.report_md).parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "# VG Skill Rule Inventory",
            "",
            f"Generated by `inventory-skill-rules.py`. "
            f"Scope: `{args.skills_glob}`.",
            "",
            "## Summary",
            "",
            f"- Skills scanned: **{summary['skills_scanned']}**",
            f"- Total rules detected: **{summary['total_rules']}**",
            "",
            "### By classification",
            "",
        ]
        for k, v in sorted(by_class.items(), key=lambda kv: -kv[1]):
            lines.append(f"- `{k}`: **{v}**")
        lines.extend(["", "### Top 10 skills by rule count", ""])
        for k, v in summary["rules_per_skill_top10"].items():
            lines.append(f"- `{k}`: {v}")
        lines.extend(["", "### Top 10 proposed validators", ""])
        for k, v in summary["validator_proposals_top10"].items():
            lines.append(f"- `{k}`: covers {v} rules")
        lines.extend(["", "## Per-skill detail", ""])

        # Group by skill
        rules_by_skill: dict[str, list[Rule]] = {}
        for r in all_rules:
            rules_by_skill.setdefault(r.skill, []).append(r)
        for skill in sorted(rules_by_skill.keys()):
            skill_rules = rules_by_skill[skill]
            lines.append(f"### `{skill}` ({len(skill_rules)} rules)")
            lines.append("")
            lines.append("| ID | Class | Proposed validator | Contexts | Rule |")
            lines.append("|----|-------|---------------------|----------|------|")
            for r in skill_rules[:50]:  # cap at 50/skill
                txt = r.rule_text.replace("|", "\\|")[:120]
                lines.append(
                    f"| {r.rule_id} | {r.classification} | "
                    f"{r.proposed_validator or '—'} | "
                    f"{','.join(r.contexts)} | {txt} |"
                )
            if len(skill_rules) > 50:
                lines.append(f"\n_(+{len(skill_rules)-50} more rules elided)_")
            lines.append("")
        Path(args.report_md).write_text("\n".join(lines), encoding="utf-8")

    if not args.summary and not args.csv and not args.report_md:
        print(json.dumps(summary, indent=2, ensure_ascii=False))

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
