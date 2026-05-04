"""
B8.0 — Python i18n helper for validators.

User requirement (2026-04-23): "ở tất cả các khâu, trả lời hoặc hiển thị
thông tin đều phải là ngôn ngữ loài người, cố gắng giải thích cụ thể vấn đề,
bằng ngôn ngữ được cài trong vg.config.md. Đây là điều bắt buộc."

Every validator Evidence.message / fix_hint goes through `t()` so output
language follows `narration.locale` in vg.config.md. Falls back to
`narration.fallback_locale` then English literal if a key is missing —
workflow never crashes due to missing translation.

Keys live in narration-strings*.yaml under
`.claude/commands/vg/_shared/`. Pattern: `<validator>.<type>.<field>`
where field ∈ {message, fix_hint, summary}.

Usage:
    from _i18n import t
    evidence = Evidence(
        type="phantom_citation",
        message=t("commit_attr.phantom_citation.message", refs=..., phase=...),
        fix_hint=t("commit_attr.phantom_citation.fix_hint", phase_dir=...),
    )

Design:
- Lazy load + cache (first `t()` reads files once).
- Regex-based vg.config.md parser — no YAML dependency for config since
  we only need 2 keys; keeps helper runnable on minimal envs.
- PyYAML required for strings tables; if missing, `t()` returns the key
  literal (graceful degradation, warned via a one-shot stderr notice).
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

_config_cache: dict[str, str] | None = None
_strings_cache: dict[str, dict[str, str]] | None = None
_yaml_warned: bool = False


def _resolve_paths() -> tuple[Path, Path, list[Path]]:
    """Recompute paths from current env (so monkeypatched VG_REPO_ROOT works
    across cache resets). Cheaper than pulling env on every t() call."""
    repo = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
    cfg = repo / ".claude" / "vg.config.md"
    shared = repo / ".claude" / "commands" / "vg" / "_shared"
    return repo, cfg, [
        shared / "narration-strings.yaml",
        shared / "narration-strings-validators.yaml",
    ]


def _read_narration_config() -> dict[str, str]:
    """Parse `narration:` block from vg.config.md.

    Returns {'locale': <primary>, 'fallback_locale': <fallback>}.
    Defaults to vi + en. Graceful if file missing / malformed.
    """
    global _config_cache
    if _config_cache is not None:
        return _config_cache

    result = {"locale": "vi", "fallback_locale": "en"}

    _, config_path, _ = _resolve_paths()
    if not config_path.exists():
        _config_cache = result
        return result

    try:
        text = config_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        _config_cache = result
        return result

    in_narration = False
    indent_baseline: int | None = None
    for line in text.splitlines():
        # Detect `narration:` top-level section (line starts at col 0, ends with :)
        if re.match(r"^narration:\s*$", line):
            in_narration = True
            continue
        if not in_narration:
            continue
        # Any non-indented, non-comment line ends the block.
        if line and not line.startswith((" ", "\t", "#")):
            break
        # Extract `<key>: <value>` (2-space indent)
        m = re.match(r"^(\s+)([\w_]+):\s*[\"']?([^\"'#\n]+?)[\"']?\s*(?:#.*)?$", line)
        if m:
            indent, key, value = m.group(1), m.group(2), m.group(3).strip()
            if indent_baseline is None:
                indent_baseline = len(indent)
            if len(indent) == indent_baseline and key in result:
                result[key] = value

    _config_cache = result
    return result


def _flatten_into(
    node: dict, out: dict[str, dict[str, str]], prefix: str,
) -> None:
    """Walk yaml tree; leaves whose values are all strings become final
    entries keyed by dotted path. Supports BOTH nested and flat layouts."""
    for k, v in node.items():
        key = f"{prefix}.{k}" if prefix else str(k)
        if isinstance(v, dict):
            # Treat as locale map iff every value is a string.
            if v and all(isinstance(vv, str) for vv in v.values()):
                out[key] = {str(lk): str(lv) for lk, lv in v.items()}
            else:
                _flatten_into(v, out, key)


def _read_strings() -> dict[str, dict[str, str]]:
    """Load + merge all narration-strings*.yaml into a flat key map."""
    global _strings_cache, _yaml_warned
    if _strings_cache is not None:
        return _strings_cache

    try:
        import yaml  # type: ignore
    except ImportError:
        if not _yaml_warned:
            print(
                "\033[33m_i18n: PyYAML not installed — narration keys will fall \033[0m"
                "back to literal (validator output less readable).",
                file=sys.stderr,
            )
            _yaml_warned = True
        _strings_cache = {}
        return {}

    _, _, strings_paths = _resolve_paths()
    merged: dict[str, dict[str, str]] = {}
    for p in strings_paths:
        if not p.exists():
            continue
        try:
            data = yaml.safe_load(p.read_text(encoding="utf-8", errors="replace")) or {}
        except Exception as e:
            print(f"\033[33m_i18n: {p.name} parse error: {e}\033[0m", file=sys.stderr)
            continue
        _flatten_into(data, merged, prefix="")
    _strings_cache = merged
    return merged


def t(key: str, **kwargs: object) -> str:
    """Translate + interpolate a narration key.

    Lookup order:
      1. config.narration.locale (primary)
      2. config.narration.fallback_locale
      3. "en" (hardcoded last-resort)
      4. key literal (absolute fallback — never raises)

    Placeholders in template use Python str.format(): `{name}` / `{count}`.
    Missing placeholders → template returned as-is (no crash).
    """
    config = _read_narration_config()
    strings = _read_strings()
    entry = strings.get(key, {})
    primary = config["locale"]
    fallback = config["fallback_locale"]
    template = (
        entry.get(primary)
        or entry.get(fallback)
        or entry.get("en")
        or key
    )
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError, ValueError):
        return template


def _reset_cache_for_tests() -> None:
    """Internal — clear caches. Used by tests that swap locale at runtime."""
    global _config_cache, _strings_cache, _yaml_warned
    _config_cache = None
    _strings_cache = None
    _yaml_warned = False


__all__ = ["t", "_reset_cache_for_tests"]
