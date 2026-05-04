#!/usr/bin/env python3
"""
Validator: i18n-coverage.py

B9.2 (v2.4 hardening, 2026-04-23): verify every user-visible string
is (a) wrapped in a translation function, (b) keyed into all declared
locales. Catches three UX drifts:

  1. Hardcoded English/Vietnamese strings in JSX (forgot to call t(...))
  2. t('foo.bar') where `foo.bar` not in default locale file
  3. Keys present in one locale but missing from others (partial i18n)

Scope: JSX/TSX/Vue source files + locale JSON files per config.
Cheap regex scan (<3s typical FE project).

Usage:
  i18n-coverage.py --phase <N>

Exit codes:
  0 PASS (full coverage) or WARN (hardcoded within threshold)
  1 BLOCK (missing keys OR hardcoded ratio exceeds threshold)

Config (vg.config.md, optional):
  i18n:
    enabled: true
    default_locale: "vi"
    locales_dir: "apps/web/public/locales"
    source_globs: ["apps/web/src/**/*.{tsx,jsx}"]
    translate_fns: ["t", "i18n.t", "translate"]  # function names to recognize
    block_on_missing_key: true
    allow_hardcoded_threshold: 0.05   # 5% of strings allowed hardcoded
    allowlist_file: ".vg/i18n-allowlist.yml"
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, timer, emit_and_exit, find_phase_dir  # noqa: E402
from _i18n import t  # noqa: E402

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()

DEFAULT_CONFIG = {
    "enabled": True,
    "default_locale": "vi",
    "locales_dir": "apps/web/public/locales",
    "source_globs": [
        "apps/web/src/**/*.tsx",
        "apps/web/src/**/*.jsx",
        "apps/*/src/**/*.tsx",
    ],
    "translate_fns": ["t", "i18n.t", "translate"],
    "block_on_missing_key": True,
    "allow_hardcoded_threshold": 0.05,
    "allowlist_file": ".vg/i18n-allowlist.yml",
}

# Match t('key.path') / i18n.t("key.path") / translate(`key.path`)
# Captures the key string
TRANSLATE_CALL_RE = re.compile(
    r"\b(?:t|i18n\.t|translate)\s*\(\s*['\"`]([a-zA-Z0-9_.\-]+)['\"`]",
)

# Suspect hardcoded: JSX text content that's not whitespace/number-only
# Matches: >Submit<  >Đăng ký<  label="Submit"  placeholder="Nhập..."
# Filters: pure number, icon-only (single char), templated {var}
HARDCODED_JSX_RE = re.compile(
    r">\s*([A-Z][A-Za-zÀ-ỹ][A-Za-zÀ-ỹ0-9 ,\.\-!?]{2,60})\s*<",
)
HARDCODED_ATTR_RE = re.compile(
    r'(?:label|placeholder|title|alt|aria-label)\s*=\s*"([A-Z][A-Za-zÀ-ỹ][^"]{2,60})"',
)

# Keys that look OK even if hardcoded (tech codes, UI-only IDs, icons)
TECH_CODE_RE = re.compile(r"^[A-Z_]+$|^\d+$|^[A-Z]{2,5}-\d+$")


# ─────────────────────────────────────────────────────────────────────────

def _read_config() -> dict:
    cfg = REPO_ROOT / ".claude" / "vg.config.md"
    merged = dict(DEFAULT_CONFIG)
    if not cfg.exists():
        return merged
    text = cfg.read_text(encoding="utf-8", errors="replace")
    # Check disabled
    m = re.search(r"^i18n:\s*\n\s+enabled:\s*(true|false)", text, re.MULTILINE)
    if m and m.group(1) == "false":
        merged["enabled"] = False
    # default_locale, locales_dir overrides
    for key in ("default_locale", "locales_dir"):
        m = re.search(rf"^\s+{key}:\s*['\"]?([\w\-./]+)['\"]?\s*$",
                      text, re.MULTILINE)
        if m:
            merged[key] = m.group(1)
    m = re.search(r"^\s+block_on_missing_key:\s*(true|false)",
                  text, re.MULTILINE)
    if m:
        merged["block_on_missing_key"] = m.group(1) == "true"
    m = re.search(r"^\s+allow_hardcoded_threshold:\s*([\d.]+)",
                  text, re.MULTILINE)
    if m:
        merged["allow_hardcoded_threshold"] = float(m.group(1))
    return merged


def _load_allowlist(path: str) -> list[re.Pattern]:
    p = REPO_ROOT / path
    if not p.exists():
        return []
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
        patterns = data.get("patterns", []) if isinstance(data, dict) else []
        return [re.compile(r) for r in patterns]
    except Exception:
        return []


def _locale_files(cfg: dict) -> dict[str, Path]:
    """Return mapping locale_code → first JSON file for that locale."""
    base = REPO_ROOT / cfg["locales_dir"]
    if not base.exists():
        return {}
    files: dict[str, Path] = {}
    # Common patterns: {lang}/common.json, {lang}.json, locales/{lang}/*.json
    for p in base.iterdir():
        if p.is_dir():
            # e.g. locales/vi/common.json — pick any .json file
            jsons = list(p.glob("*.json"))
            if jsons:
                files[p.name] = jsons[0]
        elif p.suffix == ".json":
            files[p.stem] = p
    return files


def _flatten_keys(data, prefix: str = "") -> set[str]:
    keys: set[str] = set()
    if isinstance(data, dict):
        for k, v in data.items():
            kp = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                keys |= _flatten_keys(v, kp)
            else:
                keys.add(kp)
    return keys


def _source_files(globs: list[str], commits: int = 10) -> list[Path]:
    files: set[Path] = set()
    try:
        diff = subprocess.run(
            ["git", "diff", "--name-only", f"HEAD~{commits}", "HEAD"],
            cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=10,
        )
        for line in diff.stdout.splitlines():
            p = REPO_ROOT / line.strip()
            if p.exists() and _matches_glob(line.strip(), globs):
                files.add(p)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    if not files:
        for g in globs:
            for p in REPO_ROOT.glob(g):
                if p.is_file():
                    files.add(p)
                if len(files) >= 300:
                    break
    return sorted(files)


def _matches_glob(rel: str, globs: list[str]) -> bool:
    from fnmatch import fnmatch
    for g in globs:
        if "{" in g and "}" in g:
            pre, rest = g.split("{", 1)
            exts, suf = rest.split("}", 1)
            for e in exts.split(","):
                if fnmatch(rel, f"{pre}{e}{suf}"):
                    return True
        else:
            if fnmatch(rel, g):
                return True
    return False


# ─────────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    ap.add_argument("--commits", type=int, default=10)
    args = ap.parse_args()

    out = Output(validator="i18n-coverage")
    with timer(out):
        cfg = _read_config()
        if not cfg["enabled"]:
            emit_and_exit(out)

        # phase_dir optional — validator scans source regardless
        find_phase_dir(args.phase)

        locales = _locale_files(cfg)
        if not locales:
            # No locale infra — project hasn't set up i18n, skip gracefully
            emit_and_exit(out)

        default = cfg["default_locale"]
        if default not in locales:
            out.warn(Evidence(
                type="i18n_default_locale_missing",
                message=t("i18n.default_missing.message", locale=default),
                actual=",".join(locales.keys()),
                fix_hint=t("i18n.default_missing.fix_hint", locale=default),
            ))
            emit_and_exit(out)

        # Build key inventory per locale
        locale_keys: dict[str, set[str]] = {}
        for code, path in locales.items():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                locale_keys[code] = _flatten_keys(data)
            except (OSError, json.JSONDecodeError):
                locale_keys[code] = set()

        default_keys = locale_keys[default]

        # Scan source for t('key') calls + hardcoded strings
        files = _source_files(cfg["source_globs"], args.commits)
        if not files:
            emit_and_exit(out)

        allowlist = _load_allowlist(cfg["allowlist_file"])
        translate_calls: list[tuple[str, Path, int]] = []  # (key, file, line)
        hardcoded: list[tuple[str, Path, int]] = []
        total_strings = 0

        for fp in files:
            rel = fp.relative_to(REPO_ROOT).as_posix()
            if any(p.search(rel) for p in allowlist):
                continue
            try:
                text = fp.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for m in TRANSLATE_CALL_RE.finditer(text):
                line_num = text.count("\n", 0, m.start()) + 1
                translate_calls.append((m.group(1), fp, line_num))
                total_strings += 1
            for pattern in (HARDCODED_JSX_RE, HARDCODED_ATTR_RE):
                for m in pattern.finditer(text):
                    val = m.group(1).strip()
                    if TECH_CODE_RE.match(val):
                        continue
                    # Skip if any allowlist regex matches the value
                    if any(p.search(val) for p in allowlist):
                        continue
                    line_num = text.count("\n", 0, m.start()) + 1
                    hardcoded.append((val, fp, line_num))
                    total_strings += 1

        # Gate 1: missing keys (t('x.y') where x.y not in default locale)
        missing_keys = [
            (k, f, ln) for (k, f, ln) in translate_calls
            if k not in default_keys
        ]
        # Gate 2: cross-locale diff (key present in default, missing in others)
        cross_missing: dict[str, set[str]] = {}
        for code, keys in locale_keys.items():
            if code == default:
                continue
            diff = default_keys - keys
            if diff:
                cross_missing[code] = diff

        # Gate 3: hardcoded ratio
        hardcoded_ratio = (
            len(hardcoded) / total_strings if total_strings else 0.0
        )

        if missing_keys and cfg["block_on_missing_key"]:
            sample = "; ".join(
                f"{k} ({f.relative_to(REPO_ROOT).as_posix()}:{ln})"
                for k, f, ln in missing_keys[:10]
            )
            out.add(Evidence(
                type="i18n_missing_keys",
                message=t(
                    "i18n.missing_keys.message",
                    count=len(missing_keys), locale=default,
                ),
                actual=sample,
                fix_hint=t("i18n.missing_keys.fix_hint", locale=default),
            ))

        if cross_missing:
            sample_parts = []
            for code, keys in list(cross_missing.items())[:3]:
                sample_parts.append(
                    f"{code}: {', '.join(list(keys)[:5])}"
                    + (f" (+{len(keys)-5} more)" if len(keys) > 5 else "")
                )
            # Cross-locale drift is always block when block_on_missing_key
            if cfg["block_on_missing_key"]:
                out.add(Evidence(
                    type="i18n_cross_locale_gaps",
                    message=t(
                        "i18n.cross_locale.message",
                        default_locale=default,
                        missing_total=sum(len(v) for v in cross_missing.values()),
                    ),
                    actual="; ".join(sample_parts),
                    fix_hint=t("i18n.cross_locale.fix_hint"),
                ))
            else:
                out.warn(Evidence(
                    type="i18n_cross_locale_gaps",
                    message=t(
                        "i18n.cross_locale.message",
                        default_locale=default,
                        missing_total=sum(len(v) for v in cross_missing.values()),
                    ),
                    actual="; ".join(sample_parts),
                    fix_hint=t("i18n.cross_locale.fix_hint"),
                ))

        if hardcoded_ratio > cfg["allow_hardcoded_threshold"]:
            sample = "; ".join(
                f"'{v[:30]}' ({f.relative_to(REPO_ROOT).as_posix()}:{ln})"
                for v, f, ln in hardcoded[:10]
            )
            out.add(Evidence(
                type="i18n_hardcoded_exceeds_threshold",
                message=t(
                    "i18n.hardcoded.message",
                    count=len(hardcoded),
                    ratio=f"{hardcoded_ratio*100:.1f}",
                    threshold=f"{cfg['allow_hardcoded_threshold']*100:.1f}",
                ),
                actual=sample,
                fix_hint=t("i18n.hardcoded.fix_hint"),
            ))
        elif hardcoded:
            # Under threshold — still surface as WARN for visibility
            out.warn(Evidence(
                type="i18n_hardcoded_advisory",
                message=t(
                    "i18n.hardcoded_advisory.message",
                    count=len(hardcoded),
                ),
                actual="; ".join(
                    f"'{v[:30]}' ({f.relative_to(REPO_ROOT).as_posix()}:{ln})"
                    for v, f, ln in hardcoded[:5]
                ),
                fix_hint=t("i18n.hardcoded_advisory.fix_hint"),
            ))

    emit_and_exit(out)


if __name__ == "__main__":
    main()
