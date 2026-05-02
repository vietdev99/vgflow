#!/usr/bin/env python3
"""
filter-steps.py — Deterministic profile filter for VG command files.

Parses <step name="..." profile="..." mode="..."> tags in a command markdown
file and returns the step IDs that apply to the given profile/mode.

Used by create_task_tracker in every vg/* command as a safety net: the bash
output is the expected task list. AI must create matching tasks — a mismatch
triggers BLOCK. Prevents AI from silently skipping profile-filtered steps.

USAGE
  python3 filter-steps.py --command .claude/commands/vg/build.md --profile web-fullstack
  python3 filter-steps.py --command .claude/commands/vg/review.md --profile web-fullstack --mode full
  python3 filter-steps.py --command ... --profile ... --output-ids    # CSV step names
  python3 filter-steps.py --command ... --profile ... --output-count  # just N

VALID PROFILES
  Web:    web-fullstack, web-frontend-only, web-backend-only
  Mobile: mobile-rn, mobile-flutter, mobile-native-ios, mobile-native-android,
          mobile-hybrid
  Other:  cli-tool, library

WILDCARDS IN <step profile="..."> TAG
  "mobile-*" — expands to all mobile profiles
  "web-*"    — expands to all web profiles
  Example:   <step name="5a_deploy" profile="web-fullstack,mobile-*">
             → runs for web-fullstack AND any mobile profile.

EXIT CODES
  0  ok
  1  bad args / file not found
  2  invalid profile
  3  parse error (malformed <step> tag)
"""
import argparse
import re
import sys
from pathlib import Path

# --- Profile groups ---
WEB_PROFILES = frozenset({
    "web-fullstack",
    "web-frontend-only",
    "web-backend-only",
})

MOBILE_PROFILES = frozenset({
    "mobile-rn",
    "mobile-flutter",
    "mobile-native-ios",
    "mobile-native-android",
    "mobile-hybrid",
})

OTHER_PROFILES = frozenset({
    "cli-tool",
    "library",
})

VALID_PROFILES = WEB_PROFILES | MOBILE_PROFILES | OTHER_PROFILES

# Map wildcard token -> set of profile names it expands to.
# Keep this table authoritative so callers can query without reimplementing.
WILDCARD_GROUPS = {
    "web-*": WEB_PROFILES,
    "mobile-*": MOBILE_PROFILES,
}


def expand_wildcards(tokens):
    """
    Expand wildcard tokens (e.g. "mobile-*") in a list of profile tokens.

    Non-wildcard tokens pass through unchanged.
    Unknown wildcards are left as-is (caller can decide to warn/ignore).

    Returns a set of concrete profile names (no wildcards).
    """
    expanded = set()
    for tok in tokens:
        tok = tok.strip()
        if not tok:
            continue
        if tok in WILDCARD_GROUPS:
            expanded.update(WILDCARD_GROUPS[tok])
        else:
            expanded.add(tok)
    return expanded


# Matches <step name="X"> or <step name="X" profile="a,b">
# Non-greedy, handles attribute order flexibility
STEP_RE = re.compile(
    r'<step\s+'
    r'(?P<attrs>[^>]*?)'
    r'>',
    re.MULTILINE,
)

NAME_RE = re.compile(r'name="(?P<val>[^"]+)"')
PROFILE_RE = re.compile(r'profile="(?P<val>[^"]+)"')
MODE_RE = re.compile(r'mode="(?P<val>[^"]+)"')


def parse_steps(text: str):
    """Yield (name, profile_set|None, mode_set|None) for each <step> tag.

    profile_set is None when the step has no profile= attribute (applies to all).
    profile_set is a set[str] of concrete profile names after wildcard expansion.
    mode_set is None when the step has no mode= attribute (applies to all modes).
    """
    for match in STEP_RE.finditer(text):
        attrs = match.group("attrs")
        name_match = NAME_RE.search(attrs)
        if not name_match:
            raise ValueError(
                f"<step> at offset {match.start()} missing name= attribute: {attrs!r}"
            )
        name = name_match.group("val")
        if name == "...":
            # Ignore documentation placeholders such as
            # `<step name="...">` in prose. They are not executable steps.
            continue

        profile_match = PROFILE_RE.search(attrs)
        if profile_match:
            raw_tokens = [p.strip() for p in profile_match.group("val").split(",")]
            profile_set = expand_wildcards(raw_tokens)
        else:
            profile_set = None  # means "all profiles"

        mode_match = MODE_RE.search(attrs)
        if mode_match:
            mode_set = {
                m.strip()
                for m in mode_match.group("val").split(",")
                if m.strip()
            }
        else:
            mode_set = None

        yield name, profile_set, mode_set


