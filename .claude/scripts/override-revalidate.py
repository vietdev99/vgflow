#!/usr/bin/env python3
"""
VG Bootstrap — Override Re-validation (Phase C, v1.15.0)

Fix for Scenario 1 (playwright laziness):
  When phase Y overrides a gate with scope={no-UI}, phase Z with UI should
  NOT inherit that override. This helper re-evaluates every active override
  against current phase metadata and marks those whose scope no longer
  matches as EXPIRED.

Called from config-loader at start of every /vg:* command.

Schema extension for OVERRIDE-DEBT.md entries:
    scope:                 # NEW — conservative condition for when override applies
      required_all: [...]
    revalidate_on:         # NEW — triggers to force re-eval
      - new_phase_starts
      - phase.surfaces_change

Conservative (fail-closed) policy:
    For overrides, opposite polarity to rules:
    - Unknown var / missing scope → expire override (gate goes ACTIVE, safe)
    - Match scope → carry override forward (gate stays SKIPPED)

This prevents laziness where override without scope silently propagates.

Usage (from config-loader):
    python override-revalidate.py --planning .vg --phase 07.8 \\
        --surfaces web --touched-paths 'apps/web/**' --has-mutation true \\
        --emit report

Output JSON:
    {
      "phase": "07.8",
      "active_before": 5,
      "carried_forward": [{id, reason, scope}, ...],
      "expired": [{id, reason_for_expire, original_scope}, ...],
      "legacy_no_scope": [{id, reason}]  # pre-scope overrides, treat conservatively
    }

CLI exits 0 always (never blocks caller). Output to stdout for orchestrator.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
try:
    from scope_evaluator import evaluate_scope, ScopeEvalError
except ImportError:
    import importlib.util

    _spec = importlib.util.spec_from_file_location(
        "scope_evaluator", Path(__file__).parent / "scope-evaluator.py"
    )
    _mod = importlib.util.module_from_spec(_spec)  # type: ignore
    _spec.loader.exec_module(_mod)  # type: ignore
    evaluate_scope = _mod.evaluate_scope
    ScopeEvalError = _mod.ScopeEvalError


def _build_context(args: argparse.Namespace) -> dict:
    surfaces = [s.strip() for s in (args.surfaces or "").split(",") if s.strip()]
    touched = [p.strip() for p in (args.touched_paths or "").split(",") if p.strip()]
    return {
        "phase": {
            "number": args.phase or "",
            "surfaces": surfaces,
            "touched_paths": touched,
            "has_mutation": (args.has_mutation or "false").lower() == "true",
            "ui_audit_required": (args.ui_audit_required or "false").lower() == "true",
            "is_api_only": "api" in surfaces and "web" not in surfaces,
        },
        "step": args.step or "",
    }


# OVERRIDE-DEBT.md entries are serialized as inline YAML+markdown. Parse loosely.
# Each entry typically starts with `| DEBT-YYYYMMDD... |` table row OR a YAML block.
_ENTRY_RE = re.compile(
    r"^\|\s*(DEBT-\S+)\s*\|\s*(critical|high|medium|low)\s*\|\s*(\S+)\s*\|\s*(\S+)\s*\|\s*(\S+)\s*\|(.*?)\|\s*(\S+)\s*\|\s*(OPEN|RESOLVED|WONT_FIX)\s*\|",
    re.MULTILINE,
)

# YAML block form (v1.8.0+): entries wrapped in yaml fences
_YAML_BLOCK_RE = re.compile(r"```yaml\s*\n(.*?)\n```", re.DOTALL)

# Flat list-item form (log_override_debt.sh output): "- id: OD-XXX\n  key: val\n..."
# Matches entries in .vg/OVERRIDE-DEBT.md produced by _shared/lib/override-debt.sh.
_FLAT_ENTRY_RE = re.compile(
    r"^- id:\s*(\S+)\s*\n((?:  \S.*\n?)+)",
    re.MULTILINE,
)


def load_overrides(planning_dir: Path) -> list[dict]:
    """Load override entries from OVERRIDE-DEBT.md. Returns list of dicts."""
    register = planning_dir / "OVERRIDE-DEBT.md"
    if not register.exists():
        return []

    text = register.read_text(encoding="utf-8", errors="replace")
    entries = []
    seen_ids: set[str] = set()

    # Try YAML block form first (v1.8.0+)
    for m in _YAML_BLOCK_RE.finditer(text):
        block = m.group(1)
        entry = _parse_yaml_entry(block)
        if entry and entry.get("id") and entry["id"] not in seen_ids:
            entries.append(entry)
            seen_ids.add(entry["id"])

    # Flat list-item form (log_override_debt.sh produces this)
    # Reconstruct a YAML block by prepending "id: X\n" + dedenting the indented body.
    for m in _FLAT_ENTRY_RE.finditer(text):
        # Skip the schema example (id == "OD-XXX" is the template placeholder)
        od_id = m.group(1).strip()
        if od_id in seen_ids or od_id.upper() == "OD-XXX":
            continue
        body = m.group(2)
        dedented = "\n".join(
            line[2:] if line.startswith("  ") else line
            for line in body.splitlines()
        )
        synth = f"id: {od_id}\n{dedented}\n"
        entry = _parse_yaml_entry(synth)
        if entry and entry.get("id"):
            # Normalize status terminology — flat form uses `active/resolved/expired`
            # while YAML block form uses `OPEN/RESOLVED/WONT_FIX`. Map to canonical OPEN
            # so downstream revalidate() filter catches them.
            raw_status = str(entry.get("status", "active")).lower()
            entry["status"] = "OPEN" if raw_status == "active" else raw_status.upper()
            entries.append(entry)
            seen_ids.add(entry["id"])

    # Then table rows (legacy)
    for m in _ENTRY_RE.finditer(text):
        entries.append(
            {
                "id": m.group(1),
                "severity": m.group(2),
                "phase": m.group(3),
                "step": m.group(4),
                "flag": m.group(5),
                "reason": m.group(6).strip(),
                "gate_id": m.group(7),
                "status": m.group(8),
                "scope": None,  # table rows predate scope — treat as legacy
                "revalidate_on": None,
                "legacy": True,
            }
        )

    return entries


def _parse_yaml_entry(block: str) -> dict | None:
    """Tolerant YAML block parse — handles nested scope."""
    entry: dict = {}
    cur_key = None
    cur_list = None
    for line in block.splitlines():
        stripped = line.rstrip()
        if not stripped or stripped.lstrip().startswith("#"):
            continue
        # list item under scope.required_all etc.
        if cur_list is not None and stripped.lstrip().startswith("- "):
            item = stripped.lstrip()[2:].strip()
            # Strip matched outer quotes only (don't chew both kinds)
            if len(item) >= 2:
                if item[0] == item[-1] and item[0] in ("'", '"'):
                    item = item[1:-1]
            cur_list.append(item)
            continue
        if ":" in stripped:
            parts = stripped.split(":", 1)
            k = parts[0].strip()
            v = parts[1].strip()
            indent = len(line) - len(line.lstrip())
            if indent == 0:
                cur_list = None
                if v:
                    entry[k] = _scalar(v)
                    cur_key = None
                else:
                    entry[k] = {}
                    cur_key = k
            elif cur_key and indent > 0:
                if not isinstance(entry.get(cur_key), dict):
                    entry[cur_key] = {}
                if v == "":
                    # nested list coming
                    entry[cur_key][k] = []
                    cur_list = entry[cur_key][k]
                elif v.startswith("["):
                    # inline list
                    entry[cur_key][k] = [
                        s.strip().strip("'\"")
                        for s in v.strip("[]").split(",")
                        if s.strip()
                    ]
                else:
                    entry[cur_key][k] = _scalar(v)
    return entry if "id" in entry else None


def _scalar(s: str):
    s = s.strip().strip("'\"")
    if s.lower() in ("true", "yes"):
        return True
    if s.lower() in ("false", "no"):
        return False
    if s.lower() in ("null", "none", "~"):
        return None
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s


def revalidate(entries: list[dict], context: dict) -> dict:
    """Re-evaluate scope for each active entry against current phase context.

    Returns report dict. Does NOT mutate OVERRIDE-DEBT.md (caller decides
    whether to persist status changes).
    """
    carried_forward = []
    expired = []
    legacy_no_scope = []

    active = [e for e in entries if e.get("status", "OPEN") == "OPEN"]

    for e in active:
        eid = e.get("id")
        scope = e.get("scope")

        if scope is None:
            # Legacy / no scope declared — conservative: treat as carried forward
            # but flag for triage so user can add scope retroactively.
            legacy_no_scope.append(
                {
                    "id": eid,
                    "reason": "no scope declared (legacy pre-v1.15.0 entry) — add scope or treat as global",
                    "flag": e.get("flag"),
                    "gate_id": e.get("gate_id"),
                }
            )
            carried_forward.append({"id": eid, "reason": "legacy — no scope to evaluate"})
            continue

        try:
            if evaluate_scope(scope, context):
                carried_forward.append(
                    {"id": eid, "reason": "scope matches current phase", "scope": scope}
                )
            else:
                # Conservative expire (fail-closed for overrides)
                expired.append(
                    {
                        "id": eid,
                        "reason_for_expire": "scope condition no longer met in current phase",
                        "original_scope": scope,
                        "flag": e.get("flag"),
                        "gate_id": e.get("gate_id"),
                    }
                )
        except ScopeEvalError as err:
            expired.append(
                {
                    "id": eid,
                    "reason_for_expire": f"scope eval error (fail-closed): {err}",
                    "original_scope": scope,
                    "flag": e.get("flag"),
                    "gate_id": e.get("gate_id"),
                }
            )

    return {
        "phase": context.get("phase", {}).get("number"),
        "active_before": len(active),
        "carried_forward": carried_forward,
        "expired": expired,
        "legacy_no_scope": legacy_no_scope,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Revalidate VG override-debt entries")
    ap.add_argument("--planning", default=".vg", help="planning dir containing OVERRIDE-DEBT.md")
    ap.add_argument("--phase", default="")
    ap.add_argument("--step", default="")
    ap.add_argument("--surfaces", default="", help="comma-separated")
    ap.add_argument("--touched-paths", default="")
    ap.add_argument("--has-mutation", default="false")
    ap.add_argument("--ui-audit-required", default="false")
    ap.add_argument("--emit", choices=["report", "summary"], default="report")
    args = ap.parse_args()

    entries = load_overrides(Path(args.planning))
    context = _build_context(args)
    report = revalidate(entries, context)

    if args.emit == "summary":
        # Short human-readable
        print(
            f"Override revalidation phase={report['phase']}: "
            f"active={report['active_before']} carried={len(report['carried_forward'])} "
            f"expired={len(report['expired'])} legacy={len(report['legacy_no_scope'])}"
        )
        if report["expired"]:
            print("\n⚠ EXPIRED overrides (gates reactivate for this phase):")
            for e in report["expired"]:
                print(f"  - {e['id']} ({e.get('flag', '?')}) — {e['reason_for_expire']}")
    else:
        print(json.dumps(report, indent=2, ensure_ascii=False))

    return 0


if __name__ == "__main__":
    sys.exit(main())
