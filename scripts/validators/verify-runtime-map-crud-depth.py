#!/usr/bin/env python3
"""Verify RUNTIME-MAP CRUD goal depth.

This catches a specific false-positive class: a UI CRUD/mutation goal is
marked READY because review opened a list page and asserted visible rows, but
the recorded goal_sequence never performed the mutation and never proved
persistence. /vg:test then replays the shallow list sequence and reports done.

For explicit mutation goals, runtime evidence must include:
  1. A POST/PUT/PATCH/DELETE network observation with 2xx/3xx status.
  2. A persistence probe proving the created/updated/deleted state survives
     refresh/re-read, or a documented persistence skip.

For CRUD UI goals backed by CRUD-SURFACES.md, RUNTIME-MAP must also contain a
per-goal goal_sequences[G-XX] entry. Group-level/static entries are not enough
input for /vg:test codegen.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Iterable

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, emit_and_exit, find_phase_dir, timer  # noqa: E402


REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
MUTATION_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
# Mutation verb vocabulary. Expanded by v2.45 fail-closed-validators PR after
# Phase 3.2 dogfood: G-10 "Admin clicks Approve", G-11 "Admin clicks Reject",
# G-23 "Admin resets cooling period", G-26 "Admin enables withdraw permission"
# all bypassed the depth gate because the verbs were not listed.
# When adding new verbs, prefer state-transition language (approve/reject/flag/
# reset/enable) over generic CRUD (create/update/delete) — admin actions
# rarely use plain CRUD wording.
MUTATION_WORD_RE = re.compile(
    r"\b("
    # Generic CRUD
    r"create|created|update|updated|delete|deleted|submit|submitted|"
    r"save|saved|edit|edited|remove|removed|add|added|insert|inserted|"
    # State-transition (admin actions, workflow gates)
    r"approve|approved|approving|reject|rejected|rejecting|"
    r"flag|flagged|flagging|unflag|unflagged|"
    r"enable|enabled|enabling|disable|disabled|disabling|"
    r"activate|activated|deactivate|deactivated|"
    r"reset|resetting|cancel|cancelled|cancelling|"
    r"archive|archived|restore|restored|publish|published|unpublish|"
    r"lock|locked|unlock|unlocked|freeze|frozen|unfreeze|unfrozen|"
    r"suspend|suspended|resume|resumed|"
    r"verify|verified|confirm|confirmed|deny|denied|"
    r"assign|assigned|unassign|unassigned|transfer|transferred|"
    r"upload|uploaded|download|downloaded|"
    # Vietnamese
    r"tao|cap\s*nhat|xoa|sua|luu|gui|"
    r"duyet|tu\s*choi|danh\s*dau|mo\s*khoa|khoa|"
    r"kich\s*hoat|vo\s*hieu|huy|chuyen"
    r")\b",
    re.IGNORECASE,
)
CRUD_WORD_RE = re.compile(
    r"\b(CRUD|list|table|row|rows|filter|filters|search|sort|pagination|"
    r"form|field|fields|detail|details|create|update|edit|delete|remove)\b",
    re.IGNORECASE,
)
EMPTY_FIELD_VALUES = {"", "none", "n/a", "na", "null", "-", "[]", "{}"}


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def _field(body: str, name: str) -> str:
    m = re.search(
        rf"^\*\*{re.escape(name)}:\*\*\s*(.+?)(?:\n\*\*|\n##|\Z)",
        body,
        re.MULTILINE | re.DOTALL,
    )
    return m.group(1).strip() if m else ""


def _meaningful(value: str) -> bool:
    compact = re.sub(r"\s+", " ", value.strip()).lower()
    return compact not in EMPTY_FIELD_VALUES and not compact.startswith(("none:", "n/a:", "na:"))


def _parse_goals(text: str) -> list[dict[str, Any]]:
    goals: list[dict[str, Any]] = []
    for match in re.finditer(
        r"^##\s+Goal\s+(G-[\w.-]+):?\s*(.*?)$"
        r"(?P<body>(?:(?!^##\s+Goal\s+).)*)",
        text,
        re.MULTILINE | re.DOTALL,
    ):
        gid = match.group(1)
        title = match.group(2).strip()
        body = match.group("body") or ""
        surface = _field(body, "Surface").split()[0].strip().lower() or "ui"
        mutation_evidence = _field(body, "Mutation evidence")
        persistence_check = _field(body, "Persistence check")
        combined = f"{title}\n{body}"
        explicit = _meaningful(mutation_evidence) or _meaningful(persistence_check)
        heuristic = bool(MUTATION_WORD_RE.search(combined))
        goals.append(
            {
                "id": gid,
                "title": title,
                "body": body,
                "surface": surface,
                "mutation_evidence": mutation_evidence,
                "persistence_check": persistence_check,
                "requires_mutation": surface in {"ui", "ui-mobile", ""} and (explicit or heuristic),
                "explicit": explicit,
            }
        )
    return goals


def _json_from_markdown(text: str) -> Any:
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    raw = fenced.group(1) if fenced else text
    return json.loads(raw)


def _crud_resource_names(phase_dir: Path) -> set[str]:
    path = phase_dir / "CRUD-SURFACES.md"
    if not path.exists():
        return set()
    try:
        data = _json_from_markdown(_read(path))
    except Exception:
        return set()
    resources = data.get("resources") if isinstance(data, dict) else None
    if not isinstance(resources, list):
        return set()
    names: set[str] = set()
    for resource in resources:
        if isinstance(resource, dict) and _meaningful(str(resource.get("name") or "")):
            names.add(str(resource["name"]).strip().lower())
    return names


def _requires_crud_sequence(goal: dict[str, Any], resource_names: set[str]) -> bool:
    if goal["requires_mutation"]:
        return True
    if goal["surface"] not in {"ui", "ui-mobile", ""} or not resource_names:
        return False
    combined = f"{goal['title']}\n{goal['body']}".lower()
    resource_hit = any(name and name in combined for name in resource_names)
    return resource_hit or bool(CRUD_WORD_RE.search(combined))


def _walk(value: Any) -> Iterable[Any]:
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _network_entries(seq: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for node in _walk(seq):
        if not isinstance(node, dict):
            continue
        network = node.get("network")
        if isinstance(network, list):
            entries.extend(x for x in network if isinstance(x, dict))
        elif isinstance(network, dict):
            entries.append(network)
    return entries


def _status_ok(status: Any) -> bool:
    try:
        code = int(status)
    except (TypeError, ValueError):
        return False
    return 200 <= code < 400


def _has_mutation_network(seq: dict[str, Any]) -> bool:
    for entry in _network_entries(seq):
        method = str(entry.get("method") or entry.get("verb") or "").upper()
        if method in MUTATION_METHODS and _status_ok(entry.get("status", entry.get("status_code"))):
            return True
    return False


def _has_persistence_proof(seq: dict[str, Any]) -> bool:
    for node in _walk(seq):
        if not isinstance(node, dict):
            continue
        probe = node.get("persistence_probe")
        if isinstance(probe, dict):
            if probe.get("persisted") is True:
                return True
            if probe.get("skipped") and _meaningful(str(probe.get("reason") or probe.get("skipped"))):
                return True
        if node.get("persisted") is True and (
            "persistence" in str(node.get("type", "")).lower()
            or "reload" in json.dumps(node, ensure_ascii=False).lower()
        ):
            return True
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify CRUD depth in RUNTIME-MAP goal sequences")
    parser.add_argument("--phase", required=True)
    parser.add_argument(
        "--allow-structural-fallback",
        action="store_true",
        help=(
            "Allow non-mutation CRUD UI goals without goal_sequences[G-XX] "
            "to be handled by /vg:test structural CRUD-SURFACES codegen. "
            "Mutation goals still require runtime sequence evidence."
        ),
    )
    args = parser.parse_args()

    out = Output(validator="runtime-map-crud-depth")
    with timer(out):
        phase_dir = find_phase_dir(args.phase)
        if phase_dir is None:
            out.add(Evidence(
                type="phase_not_found",
                message=f"Phase directory not found for {args.phase}",
                expected=".vg/phases/<phase>-*",
            ))
            emit_and_exit(out)

        goals_path = phase_dir / "TEST-GOALS.md"
        runtime_path = phase_dir / "RUNTIME-MAP.json"
        if not goals_path.exists() or not runtime_path.exists():
            emit_and_exit(out)

        goals = _parse_goals(_read(goals_path))
        crud_resources = _crud_resource_names(phase_dir)
        try:
            runtime = json.loads(_read(runtime_path))
        except json.JSONDecodeError as exc:
            out.add(Evidence(
                type="runtime_map_json_invalid",
                message=f"RUNTIME-MAP.json parse failed: {exc}",
                file=str(runtime_path),
            ))
            emit_and_exit(out)

        sequences = runtime.get("goal_sequences") or {}
        if not isinstance(sequences, dict):
            out.add(Evidence(
                type="runtime_map_goal_sequences_invalid",
                message="RUNTIME-MAP.json goal_sequences must be an object",
                file=str(runtime_path),
            ))
            emit_and_exit(out)

        for goal in goals:
            if not _requires_crud_sequence(goal, crud_resources):
                continue
            gid = goal["id"]
            seq = sequences.get(gid)
            if not isinstance(seq, dict):
                if (
                    args.allow_structural_fallback
                    and not goal["requires_mutation"]
                    and crud_resources
                ):
                    continue
                out.add(Evidence(
                    type="runtime_crud_sequence_missing",
                    message=f"{gid}: CRUD goal has no per-goal RUNTIME-MAP goal_sequence",
                    file=str(runtime_path),
                    expected=(
                        "goal_sequences.<goal>.steps; mutation goals additionally "
                        "need mutation + persistence evidence"
                    ),
                    actual=f"available_goal_sequences={', '.join(sorted(sequences.keys())[:8]) or '<none>'}",
                    fix_hint="Re-run /vg:review so the goal is replayed, not only listed.",
                ))
                continue
            if str(seq.get("result", "")).lower() not in {"passed", "pass", "ready"}:
                continue
            if not goal["requires_mutation"]:
                continue
            if not _has_mutation_network(seq):
                out.add(Evidence(
                    type="runtime_crud_no_mutation_network",
                    message=(
                        f"{gid}: mutation/CRUD goal is marked passed but sequence "
                        "contains no successful POST/PUT/PATCH/DELETE observation"
                    ),
                    file=str(runtime_path),
                    expected="Observed mutation network entry, e.g. POST /api/... status 201",
                    actual=f"steps={len(seq.get('steps') or [])}, network_entries={len(_network_entries(seq))}",
                    fix_hint="Review must execute the create/update/delete flow. A list-page assertion is not CRUD evidence.",
                ))
            elif not _has_persistence_proof(seq):
                out.add(Evidence(
                    type="runtime_crud_no_persistence_probe",
                    message=(
                        f"{gid}: mutation/CRUD goal has mutation network evidence "
                        "but no persistence probe"
                    ),
                    file=str(runtime_path),
                    expected="persistence_probe.persisted=true after refresh/re-read",
                    fix_hint="After mutation, reload/re-read/detail/list and record persistence_probe.persisted=true.",
                ))

    emit_and_exit(out)


if __name__ == "__main__":
    main()
