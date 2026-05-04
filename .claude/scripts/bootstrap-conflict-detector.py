#!/usr/bin/env python3
"""
VG Bootstrap — Conflict Detector (v2.6 Phase C)

Pairwise contradiction detection between ACTIVE candidate rules in
.vg/bootstrap/CANDIDATES.md. When two rules overlap in prose AND target the
same scope but contradict each other, surface them as a conflict pair so the
operator can retire the weaker rule.

Conflict signals (either is enough):
  1. Jaccard-equivalent prose similarity (via difflib.SequenceMatcher,
     SAME helper as learn-dedupe.py — see R6 in PLAN-REVISED Phase C) at or
     above the configured threshold (default 0.7).
  2. Opposing-verb pattern in title or first prose line — e.g. one rule says
     "must enable X" and the other says "must not enable X". Detected via a
     small static dict of opposing verb pairs.

Winner heuristic (when Phase A shadow telemetry is present):
  prefer higher `correctness` (shadow_correct/shadow_total) → fall back to
  higher `evidence_count` → tie → no winner declared (operator decides).

Output (JSON or JSONL):
  {
    "conflicts": [
      {
        "id_a": "L-042",
        "id_b": "L-067",
        "similarity": 0.85,
        "opposing_verb": "must vs must not"  # null if not detected
        "evidence_count_a": 12,
        "evidence_count_b": 8,
        "correctness_a": 0.91,           # null when shadow telemetry missing
        "correctness_b": 0.62,
        "winner": "L-042"                # null on tie
      }
    ]
  }

CLI:
  bootstrap-conflict-detector.py [--threshold 0.7]
                                 [--output-jsonl path]
                                 [--candidate L-XXX]
                                 [--candidates-path path]

Stdlib only. Idempotent (no state writes; pure function over CANDIDATES.md).
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional


# ─── Repo root resolution (matches learn-dedupe.py / shadow-evaluator) ───────

def _repo_root() -> Path:
    env = os.environ.get("VG_REPO_ROOT")
    if env:
        return Path(env)
    p = Path(__file__).resolve()
    for parent in [p.parent, p.parent.parent, p.parent.parent.parent]:
        if (parent / ".claude" / "vg.config.md").exists():
            return parent
    return Path.cwd()


REPO_ROOT = _repo_root()
BOOTSTRAP_DIR = REPO_ROOT / ".vg" / "bootstrap"
CONFIG_PATH = REPO_ROOT / ".claude" / "vg.config.md"


# ─── Config ──────────────────────────────────────────────────────────────────

def _load_conflict_threshold() -> float:
    """bootstrap.conflict_similarity_threshold (default 0.7)."""
    default = 0.7
    if not CONFIG_PATH.exists():
        return default
    text = CONFIG_PATH.read_text(encoding="utf-8", errors="replace")
    in_bootstrap = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("bootstrap:"):
            in_bootstrap = True
            continue
        if in_bootstrap:
            if stripped.startswith("---") or (
                line and not line[0].isspace()
                and ":" in line and not stripped.startswith("#")
            ):
                break
            if "conflict_similarity_threshold:" in stripped:
                v = stripped.partition(":")[2].strip().split("#")[0].strip()
                try:
                    return float(v)
                except ValueError:
                    return default
    return default


# ─── Candidate parsing (block-aware, mirrors learn-dedupe) ───────────────────

class CandidateRule:
    """Parsed ACTIVE candidate rule with fields needed for conflict detection."""
    def __init__(
        self,
        cid: str,
        title: str,
        prose: str,
        status: str,
        evidence_count: int,
        correctness: Optional[float],
    ):
        self.id = cid
        self.title = title
        self.prose = prose
        self.status = status
        self.evidence_count = evidence_count
        self.correctness = correctness


def _parse_yaml_value(block_text: str, key: str) -> str:
    """Extract a top-level scalar value from YAML-like block text."""
    try:
        import yaml
        data = yaml.safe_load(block_text)
        if data and key in data:
            return str(data[key])
    except Exception:
        pass
    m = re.search(
        rf"^{re.escape(key)}\s*:\s*['\"]?(.+?)['\"]?\s*$",
        block_text, re.MULTILINE,
    )
    if m:
        return m.group(1).strip()
    return ""


def _parse_prose(block_text: str) -> str:
    """Extract the `prose: |` literal-block contents (multi-line)."""
    # Match `prose: |` then collect indented lines until dedent or next top-level key.
    lines = block_text.splitlines()
    out: list[str] = []
    in_prose = False
    base_indent: Optional[int] = None
    for line in lines:
        if not in_prose:
            if re.match(r"^prose\s*:\s*[|>]", line):
                in_prose = True
            continue
        if not line.strip():
            out.append("")
            continue
        indent = len(line) - len(line.lstrip())
        if base_indent is None:
            base_indent = indent
        if indent < base_indent:
            break
        out.append(line[base_indent:])
    return "\n".join(out).strip()


def _count_evidence_items(block_text: str) -> int:
    """Count `- phase:` items inside the evidence: section."""
    in_evidence = False
    count = 0
    base_indent: Optional[int] = None
    for line in block_text.splitlines():
        if not in_evidence:
            if re.match(r"^evidence\s*:", line):
                in_evidence = True
            continue
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        if base_indent is None:
            base_indent = indent
        if indent < base_indent:
            break
        if line.lstrip().startswith("- "):
            count += 1
    return count


def _parse_correctness(block_text: str) -> Optional[float]:
    """Compute shadow_correct/shadow_total when both present and total > 0."""
    correct_str = _parse_yaml_value(block_text, "shadow_correct")
    total_str = _parse_yaml_value(block_text, "shadow_total")
    try:
        if not correct_str or not total_str:
            return None
        if correct_str.lower() in ("none", "null", ""):
            return None
        if total_str.lower() in ("none", "null", ""):
            return None
        c = int(correct_str)
        t = int(total_str)
        if t <= 0:
            return None
        return round(c / t, 4)
    except (ValueError, TypeError):
        return None


def _parse_active_rules(candidates_path: Path) -> list[CandidateRule]:
    """Parse all ACTIVE candidate rules — exclude RETIRED / WONT_FIX / promoted."""
    if not candidates_path.exists():
        return []

    text = candidates_path.read_text(encoding="utf-8", errors="replace")
    rules: list[CandidateRule] = []

    fence_pattern = re.compile(r"```yaml\s*\n(.*?)```", re.DOTALL)
    for m in fence_pattern.finditer(text):
        block_text = m.group(1)
        if not re.search(r"^\s*id\s*:", block_text, re.MULTILINE):
            continue

        cid = _parse_yaml_value(block_text, "id")
        if not cid.startswith("L-"):
            continue

        status = _parse_yaml_value(block_text, "status").lower() or "pending"
        # Only ACTIVE candidates participate in conflict detection.
        # Retired/won't-fix/promoted rules are settled.
        if status in ("retired", "retired_by_conflict", "wont_fix", "promoted", "rejected"):
            continue

        rules.append(CandidateRule(
            cid=cid,
            title=_parse_yaml_value(block_text, "title"),
            prose=_parse_prose(block_text),
            status=status,
            evidence_count=_count_evidence_items(block_text),
            correctness=_parse_correctness(block_text),
        ))

    return rules


# ─── Similarity (REUSE difflib.SequenceMatcher from learn-dedupe.py) ─────────

def prose_similarity(a: str, b: str) -> float:
    """Same algorithm as learn-dedupe.title_similarity — guarantees that
    the dedupe pass and the conflict-detect pass agree on how 'similar' two
    rules are. See R6 in Phase C plan."""
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()


# ─── Opposing-verb detection ─────────────────────────────────────────────────

# Floor for opposing-verb detection. Below this similarity, two rules likely
# discuss unrelated subject matter — opposing verbs are coincidental, not
# contradictory. Tuned so test case "must X vs must not X @ 0.55" still trips.
OPPOSING_VERB_FLOOR = 0.45

# Static dict — small list, intentionally narrow. False positives bother the
# operator far more than missed conflicts (which Jaccard catches anyway).
# Each entry: phrase → opposing phrase. Bidirectional matching applied.
OPPOSING_VERB_PAIRS = [
    ("must not", "must"),
    ("must never", "must"),
    ("never", "always"),
    ("forbidden", "required"),
    ("forbidden", "optional"),
    ("avoid", "prefer"),
    ("reject", "prefer"),
    ("disable", "enable"),
    ("disabled", "enabled"),
    ("skip", "require"),
    ("ignore", "require"),
    ("deny", "allow"),
    ("block", "allow"),
]


def _normalize_text(s: str) -> str:
    """Lowercase + collapse whitespace for verb matching."""
    return re.sub(r"\s+", " ", s.lower()).strip()


def _extract_action_phrase(text: str) -> str:
    """Take title + first prose line — the section most likely to carry the
    rule's directive verb."""
    parts = [text]
    return _normalize_text(" ".join(p for p in parts if p))


