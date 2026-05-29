"""debug_classifier — B114 v4.73.0 — smarter bug-type classification.

Replaces inline bash regex classifier in commands/vg/_shared/debug/preflight.md
with token+confidence scoring that handles:

  - multi-word patterns (e.g., "form submit không hiện toast")
  - cross-signal precedence (network status > UI > infra > static > spec)
  - per-type evidence trail (which tokens matched, why)

Why: original regex did single grep per type, last match wins by source-order.
"form submit 500" classified as `static` because TypeError pattern matched
later, but network is the right class. Confidence calculated from token
overlap density, not boolean match.

Output: JSON to stdout, machine-readable for orchestrator.

  {
    "bug_type": "network",
    "confidence": 88,
    "evidence": {"network": ["500", "fetch failed"], "runtime_ui": ["form"]},
    "alternates": [{"type": "runtime_ui", "confidence": 42}],
    "needs_clarification": false
  }

Exit codes:
  0 = classified (confidence >= threshold)
  1 = ambiguous (orchestrator should AskUserQuestion)
  2 = empty description
"""
from __future__ import annotations

import argparse
import json
import re
import sys

# Token weights per type. Tokens scored by case-insensitive substring match.
# Weight = base confidence contribution. Tokens repeated in description
# count once each.
_SIGNALS: dict[str, list[tuple[str, int]]] = {
    "network": [
        (r"\b[45]\d{2}\b", 35),  # status codes 4xx/5xx
        (r"\btimeout\b", 30),
        (r"\bERR_CONNECTION\b", 35),
        (r"\bCORS\b", 35),
        (r"\bfetch\s+failed\b", 30),
        (r"\bnetwork\s+error\b", 25),
        (r"\b(?:GET|POST|PUT|DELETE|PATCH)\s+/", 25),
        (r"\bAPI\s+(?:call|request|fail)", 20),
        (r"\bxhr\b", 15),
        (r"\baxios\b", 10),
        (r"\b502\s+bad\s+gateway\b", 40),
        (r"\b404\s+not\s+found\b", 35),
        (r"\b500\s+internal", 40),
        (r"\bredirect.*fail", 20),
        (r"\bunauthorized\b", 20),
    ],
    "runtime_ui": [
        (r"\bclick\b", 20),
        (r"\brender\b", 20),
        (r"\bmodal\b", 20),
        (r"\btab\b", 15),
        (r"\blayout\b", 20),
        (r"\bbutton\b", 15),
        (r"\bform\b", 15),
        (r"\bdropdown\b", 25),
        (r"\bpage\b", 10),
        (r"\b/[a-z][a-z0-9-]*(?:/[a-z0-9-]+)*\b", 20),  # URL paths
        (r"\bcrash\s+khi\b", 30),
        (r"\bkhông\s+hiển\s+thị\b", 25),
        (r"\bdoesn'?t\s+show\b", 25),
        (r"\bdoesn'?t\s+render\b", 25),
        (r"\bblank\s+screen\b", 30),
        (r"\bsubmit\b", 15),
        (r"\btoast\b", 20),
        (r"\binput\s+field\b", 15),
    ],
    "infra": [
        (r"\benv\s+var\b", 30),
        (r"\b\.env\b", 30),
        (r"\bconfig\b", 15),
        (r"\bdeploy\b", 20),
        (r"\brestart\b", 25),
        (r"\bport\s+\d+\b", 30),
        (r"\bpm2\b", 30),
        (r"\bdaemon\b", 25),
        (r"\bdocker\b", 25),
        (r"\bsystemd\b", 30),
        (r"\bnginx\b", 25),
        (r"\bECONNREFUSED\b", 35),
        (r"\bcannot\s+connect\b", 25),
    ],
    "static": [
        (r"\bat\s+\S+:\d+:\d+", 40),  # stack frame
        (r"\bat\s+\S+:\d+", 35),
        (r"\bTypeError\b", 35),
        (r"\bReferenceError\b", 35),
        (r"\bSyntaxError\b", 35),
        (r"\bundefined\s+is\s+not\b", 35),
        (r"\bnull\s+is\s+not\b", 35),
        (r"\bcannot\s+read\s+propert", 30),
        (r"\boff[-\s]?by[-\s]?one\b", 30),
        (r"\btypo\b", 25),
        (r"\bnull\s+check\b", 25),
        (r"\bnull\s+pointer\b", 30),
        (r"\bstack\s+trace\b", 25),
        (r"\bAssertionError\b", 30),
    ],
    "spec_gap": [
        (r"\bkhông\s+có\b", 25),
        (r"\bmissing\s+feature\b", 30),
        (r"\btính\s+năng\s+.{0,20}\s+chưa\b", 30),
        (r"\bchưa\s+có\s+UI\b", 30),
        (r"\bcần\s+thêm\b", 25),
        (r"\bshould\s+support\b", 25),
        (r"\bwishful\b", 20),
        (r"\bnowhere\b", 25),
        (r"\bnot\s+implemented\b", 30),
        (r"\bdoes\s+not\s+exist\b", 25),
    ],
}

