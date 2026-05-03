#!/usr/bin/env python3
"""
VG Bootstrap Loader (v1.15.0)

Responsible for:
  1. Loading `.vg/bootstrap/overlay.yml` and deep-merging onto vanilla config
  2. Loading `.vg/bootstrap/rules/*.md` and filtering by scope for current context
  3. Loading `.vg/bootstrap/patches/*.md` and mapping to {step, anchor}
  4. Schema validation — reject keys outside overlay.schema.yml allowlist
  5. Emitting compiled output for consumer commands

Consumer commands source this via:
    python .claude/scripts/bootstrap-loader.py \\
        --command review --phase 7.8 --step review \\
        --surfaces web,api --touched-paths 'apps/web/**' \\
        --has-mutation true \\
        --emit rules        # or: overlay | patches | all

Returns JSON to stdout.

Fail-closed: on any schema violation → emit {} for the offending artifact,
log to stderr, continue. Loader NEVER crashes the caller.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Iterable

# Locate bootstrap zone relative to repo root (assume cwd = repo root)
BOOTSTRAP_DIR = Path(".vg/bootstrap")
SCHEMA_DIR = BOOTSTRAP_DIR / "schema"

# Import scope evaluator from same directory
sys.path.insert(0, str(Path(__file__).parent))
try:
    from scope_evaluator import evaluate_scope, ScopeEvalError  # type: ignore
except ImportError:
    # Fallback — import via file path munging (dash in filename)
    import importlib.util

    _spec = importlib.util.spec_from_file_location(
        "scope_evaluator", Path(__file__).parent / "scope-evaluator.py"
    )
    _mod = importlib.util.module_from_spec(_spec)  # type: ignore
    _spec.loader.exec_module(_mod)  # type: ignore
    evaluate_scope = _mod.evaluate_scope
    ScopeEvalError = _mod.ScopeEvalError


# ---------- YAML parsing (minimal, no PyYAML dependency) ----------
def _parse_yaml(text: str) -> Any:
    """Minimal YAML subset parser — handles dict/list/scalar. No anchors, no flow.
    Uses PyYAML if available, else a simple line parser."""
    try:
        import yaml  # type: ignore

        return yaml.safe_load(text)
    except ImportError:
        pass
    return _simple_yaml(text)


def _simple_yaml(text: str) -> Any:
    """Fallback YAML parser — good enough for overlay.yml/rule frontmatter."""
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    if not lines:
        return {}
    return _parse_block(lines, 0)[0]


def _parse_block(lines: list[str], indent: int) -> tuple[Any, int]:
    """Parse a YAML block at given indent. Returns (value, lines_consumed)."""
    if not lines:
        return None, 0

    first = lines[0]
    first_indent = len(first) - len(first.lstrip())

    if first_indent < indent:
        return None, 0

    # List?
    if first.lstrip().startswith("- "):
        return _parse_list(lines, first_indent)

    # Dict?
    if ":" in first:
        return _parse_dict(lines, first_indent)

    # Scalar
    return _parse_scalar(first.strip()), 1


def _parse_list(lines: list[str], indent: int) -> tuple[list, int]:
    result = []
    i = 0
    while i < len(lines):
        ln = lines[i]
        cur_indent = len(ln) - len(ln.lstrip())
        if cur_indent < indent:
            break
        if cur_indent == indent and ln.lstrip().startswith("- "):
            item_text = ln.lstrip()[2:].strip()
            # Case A: "- key: value" (inline dict-item with value) OR "- key:" (dict-item with nested block)
            if ":" in item_text:
                # Split key:value to decide inline vs nested
                key_part, _, rest_part = item_text.partition(":")
                key_part = key_part.strip()
                rest_part = rest_part.strip()
                # Item = dict starting at this key. Synthesize a dict block.
                inline_lines = [(" " * (indent + 2)) + item_text]
                # Collect continuation lines at DEEPER indent than the "- "
                j = i + 1
                while j < len(lines):
                    nl = lines[j]
                    nl_indent = len(nl) - len(nl.lstrip())
                    # Children of a list item sit at indent+2 (aligned with the content of "- key:")
                    # Anything at indent or less breaks out of this item
                    if nl_indent > indent:
                        inline_lines.append(nl)
                        j += 1
                    else:
                        break
                val, _ = _parse_dict(inline_lines, indent + 2)
                result.append(val if val else {key_part: _parse_scalar(rest_part) if rest_part else None})
                i = j
            elif not item_text:
                # bare "-" followed by nested block on next line
                sub, consumed = _parse_block(lines[i + 1 :], indent + 2)
                result.append(sub)
                i += 1 + consumed
            else:
                result.append(_parse_scalar(item_text))
                i += 1
        else:
            break
    return result, i


def _parse_dict(lines: list[str], indent: int) -> tuple[dict, int]:
    result = {}
    i = 0
    while i < len(lines):
        ln = lines[i]
        cur_indent = len(ln) - len(ln.lstrip())
        if cur_indent < indent:
            break
        if cur_indent > indent:
            i += 1
            continue
        if ":" not in ln:
            break
        key, _, rest = ln.lstrip().partition(":")
        key = key.strip()
        rest = rest.strip()
        if rest:
            result[key] = _parse_scalar(rest)
            i += 1
        else:
            # nested block
            sub, consumed = _parse_block(lines[i + 1 :], indent + 2)
            result[key] = sub if sub is not None else {}
            i += 1 + consumed
    return result, i


def _parse_scalar(s: str) -> Any:
    s = s.strip()
    if s.startswith("#"):
        return None
    # Strip inline comments (careful with quoted strings)
    if "#" in s and not (s.startswith("'") or s.startswith('"')):
        s = s.split("#", 1)[0].strip()
    if (s.startswith("'") and s.endswith("'")) or (s.startswith('"') and s.endswith('"')):
        return s[1:-1]
    if s.lower() in ("true", "yes"):
        return True
    if s.lower() in ("false", "no"):
        return False
    if s.lower() in ("null", "~", ""):
        return None
    try:
        if "." in s:
            return float(s)
        return int(s)
    except ValueError:
        pass
    # inline list [a, b, c]
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(x.strip()) for x in inner.split(",")]
    return s


# ---------- Schema validation ----------
def _load_schema() -> dict:
    schema_path = SCHEMA_DIR / "overlay.schema.yml"
    if not schema_path.exists():
        return {"allowlist": [], "denylist": []}
    try:
        return _parse_yaml(schema_path.read_text(encoding="utf-8")) or {}
    except Exception as e:
        print(f"\033[33mbootstrap-loader: schema parse failed: {e}\033[0m", file=sys.stderr)
        return {"allowlist": [], "denylist": []}


def _key_matches_pattern(key: str, pattern: str) -> bool:
    """Match dotted key against pattern with * and ** semantics.
    - 'foo.*'  = exactly one more segment
    - 'foo.**' = one or more segments
    - 'foo.bar' = exact
    """
    if pattern == key:
        return True
    # Convert to regex
    parts = pattern.split(".")
    key_parts = key.split(".")
    # Expand ** into arbitrary segments
    rx_parts = []
    for p in parts:
        if p == "**":
            rx_parts.append(r".+")
        elif p == "*":
            rx_parts.append(r"[^.]+")
        else:
            rx_parts.append(re.escape(p))
    rx = "^" + r"\.".join(rx_parts) + "$"
    return bool(re.match(rx, key))


def _walk_dotted(d: dict, prefix: str = "") -> Iterable[str]:
    """Yield dotted paths of leaf keys in a dict."""
    for k, v in d.items():
        path = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict) and v:
            yield from _walk_dotted(v, path)
        else:
            yield path


def validate_overlay(overlay: dict, schema: dict) -> tuple[dict, list[str]]:
    """Return (valid_subset, list_of_rejected_keys)."""
    allowlist = schema.get("allowlist", []) or []
    denylist = schema.get("denylist", []) or []

    rejected = []
    valid = {}

    for key in _walk_dotted(overlay):
        # denylist first (wins over allowlist)
        if any(_key_matches_pattern(key, p) for p in denylist):
            rejected.append(f"{key} (denylist)")
            continue
        if not any(_key_matches_pattern(key, p) for p in allowlist):
            rejected.append(f"{key} (not in allowlist)")
            continue
        # Copy this key into valid by walking overlay
        _set_dotted(valid, key, _get_dotted(overlay, key))

    return valid, rejected


def _get_dotted(d: dict, key: str) -> Any:
    cur = d
    for p in key.split("."):
        cur = cur[p]
    return cur


def _set_dotted(d: dict, key: str, value: Any) -> None:
    parts = key.split(".")
    cur = d
    for p in parts[:-1]:
        if p not in cur or not isinstance(cur[p], dict):
            cur[p] = {}
        cur = cur[p]
    cur[parts[-1]] = value


# ---------- Rule file parsing ----------
def _parse_rule_file(path: Path) -> dict | None:
    """Parse a rule file with YAML frontmatter + markdown body.
    Returns dict with frontmatter keys + 'prose' body, or None if malformed.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"\033[33mbootstrap-loader: cannot read {path}: {e}\033[0m", file=sys.stderr)
        return None

    if not text.startswith("---"):
        print(f"\033[33mbootstrap-loader: {path} missing frontmatter\033[0m", file=sys.stderr)
        return None

    end = text.find("\n---", 4)
    if end == -1:
        print(f"\033[33mbootstrap-loader: {path} unterminated frontmatter\033[0m", file=sys.stderr)
        return None

    fm_text = text[4:end]
    body = text[end + 4 :].lstrip("\n")

    try:
        fm = _parse_yaml(fm_text) or {}
    except Exception as e:
        print(f"\033[33mbootstrap-loader: {path} frontmatter parse error: {e}\033[0m", file=sys.stderr)
        return None

    if not isinstance(fm, dict):
        return None

    fm["prose"] = body.strip()
    fm["_path"] = str(path)
    return fm