def parse_steps_from_frontmatter(text: str):
    """Fallback parser for slim entry SKILL.md format (no <step> XML tags).

    Reads runtime_contract.must_touch_markers from YAML frontmatter. Each entry is:
      - bare string "name"                                → universal step
      - {name: "x", profile: "web-*,..."}                 → profile-gated step
      - {name: "x", required_unless_flag: "--skip-foo"}   → optional step (returned regardless;
                                                              caller deals with skip)

    Returns list of (name, profile_set | None, mode_set | None) — same shape as parse_steps.
    """
    if not text.startswith("---\n"):
        return []
    try:
        end = text.index("\n---\n", 4)
    except ValueError:
        return []
    fm_text = text[4:end]
    try:
        import yaml  # PyYAML
    except ImportError:
        return []
    try:
        fm = yaml.safe_load(fm_text)
    except yaml.YAMLError:
        return []
    if not isinstance(fm, dict):
        return []
    contract = fm.get("runtime_contract", {})
    if not isinstance(contract, dict):
        return []
    markers = contract.get("must_touch_markers", [])
    if not isinstance(markers, list):
        return []

    out = []
    for entry in markers:
        if isinstance(entry, str):
            out.append((entry, None, None))
        elif isinstance(entry, dict):
            name = entry.get("name")
            if not name:
                continue
            profile_value = entry.get("profile")
            if profile_value:
                tokens = [p.strip() for p in str(profile_value).split(",")]
                profile_set = expand_wildcards(tokens)
            else:
                profile_set = None
            out.append((name, profile_set, None))
    return out


def filter_for_profile(steps, profile: str, mode=None):
    """Return list of step names applicable to the given profile/mode."""
    applicable = []
    for name, profile_set, mode_set in steps:
        profile_ok = profile_set is None or profile in profile_set
        mode_ok = mode_set is None or not mode or mode in mode_set
        if profile_ok and mode_ok:
            applicable.append(name)
    return applicable


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--command", required=True, help="Path to vg command markdown file")
    ap.add_argument("--profile", required=True, help="Profile name")
    ap.add_argument("--mode", default=None, help="Optional workflow mode, e.g. full/regression")
    out = ap.add_mutually_exclusive_group()
    out.add_argument("--output-ids", action="store_true", help="Print CSV of step names")
    out.add_argument("--output-count", action="store_true", help="Print count only")
    args = ap.parse_args()

    if args.profile not in VALID_PROFILES:
        print(
            f"ERROR: invalid profile '{args.profile}'. Valid: {sorted(VALID_PROFILES)}",
            file=sys.stderr,
        )
        return 2

    cmd_path = Path(args.command)
    if not cmd_path.is_file():
        print(f"ERROR: command file not found: {cmd_path}", file=sys.stderr)
        return 1

    try:
        text = cmd_path.read_text(encoding="utf-8")
    except OSError as e:
        print(f"ERROR: read failed: {e}", file=sys.stderr)
        return 1

    try:
        steps = list(parse_steps(text))
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 3

    # Fallback: slim entry SKILL.md format has no <step> XML tags. Read step
    # list from runtime_contract.must_touch_markers in YAML frontmatter.
    if not steps:
        steps = parse_steps_from_frontmatter(text)

    applicable = filter_for_profile(steps, args.profile, args.mode)

    # Hard-fail when zero steps — prevents silent telemetry violation downstream.
    # If the command file genuinely has no steps for this profile, that is a
    # config bug (or the file uses an unsupported format).
    if not applicable:
        print(
            f"ERROR: 0 steps applicable for profile '{args.profile}' in {cmd_path}.\n"
            f"  total parsed steps: {len(steps)}\n"
            f"  hint: command file must have either <step> XML tags OR\n"
            f"        runtime_contract.must_touch_markers in YAML frontmatter.\n"
            f"        Profile-gated entries use {{name: ..., profile: 'csv'}}.",
            file=sys.stderr,
        )
        return 4

    if args.output_count:
        print(len(applicable))
    elif args.output_ids:
        print(",".join(applicable))
    else:
        # Default: one per line, human-friendly
        for name in applicable:
            print(name)

    return 0


if __name__ == "__main__":
    sys.exit(main())