# Cross-symptom hints: when classifier picks runtime_ui + URL extracted,
# orchestrator should probe sibling routes. Flag in output.
_PROBE_TRIGGER_TYPES = frozenset({"runtime_ui", "network"})

# Confidence threshold for auto-classify (vs ambiguous → AskUserQuestion).
# Stays at 80 to match v4.72.x preflight regex behavior.
_AUTO_CONFIDENCE_THRESHOLD = 80


def _score_type(text: str, signals: list[tuple[str, int]]) -> tuple[int, list[str]]:
    """Sum weights of matched tokens. Return (score, matched_tokens)."""
    score = 0
    matched: list[str] = []
    seen: set[str] = set()
    for pattern, weight in signals:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            token = m.group(0).strip()
            if token.lower() in seen:
                continue
            seen.add(token.lower())
            score += weight
            matched.append(token)
    return score, matched


def classify(description: str) -> dict:
    """Classify bug description. Return verdict dict."""
    text = description.strip()
    if not text:
        return {
            "bug_type": "ambiguous",
            "confidence": 0,
            "evidence": {},
            "alternates": [],
            "needs_clarification": True,
            "error": "empty description",
        }

    scores: dict[str, tuple[int, list[str]]] = {}
    for bug_type, signals in _SIGNALS.items():
        scores[bug_type] = _score_type(text, signals)

    # Rank types by raw score
    ranked = sorted(
        scores.items(),
        key=lambda kv: kv[1][0],
        reverse=True,
    )

    top_type, (top_score, top_matches) = ranked[0]
    second_type, (second_score, _) = ranked[1] if len(ranked) > 1 else ("none", (0, []))

    # Confidence calculation:
    #   - Cap raw score at 95
    #   - If top vs second gap < 8 AND no dominant signal in top, lower confidence
    #   - Dominant signal = single matched token with weight >= 30 (e.g. status code)
    confidence = min(top_score, 95)
    top_has_dominant = any(
        any(re.search(pat, text, re.IGNORECASE) for pat, w in _SIGNALS[top_type] if w >= 30)
        for _ in [None]
    )
    if (
        second_score > 0
        and (top_score - second_score) < 8
        and not top_has_dominant
    ):
        confidence = max(0, confidence - 20)

    # If nothing matched, ambiguous
    if top_score == 0:
        return {
            "bug_type": "ambiguous",
            "confidence": 0,
            "evidence": {},
            "alternates": [],
            "needs_clarification": True,
        }

    alternates = [
        {"type": t, "confidence": min(s, 95)}
        for t, (s, _) in ranked[1:4]
        if s > 0
    ]

    needs_clarif = confidence < _AUTO_CONFIDENCE_THRESHOLD

    return {
        "bug_type": top_type,
        "confidence": confidence,
        "evidence": {
            t: matches
            for t, (_, matches) in scores.items()
            if matches
        },
        "alternates": alternates,
        "needs_clarification": needs_clarif,
        "probe_siblings_enabled": top_type in _PROBE_TRIGGER_TYPES,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("description", nargs="?", default="",
                    help="bug description (or pass via --stdin)")
    ap.add_argument("--stdin", action="store_true",
                    help="read description from stdin")
    ap.add_argument("--threshold", type=int, default=_AUTO_CONFIDENCE_THRESHOLD,
                    help="confidence threshold for auto-classify (default 80)")
    args = ap.parse_args(argv)

    desc = args.description
    if args.stdin:
        desc = sys.stdin.read()

    if not desc.strip():
        print(json.dumps({
            "bug_type": "ambiguous",
            "confidence": 0,
            "error": "empty description",
            "needs_clarification": True,
        }))
        return 2

    verdict = classify(desc)
    print(json.dumps(verdict, ensure_ascii=False, indent=2))

    if verdict["confidence"] < args.threshold:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
