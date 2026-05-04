#!/usr/bin/env python3
"""
telemetry-suggest.py — Phase E v2.5: Reactive Telemetry Suggestions

Reads VG telemetry data and emits 3 actionable suggestion types:
  1. always-pass skip  — validator consistently passes, safe reorder hint
  2. expensive-first reorder — slow validators should run late (fail-fast)
  3. override abuse warning — same --allow-* flag used too often recently

Stdlib-only. No pip dependencies.

Usage:
  python telemetry-suggest.py                    # JSONL to stdout
  python telemetry-suggest.py --format table     # human-readable table
  python telemetry-suggest.py --command vg:build # filter by command
  python telemetry-suggest.py --apply skip plan-granularity

UNQUARANTINABLE validators (verify-goal-security, etc.) are NEVER emitted
as skip candidates regardless of pass rate. This closes the "reactive gaming"
surface where an AI could suggest skipping security gates.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import quantiles
from typing import Any

# ── Repo root resolution ───────────────────────────────────────────────────
_HERE = Path(__file__).resolve()
# .claude/scripts/telemetry-suggest.py → repo root is 2 levels up
REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT", str(_HERE.parents[2])))

TELEMETRY_JSONL = REPO_ROOT / ".vg" / "telemetry.jsonl"
OVERRIDE_REGISTER = REPO_ROOT / ".vg" / "override-debt" / "register.jsonl"
ORCHESTRATOR = REPO_ROOT / ".claude" / "scripts" / "vg-orchestrator" / "__main__.py"
VG_CONFIG = REPO_ROOT / ".claude" / "vg.config.md"
SKIP_DIR = REPO_ROOT / ".vg" / "telemetry"

# ── Default config values ──────────────────────────────────────────────────
DEFAULT_SKIP_PASS_RATE = 0.98
DEFAULT_SKIP_MIN_SAMPLES = 10
DEFAULT_EXPENSIVE_THRESHOLD_MS = 5000
DEFAULT_OVERRIDE_WARN_COUNT_30D = 3


# ── Config loader ──────────────────────────────────────────────────────────

def _load_config(config_path: Path = VG_CONFIG) -> dict[str, Any]:
    """Parse telemetry.suggest.* values from vg.config.md (YAML inline block)."""
    defaults = {
        "skip_pass_rate_threshold": DEFAULT_SKIP_PASS_RATE,
        "skip_min_samples": DEFAULT_SKIP_MIN_SAMPLES,
        "expensive_threshold_ms": DEFAULT_EXPENSIVE_THRESHOLD_MS,
        "override_warn_count_30d": DEFAULT_OVERRIDE_WARN_COUNT_30D,
        "enabled": True,
    }
    if not config_path.exists():
        return defaults

    text = config_path.read_text(encoding="utf-8")

    # Find the telemetry: block, then the suggest: sub-block.
    # We do a minimal line-by-line YAML parse — no PyYAML needed.
    in_telemetry = False
    in_suggest = False
    indent_telemetry: int | None = None
    indent_suggest: int | None = None

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue

        indent = len(line) - len(stripped)

        if not in_telemetry:
            if stripped.startswith("telemetry:"):
                in_telemetry = True
                indent_telemetry = indent
            continue

        # Inside telemetry block
        if indent_telemetry is not None and indent <= indent_telemetry and stripped and not stripped.startswith("telemetry:"):
            # Left the telemetry block
            break

        if not in_suggest:
            if stripped.startswith("suggest:"):
                in_suggest = True
                indent_suggest = indent
            continue

        # Inside suggest block
        if indent_suggest is not None and indent <= indent_suggest and stripped and not stripped.startswith("suggest:"):
            break

        if ":" in stripped:
            key, _, val = stripped.partition(":")
            key = key.strip()
            val = val.strip().split("#")[0].strip()  # strip inline comments
            if key == "skip_pass_rate_threshold":
                try:
                    defaults[key] = float(val)
                except ValueError:
                    pass
            elif key in ("skip_min_samples", "expensive_threshold_ms", "override_warn_count_30d"):
                try:
                    defaults[key] = int(val)
                except ValueError:
                    pass
            elif key == "enabled":
                defaults[key] = val.lower() not in ("false", "0", "no")

    return defaults


# ── UNQUARANTINABLE parser ─────────────────────────────────────────────────

def _parse_unquarantinable(orchestrator_path: Path = ORCHESTRATOR) -> frozenset[str]:
    """
    Parse UNQUARANTINABLE = { ... } set from __main__.py via regex.
    Robust: handles multi-line set literal, comments, whitespace.
    Falls back to a hard-coded safety baseline if file is unreadable.
    """
    # Hard-coded safety baseline — these are ALWAYS protected even if parsing fails.
    SAFETY_BASELINE = frozenset({
        "phase-exists",
        "commit-attribution",
        "runtime-evidence",
        "build-crossai-required",
        "context-structure",
        "wave-verify-isolated",
        "verify-goal-security",
        "verify-goal-perf",
        "verify-security-baseline",
        "verify-foundation-architecture",
        "verify-security-test-plan",
    })

    if not orchestrator_path.exists():
        return SAFETY_BASELINE

    try:
        text = orchestrator_path.read_text(encoding="utf-8")
    except OSError:
        return SAFETY_BASELINE

    # Match: UNQUARANTINABLE = { ... }  (possibly multi-line, with comments)
    m = re.search(r'UNQUARANTINABLE\s*=\s*\{([^}]*)\}', text, re.DOTALL)
    if not m:
        return SAFETY_BASELINE

    block = m.group(1)
    # Extract quoted strings (single or double quotes)
    names = re.findall(r'["\']([^"\']+)["\']', block)
    if not names:
        return SAFETY_BASELINE

    # Union with safety baseline — parsing can only ADD validators, never remove
    return SAFETY_BASELINE | frozenset(names)


# ── Telemetry reader ───────────────────────────────────────────────────────

def _read_telemetry(path: Path = TELEMETRY_JSONL) -> list[dict]:
    """Read all valid JSONL lines from telemetry file."""
    if not path.exists():
        return []
    events: list[dict] = []
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                events.append(json.loads(raw))
            except json.JSONDecodeError:
                pass
    except OSError:
        pass
    return events


def _read_override_register(path: Path = OVERRIDE_REGISTER) -> list[dict]:
    """Read all valid JSONL lines from override-debt register."""
    if not path.exists():
        return []
    entries: list[dict] = []
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                entries.append(json.loads(raw))
            except json.JSONDecodeError:
                pass
    except OSError:
        pass
    return entries


# ── Duration extraction ────────────────────────────────────────────────────

def _duration_ms(event: dict) -> float | None:
    """Extract duration in ms from a telemetry event (various field locations)."""
    # Direct top-level field
    if "duration_ms" in event:
        try:
            return float(event["duration_ms"])
        except (TypeError, ValueError):
            pass
    # In payload
    payload = event.get("payload") or {}
    if "duration_ms" in payload:
        try:
            return float(payload["duration_ms"])
        except (TypeError, ValueError):
            pass
    # duration_s → convert
    if "duration_s" in payload:
        try:
            return float(payload["duration_s"]) * 1000
        except (TypeError, ValueError):
            pass
    return None


# ── Suggestion generators ──────────────────────────────────────────────────

def _suggest_skip(
    events: list[dict],
    unquarantinable: frozenset[str],
    cfg: dict,
    command_filter: str | None,
) -> list[dict]:
    """
    Type 1 — always-pass skip hint.

    For each validator, look at last N samples. If pass_rate >= threshold
    AND total_samples >= min_samples AND validator NOT in UNQUARANTINABLE
    → emit skip suggestion.
    """
    threshold = cfg["skip_pass_rate_threshold"]
    min_samples = cfg["skip_min_samples"]

    # Collect gate_hit events grouped by (validator/gate_id, command)
    # We use gate_id as the "validator name" identifier.
    # Only consider gate_hit events with an explicit gate_id.
    by_validator: dict[str, list[dict]] = defaultdict(list)
    for ev in events:
        etype = ev.get("event_type") or ev.get("event", "")
        if etype != "gate_hit":
            continue
        gate_id = ev.get("gate_id") or ""
        if not gate_id:
            continue
        if command_filter and ev.get("command") != command_filter:
            continue
        by_validator[gate_id].append(ev)

    suggestions: list[dict] = []
    for validator, evs in by_validator.items():
        # Security hard rule: NEVER suggest skip for UNQUARANTINABLE validators
        if validator in unquarantinable:
            continue

        # Take last N samples (most recent first)
        recent = evs[-min_samples * 2:]  # over-fetch then take last min_samples
        # Sort by ts descending for recency, then take last min_samples
        try:
            recent_sorted = sorted(recent, key=lambda e: e.get("ts", ""), reverse=True)
        except Exception:
            recent_sorted = recent
        sample = recent_sorted[:min_samples * 4]  # cap at a reasonable window
        total = len(evs)
        # Use the full history capped at recent N
        window = evs[-cfg["skip_min_samples"] * 10:]  # last 10x window
        n = len(window)
        if n == 0:
            continue

        passes = sum(
            1 for e in window
            if (e.get("outcome") or "").upper() in ("PASS", "WARN")
        )
        pass_rate = passes / n

        if pass_rate >= threshold and n >= min_samples:
            # Determine the command(s) this validator appears in
            commands = sorted({e.get("command", "unknown") for e in window})
            suggestions.append({
                "type": "skip",
                "validator": validator,
                "pass_rate": round(pass_rate, 4),
                "samples": n,
                "commands": commands,
                "reason": (
                    f"Validator '{validator}' has passed {passes}/{n} recent samples "
                    f"(pass_rate={pass_rate:.1%}). Consider adding a .skip-until-* "
                    f"marker if this area has had no recent code changes."
                ),
                "suggested_action": "add .skip-until-* marker",
            })

    return suggestions


def _suggest_reorder(
    events: list[dict],
    cfg: dict,
    command_filter: str | None,
) -> list[dict]:
    """
    Type 2 — expensive-first reorder.

    For validators in the same command group, compute p95 duration.
    If p95 > threshold_ms → suggest running it LATER (so cheap gates fail fast).
    """
    threshold = cfg["expensive_threshold_ms"]

    # Group durations by (gate_id, command)
    durations_by: dict[tuple[str, str], list[float]] = defaultdict(list)
    for ev in events:
        gate_id = ev.get("gate_id") or ""
        command = ev.get("command") or ""
        if not gate_id or not command:
            continue
        if command_filter and command != command_filter:
            continue
        ms = _duration_ms(ev)
        if ms is not None:
            durations_by[(gate_id, command)].append(ms)

    suggestions: list[dict] = []
    for (gate_id, command), durations in durations_by.items():
        if len(durations) < 2:
            # Need at least 2 samples to compute quantiles
            if len(durations) == 1 and durations[0] > threshold:
                p95 = durations[0]
            else:
                continue
        else:
            try:
                p95 = quantiles(durations, n=20)[18]  # 95th percentile (19th of 20 quantiles = index 18)
            except Exception:
                p95 = max(durations)

        if p95 > threshold:
            suggestions.append({
                "type": "reorder",
                "validator": gate_id,
                "p95_ms": round(p95, 1),
                "command": command,
                "suggested_position": "late",
                "reason": (
                    f"Validator '{gate_id}' in '{command}' has p95 duration "
                    f"{p95:.0f}ms (threshold: {threshold}ms). Running it later "
                    f"in the sequence allows cheap validators to fail fast first."
                ),
            })

    return suggestions


def _suggest_override_abuse(
    override_entries: list[dict],
    cfg: dict,
    command_filter: str | None,
) -> list[dict]:
    """
    Type 3 — override abuse warning.

    Count same --allow-* flag usage in last 30 days.
    If count >= warn_threshold → warn.
    """
    warn_count = cfg["override_warn_count_30d"]
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)

    # Group by flag
    by_flag: dict[str, list[dict]] = defaultdict(list)
    for entry in override_entries:
        ts_str = entry.get("timestamp") or entry.get("ts") or ""
        flag = entry.get("flag") or ""
        if not flag:
            continue
        # Parse timestamp — support both Z and +00:00 suffixes
        try:
            ts_str_norm = ts_str.replace("Z", "+00:00")
            ts = datetime.fromisoformat(ts_str_norm)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        except (ValueError, AttributeError):
            continue
        if ts < cutoff:
            continue
        by_flag[flag].append(entry)

    suggestions: list[dict] = []
    for flag, entries in by_flag.items():
        count = len(entries)
        if count < warn_count:
            continue
        phases = sorted({e.get("phase") or "?" for e in entries})
        suggestions.append({
            "type": "override_abuse",
            "flag": flag,
            "count_30d": count,
            "phases": phases,
            "reason": (
                f"Override flag '{flag}' has been used {count} times in the last 30 days "
                f"(threshold: {warn_count}). High bypass frequency suggests the gate needs "
                f"tuning, or the pattern is legitimate and should be config-exposed."
            ),
        })

    return suggestions


# ── Apply action ───────────────────────────────────────────────────────────

def _apply_skip(
    validator: str,
    unquarantinable: frozenset[str],
    skip_dir: Path = SKIP_DIR,
) -> int:
    """
    Write .vg/telemetry/skip-{validator}.json.
    NEVER applies to UNQUARANTINABLE validators.
    Returns 0 on success, 1 on refusal/error.
    """
    if validator in unquarantinable:
        print(
            f"ERROR: '{validator}' is in UNQUARANTINABLE — skip cannot be applied. "
            f"Security validators must always run.",
            file=sys.stderr,
        )
        return 1

    skip_dir.mkdir(parents=True, exist_ok=True)
    target = skip_dir / f"skip-{validator}.json"
    payload = {
        "validator": validator,
        "applied_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "expires_on_code_change": True,
        "note": "Auto-applied via telemetry-suggest.py --apply skip",
    }
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Written: {target}", file=sys.stderr)
    return 0


# ── Output formatters ──────────────────────────────────────────────────────

def _format_jsonl(suggestions: list[dict]) -> str:
    return "\n".join(json.dumps(s, ensure_ascii=False) for s in suggestions)


def _format_table(suggestions: list[dict]) -> str:
    if not suggestions:
        return "(no suggestions)"
    lines: list[str] = []
    for s in suggestions:
        stype = s["type"]
        if stype == "skip":
            lines.append(
                f"[SKIP]  {s['validator']:<40} pass_rate={s['pass_rate']:.1%}  "
                f"samples={s['samples']}"
            )
        elif stype == "reorder":
            lines.append(
                f"[REORDER] {s['validator']:<38} p95={s['p95_ms']:.0f}ms  "
                f"command={s['command']}  → move LATER"
            )
        elif stype == "override_abuse":
            lines.append(
                f"[OVERRIDE_ABUSE] {s['flag']:<34} count_30d={s['count_30d']}  "
                f"phases={','.join(s['phases'])}"
            )
        else:
            lines.append(json.dumps(s, ensure_ascii=False))
        lines.append(f"  Reason: {s.get('reason', '')}")
        lines.append("")
    return "\n".join(lines).rstrip()


# ── Main ───────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="VG Telemetry Suggestions — Phase E v2.5",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--format",
        choices=["jsonl", "table"],
        default="jsonl",
        help="Output format (default: jsonl)",
    )
    parser.add_argument(
        "--command",
        metavar="CMD",
        default=None,
        help="Filter suggestions to a specific command (e.g. vg:build)",
    )
    parser.add_argument(
        "--apply",
        nargs=2,
        metavar=("ACTION", "VALIDATOR"),
        help="Apply a specific suggestion, e.g. --apply skip plan-granularity",
    )
    # Allow custom paths for testing
    parser.add_argument("--telemetry-path", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--override-path", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--orchestrator-path", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--config-path", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--skip-dir", default=None, help=argparse.SUPPRESS)

    args = parser.parse_args()

    # Resolve paths (allow test overrides)
    telemetry_path = Path(args.telemetry_path) if args.telemetry_path else TELEMETRY_JSONL
    override_path = Path(args.override_path) if args.override_path else OVERRIDE_REGISTER
    orchestrator_path = Path(args.orchestrator_path) if args.orchestrator_path else ORCHESTRATOR
    config_path = Path(args.config_path) if args.config_path else VG_CONFIG
    skip_dir = Path(args.skip_dir) if args.skip_dir else SKIP_DIR

    # Load config
    cfg = _load_config(config_path)

    # Check if telemetry suggestions are enabled
    if not cfg.get("enabled", True):
        return 0

    # Parse UNQUARANTINABLE set
    unquarantinable = _parse_unquarantinable(orchestrator_path)

    # Handle --apply
    if args.apply:
        action, validator = args.apply
        if action == "skip":
            return _apply_skip(validator, unquarantinable, skip_dir)
        else:
            print(f"ERROR: unknown action '{action}'. Only 'skip' is supported.", file=sys.stderr)
            return 1

    # Read telemetry data
    events = _read_telemetry(telemetry_path)
    override_entries = _read_override_register(override_path)

    # Generate suggestions
    suggestions: list[dict] = []
    suggestions.extend(_suggest_skip(events, unquarantinable, cfg, args.command))
    suggestions.extend(_suggest_reorder(events, cfg, args.command))
    suggestions.extend(_suggest_override_abuse(override_entries, cfg, args.command))

    # Output
    if not suggestions:
        return 0

    output = _format_table(suggestions) if args.format == "table" else _format_jsonl(suggestions)
    if output:
        print(output)

    return 0


if __name__ == "__main__":
    sys.exit(main())