# ---------- Main API ----------
def load_overlay(overlay_path: Path | None = None) -> tuple[dict, list[str]]:
    """Load and validate overlay.yml. Returns (valid_overlay, rejected_keys)."""
    if overlay_path is None:
        overlay_path = BOOTSTRAP_DIR / "overlay.yml"
    if not overlay_path.exists():
        return {}, []
    try:
        raw = _parse_yaml(overlay_path.read_text(encoding="utf-8")) or {}
    except Exception as e:
        print(f"\033[33mbootstrap-loader: overlay.yml parse failed: {e}\033[0m", file=sys.stderr)
        return {}, ["<parse error>"]
    if not isinstance(raw, dict):
        return {}, ["<not a dict>"]
    schema = _load_schema()
    return validate_overlay(raw, schema)


def load_rules(
    context: dict,
    rules_dir: Path | None = None,
    include_dormant: bool = False,
) -> list[dict]:
    """Load rules/*.md, filter by scope matching context.
    Returns list of matched rule dicts (frontmatter + 'prose').
    """
    if rules_dir is None:
        rules_dir = BOOTSTRAP_DIR / "rules"
    if not rules_dir.exists():
        return []

    matched = []
    for rf in sorted(rules_dir.glob("*.md")):
        rule = _parse_rule_file(rf)
        if rule is None:
            continue
        if rule.get("status", "active") not in ("active", "experimental") and not include_dormant:
            continue
        scope = rule.get("scope")
        try:
            if evaluate_scope(scope, context):
                matched.append(rule)
        except ScopeEvalError as e:
            print(f"\033[33mbootstrap-loader: {rf} scope eval error: {e}\033[0m", file=sys.stderr)
            continue
    return matched


