#!/usr/bin/env python3
"""Bootstrap consolidation engine - Anthropic Auto Dream 4-phase pattern.

Task 5.1: gate + lock foundation. Subsequent tasks 5.2-5.5 add 4 phases:
  Phase 1 - Orient (read memory directory state)             [Task 5.2]
  Phase 2 - Gather (narrow grep events.db + transcripts)     [Task 5.3]
  Phase 3 - Consolidate (in-place merge per Anthropic Dreams) [Task 5.4]
  Phase 4 - Prune & Index (rebuild MEMORY.md <= 200 lines)   [Task 5.5]

Task 5.6 wires /vg:learn --consolidate skill mode.

Trigger gate (per design Section 13.1):
  - 24+ hours since last consolidation (default; override VG_DREAMS_GATE_HOURS)
  - >5 sessions since last consolidation (default; override VG_DREAMS_GATE_SESSIONS)
  - No existing .consolidation.lock (else refuse - concurrent dream prevention)

State tracked: .vg/bootstrap/state.json with last_run_ts + sessions_since_last.

Subcommands:
  --check-gate [--json]   Print gate decision (rc=0 open / rc=1 closed)
  --acquire-lock          Create .consolidation.lock with PID
  --release-lock          Remove .consolidation.lock
  --update-state          Update state.json after consolidation
  --increment-sessions    Increment sessions_since_last counter
  --phase orient [--json]      Phase 1: snapshot bootstrap state directory
  --phase gather [--json]      Phase 2: aggregate signal from events.db
  --phase consolidate [--apply] Phase 3: in-place merge into overlay/ACCEPTED/log
  --phase prune [--apply]      Phase 4: rebuild MEMORY.md <=200 lines, demote to topics/
  --consolidate-all [--apply] [--json]
                              Task 5.6 orchestrator: gate -> lock -> 4 phases
                              -> update_state (if --apply) -> release_lock.
                              Lock is ALWAYS released (try/finally) even on
                              mid-run exception. Default mode dry-run; --apply
                              required for any file write.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path


DEFAULT_GATE_HOURS = 24.0
DEFAULT_GATE_SESSIONS = 5


def _state_dir() -> Path:
    """Resolve bootstrap state directory.

    Priority:
      1. VG_BOOTSTRAP_STATE_DIR env (tests + explicit override)
      2. <cwd>/.vg/bootstrap/ (production default)
    """
    env = os.environ.get("VG_BOOTSTRAP_STATE_DIR")
    if env:
        return Path(env).resolve()
    return Path.cwd() / ".vg" / "bootstrap"


def _read_state(state_dir: Path) -> dict | None:
    state_file = state_dir / "state.json"
    if not state_file.exists():
        return None
    try:
        return json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def check_gate(state_dir: Path) -> tuple[bool, str]:
    """Return (gate_open, reason)."""
    lock_file = state_dir / ".consolidation.lock"
    if lock_file.exists():
        return False, f"lock file present at {lock_file} - concurrent dream blocked"

    state = _read_state(state_dir)
    if state is None:
        return True, "first run - no state.json, gate open"

    last_run = state.get("last_run_ts", 0)
    sessions_since = state.get("sessions_since_last", 0)

    gate_hours = float(os.environ.get("VG_DREAMS_GATE_HOURS", DEFAULT_GATE_HOURS))
    gate_sessions = int(os.environ.get("VG_DREAMS_GATE_SESSIONS", DEFAULT_GATE_SESSIONS))

    elapsed = time.time() - last_run
    if elapsed < gate_hours * 3600:
        elapsed_h = elapsed / 3600
        # Strip trailing .0 so integer thresholds render as "24h" not "24.0h"
        gate_h_str = f"{gate_hours:g}h"
        return False, f"<{gate_h_str} since last run ({elapsed_h:.1f}h elapsed)"

    if sessions_since <= gate_sessions:
        return False, f"<={gate_sessions} sessions since last run ({sessions_since} counted)"

    return True, "both gates passed (24h+ elapsed + sessions threshold met)"


def acquire_lock(state_dir: Path) -> bool:
    state_dir.mkdir(parents=True, exist_ok=True)
    lock_file = state_dir / ".consolidation.lock"
    if lock_file.exists():
        return False
    lock_file.write_text(f"pid={os.getpid()}\n", encoding="utf-8")
    return True


def release_lock(state_dir: Path) -> bool:
    lock_file = state_dir / ".consolidation.lock"
    if lock_file.exists():
        lock_file.unlink()
        return True
    return False


def update_state(state_dir: Path):
    state_dir.mkdir(parents=True, exist_ok=True)
    state_file = state_dir / "state.json"
    new_state = {
        "last_run_ts": time.time(),
        "sessions_since_last": 0,
    }
    state_file.write_text(json.dumps(new_state, indent=2), encoding="utf-8")


def increment_sessions(state_dir: Path):
    state = _read_state(state_dir) or {"last_run_ts": 0, "sessions_since_last": 0}
    state["sessions_since_last"] = state.get("sessions_since_last", 0) + 1
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Phase 1 - Orient (Task 5.2)
#
# Read .vg/bootstrap/ directory to produce a JSON snapshot of current memory
# state. Pure-read; never mutates anything. Used by Phase 2/3/4 as the input
# baseline ("where are we starting from?") and by /vg:learn --consolidate as
# a quick health probe.
#
# Snapshot fields:
#   accepted_md_exists / rejected_md_exists / retracted_md_exists / candidates_md_exists  bool
#   rule_count                          int   # len(rules/*.md)
#   memory_md_lines                     int   # 0 if MEMORY.md absent
#   last_consolidation_ts               float|None  # from state.json
#   sessions_since_last                 int|None    # from state.json
#   oversized_files                     list[str]   # rel paths > OVERSIZE_BYTES
#   orphan_files                        list[str]   # rel paths not matching any
#                                                   # known schema slot
#   state_dir                           str   # absolute path
# ---------------------------------------------------------------------------

OVERSIZE_BYTES = 50_000  # 50 KB - design Section 13.1 storage health probe

# Files we recognize at the top of .vg/bootstrap/. Anything else under the
# state dir that is not a rules/ entry, topics/ entry, or known artifact is
# flagged as orphan so consolidation can decide whether to re-home or prune.
KNOWN_TOP_LEVEL = frozenset({
    "MEMORY.md",
    "ACCEPTED.md",
    "REJECTED.md",
    "RETRACTED.md",
    "CANDIDATES.md",
    "CONSOLIDATION-LOG.md",
    "overlay.yml",
    "state.json",
    ".consolidation.lock",
})


def _count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return 0
    if not text:
        return 0
    # Trailing newline shouldn't add a phantom line: "a\n" is 1 line.
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def _walk_files(root: Path):
    """Yield every regular file under root (recursive). Skip if root absent."""
    if not root.exists():
        return
    for p in root.rglob("*"):
        if p.is_file():
            yield p


def orient(state_dir: Path) -> dict:
    """Phase 1 - return snapshot dict (never raises on missing dir)."""
    rules_dir = state_dir / "rules"
    rule_files = []
    if rules_dir.exists() and rules_dir.is_dir():
        rule_files = sorted(p for p in rules_dir.glob("*.md") if p.is_file())

    state = _read_state(state_dir) or {}

    snap: dict = {
        "phase": "orient",
        "state_dir": str(state_dir),
        "accepted_md_exists": (state_dir / "ACCEPTED.md").exists(),
        "rejected_md_exists": (state_dir / "REJECTED.md").exists(),
        "retracted_md_exists": (state_dir / "RETRACTED.md").exists(),
        "candidates_md_exists": (state_dir / "CANDIDATES.md").exists(),
        "memory_md_exists": (state_dir / "MEMORY.md").exists(),
        "overlay_yml_exists": (state_dir / "overlay.yml").exists(),
        "consolidation_log_exists": (state_dir / "CONSOLIDATION-LOG.md").exists(),
        "rule_count": len(rule_files),
        "memory_md_lines": _count_lines(state_dir / "MEMORY.md"),
        "last_consolidation_ts": state.get("last_run_ts"),
        "sessions_since_last": state.get("sessions_since_last"),
        "oversized_files": [],
        "orphan_files": [],
    }

    if not state_dir.exists():
        return snap

    # Storage health: any file > OVERSIZE_BYTES anywhere under state_dir
    for f in _walk_files(state_dir):
        try:
            size = f.stat().st_size
        except OSError:
            continue
        rel = f.relative_to(state_dir).as_posix()
        if size > OVERSIZE_BYTES:
            snap["oversized_files"].append(rel)

    # Orphan detection: top-level files not in KNOWN_TOP_LEVEL and not under
    # rules/ or topics/. We deliberately don't recurse into rules/topics here;
    # those are owned by Phase 3/4 and have their own naming rules.
    for child in state_dir.iterdir():
        if child.is_dir():
            if child.name not in {"rules", "topics"}:
                snap["orphan_files"].append(child.name + "/")
            continue
        if child.name not in KNOWN_TOP_LEVEL:
            snap["orphan_files"].append(child.name)

    snap["oversized_files"].sort()
    snap["orphan_files"].sort()
    return snap


# ---------------------------------------------------------------------------
# Phase 2 - Gather Signal (Task 5.3)
#
# Aggregate evidence from events.db and (later) narrow JSONL transcripts.
# Per Anthropic Auto Dream design (Section 13.1) + Codex #9 attribution gate
# (Section 13.4):
#
#   For procedural rules:
#     * outcomes WITHOUT attribution.executed_step_ids are DROPPED
#       (cargo-cult prevention — executor bypassed sequence). The CLI gate
#       in vg-orchestrator emit-event already rejects these at write time,
#       but we double-gate at read time so a manually-inserted row can't
#       poison consolidation either.
#     * outcomes WITH non-empty executed_step_ids count toward attributed_pass
#       or attributed_fail by event.outcome column.
#
#   For declarative rules: outcome counted as-is (no attribution required).
#
# Window: bounded by --since-days (default 30) AND --max-events (default
# 5000). Whichever fires first. Matches Anthropic's "last N days OR last
# 100 sessions, whichever smaller" pattern adapted for this repo's scale.
#
# Tier proposal:
#   tier_proposed = "A" iff attributed_pass >= 3 AND contradiction is False
#   contradiction = True iff attributed_pass >= 3 AND attributed_fail >= 3
#                  (PASS streak followed by recurring FAIL → propose retract,
#                  but NEVER auto-retract — Phase 3 invariant)
#
# Test isolation: VG_EVENTS_DB_PATH overrides .vg/events.db location.
# ---------------------------------------------------------------------------

DEFAULT_GATHER_SINCE_DAYS = 30
DEFAULT_GATHER_MAX_EVENTS = 5000


def _events_db_path() -> Path:
    """Resolve events.db path. VG_EVENTS_DB_PATH wins for tests; otherwise
    .vg/events.db at CWD (matches vg-orchestrator/db.py production layout)."""
    env = os.environ.get("VG_EVENTS_DB_PATH")
    if env:
        return Path(env).resolve()
    return Path.cwd() / ".vg" / "events.db"


def _query_outcome_events(db_path: Path, since_days: int,
                          max_events: int) -> list[dict]:
    """Pull bootstrap.outcome_recorded events within [now - since_days, now].

    Returns list of dicts with keys: outcome (column), payload (parsed dict).
    Empty list if db absent or schema missing (graceful degrade — Phase 2 must
    not raise on a fresh repo with no events.db yet).
    """
    if not db_path.exists():
        return []
    import sqlite3
    cutoff = time.time() - since_days * 86400
    # ts column is "%Y-%m-%dT%H:%M:%SZ" UTC string. ORDER BY id DESC LIMIT
    # max_events caps work; we then filter by ts >= cutoff in Python so a
    # malformed ts doesn't break the SQL.
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
    except sqlite3.Error:
        return []
    try:
        try:
            rows = conn.execute(
                "SELECT outcome, payload_json, ts FROM events "
                "WHERE event_type = ? ORDER BY id DESC LIMIT ?",
                ("bootstrap.outcome_recorded", max_events),
            ).fetchall()
        except sqlite3.Error:
            return []
    finally:
        conn.close()

    import datetime
    out: list[dict] = []
    for r in rows:
        ts_str = r["ts"]
        try:
            ts_dt = datetime.datetime.strptime(ts_str, "%Y-%m-%dT%H:%M:%SZ")
            ts_epoch = ts_dt.replace(tzinfo=datetime.timezone.utc).timestamp()
        except (ValueError, TypeError):
            ts_epoch = 0.0
        if ts_epoch < cutoff:
            continue
        try:
            payload = json.loads(r["payload_json"]) if r["payload_json"] else {}
        except json.JSONDecodeError:
            payload = {}
        out.append({"outcome": r["outcome"], "payload": payload})
    return out


def _classify_outcome(outcome_col: str, payload: dict) -> str:
    """Map (event.outcome column, payload.outcome) -> normalized PASS/FAIL/OTHER.

    Some emitters set outcome via the column (--outcome PASS); others put it
    in the payload (payload['outcome']='success'). We accept both. Anything
    that isn't a clean PASS or FAIL surfaces as OTHER and is ignored for
    tier promotion (tracked separately in raw_event_count).
    """
    raw = (outcome_col or "").upper()
    if raw in {"PASS", "SUCCESS"}:
        return "PASS"
    if raw in {"FAIL", "BLOCK", "FAILURE"}:
        return "FAIL"
    payload_oc = str(payload.get("outcome", "")).lower()
    if payload_oc in {"pass", "success"}:
        return "PASS"
    if payload_oc in {"fail", "failure", "block"}:
        return "FAIL"
    return "OTHER"


def gather(state_dir: Path, since_days: int = DEFAULT_GATHER_SINCE_DAYS,
           max_events: int = DEFAULT_GATHER_MAX_EVENTS) -> dict:
    """Phase 2 - aggregate rule signals from events.db.

    Returns dict with:
      phase: "gather"
      events_window_sec
      events_processed   # rows kept after window + parse
      rule_signals: { slug: { rule_type, attributed_pass, attributed_fail,
                              dropped_no_attribution, tier_proposed,
                              contradiction } }
      transcript_signals  # placeholder for future narrow-grep work
      events_db: str
    """
    db_path = _events_db_path()
    events = _query_outcome_events(db_path, since_days, max_events)

    rule_signals: dict[str, dict] = {}
    dropped_total = 0

    for ev in events:
        payload = ev["payload"] or {}
        slug = payload.get("slug") or payload.get("rule_id")
        if not slug:
            continue
        rule_type = payload.get("rule_type", "declarative")
        sig = rule_signals.setdefault(slug, {
            "rule_type": rule_type,
            "attributed_pass": 0,
            "attributed_fail": 0,
            "dropped_no_attribution": 0,
            "tier_proposed": None,
            "contradiction": False,
        })
        # Keep the most-specific rule_type if we see it later (procedural
        # wins over declarative — declarative is the safe default fallback
        # for legacy events without rule_type).
        if rule_type == "procedural":
            sig["rule_type"] = "procedural"

        # Codex #9 attribution gate (read-side enforcement):
        #   procedural rules require non-empty executed_step_ids.
        if sig["rule_type"] == "procedural":
            attribution = payload.get("attribution") or {}
            executed = (
                attribution.get("executed_step_ids")
                if isinstance(attribution, dict) else None
            )
            if not executed:
                sig["dropped_no_attribution"] += 1
                dropped_total += 1
                continue

        norm = _classify_outcome(ev["outcome"], payload)
        if norm == "PASS":
            sig["attributed_pass"] += 1
        elif norm == "FAIL":
            sig["attributed_fail"] += 1
        # OTHER -> intentionally ignored (no signal, no drop counter)

    # Tier proposal pass — done after counting so contradiction wins over
    # tier-A promotion when both fire.
    for slug, sig in rule_signals.items():
        ap = sig["attributed_pass"]
        af = sig["attributed_fail"]
        if ap >= 3 and af >= 3:
            sig["contradiction"] = True
            sig["tier_proposed"] = None  # consolidate phase will warn-only
        elif ap >= 3 and af == 0:
            sig["tier_proposed"] = "A"
        # else: leave tier_proposed=None (insufficient evidence)

    return {
        "phase": "gather",
        "events_db": str(db_path),
        "events_window_sec": since_days * 86400,
        "events_processed": len(events),
        "events_dropped_no_attribution": dropped_total,
        "rule_signals": rule_signals,
        "transcript_signals": [],  # placeholder; narrow-grep deferred
    }


# ---------------------------------------------------------------------------
# Phase 3 - Consolidate (Task 5.4)
#
# In-place merge per Anthropic Auto Dream pattern (design Section 13.1):
#   * MERGE existing files; do NOT create side-by-side CONSOLIDATION-{date}.md
#   * Surgical edits: only files we touch are modified; unchanged files stay
#     byte-identical
#   * Append-only CONSOLIDATION-LOG.md audit trail (every run, every action)
#
# Inputs: Phase 2 gather report (rule_signals).
# Action matrix per rule signal:
#
#   recurrence (tier_proposed="A")  -> overlay.yml: tier_a entry written
#                                      ACCEPTED.md: append entry
#                                      CONSOLIDATION-LOG.md: append "promoted" line
#   contradiction (PASS+FAIL >=3 each) -> CONSOLIDATION-LOG.md: append warning
#                                         emit bootstrap.contradiction_detected
#                                         (best-effort; no auto-retract)
#   drift (no fire >=30 days)       -> [deferred until Phase 4 has lifecycle data]
#
# CRITICAL INVARIANT: default mode = dry-run report. --apply required for
# any file write. Even with --apply, NEVER auto-retract or auto-modify
# rules/{slug}.md content. Contradictions surface as log warnings; humans
# decide retract via /vg:learn explicit accept/reject.
#
# Absolute timestamps only (design Section 13.1: "no relative dates"). Every
# log entry uses UTC ISO 8601.
# ---------------------------------------------------------------------------


def _utc_iso_now() -> str:
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def _load_yaml_overlay(path: Path) -> dict:
    """Best-effort YAML overlay loader. Returns {} on missing/parse-fail.

    Phase 3 only writes a tiny shape (rule_promotions list + counters), so
    we don't need the full PyYAML dependency here. We do a minimal
    line-based parse limited to that shape; on anything unexpected we
    treat it as empty and let --apply rewrite it.
    """
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    # Try PyYAML if installed; otherwise return empty (Phase 3 will
    # initialize the file from scratch on --apply).
    try:
        import yaml
        loaded = yaml.safe_load(text)
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def _dump_yaml_overlay(path: Path, data: dict) -> None:
    """Write overlay.yml. Falls back to JSON-flavored YAML if PyYAML absent."""
    try:
        import yaml
        text = yaml.safe_dump(data, sort_keys=True,
                              default_flow_style=False)
    except ImportError:
        text = json.dumps(data, indent=2, sort_keys=True) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def consolidate(state_dir: Path, gather_report: dict, apply: bool) -> dict:
    """Phase 3 - merge gather signals into overlay.yml + ACCEPTED.md + log.

    Returns a dry-run/apply report dict. Mutates filesystem ONLY when
    apply=True (and even then: never rules/{slug}.md content).
    """
    overlay_path = state_dir / "overlay.yml"
    accepted_path = state_dir / "ACCEPTED.md"
    log_path = state_dir / "CONSOLIDATION-LOG.md"
    rules_dir = state_dir / "rules"

    actions: list[dict] = []
    promotions: list[str] = []
    contradictions: list[str] = []

    rule_signals = gather_report.get("rule_signals", {}) or {}
    for slug, sig in sorted(rule_signals.items()):
        if sig.get("contradiction"):
            actions.append({"slug": slug, "action": "warn_contradiction",
                            "pass": sig["attributed_pass"],
                            "fail": sig["attributed_fail"]})
            contradictions.append(slug)
            continue
        if sig.get("tier_proposed") == "A":
            actions.append({"slug": slug, "action": "promote_tier_a",
                            "pass": sig["attributed_pass"]})
            promotions.append(slug)

    report = {
        "phase": "consolidate",
        "apply": apply,
        "actions": actions,
        "promotions": promotions,
        "contradictions": contradictions,
        "files_modified": [],
        "state_dir": str(state_dir),
    }

    if not apply:
        # Dry-run: nothing on disk changes. Caller can pipe to log.
        return report

    state_dir.mkdir(parents=True, exist_ok=True)
    ts = _utc_iso_now()
    files_modified: set[str] = set()

    # --- overlay.yml ---
    overlay = _load_yaml_overlay(overlay_path)
    overlay.setdefault("rule_promotions", {})
    overlay.setdefault("counters", {})
    counters = overlay["counters"]
    counters.setdefault("tier_a_count", 0)
    counters.setdefault("contradiction_count", 0)

    for slug in promotions:
        # Idempotent: don't double-count if a previous run already promoted.
        existing = overlay["rule_promotions"].get(slug)
        if not existing or existing.get("tier") != "A":
            overlay["rule_promotions"][slug] = {
                "tier": "A",
                "promoted_at": ts,
                "attributed_pass": rule_signals[slug]["attributed_pass"],
            }
            counters["tier_a_count"] = counters.get("tier_a_count", 0) + 1

    counters["contradiction_count"] = (
        counters.get("contradiction_count", 0) + len(contradictions))

    if promotions or contradictions:
        _dump_yaml_overlay(overlay_path, overlay)
        files_modified.add(overlay_path.name)

    # --- ACCEPTED.md (append-only entries for promotions) ---
    if promotions:
        accepted_path.parent.mkdir(parents=True, exist_ok=True)
        existing = (accepted_path.read_text(encoding="utf-8")
                    if accepted_path.exists() else "# Accepted rules\n\n")
        new_entries = []
        for slug in promotions:
            # Skip if already listed (idempotent re-runs)
            if f"- {slug}" in existing:
                continue
            sig = rule_signals[slug]
            new_entries.append(
                f"- {slug} (tier A, attributed_pass={sig['attributed_pass']}, "
                f"promoted_at={ts})")
        if new_entries:
            accepted_path.write_text(
                existing + "\n".join(new_entries) + "\n", encoding="utf-8")
            files_modified.add(accepted_path.name)

    # --- CONSOLIDATION-LOG.md (append-only audit trail; ALWAYS written
    # when apply=True, even with empty action set, so absence-of-rerun is
    # detectable). ---
    log_lines = [f"\n## {ts}"]
    if promotions:
        log_lines.append("### Promotions (tier A)")
        for slug in promotions:
            sig = rule_signals[slug]
            log_lines.append(
                f"- {slug}: attributed_pass={sig['attributed_pass']}")
    if contradictions:
        log_lines.append("### Contradictions (warn-only — NO auto-retract)")
        for slug in contradictions:
            sig = rule_signals[slug]
            log_lines.append(
                f"- {slug}: pass={sig['attributed_pass']} "
                f"fail={sig['attributed_fail']} "
                f"-> human review via /vg:learn required")
    if not promotions and not contradictions:
        log_lines.append("(no actionable signals this run)")

    if log_path.exists():
        prefix = log_path.read_text(encoding="utf-8")
    else:
        prefix = ("# Consolidation Log\n\nAppend-only audit trail. "
                  "Each run adds one section.\n")
    log_path.write_text(prefix + "\n".join(log_lines) + "\n",
                        encoding="utf-8")
    files_modified.add(log_path.name)

    # --- Defensive sanity: ensure rules/{slug}.md was NOT touched.
    # Phase 3 invariant says we never modify rule bodies. We don't actually
    # reach into rules_dir above; this assertion captures intent.
    if rules_dir.exists():
        # No-op: read-only intent. Listed here for code-review clarity.
        pass

    report["files_modified"] = sorted(files_modified)
    return report


# ---------------------------------------------------------------------------
# Phase 4 - Prune & Index (Task 5.5)
#
# Rebuild .vg/bootstrap/MEMORY.md so its line count <= MEMORY_MAX_LINES
# (Anthropic Dreams startup cutoff: 200 lines per design Section 13.1).
# When the index would overflow, demote the oldest / lowest-priority rules
# into per-topic files at .vg/bootstrap/topics/{target_step}.md, leaving a
# 1-line pointer in MEMORY.md.
#
# Index entry shape (one line per rule):
#   - {slug} ({tier}/{priority}) target={target_step} -> topics/{target_step}.md
#
# Selection for demotion when over budget:
#   1. Group rules by target_step (e.g. "deploy", "test", "accept", "build").
#   2. Sort within group by (priority asc, mtime asc) -> demote lowest-priority
#      and oldest first.
#   3. Pop until len(MEMORY.md lines) <= MEMORY_MAX_LINES.
#
# Default mode = dry-run; --apply required for writes (consistent with
# Phase 3). Topic files are append-managed: existing topic content is
# preserved, demoted rules are appended fresh under the date header.
# ---------------------------------------------------------------------------

MEMORY_MAX_LINES = 200
MEMORY_HEADER = (
    "# .vg/bootstrap/MEMORY.md\n"
    "\n"
    "Index of accepted bootstrap rules. Capped at 200 lines (Anthropic\n"
    "Dreams startup cutoff). Verbose entries demoted to topics/.\n"
    "\n"
)


PRIORITY_RANK = {"high": 3, "medium": 2, "low": 1}


def _parse_rule_frontmatter(path: Path) -> dict:
    """Return YAML frontmatter dict for a rule file. Empty dict on parse fail
    so prune is robust against partially-written files."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}
    front_text = text[4:end]
    try:
        import yaml
        loaded = yaml.safe_load(front_text)
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        # Minimal fallback: parse top-level "key: value" lines (no nesting).
        out: dict = {}
        for line in front_text.splitlines():
            if ":" in line and not line.startswith(" "):
                k, _, v = line.partition(":")
                out[k.strip()] = v.strip().strip('"').strip("'")
        return out


