#!/usr/bin/env python3
"""Generate closed-loop lifecycle specs from existing phase artifacts.

This is the deterministic counterpart to the lifecycle-depth gate. It turns
TEST-GOALS, API hints, and phase docs into a LIFECYCLE-SPECS.json contract that
/vg:test codegen can consume before writing Playwright specs.

The generator is intentionally conservative:
- it only emits goals that look side-effecting/multi-actor by default;
- it never claims runtime proof;
- each emitted goal gets a full R-C-R-U-R-D-R skeleton, fixture DAG, actors,
  artifact capture when text implies tokens/email/webhooks, and cleanup.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# F6 Batch 12: shared phase_pad util (replaces hardcoded zfill(2))
sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from phase_pad import phase_pad  # noqa: E402

REQUIRED_STAGES = (
    "read_before",
    "create",
    "read_after_create",
    "update",
    "read_after_update",
    "delete",
    "read_after_delete",
)

# G2 Batch 2: per-verb stage derivation — shorten lifecycle for non-full-CRUD goals.
GOAL_TYPE_STAGES: dict[str, tuple[str, ...]] = {
    "create-only": ("read_before", "create", "read_after_create"),
    "update-only": ("read_before", "update", "read_after_update"),
    "delete-only": ("read_before", "delete", "read_after_delete"),
    "read-only":   ("read_before",),  # G14 covered separately
}


def _stages_for_goal(goal: dict[str, Any]) -> tuple[str, ...]:
    """Derive lifecycle stages per goal_type. Default RCRURDR for full mutation."""
    gtype = (goal.get("goal_type") or "").strip().lower()
    # Explicit goal_type mapping takes priority
    if gtype in GOAL_TYPE_STAGES:
        return GOAL_TYPE_STAGES[gtype]
    # Non-empty but unrecognised goal_type (e.g. multi-actor, wizard) → full RCRURDR
    # so existing tests and behaviours are not broken by unrecognised types.
    if gtype:
        return REQUIRED_STAGES
    # goal_type absent — infer from HTTP verb hints in mutation_evidence
    evidence = " ".join(
        str(goal.get(k) or "")
        for k in ("mutation_evidence", "persistence_check", "title")
    ).upper()
    has_post = "POST " in evidence or " POST" in evidence
    has_put_patch = "PUT " in evidence or "PATCH " in evidence
    has_del = "DELETE " in evidence
    if has_post and not has_put_patch and not has_del:
        return GOAL_TYPE_STAGES["create-only"]
    if has_del and not has_post and not has_put_patch:
        return GOAL_TYPE_STAGES["delete-only"]
    if has_put_patch and not has_post and not has_del:
        return GOAL_TYPE_STAGES["update-only"]
    return REQUIRED_STAGES


SIDE_EFFECT_WORD_RE = re.compile(
    r"\b("
    r"create|created|update|updated|delete|deleted|patch|post|put|"
    r"submit|submitted|save|saved|edit|edited|remove|removed|add|added|"
    r"invite|invited|accept|accepted|register|login|logout|verify|verified|"
    r"refresh|revoke|revoked|pay|payment|refund|withdraw|transfer|sync|"
    r"upload|approve|approved|reject|rejected|enable|enabled|disable|"
    r"disabled|activate|deactivate|cancel|cancelled|archive|restore|"
    r"crud|rcrurd|rcrurdr|wizard|duplicate|mark|assign|unassign|"
    r"token|2fa|otp|webauthn|oauth|webhook|polling|queue|worker"
    r")\b",
    re.IGNORECASE,
)

ARTIFACT_WORD_RE = re.compile(
    r"\b("
    r"email|mail|token|magic\s+link|websocket|ws|realtime|real-time|"
    r"notification|callback|webhook|invite|invitation|otp|2fa|webauthn|"
    r"oauth|hmac|queue|dlq|cron|polling|artifact"
    r")\b",
    re.IGNORECASE,
)

MULTI_ACTOR_WORD_RE = re.compile(
    r"\b("
    r"multi[-\s]?actor|owner|invitee|inviter|admin|approver|reviewer|"
    r"collaborator|operator|manager|member|second\s+user|another\s+user|"
    r"role\s+switch|impersonat|oauth|external\s+system"
    r")\b",
    re.IGNORECASE,
)

ENDPOINT_RE = re.compile(
    r"\b(GET|POST|PUT|PATCH|DELETE|OPTIONS)\s+(/[A-Za-z0-9_./:{}?&=%-]+)"
)

ENDPOINT_HEADER_RE = re.compile(
    r"^#{2,4}\s+(GET|POST|PUT|PATCH|DELETE)\s+(/\S+)\s*$",
    re.MULTILINE,
)

EMPTY_VALUES = {"", "none", "n/a", "na", "null", "-", "[]", "{}"}


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def _meaningful(value: Any) -> bool:
    if value is None:
        return False
    text = re.sub(r"\s+", " ", str(value).strip()).lower()
    return text not in EMPTY_VALUES and not text.startswith(("none", "n/a", "na"))


def _field(body: str, name: str) -> str:
    patterns = (
        rf"^\*\*{re.escape(name)}:\*\*\s*(.+?)(?=^\*\*|\n##|\n#\s+G-|\Z)",
        rf"^{re.escape(name)}:\s*(.+?)(?=^\w[\w -]*:|\n##|\n#\s+G-|\Z)",
        rf"^###\s+{re.escape(name)}\s*\n(.+?)(?=^###\s+|\n##\s+|\n#\s+|\Z)",
    )
    for pattern in patterns:
        match = re.search(pattern, body, re.MULTILINE | re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return ""


def _parse_goal_block(text: str, source: Path) -> dict[str, Any] | None:
    heading = re.search(r"^#\s+(G-[\w.-]+):?\s*(.+)$", text, re.MULTILINE)
    if not heading:
        heading = re.search(
            r"^##\s+(?:Goal\s+)?(G-[\w.-]+):?\s*(.+)$",
            text,
            re.MULTILINE,
        )
    if not heading:
        return None
    goal_id = heading.group(1).strip()
    title = heading.group(2).strip()
    return {
        "id": goal_id,
        "title": title,
        "body": text,
        "goal_type": _field(text, "goal_type").lower(),
        "goal_class": _field(text, "goal_class").lower(),
        "surface": _field(text, "Surface").lower(),
        "priority": _field(text, "Priority").lower(),
        "success_criteria": _field(text, "Success criteria"),
        "mutation_evidence": _field(text, "Mutation evidence"),
        "persistence_check": _field(text, "Persistence check"),
        "dependencies": _field(text, "Dependencies"),
        "infra_deps": _field(text, "Infra deps"),
        # G4: explicit actors metadata
        "actors": _field(text, "actors") or _field(text, "actor"),
        # G6: artifact_kind field
        "artifact_kind": _field(text, "artifact_kind"),
        "source": str(source),
    }


def _parse_goals(phase_dir: Path) -> list[dict[str, Any]]:
    split_dir = phase_dir / "TEST-GOALS"
    goals: list[dict[str, Any]] = []
    if split_dir.is_dir():
        for path in sorted(split_dir.glob("G-*.md")):
            goal = _parse_goal_block(_read(path), path)
            if goal:
                goals.append(goal)
    if goals:
        return goals

    text = _read(phase_dir / "TEST-GOALS.md")
    pattern = re.compile(
        r"^##\s+(?:Goal\s+)?(G-[\w.-]+):?\s*(.*?)$"
        r"(?P<body>(?:(?!^##\s+(?:Goal\s+)?G-[\w.-]+).)*)",
        re.MULTILINE | re.DOTALL,
    )
    for match in pattern.finditer(text):
        body = f"## Goal {match.group(1)}: {match.group(2)}\n{match.group('body') or ''}"
        goal = _parse_goal_block(body, phase_dir / "TEST-GOALS.md")
        if goal:
            goals.append(goal)
    return goals


def _combined(goal: dict[str, Any]) -> str:
    return "\n".join(str(goal.get(k, "")) for k in (
        "title",
        "body",
        "goal_type",
        "goal_class",
        "surface",
        "success_criteria",
        "mutation_evidence",
        "persistence_check",
        "dependencies",
        "infra_deps",
    ))


def _needs_lifecycle(goal: dict[str, Any]) -> bool:
    goal_type = str(goal.get("goal_type") or "").lower()
    goal_class = str(goal.get("goal_class") or "").lower()
    if goal_type in {"mutation", "multi-actor", "workflow"}:
        return True
    # G14 Batch 2: read-only goals get lifecycle too (single read_before stage).
    if goal_type == "read-only":
        return True
    if goal_class in {"mutation", "crud", "workflow", "multi-actor"}:
        return True
    if _meaningful(goal.get("mutation_evidence")) or _meaningful(goal.get("persistence_check")):
        return True
    return bool(SIDE_EFFECT_WORD_RE.search(_combined(goal)))


def _needs_artifact_capture(goal: dict[str, Any]) -> bool:
    return bool(ARTIFACT_WORD_RE.search(_combined(goal)))


def _is_multi_actor(goal: dict[str, Any]) -> bool:
    return bool(MULTI_ACTOR_WORD_RE.search(_combined(goal)))


def _extract_endpoints(goal: dict[str, Any]) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    endpoints: list[dict[str, str]] = []
    for method, path in ENDPOINT_RE.findall(_combined(goal)):
        key = (method.upper(), path)
        if key in seen:
            continue
        seen.add(key)
        endpoints.append({"method": method.upper(), "path": path})
    return endpoints


APPROVER_WORDS = re.compile(r"\b(approve|approver|admin|reviewer|review|moderate|gatekeep)\b", re.IGNORECASE)
INVITEE_WORDS = re.compile(r"\b(invitee|invited|accept|collaborator|guest|member)\b", re.IGNORECASE)


def _infer_actors(goal: dict[str, Any]) -> list[dict[str, Any]]:
    text = _combined(goal).lower()
    actors: list[dict[str, Any]] = []

    def add(actor_id: str, role: str, session: str) -> None:
        if not any(actor["id"] == actor_id for actor in actors):
            actors.append({
                "id": actor_id,
                "role": role,
                "session": session,
                "permissions": [f"least privilege required for {role} path"],
            })

    if "admin" in text:
        add("admin", "admin", "admin_session")
    if "owner" in text:
        add("owner_actor", "resource_owner", "owner_session")
    if INVITEE_WORDS.search(text):
        add("invitee", "invitee", "invitee_session")
    if "approver" in text or "approve" in text:
        add("approver", "approver", "approver_session")
    if "reviewer" in text or "review" in text:
        add("reviewer", "reviewer", "reviewer_session")
    if any(word in text for word in ("collaborator", "member")):
        add("secondary_actor", "secondary_user", "secondary_session")
    if "external system" in text or "oauth" in text or "webhook" in text:
        add("external_actor", "external_system_or_webhook", "signed_callback_context")

    if not actors:
        add("system_actor", "system", "authenticated or service context required by TEST-GOALS")
    elif _is_multi_actor(goal) and len(actors) == 1:
        add("secondary_actor", "secondary_user_or_external_system", "secondary_session")
    return actors


# G1 Batch 4: preconditions from goal data
_PRECOND_BOILERPLATE = [
    "Use unique test-owned identifiers; never mutate shared production-like fixtures.",
    "Start from a clean actor/session context.",
    "Capture request_id/correlation id for every mutation.",
    "Assert canonical response envelope and error shape.",
]


def _preconditions(goal: dict[str, Any]) -> list[str]:
    """Build preconditions list from goal.dependencies + infra_deps. Fallback to boilerplate."""
    deps = goal.get("dependencies") or ""
    infra = goal.get("infra_deps") or ""
    items: list[str] = []
    if deps:
        for d in (deps if isinstance(deps, list) else [s.strip() for s in str(deps).replace("\n", ",").split(",")]):
            if d and d.lower() not in ("none", "n/a"):
                items.append(f"Dependency: {d}")
    if infra:
        for d in (infra if isinstance(infra, list) else [s.strip() for s in str(infra).replace("\n", ",").split(",")]):
            if d:
                items.append(f"Infrastructure: {d} available")
    return items or list(_PRECOND_BOILERPLATE)


# G4 Batch 4: actor inference reads explicit metadata first
ACTOR_METADATA_KEYS = ("actors", "actor")


def _infer_actors_v2(goal: dict[str, Any]) -> list[dict[str, Any]]:
    """Read explicit actors metadata first; fall back to word-match heuristic."""
    explicit = None
    for k in ACTOR_METADATA_KEYS:
        v = goal.get(k)
        if v:
            explicit = v
            break
    if explicit:
        # parse comma-separated list or list-of-strings
        if isinstance(explicit, list):
            items = [str(x).strip() for x in explicit if str(x).strip()]
        else:
            items = [s.strip() for s in str(explicit).split(",") if s.strip()]
        actors = []
        seen: set[str] = set()
        for item in items:
            aid = item.lower().replace(" ", "_")
            if aid in seen:
                continue
            seen.add(aid)
            actors.append({"id": aid, "role": item, "session": f"{aid}_session",
                           "permissions": [f"least privilege required for {item} path"]})
        if actors:
            return actors
    # Fallback to existing _infer_actors() word-match
    return _infer_actors(goal)


# G5 Batch 4: root-level fixture DAG from goal.dependencies cross-references
def _root_fixture_dag(goals_meta: list[dict[str, Any]]) -> dict[str, Any]:
    """Build fixture DAG from goal.dependencies field referencing other goal IDs."""
    nodes = []
    edges = []
    for g in goals_meta:
        gid = g.get("id") or g.get("goal_id")
        if not gid:
            continue
        nodes.append({"id": gid, "kind": g.get("goal_type", "mutation")})
        deps = g.get("dependencies") or ""
        deps_text = deps if isinstance(deps, str) else " ".join(str(d) for d in deps)
        for m in re.finditer(r"\b(G-\d+)\b", deps_text):
            ref = m.group(1)
            if ref != gid:
                edges.append({"from": gid, "to": ref})
    return {"nodes": nodes, "edges": edges}


# G6 Batch 4: artifact_capture from goal.artifact_kind
def _artifact_capture_v2(goal: dict[str, Any]) -> list[dict[str, Any]]:
    """Build artifact_capture entries reflecting goal.artifact_kind."""
    kind = (goal.get("artifact_kind") or "").strip().lower()
    if not kind:
        # Fallback: use existing logic based on artifact word detection
        if not _needs_artifact_capture(goal):
            return []
        return [
            {
                "id": "runtime_artifact",
                "source": "API/browser response, email inbox, webhook sink, queue event, token store, or notification list named in TEST-GOALS",
                "identifier": "request id, resource id, message id, token hash, event id, timestamp, or screenshot filename",
                "consumer_step": "read_after_create/read_after_update/read_after_delete",
            }
        ]
    # Specific captures by kind
    if "csv" in kind or "download" in kind:
        return [{"kind": kind, "ref": "${PHASE_DIR}/.captures/${GOAL_ID}.csv",
                 "artifact_kind": kind}]
    if "pdf" in kind:
        return [{"kind": kind, "ref": "${PHASE_DIR}/.captures/${GOAL_ID}.pdf",
                 "artifact_kind": kind}]
    if "image" in kind or "screenshot" in kind:
        return [{"kind": kind, "ref": "${PHASE_DIR}/.captures/${GOAL_ID}.png",
                 "artifact_kind": kind}]
    if "json" in kind:
        return [{"kind": kind, "ref": "${PHASE_DIR}/.captures/${GOAL_ID}.json",
                 "artifact_kind": kind}]
    return [{"kind": kind, "ref": f"${{PHASE_DIR}}/.captures/${{GOAL_ID}}.{kind}",
             "artifact_kind": kind}]


def _stage_actor(stage: str, goal: dict[str, Any], actors: list[dict[str, Any]]) -> str:
    """Resolve which actor performs this stage.

    Heuristic:
    - Single actor → that actor for all stages.
    - update/read_after_update + 'admin'/'approver' words in goal → admin/approver actor.
    - read_after_create/read_after_update + 'invitee'/'accept' words → invitee actor.
    - Default → actors[0].
    """
    if not actors:
        return "primary"
    if len(actors) == 1:
        return actors[0]["id"]
    haystack = _combined(goal)
    if stage in {"update", "read_after_update"} and APPROVER_WORDS.search(haystack):
        # Find admin/approver actor
        for a in actors:
            if a["id"] in {"admin", "approver", "reviewer"}:
                return a["id"]
    if stage in {"read_after_create"} and INVITEE_WORDS.search(haystack):
        for a in actors:
            if a["id"] in {"invitee", "collaborator", "member"}:
                return a["id"]
    return actors[0]["id"]


def _fixture_dag(goal: dict[str, Any], actors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fixtures = [
        {
            "id": f"{actor['id']}_session",
            "kind": "auth_or_service_context",
            "depends_on": [],
            "cleanup": "revoke session/token or clear service fixture if created by test",
        }
        for actor in actors
    ]
    fixtures.append({
        "id": "owned_resource",
        "kind": "resource_or_state_under_test",
        "depends_on": [fixtures[0]["id"]] if fixtures else [],
        "cleanup": "delete/deactivate/cancel/rollback or restore original state",
    })
    if _meaningful(goal.get("dependencies")):
        fixtures.append({
            "id": "cross_phase_dependencies",
            "kind": "seeded dependencies named in TEST-GOALS",
            "depends_on": [fixtures[0]["id"]] if fixtures else [],
            "cleanup": "leave shared seed intact; cleanup only test-owned children",
        })
    if _needs_artifact_capture(goal):
        fixtures.append({
            "id": "artifact_sink",
            "kind": "mailbox/webhook/queue/token capture fixture",
            "depends_on": [fixtures[0]["id"]] if fixtures else [],
            "cleanup": "clear captured artifacts owned by this test run",
        })
    return fixtures


DECISION_HEADER_RE = re.compile(
    r"^#{2,3}\s+(D-[\w.-]+):?\s*(.+?)\s*$",
    re.MULTILINE,
)
DECISION_FIELD_RE = re.compile(
    r"^\*\*expected_assertion:\*\*\s*(.+?)(?=^\*\*|\n##|\n#\s+D-|\Z)",
    re.MULTILINE | re.DOTALL,
)
DECISION_REF_RE = re.compile(r"\b(D-[\w.-]+)\b")


def _parse_context_decisions(phase_dir: Path) -> dict[str, dict[str, str]]:
    """Parse CONTEXT.md → {D-ID: {title, expected_assertion}}."""
    ctx_path = phase_dir / "CONTEXT.md"
    if not ctx_path.is_file():
        return {}
    text = _read(ctx_path)
    decisions: dict[str, dict[str, str]] = {}
    matches = list(DECISION_HEADER_RE.finditer(text))
    for i, m in enumerate(matches):
        d_id = m.group(1)
        title = m.group(2).strip()
        # Body = text from end of this header to next header or end
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end]
        assertion_match = DECISION_FIELD_RE.search(body)
        decisions[d_id] = {
            "title": title,
            "expected_assertion": assertion_match.group(1).strip() if assertion_match else "",
        }
    return decisions


def _goal_decision_refs(goal: dict[str, Any], decisions: dict[str, dict[str, str]]) -> list[str]:
    """Extract D-XX refs from goal text — match against parsed decisions."""
    if not decisions:
        return []
    haystack = _combined(goal)
    found: set[str] = set()
    for m in DECISION_REF_RE.finditer(haystack):
        d_id = m.group(1)
        if d_id in decisions:
            found.add(d_id)
    return sorted(found)


def _parse_api_contracts(phase_dir: Path) -> list[dict[str, str]]:
    """Parse API-CONTRACTS.md → list of {method, path} dicts."""
    contracts_path = phase_dir / "API-CONTRACTS.md"
    if not contracts_path.is_file():
        return []
    text = _read(contracts_path)
    return [
        {"method": m.group(1), "path": m.group(2)}
        for m in ENDPOINT_HEADER_RE.finditer(text)
    ]


def _bind_endpoint(stage: str, goal: dict[str, Any], contracts: list[dict[str, str]]) -> dict[str, str] | None:
    """Match stage to a contract endpoint via heuristic on stage verb + goal text."""
    if not contracts:
        return None
    verb_map: dict[str, tuple[str, ...]] = {
        "create": ("POST",),
        "read_before": ("GET",),
        "read_after_create": ("GET",),
        "update": ("PUT", "PATCH"),
        "read_after_update": ("GET",),
        "delete": ("DELETE",),
        "read_after_delete": ("GET",),
    }
    candidates_methods = verb_map.get(stage, ())
    if not candidates_methods:
        return None
    # First: try match in mutation_evidence + dependencies + persistence_check text
    haystack = " ".join(str(goal.get(k) or "") for k in
                        ("mutation_evidence", "persistence_check", "dependencies", "title"))
    for c in contracts:
        if c["method"] in candidates_methods and c["path"] in haystack:
            return {"method": c["method"], "path": c["path"]}
    # Fallback: first contract entry whose method matches
    for c in contracts:
        if c["method"] in candidates_methods:
            return {"method": c["method"], "path": c["path"]}
    return None


def _read_before_action(goal: dict[str, Any]) -> str:
    """Build read_before action description. Special-case read-only goals (G14)."""
    gtype = (goal.get("goal_type") or "").strip().lower()
    if gtype == "read-only":
        pc = goal.get("persistence_check") or ""
        return f"Execute read endpoint and assert filter/result semantics: {pc}"
    return "Read baseline via read endpoint or DB query from TEST-GOALS; assert target entity absent or initial state matches precondition."


# G3 Batch 3: step description built from endpoint binding
_DEFAULT_DESCRIPTIONS: dict[str, str] = {
    "read_before": "Read baseline via read endpoint or DB query from TEST-GOALS; assert target entity absent or initial state matches precondition.",
    "create": "Execute primary API/UI action from TEST-GOALS; capture mutation evidence.",
    "read_after_create": "Re-read from a fresh request/session; assert create effect persisted.",
    "update": "Mutate the created resource again, exercise status transition, retry/idempotency, role switch, or configured update path.",
    "read_after_update": "Re-read from a clean context and assert updated fields, derived state, events, permissions, or view state.",
    "delete": "Cleanup by delete, revoke, cancel, deactivate, rollback fixture, or restore original view/config state.",
    "read_after_delete": "Re-read active list/detail and assert no active test-owned resource remains; audit row may remain if required.",
}


def _step_description(stage: str, goal: dict[str, Any], endpoint: dict[str, str] | None) -> str:
    """G3 Batch 3: build action description from endpoint binding when available.

    When endpoint is bound, embed method + path directly in the description so
    codegen has concrete references instead of generic template strings.
    Falls back to _DEFAULT_DESCRIPTIONS[stage] when endpoint is absent.
    """
    if endpoint and endpoint.get("method") and endpoint.get("path"):
        method, path = endpoint["method"], endpoint["path"]
        if stage == "create":
            return f"{method} {path} with sample payload from API-CONTRACTS; assert response status + body."
        if stage == "update":
            return f"{method} {path} for the created entity; assert update applied."
        if stage == "delete":
            return f"{method} {path}; assert 204/200 and resource gone."
        if stage.startswith("read_"):
            state = stage.replace("read_", "").replace("_", " ")
            return f"GET {path}; assert {state} state per persistence_check."
    return _DEFAULT_DESCRIPTIONS.get(stage, f"Execute {stage} stage.")


def _step(
    stage: str,
    goal: dict[str, Any],
    actor_id: str,
    contracts: list[dict[str, str]] | None = None,
    decisions: dict[str, dict[str, str]] | None = None,
    decision_refs: list[str] | None = None,
) -> dict[str, Any]:
    title = goal["title"]
    mutation_evidence = goal.get("mutation_evidence") or "created resource id, state transition, response envelope, or emitted event from TEST-GOALS"
    persistence = goal.get("persistence_check") or "fresh read must prove persisted state, derived state, permissions, and absence of stale cached data"
    criteria = goal.get("success_criteria") or title
    actions = {
        "read_before": _read_before_action(goal),
        "create": f"Execute primary API/UI action from TEST-GOALS; capture mutation evidence: {mutation_evidence}",
        "read_after_create": f"Re-read from a fresh request/session; assert create effect persisted. Persistence check: {persistence}",
        "update": "Mutate the created resource again, exercise status transition, retry/idempotency, role switch, or configured update path.",
        "read_after_update": f"Re-read from a clean context and assert updated fields, derived state, events, permissions, or view state. Re-apply goal assertions: {criteria}",
        "delete": "Cleanup by delete, revoke, cancel, deactivate, rollback fixture, or restore original view/config state.",
        "read_after_delete": "Re-read active list/detail and assert no active test-owned resource remains; audit row may remain if required.",
    }
    evidence = {
        "read_before": ["response envelope", "DB/query snapshot", "no stale fixture collision"],
        "create": ["2xx response or expected 4xx", "correlation/request id", "created resource id or emitted event id"],
        "read_after_create": ["fresh read response", "DB persisted fields", "audit/outbox row when applicable"],
        "update": ["2xx/expected 4xx response", "version/idempotency behavior", "actor authorization result"],
        "read_after_update": ["fresh read response", "event/webhook/queue capture when applicable", "no cross-tenant leakage"],
        "delete": ["cleanup mutation response or fixture cleanup receipt", "audit reason", "session/job/resource cleanup marker"],
        "read_after_delete": ["404/empty active list or terminal status", "revoked sessions/jobs", "cleanup confirmation"],
    }
    endpoint = _bind_endpoint(stage, goal, contracts or [])
    # G3 Batch 3: override action description with endpoint-binding when available
    if endpoint:
        actions[stage] = _step_description(stage, goal, endpoint)
    # Build assertions from decision_refs + API-CONTRACTS
    assertions: list[dict[str, str]] = []
    if stage in {"create", "update"}:
        for d_id in (decision_refs or []):
            d_data = (decisions or {}).get(d_id, {})
            ea = d_data.get("expected_assertion", "").strip()
            if ea:
                assertions.append({"source": d_id, "check": ea})
    if endpoint:
        assertions.append({
            "source": "API-CONTRACTS",
            "check": f"{endpoint['method']} {endpoint['path']} returns expected envelope and status",
        })
    return {
        "name": stage,
        "stage": stage,
        "actor": actor_id,
        "endpoint": endpoint,
        "assertions": assertions,
        "action": actions[stage],
        "evidence": evidence[stage],
    }


def _artifact_capture(goal: dict[str, Any]) -> list[dict[str, str]]:
    if not _needs_artifact_capture(goal):
        return []
    return [
        {
            "id": "runtime_artifact",
            "source": "API/browser response, email inbox, webhook sink, queue event, token store, or notification list named in TEST-GOALS",
            "identifier": "request id, resource id, message id, token hash, event id, timestamp, or screenshot filename",
            "consumer_step": "read_after_create/read_after_update/read_after_delete",
        }
    ]


def _goal_spec(
    goal: dict[str, Any],
    contracts: list[dict[str, str]] | None = None,
    decisions: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    # G4: use explicit metadata-aware actor inference
    actors = _infer_actors_v2(goal)
    fixture_dag = _fixture_dag(goal, actors)
    _contracts = contracts or []
    _decisions = decisions or {}
    decision_refs = _goal_decision_refs(goal, _decisions)
    return {
        "title": goal["title"],
        "priority": goal.get("priority") or "important",
        "goal_type": goal.get("goal_type") or ("multi-actor" if _is_multi_actor(goal) else "mutation"),
        "surface": goal.get("surface") or "unknown",
        "source_goal": goal.get("source"),
        "primary_endpoints": _extract_endpoints(goal),
        "source_assertions": {
            "success_criteria": goal.get("success_criteria") or "",
            "mutation_evidence": goal.get("mutation_evidence") or "",
            "persistence_check": goal.get("persistence_check") or "",
            "dependencies": goal.get("dependencies") or "",
            "infra_deps": goal.get("infra_deps") or "",
        },
        "actors": actors,
        "fixture_dag": fixture_dag,
        # G1: preconditions derived from goal.dependencies + infra_deps
        "preconditions": _preconditions(goal),
        "decision_refs": decision_refs,
        "steps": [
            _step(stage, goal, _stage_actor(stage, goal, actors), _contracts, _decisions, decision_refs)
            for stage in _stages_for_goal(goal)
        ],
        # G6: artifact_capture reflects goal.artifact_kind
        "artifact_capture": _artifact_capture_v2(goal),
        "cleanup": [
            {"target": fixture["id"], "action": fixture["cleanup"]}
            for fixture in reversed(fixture_dag)
        ],
        "generator_note": "Generated from phase docs; executable tests must bind TS-XX to this goal and implement these steps.",
    }


def _find_phase_dir(phase: str, explicit: str | None) -> Path:
    if explicit:
        path = Path(explicit)
        if not path.exists():
            raise SystemExit(f"phase-dir not found: {path}")
        return path

    root = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd())
    phases_dir = root / ".vg" / "phases"
    if not phases_dir.is_dir():
        raise SystemExit(f"phase directory root not found: {phases_dir}")

    candidates = [p for p in phases_dir.iterdir() if p.is_dir()]
    exact = [p for p in candidates if p.name == phase]
    if exact:
        return exact[0]

    prefix = phase_pad(phase) if str(phase).isdigit() else str(phase)
    matches = [p for p in candidates if p.name == prefix or p.name.startswith(prefix + "-")]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise SystemExit(f"phase not found: {phase}")
    raise SystemExit(f"phase is ambiguous: {phase}: {', '.join(p.name for p in matches)}")


def generate(phase_dir: Path, include_readonly: bool = False) -> dict[str, Any]:
    goals = _parse_goals(phase_dir)
    contracts = _parse_api_contracts(phase_dir)
    decisions = _parse_context_decisions(phase_dir)
    selected = [goal for goal in goals if include_readonly or _needs_lifecycle(goal)]
    specs = {goal["id"]: _goal_spec(goal, contracts, decisions) for goal in selected}
    return {
        "schema_version": "1.0",
        "phase": phase_dir.name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": "generate-lifecycle-specs.py",
        "scope": "Generated closed-loop lifecycle contracts from phase docs. Human/executable tests must implement these contracts.",
        "formula": {
            "selection": "side-effecting or multi-actor goals from TEST-GOALS split files or TEST-GOALS.md",
            "stages": list(REQUIRED_STAGES),
            "minimum_contract": ["actors", "fixture_dag", "preconditions", "steps", "artifact_capture when applicable", "cleanup"],
            "source_artifacts": ["TEST-GOALS/", "TEST-GOALS.md", "API endpoint mentions", "phase context embedded in goal text"],
        },
        "summary": {
            "goals_seen": len(goals),
            "goals_emitted": len(specs),
            "include_readonly": include_readonly,
        },
        # G5 Batch 4: root-level fixture DAG from cross-goal dependencies
        "fixture_dag": _root_fixture_dag(selected),
        "goals": specs,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", required=True, help="Phase number or phase directory slug")
    parser.add_argument("--phase-dir", default=None)
    parser.add_argument("--out", default=None, help="Output path; default: <phase-dir>/LIFECYCLE-SPECS.json")
    parser.add_argument("--include-readonly", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true", help="Print summary JSON to stdout")
    args = parser.parse_args()

    phase_dir = _find_phase_dir(args.phase, args.phase_dir)
    payload = generate(phase_dir, include_readonly=args.include_readonly)
    out_path = Path(args.out) if args.out else phase_dir / "LIFECYCLE-SPECS.json"

    if not args.dry_run:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = out_path.with_suffix(out_path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(out_path)

    summary = {
        "phase_dir": str(phase_dir),
        "out": str(out_path),
        "dry_run": args.dry_run,
        **payload["summary"],
    }
    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        action = "would write" if args.dry_run else "wrote"
        print(f"{action} {out_path} ({summary['goals_emitted']}/{summary['goals_seen']} lifecycle goals)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
