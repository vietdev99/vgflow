#!/usr/bin/env python3
"""
Validator: verify-uat-strings-no-hardcode.py — Phase 15 D-18

Strict reuse policy: UAT narrative template + rendered output MUST NOT contain
hardcoded literal Vietnamese/English strings outside `{{...}}` interpolation.

Two-direction check:
  Forward — every {{uat_<key>}} reference resolves:
    • Key exists in narration-strings.yaml
    • Has entry for active locale (vi by default per vg.config narration.locale)

  Backward — no literal natural-language text outside interpolation/markdown:
    • Regex catches [A-Za-zÀ-ỹ]{2,}+ outside `{{...}}` AND outside markdown
      structural symbols (#, -, :, |, ```, code spans, html tags)
    • Exempt: data variable interpolations `{{var.*}}` (extracted DATA, not UI strings)
    • Exempt: decision title/excerpt extracted from CONTEXT.md (DATA)

Logic:
  1. Locate UAT-NARRATIVE.md (rendered output) AND/OR template (when checking
     pre-render). Default mode: check rendered narrative since that's what
     reaches users.
  2. Forward check: scan {{uat_<key>}} references → assert key+locale present
     in narration-strings.yaml.
  3. Backward check: tokenize, flag literal text outside allowed patterns.

Usage:
  verify-uat-strings-no-hardcode.py --phase 7.14.3
  verify-uat-strings-no-hardcode.py --template <path>     # check template instead
Output: vg.validator-output JSON on stdout
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, timer, emit_and_exit, find_phase_dir  # noqa: E402

# Forward: extract {{uat_<key>}} references
UAT_KEY_REF_RE = re.compile(r"\{\{\s*(uat_[a-z0-9_]+)\s*\}\}")
# Generic interpolation (any {{...}}) — excluded from backward scan
ANY_INTERP_RE = re.compile(r"\{\{[^}]+\}\}")
# Markdown structural symbols stripped before backward scan
MD_STRIP_PATTERNS = [
    re.compile(r"```[\s\S]*?```"),                   # code fences
    re.compile(r"`[^`\n]+`"),                         # inline code
    re.compile(r"!\[[^\]]*\]\([^)]+\)"),              # image links
    re.compile(r"\[[^\]]+\]\([^)]+\)"),               # markdown links
    re.compile(r"<!--[\s\S]*?-->"),                   # html comments
    re.compile(r"<[^>]+>"),                           # html tags
    re.compile(r"^\s*[#>\-*+|=]+.*$", re.MULTILINE),  # heading/list/table/hr lines
]
# Backward: literal natural-language text catch (Latin + Vietnamese diacritics)
NATURAL_TEXT_RE = re.compile(r"[A-Za-zÀ-ỹĐđ]{3,}")

# Exempt phrases from backward catch (project nouns / well-known abbreviations)
BACKWARD_EXEMPT = {
    "p", "f", "s",                          # pass/fail/skip prompt tokens
    "PASS", "FAIL", "SKIP", "WARN", "BLOCK",
    "vi", "en",
    "true", "false", "null",
    "URL", "UI", "API", "UAT",
    "GET", "POST", "PUT", "DELETE", "PATCH",
}


def _read_narration_strings() -> dict:
    """Lightweight YAML parse of narration-strings.yaml. Returns dict of
    {key: {vi: str, en: str}}."""
    repo = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
    candidates = [
        repo / ".claude" / "commands" / "vg" / "_shared" / "narration-strings.yaml",
        repo / "commands" / "vg" / "_shared" / "narration-strings.yaml",
    ]
    path = next((p for p in candidates if p.exists()), None)
    if path is None:
        return {}
    text = path.read_text(encoding="utf-8", errors="ignore")
    out: dict = {}
    current_key: str | None = None
    current_body: dict = {}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        # Top-level key: `key_name:`
        m_key = re.match(r"^([a-z_][a-z0-9_]*)\s*:\s*$", line)
        if m_key:
            if current_key:
                out[current_key] = current_body
            current_key = m_key.group(1)
            current_body = {}
            continue
        # Locale child: `  vi: "..."` or `  en: ...`
        m_loc = re.match(r"^\s+(vi|en|ja|ko|fr|de|es|zh)\s*:\s*[\"']?(.+?)[\"']?\s*$", line)
        if m_loc and current_key:
            current_body[m_loc.group(1)] = m_loc.group(2).rstrip("\"' ")
    if current_key:
        out[current_key] = current_body
    return out


def _read_locale() -> str:
    """Resolve narration.locale from vg.config.md (default 'vi')."""
    repo = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
    for c in [repo / ".claude" / "vg.config.md", repo / "vg.config.md",
              repo / "vg.config.template.md"]:
        if c.exists():
            text = c.read_text(encoding="utf-8", errors="ignore")
            m = re.search(
                r"^narration:\s*\n(?:[ \t]+.*\n)*?\s+locale:\s*[\"']?([a-z]{2})[\"']?",
                text, re.MULTILINE,
            )
            if m:
                return m.group(1)
    return "vi"


def _strip_for_backward(text: str, narration_values: list[str] | None = None) -> str:
    """Remove markdown/html/interpolation noise so backward scan sees only
    plain prose.

    B99 v4.69.2 (issue #199): when called on RENDERED UAT-NARRATIVE.md, any
    `{{uat_*}}` interpolation has already been replaced by the locale value
    from narration-strings.yaml. Pre-B99, the backward scan caught those
    locale values as hardcoded literals — 30+ false positives blocked
    /vg:accept step 4b. Fix: subtract all known narration values from the
    cleaned text BEFORE the natural-text scan. Anything that remains is
    actual hardcoded literal (true violation).
    """
    cleaned = text
    for pat in MD_STRIP_PATTERNS:
        cleaned = pat.sub(" ", cleaned)
    cleaned = ANY_INTERP_RE.sub(" ", cleaned)
    # B99 v4.69.2: scrub interpolated narration values from rendered output
    if narration_values:
        # Process longer values first so a longer string isn't shadowed by a
        # shorter substring (e.g. "Tiền điều kiện" before "điều kiện")
        for val in sorted(narration_values, key=len, reverse=True):
            if val and len(val) >= 2:
                cleaned = cleaned.replace(val, " ")
    return cleaned


def _collect_narration_values(narration: dict) -> list[str]:
    """B99 v4.69.2: flatten all locale values from narration-strings.yaml
    into a single list. Used by `_strip_for_backward` to subtract legit
    interpolated content from backward scan input."""
    values: list[str] = []
    for key, body in narration.items():
        if isinstance(body, dict):
            for loc_val in body.values():
                if isinstance(loc_val, str) and loc_val.strip():
                    values.append(loc_val.strip())
    return values


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", help="Phase id (default mode: scan UAT-NARRATIVE.md)")
    ap.add_argument("--template", help="Path to UAT template file (alternative mode)")
    args = ap.parse_args()

    out = Output(validator="uat-strings-no-hardcode")
    with timer(out):
        if args.template:
            target = Path(args.template)
            if not target.exists():
                out.add(Evidence(type="missing_file",
                                 message=f"Template not found: {target}"))
                emit_and_exit(out)
            target_paths = [target]
        elif args.phase:
            phase_dir = find_phase_dir(args.phase)
            if not phase_dir:
                out.add(Evidence(type="missing_file",
                                 message=f"Phase dir not found for {args.phase}"))
                emit_and_exit(out)
            narrative = phase_dir / "UAT-NARRATIVE.md"
            if not narrative.exists():
                out.add(Evidence(
                    type="missing_file",
                    message="UAT-NARRATIVE.md not found",
                    file=str(narrative),
                    fix_hint="Run /vg:accept step 4b to generate UAT-NARRATIVE.md.",
                ))
                emit_and_exit(out)
            target_paths = [narrative]
        else:
            out.add(Evidence(type="info",
                             message="Provide --phase OR --template"))
            emit_and_exit(out)

        narration = _read_narration_strings()
        locale = _read_locale()

        for tgt in target_paths:
            text = tgt.read_text(encoding="utf-8", errors="ignore")

            # Forward check
            for m in UAT_KEY_REF_RE.finditer(text):
                key = m.group(1)
                line_no = text[:m.start()].count("\n") + 1
                if key not in narration:
                    out.add(Evidence(
                        type="missing_file",
                        message=f"UAT key '{key}' referenced but not in narration-strings.yaml",
                        file=str(tgt), line=line_no,
                        actual=key,
                        fix_hint=(
                            f"Add to commands/vg/_shared/narration-strings.yaml:\n"
                            f"{key}:\n  vi: \"...\"\n  en: \"...\""
                        ),
                    ))
                    continue
                body = narration[key]
                if locale not in body:
                    out.add(Evidence(
                        type="schema_violation",
                        message=(f"UAT key '{key}' missing locale '{locale}' "
                                 f"(has: {sorted(body.keys())})"),
                        file=str(tgt), line=line_no,
                        expected=locale, actual=sorted(body.keys()),
                        fix_hint=f"Add `{locale}: \"...\"` under `{key}:` in narration-strings.yaml",
                    ))

            # Backward check
            # B99 v4.69.2 (issue #199): rendered narrative already has {{uat_*}}
            # replaced by locale values from narration-strings.yaml. Subtract
            # those known values before scanning for hardcoded literals — else
            # validator flags VN labels as i18n leaks when they came via legit
            # interpolation.
            narration_values = _collect_narration_values(narration)
            cleaned = _strip_for_backward(text, narration_values=narration_values)
            for m in NATURAL_TEXT_RE.finditer(cleaned):
                token = m.group(0)
                if token in BACKWARD_EXEMPT or token.lower() in BACKWARD_EXEMPT:
                    continue
                # Heuristic exemption: ALL-UPPERCASE acronyms ≤4 chars
                if token.isupper() and len(token) <= 4:
                    continue
                line_no = cleaned[:m.start()].count("\n") + 1
                out.add(Evidence(
                    type="semantic_check_failed",
                    message=(f"Literal text '{token}' outside `{{{{...}}}}` "
                             f"interpolation (potential i18n leak)"),
                    file=str(tgt), line=line_no,
                    actual=token,
                    fix_hint=(
                        "Move this string to commands/vg/_shared/narration-strings.yaml "
                        "as a uat_* key, then reference via {{uat_<key>}} in template. "
                        "If string is DATA (extracted URL/role/path), use {{var.*}} "
                        "convention. See D-18 § implementation."
                    ),
                ))
                # Cap noisy output: stop after 30 backward findings
                if sum(1 for e in out.evidence if e.type == "semantic_check_failed") >= 30:
                    out.evidence.append(Evidence(
                        type="info",
                        message="Stopped backward scan after 30 findings (suppressed remainder).",
                    ))
                    break

        if not out.evidence:
            out.evidence.append(Evidence(
                type="info",
                message="UAT strings strict policy passed (forward + backward)",
            ))

    emit_and_exit(out)


if __name__ == "__main__":
    main()