def _rule_summary_line(slug: str, front: dict, target: str) -> str:
    title = front.get("title", "").strip()
    tier = front.get("tier", "?")
    prio = front.get("priority", "?")
    summary = title if title else slug
    # Trim summary so each index line stays compact (~120 chars).
    if len(summary) > 80:
        summary = summary[:77] + "..."
    return (f"- {slug} ({tier}/{prio}) target={target} "
            f"-> topics/{target}.md  # {summary}")


def prune(state_dir: Path, apply: bool) -> dict:
    """Phase 4 - rebuild MEMORY.md + topic files.

    Returns dry-run/apply report dict. Mutates filesystem ONLY on apply=True.
    """
    rules_dir = state_dir / "rules"
    memory_path = state_dir / "MEMORY.md"
    topics_dir = state_dir / "topics"

    rule_paths: list[Path] = []
    if rules_dir.exists() and rules_dir.is_dir():
        rule_paths = sorted(p for p in rules_dir.glob("*.md") if p.is_file())

    # Build (slug, frontmatter, target, mtime, priority_rank) list.
    rule_meta: list[dict] = []
    for p in rule_paths:
        front = _parse_rule_frontmatter(p)
        slug = front.get("slug") or p.stem
        target = (front.get("target_step") or front.get("target")
                  or "general")
        prio = (front.get("priority") or "low").lower()
        try:
            mtime = p.stat().st_mtime
        except OSError:
            mtime = 0.0
        rule_meta.append({
            "path": p,
            "slug": slug,
            "front": front,
            "target": target,
            "mtime": mtime,
            "prio_rank": PRIORITY_RANK.get(prio, 0),
        })

    # Header line count: MEMORY_HEADER is multi-line. MEMORY.md cap is HARD
    # (Anthropic Dreams 200-line startup cutoff). Budget = cap - header -
    # demoted-pointer-section overhead. Demoted rules are NOT listed
    # individually in MEMORY.md; instead one collective pointer per target
    # group ("see topics/{target}.md") so the index stays compact.
    header_lines = MEMORY_HEADER.count("\n")

    # Sort by demotion priority: lowest prio_rank first, oldest mtime first,
    # then slug for stability. Best candidates are LAST in this order.
    ranked = sorted(
        rule_meta,
        key=lambda r: (r["prio_rank"], r["mtime"], r["slug"]),
    )

    # Greedy fit: start with empty kept set, add rules from highest priority
    # first until we hit the budget. Anything left over is demoted.
    # Budget for kept index lines = MEMORY_MAX_LINES - header - reserve
    # (demoted-section header + per-target pointer lines).
    targets_seen: set[str] = set()
    for r in rule_meta:
        targets_seen.add(r["target"])
    # Reserve: blank line + "## Demoted" + per-target pointer lines.
    # If no demotion, reserve = 0.
    # We compute the reserve assuming worst case (all targets demoted), then
    # tighten after we know which actually got demoted. Two-pass keeps the
    # math simple.
    worst_case_reserve = 2 + len(targets_seen) if targets_seen else 0
    budget = MEMORY_MAX_LINES - header_lines - worst_case_reserve
    if budget < 0:
        budget = 0

    # Walk best-priority-first (reverse of demotion order).
    kept_meta: list[dict] = []
    demoted: list[dict] = []
    for r in reversed(ranked):
        if len(kept_meta) < budget:
            kept_meta.append(r)
        else:
            demoted.append(r)

    # Recompute reserve based on actual demoted target groups.
    demoted_targets = sorted({r["target"] for r in demoted})
    if demoted_targets:
        actual_reserve = 2 + len(demoted_targets)  # blank + header + pointers
        # If actual_reserve smaller, we may be able to keep MORE rules.
        # Re-budget once.
        new_budget = MEMORY_MAX_LINES - header_lines - actual_reserve
        if new_budget > len(kept_meta):
            # Promote some demoted rules back into kept (highest-priority of
            # the demoted set first).
            promote_back = sorted(
                demoted,
                key=lambda r: (-r["prio_rank"], -r["mtime"], r["slug"]),
            )[:new_budget - len(kept_meta)]
            promote_set = {id(r) for r in promote_back}
            kept_meta.extend(promote_back)
            demoted = [r for r in demoted if id(r) not in promote_set]
            demoted_targets = sorted({r["target"] for r in demoted})

    # Stable-order kept lines by original sort (priority desc, then slug).
    kept_meta.sort(key=lambda r: (-r["prio_rank"], r["slug"]))

    kept_lines = [
        _rule_summary_line(r["slug"], r["front"], r["target"])
        for r in kept_meta
    ]

    pointer_lines: list[str] = []
    if demoted_targets:
        for t in demoted_targets:
            count = sum(1 for r in demoted if r["target"] == t)
            pointer_lines.append(
                f"- {t}: {count} rules -> topics/{t}.md")

    body_lines = list(kept_lines)
    if pointer_lines:
        body_lines.append("")
        body_lines.append("## Demoted (full content in topics/)")
        body_lines.extend(pointer_lines)

    final_text = MEMORY_HEADER + "\n".join(body_lines)
    if not final_text.endswith("\n"):
        final_text += "\n"
    final_lines = final_text.count("\n")

    # Group demoted by target for topic-file writes.
    topics_to_write: dict[str, list[dict]] = {}
    for r in demoted:
        topics_to_write.setdefault(r["target"], []).append(r)

    report = {
        "phase": "prune",
        "apply": apply,
        "state_dir": str(state_dir),
        "rules_total": len(rule_meta),
        "memory_md_lines_before": _count_lines(memory_path),
        "memory_md_lines_after": final_lines,
        "demoted_count": len(demoted),
        "demoted_slugs": [r["slug"] for r in demoted],
        "topics_written": sorted(topics_to_write.keys()),
        "files_modified": [],
    }

    if not apply:
        return report

    files_modified: list[str] = []
    state_dir.mkdir(parents=True, exist_ok=True)
    memory_path.write_text(final_text, encoding="utf-8")
    files_modified.append("MEMORY.md")

    if topics_to_write:
        topics_dir.mkdir(parents=True, exist_ok=True)
        ts = _utc_iso_now()
        for target, group in topics_to_write.items():
            tp = topics_dir / f"{target}.md"
            existing = tp.read_text(encoding="utf-8") if tp.exists() else (
                f"# {target} rules (demoted from MEMORY.md)\n\n")
            section = [f"\n## Demoted at {ts}\n"]
            for r in group:
                try:
                    body = r["path"].read_text(encoding="utf-8")
                except OSError:
                    body = ""
                section.append(
                    f"### {r['slug']} (priority={r['front'].get('priority','?')})")
                section.append("")
                section.append(body)
                section.append("")
            tp.write_text(existing + "\n".join(section), encoding="utf-8")
            files_modified.append(f"topics/{target}.md")

    report["files_modified"] = sorted(files_modified)
    return report