def detect_opposing_verb(rule_a: CandidateRule, rule_b: CandidateRule) -> Optional[str]:
    """Return a label like 'must vs must not' if the two rules carry an
    opposing verb pair targeting overlapping subject matter, else None."""
    text_a = _extract_action_phrase(
        rule_a.title + " " + rule_a.prose.split("\n", 1)[0]
    )
    text_b = _extract_action_phrase(
        rule_b.title + " " + rule_b.prose.split("\n", 1)[0]
    )

    for neg, pos in OPPOSING_VERB_PAIRS:
        # neg in A, pos in B (and vice versa). Both must use word-ish boundary
        # so 'must' doesn't trigger when the surrounding word is 'must not'.
        a_neg = _phrase_present(text_a, neg)
        a_pos = _phrase_present(text_a, pos) and not a_neg
        b_neg = _phrase_present(text_b, neg)
        b_pos = _phrase_present(text_b, pos) and not b_neg

        if (a_neg and b_pos) or (a_pos and b_neg):
            return f"{pos} vs {neg}"

    return None


def _phrase_present(haystack: str, phrase: str) -> bool:
    """Word-boundary-ish match for a multi-word phrase."""
    pattern = r"\b" + re.escape(phrase) + r"\b"
    return re.search(pattern, haystack) is not None


