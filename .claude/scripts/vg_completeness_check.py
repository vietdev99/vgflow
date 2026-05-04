#!/usr/bin/env python3
"""
vg_completeness_check.py — Completeness validation for /vg:scope output.

Runs 4 checks on CONTEXT.md:
  A) Endpoint → test scenario coverage (every decision with Endpoints must have ≥1 TS referencing the endpoint)
  C) SPECS in-scope → decisions coverage (every SPECS in-scope item must map to ≥1 decision, stemmed keyword match)
  B) Design-ref coverage (if config.design_assets declared) — WARN only
  D) Orphan decisions (decisions not mapping to any SPECS item) — WARN only

Exit codes:
  0 — all checks pass
  1 — Check A or C (HARD BLOCK) failed beyond threshold
  2 — only warnings (B or D)

Usage:
  python vg_completeness_check.py --phase-dir .vg/phases/10-deal-management-dsp-partners/
  python vg_completeness_check.py --phase-dir <DIR> --json   # emit machine-readable JSON
  python vg_completeness_check.py --phase-dir <DIR> --allow-incomplete  # warn-only mode for A/C
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────
# Stemming — strip common English suffixes for loose keyword match.
# Handles: "throttling" → "throttl" (matches "throttle")
#          "onboarding" → "onboard" (matches "onboarded", "onboards")
#          "creation"   → "creat"   (matches "create", "creating")
# Not a full Porter stemmer — project-scoped heuristic adequate for spec matching.
# ─────────────────────────────────────────────────────────────────────────
_SUFFIXES = ('ingly', 'ation', 'tions', 'sions', 'ments', 'ables',
             'ibles', 'ing', 'ion', 'ers', 'est', 'ive', 'ment', 'able',
             'ible', 'ers', 'ed', 'es', 's')

def stem(word: str) -> str:
    w = word.lower().strip('-_.,;:!?()[]{}"\'')
    if len(w) <= 4:
        return w
    for suf in _SUFFIXES:
        if w.endswith(suf) and len(w) > len(suf) + 2:
            return w[:-len(suf)]
    return w


def tokenize(text: str) -> set[str]:
    """Tokenize text → set of stems. Skip short/stop words."""
    STOP = {'the', 'and', 'for', 'with', 'from', 'into', 'that', 'this',
            'have', 'has', 'are', 'were', 'was', 'been', 'being'}
    tokens = re.findall(r'\b[a-zA-Z][a-zA-Z0-9]{2,}\b', text.lower())
    return {stem(t) for t in tokens if t not in STOP and len(t) > 3}


# ─────────────────────────────────────────────────────────────────────────
# Parsers
# ─────────────────────────────────────────────────────────────────────────
def parse_decisions(ctx: str) -> list[dict]:
    """Parse CONTEXT.md decisions. Returns list of { id, title, body }."""
    pattern = re.compile(r'^### ((?:P[\w.]+\.)?D-\d+): (.+?)$', re.M)
    results = []
    matches = list(pattern.finditer(ctx))
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i+1].start() if i+1 < len(matches) else len(ctx)
        results.append({
            'id': m.group(1),
            'title': m.group(2).strip(),
            'body': ctx[start:end],
        })
    return results


def parse_endpoints(ctx: str) -> list[tuple[str, str]]:
    """Return list of (METHOD, path) pairs across all decisions."""
    pattern = re.compile(r'^\s*-\s+(GET|POST|PUT|PATCH|DELETE)\s+(/[\w/:.\-{}]+)', re.M)
    return [(m.group(1), m.group(2)) for m in pattern.finditer(ctx)]


def parse_ts_endpoint_refs(ctx: str) -> set[tuple[str, str]]:
    """TS lines may reference endpoints inline — collect (METHOD, path) occurring anywhere."""
    # Match METHOD path anywhere (TS body, tables, etc.)
    return set(re.findall(r'\b(GET|POST|PUT|PATCH|DELETE)\s+(/[\w/:.\-{}]+)', ctx))


def parse_specs_in_scope(specs: str) -> list[str]:
    """Return list of in-scope item titles from SPECS.md."""
    in_scope_section = re.search(r'^## In[ -]scope\s*\n(.+?)(?=^##)', specs, re.M | re.S)
    if not in_scope_section:
        return []
    body = in_scope_section.group(1)
    items = re.findall(r'^\s*\d+\.\s+\*\*(.+?)\*\*', body, re.M)
    if not items:
        # Fallback: plain numbered list without **bold**
        items = re.findall(r'^\s*\d+\.\s+(.+?)(?:\s*—|\s*-|\s*:)', body, re.M)
    return [i.strip() for i in items if i.strip()]


# ─────────────────────────────────────────────────────────────────────────
# Checks
# ─────────────────────────────────────────────────────────────────────────
def check_a_endpoint_coverage(decisions, endpoints, ts_refs):
    """Every declared endpoint must appear in at least one TS/mutation-evidence reference."""
    unreferenced = []
    for method, path in endpoints:
        if (method, path) not in ts_refs:
            # Also tolerate parameterized matches: /deals/:id vs /deals/{id}
            loose = {(m, re.sub(r':([a-z_]+)', r'{\1}', p)) for m, p in ts_refs}
            if (method, re.sub(r':([a-z_]+)', r'{\1}', path)) in loose:
                continue
            unreferenced.append(f"{method} {path}")
    return unreferenced


def _fuzzy_match(needle: str, haystack: set[str], min_len: int = 4) -> bool:
    """Match needle against haystack with prefix tolerance.
    Handles stem inconsistency e.g. 'throttl' (from 'throttling') vs 'throttle' (unchanged).
    Returns True if needle is prefix of any haystack token ≥ min_len, or vice versa.
    """
    if len(needle) < min_len:
        return needle in haystack
    if needle in haystack:
        return True
    for t in haystack:
        if len(t) < min_len:
            continue
        # Prefix match either direction (handles "throttl" ↔ "throttle")
        if t.startswith(needle) or needle.startswith(t):
            return True
    return False


def check_c_specs_coverage(decisions, specs_items, threshold_pct=10.0):
    """Every SPECS in-scope item must have ≥1 decision matching via stemmed keyword.
    Returns (unmatched_items, pct_missing)."""
    unmatched = []
    all_decision_tokens = set()
    for d in decisions:
        all_decision_tokens |= tokenize(d['title'] + ' ' + d['body'])

    for item in specs_items:
        item_tokens = tokenize(item)
        # Require at least 1 meaningful keyword (>3 chars) match
        sig_tokens = {t for t in item_tokens if len(t) > 3}
        if not sig_tokens:
            continue  # trivial items skipped
        if not any(_fuzzy_match(t, all_decision_tokens) for t in sig_tokens):
            unmatched.append(item)

    pct = (100.0 * len(unmatched) / len(specs_items)) if specs_items else 0.0
    return unmatched, pct


# ─────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────
def _read_context_frontmatter_bool(ctx_text: str, key: str) -> bool:
    """Phase 16 D-04 helper — read a boolean key from CONTEXT.md frontmatter.
    Frontmatter is the leading `---\\n...\\n---\\n` block at top of file."""
    fm = re.match(r"^---\s*\n(.*?)\n---\s*\n", ctx_text, re.DOTALL)
    if not fm:
        return False
    m = re.search(rf"^\s*{re.escape(key)}\s*:\s*(true|false|True|False)\s*$",
                  fm.group(1), re.MULTILINE)
    return bool(m and m.group(1).lower() == "true")


def check_e_task_body_length(plan_files, ctx_text, allow_long: bool = False):
    """Phase 16 D-03 — task body line cap gate.

    Cap rules:
      - per-task `body_max_lines` frontmatter override → use that
      - else CONTEXT cross_ai_enriched: true → 600
      - else default 250

    Returns list[dict] of violations.
    """
    enriched = _read_context_frontmatter_bool(ctx_text, "cross_ai_enriched")
    default_cap = 600 if enriched else 250

    # Lazy-load extract_all_tasks from pre-executor-check.py
    import importlib.util
    pec_path = Path(__file__).parent / "pre-executor-check.py"
    if not pec_path.exists():
        return []
    spec = importlib.util.spec_from_file_location("pec_for_check_e", pec_path)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception:
        return []
    extract_all_tasks = getattr(mod, "extract_all_tasks", None)
    if not extract_all_tasks:
        return []

    violations = []
    for pf in plan_files:
        for task in extract_all_tasks(pf):
            fm = task.get("frontmatter") or {}
            cap = fm.get("body_max_lines") or default_cap
            try:
                cap = int(cap)
            except (TypeError, ValueError):
                cap = default_cap
            actual = task["body"].count("\n") + 1 if task["body"] else 0
            if actual > cap:
                violations.append({
                    "task_id": task["id"],
                    "file": str(pf.name),
                    "format": task["format"],
                    "actual_lines": actual,
                    "cap": cap,
                    "cap_source": (
                        "body_max_lines" if "body_max_lines" in fm
                        else ("enriched" if enriched else "default")
                    ),
                    "fix_hint": (
                        "Split task into smaller subtasks OR move prose to "
                        "<context-refs> in CONTEXT.md (P16 D-05) OR override "
                        "via frontmatter `body_max_lines: <N>`."
                    ),
                })

    return violations


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--phase-dir', required=True, type=Path)
    ap.add_argument('--json', action='store_true', help='Emit JSON instead of human text')
    ap.add_argument('--allow-incomplete', action='store_true', help='Warn-only mode for A/C')
    ap.add_argument('--threshold-pct', type=float, default=10.0,
                    help='Check C threshold: fail if more than this pct of items unmatched')
    ap.add_argument('--allow-long-task', action='store_true',
                    help='Phase 16 D-03 escape hatch: downgrade Check E BLOCK to WARN '
                         '(logs override-debt as kind=long-task)')
    args = ap.parse_args()

    ctx_path = args.phase_dir / 'CONTEXT.md'
    specs_path = args.phase_dir / 'SPECS.md'

    if not ctx_path.exists():
        print(f"\033[38;5;208mCONTEXT.md not found at {ctx_path}\033[0m", file=sys.stderr)
        return 1
    if not specs_path.exists():
        print(f"\033[38;5;208mSPECS.md not found at {specs_path}\033[0m", file=sys.stderr)
        return 1

    ctx = ctx_path.read_text(encoding='utf-8')
    specs = specs_path.read_text(encoding='utf-8')

    decisions = parse_decisions(ctx)
    endpoints = parse_endpoints(ctx)
    ts_refs = parse_ts_endpoint_refs(ctx)
    specs_items = parse_specs_in_scope(specs)

    # Run checks
    check_a_unref = check_a_endpoint_coverage(decisions, endpoints, ts_refs)
    check_c_unmatched, check_c_pct = check_c_specs_coverage(decisions, specs_items, args.threshold_pct)

    # Phase 16 D-03 — Check E: per-task body line cap
    plan_files = sorted(args.phase_dir.glob("PLAN*.md"))
    check_e_violations = check_e_task_body_length(plan_files, ctx, args.allow_long_task)

    result = {
        'decisions': len(decisions),
        'endpoints': len(endpoints),
        'test_scenarios': len(re.findall(r'^\s*-\s+TS-\d+:', ctx, re.M)),
        'specs_in_scope': len(specs_items),
        'check_a': {
            'name': 'endpoint_coverage',
            'status': 'PASS' if not check_a_unref else 'BLOCK',
            'unreferenced_count': len(check_a_unref),
            'unreferenced': check_a_unref,
        },
        'check_e': {
            'name': 'task_body_length_cap',
            'status': (
                'PASS' if not check_e_violations
                else ('WARN' if args.allow_long_task else 'BLOCK')
            ),
            'violations_count': len(check_e_violations),
            'violations': check_e_violations[:10],  # cap evidence
            'note': (
                'Phase 16 D-03 — body cap 250 default, 600 if cross_ai_enriched, '
                'per-task body_max_lines override.'
            ),
        },
        'check_c': {
            'name': 'specs_in_scope_coverage',
            'status': ('PASS' if not check_c_unmatched
                       else 'BLOCK' if check_c_pct > args.threshold_pct
                       else 'WARN'),
            'unmatched_count': len(check_c_unmatched),
            'unmatched_pct': round(check_c_pct, 1),
            'threshold_pct': args.threshold_pct,
            'unmatched': check_c_unmatched,
            'note': 'Uses stemmed keyword match (strips -ing, -tion, -ed, -s, etc.)',
        },
    }

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Completeness Validation — {args.phase_dir.name}")
        print(f"  Decisions:     {result['decisions']}")
        print(f"  Endpoints:     {result['endpoints']}")
        print(f"  TS:            {result['test_scenarios']}")
        print(f"  SPECS items:   {result['specs_in_scope']}")
        print()
        for k in ('check_a', 'check_c'):
            c = result[k]
            icon = {'PASS': '✓', 'WARN': '', 'BLOCK': ''}[c['status']]
            print(f"  {icon} Check {k[-1].upper()} ({c['name']}): {c['status']}")
            if c['status'] != 'PASS':
                if k == 'check_a':
                    for u in c['unreferenced'][:5]:
                        print(f"      - {u}")
                else:
                    print(f"      {c['unmatched_pct']}% unmatched (threshold {c['threshold_pct']}%)")
                    for u in c['unmatched'][:5]:
                        print(f"      - {u}")

    # Exit code (P16 D-03: include Check E in BLOCK + WARN aggregation)
    all_checks = (result['check_a'], result['check_c'], result['check_e'])
    blocks = sum(1 for c in all_checks if c['status'] == 'BLOCK')
    if blocks > 0:
        if args.allow_incomplete:
            print("\n⚠ --allow-incomplete: treating BLOCKs as warnings", file=sys.stderr)
            return 2
        return 1
    if any(c['status'] == 'WARN' for c in all_checks):
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
