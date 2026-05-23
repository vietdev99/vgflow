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
# Batch 36 R2: read-only goals (display/list/dashboard/filter/search/error
# views) need richer stage coverage than just read_before. Without these
# stages, codegen subagent emits sparse specs for read-only views which
# is the user-reported "test-specs sơ sài" root cause.
READONLY_STAGES: tuple[str, ...] = (
    "read_before",          # G14 back-compat: precondition snapshot
    "render_initial",       # Page loads, layout renders, no console errors
    "interaction_filter",   # Apply filter → URL+state updates, list refilters
    "interaction_sort",     # Click sort column → order changes, URL persists
    "interaction_paginate", # Navigate pages → URL param, deep-link works
    "empty_state",          # Filter to zero results → friendly empty UI
    "error_state_4xx",      # Backend 4xx/5xx → user-facing error, no crash
    "loading_state",        # Skeleton/spinner shown during fetch
    "accessibility",        # ARIA labels, keyboard nav, screen-reader hints
)

GOAL_TYPE_STAGES: dict[str, tuple[str, ...]] = {
    "create-only": ("read_before", "create", "read_after_create"),
    "update-only": ("read_before", "update", "read_after_update"),
    "delete-only": ("read_before", "delete", "read_after_delete"),
    "read-only":   READONLY_STAGES,  # Batch 36 R2: 8 stages
}

# B62-pre (audit ID-1): feature_chain class needs RCRURDR + visibility_check
# stages per chain step. Without this, AI emits goal_class=feature_chain but
# pipeline falls through to default RCRURDR → visibility_check never emits →
# B62 silent no-op.
FEATURE_CHAIN_STAGES: tuple[str, ...] = (
    "read_before",
    "create",
    "read_after_create",
    "visibility_check",        # B62-pre: navigate to target view, assert entity visible
    "interaction_chain",       # Click entity in target view → detail loads
    "update",
    "read_after_update",
    "cascade_check",           # B62-pre: re-verify visibility post-update
    "delete",
    "read_after_delete",
    "archive_visibility_check",  # B62-pre: assert entity in archive list, gone from primary
)

# B62-pre (audit ID-1): goal_class enum dispatch (separate from goal_type).
# AI may set goal_class without goal_type. Without this lookup, the
# template/goal-class enum extension would be a no-op.
GOAL_CLASS_STAGES: dict[str, tuple[str, ...]] = {
    "feature_chain":       FEATURE_CHAIN_STAGES,
    "post_create_cascade": FEATURE_CHAIN_STAGES,  # alias
}


# B97 v4.69.0 (issue #200): generator-validator alignment. Pre-B97,
# generator passed goal_class through verbatim from TEST-GOALS markdown.
# Many goal authors omitted the field for non-mutation goals → validator
# defaulted to full RCRURDR → 85 of 206 goals BLOCKED with stage-missing.
# Fix: when goal_class blank but stage-set is determinable, infer it.
def _infer_goal_class(stages: tuple[str, ...]) -> str:
    """Reverse-map emitted stage set → canonical goal_class enum.

    Returns empty string when stages don't match any known shape (caller
    should leave goal_class blank rather than guess).
    """
    s = tuple(stages)
    # Exact match against known stage tuples
    if s == GOAL_TYPE_STAGES["read-only"]:
        return "readonly"
    if s == GOAL_TYPE_STAGES["create-only"]:
        return "create-only"
    if s == GOAL_TYPE_STAGES["update-only"]:
        return "update-only"
    if s == GOAL_TYPE_STAGES["delete-only"]:
        return "delete-only"
    if s == FEATURE_CHAIN_STAGES:
        return "feature_chain"
    if s == REQUIRED_STAGES:
        return "mutation"
    # Immutable-resource shape (B75: read_before, create, read_after_create only)
    if s == ("read_before", "create", "read_after_create"):
        return "create-only"
    return ""


# B94 v4.67.3 (issue #197 F-CAI-09): read-only goal keyword cues. Used to
# auto-detect read-only goals when `goal_type` not declared explicitly.
# PrintwayV3 Phase 8.2: 52 goals classified RCRURDR but actually read-only
# subset (list/display/dashboard with no mutation hints). Auto-detect
# coerces stages to read-only when title leads with these verbs AND no
# mutation HTTP verb appears in evidence.
_READONLY_TITLE_RE = re.compile(
    r"\b("
    r"list|display|show|view|render|render the|browse|see|preview|"
    r"filter|search|sort|paginate|count|tally|dashboard|summary|"
    r"overview|report|export\s+view|read|fetch|query|inspect|"
    r"validate.*display|verify.*shown|empty\s+state|error\s+state"
    r")\b",
    re.IGNORECASE,
)
_MUTATION_TITLE_RE = re.compile(
    r"\b("
    r"create|created|creating|add|adding|insert|register|submit|save|"
    r"update|updating|edit|editing|modify|change|patch|put|"
    r"delete|deleting|remove|archive|cancel|deactivate|disable|"
    r"approve|reject|invite|revoke|reset|rollback|"
    r"upload|import|sync|trigger|publish|send"
    r")\b",
    re.IGNORECASE,
)


def _looks_read_only(goal: dict[str, Any]) -> bool:
    """B94 v4.67.3 (issue #197 F-CAI-09): heuristic auto-detect for
    read-only goals when `goal_type` is empty/absent.

    Returns True when:
      - title matches read-only verb cue (list/display/dashboard/etc.)
      - AND title has NO mutation verb cue
      - AND mutation_evidence is empty OR has no HTTP mutation verb
      - AND no goal_class declared (feature_chain etc. always go RCRURDR)
    """
    if goal.get("goal_class"):
        return False
    title = str(goal.get("title") or "")
    if not title:
        return False
    if _MUTATION_TITLE_RE.search(title):
        return False
    if not _READONLY_TITLE_RE.search(title):
        return False
    # Check mutation_evidence has no HTTP mutation verb
    evidence = " ".join(
        str(goal.get(k) or "")
        for k in ("mutation_evidence", "persistence_check")
    ).upper()
    has_mut_verb = (
        "POST " in evidence or " POST" in evidence or
        "PUT " in evidence or " PUT" in evidence or
        "PATCH " in evidence or " PATCH" in evidence or
        "DELETE " in evidence or " DELETE" in evidence
    )
    return not has_mut_verb