# ─── Winner determination ───────────────────────────────────────────────────

def determine_winner(rule_a: CandidateRule, rule_b: CandidateRule) -> Optional[str]:
    """Return winner candidate id, or None on tie.

    Heuristic order (per Phase C plan):
      1. Higher Phase A correctness (shadow telemetry) — if BOTH have shadow
         data. If only one has it, the one with shadow data wins (more signal).
      2. Higher evidence_count.
      3. Tie → None (operator decides).
    """
    if rule_a.correctness is not None and rule_b.correctness is not None:
        if rule_a.correctness > rule_b.correctness:
            return rule_a.id
        if rule_b.correctness > rule_a.correctness:
            return rule_b.id
        # Equal correctness — fall through to evidence count.
    elif rule_a.correctness is not None and rule_b.correctness is None:
        return rule_a.id
    elif rule_b.correctness is not None and rule_a.correctness is None:
        return rule_b.id

    if rule_a.evidence_count > rule_b.evidence_count:
        return rule_a.id
    if rule_b.evidence_count > rule_a.evidence_count:
        return rule_b.id
    return None


# ─── Pairwise scan ───────────────────────────────────────────────────────────

def find_conflicts(
    rules: list[CandidateRule],
    threshold: float,
    candidate_filter: Optional[str] = None,
) -> list[dict]:
    """Pairwise scan over ACTIVE rules. Each unordered pair (A, B) is checked
    for similarity and opposing verbs."""
    conflicts: list[dict] = []

    for i, rule_a in enumerate(rules):
        for rule_b in rules[i + 1:]:
            if candidate_filter and candidate_filter not in (rule_a.id, rule_b.id):
                continue

            sim = prose_similarity(rule_a.prose, rule_b.prose)
            opp = detect_opposing_verb(rule_a, rule_b)

            # Opposing verbs alone are noisy ("must X" appears in many unrelated
            # rules). Require a minimum subject-matter overlap before flagging
            # by verb. The OPPOSING_VERB_FLOOR is intentionally well below
            # `threshold` so the test case "must X vs must not X with 0.55
            # similarity" still trips.
            opp_qualified = bool(opp) and sim >= OPPOSING_VERB_FLOOR

            if sim < threshold and not opp_qualified:
                continue

            winner = determine_winner(rule_a, rule_b)
            conflicts.append({
                "id_a": rule_a.id,
                "id_b": rule_b.id,
                "similarity": round(sim, 4),
                "opposing_verb": opp,
                "evidence_count_a": rule_a.evidence_count,
                "evidence_count_b": rule_b.evidence_count,
                "correctness_a": rule_a.correctness,
                "correctness_b": rule_b.correctness,
                "winner": winner,
            })

    return conflicts


# ─── Main ────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(
        description="VG Bootstrap Learn — Pairwise Conflict Detector (v2.6 Phase C)"
    )
    ap.add_argument("--threshold", type=float, default=None,
                    help="Prose similarity threshold (default: from config or 0.7)")
    ap.add_argument("--candidate",
                    help="Only report conflicts that involve this candidate id")
    ap.add_argument("--output-jsonl",
                    help="Write each conflict as one JSON line to this path "
                         "(stdout still receives the wrapped {conflicts: [...]} object)")
    ap.add_argument("--candidates-path",
                    help="Path to CANDIDATES.md (default: .vg/bootstrap/CANDIDATES.md)")
    args = ap.parse_args()

    candidates_path = (
        Path(args.candidates_path) if args.candidates_path
        else BOOTSTRAP_DIR / "CANDIDATES.md"
    )
    threshold = args.threshold if args.threshold is not None else _load_conflict_threshold()

    rules = _parse_active_rules(candidates_path)

    if not rules:
        print(json.dumps({"conflicts": []}))
        return 0

    conflicts = find_conflicts(rules, threshold, candidate_filter=args.candidate)

    if args.output_jsonl:
        out_path = Path(args.output_jsonl)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as fh:
            for c in conflicts:
                fh.write(json.dumps(c, ensure_ascii=False) + "\n")

    print(json.dumps({"conflicts": conflicts}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
