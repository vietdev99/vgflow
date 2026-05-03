#!/usr/bin/env python3
"""
validate-crossai-review-xml.py — Phase L of v2.5.2 hardening.

Problem closed:
  v2.5.1 crossai XML presence-checked via `glob_min_count: 1`. Malformed
  XML, empty content, or fabricated verdict still satisfies glob match.
  CrossAI outputs are trust-anchor artifacts — must be semantically valid.

This validator checks XML structure via XPath (no XSD — AI output has
no schema owner + XSD rigidity blocks legitimate variations). Enforced
checks:
  1. Parses as valid XML
  2. Contains <crossai_review> root
  3. <verdict> exists with value in {pass, flag, block}
  4. <score> exists with decimal 0-10 (or "N/10" format)
  5. <reviewer> exists and non-empty
  6. Optional: custom XPath expressions per-contract

Does NOT verify correctness of verdict logic — that's the reviewer's job.
Only verifies AI can't forge by emitting garbage XML or empty `<verdict/>`.

Exit codes:
  0 = all XML files valid
  1 = validation failures
  2 = config error

Usage:
  validate-crossai-review-xml.py --path <file.xml>
  validate-crossai-review-xml.py --glob ".vg/phases/7.14/crossai/result-*.xml"
  validate-crossai-review-xml.py --path X --require-xpath "/crossai_review/verdict[text()='pass']"
"""
from __future__ import annotations

import argparse
import glob as _glob
import json
import re
import sys
from pathlib import Path
from xml.etree import ElementTree as ET


VALID_VERDICTS = frozenset({"pass", "flag", "block"})


def _parse_score(text: str) -> float | None:
    """Accept '7.2', '7.2/10', 'N/10' → 7.2. Returns None if unparseable."""
    if not text:
        return None
    m = re.match(r"^\s*(\d+(?:\.\d+)?)(?:\s*/\s*10)?\s*$", text.strip())
    if m:
        return float(m.group(1))
    return None


def _validate_one(path: Path, required_xpaths: list[str] | None = None) -> dict:
    """Return dict: {path, verdict: OK|FAIL, reason, details}."""
    result = {
        "path": str(path),
        "verdict": "OK",
        "reason": None,
        "details": {},
    }

    # 1. File must exist + be non-empty
    if not path.exists():
        result["verdict"] = "FAIL"
        result["reason"] = "file does not exist"
        return result

    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except PermissionError:
        result["verdict"] = "FAIL"
        result["reason"] = "cannot read file (permission error)"
        return result

    if not content.strip():
        result["verdict"] = "FAIL"
        result["reason"] = "file is empty"
        return result

    # 2. Parse as XML
    # CrossAI output may have preamble text before <crossai_review>
    # Extract just the XML block
    xml_match = re.search(
        r"<crossai_review>.*?</crossai_review>",
        content, re.DOTALL,
    )
    if not xml_match:
        result["verdict"] = "FAIL"
        result["reason"] = (
            "no <crossai_review>...</crossai_review> block found"
        )
        return result

    xml_text = xml_match.group(0)
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        result["verdict"] = "FAIL"
        result["reason"] = f"XML parse error: {e}"
        return result

    # 3. Verdict check
    verdict_elem = root.find("verdict")
    if verdict_elem is None or not (verdict_elem.text or "").strip():
        result["verdict"] = "FAIL"
        result["reason"] = "<verdict> element missing or empty"
        return result
    verdict_value = verdict_elem.text.strip().lower()
    if verdict_value not in VALID_VERDICTS:
        result["verdict"] = "FAIL"
        result["reason"] = (
            f"<verdict> value {verdict_value!r} not in "
            f"{sorted(VALID_VERDICTS)}"
        )
        return result
    result["details"]["verdict_value"] = verdict_value

    # 4. Score check
    score_elem = root.find("score")
    if score_elem is None or not (score_elem.text or "").strip():
        result["verdict"] = "FAIL"
        result["reason"] = "<score> element missing or empty"
        return result
    score = _parse_score(score_elem.text)
    if score is None:
        result["verdict"] = "FAIL"
        result["reason"] = (
            f"<score> value {score_elem.text!r} unparseable as decimal 0-10"
        )
        return result
    if score < 0 or score > 10:
        result["verdict"] = "FAIL"
        result["reason"] = f"<score> value {score} out of range 0-10"
        return result
    result["details"]["score"] = score

    # 5. Reviewer check
    reviewer_elem = root.find("reviewer")
    if reviewer_elem is None or not (reviewer_elem.text or "").strip():
        result["verdict"] = "FAIL"
        result["reason"] = "<reviewer> element missing or empty"
        return result
    result["details"]["reviewer"] = reviewer_elem.text.strip()

    # 6. Optional custom XPath requirements
    if required_xpaths:
        for xp in required_xpaths:
            # Note: ElementTree XPath support is limited — for complex
            # expressions (predicates with text() comparisons) we fall back
            # to regex since ET doesn't support full XPath 1.0
            try:
                matches = root.findall(xp) if not _is_text_predicate(xp) \
                    else _regex_xpath_match(root, xp)
            except SyntaxError as e:
                result["verdict"] = "FAIL"
                result["reason"] = f"invalid xpath {xp!r}: {e}"
                return result
            if not matches:
                result["verdict"] = "FAIL"
                result["reason"] = (
                    f"required xpath {xp!r} matched no nodes"
                )
                return result

    return result


def _is_text_predicate(xpath: str) -> bool:
    return "text()" in xpath


def _regex_xpath_match(root: ET.Element, xpath: str) -> list:
    """Simplified support for /path/element[text() = 'value'] style."""
    m = re.match(r"^/(\w+)/(\w+)\[text\(\)\s*=\s*['\"](.+?)['\"]\]$", xpath)
    if not m:
        return []
    root_name, child_name, expected = m.groups()
    if root.tag != root_name:
        return []
    matches = []
    for child in root.findall(child_name):
        if (child.text or "").strip() == expected:
            matches.append(child)
    return matches


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--path", help="single XML file")
    g.add_argument("--glob", help="glob pattern (e.g. 'crossai/result-*.xml')")
    ap.add_argument("--require-xpath", action="append", default=[],
                    help="additional XPath that MUST match ≥1 node (repeatable)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true",
                    help="suppress output on pass")
    args = ap.parse_args()

    if args.path:
        paths = [Path(args.path)]
    else:
        paths = [Path(p) for p in _glob.glob(args.glob)]

    if not paths:
        print(f"\033[38;5;208mNo files matched: {args.path or args.glob}\033[0m", file=sys.stderr)
        return 1

    results = [_validate_one(p, args.require_xpath) for p in paths]
    failures = [r for r in results if r["verdict"] != "OK"]

    if args.json:
        print(json.dumps({
            "checked": len(results),
            "failures": len(failures),
            "results": results,
        }, indent=2))
    else:
        if failures:
            print(f"\033[38;5;208mCrossAI XML validation: {len(failures)}/{len(results)} failed\033[0m\n")
            for r in failures:
                print(f"  [FAIL] {r['path']}")
                print(f"    {r['reason']}")
        elif not args.quiet:
            print(f"✓ CrossAI XML validation OK — {len(results)} file(s) valid")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
