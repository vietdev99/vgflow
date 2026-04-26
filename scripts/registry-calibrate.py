#!/usr/bin/env python3
"""
VG Harness v2.6 — Phase F (2026-04-26): registry-calibrate.py

Per-validator severity calibration suggester. Reads telemetry
(.vg/events.jsonl + .vg/validator-quarantine.json) and the dispatch
manifest (.claude/scripts/validators/dispatch-manifest.json), then
proposes severity transitions for operator review.

Heuristics (all require min_fires ≥ 10):

  * BLOCK → WARN downgrade
      severity = BLOCK  AND  override_rate > 0.60  AND  NOT UNQUARANTINABLE
      rationale: hard gate that operators routinely bypass adds friction
      without trust. Demote to WARN, keep telemetry.

  * WARN → BLOCK upgrade
      severity = WARN  AND  block_correlation > 0.80
      rationale: when this WARN fires, a downstream BLOCK fires within
      the same phase >80% of the time. Promote to first-class gate.
      UNQUARANTINABLE flag does NOT block upgrades — security validators
      currently WARN can still be tightened.

  * Domain-cluster outlier
      A validator whose name shares a prefix (e.g. "verify-") AND a domain
      keyword (security/auth/contract/perf) with a peer cluster of ≥4
      neighbors that all share severity X, while the candidate sits at
      severity Y, is flagged. Advisory only — operator decides.

UNQUARANTINABLE protection (R8):
  Single source of truth lives in vg-orchestrator/__main__.py. We import
  the constant rather than mirror it, so any future allowlist change
  flows through automatically. Downgrade suggestions are SUPPRESSED for
  any UNQUARANTINABLE validator regardless of override rate.

Output:
  .vg/CALIBRATION-SUGGESTIONS.md — PR-style human-readable diff with
  one section per suggestion. Each carries a stable suggestion id
  (S-001, S-002, ...) computed deterministically from (validator,
  proposed_severity) so re-running `status` doesn't churn ids.

CLI:
  status                          (default — recompute + write)
  apply --suggestion-id S-NNN --reason '<≥50 chars>'
  apply-all --reason '<≥50 chars>'
  apply-decay [--dry-run] --reason '<≥50 chars>'    (Phase Q, v2.7)

Apply path:
  - Hard-gates `verify_human_operator()` (TTY OR HMAC-signed token).
  - Mutates dispatch-manifest.json: validators[<v>].severity = new value.
  - Emits `calibration.applied` (v2.6 Phase F) /
    `calibration.suggestion_decayed` (v2.7 Phase Q) audit events so
    dashboard panels can surface history.

Decay (v2.7 Phase Q):
  - Sidecar state file `.vg/calibration-suggestions-state.json` records
    {suggestion_id: {first_seen_phase, first_seen_ts}} on each `status`
    run.
  - `apply-decay` finds suggestions older than
    `calibration.decay_after_phases` (default 5) AND no longer crossing
    threshold (no confirming evidence in current recompute) → marks
    them RETIRED in CALIBRATION-SUGGESTIONS.md (forensic trail) +
    emits `calibration.suggestion_decayed` audit event.

Stdlib only: json, subprocess, pathlib, argparse, datetime, hashlib,
collections, os, sys.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ────────────────────────── repo-root resolution ──────────────────────────

def _repo_root() -> Path:
    env = os.environ.get("VG_REPO_ROOT")
    if env:
        return Path(env).resolve()
    return Path(__file__).resolve().parents[2]


REPO_ROOT = _repo_root()
EVENTS_JSONL = REPO_ROOT / ".vg" / "events.jsonl"
QUARANTINE_FILE = REPO_ROOT / ".vg" / "validator-quarantine.json"
MANIFEST_FILE = (
    REPO_ROOT / ".claude" / "scripts" / "validators" / "dispatch-manifest.json"
)
SUGGESTIONS_FILE = REPO_ROOT / ".vg" / "CALIBRATION-SUGGESTIONS.md"
SUGGESTIONS_STATE_FILE = (
    REPO_ROOT / ".vg" / "calibration-suggestions-state.json"
)

# Thresholds (kept in code, easy to tune later)
MIN_FIRES = 10
DOWNGRADE_OVERRIDE_RATE = 0.60
UPGRADE_CORRELATION_RATE = 0.80
DOMAIN_CLUSTER_MIN_PEERS = 4
DECAY_LOOKBACK_PHASES_DEFAULT = 5


# ─────────────────────── UNQUARANTINABLE import ───────────────────────────
#
# R8 / R10: single-source-of-truth import from the orchestrator. If the
# import fails (test sandbox without the orchestrator on path), we fall
# back to an empty set — calibrator still runs, just without exemption
# protection. Tests inject their own UNQUARANTINABLE list when needed.

def _load_unquarantinable() -> set[str]:
    orch = REPO_ROOT / ".claude" / "scripts" / "vg-orchestrator"
    if str(orch) not in sys.path:
        sys.path.insert(0, str(orch))
    try:
        # Load __main__.py as a module without executing main()
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "_vg_orch_main", str(orch / "__main__.py")
        )
        if spec is None or spec.loader is None:
            return set()
        mod = importlib.util.module_from_spec(spec)
        # Guard against the file's `if __name__ == "__main__"` block
        mod.__name__ = "_vg_orch_main"
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        u = getattr(mod, "UNQUARANTINABLE", None)
        if isinstance(u, (set, frozenset, list, tuple)):
            return set(u)
        return set()
    except Exception:
        return set()


# ────────────────────────── data loading ──────────────────────────────────

def _load_events(path: Path, max_events: int = 500_000) -> list[dict]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    out: list[dict] = []
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
            if len(out) >= max_events:
                break
    return out


def _load_quarantine() -> dict[str, dict]:
    if not QUARANTINE_FILE.exists():
        return {}
    try:
        return json.loads(QUARANTINE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_manifest() -> dict[str, Any]:
    if not MANIFEST_FILE.exists():
        return {"version": "1.0", "validators": {}}
    try:
        return json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"version": "1.0", "validators": {}}


def _save_manifest(manifest: dict[str, Any]) -> None:
    MANIFEST_FILE.parent.mkdir(parents=True, exist_ok=True)
    # ensure_ascii=True to match the existing manifest's encoding
    # convention — em-dash etc. stay as \u escapes so git diffs only
    # show the actual severity change.
    MANIFEST_FILE.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=True),
        encoding="utf-8",
    )


# ───────────────────────── event payload helpers ──────────────────────────

def _extract_payload(event: dict) -> dict:
    pl = event.get("payload")
    if isinstance(pl, dict):
        return pl
    pj = event.get("payload_json")
    if isinstance(pj, str) and pj:
        try:
            d = json.loads(pj)
            if isinstance(d, dict):
                return d
        except json.JSONDecodeError:
            pass
    return {}


def _validator_of(event: dict) -> str | None:
    pl = _extract_payload(event)
    v = pl.get("validator")
    if isinstance(v, str) and v:
        return v
    # override.used uses {"flag": <validator-name>} when paired
    if event.get("event_type") == "override.used":
        f = pl.get("flag", "")
        if isinstance(f, str):
            f = f.lstrip("-")
            if f.startswith("skip-"):
                return f[5:]
            return f or None
    return None


# ───────────────────────── per-validator stats ────────────────────────────

def aggregate_validator_stats(events: list[dict]) -> dict[str, dict]:
    """Produce {validator: {fires, blocks, passes, warns, overrides,
    block_phases, override_phases, shadow_correct, shadow_total}}."""
    stats: dict[str, dict] = defaultdict(
        lambda: {
            "fires": 0,
            "blocks": 0,
            "passes": 0,
            "warns": 0,
            "overrides": 0,
            "block_phases": set(),
            "override_phases": set(),
            "shadow_correct": 0,
            "shadow_total": 0,
        }
    )

    # First pass — validation events + override events
    for e in events:
        et = e.get("event_type", "")
        v = _validator_of(e)
        phase = str(e.get("phase", "")).strip()
        if et in ("validation.passed", "validation.warned",
                  "validation.failed"):
            if not v:
                continue
            s = stats[v]
            s["fires"] += 1
            outcome = e.get("outcome", "")
            if outcome == "BLOCK":
                s["blocks"] += 1
                if phase:
                    s["block_phases"].add(phase)
            elif outcome == "WARN":
                s["warns"] += 1
            elif outcome == "PASS":
                s["passes"] += 1
        elif et == "override.used":
            if not v:
                continue
            s = stats[v]
            s["overrides"] += 1
            if phase:
                s["override_phases"].add(phase)
        elif et == "bootstrap.shadow_prediction":
            # Phase A telemetry — payload {validator, predicted, actual, ...}
            if not v:
                continue
            pl = _extract_payload(e)
            s = stats[v]
            s["shadow_total"] += 1
            if pl.get("predicted") == pl.get("actual"):
                s["shadow_correct"] += 1

    return dict(stats)


def block_correlation_per_validator(
    events: list[dict],
) -> dict[str, dict[str, int]]:
    """For each validator that fires WARN in a phase, count whether ANY
    BLOCK validation event also fires in the same phase. Returns
    {validator: {warn_phases: int, warn_phases_with_block: int}}.

    Same-phase BLOCK by ANOTHER validator counts as correlation —
    semantics: "this WARN is a leading indicator that the build is
    about to BLOCK on something nearby." That's the upgrade signal.
    """
    # Build phase → set of (validator, outcome)
    phase_outcomes: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for e in events:
        et = e.get("event_type", "")
        if et not in ("validation.passed", "validation.warned",
                      "validation.failed"):
            continue
        v = _validator_of(e)
        phase = str(e.get("phase", "")).strip()
        if not v or not phase:
            continue
        phase_outcomes[phase].append((v, e.get("outcome", "")))

    # Per-validator: phases where this validator hit WARN
    warn_phase_map: dict[str, set[str]] = defaultdict(set)
    block_phase_set: set[str] = set()
    for phase, lst in phase_outcomes.items():
        had_block = any(o == "BLOCK" for _, o in lst)
        if had_block:
            block_phase_set.add(phase)
        for v, o in lst:
            if o == "WARN":
                warn_phase_map[v].add(phase)

    out: dict[str, dict[str, int]] = {}
    for v, warn_phases in warn_phase_map.items():
        out[v] = {
            "warn_phases": len(warn_phases),
            "warn_phases_with_block": len(warn_phases & block_phase_set),
        }
    return out


# ─────────────────────────── domain clustering ────────────────────────────

DOMAIN_KEYWORDS = (
    "security", "auth", "csrf", "cookie", "jwt", "secret",
    "contract", "rollback", "perf", "container",
    "rate-limit", "input-validation", "permission",
)


def _domain_of(name: str) -> str | None:
    n = name.lower()
    for kw in DOMAIN_KEYWORDS:
        if kw in n:
            return kw
    return None


def domain_cluster_outliers(
    manifest: dict[str, Any],
) -> list[tuple[str, str, str, str]]:
    """Return list of (validator, current_severity, peer_severity, domain).

    A validator is an outlier when ≥4 peers in its domain share severity
    X and the candidate sits at severity Y. WARN→BLOCK alignment only
    (don't suggest downgrades from cluster — too aggressive).
    """
    domain_to_validators: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for vname, meta in manifest.get("validators", {}).items():
        dom = _domain_of(vname)
        if not dom:
            continue
        sev = str(meta.get("severity", "")).upper()
        domain_to_validators[dom].append((vname, sev))

    outliers: list[tuple[str, str, str, str]] = []
    for dom, lst in domain_to_validators.items():
        if len(lst) < DOMAIN_CLUSTER_MIN_PEERS + 1:
            continue
        sev_counts = Counter(sev for _, sev in lst)
        if not sev_counts:
            continue
        majority_sev, majority_count = sev_counts.most_common(1)[0]
        if majority_count < DOMAIN_CLUSTER_MIN_PEERS:
            continue
        # Only flag the WARN→BLOCK direction (alignment toward stricter)
        if majority_sev != "BLOCK":
            continue
        for vname, sev in lst:
            if sev != majority_sev and sev == "WARN":
                outliers.append((vname, sev, majority_sev, dom))
    return outliers


# ───────────────────────── suggestion generation ──────────────────────────

def _suggestion_id(validator: str, new_severity: str) -> str:
    h = hashlib.sha1(
        f"{validator}|{new_severity}".encode("utf-8")
    ).hexdigest()[:6]
    # Stable short id — full-3-digit numeric form when possible
    n = int(h, 16) % 1000
    return f"S-{n:03d}"


def compute_suggestions(
    events: list[dict] | None = None,
    manifest: dict[str, Any] | None = None,
    quarantine: dict[str, dict] | None = None,
    unquarantinable: set[str] | None = None,
) -> list[dict]:
    """Pure function — testable. All inputs injectable."""
    if events is None:
        events = _load_events(EVENTS_JSONL)
    if manifest is None:
        manifest = _load_manifest()
    if quarantine is None:
        quarantine = _load_quarantine()
    if unquarantinable is None:
        unquarantinable = _load_unquarantinable()

    stats = aggregate_validator_stats(events)
    correlation = block_correlation_per_validator(events)
    suggestions: list[dict] = []
    seen_ids: set[str] = set()

    validators = manifest.get("validators", {})

    # 1) BLOCK → WARN downgrade pass (UNQUARANTINABLE-protected)
    for vname, meta in sorted(validators.items()):
        cur = str(meta.get("severity", "")).upper()
        if cur != "BLOCK":
            continue
        if vname in unquarantinable:
            continue
        s = stats.get(vname)
        if not s:
            continue
        fires = s["fires"]
        if fires < MIN_FIRES:
            continue
        # Override rate denominator = fires (firing count, not just BLOCKs).
        # If validator BLOCKED 30 times and overrides used 20 of those 30,
        # rate = 20/30 = 0.67 → suggest downgrade.
        denom = max(s["blocks"], 1)
        rate = s["overrides"] / denom
        if rate <= DOWNGRADE_OVERRIDE_RATE:
            continue
        sid = _suggestion_id(vname, "WARN")
        if sid in seen_ids:
            continue
        seen_ids.add(sid)
        suggestions.append({
            "id": sid,
            "validator": vname,
            "kind": "downgrade",
            "current_severity": "BLOCK",
            "proposed_severity": "WARN",
            "unquarantinable": False,
            "evidence": {
                "fires": fires,
                "blocks": s["blocks"],
                "overrides": s["overrides"],
                "override_rate": round(rate, 3),
                "threshold": DOWNGRADE_OVERRIDE_RATE,
            },
            "reason": (
                f"override_rate={rate:.2%} exceeds "
                f"{DOWNGRADE_OVERRIDE_RATE:.0%} threshold over "
                f"{fires} fires ({s['overrides']} overrides / "
                f"{s['blocks']} blocks). Operators routinely bypass "
                f"this BLOCK — demote to WARN to reduce friction "
                f"without losing telemetry."
            ),
        })

    # 2) WARN → BLOCK upgrade pass (UNQUARANTINABLE allowed)
    for vname, meta in sorted(validators.items()):
        cur = str(meta.get("severity", "")).upper()
        if cur != "WARN":
            continue
        s = stats.get(vname)
        if not s:
            continue
        fires = s["fires"]
        if fires < MIN_FIRES:
            continue
        corr = correlation.get(vname, {})
        warn_phases = corr.get("warn_phases", 0)
        if warn_phases < 1:
            continue
        ratio = corr.get("warn_phases_with_block", 0) / warn_phases
        if ratio <= UPGRADE_CORRELATION_RATE:
            continue
        sid = _suggestion_id(vname, "BLOCK")
        if sid in seen_ids:
            continue
        seen_ids.add(sid)
        suggestions.append({
            "id": sid,
            "validator": vname,
            "kind": "upgrade",
            "current_severity": "WARN",
            "proposed_severity": "BLOCK",
            "unquarantinable": vname in unquarantinable,
            "evidence": {
                "fires": fires,
                "warn_phases": warn_phases,
                "warn_phases_with_block": corr.get(
                    "warn_phases_with_block", 0
                ),
                "block_correlation": round(ratio, 3),
                "threshold": UPGRADE_CORRELATION_RATE,
            },
            "reason": (
                f"block_correlation={ratio:.2%} — when this WARN "
                f"fires, a BLOCK fires in the same phase "
                f"{ratio:.0%} of the time "
                f"({corr.get('warn_phases_with_block', 0)}/"
                f"{warn_phases} phases). Promote to first-class "
                f"BLOCK to gate earlier."
            ),
        })

    # 3) Domain-cluster outliers (advisory, no auto-apply)
    for vname, cur_sev, peer_sev, dom in domain_cluster_outliers(manifest):
        sid = _suggestion_id(vname, peer_sev)
        if sid in seen_ids:
            continue
        seen_ids.add(sid)
        suggestions.append({
            "id": sid,
            "validator": vname,
            "kind": "domain-cluster",
            "current_severity": cur_sev,
            "proposed_severity": peer_sev,
            "unquarantinable": vname in unquarantinable,
            "evidence": {
                "domain": dom,
                "peer_majority": peer_sev,
                "min_peers": DOMAIN_CLUSTER_MIN_PEERS,
            },
            "reason": (
                f"domain '{dom}': ≥{DOMAIN_CLUSTER_MIN_PEERS} peers "
                f"share severity {peer_sev}, this validator sits at "
                f"{cur_sev}. Consider aligning for consistency."
            ),
        })

    return suggestions


# ─────────────────────────── markdown rendering ───────────────────────────

_HEADER = """\
# CALIBRATION-SUGGESTIONS

> Auto-generated by `.claude/scripts/registry-calibrate.py status`.
> Operator reviews each suggestion, then applies via the CLI documented
> below. Do NOT hand-edit this file — re-run the script to refresh.

## Schema

Each section corresponds to one suggestion with a stable id `S-NNN`
derived from `(validator, proposed_severity)`. Fields:

- **validator** — name as registered in `dispatch-manifest.json`
- **kind** — `downgrade` (BLOCK→WARN), `upgrade` (WARN→BLOCK),
  `domain-cluster` (advisory alignment to peer cluster)
- **current_severity / proposed_severity** — canonical `BLOCK | WARN`
- **unquarantinable** — `true` ⇒ allowlisted in
  `vg-orchestrator/__main__.py UNQUARANTINABLE`. Downgrade suggestions
  are NEVER emitted for these (calibrator skips them); upgrade
  suggestions still surface and are operator-applicable.
- **evidence** — numeric counters that triggered the rule (fires,
  override_rate, block_correlation, ...)
- **reason** — one-line summary used in the audit event payload

## Apply CLI

```bash
# Status (default — recompute + rewrite this file)
python3 .claude/scripts/registry-calibrate.py status

# Apply one suggestion (TTY OR HMAC token + reason ≥50 chars required)
python3 .claude/scripts/registry-calibrate.py apply \\
  --suggestion-id S-001 \\
  --reason 'long-form audit text explaining why this is correct'

# Apply every current suggestion (same gates)
python3 .claude/scripts/registry-calibrate.py apply-all \\
  --reason 'bulk approval after operator review of 2026-04-26 dashboard'

# Or via the orchestrator subcommand wrapper
python3 .claude/scripts/vg-orchestrator calibrate status
python3 .claude/scripts/vg-orchestrator calibrate apply \\
  --suggestion-id S-001 --reason '<≥50 chars>'
```

## Decay policy

Suggestions older than **{lookback} phases** auto-expire on the next
`status` run if the underlying telemetry no longer crosses threshold.
Expiry is silent — there is no record of expired ids. Re-emerge happens
only when telemetry crosses threshold again.

## UNQUARANTINABLE protection

Validators in the `UNQUARANTINABLE` allowlist (currently {n_unq}
entries) are policy-locked: no calibration can downgrade them. This
prevents silent erosion of security/correctness gates by override
pressure. If a security validator legitimately needs to become
advisory, the change requires an explicit allowlist edit in
`vg-orchestrator/__main__.py` reviewed at PR.

---
"""


def render_markdown(
    suggestions: list[dict],
    *,
    n_unquarantinable: int,
    lookback: int = DECAY_LOOKBACK_PHASES_DEFAULT,
) -> str:
    out = _HEADER.format(lookback=lookback, n_unq=n_unquarantinable)
    out += (
        f"_Generated at {datetime.now(timezone.utc).isoformat()}._\n"
        f"_Total suggestions: **{len(suggestions)}**._\n\n"
    )
    if not suggestions:
        out += (
            "## No suggestions\n\n"
            "No validator currently crosses calibration thresholds. "
            "This is the expected steady state — re-run after the next "
            "phase run to refresh.\n"
        )
        return out

    for s in suggestions:
        unq_tag = " `[UNQUARANTINABLE]`" if s.get("unquarantinable") else ""
        out += f"## {s['id']} — `{s['validator']}` ({s['kind']}){unq_tag}\n\n"
        out += (
            f"- **Current severity:** `{s['current_severity']}`\n"
            f"- **Proposed severity:** `{s['proposed_severity']}`\n"
            f"- **Reason:** {s['reason']}\n"
        )
        out += "- **Evidence:**\n"
        for k, v in s.get("evidence", {}).items():
            out += f"    - `{k}`: `{v}`\n"
        out += "\n"
        out += (
            f"```bash\npython3 .claude/scripts/registry-calibrate.py "
            f"apply --suggestion-id {s['id']} \\\n"
            f"  --reason '<≥50 chars audit text>'\n```\n\n"
        )
        out += "---\n\n"
    return out


# ─────────────────────────────── apply path ───────────────────────────────

def _verify_human() -> tuple[bool, str | None, str | None]:
    """Return (is_human, approver_or_None, error_msg_or_None)."""
    try:
        # allow_flag_gate lives next to vg-orchestrator
        orch = REPO_ROOT / ".claude" / "scripts" / "vg-orchestrator"
        if str(orch) not in sys.path:
            sys.path.insert(0, str(orch))
        from allow_flag_gate import verify_human_operator  # type: ignore
        is_human, approver = verify_human_operator("calibrate-apply")
        return is_human, approver, None
    except Exception as e:
        return False, None, f"verify_human_operator unavailable: {e}"


def _emit_audit_event(
    *,
    suggestion: dict,
    reason: str,
    approver: str,
) -> None:
    try:
        sys.path.insert(
            0, str(REPO_ROOT / ".claude" / "scripts" / "vg-orchestrator")
        )
        import db as _db  # type: ignore
        _db.append_event(
            run_id="calibrate-apply",
            event_type="calibrate.applied",
            phase="",
            command="registry-calibrate",
            actor="user",
            outcome="INFO",
            payload={
                "suggestion_id": suggestion["id"],
                "validator": suggestion["validator"],
                "old_severity": suggestion["current_severity"],
                "new_severity": suggestion["proposed_severity"],
                "kind": suggestion["kind"],
                "reason": reason[:500],
                "operator_token": approver[:120] if approver else "",
                "unquarantinable": bool(suggestion.get("unquarantinable")),
            },
        )
    except Exception:
        # Audit must never break apply — best-effort.
        pass


def _apply_suggestion(
    suggestion: dict,
    reason: str,
    approver: str,
) -> tuple[bool, str]:
    """Returns (ok, message)."""
    manifest = _load_manifest()
    validators = manifest.setdefault("validators", {})
    vmeta = validators.get(suggestion["validator"])
    if not vmeta:
        return False, (
            f"validator '{suggestion['validator']}' not found in "
            "dispatch-manifest.json"
        )
    cur = str(vmeta.get("severity", "")).upper()
    if cur != suggestion["current_severity"]:
        return False, (
            f"manifest severity drift: expected "
            f"{suggestion['current_severity']}, found {cur}. Re-run "
            f"`registry-calibrate.py status` to refresh suggestions."
        )
    vmeta["severity"] = suggestion["proposed_severity"]
    vmeta["calibrated_at"] = datetime.now(timezone.utc).isoformat()
    vmeta["calibrated_from"] = suggestion["current_severity"]
    vmeta["calibrated_reason"] = reason[:500]
    _save_manifest(manifest)
    _emit_audit_event(
        suggestion=suggestion, reason=reason, approver=approver,
    )
    return True, (
        f"applied {suggestion['id']}: {suggestion['validator']} "
        f"{suggestion['current_severity']} → "
        f"{suggestion['proposed_severity']}"
    )


# ─────────────────────────────── CLI ──────────────────────────────────────

def cmd_status(args: argparse.Namespace) -> int:
    suggestions = compute_suggestions()
    unq = _load_unquarantinable()
    # Phase Q: record first-seen state for decay tracking.
    _update_suggestions_state(suggestions)
    md = render_markdown(
        suggestions,
        n_unquarantinable=len(unq),
        lookback=args.lookback_phases,
    )
    SUGGESTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SUGGESTIONS_FILE.write_text(md, encoding="utf-8")
    if args.json:
        print(json.dumps({
            "schema": "calibration.status.v1",
            "total": len(suggestions),
            "suggestions": suggestions,
        }, indent=2, default=str))
    else:
        print(f"✓ Wrote {len(suggestions)} suggestion(s) to "
              f"{SUGGESTIONS_FILE.relative_to(REPO_ROOT)}")
        for s in suggestions:
            tag = " [UNQUARANTINABLE]" if s.get("unquarantinable") else ""
            print(f"  {s['id']}  {s['validator']:<48s}  "
                  f"{s['current_severity']:>5s} → "
                  f"{s['proposed_severity']:<5s}  ({s['kind']}){tag}")
    return 0


def _gate_reason(reason: str) -> int | None:
    if not reason or len(reason) < 50:
        print(
            "⛔ --reason required (min 50 chars). Calibration changes "
            "alter hard gate behavior — audit text must explain WHY "
            "the data crossed threshold and what the operator verified.",
            file=sys.stderr,
        )
        return 2
    return None


def cmd_apply(args: argparse.Namespace) -> int:
    rc = _gate_reason(args.reason)
    if rc is not None:
        return rc
    is_human, approver, err = _verify_human()
    if not is_human:
        msg = (
            "⛔ calibrate apply requires TTY session OR signed approver "
            "token (HMAC). AI subagents cannot self-mutate validator "
            "severity — would defeat the audit trail.\n"
            "   To approve as human:\n"
            "     a) Run from interactive shell (TTY) — auto-approved.\n"
            "     b) Mint signed token: python3 .claude/scripts/"
            "vg-auth.py approve --flag calibrate-apply\n"
            "        Then export VG_HUMAN_OPERATOR=<token>."
        )
        if err:
            msg += f"\n   (caller-auth error: {err})"
        print(msg, file=sys.stderr)
        return 2
    suggestions = compute_suggestions()
    by_id = {s["id"]: s for s in suggestions}
    target = by_id.get(args.suggestion_id)
    if not target:
        print(
            f"⛔ unknown suggestion id '{args.suggestion_id}'. Run "
            f"`registry-calibrate.py status` to refresh.",
            file=sys.stderr,
        )
        return 1
    ok, msg = _apply_suggestion(target, args.reason, approver or "tty")
    print(("✓ " if ok else "⛔ ") + msg, file=sys.stdout if ok else sys.stderr)
    return 0 if ok else 1


def cmd_apply_all(args: argparse.Namespace) -> int:
    rc = _gate_reason(args.reason)
    if rc is not None:
        return rc
    is_human, approver, err = _verify_human()
    if not is_human:
        print(
            "⛔ calibrate apply-all requires TTY OR HMAC token + reason."
            + (f" ({err})" if err else ""),
            file=sys.stderr,
        )
        return 2
    suggestions = compute_suggestions()
    if not suggestions:
        print("✓ No suggestions to apply.")
        return 0
    applied = 0
    failed: list[str] = []
    for s in suggestions:
        ok, msg = _apply_suggestion(s, args.reason, approver or "tty")
        if ok:
            applied += 1
            print("✓ " + msg)
        else:
            failed.append(f"{s['id']}: {msg}")
    if failed:
        print("\n⛔ failures:", file=sys.stderr)
        for f in failed:
            print(f"  {f}", file=sys.stderr)
    print(f"\nApplied {applied}/{len(suggestions)}")
    return 0 if not failed else 1


# ────────────────── Phase Q (v2.7): decay-policy enforcement ──────────────
#
# Decay model:
#   * `_update_suggestions_state(current_suggestions)` is called from
#     cmd_status. It records {suggestion_id: {first_seen_phase,
#     first_seen_ts}} for any newly-seen ids in a sidecar JSON file.
#     Already-tracked ids keep their original first_seen_phase — we
#     never re-stamp.
#   * "Phase counter" = count of distinct `phase` values observed in
#     events.jsonl. Approximates "how many phases have run since
#     first_seen". This is stdlib-only and avoids coupling to ROADMAP.md.
#   * `_compute_decay_candidates()` returns suggestions whose age in
#     phases ≥ DECAY_LOOKBACK_PHASES_DEFAULT AND that no longer appear
#     in the freshly-recomputed suggestion list (= no confirming
#     evidence — telemetry no longer crosses threshold).
#   * Decay action: append RETIRED block to CALIBRATION-SUGGESTIONS.md
#     in-place (mirror v2.6 Phase C `RETIRED_BY_CONFLICT` lifecycle —
#     forensic trail, no deletion) + emit
#     `calibration.suggestion_decayed` audit event per retired id.

def _current_phase_counter(events: list[dict] | None = None) -> int:
    """Count distinct phase values in events.jsonl. Used as a coarse
    'absolute phase counter' for decay age math."""
    if events is None:
        events = _load_events(EVENTS_JSONL)
    phases: set[str] = set()
    for e in events:
        p = str(e.get("phase", "")).strip()
        if p:
            phases.add(p)
    return len(phases)


def _load_suggestions_state() -> dict[str, dict]:
    if not SUGGESTIONS_STATE_FILE.exists():
        return {}
    try:
        d = json.loads(SUGGESTIONS_STATE_FILE.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save_suggestions_state(state: dict[str, dict]) -> None:
    SUGGESTIONS_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    SUGGESTIONS_STATE_FILE.write_text(
        json.dumps(state, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _update_suggestions_state(suggestions: list[dict]) -> dict[str, dict]:
    """Stamp first_seen_phase + first_seen_ts for any new ids; preserve
    existing entries. Returns the merged state (also written to disk)."""
    state = _load_suggestions_state()
    phase_counter = _current_phase_counter()
    ts = datetime.now(timezone.utc).isoformat()
    changed = False
    for s in suggestions:
        sid = s.get("id")
        if not sid or sid in state:
            continue
        state[sid] = {
            "first_seen_phase": phase_counter,
            "first_seen_ts": ts,
            "validator": s.get("validator", ""),
            "kind": s.get("kind", ""),
            "proposed_severity": s.get("proposed_severity", ""),
        }
        changed = True
    if changed:
        _save_suggestions_state(state)
    return state


def _compute_decay_candidates(
    *,
    decay_after_phases: int = DECAY_LOOKBACK_PHASES_DEFAULT,
    events: list[dict] | None = None,
    manifest: dict[str, Any] | None = None,
    state: dict[str, dict] | None = None,
) -> list[dict]:
    """Return list of {suggestion_id, age_phases, retire_reason, validator,
    proposed_severity} for ids that should decay.

    Eligible iff:
      * tracked in state (first_seen_phase known)
      * age_phases ≥ decay_after_phases
      * NOT present in current fresh suggestion recompute (no confirming
        evidence — telemetry no longer matches threshold profile)
    """
    if events is None:
        events = _load_events(EVENTS_JSONL)
    if state is None:
        state = _load_suggestions_state()
    fresh = compute_suggestions(events=events, manifest=manifest)
    fresh_ids = {s["id"] for s in fresh}

    current_phase_counter = _current_phase_counter(events)
    candidates: list[dict] = []
    for sid, meta in state.items():
        if meta.get("retired_at"):
            continue
        first_seen = int(meta.get("first_seen_phase", 0))
        age_phases = max(current_phase_counter - first_seen, 0)
        if age_phases < decay_after_phases:
            continue
        if sid in fresh_ids:
            # Confirming evidence — validator's firing pattern still
            # matches the suggestion's BLOCK/WARN profile. Keep active.
            continue
        candidates.append({
            "suggestion_id": sid,
            "age_phases": age_phases,
            "retire_reason": (
                f"decay — no confirming evidence after "
                f"{decay_after_phases} phases"
            ),
            "validator": meta.get("validator", ""),
            "proposed_severity": meta.get("proposed_severity", ""),
            "kind": meta.get("kind", ""),
        })
    return candidates


def _emit_decay_event(
    *,
    candidate: dict,
    operator_token: str,
) -> None:
    """Emit calibration.suggestion_decayed audit event. Best-effort —
    audit must never break decay action."""
    try:
        sys.path.insert(
            0, str(REPO_ROOT / ".claude" / "scripts" / "vg-orchestrator")
        )
        import db as _db  # type: ignore
        _db.append_event(
            run_id="calibrate-decay",
            event_type="calibration.suggestion_decayed",
            phase="",
            command="registry-calibrate",
            actor="user",
            outcome="INFO",
            payload={
                "suggestion_id": candidate["suggestion_id"],
                "age_phases": candidate["age_phases"],
                "retire_reason": candidate["retire_reason"],
                "operator_token": operator_token[:120] if operator_token else "",
                "validator": candidate.get("validator", ""),
                "proposed_severity": candidate.get("proposed_severity", ""),
                "ts": datetime.now(timezone.utc).isoformat(),
            },
        )
    except Exception:
        pass


def _retire_in_state(
    state: dict[str, dict],
    candidates: list[dict],
    *,
    operator_token: str,
) -> None:
    """Mark RETIRED in state file (forensic trail) — never delete."""
    ts = datetime.now(timezone.utc).isoformat()
    for c in candidates:
        sid = c["suggestion_id"]
        entry = state.setdefault(sid, {})
        entry["retired_at"] = ts
        entry["retire_reason"] = c["retire_reason"]
        entry["retired_age_phases"] = c["age_phases"]
        entry["retired_by"] = operator_token[:120] if operator_token else "tty"
    _save_suggestions_state(state)


def _annotate_retired_in_md(candidates: list[dict]) -> None:
    """Append RETIRED markers to CALIBRATION-SUGGESTIONS.md per
    decayed id — forensic trail, no deletion. Mirrors v2.6 Phase C
    RETIRED_BY_CONFLICT lifecycle pattern."""
    if not candidates:
        return
    if not SUGGESTIONS_FILE.exists():
        return
    body = SUGGESTIONS_FILE.read_text(encoding="utf-8")
    ts = datetime.now(timezone.utc).isoformat()
    block = "\n## Retired (decay)\n\n"
    block += (
        "_Suggestions below crossed threshold once but no longer have "
        "confirming evidence. Kept for forensic trail._\n\n"
    )
    for c in candidates:
        block += (
            f"- `{c['suggestion_id']}` `{c.get('validator', '')}` — "
            f"retired_at: `{ts}`, age_phases: `{c['age_phases']}`, "
            f"retire_reason: \"{c['retire_reason']}\"\n"
        )
    block += "\n"
    SUGGESTIONS_FILE.write_text(body + block, encoding="utf-8")


def cmd_apply_decay(args: argparse.Namespace) -> int:
    """Phase Q (v2.7): apply decay policy to suggestions older than
    `calibration.decay_after_phases` (default 5) without confirming
    evidence. TTY/HMAC + --reason ≥50 chars required (matches Phase F
    apply path)."""
    rc = _gate_reason(args.reason)
    if rc is not None:
        return rc
    is_human, approver, err = _verify_human()
    if not is_human:
        msg = (
            "⛔ calibrate apply-decay requires TTY session OR signed "
            "approver token (HMAC). AI subagents cannot self-mutate "
            "validator severity — would defeat the audit trail.\n"
            "   To approve as human:\n"
            "     a) Run from interactive shell (TTY) — auto-approved.\n"
            "     b) Mint signed token: python3 .claude/scripts/"
            "vg-auth.py approve --flag calibrate-apply\n"
            "        Then export VG_HUMAN_OPERATOR=<token>."
        )
        if err:
            msg += f"\n   (caller-auth error: {err})"
        print(msg, file=sys.stderr)
        return 2

    # Refresh state from a fresh status pass — ensures any newly-emerged
    # suggestions are stamped first_seen before we evaluate decay.
    fresh = compute_suggestions()
    _update_suggestions_state(fresh)

    candidates = _compute_decay_candidates(
        decay_after_phases=args.decay_after_phases,
    )
    if not candidates:
        print("✓ No decay candidates — all tracked suggestions either "
              "younger than threshold or still have confirming evidence.")
        return 0

    if args.dry_run:
        print(f"(dry-run) Would retire {len(candidates)} suggestion(s):")
        for c in candidates:
            print(
                f"  {c['suggestion_id']}  {c.get('validator', ''):<48s}  "
                f"age={c['age_phases']} phases  ({c['retire_reason']})"
            )
        return 0

    state = _load_suggestions_state()
    _retire_in_state(state, candidates, operator_token=approver or "tty")
    _annotate_retired_in_md(candidates)
    for c in candidates:
        _emit_decay_event(candidate=c, operator_token=approver or "tty")
        print(
            f"✓ retired {c['suggestion_id']}  {c.get('validator', '')}  "
            f"(age={c['age_phases']} phases)"
        )
    print(f"\nRetired {len(candidates)} suggestion(s) via decay policy.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="registry-calibrate",
        description=(
            "VG Harness v2.6 Phase F — per-validator severity "
            "calibration suggester."
        ),
    )
    sub = p.add_subparsers(dest="action", required=False)

    s_status = sub.add_parser(
        "status",
        help="Compute + write CALIBRATION-SUGGESTIONS.md (default).",
    )
    s_status.add_argument(
        "--lookback-phases", type=int,
        default=DECAY_LOOKBACK_PHASES_DEFAULT,
        help="Decay-policy footer text (display only, advisory).",
    )
    s_status.add_argument(
        "--json", action="store_true", default=False,
        help="Emit suggestions as JSON to stdout (machine-readable).",
    )
    s_status.set_defaults(func=cmd_status)

    s_apply = sub.add_parser(
        "apply",
        help="Apply ONE suggestion to dispatch-manifest.json.",
    )
    s_apply.add_argument("--suggestion-id", required=True,
                         help="ID from CALIBRATION-SUGGESTIONS.md (S-NNN)")
    s_apply.add_argument("--reason", required=True, default="",
                         help="Audit text — min 50 chars")
    s_apply.set_defaults(func=cmd_apply)

    s_all = sub.add_parser(
        "apply-all",
        help="Apply EVERY current suggestion (same gates).",
    )
    s_all.add_argument("--reason", required=True, default="",
                      help="Audit text — min 50 chars")
    s_all.set_defaults(func=cmd_apply_all)

    # Phase Q (v2.7): decay-policy enforcement
    s_decay = sub.add_parser(
        "apply-decay",
        help=("Retire suggestions older than --decay-after-phases that "
              "no longer have confirming evidence (Phase Q, v2.7)."),
    )
    s_decay.add_argument(
        "--reason", required=True, default="",
        help="Audit text — min 50 chars",
    )
    s_decay.add_argument(
        "--decay-after-phases", type=int,
        default=DECAY_LOOKBACK_PHASES_DEFAULT,
        help=("Age threshold in phases (default 5, mirrors "
              "calibration.decay_after_phases config key)."),
    )
    s_decay.add_argument(
        "--dry-run", action="store_true", default=False,
        help="Preview decay candidates without retiring them.",
    )
    s_decay.set_defaults(func=cmd_apply_decay)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.action:
        # Default: status
        args.lookback_phases = DECAY_LOOKBACK_PHASES_DEFAULT
        args.json = False
        return cmd_status(args)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