def _stages_for_goal(goal: dict[str, Any]) -> tuple[str, ...]:
    """Derive lifecycle stages.

    Dispatch precedence (B62-pre — audit ID-1, B94 v4.67.3 — F-CAI-09):
      1. goal_class (NEW dispatch key — feature_chain wins over RCRURDR default)
      2. goal_type (existing dispatch — backward compatible)
      3. B94: read-only AUTO-DETECT from title/body when goal_type empty
      4. HTTP verb inference from mutation_evidence (legacy fallback)

    Without B62-pre fix, AI setting goal_class=feature_chain produced no
    stage change because pipeline read goal_type only.

    B94 v4.67.3 (issue #197 F-CAI-09): PrintwayV3 Phase 8.2 had 52 goals
    classified default RCRURDR when actually read-only subset
    (list/display/dashboard). Validator emitted 52 warnings. Auto-detect
    coerces to read-only stages when title leads with read verbs and
    evidence has no mutation HTTP verb.
    """
    # B75 v4.63.7 (issue #191 C-M4): immutable resources skip update + delete.
    # Goal authors mark `immutable: true` when the resource cannot be mutated
    # (e.g. ledger entries, audit logs, append-only journals). Avoids the
    # 52-goal partial-RCRURDR BLOCK reported in Phase 8.2 dogfood.
    if goal.get("immutable") is True:
        return ("read_before", "create", "read_after_create")

    # B62-pre: goal_class takes priority (feature_chain etc.)
    gclass = (goal.get("goal_class") or "").strip().lower()
    if gclass in GOAL_CLASS_STAGES:
        return GOAL_CLASS_STAGES[gclass]

    gtype = (goal.get("goal_type") or "").strip().lower()
    # Explicit goal_type mapping takes priority over inference
    if gtype in GOAL_TYPE_STAGES:
        return GOAL_TYPE_STAGES[gtype]
    # Non-empty but unrecognised goal_type (e.g. multi-actor, wizard) → full RCRURDR
    # so existing tests and behaviours are not broken by unrecognised types.
    if gtype:
        return REQUIRED_STAGES
    # B94 v4.67.3: read-only auto-detect from title+evidence cues
    if _looks_read_only(goal):
        goal.setdefault("_b94_readonly_autodetected", True)
        return GOAL_TYPE_STAGES.get("read-only", REQUIRED_STAGES)
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
# B76 v4.63.8 (issue #191 C-M1/C-M5 real root cause):
# 3-layer split API-CONTRACTS.md uses TOC links `- [GET /path](file.md)`
# instead of `### GET /path` headers. Pre-B76 regex matched 0 entries
# → contracts=[] → _bind_endpoint() returned None for every step
# → 1218/1218 endpoint=null on consumer side. New pattern matches both
# index-link and header forms.
ENDPOINT_TOC_LINK_RE = re.compile(
    r"^\s*[-*]\s+\[(GET|POST|PUT|PATCH|DELETE)\s+(/\S+)\]\([^)]+\)",
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
    # B74 v4.63.6 (issue #191 C-M6): strip fenced code blocks (```yaml ... ```)
    # before regex extraction so YAML rcrurdr block content does not leak into
    # adjacent field values (e.g. Dependencies value pulling in
    # `resource/api_endpoint/expectations` lines from a sibling yaml block).
    body_clean = re.sub(r"```[\w-]*\n.*?\n```\s*", "", body, flags=re.DOTALL)
    patterns = (
        rf"^\*\*{re.escape(name)}:\*\*\s*(.+?)(?=^\*\*|\n##|\n#\s+G-|\Z)",
        rf"^{re.escape(name)}:\s*(.+?)(?=^\w[\w -]*:|\n##|\n#\s+G-|\Z)",
        rf"^###\s+{re.escape(name)}\s*\n(.+?)(?=^###\s+|\n##\s+|\n#\s+|\Z)",
    )
    for pattern in patterns:
        match = re.search(pattern, body_clean, re.MULTILINE | re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return ""


def _parse_chain_steps(text: str) -> list[dict[str, Any]]:
    """B65a (codex BLOCKER #2): parse chain_steps[] YAML block from TEST-GOAL
    frontmatter. Each step has step_id + description + target_view_class +
    expected_state + downstream_effects[].

    Format (per TEST-GOAL-enriched-template.md):
        chain_steps:
          - step_id: S1
            description: "..."
            target_view_class: source_view
            expected_state: list_loaded
            downstream_effects: []
          - step_id: S2
            ...

    Returns empty list when no chain_steps block found.
    """
    block_m = re.search(
        r"^chain_steps:\s*\n((?:\s+(?:-\s+|\s).*\n)+)",
        text,
        re.MULTILINE,
    )
    if not block_m:
        return []
    block = block_m.group(1)
    steps: list[dict[str, Any]] = []
    # Split by step_id markers — each `- step_id:` starts a new step
    step_starts = list(re.finditer(r"^\s*-\s+step_id:\s*(\S+)", block, re.MULTILINE))
    for i, sm in enumerate(step_starts):
        start = sm.start()
        end = step_starts[i + 1].start() if i + 1 < len(step_starts) else len(block)
        chunk = block[start:end]
        step_id = sm.group(1).strip().strip('"\'')
        desc_m = re.search(r"description:\s*\"?([^\"\n]+)\"?", chunk)
        tvc_m = re.search(r"target_view_class:\s*(\S+)", chunk)
        es_m = re.search(r"expected_state:\s*(\S+)", chunk)
        # downstream_effects block — inline `[]` or YAML list
        de_inline_m = re.search(r"downstream_effects:\s*\[(.*?)\]", chunk)
        downstream: list[str] = []
        if de_inline_m:
            raw = de_inline_m.group(1).strip()
            if raw:
                downstream = [s.strip().strip('"\'') for s in raw.split(",") if s.strip()]
        else:
            de_block_m = re.search(
                r"downstream_effects:\s*\n((?:\s+-\s+.*\n)+)",
                chunk,
                re.MULTILINE,
            )
            if de_block_m:
                for line in de_block_m.group(1).splitlines():
                    item_m = re.match(r"\s+-\s+\"?(.+?)\"?\s*$", line)
                    if item_m:
                        downstream.append(item_m.group(1).strip())
        steps.append({
            "step_id": step_id,
            "description": (desc_m.group(1).strip() if desc_m else ""),
            "target_view_class": (tvc_m.group(1).strip().strip('"\'') if tvc_m else ""),
            "expected_state": (es_m.group(1).strip().strip('"\'') if es_m else ""),
            "downstream_effects": downstream,
        })
    return steps


def _parse_enables(text: str) -> list[str]:
    """B65a (codex BLOCKER #2): parse enables[] from TEST-GOAL frontmatter.

    Inline form: `enables: [G-04, G-07]`
    Block form:  `enables:\\n  - G-04\\n  - G-07`
    """
    inline_m = re.search(r"^enables:\s*\[(.*?)\]", text, re.MULTILINE)
    if inline_m:
        raw = inline_m.group(1)
        return [s.strip().strip('"\'') for s in raw.split(",") if s.strip()]
    block_m = re.search(
        r"^enables:\s*\n((?:\s+-\s+.*\n)+)",
        text,
        re.MULTILINE,
    )
    if block_m:
        out: list[str] = []
        for line in block_m.group(1).splitlines():
            item_m = re.match(r"\s+-\s+\"?(G-[\w.-]+)\"?", line)
            if item_m:
                out.append(item_m.group(1))
        return out
    return []


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
    # B75 v4.63.7 (issue #191 C-M4): parse `immutable` flag from frontmatter.
    # Goals marked immutable: true skip update + delete stages (RCRURDR
    # becomes RCR — read-create-read_after_create only).
    immutable_raw = _field(text, "immutable").strip().lower()
    is_immutable = immutable_raw in ("true", "yes", "1")
    # B75 v4.63.7 (C-M7): parse success_status for cross-validation.
    success_status_raw = _field(text, "success_status").strip()
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
        # B65a (codex BLOCKER #2): chain_steps + enables now parsed first-class
        "chain_steps": _parse_chain_steps(text),
        "enables": _parse_enables(text),
        # B75 v4.63.7 (issue #191): new fields for C-M4 immutable + C-M7 cross-validation.
        "immutable": is_immutable,
        "success_status": success_status_raw,
        "source": str(source),
    }


def _parse_goals(phase_dir: Path,
                 dropped_log: list[dict[str, str]] | None = None) -> list[dict[str, Any]]:
    """B75 v4.63.7 (issue #191 C-M8): merge BOTH TEST-GOALS/G-*.md (split) AND
    TEST-GOALS.md (flat) sources. Dedup by goal id, split-dir wins when both
    present (split files are the canonical source-of-truth post-Batch-9; the
    flat file may carry goals appended later that weren't migrated yet).

    Previously: split dir = ANY match → flat file was IGNORED. Caused
    G-201..G-226 to be dropped in Phase 8.2 (split dir had G-001..G-200,
    flat had G-001..G-226). 74 CONTEXT.md decisions absent from coverage.

    B90 v4.66.1 (issue #197 F-CAI-08): when `_parse_goal_block` returns None
    (heading regex match fails OR id field missing), record diagnostic in
    `dropped_log` so caller can report which goals were silently skipped.
    Previously: silent drop. PrintwayV3 Phase 8.2 had 206 headings → 200
    emitted; the 6 missing (G-221..G-226) were dropped without warning.
    """
    goals_by_id: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    # 1. Split dir (canonical source).
    split_dir = phase_dir / "TEST-GOALS"
    if split_dir.is_dir():
        for path in sorted(split_dir.glob("G-*.md")):
            goal = _parse_goal_block(_read(path), path)
            if goal and goal.get("id"):
                gid = goal["id"]
                if gid not in goals_by_id:
                    order.append(gid)
                goals_by_id[gid] = goal
            elif dropped_log is not None:
                dropped_log.append({
                    "source": str(path),
                    "reason": "split-file heading regex match failed OR id field missing",
                })

    # 2. Flat TEST-GOALS.md (merge; only ADD missing goals — split-dir wins
    # for duplicates so per-goal split semantics are preserved).
    flat_path = phase_dir / "TEST-GOALS.md"
    if flat_path.is_file():
        text = _read(flat_path)
        pattern = re.compile(
            r"^##\s+(?:Goal\s+)?(G-[\w.-]+):?\s*(.*?)$"
            r"(?P<body>(?:(?!^##\s+(?:Goal\s+)?G-[\w.-]+).)*)",
            re.MULTILINE | re.DOTALL,
        )
        for match in pattern.finditer(text):
            gid_raw = match.group(1).strip()
            body = f"## Goal {gid_raw}: {match.group(2)}\n{match.group('body') or ''}"
            goal = _parse_goal_block(body, flat_path)
            if goal and goal.get("id"):
                gid = goal["id"]
                if gid not in goals_by_id:
                    order.append(gid)
                    goals_by_id[gid] = goal
                # else: split-dir version already wins — skip flat.
            elif dropped_log is not None:
                dropped_log.append({
                    "source": f"{flat_path}#{gid_raw}",
                    "reason": "flat-file goal block parse failed (body present but heading regex did not match _parse_goal_block patterns)",
                })

    return [goals_by_id[gid] for gid in order]


def _count_goal_headings(phase_dir: Path) -> dict[str, int]:
    """B90 v4.66.1 (issue #197 F-CAI-08): count raw `## G-` headings in
    TEST-GOALS.md + `# G-` headings in TEST-GOALS/G-*.md split files.
    Caller compares to parsed-goal count to detect silent drops.
    """
    counts = {"split_files": 0, "flat_headings": 0, "flat_files_exists": 0}
    split_dir = phase_dir / "TEST-GOALS"
    if split_dir.is_dir():
        counts["split_files"] = len(list(split_dir.glob("G-*.md")))
    flat_path = phase_dir / "TEST-GOALS.md"
    if flat_path.is_file():
        counts["flat_files_exists"] = 1
        text = _read(flat_path)
        counts["flat_headings"] = len(re.findall(
            r"^##\s+(?:Goal\s+)?G-[\w.-]+", text, re.MULTILINE
        ))
    return counts


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


# B75 v4.63.7 (issue #191 C-M3): generic role placeholders that should NOT
# be emitted when canonical foundation roles are available. AI-generated
# placeholders like "secondary_user_or_external_system" or "reviewer"
# leaked through fallback `_infer_actors`. Loading the project FOUNDATION
# roles + auditing the field surfaces these generic placeholders.
_GENERIC_ACTOR_PLACEHOLDERS = frozenset({
    "secondary_user_or_external_system",
    "external_system",
    "approver",
    "reviewer",
    "secondary_user",
    "secondary_actor",
    "any_authenticated_user",
})


def _load_foundation_roles(phase_dir: Path | None) -> list[str]:
    """Best-effort read of canonical project roles from FOUNDATION.md / vg.config.md.

    Looks for a `## Roles` or `**Roles:**` block. Returns lowercase
    snake_case role IDs. Empty list = no canonical source found
    (caller falls back to existing inference).
    """
    if phase_dir is None:
        return []
    candidates: list[Path] = []
    project_root = phase_dir
    for _ in range(6):
        if ((project_root / ".vg").is_dir()
                or (project_root / "vg.config.md").is_file()
                or (project_root / "FOUNDATION.md").is_file()):
            break
        if project_root.parent == project_root:
            break
        project_root = project_root.parent
    for name in ("FOUNDATION.md", "vg.config.md"):
        candidates.append(project_root / name)
        candidates.append(project_root / ".vg" / name)
    seen_paths: set[str] = set()
    text = ""
    for p in candidates:
        try:
            if p.is_file() and str(p.resolve()) not in seen_paths:
                seen_paths.add(str(p.resolve()))
                text += "\n" + p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
    if not text:
        return []
    roles: list[str] = []
    m_block = re.search(
        r"(?im)^(?:##\s+Roles|^\*\*Roles:\*\*)\s*\n(?P<body>.+?)(?=^##\s+|\n\*\*[\w-]+:\*\*|\Z)",
        text,
        re.DOTALL,
    )
    if m_block:
        body = m_block.group("body")
        for line in body.splitlines():
            line = line.strip().lstrip("-*").strip()
            if not line:
                continue
            # Extract first identifier-like token, drop trailing punctuation/desc.
            m_role = re.match(r"^([A-Za-z][\w/-]+)", line)
            if m_role:
                rid = m_role.group(1).lower().replace("-", "_").replace("/", "_")
                if rid and rid not in roles:
                    roles.append(rid)
    return roles


def _infer_actors_v2(goal: dict[str, Any], phase_dir: Path | None = None) -> list[dict[str, Any]]:
    """Read explicit actors metadata first; fall back to word-match heuristic.

    B75 v4.63.7 (issue #191 C-M3): when canonical roles available from
    FOUNDATION.md/vg.config.md, reject generic placeholders and remap
    to canonical names where possible.
    """
    canonical_roles = _load_foundation_roles(phase_dir) if phase_dir else []
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
            # B75 C-M3: replace generic placeholders with first canonical role
            # if a project role list exists (otherwise keep as-is for compat).
            if aid in _GENERIC_ACTOR_PLACEHOLDERS and canonical_roles:
                aid = canonical_roles[0]
                item = aid
                goal.setdefault("_b75_generic_actor_replaced", 0)
                goal["_b75_generic_actor_replaced"] += 1
            if aid in seen:
                continue
            seen.add(aid)
            actors.append({"id": aid, "role": item, "session": f"{aid}_session",
                           "permissions": [f"least privilege required for {item} path"]})
        if actors:
            return actors
    # Fallback to existing _infer_actors() word-match, then post-filter
    # generic placeholders if canonical roles known.
    actors = _infer_actors(goal)
    if canonical_roles:
        for a in actors:
            if a.get("role") in _GENERIC_ACTOR_PLACEHOLDERS:
                a["role"] = canonical_roles[0]
                a["id"] = canonical_roles[0]
                a["session"] = f"{canonical_roles[0]}_session"
                goal.setdefault("_b75_generic_actor_replaced", 0)
                goal["_b75_generic_actor_replaced"] += 1
    return actors


# B75 v4.63.7 (issue #191 C-M7): validate mutation_evidence vs success_status.
# Goal frontmatter `success_status: 201` should be consistent with
# `Mutation evidence: ... returns 201`. G-048-style internal contradiction
# (success=200 vs evidence=201) is silently emitted today.
_STATUS_RE = re.compile(r"\b(2\d\d|3\d\d|4\d\d|5\d\d)\b")


def _validate_success_status_consistency(goal: dict[str, Any]) -> dict[str, Any] | None:
    """Return None when consistent; dict with `expected`/`observed` when drift."""
    success_status = (goal.get("success_status") or "").strip()
    mutation = goal.get("mutation_evidence") or ""
    if not success_status or not mutation:
        return None
    # Extract HTTP status code from success_status field.
    m = _STATUS_RE.search(success_status)
    if not m:
        return None
    declared = m.group(1)
    # Extract codes from mutation_evidence text.
    evidence_codes = _STATUS_RE.findall(mutation)
    if not evidence_codes:
        return None
    if declared in evidence_codes:
        return None
    # Mismatch — pick the FIRST observed evidence code as the conflict.
    return {"declared": declared, "observed": evidence_codes[0]}


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


def _parse_actor_workflow(goal: dict[str, Any]) -> dict[str, str]:
    """B92 v4.67.1 (issue #197 F-CAI-02): parse explicit per-stage actor
    assignments from goal frontmatter.

    Supported form (in body, parsed via _field):
        actor_workflow:
          create: requestor
          update: approver
          delete: admin

    Or inline:
        actor_workflow: {create: requestor, update: approver}

    Returns dict mapping stage → actor_id. Empty when not declared.
    """
    body = goal.get("body") or ""
    raw = _field(body, "actor_workflow").strip()
    if not raw:
        return {}
    mapping: dict[str, str] = {}
    # Inline form `{stage: actor, stage: actor}`
    if raw.startswith("{") and raw.endswith("}"):
        inner = raw[1:-1]
        for piece in inner.split(","):
            kv = piece.strip().split(":", 1)
            if len(kv) == 2:
                mapping[kv[0].strip()] = kv[1].strip()
        return mapping
    # Block form: each line `  stage: actor`
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        stage, actor = line.split(":", 1)
        mapping[stage.strip()] = actor.strip()
    return mapping


def _stage_actor(stage: str, goal: dict[str, Any], actors: list[dict[str, Any]]) -> str:
    """Resolve which actor performs this stage.

    B92 v4.67.1 (issue #197 F-CAI-02): explicit `actor_workflow:` frontmatter
    overrides keyword heuristics. When declared:
      actor_workflow:
        create: requestor
        update: approver
        delete: admin
    each stage's actor is pinned. Falls back to keyword heuristic when not
    declared (legacy behavior).

    Pre-B92 heuristic kept for goals without explicit workflow:
    - Single actor → that actor for all stages.
    - update/read_after_update + 'admin'/'approver' words → admin/approver actor.
    - read_after_create + 'invitee'/'accept' words → invitee actor.
    - Default → actors[0].
    """
    if not actors:
        return "primary"
    if len(actors) == 1:
        return actors[0]["id"]
    actor_ids = {a["id"] for a in actors}
    # B92: explicit workflow declaration wins
    workflow = _parse_actor_workflow(goal)
    if stage in workflow and workflow[stage] in actor_ids:
        return workflow[stage]
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
    """B92 v4.67.1 (issue #197 F-CAI-06): multi-actor DAG with cross-owner
    cleanup chain.

    Pre-B92: `owned_resource` depended only on `actors[0]_session`. When a
    workflow involved sequence (create-by-actor-A → patch-by-actor-B →
    delete-by-actor-C), each actor's session existed but the resource
    cleanup chain had no restoration path — cleanup walker couldn't
    traverse mutations across actor boundaries.

    B92: `owned_resource.depends_on` lists ALL actor sessions involved in
    mutations (not just the first). When `actor_workflow` declared, the
    set respects declared mutation stages; otherwise depends on all actor
    sessions present. Cleanup chain phrased to reverse-traverse mutations.
    """
    fixtures = [
        {
            "id": f"{actor['id']}_session",
            "kind": "auth_or_service_context",
            "depends_on": [],
            "cleanup": "revoke session/token or clear service fixture if created by test",
        }
        for actor in actors
    ]
    # B92 F-CAI-06: owned_resource depends on ALL mutating actor sessions
    if fixtures:
        workflow = _parse_actor_workflow(goal)
        mutating_stages = ("create", "update", "delete")
        if workflow:
            mut_actors = {workflow.get(s) for s in mutating_stages if workflow.get(s)}
            owned_deps = sorted({f"{a}_session" for a in mut_actors if a})
            if not owned_deps:
                owned_deps = [fixtures[0]["id"]]
        elif len(fixtures) > 1:
            # Multi-actor goal without explicit workflow → conservatively
            # depend on ALL sessions so cleanup walker spans the chain.
            owned_deps = [f["id"] for f in fixtures]
        else:
            owned_deps = [fixtures[0]["id"]]
    else:
        owned_deps = []

    fixtures.append({
        "id": "owned_resource",
        "kind": "resource_or_state_under_test",
        "depends_on": owned_deps,
        # B92 F-CAI-06: cleanup phrased to walk back through any actor
        "cleanup": (
            "delete/deactivate/cancel/rollback or restore original state. "
            "Multi-actor: reverse-traverse mutation chain "
            "(actor-C delete → actor-B revert patch → actor-A delete)."
            if len(owned_deps) > 1 else
            "delete/deactivate/cancel/rollback or restore original state"
        ),
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


# B76 v4.63.8 (issue #191 C-M8 real root cause):
# Phase decision headers in CONTEXT.md use `### P8.D-67:` form
# (project-prefixed). Pre-B76 regex only matched bare `D-XX` → 0
# decisions parsed from P8/P9/P10 phases → decision_refs empty for
# every goal. Allow optional `P\d+\.` prefix and normalize to the
# prefixed canonical ID so lookup matches goal references.
DECISION_HEADER_RE = re.compile(
    r"^#{2,3}\s+((?:P\d+\.)?D-[\w.-]+):?\s*(.+?)\s*$",
    re.MULTILINE,
)
DECISION_FIELD_RE = re.compile(
    r"^\*\*expected_assertion:\*\*\s*(.+?)(?=^\*\*|\n##|\n#\s+D-|\Z)",
    re.MULTILINE | re.DOTALL,
)
# B76 v4.63.8 (issue #191 C-M8): match optional `P\d+\.` prefix so
# goal references like `P8.D-84` resolve against decisions parsed with
# the same canonical form.
DECISION_REF_RE = re.compile(r"\b((?:P\d+\.)?D-[\w.-]+)\b")


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


def _parse_explicit_decision_refs(goal: dict[str, Any]) -> list[str]:
    """B93 v4.67.2 (issue #197 F-CAI-07): parse explicit `decision_refs:`
    frontmatter field on goal. Supports inline + block list forms:

        decision_refs: [P8.D-12, P8.D-44]
        decision_refs:
          - P8.D-12
          - P8.D-44
    """
    body = goal.get("body") or ""
    raw = _field(body, "decision_refs").strip()
    if not raw:
        return []
    refs: list[str] = []
    # Inline `[X, Y, Z]`
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1]
        for piece in inner.split(","):
            piece = piece.strip().strip('"').strip("'")
            if DECISION_REF_RE.fullmatch(piece):
                refs.append(piece)
        return refs
    # Block: each line `- X`
    for line in raw.splitlines():
        line = line.strip().lstrip("-").strip().strip('"').strip("'")
        if not line or line.startswith("#"):
            continue
        if DECISION_REF_RE.fullmatch(line):
            refs.append(line)
    return refs


def _goal_decision_refs(goal: dict[str, Any], decisions: dict[str, dict[str, str]]) -> list[str]:
    """Extract D-XX refs from goal — explicit frontmatter first, then text scan.

    B93 v4.67.2 (issue #197 F-CAI-07): prefer explicit `decision_refs:`
    frontmatter list when declared. Previously: relied entirely on text-scan
    regex over goal body. Many goals didn't reference D-XX inline → coverage
    came out 68.4% on PrintwayV3 Phase 8.2 (162/237 P8.D-XX, below 85%
    gate). Explicit frontmatter lets blueprint AI bind decisions directly.

    Returns sorted union of explicit + text-scanned references that exist
    in `decisions`.
    """
    if not decisions:
        return []
    found: set[str] = set()
    # 1. Explicit frontmatter declaration
    for ref in _parse_explicit_decision_refs(goal):
        if ref in decisions:
            found.add(ref)
    # 2. Text scan fallback (legacy)
    haystack = _combined(goal)
    for m in DECISION_REF_RE.finditer(haystack):
        d_id = m.group(1)
        if d_id in decisions:
            found.add(d_id)
    return sorted(found)


def _decision_coverage(goals: list[dict[str, Any]],
                       decisions: dict[str, dict[str, str]]) -> dict[str, Any]:
    """B93 v4.67.2 (issue #197 F-CAI-07): compute decision coverage % +
    list unbound decision IDs.

    Returns:
      total_decisions: phase total (denominator)
      bound_decisions: count referenced by ≥1 goal
      coverage_pct: 0-100
      unbound: list of decision IDs no goal references (first 30)
      threshold: 85.0 (advisory gate; flips to BLOCK in later batch)
      passed: coverage_pct >= threshold
    """
    if not decisions:
        return {
            "total_decisions": 0,
            "bound_decisions": 0,
            "coverage_pct": 100.0,
            "unbound": [],
            "threshold": 85.0,
            "passed": True,
        }
    referenced: set[str] = set()
    for g in goals:
        for ref in _goal_decision_refs(g, decisions):
            referenced.add(ref)
    total = len(decisions)
    bound = len(referenced & set(decisions.keys()))
    pct = round((bound / total) * 100.0, 1) if total else 100.0
    unbound = sorted(set(decisions.keys()) - referenced)
    return {
        "total_decisions": total,
        "bound_decisions": bound,
        "coverage_pct": pct,
        "unbound": unbound[:30],
        "unbound_count": len(unbound),
        "threshold": 85.0,
        "passed": pct >= 85.0,
    }


def _parse_api_contracts(phase_dir: Path) -> list[dict[str, str]]:
    """Parse API-CONTRACTS.md → list of {method, path} dicts.

    B76 v4.63.8 (issue #191 C-M1/C-M5 real root cause):
    Supports two layouts emitted by /vg:blueprint:
      (a) flat:     `### GET /api/v1/...` headers (legacy single-file).
      (b) 3-layer split: TOC index `- [GET /path](file.md)` + per-endpoint
          markdown files in `API-CONTRACTS/<slug>.md` (Batch 60+).
    Pre-B76 only matched (a) → P8.2-style index files returned 0 contracts
    → all step endpoints null. Now matches both and de-duplicates.
    """
    contracts_path = phase_dir / "API-CONTRACTS.md"
    if not contracts_path.is_file():
        return []
    text = _read(contracts_path)
    found: dict[tuple[str, str], dict[str, str]] = {}
    for m in ENDPOINT_HEADER_RE.finditer(text):
        method, path = m.group(1), m.group(2)
        found[(method, path)] = {"method": method, "path": path}
    for m in ENDPOINT_TOC_LINK_RE.finditer(text):
        method, path = m.group(1), m.group(2)
        found.setdefault((method, path), {"method": method, "path": path})
    # Also pull from per-endpoint files in API-CONTRACTS/ subdirectory
    split_dir = phase_dir / "API-CONTRACTS"
    if split_dir.is_dir():
        for sub in split_dir.glob("*.md"):
            sub_text = _read(sub)
            for m in ENDPOINT_HEADER_RE.finditer(sub_text):
                method, path = m.group(1), m.group(2)
                found.setdefault((method, path), {"method": method, "path": path})
    return list(found.values())


_ENTITY_SLUG_RE = re.compile(r"[a-z0-9][a-z0-9_-]+")


def _extract_entity_slugs(goal: dict[str, Any]) -> set[str]:
    """B91 v4.67.0 (issue #197 F-CAI-01): derive entity slugs to anchor
    endpoint matching. Sources, in order of trust:

      1. goal.primary_endpoints[].path — path segments after `/api/v1/<scope>/`
         OR `/admin/` (strip resource id placeholders like `:id`, `{id}`).
      2. goal.title — first 2-3 lowercase tokens that look like resource names.
      3. goal.mutation_evidence + persistence_check noun phrases.

    Returns a set of candidate slugs (lowercased). Used by `_bind_endpoint`
    to filter contract candidates to those whose path overlaps with at least
    one slug — eliminating G-001 (topup review) emitting bindings for
    `/admin/payment-gateways` or `/admin/legal-entities`.
    """
    slugs: set[str] = set()
    for ep in (goal.get("primary_endpoints") or []):
        if not isinstance(ep, dict):
            continue
        path = str(ep.get("path") or "").lower()
        for seg in path.split("/"):
            if not seg or seg in {"api", "v1", "admin", "auth", "public"}:
                continue
            # Drop placeholder tokens
            if seg.startswith(":") or seg.startswith("{"):
                continue
            if _ENTITY_SLUG_RE.fullmatch(seg):
                slugs.add(seg)
    # Fallback: title-derived slugs
    if not slugs:
        title = str(goal.get("title") or "").lower()
        for word in re.findall(r"[a-z][a-z0-9_-]{2,}", title)[:6]:
            if word in {"the", "list", "view", "page", "screen", "filter",
                        "create", "delete", "update", "review", "approve",
                        "search", "show", "display", "and", "with"}:
                continue
            slugs.add(word)
    return slugs


def _normalize_contract_path(path: str, contract_paths: set[str]) -> str:
    """B91 v4.67.0 (issue #197 F-CAI-04): tolerant path normalization.

    If `path` not in `contract_paths` but a known prefix variant is
    (e.g. `/admin/credits` ↔ `/api/v1/admin/credits`), return the
    contract-side variant. Otherwise return path unchanged.

    Common stale-prefix patterns observed in PrintwayV3 Phase 8.2:
      bare:        /admin/...        → contracts ship /api/v1/admin/...
      versioned:   /api/v1/admin/... → contracts may ship bare during dev
    """
    if path in contract_paths:
        return path
    candidates = [
        f"/api/v1{path}" if path.startswith("/admin/") else None,
        path.replace("/api/v1", "", 1) if path.startswith("/api/v1/admin/") else None,
        f"/api/v1{path}" if path.startswith("/auth/") else None,
    ]
    for c in candidates:
        if c and c in contract_paths:
            return c
    return path


def _bind_endpoint(stage: str, goal: dict[str, Any], contracts: list[dict[str, str]]) -> dict[str, str] | None:
    """Match stage to a contract endpoint via heuristic on stage verb + goal text.

    B74 v4.63.6 (issue #191 C-M1 / C-M5): record diagnostic on goal when
    fallback path is taken.

    B91 v4.67.0 (issue #197 F-CAI-01 + F-CAI-04 + F-CAI-10):
      - F-CAI-01 fix: drop verb-only fallback that pulled unrelated mutations.
        Replace with entity-slug anchored filter. Goals whose entity slugs
        don't overlap any candidate path → return None (with telemetry tag).
        Previously G-001 (topup review) got bindings for unrelated
        payment-gateway PATCH + bank-account DELETE because contracts list
        contained them and goal had `update`/`delete` stages.
      - F-CAI-04 fix: tolerant prefix normalization. `goal.primary_endpoints`
        path of `/admin/credits` resolves to contract `/api/v1/admin/credits`.
      - F-CAI-10 fix: when contracts list empty, fall back to goal's own
        primary_endpoints (per stage verb) instead of returning None for
        every step. Preserves declared endpoints even when API-CONTRACTS.md
        unparseable.
    """
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

    # B91 F-CAI-10: when contracts empty, fall back to goal's own primary_endpoints
    if not contracts:
        for ep in (goal.get("primary_endpoints") or []):
            if not isinstance(ep, dict):
                continue
            ep_method = str(ep.get("method") or "").upper()
            ep_path = str(ep.get("path") or "")
            if ep_method in candidates_methods and ep_path:
                goal.setdefault("_b91_endpoint_contracts_empty_count", 0)
                goal["_b91_endpoint_contracts_empty_count"] += 1
                return {"method": ep_method, "path": ep_path}
        return None

    contract_paths_set = {c["path"] for c in contracts}
    entity_slugs = _extract_entity_slugs(goal)

    def _path_anchored(path: str) -> bool:
        """Path must contain ≥1 entity slug from the goal."""
        if not entity_slugs:
            return True  # no slugs → can't filter; accept anything (legacy behavior)
        path_lower = path.lower()
        return any(slug in path_lower for slug in entity_slugs)

    # First: explicit primary_endpoints[] on goal (normalized) — highest trust.
    for ep in (goal.get("primary_endpoints") or []):
        if not isinstance(ep, dict):
            continue
        ep_method = str(ep.get("method") or "").upper()
        ep_path = str(ep.get("path") or "")
        if ep_method not in candidates_methods or not ep_path:
            continue
        normalized = _normalize_contract_path(ep_path, contract_paths_set)
        if normalized in contract_paths_set:
            return {"method": ep_method, "path": normalized}
    # Second: contract matches in text haystack, anchored by entity slugs.
    haystack = " ".join(str(goal.get(k) or "") for k in
                        ("mutation_evidence", "persistence_check",
                         "dependencies", "title"))
    for c in contracts:
        if c["method"] not in candidates_methods:
            continue
        if c["path"] not in haystack:
            continue
        if not _path_anchored(c["path"]):
            continue
        return {"method": c["method"], "path": c["path"]}
    # Third: entity-slug anchored scan of all contracts (no haystack required).
    for c in contracts:
        if c["method"] not in candidates_methods:
            continue
        if _path_anchored(c["path"]):
            goal.setdefault("_b91_endpoint_slug_fallback_count", 0)
            goal["_b91_endpoint_slug_fallback_count"] += 1
            return {"method": c["method"], "path": c["path"]}
    # B91 F-CAI-01: drop unconstrained verb-only fallback (was line 954-958
    # pre-B91). Returning None here preserves entity-anchor invariant —
    # rather than emitting a binding to an unrelated resource. Caller's
    # _b91_endpoint_unmatched_count tracks the gap for diagnostics.
    goal.setdefault("_b91_endpoint_unmatched_count", 0)
    goal["_b91_endpoint_unmatched_count"] += 1
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


def _derive_edge_cases(goal: dict[str, Any]) -> list[dict[str, Any]]:
    """Batch 37 F3: emit first-class edge_cases[] per goal.

    Defaults cover boundary + empty + unicode + large-payload variants
    every spec must include. Spec generator emits test.each([variants])
    where variants come from this list.
    """
    gtype = (goal.get("goal_type") or "").lower()
    cases: list[dict[str, Any]] = [
        {
            "kind": "boundary",
            "label": "min boundary value",
            "input_hint": "use lowest allowed value (0, '', 1 char, min date)",
            "expected": "accept or reject per spec; no crash",
        },
        {
            "kind": "boundary",
            "label": "max boundary value",
            "input_hint": "use highest allowed (max int, max length, future date)",
            "expected": "accept or reject per spec; no truncation silently",
        },
        {
            "kind": "empty_string",
            "label": "empty string for non-required field",
            "input_hint": "submit empty for optional fields",
            "expected": "no validation error if optional",
        },
        {
            "kind": "unicode_special",
            "label": "unicode + emoji + RTL + special chars",
            "input_hint": "包含中文 🎉 العربية ' \" < > & --",
            "expected": "stored/displayed unchanged; no XSS/SQL injection",
        },
    ]
    if gtype in {"create-only", "update-only", "create", "update", "mutation"} or not gtype:
        cases.append({
            "kind": "large_payload",
            "label": "payload at limit",
            "input_hint": "field at max allowed size + many array items",
            "expected": "accept or 413/422 per contract; no timeout",
        })
    if gtype == "read-only":
        cases.extend([
            {
                "kind": "filter_combination",
                "label": "multiple filters combined",
                "input_hint": "apply >=2 filters simultaneously",
                "expected": "AND semantics; URL reflects all; reset clears all",
            },
            {
                "kind": "pagination_edge",
                "label": "out-of-range page",
                "input_hint": "?page=99999",
                "expected": "clamp to last page OR empty state; no 500",
            },
        ])
    return cases


def _derive_negative_specs(goal: dict[str, Any]) -> list[dict[str, Any]]:
    """Batch 37 F4: emit first-class negative_specs[] per goal.

    Negative paths previously prompt-only. Codegen told 'never invent
    assertions beyond TEST-GOALS' → no 401/403/422 coverage.
    """
    gtype = (goal.get("goal_type") or "").lower()
    negs: list[dict[str, Any]] = [
        {
            "kind": "unauthorized_401",
            "label": "missing/expired auth token",
            "expected_status": 401,
            "setup": "clear cookies/Authorization header before request",
            "assert": "response.status == 401 with envelope {ok:false, error:{code:'UNAUTHORIZED'}}",
        },
        {
            "kind": "forbidden_403",
            "label": "wrong role / lacks permission",
            "expected_status": 403,
            "setup": "login as role without permission to this action",
            "assert": "response.status == 403; UI hides/disables action; no state change",
        },
    ]
    if gtype in {"create-only", "update-only", "mutation", "create", "update"} or not gtype:
        negs.extend([
            {
                "kind": "validation_422",
                "label": "invalid/missing required field",
                "expected_status": 422,
                "setup": "submit payload with required field absent or malformed",
                "assert": "422 with envelope {error:{code:'VALIDATION_ERROR', fields:[...]}}; no DB write",
            },
            {
                "kind": "not_found_404",
                "label": "operate on non-existent resource",
                "expected_status": 404,
                "setup": "use id that doesn't exist or was deleted",
                "assert": "404; no partial mutation; envelope error.code='NOT_FOUND'",
            },
        ])
    if gtype == "read-only":
        negs.append({
            "kind": "not_found_404",
            "label": "GET non-existent resource",
            "expected_status": 404,
            "setup": "navigate to URL with id that doesn't exist",
            "assert": "404 page or empty state; no white-screen",
        })
    negs.append({
        "kind": "rate_limit_429",
        "label": "burst traffic triggers rate limit",
        "expected_status": 429,
        "setup": "issue rapid repeated requests beyond burst limit",
        "assert": "429 with Retry-After header; subsequent OK after delay",
        "advisory": True,
    })
    return negs


def _parse_acceptance_criteria(goal: dict[str, Any]) -> list[str]:
    """Batch 36 R3: extract acceptance_criteria from goal frontmatter.

    Goal frontmatter may declare criteria in multiple shapes:
      - list[str]: ["criterion 1", "criterion 2"]
      - dict {"main": [...], "alternate": [...]}
      - prose string: "Criteria: A. B. C." (split on sentence punctuation)
      - alternate keys: acceptance_criteria, success_criteria, criteria
    Returns deduplicated non-empty list.
    """
    candidates = (
        goal.get("acceptance_criteria")
        or goal.get("success_criteria")
        or goal.get("criteria")
        or []
    )
    items: list[str] = []
    if isinstance(candidates, list):
        for c in candidates:
            if isinstance(c, str) and c.strip():
                items.append(c.strip())
            elif isinstance(c, dict):
                for v in c.values():
                    if isinstance(v, str) and v.strip():
                        items.append(v.strip())
    elif isinstance(candidates, dict):
        for v in candidates.values():
            if isinstance(v, list):
                items.extend(s.strip() for s in v if isinstance(s, str) and s.strip())
            elif isinstance(v, str) and v.strip():
                items.append(v.strip())
    elif isinstance(candidates, str):
        for chunk in re.split(r"(?<=[.!?])\s+|\n+", candidates):
            chunk = chunk.strip().lstrip("-•").strip()
            if chunk:
                items.append(chunk)
    # Dedup preserving order
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        if it not in seen:
            seen.add(it)
            out.append(it)
    return out


def _criteria_assertions(goal: dict[str, Any]) -> list[dict[str, str]]:
    """Batch 36 R3: convert acceptance_criteria to assertion[] entries.

    Each criterion becomes a structured assertion the spec body MUST verify
    with expect(). Validator verify-spec-criteria-coverage.py (separate)
    will cross-check spec body against this list.
    """
    out: list[dict[str, str]] = []
    for i, crit in enumerate(_parse_acceptance_criteria(goal), 1):
        out.append({
            "source": f"acceptance_criteria[{i}]",
            "check": crit,
        })
    return out


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


# B106 v4.70.0 (UAT bug root-cause investigation): FE form-submit coverage.
# Pre-B106 pipeline ran FE form submission against real backend ONLY at
# interactive UAT (STEP 5 accept) — first 4xx/422 catch was always a human.
# Top UAT failure classes (Explore agent C estimates ~50% catchable):
#   1. Form 4xx/422 silently swallowed — no page.on('response') capture
#   2. Success message/toast missing — codegen ignored mutation_evidence keyword
#   3. Redirect-after-submit broken — no waitForNavigation() assertion
# Fix: inject network_assertion + success_assertion metadata into lifecycle
# spec JSON during _step() for mutation stages. vg-test-codegen subagent
# reads these fields and emits corresponding Playwright code mechanically.
# verify-fe-form-submit-coverage.py validator BLOCKS at /vg:test + /vg:accept
# when generated specs miss the assertions.
_SUCCESS_KEYWORD_RE = re.compile(
    r"\b(success(?:fully)?|confirmed|created|updated|deleted|redirect(?:ed|s|ing)?|"
    r"navigat(?:e|ed|es|ing|ion)|goto|toast|message|notification|saved|published|"
    r"approved|rejected|banner|alert|status|confirmation|brought to)\b",
    re.IGNORECASE,
)
_NAVIGATION_URL_RE = re.compile(
    r"\b(?:redirect(?:ed|s|ing)?|navigat(?:e|ed|es|ing)|goto|takes you to|"
    r"brought to)\b[^.\n]{0,40}?(/[\w/{}:.-]+)",
    re.IGNORECASE,
)


def _extract_success_signals(text: str) -> dict[str, Any]:
    """B106: parse mutation_evidence (+ success_criteria fallback) for
    success-feedback signals. Returns dict with:
      - has_signal: True when any success keyword matches
      - keywords_matched: list of matched verbs (for diagnostic)
      - expect_navigation_to: extracted URL pattern (str) OR None
    """
    if not text:
        return {"has_signal": False, "keywords_matched": [], "expect_navigation_to": None}
    keywords = sorted({m.group(0).lower() for m in _SUCCESS_KEYWORD_RE.finditer(text)})
    nav_match = _NAVIGATION_URL_RE.search(text)
    nav_url = nav_match.group(1) if nav_match else None
    return {
        "has_signal": bool(keywords),
        "keywords_matched": keywords,
        "expect_navigation_to": nav_url,
    }


def _build_network_assertion(stage: str, endpoint: dict[str, str] | None) -> dict[str, Any] | None:
    """B106 Gate 1: inject page.on('response') capture metadata for mutation
    stages. Spec consumer (codegen) emits Playwright code that wraps the
    submit click in waitForResponse + asserts status < 400, OR if 4xx/5xx,
    requires an error toast be visible. Closes "form 4xx silently swallowed"
    bug class (Explore C estimate: 18-22% of UAT failures).
    """
    if stage not in {"create", "update", "delete"}:
        return None
    if not endpoint:
        return None
    return {
        "kind": "response_capture",
        "endpoint_method": endpoint.get("method"),
        "endpoint_path": endpoint.get("path"),
        "assert_status_lt": 400,
        "on_4xx_5xx_must_render_error_toast": True,
        "error_toast_selectors": [
            "[role=alert]",
            "[data-testid*=error]",
            ".error-banner",
            ".form-error",
            "[class*=Error]",
        ],
    }


# B110 v4.71.0 (UAT bug catch trilogy — accessibility branch):
# Inject `a11y_assertion` metadata for stages that exercise rendered UI.
# Codegen subagent reads this and emits `AxeBuilder({page}).analyze()` +
# critical/serious filter. Catches missing ARIA labels, color contrast,
# focus visibility, keyboard nav, screen-reader announcements.
_A11Y_STAGES = frozenset({
    "render_initial",
    "accessibility",
    "interaction_filter",
    "interaction_sort",
    "interaction_paginate",
    "read_after_create",
    "read_after_update",
    "visibility_check",
    "interaction_chain",
})


# B111 v4.71.1 — role-swap multi-actor replay. When a goal declares ≥2
# actors (via _infer_actors_v2 OR explicit actor_workflow), each mutation
# stage assigned to actor B must be preceded by a role-swap step:
# either close the actor-A context + open actor-B context, OR call a
# `loginAs(roleB)` fixture. Without this codegen runs the whole spec as
# the FIRST actor → role-B-only branches never execute.

def _build_role_swap_assertion(
    stage: str,
    goal: dict[str, Any],
    actor_id: str,
    actors: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """B111: when goal has multiple actors AND current step's actor differs
    from prior context, emit role-swap metadata. Codegen translates to
    `await loginAs('<actor>')` OR `await context.close(); ctx = await
    browser.newContext(...)`.

    Triggered for stages that perform user-visible actions (mutation +
    interaction) when there's a multi-actor workflow. Single-actor goals
    → returns None.
    """
    if len(actors) < 2:
        return None
    # Only emit on actionable stages — skip read_before stages which
    # codegen typically runs once at fixture setup
    if stage not in {
        "create", "update", "delete",
        "read_after_create", "read_after_update", "read_after_delete",
        "visibility_check", "interaction_chain",
        "cascade_check", "archive_visibility_check",
    }:
        return None
    if not actor_id:
        return None
    actor_ids = [a["id"] for a in actors]
    return {
        "kind": "role_swap",
        "active_actor": actor_id,
        "actors_in_workflow": actor_ids,
        "swap_strategy": (
            "preferred: dedicated browser context per actor via "
            "`browser.newContext()` + `loginAs(<actor>)`. Acceptable: "
            "single context + logout/login between actors."
        ),
        "fixture_hint": f"loginAs('{actor_id}') OR contextFor('{actor_id}')",
    }


def _build_a11y_assertion(stage: str, goal: dict[str, Any]) -> dict[str, Any] | None:
    """B110: inject a11y assertion metadata for render-bearing stages.

    Returns None when stage doesn't render UI (mutation-only without
    follow-up read) or when CONTEXT.md declares `a11y_waiver: true`.
    """
    if stage not in _A11Y_STAGES:
        return None
    # Per-goal opt-out via `a11y_waiver: true` in goal frontmatter
    if str(goal.get("a11y_waiver") or "").lower() in ("true", "yes", "1"):
        return None
    return {
        "kind": "axe_core_scan",
        "block_levels": ["critical", "serious"],
        "include_levels_in_report": ["critical", "serious", "moderate"],
        "rule_allowlist_path": "axe-allowlist.json",  # optional per-app file
        "selectors_focus": (
            "main, [role=main], form, [role=dialog], [role=alert]"
        ),
    }


def _build_success_assertion(stage: str, goal: dict[str, Any]) -> dict[str, Any] | None:
    """B106 Gate 2: inject success-message + navigation assertion metadata
    for mutation stages. Parses goal.mutation_evidence + success_criteria for
    keywords; codegen emits page.waitForURL OR locator visibility assertion.
    Closes "missing success feedback" + "redirect broken" classes (Explore C
    estimate: 20-28% of UAT failures combined).
    """
    if stage not in {"create", "update", "delete"}:
        return None
    haystack = " ".join([
        str(goal.get("mutation_evidence") or ""),
        str(goal.get("persistence_check") or ""),
        str(goal.get("success_criteria") or ""),
        str(goal.get("title") or ""),
    ])
    signals = _extract_success_signals(haystack)
    if not signals["has_signal"]:
        return None
    return {
        "kind": "post_submit_feedback",
        "expect_toast_or_status": True,
        "expect_navigation_to": signals["expect_navigation_to"],
        "wait_strategy": (
            "waitForURL when expect_navigation_to is set; else locator visibility"
        ),
        "success_selectors": [
            "[role=status]",
            "[data-testid*=success]",
            ".success-banner",
            ".toast-success",
            "[class*=Success]",
        ],
        "keywords_matched": signals["keywords_matched"],
    }


def _step(
    stage: str,
    goal: dict[str, Any],
    actor_id: str,
    contracts: list[dict[str, str]] | None = None,
    decisions: dict[str, dict[str, str]] | None = None,
    decision_refs: list[str] | None = None,
    actors: list[dict[str, Any]] | None = None,
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
        # Batch 36 R2: read-only stages for display/list/dashboard/filter goals
        "render_initial": f"Navigate to the page; assert layout renders, no console errors, key elements visible. Acceptance: {criteria}",
        "interaction_filter": "Apply filter control (dropdown/text/date/select); assert URL updates with filter param, list re-renders with subset, filter state persists on refresh.",
        "interaction_sort": "Click sort header (asc + desc); assert order changes, URL persists sort key+dir, multi-column sort respects priority.",
        "interaction_paginate": "Navigate next/prev/last/first/jump-to-page; assert URL page param updates, deep-link works (paste URL → correct page), out-of-range clamps gracefully.",
        "empty_state": "Filter/search to zero-result state; assert friendly empty UI (illustration/message), no error console, CTA visible if applicable.",
        "error_state_4xx": "Trigger 4xx/5xx response (invalid filter, unauthorized, server down); assert user-facing error message, no white-screen, retry CTA where applicable.",
        "loading_state": "Throttle network; assert skeleton/spinner shown during fetch, replaced by content on resolve, no layout shift after replace.",
        "accessibility": "Tab through interactive controls; assert focus visible, ARIA labels on inputs, screen-reader announcements for state changes, color contrast ≥4.5:1 on text.",
        # B65a (post-codex audit): FEATURE_CHAIN_STAGES descriptions. B62-pre
        # added the stages tuple but _step actions/evidence dicts didn't have
        # entries → KeyError when feature_chain goals processed.
        "visibility_check": "Navigate to a target view OUTSIDE the source view family (dashboard/audit log/sibling list); assert the just-mutated entity appears with correct count delta and the chain's expected_state per chain_steps[].",
        "interaction_chain": "Click the entity in the target view; assert detail view loads with mutation reflected end-to-end (status, badges, derived fields); verify chain_steps[].downstream_effects on this hop.",
        "cascade_check": "After update mutation, re-verify visibility in target view(s); assert status flip propagates to dashboard counters, badge updates, and any subscribed sibling views per chain_steps downstream_effects.",
        "archive_visibility_check": "After delete/archive, assert entity present in audit_log/archive list AND absent from primary list; verify archive_count +1 / active_count -1 per chain_steps downstream_effects.",
    }
    evidence = {
        "read_before": ["response envelope", "DB/query snapshot", "no stale fixture collision"],
        "create": ["2xx response or expected 4xx", "correlation/request id", "created resource id or emitted event id"],
        "read_after_create": ["fresh read response", "DB persisted fields", "audit/outbox row when applicable"],
        "update": ["2xx/expected 4xx response", "version/idempotency behavior", "actor authorization result"],
        # Batch 36 R2: read-only stage evidence
        "render_initial": ["screenshot", "console messages (zero errors)", "key element snapshot"],
        "interaction_filter": ["URL after filter applied", "filtered row count", "filter state in DOM"],
        "interaction_sort": ["URL with sort param", "first/last row id post-sort", "ARIA sort indicator"],
        "interaction_paginate": ["URL page param", "current page indicator", "row count per page"],
        "empty_state": ["empty UI screenshot", "console (no errors)", "empty-state DOM signature"],
        "error_state_4xx": ["error UI screenshot", "console message text", "HTTP response captured"],
        "loading_state": ["skeleton DOM snapshot", "network throttled response time", "post-resolve content"],
        "accessibility": ["axe-core findings", "keyboard nav trace", "screen-reader transcript"],
        "read_after_update": ["fresh read response", "event/webhook/queue capture when applicable", "no cross-tenant leakage"],
        "delete": ["cleanup mutation response or fixture cleanup receipt", "audit reason", "session/job/resource cleanup marker"],
        "read_after_delete": ["404/empty active list or terminal status", "revoked sessions/jobs", "cleanup confirmation"],
        # B65a: FEATURE_CHAIN_STAGES evidence entries (paired with actions above)
        "visibility_check": ["screenshot of target view", "entity_id presence in DOM",
                              "observed_count_delta vs pre-mutation"],
        "interaction_chain": ["detail route URL", "entity field values match source mutation",
                               "no console errors during navigation"],
        "cascade_check": ["target view re-snapshot", "dashboard counter post-update",
                          "audit_log entry for update"],
        "archive_visibility_check": ["primary list screenshot (entity absent)",
                                      "archive list screenshot (entity present)",
                                      "active_count -1, archive_count +1 deltas"],
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
    # Batch 36 R3: append acceptance_criteria assertions on key stages.
    # Apply criteria to read_after_* + render_initial stages (where user-
    # visible behavior is asserted). Skip raw mutation stages to avoid
    # double-counting (criteria better verified after persistence).
    if stage in {"read_after_create", "read_after_update", "read_after_delete",
                 "render_initial", "empty_state", "error_state_4xx",
                 "interaction_filter", "interaction_sort", "interaction_paginate"}:
        assertions.extend(_criteria_assertions(goal))
    step = {
        "name": stage,
        "stage": stage,
        "actor": actor_id,
        "endpoint": endpoint,
        "assertions": assertions,
        "action": actions[stage],
        "evidence": evidence[stage],
    }
    # B106 v4.70.0: inject pre-UAT FE form-submit coverage metadata
    network_assertion = _build_network_assertion(stage, endpoint)
    if network_assertion:
        step["network_assertion"] = network_assertion
        goal.setdefault("_b106_network_assertion_count", 0)
        goal["_b106_network_assertion_count"] += 1
    success_assertion = _build_success_assertion(stage, goal)
    if success_assertion:
        step["success_assertion"] = success_assertion
        goal.setdefault("_b106_success_assertion_count", 0)
        goal["_b106_success_assertion_count"] += 1
    # B110 v4.71.0: a11y assertion for render-bearing stages
    a11y_assertion = _build_a11y_assertion(stage, goal)
    if a11y_assertion:
        step["a11y_assertion"] = a11y_assertion
        goal.setdefault("_b110_a11y_assertion_count", 0)
        goal["_b110_a11y_assertion_count"] += 1
    # B111 v4.71.1: role-swap metadata for multi-actor goals
    role_swap = _build_role_swap_assertion(stage, goal, actor_id, actors or [])
    if role_swap:
        step["role_swap_assertion"] = role_swap
        goal.setdefault("_b111_role_swap_count", 0)
        goal["_b111_role_swap_count"] += 1
    return step


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
    # B97 v4.69.0 (issue #200): infer goal_class from emitted stages
    # when authors omitted the field. Eliminates 85/206 RCRURDR mismatch
    # BLOCK on PrintwayV3 Phase 8.2 R3.
    emitted_stages = _stages_for_goal(goal)
    declared_class = (goal.get("goal_class") or "").strip().lower()
    if declared_class:
        effective_goal_class = declared_class
        _b97_inferred = False
    else:
        inferred = _infer_goal_class(emitted_stages)
        effective_goal_class = inferred
        _b97_inferred = bool(inferred)
        if _b97_inferred:
            goal.setdefault("_b97_goal_class_inferred", inferred)
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
            _step(stage, goal, _stage_actor(stage, goal, actors), _contracts, _decisions, decision_refs, actors)
            for stage in _stages_for_goal(goal)
        ],
        # G6: artifact_capture reflects goal.artifact_kind
        "artifact_capture": _artifact_capture_v2(goal),
        # Batch 37 F3: first-class edge case variants per goal
        "edge_cases": _derive_edge_cases(goal),
        # Batch 37 F4: first-class negative path variants per goal
        "negative_specs": _derive_negative_specs(goal),
        # B65a (codex BLOCKER #2): persist chain_steps + enables so codegen
        # consumer (B65c) can iterate per chain step with test.step() inside
        # test.each(variants). Without this, chain_steps die at the producer.
        "chain_steps": goal.get("chain_steps") or [],
        "enables": goal.get("enables") or [],
        # B97 v4.69.0 (issue #200): emit effective goal_class (declared or
        # inferred). Pre-B97 emitted "" when authors omitted → downstream
        # validator dispatched to default RCRURDR → false-positive BLOCK.
        "goal_class": effective_goal_class,
        "cleanup": [
            {"target": fixture["id"], "action": fixture["cleanup"]}
            for fixture in reversed(fixture_dag)
        ],
        "generator_note": (
            "Generated from phase docs; executable tests must bind TS-XX to this "
            "goal and implement these steps. Edge cases + negative specs MUST be "
            "rendered as test.each([...]) variants. B65a: chain_steps + enables "
            "now persisted for feature_chain goals."
            + (f" | B97-inferred goal_class: {effective_goal_class}" if _b97_inferred else "")
        ),
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


def _audit_source_assertions(goals: list[dict[str, Any]]) -> dict[str, Any]:
    """B91 v4.67.0 (issue #197 F-CAI-03): audit goals for empty source
    assertion fields. Mutation goals require non-empty mutation_evidence +
    persistence_check; without these, read_after_* stages assert against
    empty contract → specs cannot verify side effects.

    Returns dict with `count`, `by_field`, `goal_ids` (first 20).
    Mutation goals only (read-only goals don't need persistence_check).
    """
    empty_evidence: list[str] = []
    empty_persistence: list[str] = []
    for g in goals:
        gtype = str(g.get("goal_type") or "").lower()
        if gtype == "read-only":
            continue
        # Mutation-class goals only
        if not (_needs_lifecycle(g) and gtype in {"mutation", "multi-actor", "workflow", ""}):
            continue
        if not _meaningful(g.get("mutation_evidence")):
            empty_evidence.append(str(g.get("id") or "?"))
        if not _meaningful(g.get("persistence_check")):
            empty_persistence.append(str(g.get("id") or "?"))
    return {
        "empty_mutation_evidence_count": len(empty_evidence),
        "empty_persistence_check_count": len(empty_persistence),
        "empty_mutation_evidence_goals": empty_evidence[:20],
        "empty_persistence_check_goals": empty_persistence[:20],
    }


def generate(phase_dir: Path, include_readonly: bool = False) -> dict[str, Any]:
    # B90 v4.66.1 (issue #197 F-CAI-08): track silently-dropped goals so
    # caller can warn instead of leaking 6 dropped goals as PrintwayV3
    # Phase 8.2 did (206 headings → 200 emitted, silent miss).
    dropped: list[dict[str, str]] = []
    goals = _parse_goals(phase_dir, dropped_log=dropped)
    heading_counts = _count_goal_headings(phase_dir)
    contracts = _parse_api_contracts(phase_dir)
    decisions = _parse_context_decisions(phase_dir)
    # B91 v4.67.0 (issue #197 F-CAI-03): source assertion audit before spec gen
    source_audit = _audit_source_assertions(goals)
    # B93 v4.67.2 (issue #197 F-CAI-07): decision coverage audit
    decision_audit = _decision_coverage(goals, decisions)
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
            # B90 F-CAI-08 diagnostics: raw heading counts + dropped log
            "heading_counts": heading_counts,
            "goals_dropped": dropped,
            "goals_dropped_count": len(dropped),
            # B91 v4.67.0 (issue #197 F-CAI-03): empty assertion audit
            "source_assertion_audit": source_audit,
            # B91 v4.67.0 (issue #197 F-CAI-01 + F-CAI-10): endpoint binding
            # diagnostics. Counts of fallback paths surfaced per-goal via
            # `_b91_*` tags; aggregate here for operator warning.
            "endpoint_binding_audit": {
                "slug_fallback_total": sum(
                    g.get("_b91_endpoint_slug_fallback_count", 0)
                    for g in selected
                ),
                "unmatched_total": sum(
                    g.get("_b91_endpoint_unmatched_count", 0)
                    for g in selected
                ),
                "contracts_empty_fallback_total": sum(
                    g.get("_b91_endpoint_contracts_empty_count", 0)
                    for g in selected
                ),
            },
            # B93 v4.67.2 (issue #197 F-CAI-07): decision coverage audit
            "decision_coverage_audit": decision_audit,
            # B94 v4.67.3 (issue #197 F-CAI-09): read-only auto-detect count
            "readonly_autodetected_count": sum(
                1 for g in selected
                if g.get("_b94_readonly_autodetected")
            ),
            # B97 v4.69.0 (issue #200): goal_class inference count
            "goal_class_inferred_count": sum(
                1 for g in selected
                if g.get("_b97_goal_class_inferred")
            ),
            # B106 v4.70.0: pre-UAT FE form-submit coverage audit
            "form_submit_coverage_audit": {
                "network_assertion_total": sum(
                    g.get("_b106_network_assertion_count", 0) for g in selected
                ),
                "success_assertion_total": sum(
                    g.get("_b106_success_assertion_count", 0) for g in selected
                ),
                "mutation_goals_with_network_check": sum(
                    1 for g in selected
                    if g.get("_b106_network_assertion_count", 0) > 0
                ),
                "mutation_goals_with_success_check": sum(
                    1 for g in selected
                    if g.get("_b106_success_assertion_count", 0) > 0
                ),
            },
            # B110 v4.71.0: a11y coverage audit
            "a11y_coverage_audit": {
                "a11y_assertion_total": sum(
                    g.get("_b110_a11y_assertion_count", 0) for g in selected
                ),
                "goals_with_a11y_check": sum(
                    1 for g in selected
                    if g.get("_b110_a11y_assertion_count", 0) > 0
                ),
            },
            # B111 v4.71.1: role-swap coverage audit
            "role_swap_coverage_audit": {
                "role_swap_assertion_total": sum(
                    g.get("_b111_role_swap_count", 0) for g in selected
                ),
                "multi_actor_goals_with_swap": sum(
                    1 for g in selected
                    if g.get("_b111_role_swap_count", 0) > 0
                ),
            },
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
    # B90 v4.66.1 (issue #197 F-CAI-08): surface silently-dropped goals to
    # stderr so operator catches the miss instead of shipping with sparse
    # coverage. Header-count comparison flags drift between TEST-GOALS.md
    # heading rows and `_parse_goal_block` accepted rows.
    dropped_count = summary.get("goals_dropped_count", 0)
    heading_counts = summary.get("heading_counts", {})
    expected_min = heading_counts.get("split_files", 0) + heading_counts.get("flat_headings", 0)
    if dropped_count or (expected_min and summary["goals_seen"] < expected_min):
        print(
            f"⚠ goal parse drift detected — "
            f"heading_counts={heading_counts} parsed={summary['goals_seen']} "
            f"dropped={dropped_count}.",
            file=sys.stderr,
        )
        for d in summary.get("goals_dropped", [])[:10]:
            print(f"  - source={d.get('source')} reason={d.get('reason')}",
                  file=sys.stderr)
    # B91 v4.67.0 (issue #197 F-CAI-03): warn on empty source assertions
    sa = summary.get("source_assertion_audit", {})
    if sa.get("empty_mutation_evidence_count") or sa.get("empty_persistence_check_count"):
        print(
            f"⚠ source assertion gaps — "
            f"empty mutation_evidence: {sa.get('empty_mutation_evidence_count')} goals, "
            f"empty persistence_check: {sa.get('empty_persistence_check_count')} goals. "
            f"read_after_* stages will assert against empty contract.",
            file=sys.stderr,
        )
        for gid in sa.get("empty_mutation_evidence_goals", [])[:5]:
            print(f"  - {gid}: empty mutation_evidence", file=sys.stderr)
        for gid in sa.get("empty_persistence_check_goals", [])[:5]:
            print(f"  - {gid}: empty persistence_check", file=sys.stderr)
    # B91 v4.67.0 (issue #197 F-CAI-01 / F-CAI-10): warn on endpoint binding gaps
    eba = summary.get("endpoint_binding_audit", {})
    if eba.get("unmatched_total") or eba.get("slug_fallback_total"):
        print(
            f"⚠ endpoint binding diagnostics — "
            f"unmatched={eba.get('unmatched_total')} "
            f"slug_fallback={eba.get('slug_fallback_total')} "
            f"contracts_empty_fallback={eba.get('contracts_empty_fallback_total')}. "
            f"Unmatched stages have endpoint=null (entity-anchor invariant — "
            f"avoids cross-resource pollution per B91 F-CAI-01).",
            file=sys.stderr,
        )
    # B93 v4.67.2 (issue #197 F-CAI-07): warn when decision coverage below threshold
    dca = summary.get("decision_coverage_audit", {})
    if dca.get("total_decisions") and not dca.get("passed", True):
        print(
            f"⚠ decision coverage below {dca['threshold']}% threshold — "
            f"{dca['bound_decisions']}/{dca['total_decisions']} "
            f"({dca['coverage_pct']}%) of CONTEXT.md decisions bound to goals. "
            f"{dca.get('unbound_count', 0)} unbound. "
            f"Advisory only — blueprint AI should add `decision_refs: [...]` "
            f"frontmatter to each goal or reference D-XX in goal body.",
            file=sys.stderr,
        )
        for d_id in dca.get("unbound", [])[:5]:
            print(f"  - unbound: {d_id}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
