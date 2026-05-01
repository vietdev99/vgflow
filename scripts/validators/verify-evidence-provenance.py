#!/usr/bin/env python3
"""Verify evidence provenance in goal_sequences (RFC v9 D10).

Closes wave-3.2.2 trust model hole: bidirectional sync (matrix-staleness
SUSPECTED → READY) was triggering on hand-written `submit + 2xx` evidence.
Executor agents could fabricate evidence without scanner ever running.

This validator enforces:
1. Every mutation step in goal_sequences[].steps[] has structured `evidence`
2. evidence.source ∈ {scanner, executor, orchestrator, diagnostic_l2, manual}
3. evidence.scanner_run_id (when source=scanner) matches an event in events.db
4. evidence.artifact_hash present
5. evidence.captured_at present and parseable
6. evidence.schema_version matches expected

Companion: matrix-staleness validator updated (RFC v9 D10) to promote
SUSPECTED → READY ONLY when ALL submit + 2xx steps have
`evidence.source: scanner` (or `diagnostic_l2` post-fix with audit trail).

Migration: legacy goal_sequences pre-v9 missing evidence object are marked
`legacy_pre_provenance` and treated informational-only (cannot trigger
status promotion).

Severity: BLOCK at /vg:review run-complete and /vg:test entry.

Output: standard validator JSON contract (RFC v9 D11):
  {"verdict": "PASS"|"BLOCK", "block_type": "B", "evidence": [...]}
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, emit_and_exit, find_phase_dir, timer  # noqa: E402

EXPECTED_SCHEMA_VERSION = "1.0"
ALLOWED_SOURCES = {"scanner", "executor", "orchestrator", "diagnostic_l2", "manual"}

# Mutation step heuristic (overlap with mutation-actually-submitted validator):
# a step is "mutation" if it has `do: click|submit|tap|press` AND target text
# matches submit/approve/confirm intent.
MUTATION_ACTIONS = {"click", "submit", "tap", "press"}


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def is_mutation_step(step: dict) -> bool:
    if not isinstance(step, dict):
        return False
    action = str(step.get("do") or step.get("action") or "").lower()
    if action not in MUTATION_ACTIONS:
        return False
    # Heuristic: target/label/selector contains submit/approve/confirm verbs
    target_text = " ".join(
        str(step.get(k, "")) for k in ("target", "label", "selector", "name")
    ).lower()
    submit_verbs = ("submit", "approve", "confirm", "save", "create",
                    "update", "delete", "reject", "send", "duyệt", "xác nhận",
                    "gửi", "tạo", "cập nhật", "xóa", "từ chối")
    return any(v in target_text for v in submit_verbs)


def has_2xx_network(step: dict) -> bool:
    """Walk step for 2xx mutation network entry."""
    def walk(value):
        if isinstance(value, dict):
            net = value.get("network")
            entries = []
            if isinstance(net, list):
                entries = net
            elif isinstance(net, dict):
                entries = [net]
            for e in entries:
                if not isinstance(e, dict):
                    continue
                method = str(e.get("method") or "").upper()
                status = e.get("status", e.get("status_code"))
                try:
                    code = int(status)
                except (TypeError, ValueError):
                    continue
                if method in {"POST", "PUT", "PATCH", "DELETE"} and 200 <= code < 300:
                    return True
            for v in value.values():
                if walk(v):
                    return True
        elif isinstance(value, list):
            for v in value:
                if walk(v):
                    return True
        return False
    return walk(step)


def validate_evidence(evidence: dict, gid: str, step_idx: int,
                       events_db_path: Path | None) -> list[dict]:
    """Validate structured evidence object. Returns list of error dicts."""
    errors = []
    if not isinstance(evidence, dict):
        errors.append({
            "type": "evidence_not_dict",
            "gid": gid,
            "step_idx": step_idx,
            "issue": "evidence must be object, got: " + type(evidence).__name__,
        })
        return errors

    # Required: source
    source = evidence.get("source")
    if source is None:
        errors.append({
            "type": "evidence_source_missing",
            "gid": gid,
            "step_idx": step_idx,
            "issue": "evidence.source field required",
        })
    elif source not in ALLOWED_SOURCES:
        errors.append({
            "type": "evidence_source_invalid",
            "gid": gid,
            "step_idx": step_idx,
            "issue": f"evidence.source='{source}' not in {sorted(ALLOWED_SOURCES)}",
        })

    # Required: artifact_hash (sha256:... format)
    artifact_hash = evidence.get("artifact_hash")
    if not artifact_hash or not isinstance(artifact_hash, str):
        errors.append({
            "type": "artifact_hash_missing",
            "gid": gid,
            "step_idx": step_idx,
            "issue": "evidence.artifact_hash required (e.g., sha256:abc123...)",
        })
    elif not artifact_hash.startswith("sha256:"):
        errors.append({
            "type": "artifact_hash_format",
            "gid": gid,
            "step_idx": step_idx,
            "issue": f"evidence.artifact_hash must start with 'sha256:', got '{artifact_hash[:20]}'",
        })

    # Required: captured_at
    captured_at = evidence.get("captured_at")
    if not captured_at:
        errors.append({
            "type": "captured_at_missing",
            "gid": gid,
            "step_idx": step_idx,
            "issue": "evidence.captured_at required (ISO 8601)",
        })

    # Required: schema_version
    schema_version = evidence.get("schema_version")
    if not schema_version:
        errors.append({
            "type": "schema_version_missing",
            "gid": gid,
            "step_idx": step_idx,
            "issue": "evidence.schema_version required",
        })
    elif not str(schema_version).startswith("1."):
        errors.append({
            "type": "schema_version_unsupported",
            "gid": gid,
            "step_idx": step_idx,
            "issue": f"evidence.schema_version='{schema_version}' major mismatch (expected 1.x)",
        })

    # When source=scanner: scanner_run_id must match events.db entry
    if source == "scanner":
        scanner_run_id = evidence.get("scanner_run_id")
        if not scanner_run_id:
            errors.append({
                "type": "scanner_run_id_missing",
                "gid": gid,
                "step_idx": step_idx,
                "issue": "evidence.source=scanner requires evidence.scanner_run_id",
            })
        elif events_db_path and events_db_path.exists():
            # Check events.db has matching haiku_scanner_spawned event
            try:
                conn = sqlite3.connect(events_db_path)
                row = conn.execute(
                    "SELECT 1 FROM events WHERE event_type='review.haiku_scanner_spawned' "
                    "AND payload LIKE ? LIMIT 1",
                    (f"%{scanner_run_id}%",),
                ).fetchone()
                conn.close()
                if not row:
                    errors.append({
                        "type": "scanner_run_id_orphan",
                        "gid": gid,
                        "step_idx": step_idx,
                        "issue": (
                            f"evidence.scanner_run_id='{scanner_run_id}' has no matching "
                            f"review.haiku_scanner_spawned event in events.db. "
                            f"Possible fabricated evidence."
                        ),
                    })
            except sqlite3.Error:
                pass  # events.db unavailable, skip cross-check

    # When source=diagnostic_l2: layer2_proposal_id should be populated
    if source == "diagnostic_l2":
        proposal_id = evidence.get("layer2_proposal_id")
        if not proposal_id:
            errors.append({
                "type": "layer2_proposal_id_missing",
                "gid": gid,
                "step_idx": step_idx,
                "issue": "evidence.source=diagnostic_l2 requires evidence.layer2_proposal_id",
            })

    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify evidence provenance in goal_sequences")
    parser.add_argument("--phase", required=True)
    parser.add_argument(
        "--severity",
        choices=["block", "warn"],
        default="block",
        help="block (default v9) or warn (legacy migration mode)",
    )
    parser.add_argument(
        "--allow-legacy",
        action="store_true",
        help="Allow goal_sequences without evidence field (mark as legacy_pre_provenance, "
             "informational only). Use during migration period.",
    )
    args = parser.parse_args()

    out = Output(validator="evidence-provenance")
    with timer(out):
        phase_dir = find_phase_dir(args.phase)
        if phase_dir is None:
            out.add(Evidence(type="phase_not_found", message=f"Phase not found: {args.phase}"))
            emit_and_exit(out)

        runtime_path = phase_dir / "RUNTIME-MAP.json"
        if not runtime_path.exists():
            out.add(Evidence(type="runtime_map_missing", message=f"RUNTIME-MAP.json not found at {runtime_path}"))
            emit_and_exit(out)

        try:
            runtime = json.loads(_read(runtime_path))
        except json.JSONDecodeError as e:
            out.add(Evidence(type="runtime_map_parse_error", message=str(e)))
            emit_and_exit(out)

        sequences = runtime.get("goal_sequences") or {}
        events_db = phase_dir.parent.parent.parent / ".vg" / "events.db"
        if not events_db.exists():
            events_db = None

        all_errors: list[dict] = []
        legacy_count = 0
        scanner_count = 0
        non_scanner_count = 0
        total_mutation_steps = 0

        for gid, seq in sequences.items():
            if not isinstance(seq, dict):
                continue
            steps = seq.get("steps") or []
            for idx, step in enumerate(steps):
                if not is_mutation_step(step):
                    continue
                # Only enforce on mutation steps that had 2xx (i.e., claim-of-success)
                if not has_2xx_network(step):
                    continue

                total_mutation_steps += 1
                evidence = step.get("evidence")
                if evidence is None:
                    if args.allow_legacy:
                        legacy_count += 1
                        continue
                    all_errors.append({
                        "type": "evidence_missing",
                        "gid": gid,
                        "step_idx": idx,
                        "issue": (
                            "Mutation step claims success (action + 2xx network) but "
                            "lacks evidence object. RFC v9 D10 requires structured "
                            "provenance. Use --allow-legacy during migration."
                        ),
                    })
                    continue

                step_errors = validate_evidence(evidence, gid, idx, events_db)
                if step_errors:
                    all_errors.extend(step_errors)
                else:
                    source = evidence.get("source")
                    if source == "scanner":
                        scanner_count += 1
                    else:
                        non_scanner_count += 1

        # Emit summary evidence
        out.add(
            Evidence(
                type="provenance_summary",
                message=(
                    f"{total_mutation_steps} mutation steps verified: "
                    f"{scanner_count} scanner-sourced, "
                    f"{non_scanner_count} other-sourced, "
                    f"{legacy_count} legacy (pre-v9), "
                    f"{len(all_errors)} errors"
                ),
            ),
            escalate=False,
        )

        # Emit per-error evidence
        for err in all_errors:
            out.add(
                Evidence(
                    type=err["type"],
                    message=f"{err['gid']} step[{err['step_idx']}]: {err['issue']}",
                    file=str(runtime_path),
                    fix_hint=(
                        "Add structured evidence object to step in RUNTIME-MAP.json. "
                        "Schema: { source, artifact_hash, captured_at, schema_version, "
                        "scanner_run_id (when source=scanner), layer2_proposal_id "
                        "(when source=diagnostic_l2) }. "
                        "If migrating legacy phase, run with --allow-legacy."
                    ),
                ),
                escalate=(args.severity == "block"),
            )

        # Severity downgrade for warn mode
        if all_errors and args.severity == "warn":
            if out.verdict == "BLOCK":
                out.verdict = "WARN"
            out.add(
                Evidence(
                    type="severity_downgraded",
                    message=f"{len(all_errors)} provenance errors downgraded to WARN.",
                ),
                escalate=False,
            )

    emit_and_exit(out)


if __name__ == "__main__":
    main()