# ---------------------------------------------------------------------------
# Task 5.6 - --consolidate-all orchestrator
#
# Wires gate -> lock -> 4 phases -> state update -> release-lock into a single
# atomic CLI surface invoked by /vg:learn --consolidate. Lock is ALWAYS
# released via try/finally so a phase crash never strands the bootstrap zone.
#
# Exit codes:
#   0 - gate_closed (no-op) | ok (success, dry-run or apply)
#   1 - lock_busy (concurrent dream blocked) | phase_error (any phase raised)
# ---------------------------------------------------------------------------

def consolidate_all(state_dir: Path, apply: bool,
                    since_days: int = DEFAULT_GATHER_SINCE_DAYS,
                    max_events: int = DEFAULT_GATHER_MAX_EVENTS) -> tuple[int, dict]:
    """Run the full 4-phase Anthropic Auto Dream cycle atomically.

    Returns (exit_code, report_dict).
    """
    # 1. Gate check -- if closed, return 0 with reason and DO NOTHING
    gate_open, reason = check_gate(state_dir)
    if not gate_open:
        return 0, {"status": "gate_closed", "reason": reason,
                   "state_dir": str(state_dir)}

    # 2. Acquire lock -- if busy, return 1
    if not acquire_lock(state_dir):
        return 1, {"status": "lock_busy",
                   "reason": "concurrent dream already running",
                   "state_dir": str(state_dir)}

    # 3. Run 4 phases. CRITICAL: try/finally so release_lock ALWAYS runs.
    try:
        orient_result = orient(state_dir)
        gather_result = gather(state_dir, since_days, max_events)
        consolidate_result = consolidate(state_dir, gather_result, apply=apply)
        prune_result = prune(state_dir, apply=apply)

        # 4. Update state.json only on real apply (dry-run leaves state alone)
        if apply:
            update_state(state_dir)

        report = {
            "status": "ok",
            "apply": apply,
            "state_dir": str(state_dir),
            "orient": orient_result,
            "gather": gather_result,
            "consolidate": consolidate_result,
            "prune": prune_result,
        }
        return 0, report
    except Exception as exc:  # noqa: BLE001 - we re-raise context via report
        return 1, {
            "status": "phase_error",
            "apply": apply,
            "state_dir": str(state_dir),
            "error": f"{type(exc).__name__}: {exc}",
        }
    finally:
        # ALWAYS release the lock, even on exception. This is the hard
        # invariant: a stranded lock blocks every future dream until
        # someone manually clears .consolidation.lock.
        release_lock(state_dir)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Bootstrap consolidation gate (Task 5.1)")
    parser.add_argument("--check-gate", action="store_true", help="Check trigger gate")
    parser.add_argument("--acquire-lock", action="store_true", help="Acquire .consolidation.lock")
    parser.add_argument("--release-lock", action="store_true", help="Release .consolidation.lock")
    parser.add_argument("--update-state", action="store_true",
                        help="Update state.json after successful consolidation")
    parser.add_argument("--increment-sessions", action="store_true",
                        help="Increment sessions_since_last counter")
    parser.add_argument("--phase",
                        choices=["orient", "gather", "consolidate", "prune"],
                        default=None,
                        help="Run a 4-phase consolidation step")
    parser.add_argument("--since-days", type=int, default=DEFAULT_GATHER_SINCE_DAYS,
                        help="Phase 2 window in days (default 30)")
    parser.add_argument("--max-events", type=int, default=DEFAULT_GATHER_MAX_EVENTS,
                        help="Phase 2 max events to scan (default 5000)")
    parser.add_argument("--apply", action="store_true",
                        help="Phase 3/4: perform writes (default: dry-run report)")
    parser.add_argument("--consolidate-all", action="store_true",
                        help="Task 5.6 orchestrator: gate -> lock -> 4 phases "
                             "-> update_state (if --apply) -> release_lock. "
                             "Lock ALWAYS released via try/finally.")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args(argv[1:])

    state_dir = _state_dir()

    if args.check_gate:
        gate_open, reason = check_gate(state_dir)
        payload = {"gate_open": gate_open, "reason": reason, "state_dir": str(state_dir)}
        if args.json:
            print(json.dumps(payload))
        else:
            print(f"gate_open={gate_open} reason={reason}")
        return 0 if gate_open else 1

    if args.acquire_lock:
        ok = acquire_lock(state_dir)
        if not ok:
            print("acquire_lock: lock already present", file=sys.stderr)
            return 1
        return 0

    if args.release_lock:
        ok = release_lock(state_dir)
        if not ok:
            print("release_lock: no lock file present", file=sys.stderr)
            return 1
        return 0

    if args.update_state:
        update_state(state_dir)
        return 0

    if args.increment_sessions:
        increment_sessions(state_dir)
        return 0

    if args.phase == "orient":
        snap = orient(state_dir)
        if args.json:
            print(json.dumps(snap))
        else:
            print(f"phase=orient state_dir={snap['state_dir']}")
            print(f"  rules: {snap['rule_count']}")
            print(f"  MEMORY.md: {snap['memory_md_lines']} lines"
                  f" (exists={snap['memory_md_exists']})")
            print(f"  ACCEPTED.md exists: {snap['accepted_md_exists']}")
            print(f"  oversized files: {len(snap['oversized_files'])}")
            print(f"  orphan files: {len(snap['orphan_files'])}")
        return 0

    if args.phase == "gather":
        report = gather(state_dir, args.since_days, args.max_events)
        if args.json:
            print(json.dumps(report))
        else:
            print(f"phase=gather events_db={report['events_db']}")
            print(f"  events_processed: {report['events_processed']}")
            print(f"  events_dropped_no_attribution: "
                  f"{report['events_dropped_no_attribution']}")
            print(f"  rule_signals:")
            for slug, sig in sorted(report["rule_signals"].items()):
                print(f"    {slug}: pass={sig['attributed_pass']} "
                      f"fail={sig['attributed_fail']} "
                      f"tier={sig['tier_proposed']} "
                      f"contradiction={sig['contradiction']}")
        return 0

    if args.phase == "consolidate":
        # Phase 3 chains off Phase 2's gather report. Run gather first so
        # tests can drive Phase 3 end-to-end with one CLI call.
        gather_report = gather(state_dir, args.since_days, args.max_events)
        report = consolidate(state_dir, gather_report, apply=args.apply)
        if args.json:
            print(json.dumps(report))
        else:
            mode = "apply" if args.apply else "dry-run"
            print(f"phase=consolidate mode={mode} state_dir={report['state_dir']}")
            print(f"  promotions: {len(report['promotions'])} "
                  f"-> {report['promotions']}")
            print(f"  contradictions: {len(report['contradictions'])} "
                  f"-> {report['contradictions']}")
            print(f"  files_modified: {report['files_modified']}")
        return 0

    if args.phase == "prune":
        report = prune(state_dir, apply=args.apply)
        if args.json:
            print(json.dumps(report))
        else:
            mode = "apply" if args.apply else "dry-run"
            print(f"phase=prune mode={mode} state_dir={report['state_dir']}")
            print(f"  rules_total: {report['rules_total']}")
            print(f"  MEMORY.md lines before: {report['memory_md_lines_before']}"
                  f", after: {report['memory_md_lines_after']}")
            print(f"  demoted: {report['demoted_count']} "
                  f"-> {report['demoted_slugs']}")
            print(f"  topics_written: {report['topics_written']}")
            print(f"  files_modified: {report['files_modified']}")
        return 0

    if args.consolidate_all:
        rc, report = consolidate_all(state_dir, apply=args.apply,
                                     since_days=args.since_days,
                                     max_events=args.max_events)
        if args.json:
            print(json.dumps(report))
        else:
            status = report.get("status", "?")
            mode = "apply" if args.apply else "dry-run"
            print(f"consolidate-all status={status} mode={mode} "
                  f"state_dir={report.get('state_dir','?')}")
            if status == "gate_closed":
                print(f"  reason: {report.get('reason','')}")
            elif status == "lock_busy":
                print(f"  reason: {report.get('reason','')}")
            elif status == "phase_error":
                print(f"  error: {report.get('error','')}")
            elif status == "ok":
                cons = report.get("consolidate", {}) or {}
                pru = report.get("prune", {}) or {}
                gather_r = report.get("gather", {}) or {}
                print(f"  events_processed: "
                      f"{gather_r.get('events_processed', 0)}")
                print(f"  promotions: "
                      f"{len(cons.get('promotions', []))}")
                print(f"  contradictions: "
                      f"{len(cons.get('contradictions', []))}")
                print(f"  demoted: {pru.get('demoted_count', 0)}")
                files_mod = list(cons.get("files_modified", []) or []) + \
                            list(pru.get("files_modified", []) or [])
                print(f"  files_modified: {len(files_mod)} -> {files_mod}")
        return rc

    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