def load_patches(
    context: dict,
    command: str,
    patches_dir: Path | None = None,
) -> dict[str, str]:
    """Load patches/{command}.{anchor}.md, filter by scope.
    Returns {anchor: prose} map for the given command.
    """
    if patches_dir is None:
        patches_dir = BOOTSTRAP_DIR / "patches"
    if not patches_dir.exists():
        return {}

    anchors = {}
    for pf in sorted(patches_dir.glob(f"{command}.*.md")):
        patch = _parse_rule_file(pf)
        if patch is None:
            continue
        anchor = patch.get("anchor") or pf.stem.split(".", 1)[1] if "." in pf.stem else None
        if not anchor:
            continue
        scope = patch.get("scope")
        try:
            if evaluate_scope(scope, context):
                anchors[anchor] = patch.get("prose", "")
        except ScopeEvalError as e:
            print(f"\033[33mbootstrap-loader: patch scope error: {e}\033[0m", file=sys.stderr)
    return anchors


def build_context(args: argparse.Namespace) -> dict:
    """Build evaluation context from CLI flags."""
    surfaces = [s.strip() for s in (args.surfaces or "").split(",") if s.strip()]
    touched = [p.strip() for p in (args.touched_paths or "").split(",") if p.strip()]
    return {
        "phase": {
            "number": args.phase or "",
            "surfaces": surfaces,
            "touched_paths": touched,
            "has_mutation": (args.has_mutation or "").lower() == "true",
            "ui_audit_required": (args.ui_audit_required or "").lower() == "true",
            "is_api_only": "api" in surfaces and "web" not in surfaces,
        },
        "step": args.step or "",
        "command": args.command or "",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="VG Bootstrap Loader")
    ap.add_argument("--command", default="")
    ap.add_argument("--phase", default="")
    ap.add_argument("--step", default="")
    ap.add_argument("--surfaces", default="", help="comma-separated, e.g. web,api")
    ap.add_argument("--touched-paths", default="")
    ap.add_argument("--has-mutation", default="false")
    ap.add_argument("--ui-audit-required", default="false")
    ap.add_argument(
        "--emit",
        choices=["overlay", "rules", "patches", "all", "trace"],
        default="all",
    )
    args = ap.parse_args()

    context = build_context(args)

    out: dict = {"context": context}

    if args.emit in ("overlay", "all"):
        overlay, rejected = load_overlay()
        out["overlay"] = overlay
        out["overlay_rejected"] = rejected

    if args.emit in ("rules", "all"):
        rules = load_rules(context)
        out["rules"] = [
            {
                "id": r.get("id"),
                "title": r.get("title"),
                "target_step": r.get("target_step"),
                "action": r.get("action"),
                "prose": r.get("prose"),
                "confidence": r.get("confidence"),
                "_path": r.get("_path"),
            }
            for r in rules
        ]

    if args.emit in ("patches", "all"):
        out["patches"] = load_patches(context, args.command)

    if args.emit == "trace":
        # Trace mode: show what WOULD match with verbose info
        overlay, rejected = load_overlay()
        rules = load_rules(context, include_dormant=True)
        patches = load_patches(context, args.command)
        out = {
            "context": context,
            "overlay_keys": list(_walk_dotted(overlay)),
            "overlay_rejected": rejected,
            "rules_matched": [{"id": r.get("id"), "status": r.get("status")} for r in rules],
            "patches_matched": list(patches.keys()),
        }

    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
